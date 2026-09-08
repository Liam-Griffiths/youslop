"""Grounding a script in real search results before a word of it is written.

Claude Code's own WebSearch/WebFetch tools turned out not to work headlessly
(this took an afternoon of testing to confirm): the CLI's `--print` mode has
no one to answer the tool's permission prompt, so a call in that mode either
gets an honest denial or — worse, across every permission flag tried —
silently skips the tool and answers from memory with fabricated citations
instead. Real grounding here goes around that entirely: a local SearXNG
instance (`docker-compose.searxng.yml`) does the actual searching over plain
HTTP, no CLI tool-use involved, and Claude only ever sees pages that were
really fetched. `script_gen.py` uses `gather()`; nothing else in this module
writes narration.
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import threading
from typing import Callable

import httpx

from .config import SEARXNG_URL, USER_AGENT
from .llm import LLMError, MODEL_SCRIPT, MODEL_UTILITY, complete_json

Progress = Callable[[str], None]

_client_lock = threading.Lock()
_client: httpx.Client | None = None


def _client_for_web() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=httpx.Timeout(20.0, connect=8.0),
                follow_redirects=True,
            )
        return _client


def available() -> bool:
    return bool(SEARXNG_URL)


# ------------------------------------------------------------------- search
def search(query: str, count: int = 6) -> list[dict]:
    """SearXNG's results for one query: title, url, snippet. Never raises —
    a dead or unreachable instance just means no results, same as a stock
    archive that times out."""
    if not SEARXNG_URL:
        return []
    try:
        r = _client_for_web().get(f"{SEARXNG_URL}/search",
                                  params={"q": query, "format": "json"})
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    out = []
    for item in (data.get("results") or [])[:count]:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        out.append({"title": (item.get("title") or "").strip(), "url": url,
                    "snippet": (item.get("content") or "").strip()})
    return out


# --------------------------------------------------------------------- fetch
# A page is fetched with a plain GET and reduced to text with regexes rather
# than a real HTML parser — no new dependency, and a documentary source is
# usually server-rendered prose (Wikipedia, news, museum sites, court PDFs
# rendered as HTML), not the kind of JS-heavy page this would fail on.
_SCRIPT_STYLE = re.compile(
    r"<(script|style|noscript|template)[^>]*>.*?</\1>", re.I | re.S)
_BLOCK_BREAK = re.compile(r"</?(p|br|div|li|h[1-6]|tr|section|article)[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_BLANKLINES = re.compile(r"\n{3,}")
_ENTITIES = {"&amp;": "&", "&nbsp;": " ", "&quot;": '"', "&#39;": "'",
            "&lt;": "<", "&gt;": ">"}


def _html_to_text(html: str) -> str:
    text = _SCRIPT_STYLE.sub(" ", html)
    text = _BLOCK_BREAK.sub("\n", text)
    text = _TAG.sub(" ", text)
    for ent, ch in _ENTITIES.items():
        text = text.replace(ent, ch)
    text = _WS.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    # A nav menu is one short label per line ("Main page", "Log in", "Donate");
    # real prose runs long. Without this filter a Wikipedia fetch spends most
    # of its character budget on sidebar chrome before reaching the article.
    lines = [l for l in lines if len(l) >= 45 or l.endswith((".", "!", "?", '"'))]
    text = "\n".join(lines)
    return _BLANKLINES.sub("\n\n", text).strip()


def fetch_page(url: str, max_chars: int = 6000) -> str:
    """A page's readable text, best-effort. "" on anything that goes wrong —
    a paywall, a timeout, a non-HTML response are all just "nothing here"."""
    try:
        r = _client_for_web().get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            return ""
        return _html_to_text(r.text)[:max_chars]
    except Exception:
        return ""


# ---------------------------------------------------------------- the dossier
def _propose_queries(idea: str, count: int = 6) -> list[str]:
    prompt = f"""A creator wants a documentary-style video about this:

\"\"\"{idea}\"\"\"

Propose {count} web search queries that would find the concrete, checkable
facts a script about this would need: names, dates, numbers, direct quotes,
official or court records, and where the record is disputed or thin. Order
from most specific to more general. Plain search-engine phrasing — no
boolean operators, no quotes around phrases.

Return JSON: a list of {count} strings."""
    out = complete_json(prompt, model=MODEL_UTILITY, timeout=180,
                        require=lambda v: isinstance(v, list) and bool(v),
                        require_hint="Return a bare JSON list of query strings.")
    return [str(q).strip() for q in out if str(q).strip()][:count]


def _spread_across_domains(hits: list[dict], limit: int) -> list[dict]:
    """Up to `limit` hits, drawing round-robin across domains.

    A search that comes back ten deep on one site and nothing else would
    otherwise crowd out everything but that one site's account of things.
    """
    by_domain: dict[str, list[dict]] = {}
    for h in hits:
        domain = h["url"].split("/")[2] if "://" in h["url"] else h["url"]
        by_domain.setdefault(domain, []).append(h)
    picked: list[dict] = []
    row = 0
    while len(picked) < limit and row < 4:
        for domain in by_domain:
            if row < len(by_domain[domain]):
                picked.append(by_domain[domain][row])
                if len(picked) >= limit:
                    break
        row += 1
    return picked


def gather(idea: str, progress: Progress = lambda m: None) -> dict:
    """Search, fetch and synthesise a dossier of sourced facts for `idea`.

    Returns {} — not an error — when SEARXNG_URL isn't set, nothing came
    back, or the synthesis call itself fails. `script_gen.generate` treats an
    empty dossier as "write without grounding", the same as before this
    module existed, rather than failing the whole script over it.
    """
    if not available():
        return {}

    queries = _propose_queries(idea)
    if not queries:
        return {}
    progress(f"Researching: {len(queries)} search quer"
             f"{'y' if len(queries) == 1 else 'ies'}")

    seen: set[str] = set()
    hits: list[dict] = []
    for q in queries:
        for r in search(q):
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            hits.append(r)
    if not hits:
        progress("Research found nothing — writing without grounding")
        return {}
    progress(f"{len(hits)} unique result(s); fetching the most promising")

    picked = _spread_across_domains(hits, limit=14)
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        sources = list(pool.map(fetch_page, [h["url"] for h in picked]))
    for h, text in zip(picked, sources):
        h["text"] = text
    picked = [h for h in picked if h["text"] or h["snippet"]]
    if not picked:
        progress("Nothing fetched cleanly — writing without grounding")
        return {}

    listing = "\n\n".join(
        f'[{i + 1}] {h["title"]}\n{h["url"]}\n{(h["text"] or h["snippet"])[:2500]}'
        for i, h in enumerate(picked)
    )
    progress(f"Synthesising a dossier from {len(picked)} source(s)")

    prompt = f"""Below is raw material fetched from the web for a documentary
video about:

\"\"\"{idea}\"\"\"

SOURCES:
{listing}

Extract the concrete, checkable facts a script could be built on: names,
dates, numbers, direct quotes, and what these sources agree or disagree on.
Every fact must be attributable to one of the numbered sources above — do not
add anything the sources do not say, even something you are otherwise
confident is true.

Return JSON:
{{"facts": [{{"claim": "the fact, plainly stated", "date": "" or a date,
  "source": "that source's name or publication", "url": "copied exactly from
  the source list above", "confidence": "high"|"medium"|"low"}}],
 "open_questions": ["things these sources leave unclear or contradict each
   other on"],
 "corrections": ["anything the creator's own idea states that these sources
   contradict"]}}"""
    try:
        dossier = complete_json(
            prompt, model=MODEL_SCRIPT, timeout=600,
            require=lambda v: isinstance(v, dict) and bool(v.get("facts")),
            require_hint='The object needs a "facts" array.')
    except LLMError as exc:
        progress(f"Research synthesis failed ({str(exc)[:100]}) — "
                 "writing without grounding")
        return {}

    if not isinstance(dossier, dict):
        return {}
    dossier.setdefault("facts", [])
    dossier.setdefault("open_questions", [])
    dossier.setdefault("corrections", [])
    dossier["queries"] = queries
    dossier["source_count"] = len(picked)
    progress(f"Research done: {len(dossier['facts'])} fact(s), "
             f"{len(dossier['open_questions'])} open question(s)")
    return dossier

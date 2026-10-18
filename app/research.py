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

Two depths, chosen by `YOUSLOP_RESEARCH_MODE`:

- **quick** — one pass: propose queries, search, fetch, synthesise.
- **deep** — Claude's research mode: a loop of rounds in which Claude reads
  what it has, asks for more searches or pages, and stops when it is satisfied.
  The loop is driven here, not by a tool API, so it works on both the CLI and
  API backends: each round is one JSON-only call that says what to do next, and
  this module does it and feeds the results back.
"""
from __future__ import annotations

import concurrent.futures as cf
import html as html_lib
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import (
    ANTHROPIC_API_KEY, BRAVE_SEARCH_KEY, RESEARCH_MODE, SEARCH_BACKEND,
    SEARXNG_URL, USER_AGENT,
)
from .config import OLLAMA_CONTEXT
from .llm import (
    LLMError, MODEL_SCRIPT, MODEL_UTILITY, _api_model_id, complete,
    complete_json, resolve_backend,
)

Progress = Callable[[str], None]
log = logging.getLogger("youslop.research")

# Search sites answer a bot's request with a challenge or a rate limit, so the
# searches identify as a browser. Page fetches keep the app's own contact
# string, which is what USER_AGENT is for.
SEARCH_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.5 Safari/605.1.15")

# Deep mode's budget. Enough rounds to follow up a gap or two, few enough that
# a run stays in minutes rather than becoming an open-ended crawl.
DEEP_ROUNDS = 5
DEEP_SEARCHES_PER_ROUND = 3
DEEP_READS_PER_ROUND = 4
DEEP_MAX_SOURCES = 20

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


def search_backends() -> list[str]:
    """The backends a search tries, in order, until one returns results.

    An explicit choice is just that backend, and nothing else — with its
    prerequisite missing the list is empty, not a silent fallback. "auto" is a
    chain: a SearXNG instance the user runs, a Brave key, the free no-key
    search, and Claude's own search last, because it is the only one billed
    per search. So a fresh install with only Claude Code still researches, and
    a SearXNG URL that is set but not answering does not switch research off.
    """
    if SEARCH_BACKEND == "searxng":
        return ["searxng"] if SEARXNG_URL else []
    if SEARCH_BACKEND == "brave":
        return ["brave"] if BRAVE_SEARCH_KEY else []
    if SEARCH_BACKEND == "claude":
        return ["claude"] if ANTHROPIC_API_KEY else []
    if SEARCH_BACKEND == "scrape":
        return ["scrape"]
    chain = []
    if SEARXNG_URL:
        chain.append("searxng")
    if BRAVE_SEARCH_KEY:
        chain.append("brave")
    chain.append("scrape")
    if ANTHROPIC_API_KEY:
        chain.append("claude")
    return chain


def search_backend() -> str:
    """The first backend a search would try, for logs and Settings."""
    chain = search_backends()
    return chain[0] if chain else "none"


def available() -> bool:
    return bool(search_backends())


# ------------------------------------------------------------------- search
def search(query: str, count: int = 6) -> list[dict]:
    """Results for one query: title, url, snippet, from the first backend in
    the chain that has any. Never raises — a backend that is down or
    unreachable is just a backend with no results."""
    chain = search_backends()
    for n, backend in enumerate(chain):
        found = _run_backend(backend, query, count)
        if found:
            return found
        if n + 1 < len(chain):
            log.info("search %r: %s had nothing, trying %s",
                     query, backend, chain[n + 1])
    return []


def _run_backend(backend: str, query: str, count: int) -> list[dict]:
    if backend == "searxng":
        return _search_searxng(query, count)
    if backend == "claude":
        return _search_claude(query, count)
    if backend == "brave":
        return _search_brave(query, count)
    if backend == "scrape":
        return _search_keyless(query, count)
    return []


# Each site gets its own spacing, so a burst of searches cannot trip its rate
# limit. Brave allows one request a second on the free tier; DuckDuckGo starts
# answering 202 (a bot challenge, not results) when a burst comes in; the
# others are gentler still.
_HOST_GAP = {"brave": 1.1, "duckduckgo": 5.0, "bing": 3.0, "wikipedia": 1.0}
_host_lock = threading.Lock()
_host_next: dict[str, float] = {}


def _polite(host: str) -> None:
    """Block until this site may be asked again. Reserves the slot under the
    lock, so two threads cannot both think they are first."""
    with _host_lock:
        now = time.monotonic()
        start = max(now, _host_next.get(host, 0.0))
        _host_next[host] = start + _HOST_GAP[host]
    if start > now:
        time.sleep(start - now)


def _get(url: str, host: str, params: dict | None = None,
         headers: dict | None = None, tries: int = 3) -> httpx.Response | None:
    """A GET that waits its turn, and retries when the site says "not now"
    (202/429/503). None on anything else, logged, never raised."""
    for attempt in range(tries):
        _polite(host)
        try:
            r = _client_for_web().get(url, params=params, headers=headers or {})
        except Exception as exc:
            log.warning("%s: request failed: %s", host, exc)
            return None
        if r.status_code == 200:
            return r
        if r.status_code in (202, 429, 503) and attempt < tries - 1:
            time.sleep(10 * (attempt + 1))
            continue
        log.warning("%s: HTTP %s for %r", host, r.status_code, params or url)
        return None
    return None


def _search_brave(query: str, count: int = 6) -> list[dict]:
    """Brave Search's web results. Needs BRAVE_SEARCH_API_KEY; never raises."""
    if not BRAVE_SEARCH_KEY:
        return []
    _polite("brave")
    try:
        r = _client_for_web().get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count},
            headers={"X-Subscription-Token": BRAVE_SEARCH_KEY,
                     "Accept": "application/json"},
        )
        r.raise_for_status()
        results = (r.json().get("web") or {}).get("results") or []
    except Exception:
        return []
    return [{"title": (x.get("title") or "").strip(),
             "url": (x.get("url") or "").strip(),
             "snippet": (x.get("description") or "").strip()}
            for x in results[:count] if x.get("url")]


# DuckDuckGo's no-JavaScript results page. Each hit is a result__a link, with
# its target wrapped in a redirect (/l/?uddg=<encoded url>) and a snippet in
# result__snippet. A plain scrape like this breaks when DuckDuckGo changes its
# markup, and it returns nothing when DuckDuckGo serves a bot challenge; both
# just mean no results, the same as an archive that is down.
_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


def _search_keyless(query: str, count: int = 6) -> list[dict]:
    """The no-key search: DuckDuckGo's HTML results, Bing News for fresh
    stories, and Wikipedia's own search for the reference articles. Each query
    asks all three, because each misses things the others find — a death
    from last week is in the news, not yet in an encyclopaedia. Duplicates
    are merged by URL; a source that fails just contributes nothing."""
    hits: list[dict] = []
    per_source: dict[str, int] = {}
    for name, fn in (("duckduckgo", _search_ddg), ("bing", _search_bing_news),
                     ("wikipedia", _search_wikipedia)):
        found = fn(query, count)
        per_source[name] = len(found)
        for h in found:
            if not any(x["url"] == h["url"] for x in hits):
                hits.append(h)
    log.info("search %r: duckduckgo %d, bing news %d, wikipedia %d",
             query, per_source["duckduckgo"], per_source["bing"],
             per_source["wikipedia"])
    return hits


def _search_ddg(query: str, count: int = 6) -> list[dict]:
    """DuckDuckGo's no-JavaScript results page. Never raises."""
    r = _get("https://html.duckduckgo.com/html/", "duckduckgo",
             params={"q": query}, headers={"User-Agent": SEARCH_UA})
    if r is None:
        return []
    html = r.text
    snippets = [_inline_text(m) for m in _DDG_SNIPPET.findall(html)]
    out: list[dict] = []
    for i, m in enumerate(_DDG_RESULT.finditer(html)):
        url = _ddg_target(m.group(1))
        if not url or any(h["url"] == url for h in out):
            continue
        out.append({"title": _inline_text(m.group(2)), "url": url,
                    "snippet": snippets[i] if i < len(snippets) else ""})
        if len(out) >= count:
            break
    return out


def _search_bing_news(query: str, count: int = 6) -> list[dict]:
    """Bing News's RSS feed: recent articles with their publication dates in
    the snippet. Each item's link is a Bing redirect that carries the real
    article address in its `url` parameter. Never raises."""
    r = _get("https://www.bing.com/news/search", "bing",
             params={"q": query, "format": "rss"},
             headers={"User-Agent": SEARCH_UA})
    if r is None:
        return []
    try:
        items = ET.fromstring(r.content).findall("./channel/item")
    except ET.ParseError as exc:
        log.warning("bing news: unreadable feed: %s", exc)
        return []
    out: list[dict] = []
    for item in items:
        link = (item.findtext("link") or "").strip()
        target = parse_qs(urlparse(link).query).get("url", [""])[0]
        if not target.startswith(("http://", "https://")):
            continue
        if any(h["url"] == target for h in out):
            continue
        date = (item.findtext("pubDate") or "").strip()
        snippet = _inline_text(item.findtext("description") or "")
        out.append({"title": _inline_text(item.findtext("title") or ""),
                    "url": target,
                    "snippet": f"{date}. {snippet}".strip(". ")})
        if len(out) >= count:
            break
    return out


WIKI_MAX_CHARS = 12000


def _wikipedia_article(title: str) -> str:
    """The full plain text of an English Wikipedia article, from its own API
    rather than scraped HTML: one request, no navigation chrome, and redirects
    followed. "" if the article cannot be read. Never raises."""
    r = _get("https://en.wikipedia.org/w/api.php", "wikipedia",
             params={"action": "query", "prop": "extracts", "explaintext": 1,
                     "redirects": 1, "titles": title, "format": "json"})
    if r is None:
        return ""
    try:
        pages = (r.json().get("query") or {}).get("pages") or {}
    except ValueError:
        return ""
    page = next(iter(pages.values()), {})
    return (page.get("extract") or "")[:WIKI_MAX_CHARS]


def _is_wikipedia(url: str) -> bool:
    return url.startswith("https://en.wikipedia.org/wiki/")


def _fetch_source(hit: dict) -> str:
    """A hit's text: the article itself for Wikipedia, the page for anything
    else. A hit that already carries text is not fetched again."""
    if hit.get("text"):
        return hit["text"]
    if _is_wikipedia(hit["url"]):
        title = unquote(hit["url"][len("https://en.wikipedia.org/wiki/"):]).replace("_", " ")
        return _wikipedia_article(title)
    return fetch_page(hit["url"])


def _search_wikipedia(query: str, count: int = 6) -> list[dict]:
    """English Wikipedia's search API. The page text itself is fetched later
    like any other source. Never raises."""
    r = _get("https://en.wikipedia.org/w/api.php", "wikipedia",
             params={"action": "query", "list": "search", "srsearch": query,
                     "srlimit": count, "format": "json"})
    if r is None:
        return []
    try:
        results = (r.json().get("query") or {}).get("search") or []
    except ValueError:
        return []
    return [{"title": item.get("title", ""),
             "url": "https://en.wikipedia.org/wiki/"
                    + item.get("title", "").replace(" ", "_"),
             "snippet": _inline_text(item.get("snippet", ""))}
            for item in results[:count] if item.get("title")]


def _inline_text(fragment: str) -> str:
    """A title or snippet fragment as plain text. Unlike _html_to_text this keeps
    short lines, which a search title nearly always is."""
    text = html_lib.unescape(_TAG.sub("", fragment))
    return _WS.sub(" ", text).strip()


def _ddg_target(href: str) -> str:
    """The real destination behind a DuckDuckGo result link, or "" if the link
    is not an outside web page."""
    href = html_lib.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href:
        target = parse_qs(urlparse(href).query).get("uddg", [""])[0]
        href = target
    if not href.startswith(("http://", "https://")):
        return ""
    if urlparse(href).hostname and urlparse(href).hostname.endswith("duckduckgo.com"):
        return ""           # DuckDuckGo's own ad and settings links, not results
    return href


def _search_claude(query: str, count: int = 6) -> list[dict]:
    """One query through Claude's server-side web search. Anthropic runs the
    search and returns the results inside the same response, so nothing here
    needs SearXNG or a tool loop. Only the result list is kept: the page text
    comes from fetch_page(), the same as for SearXNG hits, so the dossier
    never leans on Claude's own summary of a page.

    Needs an API key — the CLI backend cannot run server-side search headlessly
    (see the module note above)."""
    if not ANTHROPIC_API_KEY:
        return []
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=60.0)
        response = client.messages.create(
            model=_api_model_id(MODEL_UTILITY),
            max_tokens=1024,
            tools=[{"type": "web_search_20260209", "name": "web_search",
                    "max_uses": 1}],
            messages=[{"role": "user", "content":
                       f"Run one web search for exactly this query and nothing "
                       f"else: {query}"}],
        )
    except Exception:
        return []
    out = []
    for block in response.content:
        if block.type != "web_search_tool_result" or not isinstance(block.content, list):
            continue
        for item in block.content:
            url = (getattr(item, "url", "") or "").strip()
            if not url or any(h["url"] == url for h in out):
                continue
            out.append({"title": (getattr(item, "title", "") or "").strip(),
                        "url": url, "snippet": ""})
    return out[:count]


def _search_searxng(query: str, count: int = 6) -> list[dict]:
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


def _source_blocks(sources: list[dict]) -> list[str]:
    return [f'[{i + 1}] {h["title"]}\n{h["url"]}\n{(h["text"] or h["snippet"])[:4000]}'
            for i, h in enumerate(sources)]


def _chunk_budget() -> int | None:
    """How many characters of source text one call may carry, or None when the
    backend's window is large enough to take them all. Only the local model
    has a window that small. Half the window is kept back for the instructions
    and the reply; about four characters make a token."""
    if resolve_backend() != "ollama":
        return None
    return OLLAMA_CONTEXT * 4 // 2


_SUMMARY_PROMPT = """Below are numbered sources fetched from the web for a
documentary video about:

\"\"\"{idea}\"\"\"

SOURCES:
{listing}

Write a dense summary of every concrete, checkable fact in these sources:
names, dates, numbers, places, direct quotes, and where sources disagree.
For each point, keep the source number in square brackets and copy the
source's URL. Add nothing the sources do not say. Plain text, no preamble."""


def _summarise_in_chunks(idea: str, blocks: list[str], budget: int,
                         progress: Progress) -> list[str]:
    """Summaries of `blocks`, each covering as many sources as fit in `budget`
    characters. A chunk whose call fails is dropped and logged, not fatal."""
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        if current and size + len(block) > budget:
            chunks.append(current)
            current, size = [], 0
        current.append(block)
        size += len(block)
    if current:
        chunks.append(current)

    summaries: list[str] = []
    for n, chunk in enumerate(chunks, 1):
        progress(f"Summarising the sources, part {n} of {len(chunks)}")
        prompt = _SUMMARY_PROMPT.format(idea=idea, listing="\n\n".join(chunk))
        try:
            summaries.append(complete(prompt, model=MODEL_UTILITY, timeout=600))
        except LLMError as exc:
            log.warning("research: summary part %d of %d failed: %s",
                        n, len(chunks), exc)
    return summaries


def _synthesise(idea: str, sources: list[dict], progress: Progress) -> dict:
    """Facts, open questions and corrections from fetched sources, each fact
    tied to one of them. {} when the synthesis call itself fails — the caller
    writes without grounding rather than failing the whole script.

    On the local model, sources that would overflow its window are first
    summarised in chunks, and the dossier is written from those summaries. The
    summaries keep each source's number and URL, so facts still cite sources."""
    blocks = _source_blocks(sources)
    label, listing = "SOURCES", "\n\n".join(blocks)
    budget = _chunk_budget()
    if budget is not None and len(listing) > budget:
        progress(f"{len(sources)} sources are too much for the local model's "
                 "window — summarising them first")
        summaries = _summarise_in_chunks(idea, blocks, budget, progress)
        if not summaries:
            progress("Summarising the sources failed — writing without grounding")
            return {}
        label = "SUMMARIES OF THE SOURCES (each point keeps its source number and URL)"
        listing = "\n\n".join(summaries)
    progress(f"Synthesising a dossier from {len(sources)} source(s)")

    prompt = f"""Below is raw material fetched from the web for a documentary
video about:

\"\"\"{idea}\"\"\"

{label}:
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
    return dossier


def _finish(dossier: dict, queries: list[str], sources: list[dict],
            progress: Progress) -> dict:
    if not dossier:
        return {}
    dossier["queries"] = queries
    dossier["source_count"] = len(sources)
    progress(f"Research done: {len(dossier['facts'])} fact(s), "
             f"{len(dossier['open_questions'])} open question(s)")
    return dossier


def gather(idea: str, progress: Progress = lambda m: None, mode: str = "") -> dict:
    """Search, fetch and synthesise a dossier of sourced facts for `idea`.

    Returns {} — not an error — when no search backend is available, nothing came
    back, or the synthesis call itself fails. `script_gen.generate` treats an
    empty dossier as "write without grounding", the same as before this
    module existed, rather than failing the whole script over it.
    """
    if not available():
        return {}
    if (mode or RESEARCH_MODE) == "deep":
        return gather_deep(idea, progress)

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
        log.warning("research: %d quer%s, no results from %s — writing without "
                    "grounding", len(queries), "y" if len(queries) == 1 else "ies",
                    search_backend())
        progress("Research found nothing — writing without grounding")
        return {}
    progress(f"{len(hits)} unique result(s); fetching the most promising")

    picked = _spread_across_domains(hits, limit=14)
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        texts = list(pool.map(_fetch_source, picked))
    for h, text in zip(picked, texts):
        h["text"] = text
    picked = [h for h in picked if h["text"] or h["snippet"]]
    if not picked:
        progress("Nothing fetched cleanly — writing without grounding")
        return {}

    dossier = _synthesise(idea, picked, progress)
    return _finish(dossier, queries, picked, progress)


# ------------------------------------------------------------- deep research
def _plan_round(idea: str, queries: list[str], candidates: list[dict],
                sources: list[dict], rounds_left: int) -> dict:
    """One planning call: what to search for next, which results to read,
    or that the reading so far is enough. Shows Claude the unread results by
    id and the pages already read, trimmed — the full text is for synthesis."""
    unread = [f"C{i + 1} | {c['title']} | {c['url']} | {c['snippet'][:200]}"
              for i, c in enumerate(candidates) if not c.get("attempted")]
    read = [f"S{i + 1} | {s['title']} | {s['url']} | {s['text'][:300]}"
            for i, s in enumerate(sources)]
    prompt = f"""You are researching for a documentary-style video about:

\"\"\"{idea}\"\"\"

Gather concrete, checkable facts — names, dates, numbers, direct quotes,
official or court records — and find where the record is disputed or thin.
Work like a careful researcher: read the most promising pages, notice what is
still missing, then search for exactly that.

SEARCHES RUN SO FAR:
{chr(10).join("- " + q for q in queries) or "(none)"}

UNREAD SEARCH RESULTS (id | title | url | snippet):
{chr(10).join(unread) or "(none)"}

PAGES READ SO FAR (id | title | url | opening):
{chr(10).join(read) or "(none)"}

Rounds left after this one: {rounds_left}. Per round you may run up to
{DEEP_SEARCHES_PER_ROUND} new searches and read up to {DEEP_READS_PER_ROUND}
unread results.

Return JSON:
{{"search": ["new query", ...],
 "read": ["C3", ...],
 "done": false}}

"search": plain search-engine phrasing, aimed at a gap; [] if none needed.
"read": ids from UNREAD SEARCH RESULTS only; [] if none.
"done": true once the pages read so far cover the main claims well enough to
write from. Do not repeat a search already run."""
    return complete_json(
        prompt, model=MODEL_SCRIPT, timeout=300,
        require=lambda v: isinstance(v, dict) and "done" in v,
        require_hint='The object needs "search", "read" and "done" keys.')


def _ids(values, prefix: str, limit: int) -> list[int]:
    """'C3' → 2 (zero-based), keeping only well-formed ids of that prefix."""
    out: list[int] = []
    for v in values if isinstance(values, list) else []:
        m = re.fullmatch(rf"\s*{prefix}(\d+)\s*", str(v), re.I)
        if m and 1 <= int(m.group(1)) <= limit and int(m.group(1)) - 1 not in out:
            out.append(int(m.group(1)) - 1)
    return out


def gather_deep(idea: str, progress: Progress = lambda m: None) -> dict:
    """Claude's research mode: rounds of plan → search → read, then one
    synthesis over everything read. Same return shape as `gather()`, so the
    script writer and the Sources panel do not know which depth ran."""
    queries: list[str] = []
    candidates: list[dict] = []   # every search hit, in the order found
    sources: list[dict] = []      # the ones read and worth keeping

    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for rnd in range(1, DEEP_ROUNDS + 1):
            rounds_left = DEEP_ROUNDS - rnd
            try:
                plan = _plan_round(idea, queries, candidates, sources, rounds_left)
            except LLMError as exc:
                progress(f"Research planning stopped ({str(exc)[:100]}) — "
                         "using what was read so far")
                break

            new_queries = []
            for q in plan.get("search") or []:
                q = str(q).strip()
                if q and q not in queries and q not in new_queries:
                    new_queries.append(q)
            new_queries = new_queries[:DEEP_SEARCHES_PER_ROUND]
            queries += new_queries

            known = {c["url"] for c in candidates}
            for q in new_queries:
                for r in search(q):
                    if r["url"] not in known:
                        known.add(r["url"])
                        candidates.append(r)

            room = max(0, DEEP_MAX_SOURCES - len(sources))
            chosen = [candidates[i] for i in _ids(plan.get("read"), "C", len(candidates))
                      if not candidates[i].get("attempted")]
            # The reference article is read once, every run, whatever the planner
            # asked for: it is the one source that is written to be complete.
            wiki = next((c for c in candidates
                         if _is_wikipedia(c["url"]) and not c.get("attempted")), None)
            if wiki is not None and wiki not in chosen:
                chosen.insert(0, wiki)
            to_read = chosen[:min(DEEP_READS_PER_ROUND, room)]
            for c in to_read:
                c["attempted"] = True
            texts = list(pool.map(_fetch_source, to_read))
            for c, text in zip(to_read, texts):
                c["text"] = text
                if text or c["snippet"]:
                    sources.append(c)

            progress(f"Round {rnd}: {len(new_queries)} search(es), "
                     f"{len(to_read)} page(s) read — {len(sources)} source(s) so far")
            if plan.get("done") is True or len(sources) >= DEEP_MAX_SOURCES:
                break
            if not new_queries and not to_read:
                break       # nothing new to ask or read: it has stalled

    if not sources:
        log.warning("deep research: %d quer%s, no readable sources from %s — "
                    "writing without grounding", len(queries),
                    "y" if len(queries) == 1 else "ies", search_backend())
        progress("Research found nothing readable — writing without grounding")
        return {}

    dossier = _synthesise(idea, sources, progress)
    return _finish(dossier, queries, sources, progress)

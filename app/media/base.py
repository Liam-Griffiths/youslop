"""Shared HTTP client, scoring and the provider interface."""
from __future__ import annotations

import re
import threading
import time
from typing import Protocol

import httpx

from ..config import USER_AGENT
from ..schema import MediaCandidate

_client_lock = threading.Lock()
_client: httpx.Client | None = None


def client() -> httpx.Client:
    """One shared connection-pooled client for every provider."""
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
            )
        return _client


# Public archives are a shared resource and they rate limit hard. Wikimedia will
# start returning "too many requests" within seconds of an unthrottled fan-out,
# which reads as "no results" rather than as an error. Each provider gets a
# concurrency cap and a minimum gap between requests.
#   (max_concurrent, min_seconds_between_requests)
_LIMITS = {
    "wikimedia": (1, 0.34),
    "loc": (1, 0.30),
    "met": (2, 0.12),
    "nypl": (1, 0.25),
    "openverse": (2, 0.20),
    "pexels": (3, 0.05),
    "pixabay": (3, 0.05),
    "giphy": (3, 0.08),
    "storyblocks": (2, 0.10),
    # Nominatim's own usage policy states this limit explicitly: at most one
    # request a second. The tile servers are more permissive, but a mosaic
    # fetches a whole grid at once, and there is no reason to hit either any
    # harder than the archives above already are.
    "nominatim": (1, 1.0),
    "osm-tile": (4, 0.05),
    "esri": (6, 0.02),
}


class _Limiter:
    def __init__(self, concurrency: int, interval: float) -> None:
        self.sem = threading.Semaphore(concurrency)
        self.interval = interval
        self.lock = threading.Lock()
        self.next_at = 0.0

    def __enter__(self):
        self.sem.acquire()
        with self.lock:
            wait = self.next_at - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.next_at = time.monotonic() + self.interval
        return self

    def __exit__(self, *exc):
        self.sem.release()


_LIMITERS: dict[str, _Limiter] = {}
_LIM_GUARD = threading.Lock()


def throttle(provider: str) -> _Limiter:
    with _LIM_GUARD:
        if provider not in _LIMITERS:
            _LIMITERS[provider] = _Limiter(*_LIMITS.get(provider, (3, 0.1)))
        return _LIMITERS[provider]


def get_json(url: str, provider: str, retries: int = 2, **kw):
    """Rate-limited GET with backoff. Returns None only after real failures."""
    delay = 1.2
    for attempt in range(retries + 1):
        with throttle(provider):
            try:
                r = client().get(url, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"{r.status_code}", request=r.request, response=r)
                if r.status_code != 200:
                    return None
                return r.json()
            except Exception:
                if attempt == retries:
                    return None
        time.sleep(delay)      # back off outside the limiter, not holding it
        delay *= 2.2
    return None


class Provider(Protocol):
    name: str
    kinds: tuple[str, ...]

    def available(self) -> bool: ...
    def search(self, query: str, kind: str, limit: int) -> list[MediaCandidate]: ...


# ------------------------------------------------------------------- filtering
# Wikimedia in particular is full of these, and none of them belong in a doc.
_JUNK = re.compile(
    r"\b(logo|icon|coat of arms|flag of|barnstar|wikimedia|wikipedia|commons|"
    r"symbol|emblem|seal of|template|userbox|question book|ambox|edit-|"
    r"disambig|stub|padlock|crystal clear|nuvola|gnome-|oojs|placeholder|"
    r"signature|blank|sound-icon|speaker|qr code)\b",
    re.I,
)
_BAD_EXT = re.compile(r"\.(svg|gif|xcf|webp\?|tif|tiff)$", re.I)

_STOP = {
    "the", "a", "an", "of", "in", "on", "at", "and", "or", "to", "for", "with",
    "from", "by", "his", "her", "their", "its", "photo", "photograph", "image",
}


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in _STOP and len(w) > 2}


def is_junk(title: str, url: str) -> bool:
    return bool(_JUNK.search(title or "")) or bool(_BAD_EXT.search((url or "").split("?")[0]))


# These providers match loosely across all their metadata, so they always return
# *something*. Without a relevance gate the Met will happily answer an Antarctic
# query with a Renaissance altarpiece. Pixabay and Pexels belong here for the
# same reason, just a different flavour of it: both are modern stock-photo
# libraries with essentially no historical content, searched by matching a
# query against user-submitted tags — so a query this app actually sends
# ("Ernest Shackleton Endurance 1915") comes back with whatever generic "ship"
# or "ice" stock shot tagged closest, not a rejection. That is precisely what
# this gate exists to catch; they were just never added to it.
LOOSE_PROVIDERS = {"met", "openverse", "pixabay", "pexels"}


def relevant(cand: MediaCandidate, query: str) -> bool:
    """Reject a loose provider's hit that only glances off the query.

    One shared word is not enough: "Endurance ship night flashlight 1915" and the
    Met's "Night-Shining White" share "night" and nothing else that matters.

    The percentage branch exists for long queries, where getting half the
    words right is a real signal. It stops being one on a short query: a
    two-word search like "humanoid robot" — exactly what script_gen writes
    for modern b-roll — already clears 50% overlap by sharing the single word
    "robot" with any generically-tagged stock photo, which is precisely the
    kind of match this function exists to catch. Short queries require both
    words shared; the percentage allowance only kicks in once there are
    enough words for "most of them" to mean something.
    """
    if cand.provider not in LOOSE_PROVIDERS:
        return True
    q = tokens(query)
    if not q:
        return True
    hit = q & tokens(cand.title)
    if len(q) <= 3:
        return len(hit) >= 2
    return len(hit) >= 2 or len(hit) / len(q) >= 0.5


_YEAR = re.compile(r"^(1[5-9]\d\d|20\d\d)$")


def relax(query: str) -> list[str]:
    """Progressively looser rewrites of an over-specific picture-research query.

    "Endurance Grytviken whaling station 1914" finds nothing on Commons because
    every term is ANDed. Dropping the year, then the tail, finds the picture.
    """
    words = query.split()
    variants: list[str] = []

    def add(ws: list[str]) -> None:
        v = " ".join(ws).strip()
        if len(ws) >= 1 and v and v.lower() != query.lower() and v not in variants:
            variants.append(v)

    no_year = [w for w in words if not _YEAR.match(w.strip(",."))]
    if len(no_year) != len(words):
        add(no_year)

    tail = no_year or words
    proper = [w for w in words if w[:1].isupper() and not _YEAR.match(w)]

    # Ordered by how often each rewrite actually finds the picture:
    #   1. drop the last qualifier      ("… whaling station 1914" -> "… whaling station")
    #   2. drop the leading subject     ("Endurance Grytviken …" -> "Grytviken …"), because
    #      the subject was often never photographed at the place being described
    #   3. keep shortening from the end, then the proper nouns alone
    if len(tail) >= 3:
        add(tail[:-1])
    if len(tail) >= 3:
        add(tail[1:])
    for cut in range(2, len(tail)):
        if len(tail) - cut >= 2:
            add(tail[: len(tail) - cut])
    if len(tail) >= 4:
        add(tail[1:3])
    if 1 <= len(proper) <= 3:
        add(proper)

    return variants[:5]


# -------------------------------------------------------------------- scoring
PROVIDER_WEIGHT = {
    "wikimedia": 1.00,
    "met": 0.85,
    "loc": 0.95,
    "nypl": 0.92,
    "openverse": 0.72,
    "storyblocks": 0.78,
    "pexels": 0.66,
    "pixabay": 0.60,
    "library": 1.15,
    "maps": 1.10,
    "local": 1.20,
}


# Commons hosts the same diagram translated many times over, and the English
# original is rarely the one that ranks first. A map captioned "Déli-sark" is
# still the right map, so this is a penalty rather than a filter.
_LOCALISED = re.compile(
    r"\((HUN|DEU|GER|FRA|SPA|ITA|RUS|POL|NLD|POR|CES|SWE|TUR|JPN|ZHO|KOR|FIN|"
    r"DAN|NOR|RON|UKR|ELL|ARA|HEB|VIE|IND|THA|CAT|SRP|BUL|HRV|SLK|SLV|EST|LAV|"
    r"LIT|HUN)\)|[ _-](de|fr|es|it|ru|pl|nl|pt|hu|cs|sv|tr|ja|zh|ko|fi|da|no|ro|"
    r"uk|el|ar|he|vi|id|th|ca|sr|bg|hr|sk|sl)\.(svg|png|jpg|jpeg)$",
    re.I,
)


def score(cand: MediaCandidate, query: str, prefer_kind: str) -> float:
    """Rank a candidate. Higher is better; roughly 0-3."""
    s = PROVIDER_WEIGHT.get(cand.provider, 0.5)

    if _LOCALISED.search(cand.title or "") or _LOCALISED.search(cand.url or ""):
        s -= 0.55

    # Text relevance: how much of the query the asset's own title accounts for.
    q_toks = tokens(query)
    if q_toks:
        overlap = len(q_toks & tokens(cand.title)) / len(q_toks)
        s += overlap * 0.9

    # Resolution: enough pixels to survive a slow zoom on a 1080p frame.
    if cand.kind == "image":
        px = cand.width * cand.height
        if px:
            if px < 640 * 480:
                s -= 0.9
            elif px < 1280 * 720:
                s -= 0.35
            elif px > 2400 * 1600:
                s += 0.30
            elif px > 1600 * 1000:
                s += 0.15
        if cand.width and cand.height:
            ar = cand.width / cand.height
            if ar < 0.55 or ar > 3.2:     # slivers and full-page scans crop badly
                s -= 0.5
            elif 1.2 <= ar <= 2.1:
                s += 0.2
    else:
        if cand.duration and cand.duration < 4:
            s -= 0.5
        if cand.width >= 1920:
            s += 0.2

    if cand.kind != prefer_kind:
        s -= 0.45

    return round(s, 4)


def dedupe(cands: list[MediaCandidate]) -> list[MediaCandidate]:
    seen_url: set[str] = set()
    seen_title: set[str] = set()
    out = []
    for c in cands:
        key = (c.url or "").split("?")[0]
        tkey = f"{c.provider}:{(c.title or '').strip().lower()}"
        if key in seen_url or (c.title and tkey in seen_title):
            continue
        seen_url.add(key)
        if c.title:
            seen_title.add(tkey)
        out.append(c)
    return out

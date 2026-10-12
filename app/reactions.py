"""Reaction GIFs, from Giphy — a comic beat, not a documentary picture.

Everything else in `app/media/` searches for the right historical photograph
and argues, via `relevant()`/`LOOSE_PROVIDERS`/`PROVIDER_WEIGHT`, about how
close a hit has to be before it is allowed to stand in for a named person or
place. A reaction GIF has no such question — "mind blown" doesn't get more
or less correct, it either lands as a joke or it doesn't, and that is a
judgement only the creator watching the result can make. So this is
deliberately **not** a `media.providers` entry: it is never in
`ALL_PROVIDERS`, never part of the automatic gather for a slide, and never
scored against a query the way an archive hit is. It only exists where a
human went looking for it — the "reaction gif" option on the manual search
picker (`POST /api/projects/{pid}/slides/{sid}/search`) — which is exactly
the boundary a documentary tool and a meme ought to have between them.

Rights are not cleared by using this. Most reaction GIFs are clipped from
television, film, or someone's own unlicensed upload; every candidate here
carries a `license` string that says so plainly, read the same way the
credits block already reads every other provider's — see `render.credits_text`.
"""
from __future__ import annotations

from .config import GIPHY_KEY
from .media.base import get_json
from .schema import MediaCandidate

SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
RATING = "pg-13"     # Giphy's own content filter; the closest thing to a safety net here


def available() -> bool:
    return bool(GIPHY_KEY)


def search(query: str, limit: int = 16) -> list[MediaCandidate]:
    """Reaction GIFs for `query`. `[]` on any failure — a missing key, a rate
    limit, Giphy being down — never raises, same contract every other
    provider keeps."""
    if not GIPHY_KEY or not query.strip():
        return []
    data = get_json(SEARCH_URL, "giphy", params={
        "api_key": GIPHY_KEY, "q": query, "limit": str(max(1, min(25, limit))),
        "rating": RATING, "lang": "en",
    })
    out: list[MediaCandidate] = []
    for g in (data or {}).get("data", []) or []:
        images = g.get("images") or {}
        # Giphy's own best-quality rendition under a frame-count/size cap —
        # the "original" is sometimes enormous, and every candidate here is a
        # few seconds held at most, not a hero shot worth the extra weight.
        pick = images.get("downsized_large") or images.get("original") or {}
        # The .mp4 rendition over the .gif: ffmpeg decodes both equally well
        # (confirmed — ffprobe reads a GIF's duration and dimensions exactly
        # like any other video), but the mp4 is a fraction of the size for
        # the same clip, which matters when `_clip_source` may loop it.
        url = pick.get("mp4") or pick.get("url")
        if not url:
            continue
        try:
            width, height = int(pick.get("width") or 0), int(pick.get("height") or 0)
        except (TypeError, ValueError):
            width = height = 0
        user = (g.get("user") or {}).get("display_name") or (g.get("user") or {}).get("username") or ""
        out.append(MediaCandidate(
            id=f"gph{g.get('id', '')}", provider="giphy", kind="video",
            title=(g.get("title") or "").strip() or query,
            url=url, thumb=(images.get("fixed_height_small") or images.get("preview_gif") or {}).get("url", url),
            source_page=g.get("url", ""), author=user,
            license="Giphy — rights not cleared; check before a monetised upload",
            width=width, height=height,
            # Giphy's search API does not report a clip's duration — left at
            # 0 (unknown) rather than guessed; render.py's own clip-source
            # step measures the real figure off the downloaded file before
            # it ever needs one, the same as it does for any video pick.
            duration=0.0,
            query=query,
            # Fixed, not computed: nothing here is being ranked against a
            # query the way an archive hit is — see the module docstring.
            score=1.0,
        ))
    return out

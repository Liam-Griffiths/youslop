"""Concrete media providers. Each returns MediaCandidate lists and never raises."""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import hmac
import os
import re
import time

from ..config import PEXELS_KEY, PIXABAY_KEY, STORYBLOCKS_PUBLIC, STORYBLOCKS_SECRET
from ..schema import MediaCandidate
from .base import get_json, is_junk


def _get(url: str, provider: str, **kw) -> dict | list | None:
    """Throttled, retrying GET. `provider` selects the rate limit bucket."""
    return get_json(url, provider, **kw)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


# --------------------------------------------------------------- wikimedia
class Wikimedia:
    name = "wikimedia"
    kinds = ("image",)
    # Search returns picker-sized previews only. The render-sized rendition is
    # fetched per image, on demand, once the creator has actually chosen it —
    # browsing a 35-slide project otherwise pulls hundreds of megabytes of
    # full-resolution files off Wikimedia for pictures nobody ends up using.
    THUMB_W = 480
    FULL_W = 1920

    def available(self) -> bool:
        return True

    def full_url(self, ref: str) -> tuple[str, int, int] | None:
        """Resolve one file's render-sized rendition. `ref` is its File: title.

        Only widths the API itself generates are fetchable, so this has to ask
        rather than rewrite the preview URL by hand.
        """
        data = _get(
            "https://commons.wikimedia.org/w/api.php", "wikimedia",
            params={"action": "query", "format": "json", "formatversion": "2",
                    "titles": ref, "prop": "imageinfo",
                    "iiprop": "url|size", "iiurlwidth": str(self.FULL_W)},
        )
        pages = ((data or {}).get("query") or {}).get("pages") or []
        if not pages:
            return None
        info = (pages[0].get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            return None
        return (url,
                int(info.get("thumbwidth") or info.get("width") or 0),
                int(info.get("thumbheight") or info.get("height") or 0))

    def search(self, query: str, kind: str, limit: int = 14) -> list[MediaCandidate]:
        if kind != "image":
            return []
        data = _get(
            "https://commons.wikimedia.org/w/api.php", "wikimedia",
            params={
                "action": "query", "format": "json", "formatversion": "2",
                "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": "6", "gsrlimit": str(limit),
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(self.THUMB_W),
            },
        )
        pages = ((data or {}).get("query") or {}).get("pages") or []
        out = []
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            title = re.sub(r"^File:|\.\w+$", "", p.get("title", ""))
            if not info.get("url") or is_junk(title, info["url"]):
                continue
            meta = info.get("extmetadata") or {}

            # Always the API's pre-rendered thumbnail, never the original. The
            # originals live behind aggressive hotlink throttling and answer a
            # batch of requests with 429s; the /thumb/ renders serve fine and
            # convert TIFF and friends to JPEG on the way.
            preview = info.get("thumburl") or info["url"]
            # The source's true dimensions, so ranking still judges the real
            # image rather than the 480px preview of it.
            w = int(info.get("width") or 0)
            h = int(info.get("height") or 0)
            out.append(MediaCandidate(
                id=f"wm{abs(hash(p.get('title'))) % 10**10}",
                provider=self.name, kind="image", title=title,
                url=preview, thumb=preview, ref=p.get("title", ""), full=False,
                source_page=info.get("descriptionurl", ""),
                author=_strip_html((meta.get("Artist") or {}).get("value", ""))[:80],
                license=_strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
                width=w, height=h, query=query,
            ))
        return out


# ---------------------------------------------------------------- openverse
class Openverse:
    name = "openverse"
    kinds = ("image",)

    def available(self) -> bool:
        return True

    def search(self, query: str, kind: str, limit: int = 12) -> list[MediaCandidate]:
        if kind != "image":
            return []
        data = _get("https://api.openverse.org/v1/images/", "openverse",
                    params={"q": query, "page_size": str(limit),
                            "license_type": "all-cc,commercial", "mature": "false"})
        out = []
        for r in (data or {}).get("results", []) or []:
            url = r.get("url") or ""
            title = r.get("title") or ""
            if not url or is_junk(title, url):
                continue
            out.append(MediaCandidate(
                id=f"ov{r.get('id', '')[:12]}", provider=self.name, kind="image",
                title=title, url=url, thumb=r.get("thumbnail") or url,
                source_page=r.get("foreign_landing_url", ""),
                author=r.get("creator") or "",
                license=f"CC {(r.get('license') or '').upper()} {r.get('license_version', '')}".strip(),
                width=int(r.get("width") or 0), height=int(r.get("height") or 0),
                query=query,
            ))
        return out


# ---------------------------------------------------------- library of congress
class LibraryOfCongress:
    name = "loc"
    kinds = ("image",)
    _size = re.compile(r"#h=(\d+)&w=(\d+)")

    def available(self) -> bool:
        return True

    def search(self, query: str, kind: str, limit: int = 10) -> list[MediaCandidate]:
        if kind != "image":
            return []
        data = _get("https://www.loc.gov/photos/", "loc",
                    params={"q": query, "fo": "json", "c": str(limit), "at": "results"})
        out = []
        for r in (data or {}).get("results", []) or []:
            urls = r.get("image_url") or []
            if isinstance(urls, str):
                urls = [urls]
            best, best_px, bw, bh = "", 0, 0, 0
            small, small_px = "", 10 ** 12
            for u in urls:
                m = self._size.search(u)
                h, w = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
                clean = u.split("#")[0]
                if clean.endswith(".gif"):
                    continue
                if h * w >= best_px:
                    best, best_px, bw, bh = clean, h * w, w, h
                # Smallest rendition still big enough to read in the picker.
                if 0 < h * w < small_px and w >= 300:
                    small, small_px = clean, h * w
            title = r.get("title") or ""
            if not best or is_junk(title, best):
                continue
            if best.startswith("//"):
                best = "https:" + best
            if small.startswith("//"):
                small = "https:" + small
            out.append(MediaCandidate(
                id=f"loc{abs(hash(best)) % 10**10}", provider=self.name, kind="image",
                title=title, url=best, thumb=small or best,
                source_page=r.get("url") or r.get("id") or "",
                author=", ".join(r.get("contributor") or [])[:80],
                license="Library of Congress; rights vary, check the item page",
                width=bw, height=bh, query=query,
            ))
        return out


# ------------------------------------------------------------- met museum
class MetMuseum:
    name = "met"
    kinds = ("image",)
    API = "https://collectionapi.metmuseum.org/public/collection/v1"

    def available(self) -> bool:
        return True

    def search(self, query: str, kind: str, limit: int = 8) -> list[MediaCandidate]:
        if kind != "image":
            return []
        data = _get(f"{self.API}/search", "met", params={"q": query, "hasImages": "true"})
        ids = ((data or {}).get("objectIDs") or [])[:limit]
        if not ids:
            return []

        def fetch(oid: int) -> MediaCandidate | None:
            o = _get(f"{self.API}/objects/{oid}", "met")
            if not o or not o.get("primaryImage"):
                return None
            title = o.get("title") or ""
            return MediaCandidate(
                id=f"met{oid}", provider=self.name, kind="image", title=title,
                url=o["primaryImage"], thumb=o.get("primaryImageSmall") or o["primaryImage"],
                source_page=o.get("objectURL", ""),
                author=o.get("artistDisplayName") or "The Metropolitan Museum of Art",
                license="Public domain (Met OA)" if o.get("isPublicDomain") else "Met, rights vary",
                width=0, height=0, query=query,   # Met omits dimensions; stay neutral
            )

        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            return [c for c in pool.map(fetch, ids) if c]


# ------------------------------------------------------------------ nypl
class NYPL:
    name = "nypl"
    kinds = ("image",)

    def available(self) -> bool:
        return bool(os.environ.get("NYPL_TOKEN"))

    def search(self, query: str, kind: str, limit: int = 10) -> list[MediaCandidate]:
        token = os.environ.get("NYPL_TOKEN")
        if kind != "image" or not token:
            return []
        data = _get("http://api.repo.nypl.org/api/v2/items/search", "nypl",
                    params={"q": query, "per_page": str(limit)},
                    headers={"Authorization": f"Token token={token}"})
        result = ((data or {}).get("nyplAPI") or {}).get("response") or {}
        items = (result.get("result") or [])
        if isinstance(items, dict):
            items = [items]
        out = []
        for it in items:
            uuid = it.get("uuid") or ""
            title = it.get("title") or ""
            img = it.get("imageID")
            if not uuid or not img:
                continue
            url = f"https://images.nypl.org/index.php?id={img}&t=g"
            out.append(MediaCandidate(
                id=f"nypl{uuid[:10]}", provider=self.name, kind="image", title=title,
                url=url, thumb=f"https://images.nypl.org/index.php?id={img}&t=w",
                source_page=f"https://digitalcollections.nypl.org/items/{uuid}",
                author="The New York Public Library",
                license="NYPL Digital Collections; rights vary",
                width=1600, height=1200, query=query,
            ))
        return out


# ---------------------------------------------------------------- pexels
class Pexels:
    name = "pexels"
    kinds = ("image", "video")

    def available(self) -> bool:
        return bool(PEXELS_KEY)

    def search(self, query: str, kind: str, limit: int = 10) -> list[MediaCandidate]:
        if not PEXELS_KEY:
            return []
        hdr = {"Authorization": PEXELS_KEY}
        out = []
        if kind == "video":
            data = _get("https://api.pexels.com/videos/search", "pexels", headers=hdr,
                        params={"query": query, "per_page": str(limit),
                                "orientation": "landscape", "size": "medium"})
            for v in (data or {}).get("videos", []) or []:
                files = sorted(
                    (f for f in v.get("video_files", []) if (f.get("width") or 0) <= 2560),
                    key=lambda f: f.get("width") or 0, reverse=True)
                if not files:
                    continue
                f = files[0]
                out.append(MediaCandidate(
                    id=f"pxv{v.get('id')}", provider=self.name, kind="video",
                    title=(v.get("url") or "").rstrip("/").split("/")[-1].replace("-", " "),
                    url=f.get("link", ""),
                    thumb=v.get("image", ""), source_page=v.get("url", ""),
                    author=(v.get("user") or {}).get("name", ""),
                    license="Pexels licence", width=int(f.get("width") or 0),
                    height=int(f.get("height") or 0), duration=float(v.get("duration") or 0),
                    query=query,
                ))
        else:
            data = _get("https://api.pexels.com/v1/search", "pexels", headers=hdr,
                        params={"query": query, "per_page": str(limit), "orientation": "landscape"})
            for p in (data or {}).get("photos", []) or []:
                src = p.get("src") or {}
                out.append(MediaCandidate(
                    id=f"pxp{p.get('id')}", provider=self.name, kind="image",
                    title=p.get("alt") or query, url=src.get("original", ""),
                    thumb=src.get("medium", ""), source_page=p.get("url", ""),
                    author=p.get("photographer", ""), license="Pexels licence",
                    width=int(p.get("width") or 0), height=int(p.get("height") or 0),
                    query=query,
                ))
        return [c for c in out if c.url]


# --------------------------------------------------------------- pixabay
class Pixabay:
    name = "pixabay"
    kinds = ("image", "video")

    def available(self) -> bool:
        return bool(PIXABAY_KEY)

    def search(self, query: str, kind: str, limit: int = 10) -> list[MediaCandidate]:
        if not PIXABAY_KEY:
            return []
        out = []
        if kind == "video":
            data = _get("https://pixabay.com/api/videos/", "pixabay",
                        params={"key": PIXABAY_KEY, "q": query, "per_page": str(max(3, limit))})
            for v in (data or {}).get("hits", []) or []:
                vids = v.get("videos") or {}
                pick = vids.get("large") or vids.get("medium") or vids.get("small") or {}
                if not pick.get("url"):
                    continue
                out.append(MediaCandidate(
                    id=f"pbv{v.get('id')}", provider=self.name, kind="video",
                    title=v.get("tags", ""), url=pick["url"],
                    thumb=pick.get("thumbnail", ""),
                    source_page=v.get("pageURL", ""), author=v.get("user", ""),
                    license="Pixabay content licence",
                    width=int(pick.get("width") or 0), height=int(pick.get("height") or 0),
                    duration=float(v.get("duration") or 0), query=query,
                ))
        else:
            data = _get("https://pixabay.com/api/", "pixabay",
                        params={"key": PIXABAY_KEY, "q": query, "per_page": str(max(3, limit)),
                                "image_type": "photo", "orientation": "horizontal"})
            for p in (data or {}).get("hits", []) or []:
                out.append(MediaCandidate(
                    id=f"pbi{p.get('id')}", provider=self.name, kind="image",
                    title=p.get("tags", ""), url=p.get("largeImageURL", ""),
                    thumb=p.get("webformatURL", ""), source_page=p.get("pageURL", ""),
                    author=p.get("user", ""), license="Pixabay content licence",
                    width=int(p.get("imageWidth") or 0), height=int(p.get("imageHeight") or 0),
                    query=query,
                ))
        return [c for c in out if c.url]


# ------------------------------------------------------------- storyblocks
class Storyblocks:
    """Paid API. Stays dark unless both keys are present in the environment."""
    name = "storyblocks"
    kinds = ("image", "video")
    BASE = "https://api.storyblocks.com/api/v2"

    def available(self) -> bool:
        return bool(STORYBLOCKS_PUBLIC and STORYBLOCKS_SECRET)

    def _auth(self, resource: str) -> dict:
        expires = str(int(time.time()) + 100)
        sig = hmac.new((STORYBLOCKS_SECRET + expires).encode(),
                       resource.encode(), hashlib.sha256).hexdigest()
        return {"APIKEY": STORYBLOCKS_PUBLIC, "EXPIRES": expires, "HMAC": sig,
                "project_id": os.environ.get("STORYBLOCKS_PROJECT_ID", "youslop"),
                "user_id": os.environ.get("STORYBLOCKS_USER_ID", "local")}

    def search(self, query: str, kind: str, limit: int = 8) -> list[MediaCandidate]:
        if not self.available():
            return []
        resource = "/videos/search" if kind == "video" else "/images/search"
        params = self._auth(resource) | {"keywords": query, "results_per_page": str(limit),
                                         "content_type": "footage" if kind == "video" else "photos"}
        data = _get(self.BASE + resource, "storyblocks", params=params)
        out = []
        for r in (data or {}).get("results", []) or []:
            url = (r.get("preview_urls") or {}).get("_1080p") or r.get("preview_url") or ""
            thumb = (r.get("thumbnail_urls") or {}).get("_480") or r.get("thumbnail_url") or ""
            if not url:
                continue
            out.append(MediaCandidate(
                id=f"sb{r.get('id')}", provider=self.name, kind=kind,
                title=r.get("title", ""), url=url, thumb=thumb,
                source_page=r.get("details_url", ""), author="Storyblocks",
                license="Storyblocks licence (account required)",
                width=int(r.get("width") or 1920), height=int(r.get("height") or 1080),
                duration=float(r.get("duration") or 0), query=query,
            ))
        return out


# --------------------------------------------------------------- your library
class Library:
    """Hand-downloaded stock, tagged and stored in app/library.py.

    No network, no rate limit — this is just an in-memory scan of your own
    index, so it costs nothing to try first.
    """
    name = "library"
    kinds = ("image", "video")

    def available(self) -> bool:
        return True

    def search(self, query: str, kind: str, limit: int = 12) -> list[MediaCandidate]:
        from .. import library
        return library.search(query, kind, limit)


ALL_PROVIDERS = [
    Wikimedia(), LibraryOfCongress(), MetMuseum(), NYPL(),
    Openverse(), Pexels(), Pixabay(), Storyblocks(), Library(),
]

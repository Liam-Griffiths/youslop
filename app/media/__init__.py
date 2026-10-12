"""Search, rank, pick and download the visuals for a project."""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import mimetypes
import re
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from ..schema import MediaCandidate, Project, Slide
from ..store import project_dir
from .base import client, dedupe, relax, relevant, score, throttle
from .providers import ALL_PROVIDERS

Progress = Callable[[str], None]

MAX_CANDIDATES = 14
ENOUGH = 6          # below this, widen the queries and search again


def provider_status() -> list[dict]:
    return [
        {"name": p.name, "kinds": list(p.kinds), "available": p.available()}
        for p in ALL_PROVIDERS
    ]


# Pexels and Pixabay are modern stock-photo libraries with essentially no
# historical content, matched by tags rather than anything resembling a
# caption. `relevant()` catches a candidate sharing too few words with the
# query, but it cannot catch the opposite failure — a query like "Tesla Bot
# announcement Palo Alto 2021" coincidentally sharing "palo"+"alto" with a
# generic Stanford-campus stock photo, or "1939 World's Fair" matching a tag
# for an entirely different fair. Shared place names and category words pass
# a token-overlap gate without the photo being of the right thing. So rather
# than chase every such coincidence with a sharper heuristic, these two are
# simply never offered for a genuinely *image* search — the one
# `plan_visuals()` already reserves for "historical, archival or specific to
# a named person/event" (see script_gen.py). They stay fully available for
# "video" b-roll, which is the generic-modern-motion case they actually suit,
# and for the image-of-a-video-slide fallback inside `_jobs_for` below.
STOCK_PHOTO_PROVIDERS = {"pexels", "pixabay"}


def _active(kind: str, allow_stock: bool = True) -> list:
    pool = [p for p in ALL_PROVIDERS if p.available() and kind in p.kinds]
    if not allow_stock:
        pool = [p for p in pool if p.name not in STOCK_PHOTO_PROVIDERS]
    return pool


_CACHE: dict[tuple, list[MediaCandidate]] = {}
_CACHE_LOCK = threading.Lock()


def _cached_search(provider, query: str, kind: str) -> list[MediaCandidate]:
    """One provider+query lookup, memoised. Relaxed queries repeat constantly
    across slides, and every saved request is one we don't spend on a rate limit."""
    key = (provider.name, query.lower(), kind)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        out = provider.search(query, kind, 10) or []
    except Exception:
        out = []
    # Never memoise an empty result. A rate-limited or timed-out request is
    # indistinguishable from a genuinely empty one here, and caching the failure
    # would poison every later slide that tries the same query.
    if out:
        with _CACHE_LOCK:
            _CACHE[key] = out
            if len(_CACHE) > 4000:
                _CACHE.clear()
    return out


def _run(jobs: list[tuple], kind: str) -> list[MediaCandidate]:
    """Execute (provider, query, kind) jobs in parallel, keeping only relevant hits."""
    if not jobs:
        return []
    found: list[MediaCandidate] = []
    with cf.ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        futures = [pool.submit(_cached_search, p, q, k) for p, q, k in jobs]
        for fut in cf.as_completed(futures):
            try:
                found.extend(fut.result() or [])
            except Exception:
                continue
    # Candidates are shared objects when cached, so hand back copies the caller
    # can score and mutate freely.
    return [replace(c) for c in found if relevant(c, c.query)]


def _jobs_for(queries: list[str], kind: str, providers=None,
             allow_stock: bool = True) -> list[tuple]:
    providers = providers if providers is not None else _active(kind, allow_stock)
    jobs = [(p, q, kind) for q in queries for p in providers]
    # Stills are the fallback for a video slide when the stock libraries are
    # dry — always stock-eligible, since a video slide already wants generic
    # motion-adjacent content and this is exactly the case stock suits.
    if kind == "video":
        jobs += [(p, q, "image") for q in queries[:2] for p in _active("image")]
    return jobs


def _ladder(queries: list[str]) -> list[str]:
    """Round-robin the rewrites, so the best variant of *each* query is tried
    before the second-best variant of the first one."""
    ladders = [relax(q) for q in queries[:2]]
    out: list[str] = []
    for rank in range(max((len(l) for l in ladders), default=0)):
        for ladder in ladders:
            if rank < len(ladder) and ladder[rank] not in out and ladder[rank] not in queries:
                out.append(ladder[rank])
    return out


# Which providers get tried first, before anyone else is even asked — see
# `search()`. This used to be one fixed tuple regardless of `kind`, which
# meant an *image* search's first pass was library + wikimedia + pexels +
# storyblocks: two paid stock-video services ranked ahead of the Library of
# Congress, the Met and NYPL, the three sources `PROVIDER_WEIGHT` itself
# already rates above storyblocks. Second-tier "rest" only gets searched when
# the first pass comes up thin, so those three were routinely never asked at
# all for a slide the first pass already half-filled with stock. Now kind
# decides the tier the way the weights already imply it should: an image
# search leads with the real archives, a video search leads with the sources
# that actually have motion footage.
LEAD_PROVIDERS = {
    "image": {"library", "wikimedia", "loc", "nypl", "met"},
    "video": {"library", "pexels", "storyblocks"},
}


def search(queries: list[str], kind: str, limit: int = MAX_CANDIDATES,
           fallback: str = "", allow_stock: bool = True) -> list[MediaCandidate]:
    """Find visuals for one slide, spending as few archive requests as possible.

    A picture-research query like "Endurance Grytviken whaling station 1914" is
    usually too specific for an archive's AND-based search, so we widen in
    stages. Each stage only runs if the previous one came back thin, which keeps
    a 24-slide project from firing hundreds of requests at Wikimedia and getting
    itself rate limited into returning nothing at all.
    """
    pool = _active(kind, allow_stock)
    lead_names = LEAD_PROVIDERS.get(kind, LEAD_PROVIDERS["image"])
    lead = [p for p in pool if p.name in lead_names]
    rest = [p for p in pool if p not in lead]
    found: list[MediaCandidate] = []

    def enough(n: int) -> bool:
        return len({c.url for c in found}) >= n

    # 1. the best source for this kind, on the exact queries
    if lead:
        found += _run(_jobs_for(queries[:3], kind, lead), kind)
    # 2. same source, looser phrasing
    if not enough(ENOUGH):
        widened = _ladder(queries)
        if widened and lead:
            found += _run(_jobs_for(widened[:4], kind, lead), kind)
    # 3. everyone else, exact queries
    if not enough(ENOUGH) and rest:
        found += _run(_jobs_for(queries[:2], kind, rest), kind)
    # 4. everyone else, looser phrasing
    if not enough(4) and rest:
        widened = _ladder(queries)
        if widened:
            found += _run(_jobs_for(widened[:2], kind, rest), kind)
    # 5. last resort: the video's own subject, so no slide is left blank
    if fallback and not enough(3):
        found += _run(_jobs_for([fallback], kind), kind)

    for c in found:
        # The library provider already scored its own hits with tags folded
        # into the text-relevance term; redoing it here against the bare
        # title would throw that away.
        if c.provider != "library":
            c.score = score(c, c.query, kind)
    found = dedupe(found)
    found.sort(key=lambda c: c.score, reverse=True)

    # Diversity cap: one chatty provider must not crowd the picker. Openverse
    # will happily return forty Flickr snapshots for a historical query. The cap
    # is generous, because on a historical subject Wikimedia deserves to win.
    per_provider: dict[str, int] = {}
    kept: list[MediaCandidate] = []
    for c in found:
        n = per_provider.get(c.provider, 0)
        if n >= max(6, limit - 4):
            continue
        per_provider[c.provider] = n + 1
        kept.append(c)
        if len(kept) >= limit:
            break
    return kept


def _slide_map(project: Project, slide: Slide) -> dict | None:
    """The map/satellite/establishing-shot candidate a "map" slide asked for.

    None on any failure — a bad geocode, a dead tile server — rather than
    raising: the normal archive search for this slide already ran alongside
    this, so a slide that can't get a map is no worse off than before this
    existed.
    """
    from .. import maps
    lat, lon = slide.map_lat, slide.map_lon
    if not (lat or lon):
        # The writer's own automatic pick (script_gen's "kind": "map") only
        # sets a place name, never coordinates — geocode it here, once, the
        # one time a human hasn't already clicked a point in the picker.
        coords = maps.geocode(slide.map_place)
        if not coords:
            return None
        lat, lon = coords
    shots = {
        "still": maps.still, "establishing": maps.establishing_shot,
        "reveal": maps.reveal_shot, "pan": maps.pan_shot,
    }
    kind = slide.map_kind if slide.map_kind in ("street", "hybrid", "terrain") else "satellite"
    shot = shots.get(slide.map_style, maps.still)
    zoom = slide.map_zoom or (14 if shot is maps.still else 15)
    try:
        dest = project_dir(project.id) / "media"
        return shot(lat, lon, zoom, kind, project.style.accent, dest, label=slide.map_place)
    except Exception:
        return None


def _slide_diagram(project: Project, slide: Slide) -> dict | None:
    """The drawn diagram a "diagram" slide asked for, or None if it won't draw.

    Same contract as `_slide_map`: never raises. A spec a model wrote badly
    enough that `diagram.normalise` rejects it leaves the slide with its
    ordinary archive search, which is no worse off than before.
    """
    from .. import diagram as diagram_mod
    spec = getattr(slide, "diagram", None)
    if not spec:
        return None
    try:
        return diagram_mod.candidate(
            spec, project_dir(project.id) / "media", project.style.accent,
            motion="reveal", hand=getattr(project.style, "board_hand", "marker"))
    except Exception:
        return None


def _drawn_noun(slide: Slide) -> str:
    if slide.prefer_kind == "diagram":
        return "diagram"
    if slide.prefer_kind == "map":
        return "map"
    return "designed slide"


def _slide_custom(project: Project, slide: Slide) -> dict | None:
    """Draw the slide's filled style, and fetch any photos it asked for.

    Same contract as `_slide_diagram` — never raises. Rendered as a *still*
    rather than the animated clip: this is the preview the Media tab shows,
    and `render._render_custom_style` redraws it animated at the paragraph's
    exact length anyway, so encoding thirty videos here would be thrown away.
    The point of doing it inside gather is the archive fetch, which belongs
    where every other archive fetch already happens.
    """
    from .. import custom_slide as custom_mod
    spec = getattr(slide, "custom", None)
    if not spec or not spec.get("elements"):
        return None
    try:
        return custom_mod.candidate(
            spec, project_dir(project.id) / "media", motion="still",
            hand=getattr(project.style, "board_hand", "marker"))
    except Exception:
        return None


def subject_query(project: Project) -> str:
    """A short, searchable stand-in for the whole video.

    The outline's "subject" is a descriptive sentence ("Ernest Shackleton and the
    crew of the Endurance, Imperial Trans-Antarctic Expedition"), and ANDing all
    of that finds nothing. The proper nouns alone find the subject.
    """
    subject = project.outline.get("subject") or project.title or ""
    proper = [w.strip(",.") for w in subject.split()
              if w[:1].isupper() and len(w) > 2]
    seen, keep = set(), []
    for w in proper:
        if w.lower() not in seen:
            seen.add(w.lower())
            keep.append(w)
    return " ".join(keep[:3]) or subject[:40]


def gather(project: Project, progress: Progress = lambda m: None,
           only: list[str] | None = None) -> None:
    """Populate candidates and auto-pick a lead visual for each slide.

    Only the slides that actually start a picture are searched for. With
    `style.picture_every` above 1 the rest hold the picture already on screen,
    which is the whole point of the setting: a 24 paragraph video set to change
    every third paragraph needs eight pictures found, not twenty-four.
    """
    from ..render import is_lead

    targets = [s for s in project.slides
               if (only is None or s.id in only) and not s.locked_media
               and is_lead(project, s)]
    if not targets:
        return
    progress(f"Searching {len(_active('image'))} image and "
             f"{len(_active('video'))} video sources for {len(targets)} slides")

    done = 0
    fallback = subject_query(project)

    # Fetch the subject pool once, up front. Every slide can draw on it, so a
    # slide whose specific shot does not exist is never left with a blank frame,
    # and we spend exactly one set of requests on it instead of one per slide.
    subject_pool = search([fallback], "image", limit=24, allow_stock=False) if fallback else []
    progress(f"Subject pool: {len(subject_pool)} general images for “{fallback}”")

    def work(slide: Slide) -> tuple[Slide, list[MediaCandidate], dict | None]:
        # A slide the writer marked as wanting a map still gets its normal
        # archive search too — a real photograph, if one turns out to exist,
        # is allowed to win the slot on its own merits.
        kind = slide.prefer_kind if slide.prefer_kind == "video" else "image"
        cands = search(slide.queries or [project.title], kind, allow_stock=kind != "image")
        if slide.prefer_kind == "map":
            drawn = _slide_map(project, slide)
        elif slide.prefer_kind == "diagram":
            drawn = _slide_diagram(project, slide)
        elif (slide.custom or {}).get("elements"):
            drawn = _slide_custom(project, slide)
        else:
            drawn = None
        return slide, cands, drawn

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for slide, cands, drawn in pool.map(work, targets):
            slide.candidates = [c.to_dict() for c in cands]
            if drawn:
                slide.candidates.insert(0, drawn)
                # The spec comes back with its photo fetches resolved; keeping
                # it is what stops the render re-fetching them one by one.
                if drawn.get("custom"):
                    slide.custom = drawn["custom"]
            done += 1
            note = (f" (+ a {_drawn_noun(slide)})" if drawn else "")
            progress(f"Media {done}/{len(targets)}: {len(cands)} option(s){note} for "
                     f"“{(slide.title or slide.narration)[:42]}…”")

    _top_up(targets, subject_pool, progress)
    _autopick(project)
    project.status = "media" if project.status == "scripted" else project.status


def _top_up(slides: list[Slide], pool: list[MediaCandidate],
            progress: Progress = lambda m: None) -> None:
    """Backfill thin slides from the subject pool, spreading the images around.

    Handing every thin slide the same top-ranked photo would put one portrait on
    screen five times, so each slide starts from a different point in the pool.
    """
    if not pool:
        return
    thin = [s for s in slides if len(s.candidates) < 3]
    if not thin:
        return
    for n, slide in enumerate(thin):
        have = {c["id"] for c in slide.candidates}
        rotated = pool[n % len(pool):] + pool[: n % len(pool)]
        extra = []
        for c in rotated:
            if c.id in have:
                continue
            d = c.to_dict()
            d["score"] = round(c.score - 0.6, 4)   # a stand-in, not a real match
            extra.append(d)
            if len(slide.candidates) + len(extra) >= 8:
                break
        slide.candidates = slide.candidates + extra
    progress(f"Topped up {len(thin)} thin slides from the subject pool")


def _autopick(project: Project) -> None:
    """Choose the best candidate per slide, avoiding repeats across the video."""
    used: set[str] = {
        s.chosen_id for s in project.slides if s.locked_media and s.chosen_id
    }
    for slide in project.slides:
        if slide.locked_media and slide.chosen_id:
            continue
        if not slide.candidates:
            slide.chosen_id = ""
            continue
        best, best_score = None, -1e9
        for c in slide.candidates:
            # Reuse is a last resort. Seeing the same portrait five times reads
            # as a broken edit, so any unused option beats any used one.
            adj = c.get("score", 0) - (100.0 if c["id"] in used else 0)
            if adj > best_score:
                best, best_score = c, adj
        slide.chosen_id = best["id"] if best else ""
        if slide.chosen_id:
            used.add(slide.chosen_id)


# ------------------------------------------------------------------- download
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _extension(url: str, content_type: str, kind: str) -> str:
    ext = Path(url.split("?")[0]).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".mp4", ".mov", ".webm"}:
        return ext
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip() or "")
    return guessed or (".mp4" if kind == "video" else ".jpg")


def upgrade(cand: dict) -> dict:
    """Swap a picker-sized preview URL for a render-sized one, in place.

    Search deliberately returns small previews so that browsing options costs
    the archives almost nothing. Only the images actually chosen get promoted,
    and only once — the flag stops a re-render from asking again.
    """
    if cand.get("full") or not cand.get("ref"):
        return cand
    provider = next((p for p in ALL_PROVIDERS if p.name == cand.get("provider")), None)
    if provider is None or not hasattr(provider, "full_url"):
        return cand
    resolved = provider.full_url(cand["ref"])
    if resolved:
        url, w, h = resolved
        cand["url"] = url
        if w and h:
            cand["width"], cand["height"] = w, h
        cand["full"] = True
    return cand


def download_to(cand: dict, dest: Path, stem: str | None = None,
                retries: int = 3) -> str:
    """Fetch one asset into `dest`. Returns the filename written.

    Downloads go through the same rate limiter as searches. Wikimedia's file
    host is a separate service from its API and will 429 an unthrottled batch,
    which used to leave most slides showing an empty slate.
    """
    dest.mkdir(parents=True, exist_ok=True)
    stem = _SAFE.sub("_", stem or f"{cand['provider']}_{cand['id']}")[:60]
    for existing in dest.glob(stem + ".*"):
        if existing.suffix != ".part" and existing.stat().st_size > 0:
            return existing.name

    # A library asset already lives on this machine — a copy, not a fetch, so
    # it costs nothing and can never be rate-limited.
    if cand.get("provider") == "library":
        from .. import library
        src = library.file_path(cand["ref"])
        if not src or not src.is_file():
            raise RuntimeError(f"Library asset {cand.get('ref')} is missing on disk")
        path = dest / f"{stem}{src.suffix}"
        shutil.copyfile(src, path)
        return path.name

    # Note on Wikimedia: only thumbnail widths the API itself generated can be
    # fetched. Hand-derived widths come back 400 ("use thumbnail sizes listed
    # on ..."), so providers must hand us a URL the API produced, and the only
    # fallback is the original file.
    urls = [cand["url"]]

    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        for url in urls:
            try:
                with throttle(cand["provider"]):
                    with client().stream("GET", url) as r:
                        r.raise_for_status()
                        ext = _extension(url, r.headers.get("content-type", ""),
                                         cand["kind"])
                        path = dest / f"{stem}{ext}"
                        tmp = path.with_suffix(path.suffix + ".part")
                        with open(tmp, "wb") as fh:
                            for chunk in r.iter_bytes(65536):
                                fh.write(chunk)
                        tmp.replace(path)
                return path.name
            except Exception as exc:
                last = exc
        if attempt < retries:
            time.sleep(delay)
            delay *= 2.0
    raise last or RuntimeError("download failed")


def download(project: Project, cand: dict, progress: Progress = lambda m: None,
             retries: int = 3) -> str:
    """Fetch one asset into the project's media dir. Returns a relative path."""
    name = download_to(cand, project_dir(project.id) / "media", retries=retries)
    return f"media/{name}"


def download_chosen(project: Project, progress: Progress = lambda m: None,
                     only: list[Slide] | None = None) -> list[str]:
    """Fetch each slide's visual. Returns ids of slides left with none.

    Only the slides in `only` are fetched. Pass the lead of each picture group
    here — a 24-paragraph project set to change every third paragraph then
    downloads eight images, not twenty-four. Firing off one request per slide
    regardless of whether that slide ever reaches the screen is exactly what
    was getting renders rate-limited; `only` is what keeps the request count
    matched to what the cut actually shows. Omitting it downloads for every
    slide in the project, which is almost never what a render wants.

    A candidate that fails after retries (usually a rate limit) does not leave
    the slide on a blank slate: the next-best candidate already found for that
    slide is tried in its place, so a slide only goes blank once every option
    it has has failed.
    """
    slides = only if only is not None else project.slides
    todo = []
    for slide in slides:
        cand = next((c for c in slide.candidates if c["id"] == slide.chosen_id), None)
        if cand and not cand.get("local_path"):
            todo.append(slide)
    if not todo:
        return []

    progress(f"Downloading {len(todo)} asset(s)")
    failed: list[str] = []
    done = 0

    def work(slide: Slide):
        chosen = next(c for c in slide.candidates if c["id"] == slide.chosen_id)
        rest = sorted((c for c in slide.candidates if c["id"] != slide.chosen_id),
                      key=lambda c: c.get("score", 0), reverse=True)
        errors = []
        for cand in [chosen, *rest]:
            if cand.get("local_path"):
                return slide, cand, None
            try:
                upgrade(cand)        # promote to render quality before fetching
                cand["local_path"] = download(project, cand)
                return slide, cand, None
            except Exception as exc:
                errors.append(f"{cand['provider']}: {str(exc)[:60]}")
        return slide, None, errors

    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for slide, cand, errors in pool.map(work, todo):
            done += 1
            if cand is None:
                failed.append(slide.id)
                progress(f"  ! “{(slide.title or slide.narration)[:42]}…”: every "
                         f"candidate failed ({'; '.join(errors[:2])})")
                continue
            if cand["id"] != slide.chosen_id:
                progress(f"  {done}/{len(todo)} fallback: {cand['provider']} → "
                         f"{cand['local_path']}")
                slide.chosen_id = cand["id"]
            else:
                progress(f"  {done}/{len(todo)} {cand['provider']} → {cand['local_path']}")
    return failed


def thumb_cache_path(url: str) -> Path:
    from ..config import CACHE_DIR
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"thumb_{h}"

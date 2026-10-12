"""Map, satellite and establishing-shot visuals, generated from a point.

For a slide about geography rather than a documentable subject — a route
between two towns, how isolated a region is, where a border actually falls —
no archive photograph answers that as well as just showing the place. This
builds one from keyless, no-registration sources: Nominatim (OpenStreetMap's
geocoder) turns a place name into coordinates, `tile.openstreetmap.org` serves
street-map tiles, and Esri serves satellite imagery, terrain shading, and a
transparent place-name/border overlay (composited onto the satellite tiles
for the "hybrid" map type) — all off the same `server.arcgisonline.com` host,
one throttle bucket in `media/base.py`.

Four outputs, all handed back as a plain `MediaCandidate.to_dict()`-shaped
dict with `local_path` already set: a `still` (one mosaic, a pin at the
point), an `establishing_shot` (a continuous zoom-pyramid push toward the
point, translating in rather than jump-cutting between stages), a
`reveal_shot` (the same move played backwards — pull back from the point to
its context), and a `pan_shot` (a lateral drift-and-settle at roughly one
zoom level, no zoom pyramid needed). Every one of them is built the same way
`app/intro.py` builds its slate animations — Pillow frames piped straight
into ffmpeg. None needs anything else built for it: once a candidate has a
`local_path`, the whole existing render path — Ken Burns, the essay format's
boxed slide, grade, vignette, `_clip_source`'s stretch/loop — treats it
exactly like a downloaded photo or clip, because that is structurally what
it now is.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import io
import math
import uuid
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw

from . import ffutil
from .config import FPS, HEIGHT, WIDTH
from .media.base import client, throttle
from .schema import MediaCandidate

Kind = Literal["satellite", "street", "hybrid", "terrain"]

TILE_SIZE = 256
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

# "labels" isn't a public Kind — it's the transparent overlay `hybrid`
# composites onto the satellite base, one tile source among several rather
# than a map type of its own.
_TILE_URLS = {
    "street": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/"
                 "World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "terrain": "https://server.arcgisonline.com/ArcGIS/rest/services/"
               "World_Terrain_Base/MapServer/tile/{z}/{y}/{x}",
    "labels": "https://server.arcgisonline.com/ArcGIS/rest/services/"
              "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
}
_PROVIDER_FOR = {"street": "osm-tile", "satellite": "esri", "terrain": "esri", "labels": "esri"}
ATTRIBUTION = {
    "street": "Map data © OpenStreetMap contributors, ODbL",
    "satellite": "Imagery © Esri, Maxar, Earthstar Geographics",
    "hybrid": "Imagery © Esri, Maxar, Earthstar Geographics; place names © Esri",
    "terrain": "Terrain © Esri, USGS, NOAA",
}


# ------------------------------------------------------------------ geocoding
def geocode(place: str) -> tuple[float, float] | None:
    """`place` resolved to (lat, lon). None — never raises — if it can't be.

    A frontend convenience for jumping the map widget to a typed place —
    the shot generators below take coordinates directly and never call this
    themselves.
    """
    if not place.strip():
        return None
    try:
        with throttle("nominatim"):
            r = client().get(NOMINATIM_URL, params={
                "q": place, "format": "json", "limit": 1,
            })
        r.raise_for_status()
        results = r.json()
    except Exception:
        return None
    if not results:
        return None
    try:
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None


def reverse_geocode(lat: float, lon: float) -> str:
    """A human-readable label for (lat, lon). Falls back to the coordinates
    themselves — never raises — when reverse lookup fails or is inconclusive."""
    fallback = f"{lat:.4f}, {lon:.4f}"
    try:
        with throttle("nominatim"):
            r = client().get(NOMINATIM_REVERSE_URL, params={
                "lat": lat, "lon": lon, "format": "json", "zoom": 12,
            })
        r.raise_for_status()
        result = r.json()
    except Exception:
        return fallback
    name = result.get("display_name") if isinstance(result, dict) else None
    if not name:
        return fallback
    # A full Nominatim address string runs long ("Eiffel Tower, Avenue
    # Gustave Eiffel, 7th Arrondissement, Paris, ..."); the first couple of
    # comma-separated parts read like a place name, the rest doesn't.
    parts = [p.strip() for p in name.split(",") if p.strip()]
    return ", ".join(parts[:2]) if parts else fallback


# ---------------------------------------------------------------------- tiles
def _tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Web Mercator: (lat, lon) at zoom `z` to fractional tile coordinates."""
    lat_rad = math.radians(lat)
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _fetch_raw(source: str, z: int, x: int, y: int, rgba: bool = False) -> Image.Image | None:
    n = 2 ** z
    x, y = x % n, max(0, min(n - 1, y))       # x wraps the date line; y clamps at the poles
    url = _TILE_URLS[source].format(z=z, x=x, y=y)
    try:
        with throttle(_PROVIDER_FOR[source]):
            r = client().get(url)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        return img.convert("RGBA") if rgba else img.convert("RGB")
    except Exception:
        return None


def _fetch_tile(kind: Kind, z: int, x: int, y: int) -> Image.Image | None:
    if kind == "hybrid":
        base = _fetch_raw("satellite", z, x, y)
        if base is None:
            return None
        overlay = _fetch_raw("labels", z, x, y, rgba=True)
        if overlay is not None:
            base = base.convert("RGBA")
            base.alpha_composite(overlay)
            base = base.convert("RGB")
        return base
    return _fetch_raw(kind, z, x, y)


def _mosaic(lat: float, lon: float, z: int, kind: Kind, tiles: int = 3) -> Image.Image:
    """A `tiles`×`tiles` grid of tiles centred on (lat, lon), stitched."""
    cx, cy = _tile_xy(lat, lon, z)
    tx, ty = int(cx), int(cy)
    half = tiles // 2
    mosaic = Image.new("RGB", (tiles * TILE_SIZE, tiles * TILE_SIZE), (30, 30, 32))

    def fetch(args: tuple[int, int]) -> tuple[int, int, Image.Image | None]:
        dx, dy = args
        return dx, dy, _fetch_tile(kind, z, tx + dx, ty + dy)

    coords = [(dx, dy) for dx in range(-half, tiles - half) for dy in range(-half, tiles - half)]
    with cf.ThreadPoolExecutor(max_workers=min(9, len(coords))) as pool:
        for dx, dy, tile in pool.map(fetch, coords):
            if tile is not None:
                mosaic.paste(tile, ((dx + half) * TILE_SIZE, (dy + half) * TILE_SIZE))

    # Where exactly (cx, cy) falls within the centre tile, in mosaic pixels —
    # the pin, and the crop below, both need this rather than just the middle.
    px = (cx - tx + half) * TILE_SIZE
    py = (cy - ty + half) * TILE_SIZE
    return mosaic, (px, py)


# --------------------------------------------------------------------- camera
def _frame(mosaic: Image.Image, point: tuple[float, float], w: int, h: int,
          zoom: float = 1.0, offset: tuple[float, float] = (0.0, 0.0)
          ) -> tuple[Image.Image, tuple[float, float]]:
    """A w×h frame cropped from `mosaic`: covers the frame at zoom=1.0, zooms
    in for zoom>1, and is centred on `point` shifted by `offset` (in
    *output-frame* fractions, so a given offset reads as the same amount of
    on-screen travel regardless of zoom). One `Image.resize(box=...)` call —
    cost is the output size, not the crop size, so this is cheap to call once
    per frame. Returns the frame and where `point` landed on screen; every
    shot composites its pin from that.
    """
    cover = max(w / mosaic.width, h / mosaic.height, 1.0)
    total = max(cover * zoom, w / mosaic.width, h / mosaic.height)
    bw, bh = w / total, h / total
    px, py = point
    ox, oy = offset[0] * bw, offset[1] * bh
    left = min(max(px + ox - bw / 2, 0), max(0, mosaic.width - bw))
    top = min(max(py + oy - bh / 2, 0), max(0, mosaic.height - bh))
    frame = mosaic.resize((w, h), Image.LANCZOS, box=(left, top, left + bw, top + bh))
    screen = ((px - left) * (w / bw), (py - top) * (h / bh))
    return frame, screen


def _pin(size: tuple[int, int], point: tuple[float, float], accent: str) -> Image.Image:
    """A small filled circle with a ring, in the channel's accent colour."""
    from .titles import _hex
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = point
    color = _hex(accent)
    d.ellipse([x - 16, y - 16, x + 16, y + 16], outline=color, width=3)
    d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=color)
    return layer


def _with_pin(frame: Image.Image, screen_point: tuple[float, float],
             accent: str, alpha: float) -> Image.Image:
    if alpha <= 0:
        return frame
    pin = _pin(frame.size, screen_point, accent)
    if alpha < 1.0:
        pin.putalpha(pin.split()[3].point(lambda v: int(v * alpha)))
    return Image.alpha_composite(frame.convert("RGBA"), pin).convert("RGB")


def _safe_stem(place: str) -> str:
    h = hashlib.sha1(place.encode()).hexdigest()[:8]
    return f"map_{h}_{uuid.uuid4().hex[:6]}"


def _candidate(place: str, kind: Kind, local_path: str, media_kind: str,
              width: int, height: int, duration: float = 0.0,
              thumb: str = "") -> dict:
    label = {
        "street": "street map", "satellite": "satellite view",
        "hybrid": "satellite view, labelled", "terrain": "terrain map",
    }[kind]
    title = f"{place} — {label}" if place else label
    cand = MediaCandidate(
        id=f"map{uuid.uuid4().hex[:10]}", provider="maps", kind=media_kind,
        title=title, url="", thumb=thumb,
        source_page="https://www.openstreetmap.org/copyright" if kind == "street"
                    else "https://www.esri.com",
        author="", license=ATTRIBUTION[kind],
        width=width, height=height, duration=duration, query=place,
        # This exists because the writer specifically decided the slide it's
        # for needs a map — not a bare provider weight most archive hits sit
        # under (a typical score is roughly 0-3; `media/base.py:score()` never
        # runs on this candidate to set one, since it isn't a search result).
        # High enough to usually win _autopick, same reasoning `local` uploads
        # get a fixed 3.0 there for the same "this was deliberate" reason —
        # just a shade under it, since an upload is a still more direct choice.
        score=2.6,
    )
    d = cand.to_dict()
    d["local_path"] = local_path
    return d


def _encode(frames, dest: Path, stem: str) -> tuple[Path, int] | None:
    """Pillow frames straight into ffmpeg. `frames` is any iterable of
    same-size RGB images; streamed, never buffered as a whole clip."""
    out_path = dest / f"{stem}.mp4"
    n = ffutil.encode_frames(frames, out_path)
    return (out_path, n) if n else None


# ---------------------------------------------------------------------- still
def still(lat: float, lon: float, zoom: int, kind: Kind, accent: str,
         dest: Path, label: str = "") -> dict | None:
    """One establishing still: a mosaic at `zoom`, pinned at (lat, lon).
    `dest` is the project's media directory it gets saved into."""
    label = label or reverse_geocode(lat, lon)
    mosaic, point = _mosaic(lat, lon, zoom, kind, tiles=3)
    frame, screen = _frame(mosaic, point, WIDTH, HEIGHT)
    frame = _with_pin(frame, screen, accent, 1.0)

    dest.mkdir(parents=True, exist_ok=True)
    name = f"{_safe_stem(label)}.jpg"
    frame.save(dest / name, "JPEG", quality=90)
    return _candidate(label, kind, f"media/{name}", "image", WIDTH, HEIGHT)


# ------------------------------------------------------------- zoom pyramids
# A continuous push toward (or, played backwards, pull back from) a point,
# rather than three hard-cut stages: fetch a handful of mosaics at
# increasing zoom, sweep an "effective zoom" continuously across them, and
# where the sweep crosses from one fetched level into the next, dissolve
# between the two levels' own renders of that *same* effective zoom — both
# represent the same field of view at the crossover, so the seam doesn't
# read as a cut. Meanwhile the crop centre eases in from an offset toward
# the point, so the camera is visibly still travelling, not just scaling in
# place — that's the "translating to the final location" part.
_MIN_ZOOM = 2
_PYRAMID_STEP = 2        # zoom levels between fetched mosaics — smaller steps
                         # means less resolution jump at each dissolve, so the
                         # crossover reads as smooth rather than a soft jerk
_PYRAMID_SPAN = 5        # how far below the final zoom the widest level starts —
                         # kept short so the shot opens already fairly close in,
                         # not a dramatic whole-region establishing pull
_BLEND_FRAC = 0.4        # fraction of each level's span spent dissolving into the next
_OFFSET_MAX = 0.08       # how far off-centre (in frame fractions) the camera starts —
                         # a light drift, not a pan; kept small so it reads as the
                         # zoom settling rather than a distracting sideways slide
_OFFSET_DIR = (-0.78, -0.5)
_PIN_FADE_FRAC = 0.22    # fraction of the clip spent fading the pin in (or, reversed, out)


def _pyramid_levels(end_zoom: int) -> list[int]:
    start = max(_MIN_ZOOM, end_zoom - _PYRAMID_SPAN)
    levels = list(range(start, end_zoom, _PYRAMID_STEP))
    if not levels or levels[-1] != end_zoom:
        levels.append(end_zoom)
    return levels


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _offset_at(te: float, mag: float) -> tuple[float, float]:
    m = mag * (1 - te) ** 1.3
    return (_OFFSET_DIR[0] * m, _OFFSET_DIR[1] * m)


def _safe_offset_mag(mosaic: Image.Image, point: tuple[float, float], w: int, h: int,
                     zoom: float, direction: tuple[float, float] = _OFFSET_DIR) -> float:
    """The largest offset magnitude `_offset_at` can produce at `zoom` without
    `_frame`'s crop needing to clamp against a mosaic edge.

    A real click can land anywhere within its tile, not just dead-centre — so
    the true margin on the side the camera drifts in from can be much
    smaller than the mosaic's overall size suggests, and can even differ a
    lot between two clicks a few pixels apart. Every offset used in this
    module is capped by this rather than a flat constant, because a fixed
    magnitude that happens to fit a centred test point can still silently
    clamp for an off-centre one — and a clamp that only bites on one axis
    (typically the wider one, against a 16:9 frame) is exactly what reads as
    the camera drifting one way, then swerving into the other once the
    clamp releases, rather than one continuous diagonal drift.
    """
    cover = max(w / mosaic.width, h / mosaic.height, 1.0)
    total = max(cover * zoom, w / mosaic.width, h / mosaic.height)
    bw, bh = w / total, h / total
    px, py = point

    def axis(p: float, b: float, extent: float, d: float) -> float:
        if abs(d) < 1e-9:
            return float("inf")
        bound = (extent - b - p + b / 2) if d > 0 else -(p - b / 2)
        return max(0.0, bound / (d * b))

    return min(axis(px, bw, mosaic.width, direction[0]),
              axis(py, bh, mosaic.height, direction[1]))


def _pin_alpha(te: float) -> float:
    return max(0.0, min(1.0, (te - (1 - _PIN_FADE_FRAC)) / _PIN_FADE_FRAC))


def _flight_frame(levels: list[int], mosaics: dict[int, tuple[Image.Image, tuple[float, float]]],
                  start_zoom: int, end_zoom: int, te: float, accent: str,
                  offset_mag: float) -> Image.Image:
    e = start_zoom + (end_zoom - start_zoom) * te
    lo = max(l for l in levels if l <= e)
    higher = [l for l in levels if l > lo]
    hi = higher[0] if higher else lo
    offset = _offset_at(te, offset_mag)

    img_lo, pt_lo = mosaics[lo]
    frame, screen = _frame(img_lo, pt_lo, WIDTH, HEIGHT, zoom=2 ** (e - lo), offset=offset)

    if hi != lo:
        frac = (e - lo) / (hi - lo)
        if frac >= 1 - _BLEND_FRAC:
            img_hi, pt_hi = mosaics[hi]
            f_hi, screen_hi = _frame(img_hi, pt_hi, WIDTH, HEIGHT, zoom=2 ** (e - hi), offset=offset)
            a = (frac - (1 - _BLEND_FRAC)) / _BLEND_FRAC
            frame = Image.blend(frame, f_hi, a)
            if a > 0.5:
                screen = screen_hi

    return _with_pin(frame, screen, accent, _pin_alpha(te))


def _flight(lat: float, lon: float, end_zoom: int, kind: Kind, accent: str,
           dest: Path, label: str, seconds: float, reverse: bool) -> dict | None:
    label = label or reverse_geocode(lat, lon)
    levels = _pyramid_levels(end_zoom)
    start_zoom = levels[0]
    mosaics = {z: _mosaic(lat, lon, z, kind, tiles=5) for z in levels}
    # The widest level at its own native (unzoomed) crop is where the offset
    # is largest (te=0) *and* the margin to hold it is tightest — every other
    # moment in the clip has either less offset to place or more room for it
    # (later levels are always reached at a smaller te, once the offset has
    # already eased down), so this one check covers the whole flight.
    offset_mag = min(_OFFSET_MAX, _safe_offset_mag(*mosaics[start_zoom], WIDTH, HEIGHT, zoom=1.0))
    n = max(2, round(seconds * FPS))

    def frames():
        for i in range(n):
            t = i / max(1, n - 1)
            if reverse:
                t = 1 - t
            yield _flight_frame(levels, mosaics, start_zoom, end_zoom, _ease(t), accent, offset_mag)

    dest.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(label)
    result = _encode(frames(), dest, stem)
    if not result:
        return None
    out_path, n_written = result

    # A poster frame for the picker grid: an <img> tag can't render an mp4.
    # The clip's final, fully-arrived view — pin lit — is the most
    # informative single frame of it.
    poster = _flight_frame(levels, mosaics, start_zoom, end_zoom, 1.0, accent, offset_mag)
    poster_name = f"{stem}_poster.jpg"
    poster.save(dest / poster_name, "JPEG", quality=88)

    return _candidate(label, kind, f"media/{out_path.name}", "video", WIDTH, HEIGHT,
                      duration=round(n_written / FPS, 2), thumb=f"media/{poster_name}")


def establishing_shot(lat: float, lon: float, zoom: int, kind: Kind, accent: str,
                      dest: Path, label: str = "") -> dict | None:
    """A continuous push from wide context down to (lat, lon) at `zoom`."""
    return _flight(lat, lon, zoom, kind, accent, dest, label, seconds=7.0, reverse=False)


def reveal_shot(lat: float, lon: float, zoom: int, kind: Kind, accent: str,
                dest: Path, label: str = "") -> dict | None:
    """The establishing shot's move, played backwards: starts tight and
    pin-lit on (lat, lon), pulls back to reveal its wider context."""
    return _flight(lat, lon, zoom, kind, accent, dest, label, seconds=5.0, reverse=True)


# -------------------------------------------------------------------- pan
def pan_shot(lat: float, lon: float, zoom: int, kind: Kind, accent: str,
            dest: Path, label: str = "", seconds: float = 5.0) -> dict | None:
    """A lighter shot than the zoom pyramids above: one mosaic at `zoom`, a
    camera that drifts in from off-centre and settles on the point, with a
    faint zoom-in for a little life — no pyramid levels to fetch or blend."""
    label = label or reverse_geocode(lat, lon)
    # An odd tile count so the mosaic is symmetric around the clicked point —
    # an even count leaves more margin on one side than the other, which can
    # clamp the crop off-centre right when the camera is meant to be settling
    # dead-on the pin.
    mosaic, point = _mosaic(lat, lon, zoom, kind, tiles=5)
    n = max(2, round(seconds * FPS))
    # zoom starts a little tighter than bare cover (1.0) on purpose: at
    # exactly 1.0 a wide 16:9 frame against a roughly square mosaic has zero
    # horizontal slack to offset into, so any offset would be clamped away
    # on that axis until the zoom-in opens up room for it. Zoom only
    # increases from there (a proper "faint zoom-in for life"), so this
    # starting point is also the tightest margin the whole clip ever has —
    # capping the offset against it, once, is enough for every later frame.
    _PAN_ZOOM0 = 1.15
    offset_mag = min(0.15, _safe_offset_mag(mosaic, point, WIDTH, HEIGHT, zoom=_PAN_ZOOM0))

    def frame_at(te: float) -> Image.Image:
        frame, screen = _frame(mosaic, point, WIDTH, HEIGHT,
                               zoom=_PAN_ZOOM0 + 0.10 * te, offset=_offset_at(te, offset_mag))
        return _with_pin(frame, screen, accent, _pin_alpha(te))

    def frames():
        for i in range(n):
            yield frame_at(_ease(i / max(1, n - 1)))

    dest.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(label)
    result = _encode(frames(), dest, stem)
    if not result:
        return None
    out_path, n_written = result

    poster_name = f"{stem}_poster.jpg"
    frame_at(1.0).save(dest / poster_name, "JPEG", quality=88)

    return _candidate(label, kind, f"media/{out_path.name}", "video", WIDTH, HEIGHT,
                      duration=round(n_written / FPS, 2), thumb=f"media/{poster_name}")

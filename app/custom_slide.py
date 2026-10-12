"""Slides whose shape nobody anticipated — a spec in, a styled, animated frame
out, the same deal `app/diagram.py` makes for a diagram.

Nine diagram layouts and ten board templates cover a lot, but not everything a
paragraph wants: a pull-quote over a photo, a scoreboard of three numbers, a
single word taking the whole frame. This module trades the diagram's fixed
vocabulary (nodes, edges) for a free one — a handful of positioned elements,
each a box of text, a shape, or a photo pulled from the archives, each on its
own reveal beat with its own way of arriving. Claude (or a person) can
describe a layout no template saw coming, because the spec does not know what
a "layout" is — it only knows where things sit and when they appear.

Reuses `app/diagram.py`'s board (the grey-blue ground, the grain), its beat
scheduler (`schedule`/`reveal_at` — the same "draws in, then holds" timing),
and `app/titles.py`'s bundled font stacks, so a custom slide sits in the same
visual family as a diagram or a board template rather than looking like a
fourth, unrelated thing. A finished slide is handed back as a plain
`MediaCandidate`-shaped dict with `local_path` set, exactly like a diagram or
a downloaded photo, so the rest of the render path needs to know nothing
about it.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from . import diagram, ffutil, titles
from .config import FPS, HEIGHT, WIDTH
from .schema import MediaCandidate

DEFAULT_HAND = diagram.DEFAULT_HAND
DEFAULT_SECONDS = 6.0

SIZE_PX = {"sm": 30, "md": 44, "lg": 64, "xl": 92, "xxl": 170}
ANIM_KEYS = {"fade", "rise", "fly-left", "fly-right", "pop", "none"}
TYPE_KEYS = {"text", "rect", "circle", "line", "image"}
FONT_KEYS = {"hand", "sans", "serif", "mono", "display"}
ANIMS = [
    {"key": "fade", "label": "Fade in"},
    {"key": "rise", "label": "Rise — drifts up into place"},
    {"key": "fly-left", "label": "Fly in from the left"},
    {"key": "fly-right", "label": "Fly in from the right"},
    {"key": "pop", "label": "Pop — a quick snap in"},
    {"key": "none", "label": "Already there — no entrance"},
]

SPEC_DOC = """A custom slide spec is one JSON object:

{"background": "" for the default board, or a hex colour,
 "elements": [
   {"type": "text",
    "text": "the words — as short as a slide can carry",
    "x": 0.08, "y": 0.08, "w": 0.5, "h": 0.22,
    "size": "sm" | "md" | "lg" | "xl" | "xxl",
    "align": "left" | "center" | "right",
    "color": "#ffffff" or a hex colour,
    "font": "hand" | "sans" | "serif" | "mono" | "display",
    "order": 0, "anim": "fade" | "rise" | "fly-left" | "fly-right" | "pop" | "none"},
   {"type": "rect" | "circle" | "line",
    "x": .., "y": .., "w": .., "h": ..,
    "color": "#E8C36A", "fill": true, "stroke": 4,
    "opacity": 1, "order": 1, "anim": "fade"},
   {"type": "image",
    "query": "a short, specific search for an archive photo — written like a "
             "caption, e.g. \\"Apollo 11 launch pad 1969\\", not \\"rocket\\"",
    "x": .., "y": .., "w": .., "h": ..,
    "fit": "cover" | "contain",
    "order": 0, "anim": "fade"}
 ]}

Rules that matter:
- x and y are the element's top-left corner; w and h are its size. All four
  are a fraction of the frame, 0 to 1 — (0,0) is the top-left corner of the
  whole slide, (1,1) the bottom-right. Elements may overlap on purpose: a
  text box sitting over an image is how a caption works.
- 1-10 elements. A slide this busy gets skimmed, not read — say less, bigger.
- `order` groups what arrives together; put the same order on two elements
  to land them in one beat. Beats draw in across the clip, low numbers
  first, then hold — the same pacing a diagram uses.
- An "image" element searches the archives for `query`. Write it like a
  photo caption, specific enough to actually find the right thing.
- "xxl" is for one number or one word carrying the whole frame — give it a
  wide, tall box (w about 0.9, h about 0.4) or it will shrink to fit.
- `opacity` (0 to 1, on any element) is how you make text readable over a
  photo: lay a filled black rect at about 0.5 across the lower third, then
  put the text on top of it.
- Never restate the narration word for word as on-screen text. Show what the
  voice can't — a number, a label, a face, a place — not a repeat of it.
- Reach for this when nothing else fits the paragraph: a diagram draws a
  shape, a board template draws a point, but a quote over a photo, a single
  giant number, or a scoreboard of three stats has no other home."""


def _stack(font: str, hand: str) -> list[tuple[str, int]]:
    if font == "sans":
        return titles.FONT_STACK
    if font == "serif":
        return titles.SERIF_STACK
    if font == "mono":
        return titles.MONO_STACK
    if font == "display":
        return titles.DISPLAY_STACK
    return diagram.hand_stack(hand)


_PROBE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def _wrap(text: str, font, max_w: float) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines, cur = [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if _PROBE.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def _fit_text(text: str, stack, max_w: float, max_h: float, start_size: int
              ) -> tuple[object, list[str], float]:
    size = start_size
    while size > 14:
        font = titles._load(stack, size)
        lines = _wrap(text, font, max_w)
        line_h = size * 1.22
        if line_h * len(lines) <= max_h and all(
                _PROBE.textlength(l, font=font) <= max_w for l in lines):
            return font, lines, line_h
        size = int(size * 0.92)
    font = titles._load(stack, 14)
    return font, _wrap(text, font, max_w), 14 * 1.22


def _fit_image(img: Image.Image, w: int, h: int, fit: str) -> Image.Image:
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return Image.new("RGB", (w, h), (40, 44, 52))
    if fit == "contain":
        scale = min(w / iw, h / ih)
        nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
        resized = img.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (w, h), (20, 22, 27))
        canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
        return canvas
    scale = max(w / iw, h / ih)
    nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - w) // 2, (nh - h) // 2
    return resized.crop((x0, y0, x0 + w, y0 + h))


# ------------------------------------------------------------------ the spec
def _clamp01(v, default: float) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


def normalise(spec: dict | str) -> dict:
    """Clean a spec written by a person or a model into something drawable.

    Forgiving on purpose, the same way `diagram.normalise` is: an element
    missing a field gets a sane default rather than an error, and anything
    unrecognisable is dropped rather than failing the whole slide.
    """
    if isinstance(spec, str):
        spec = json.loads(spec)
    if not isinstance(spec, dict):
        raise ValueError("A custom slide spec is a JSON object.")
    raw_elements = spec.get("elements") or []
    if isinstance(raw_elements, dict):
        raw_elements = [raw_elements]
    if not isinstance(raw_elements, list):
        raise ValueError("`elements` must be a list.")
    elements: list[dict] = []
    for i, raw in enumerate(raw_elements[:10]):
        if not isinstance(raw, dict):
            continue
        t = str(raw.get("type") or "").strip().lower()
        if t not in TYPE_KEYS:
            continue
        order = raw.get("order")
        el = {
            "type": t,
            "x": _clamp01(raw.get("x"), 0.1),
            "y": _clamp01(raw.get("y"), 0.1),
            "w": max(0.03, _clamp01(raw.get("w"), 0.3)),
            "h": max(0.03, _clamp01(raw.get("h"), 0.2)),
            "order": int(order) if isinstance(order, (int, float)) else i,
            "anim": str(raw.get("anim") or "fade").strip().lower(),
            "opacity": _clamp01(raw.get("opacity"), 1.0),
        }
        if el["anim"] not in ANIM_KEYS:
            el["anim"] = "fade"
        if t == "text":
            el["text"] = str(raw.get("text") or "").strip()[:200]
            if not el["text"]:
                continue
            size = str(raw.get("size") or "md").strip().lower()
            el["size"] = size if size in SIZE_PX else "md"
            align = str(raw.get("align") or "left").strip().lower()
            el["align"] = align if align in ("left", "center", "right") else "left"
            el["color"] = str(raw.get("color") or "#ffffff").strip()[:20] or "#ffffff"
            font = str(raw.get("font") or "hand").strip().lower()
            el["font"] = font if font in FONT_KEYS else "hand"
        elif t in ("rect", "circle", "line"):
            el["color"] = str(raw.get("color") or "#E8C36A").strip()[:20] or "#E8C36A"
            el["fill"] = bool(raw.get("fill", True))
            try:
                el["stroke"] = max(1, min(20, int(raw.get("stroke") or 4)))
            except (TypeError, ValueError):
                el["stroke"] = 4
        elif t == "image":
            el["query"] = str(raw.get("query") or "").strip()[:140]
            el["local_path"] = str(raw.get("local_path") or "").strip()[:160]
            if not el["query"] and not el["local_path"]:
                continue
            fit = str(raw.get("fit") or "cover").strip().lower()
            el["fit"] = fit if fit in ("cover", "contain") else "cover"
        elements.append(el)
    if not elements:
        raise ValueError("A custom slide needs at least one element.")
    reveal = "all" if str(spec.get("reveal") or "").lower() == "all" else "sequence"
    return {
        "background": str(spec.get("background") or "").strip()[:20],
        "elements": elements,
        "reveal": reveal,
    }


# --------------------------------------------------------------- image fetch
def resolve_images(spec: dict, dest: Path) -> dict:
    """Fetch an archive photo for every image element that only has a query.

    Mutating a *copy*: the resolved spec — with `local_path` filled in — is
    what gets saved back onto the slide, so re-rendering the same spec (a
    colour tweak, a different animation) never re-fetches. The same deal
    `app/intro.py` makes for cast portraits.
    """
    from . import media

    elements = [dict(e) for e in spec.get("elements", [])]
    for el in elements:
        if el["type"] != "image" or el.get("local_path") or not el.get("query"):
            continue
        try:
            found = media.search([el["query"]], "image", limit=3, allow_stock=False)
            if not found:
                found = media.search([el["query"]], "image", limit=3, allow_stock=True)
            if not found:
                continue
            cand = media.upgrade(found[0].to_dict())
            stem = f"custom_img_{hashlib.sha1(el['query'].encode()).hexdigest()[:10]}"
            el["local_path"] = media.download_to(cand, dest, stem=stem)
            el["source_page"] = cand.get("source_page", "")
            el["author"] = cand.get("author", "")
        except Exception:
            continue
    return {**spec, "elements": elements}


# ------------------------------------------------------------------- layout
def _layout(spec: dict) -> list[dict]:
    out = []
    for el in spec["elements"]:
        out.append({**el,
                    "_x": round(el["x"] * WIDTH), "_y": round(el["y"] * HEIGHT),
                    "_w": max(8, round(el["w"] * WIDTH)),
                    "_h": max(8, round(el["h"] * HEIGHT))})
    return out


def _build_tile(el: dict, hand: str, media_root: Path | None) -> Image.Image:
    """The element at full opacity, sized to its own box — built once, then
    faded and shifted per frame rather than redrawn."""
    w, h = el["_w"], el["_h"]
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if el["type"] == "text":
        stack = _stack(el["font"], hand)
        font, lines, line_h = _fit_text(el["text"], stack, w, h, SIZE_PX[el["size"]])
        draw = ImageDraw.Draw(tile, "RGBA")
        color = titles._hex(el["color"])
        ax = {"left": 0, "center": w / 2, "right": w}[el["align"]]
        anchor = {"left": "l", "center": "m", "right": "r"}[el["align"]] + "t"
        y = 0.0
        for line in lines:
            draw.text((ax, y), line, font=font, fill=color, anchor=anchor)
            y += line_h
    elif el["type"] in ("rect", "circle", "line"):
        draw = ImageDraw.Draw(tile, "RGBA")
        color = titles._hex(el["color"])
        sw = el["stroke"]
        if el["type"] == "rect":
            if el["fill"]:
                draw.rectangle([0, 0, w - 1, h - 1], fill=color)
            else:
                draw.rectangle([sw / 2, sw / 2, w - 1 - sw / 2, h - 1 - sw / 2],
                               outline=color, width=sw)
        elif el["type"] == "circle":
            if el["fill"]:
                draw.ellipse([0, 0, w - 1, h - 1], fill=color)
            else:
                draw.ellipse([sw / 2, sw / 2, w - 1 - sw / 2, h - 1 - sw / 2],
                             outline=color, width=sw)
        else:
            draw.line([0, h / 2, w - 1, h / 2], fill=color, width=sw)
    elif el["type"] == "image" and el.get("local_path") and media_root:
        path = media_root / el["local_path"]
        if path.is_file():
            try:
                img = Image.open(path).convert("RGB")
                fitted = _fit_image(img, w, h, el["fit"])
                tile.paste(fitted.convert("RGBA"), (0, 0))
            except Exception:
                pass
    # A translucent element — a dark scrim under text over a photo is the
    # reason this exists — is baked into the tile, so the per-frame fade
    # multiplies against it rather than fighting it.
    if el["opacity"] < 0.999:
        tile.putalpha(tile.getchannel("A").point(
            lambda v: int(v * el["opacity"])))
    return tile


def _anim(kind: str, f: float) -> tuple[float, int, int]:
    """Alpha and a pixel offset for how far into its entrance this element is."""
    if kind == "rise":
        return f, 0, round((1 - f) * 46)
    if kind == "fly-left":
        return f, -round((1 - f) * 240), 0
    if kind == "fly-right":
        return f, round((1 - f) * 240), 0
    if kind == "pop":
        return min(1.0, f * 1.4), 0, 0
    return f, 0, 0


def _faded(tile: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return tile
    out = tile.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * alpha)))
    return out


# -------------------------------------------------------------------- output
def render_still(spec: dict, hand: str = DEFAULT_HAND,
                 media_root: Path | None = None, grain: float = 0.5) -> Image.Image:
    """The finished slide, every element at full opacity, in place."""
    spec = normalise(spec)
    base = diagram.ground(spec["background"] or diagram.GROUND, grain).convert("RGBA")
    for el in _layout(spec):
        base.alpha_composite(_build_tile(el, hand, media_root), (el["_x"], el["_y"]))
    return base.convert("RGB")


def frames(spec: dict, seconds: float, hand: str = DEFAULT_HAND,
          media_root: Path | None = None, grain: float = 0.5):
    """The slide arriving, beat by beat, as RGB frames at `FPS`.

    Elements marked "none" skip the reveal entirely and are painted into the
    base before frame one — a background photo shouldn't fade in on its own
    schedule, it should just be there. Everything else settles into the base
    once its beat finishes, the same cost-saving trick `diagram.frames` uses.
    """
    spec = normalise(spec)
    elements = _layout(spec)
    tiles = [_build_tile(el, hand, media_root) for el in elements]
    base = diagram.ground(spec["background"] or diagram.GROUND, grain).convert("RGBA")

    live = [i for i, el in enumerate(elements) if el["anim"] != "none"]
    for i, el in enumerate(elements):
        if el["anim"] == "none":
            base.alpha_composite(tiles[i], (el["_x"], el["_y"]))

    orders = sorted({elements[i]["order"] for i in live})
    beats = len(orders)
    order_index = {o: i for i, o in enumerate(orders)}
    plan = diagram.schedule(beats, seconds, spec["reveal"])
    settled = 0
    total = max(2, int(round(seconds * FPS)))
    for frame_i in range(total):
        t = frame_i / FPS
        reveal = diagram.reveal_at(plan, t)
        done = settled
        while done < beats and reveal.get(done, 0.0) >= 1.0:
            done += 1
        if done > settled:
            for i in live:
                oi = order_index[elements[i]["order"]]
                if settled <= oi < done:
                    base.alpha_composite(tiles[i], (elements[i]["_x"], elements[i]["_y"]))
            settled = done
        frame = base.copy()
        for i in live:
            el = elements[i]
            oi = order_index[el["order"]]
            if oi < settled:
                continue
            f = reveal.get(oi, 0.0)
            if f <= 0.001:
                continue
            alpha, dx, dy = _anim(el["anim"], f)
            frame.alpha_composite(_faded(tiles[i], alpha), (el["_x"] + dx, el["_y"] + dy))
        yield frame.convert("RGB")


def _title_text(spec: dict) -> str:
    for el in spec["elements"]:
        if el["type"] == "text":
            return el["text"][:48]
    return "custom slide"


def candidate(spec: dict, dest: Path, *, motion: str = "reveal",
             seconds: float = DEFAULT_SECONDS, hand: str = DEFAULT_HAND,
             grain: float = 0.5) -> dict | None:
    """Render a spec into `dest` and hand back a media candidate for it.

    Shaped exactly like `diagram.candidate()` — a `MediaCandidate`-shaped
    dict with `local_path` set, so the rest of the render path stages it the
    same as any downloaded photograph. Fetches any image elements' archive
    photos first, so the spec saved back onto the slide is the resolved one.
    """
    spec = normalise(spec)
    dest.mkdir(parents=True, exist_ok=True)
    spec = resolve_images(spec, dest)
    stem = f"custom_{uuid.uuid4().hex[:10]}"
    title = _title_text(spec)
    poster = ""
    if motion == "still":
        out = dest / f"{stem}.png"
        render_still(spec, hand=hand, media_root=dest, grain=grain).save(out)
        kind, local = "image", out.name
        duration = 0.0
    else:
        out = dest / f"{stem}.mp4"
        seconds = max(2.0, min(20.0, float(seconds)))
        n = ffutil.encode_frames(
            frames(spec, seconds, hand=hand, media_root=dest, grain=grain), out)
        if not n:
            return None
        kind, local = "video", out.name
        duration = round(n / FPS, 3)
        shot = dest / f"{stem}_poster.jpg"
        render_still(spec, hand=hand, media_root=dest, grain=grain).save(shot, quality=88)
        poster = f"media/{shot.name}" if dest.name == "media" else shot.name
    cand = MediaCandidate(
        id=f"custom_{uuid.uuid4().hex[:8]}",
        provider="custom",
        kind=kind,
        title=f"{title} — custom slide",
        source_page="",
        author="designed here",
        license="yours",
        width=WIDTH,
        height=HEIGHT,
        duration=duration,
        # Above every search hit, the same deal a diagram gets: this was
        # asked for by name, not found by a guess at a query.
        score=3.0,
        query="custom",
        thumb=poster,
    )
    d = cand.to_dict()
    d["local_path"] = f"media/{local}" if dest.name == "media" else local
    d["custom"] = spec
    return d

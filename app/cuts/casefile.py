"""Casefile: the evidence board.

A corkboard under one warm lamp. Every cue is something pinned to it — the
paragraph's picture as a polaroid, a typed index card, a newspaper clipping, a
sticky note, a redacted page whose black bar slides off — and the camera
drifts over to each one as the narrator reaches it, and it is pinned up. Earlier items stay up, slightly soft, so the
web gets denser as the case goes on. At the end of the video the camera pulls
back to show the whole board.

The board carries across paragraphs: segment N draws everything paragraphs
before it pinned, rebuilt from their cues, so the cut can be rendered in
parallel and still read as one continuous board. It starts afresh at a
chapter, or when it fills up.

Built for true crime, unsolved mysteries, corporate scandals and
how-it-went-wrong deep dives.
"""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import kit

KEY = "casefile"
LABEL = "Casefile"
FOR = "True crime, mysteries, scandals"
BLURB = ("A lamp-lit corkboard. Polaroids, clippings and typed cards pinned up "
         "as you talk. The board carries over the whole case.")
LOOKS = [{"key": "", "label": "Cork"}, {"key": "wall", "label": "Dark wall"},
         {"key": "felt", "label": "Green felt"}]
FALLBACK_KIND = "card"
MIN_HOLD = 1.6

KINDS = {"photo", "card", "clipping", "note", "redacted"}

PLAN = """The format is an evidence board: a dark corkboard under one warm lamp.
Each cue PINS ONE ITEM to the board as the narrator reaches it. Earlier items
stay up for the whole case, so the board fills up as the story goes.

Cue kinds — every cue is an object with "kind", "on" and the fields listed:
- {"kind": "photo", "caption": "2-5 words, handwritten under it"}
  The paragraph's own picture as a polaroid. At most one per paragraph.
- {"kind": "card", "title": "a date, a name or a place", "text": "max 14 words"}
  A typed index card. The workhorse for names, dates, times, facts.
- {"kind": "clipping", "headline": "a newspaper-style headline, max 8 words",
   "text": "one sentence of the story, max 20 words"}
- {"kind": "note", "text": "a handwritten question or hunch, max 8 words"}
  A sticky note. "Who called at 2am?" "Same car?"
- {"kind": "redacted", "title": "a document name", "text": "the line revealed, max 12 words"}
  A page with a black bar that slides off to show the line.

Rules: 1-3 cues per paragraph — the camera needs time to travel. Never invent
facts: headlines and cards restate what the narration says. Clippings are
paraphrased as a headline, not presented as a real publication's words."""

KIND_DOC = "photo · card · clipping · note · redacted"

WORLD_W, WORLD_H = 4608, 2592
COLS, ROWS = 5, 3
PER_BOARD = COLS * ROWS - 1
# The board behind the item in focus is drawn at this fraction of the frame's
# scale. It is blurred out of focus anyway, and at 4.6K wide it is the
# dominant cost of the cut: every frame is a resize out of it.
WORLD_SCALE = 0.6
RED = (178, 28, 34, 255)


def _s(v, n):
    return str(v or "").strip()[:n]


def normalise(c: dict) -> dict | None:
    kind = str(c.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None
    if kind == "photo":
        return {"kind": kind, "caption": _s(c.get("caption"), 40)}
    if kind == "card":
        text = _s(c.get("text"), 110)
        return {"kind": kind, "title": _s(c.get("title"), 30), "text": text} if (
            text or c.get("title")) else None
    if kind == "clipping":
        head = _s(c.get("headline"), 70)
        return {"kind": kind, "headline": head,
                "text": _s(c.get("text"), 160)} if head else None
    if kind == "note":
        text = _s(c.get("text"), 60)
        return {"kind": kind, "text": text} if text else None
    if kind == "redacted":
        text = _s(c.get("text"), 90)
        return {"kind": kind, "title": _s(c.get("title"), 30) or "Case file",
                "text": text} if text else None
    return None


def derive(slide) -> list[dict]:
    parts = kit.clauses(slide.narration, max_words=14, min_words=5)
    cues: list[dict] = [{"kind": "photo", "caption": kit.short(slide.title or parts[0] if parts else "", 4),
                         "on": ""}]
    if len(parts) > 1:
        mid = parts[len(parts) // 2]
        cues.append({"kind": "card", "title": kit.keyword(mid).upper()[:20],
                     "text": kit.short(mid, 12), "on": kit.head(mid)})
    if len(parts) > 3:
        last = parts[-1]
        if last.rstrip().endswith("?"):
            cues.append({"kind": "note", "text": kit.short(last, 7), "on": kit.head(last)})
    return cues


# ------------------------------------------------------------------- items
def _paper(st: kit.Stage, w, h, color, edge=None):
    st.rect(0, 0, w, h, fill=color)
    if edge:
        st.rect(0, 0, w, h, outline=edge, width=2)


def _item(cue: dict, picture, k: float, f: float = 1.0) -> Image.Image:
    """One pinned thing, drawn flat. `f` is how far its reveal has got."""
    kind = cue["kind"]
    if kind == "photo":
        w, h = 600, 700
        st = kit.Stage.sized(w, h, k)
        rng = random.Random(str(cue.get("caption")))
        _paper(st, w, h, rng.choice([(240, 236, 226, 255), (236, 232, 220, 255),
                                     (244, 242, 236, 255)]))
        if picture is not None:
            st.img.paste(kit.cover(picture, st.p(540), st.p(520)).convert("RGBA"),
                         (st.p(30), st.p(30)))
            # Faded print: lift the blacks and warm it.
            st.wash(30, 30, 570, 550, (255, 220, 170, 34))
            if rng.random() < 0.3:      # a black-and-white print
                grey = ImageOps.grayscale(st.img.crop(st.box(30, 30, 570, 550))).convert("RGBA")
                st.img.paste(grey, (st.p(30), st.p(30)))
        else:
            st.rect(30, 30, 570, 550, fill=(40, 38, 36, 255))
            st.text((300, 290), "NO PHOTO", "typewriter", 34, (120, 116, 108), anchor="mm")
        if cue.get("caption"):
            size, lines = kit.fit(cue["caption"], "hand", 64, 520, 1, floor=30)
            st.text((300, 625), lines[0] if lines else "", "hand", size,
                    rng.choice([(30, 34, 70), (28, 28, 30), (60, 30, 40)]), anchor="mm")
        if rng.random() < 0.35:         # taped at the corner as well as pinned
            _tape(st, rng.choice([70, w - 70]), 22, rng.uniform(-35, 35) )
        return st.img
    if kind == "card":
        w, h = 680, 420
        st = kit.Stage.sized(w, h, k)
        rng = random.Random(str(cue.get("title")) + str(cue.get("text")))
        _paper(st, w, h, rng.choice([(246, 242, 230, 255), (240, 244, 238, 255),
                                     (248, 238, 214, 255)]))
        st.rect(0, 92, w, 95, fill=rng.choice([(214, 92, 92, 255), (92, 120, 200, 255),
                                              (70, 150, 110, 255)]))
        for y in range(146, h - 20, 50):
            st.rect(0, y, w, y + 2, fill=(150, 180, 214, 255))
        st.text((40, 50), cue.get("title", "").upper(), "mono_bold", 44, (36, 36, 40), anchor="lm")
        text = cue.get("text", "")
        lines = kit.wrap(text, "typewriter", 36, w - 80)[:5]
        total = sum(len(l) for l in lines)
        budget = int(round(total * kit.clamp(f)))
        for i, line in enumerate(lines):
            shown = line[:max(0, budget)]
            budget -= len(line)
            st.text((40, 140 + i * 50), shown, "typewriter", 36, (40, 40, 46), anchor="ls")
        return st.img
    if kind == "clipping":
        w, h = 600, 640
        st = kit.Stage.sized(w, h, k)
        rng = random.Random(cue.get("headline"))
        _paper(st, w, h, rng.choice([(226, 222, 208, 255), (222, 214, 190, 255),
                                     (232, 230, 222, 255)]))
        size, lines = kit.fit(cue["headline"].upper(), "condensed", 74, w - 70, 3, floor=34)
        y = 46
        for line in lines:
            st.text((35, y), line, "condensed", size, (22, 22, 24), anchor="lt")
            y += size * 1.05
        hl = kit.ease_out(kit.progress(f, 0.45, 0.5))
        if hl > 0:
            st.wash(28, 40, 28 + (w - 56) * hl, y + 4, (255, 222, 40, 110))
        y += 26
        body = kit.wrap(cue.get("text", ""), "serif", 32, w - 70)[:4]
        for line in body:
            st.text((35, y), line, "serif", 32, (40, 40, 40), anchor="lt")
            y += 40
        # The rest of the column is filler print, ruled rather than written.
        while y < h - 40:
            st.rect(35, y + 10, 35 + rng.uniform(0.6, 1.0) * (w - 70), y + 22,
                    fill=(150, 146, 136, 255))
            y += 34
        return st.img
    if kind == "note":
        w = h = 440
        st = kit.Stage.sized(w, h, k)
        paper, band = random.Random(cue["text"]).choice([
            ((250, 218, 84, 255), (240, 204, 70, 255)),
            ((248, 176, 190, 255), (236, 160, 176, 255)),
            ((170, 214, 240, 255), (152, 198, 228, 255))])
        _paper(st, w, h, paper)
        st.rect(0, 0, w, 50, fill=band)
        size, lines = kit.fit(cue["text"], "marker", 64, w - 70, 4, floor=28)
        top = h / 2 + 20 - len(lines) * size * 0.6
        for i, line in enumerate(lines):
            st.text((w / 2, top + i * size * 1.2), line, "marker", size, (30, 30, 50), anchor="mm")
        return st.img
    # redacted
    w, h = 580, 720
    st = kit.Stage.sized(w, h, k)
    _paper(st, w, h, (238, 238, 232, 255))
    st.text((40, 50), cue.get("title", "").upper(), "mono_bold", 32, (30, 30, 30), anchor="lm")
    st.text((w - 40, 50), "CONFIDENTIAL", "mono_bold", 22, (170, 30, 30), anchor="rm")
    st.rect(40, 80, w - 40, 83, fill=(30, 30, 30, 255))
    rng = random.Random(cue["text"])
    y = 120
    target = 120 + 4 * 44
    while y < h - 40:
        if y == target:
            lines = kit.wrap(cue["text"], "typewriter", 32, w - 80)[:3]
            for i, line in enumerate(lines):
                st.text((40, y + i * 44 + 24), line, "typewriter", 32, (20, 20, 20), anchor="ls")
            band = len(lines) * 44
            slide = kit.ease_in_out(kit.progress(f, 0.25, 0.6))
            x0 = 34 + (w - 68) * slide
            st.rect(x0, y - 6, x0 + (w - 68), y + band - 10, fill=(10, 10, 10, 255))
            y += band
            continue
        if rng.random() < 0.35:
            st.rect(40, y, 40 + rng.uniform(0.3, 0.9) * (w - 80), y + 28, fill=(14, 14, 14, 255))
        else:
            st.rect(40, y + 10, 40 + rng.uniform(0.5, 1.0) * (w - 80), y + 20,
                    fill=(120, 120, 120, 255))
        y += 44
    return st.img


def _finish(flat: Image.Image, angle: float, k: float,
            shadow: Image.Image | None = None) -> Image.Image:
    """Rotate and shadow a flat item, centred in its tile.

    The shadow depends only on the item's outline, so a caller redrawing an
    item mid-reveal passes the one it already has rather than blurring a new
    one every frame.
    """
    pad = int(60 * k)
    tile = Image.new("RGBA", (flat.width + pad * 2, flat.height + pad * 2), (0, 0, 0, 0))
    tile.alpha_composite(flat, (pad, pad))
    tile = tile.rotate(angle, resample=Image.BICUBIC)
    out = (shadow if shadow is not None else kit.shadow_of(tile, 14 * k, 170)).copy()
    sx = (out.width - tile.width) // 2
    out.alpha_composite(tile, (sx + int(10 * k), sx - int(4 * k)))
    return out


def _shadow(ctx, item: dict) -> Image.Image:
    key = ("cf_shadow", id(item["flat"]))
    if key not in ctx.cache:
        pad = int(60 * ctx.k)
        flat = item["flat"]
        tile = Image.new("RGBA", (flat.width + pad * 2, flat.height + pad * 2), (0, 0, 0, 0))
        tile.alpha_composite(flat, (pad, pad))
        ctx.cache[key] = kit.shadow_of(tile.rotate(item["angle"], resample=Image.BICUBIC),
                                       14 * ctx.k, 170)
    return ctx.cache[key]


# Kinds whose look changes as they arrive: typed, highlighted, unredacted.
REVEALS = {"card", "clipping", "redacted"}
STEPS = 12          # reveal steps per second — "on twos", like stop motion


def _revealing(ctx, beat, item: dict, f: float, length: float) -> Image.Image:
    """The item part-revealed, stepped and cached so each step draws once."""
    step = int(f * max(1.0, length) * STEPS)
    key = ("cf_rev", id(item["flat"]), step)
    if key not in beat.extra:
        q = step / max(1.0, max(1.0, length) * STEPS)
        flat = _item(item["cue"], beat.picture, ctx.k, q)
        beat.extra[key] = _finish(flat, item["angle"], ctx.k, _shadow(ctx, item))
    return beat.extra[key]


PINS = [((196, 30, 36), 5), ((40, 96, 190), 2), ((236, 188, 36), 2),
        ((236, 236, 230), 1), ((44, 150, 90), 1)]
_SPRITES: dict = {}


def _pin_colour(n: int) -> tuple[int, int, int]:
    pool = [c for c, w in PINS for _ in range(w)]
    return pool[random.Random(n * 977 + 3).randrange(len(pool))]


def _pin_sprite(R: float, rgb) -> Image.Image:
    """A push-pin seen from above, drawn at 4x and shrunk so its edge is
    smooth: soft shadow, domed head, rim, and a bright highlight."""
    key = (round(R * 2), rgb)
    if key in _SPRITES:
        return _SPRITES[key]
    S = 4
    r = max(2.0, R) * S
    side = int(r * 3.4)
    c = side / 2
    img = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sh = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((c - r * 0.9 + r * 0.45, c - r * 0.9 + r * 0.8,
                                c + r * 0.9 + r * 0.45, c + r * 0.9 + r * 0.8),
                               fill=(0, 0, 0, 120))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(r * 0.32)))
    d = ImageDraw.Draw(img)
    dark = tuple(int(v * 0.55) for v in rgb) + (255,)
    mid = tuple(rgb) + (255,)
    lite = tuple(min(255, int(v + (255 - v) * 0.45)) for v in rgb) + (255,)
    d.ellipse((c - r, c - r, c + r, c + r), fill=dark)
    # The dome: lighter towards the lamp (up and left), so it reads as round.
    for f, col, dx in ((0.86, mid, 0.07), (0.62, lite, 0.16)):
        rr = r * f
        d.ellipse((c - rr - r * dx, c - rr - r * dx, c + rr - r * dx, c + rr - r * dx), fill=col)
    hl = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse((c - r * 0.5, c - r * 0.62, c - r * 0.08, c - r * 0.26),
                               fill=(255, 255, 255, 215))
    img.alpha_composite(hl.filter(ImageFilter.GaussianBlur(r * 0.07)))
    out = img.resize((max(2, side // S), max(2, side // S)), Image.LANCZOS)
    _SPRITES[key] = out
    return out


def _pin(st: kit.Stage, x, y, r=17, n: int = 0):
    sp = _pin_sprite(r * st.k, _pin_colour(n))
    kit._composite_clipped(st.img, sp, st.p(x) - sp.width // 2, st.p(y) - sp.height // 2)


def _tape(st: kit.Stage, x, y, angle):
    """A strip of translucent masking tape across a corner."""
    w, h = 150, 46
    strip = Image.new("RGBA", (st.p(w), st.p(h)), (236, 226, 190, 175))
    d = ImageDraw.Draw(strip)
    for i in range(0, strip.width, max(2, st.p(10))):
        d.line((i, 0, i, 3), fill=(210, 198, 160, 190))
    strip = strip.rotate(angle, expand=True, resample=Image.BICUBIC)
    kit._composite_clipped(st.img, strip, st.p(x) - strip.width // 2, st.p(y) - strip.height // 2)


# ------------------------------------------------------------------- board
def _slots(board: int) -> list[tuple[float, float, float]]:
    """Where items go on one board: a jittered grid, centre first."""
    rng = random.Random(board * 131 + 7)
    cw, ch = WORLD_W / COLS, WORLD_H / ROWS
    cells = [(c, r) for r in range(ROWS) for c in range(COLS)]
    mid = ((COLS - 1) / 2, (ROWS - 1) / 2)
    # Nearest the centre first, ties broken by a fixed shuffle so the board
    # fills out from the middle rather than reading left to right.
    rng.shuffle(cells)
    cells.sort(key=lambda c: round(math.dist(c, mid) * 1.6))
    return [((c + 0.5) * cw + rng.uniform(-90, 90), (r + 0.5) * ch + rng.uniform(-60, 60),
             rng.uniform(-5, 5)) for c, r in cells]


def _boards(ctx) -> dict[str, tuple[int, int]]:
    """slide id -> (board number, index of its first item on that board)."""
    key = "cf_boards"
    if key in ctx.cache:
        return ctx.cache[key]
    from . import cues_for, BY_KEY
    module = BY_KEY[KEY]
    out: dict[str, tuple[int, int]] = {}
    board, used = 0, 0
    for i, s in enumerate(ctx.project.slides):
        n = len(cues_for(module, s))
        if i and ((getattr(s, "chapter", "") or "").strip() or used + n > PER_BOARD):
            board, used = board + 1, 0
        out[s.id] = (board, used)
        used += n
    ctx.cache[key] = out
    return out


def _ground(ctx) -> Image.Image:
    wk = ctx.k * WORLD_SCALE
    key = ("cf_ground", ctx.look, wk)
    if key in ctx.cache:
        return ctx.cache[key]
    size = (max(1, round(WORLD_W * wk)), max(1, round(WORLD_H * wk)))
    small = (size[0] // 3 or 1, size[1] // 3 or 1)
    noise = Image.effect_noise(small, 60).resize(size, Image.BILINEAR)
    if ctx.look == "wall":
        lo, hi = (22, 22, 26), (52, 50, 54)
    elif ctx.look == "felt":
        lo, hi = (22, 58, 40), (48, 110, 74)
    else:
        lo, hi = (74, 46, 26), (150, 104, 62)
    ground = ImageOps.colorize(noise, lo, hi).convert("RGBA")
    if ctx.look == "felt":
        fibre = Image.effect_noise(size, 90).point(lambda v: 255 if v > 200 else 0)
        ground.paste(Image.new("RGBA", size, (150, 200, 170, 36)), (0, 0), fibre)
    elif ctx.look != "wall":
        speck = Image.effect_noise(size, 120).point(lambda v: 255 if v > 232 else 0)
        dark = Image.new("RGBA", size, (40, 22, 10, 120))
        ground.paste(dark, (0, 0), speck)
    ctx.cache[key] = ground
    return ground


def _place(ctx, board: int, n: int, cue: dict, picture) -> dict:
    """An item's finished tile, its world position and where its pin is."""
    slots = _slots(board)
    x, y, angle = slots[n % len(slots)]
    flat = _item(cue, picture, ctx.k)
    return {"flat": flat, "x": x, "y": y, "angle": angle,
            "w": flat.width / ctx.k, "h": flat.height / ctx.k,
            "pin": (x, y - flat.height / ctx.k / 2 + 26), "n": board * 100 + n}


def _history(ctx, beat) -> list[tuple[dict, object]]:
    """Every (cue, picture) pinned on this board before `beat`'s slide."""
    from . import cues_for, BY_KEY, load_picture
    module = BY_KEY[KEY]
    boards = _boards(ctx)
    board, _ = boards.get(beat.slide.id, (0, 0))
    out = []
    for s in ctx.project.slides:
        if s.id == beat.slide.id:
            break
        if boards.get(s.id, (-1, 0))[0] != board:
            continue
        pic = load_picture(ctx, s, None)
        out += [(c, pic) for c in cues_for(module, s)]
    return out


def _tile(ctx, item: dict) -> Image.Image:
    key = ("cf_tile", id(item["flat"]))
    if key not in ctx.cache:
        ctx.cache[key] = _finish(item["flat"], item["angle"], ctx.k, _shadow(ctx, item))
    return ctx.cache[key]


def _world(ctx, beat, upto: int) -> tuple[Image.Image, list[dict]]:
    """The board with everything before cue `upto` of this beat pinned up."""
    key = ("cf_world", beat.slide.id, upto, ctx.k, ctx.look)
    if key in beat.extra:
        return beat.extra[key]
    board, first = _boards(ctx).get(beat.slide.id, (0, 0))
    placed = beat.extra.get("cf_placed")
    if placed is None:
        hist = _history(ctx, beat)
        start = first - len(hist)
        seq = hist + [(c, beat.picture) for c in beat.cues]
        # Paragraphs sharing one picture would pin the same polaroid again
        # and again; after the first, it goes up as a card with its caption.
        seen: set[int] = set()
        for n, (c, pic) in enumerate(seq):
            if c["kind"] == "photo":
                if pic is not None and id(pic) in seen:
                    seq[n] = ({"kind": "card", "title": "", "text": c.get("caption", "")}, pic)
                elif pic is not None:
                    seen.add(id(pic))
        placed = [_place(ctx, board, start + i, c, p) for i, (c, p) in enumerate(seq)]
        for item, (cue, _pic) in zip(placed, seq):
            item["cue"] = cue
        beat.extra["cf_placed"] = placed
        beat.extra["cf_hist"] = len(hist)
    n_up = beat.extra["cf_hist"] + upto
    wk = ctx.k * WORLD_SCALE
    st = kit.Stage.sized(WORLD_W, WORLD_H, wk)
    st.img = _ground(ctx).copy()
    st.draw = ImageDraw.Draw(st.img)
    for item in placed[:n_up]:
        tile = _tile(ctx, item)
        tile = tile.resize((max(1, round(tile.width * WORLD_SCALE)),
                            max(1, round(tile.height * WORLD_SCALE))), Image.BILINEAR)
        kit._composite_clipped(st.img, tile, st.p(item["x"]) - tile.width // 2,
                               st.p(item["y"]) - tile.height // 2)
    for n, item in enumerate(placed[:n_up]):
        _pin(st, *item["pin"], n=item["n"])
    # Everything already up sits behind the focus: soft, a little darker.
    # Opaque, so kept as RGB: Pillow premultiplies the *whole* of an RGBA
    # image on every resize, crop box or not, and this one is 4.6K wide.
    soft = st.img.convert("RGB").filter(ImageFilter.GaussianBlur(2.9 * wk))
    result = (soft, placed)
    beat.extra[key] = result
    return result


# ------------------------------------------------------------------ camera
def _focus(item: dict | None) -> tuple[float, float, float]:
    if item is None:
        return WORLD_W / 2, WORLD_H / 2, kit.W / WORLD_W
    return item["x"], item["y"] + 20, min(1.35, 0.62 * kit.H / item["h"])


def _view(world: Image.Image, cam, ctx) -> Image.Image:
    cx, cy, z = cam
    vw, vh = kit.W / z, kit.H / z
    x0 = kit.clamp(cx - vw / 2, 0, max(0, WORLD_W - vw))
    y0 = kit.clamp(cy - vh / 2, 0, max(0, WORLD_H - vh))
    k = ctx.k * WORLD_SCALE
    return world.resize(ctx.size, Image.BILINEAR,
                        box=(x0 * k, y0 * k, min(world.width, (x0 + vw) * k),
                             min(world.height, (y0 + vh) * k))), (x0, y0, z)


def _light(ctx) -> Image.Image:
    key = ("cf_light", ctx.k)
    if key not in ctx.cache:
        layer = kit.vignette(ctx.size, 0.95, centre=(0.42, 0.38))
        warm = Image.new("RGBA", ctx.size, (255, 170, 90, 22))
        warm.alpha_composite(layer)
        ctx.cache[key] = warm
    return ctx.cache[key]


def frame(beat: kit.Beat, ctx, t: float) -> Image.Image:
    i = beat.at(t)
    start, end = beat.times[i]
    u = t - start
    world, placed = _world(ctx, beat, i)
    n_hist = beat.extra["cf_hist"]
    item = placed[n_hist + i]
    prev = placed[n_hist + i - 1] if n_hist + i > 0 else None
    # Travel from the last thing pinned to this one, then hold dead still.
    # A slow creep in looked alive on paper and wiggled on screen: the item
    # is re-rounded to whole pixels every frame, and its text shimmers.
    travel = 0.9
    span = max(0.6, (end - start) * 0.5)
    pull = 0.0
    if beat.last:
        pull = kit.ease_in_out(kit.progress(t, beat.length - 3.6, 3.0))
    settled = (u >= travel + 0.2 + span and pull <= 0
               and (u >= travel * 0.55 + 0.3))
    key = ("cf_still", i)
    if settled and key in beat.extra:
        return beat.extra[key]
    a, b = _focus(prev), _focus(item)
    m = kit.ease_in_out(kit.progress(u, 0, travel))
    cam = (kit.lerp(a[0], b[0], m), kit.lerp(a[1], b[1], m), kit.lerp(a[2], b[2], m))
    # Pull back from the board when the case closes.
    if pull > 0:
        whole = _focus(None)
        cam = tuple(kit.lerp(cam[j], whole[j], pull) for j in range(3))
    out, (x0, y0, z) = _view(world, cam, ctx)
    st = kit.Stage(ctx.k)
    st.img = out.convert("RGBA")
    st.draw = ImageDraw.Draw(st.img)

    def screen(p):
        return ((p[0] - x0) * z, (p[1] - y0) * z)

    # The item itself, sharp, dropping in as the camera arrives.
    drop = kit.progress(u, travel * 0.55, 0.3)
    if drop > 0:
        reveal = kit.progress(u, travel + 0.2, span)
        if reveal >= 1 or item["cue"]["kind"] not in REVEALS:
            tile = _tile(ctx, item)
        else:
            tile = _revealing(ctx, beat, item, reveal, span)
        s = z * (1 + 0.14 * (1 - kit.ease_out(drop)))
        tw, th = max(1, int(tile.width * s)), max(1, int(tile.height * s))
        scaled = tile.resize((tw, th), Image.BILINEAR)
        cx, cy = screen((item["x"], item["y"]))
        st.paste(scaled, cx - tw / ctx.k / 2, cy - th / ctx.k / 2, alpha=kit.ease_out(drop))
        if drop >= 1:
            _pin(st, *screen(item["pin"]), r=17 * z, n=item["n"])
    st.img.alpha_composite(_light(ctx))
    out = st.rgb()
    if settled:
        beat.extra[key] = out
    return out


def chapter(ctx, title: str, base: Image.Image, u: float) -> Image.Image:
    """The board sinks into shadow and a typed label is pinned up over it."""
    st = kit.dim_to(base, (8, 6, 4), 0.62 * kit.ease_out(kit.progress(u, 0, 0.45)))
    drop = kit.progress(u, 0.2, 0.35)
    if drop <= 0:
        return st.rgb()
    w, h = 1180, 420
    flat = kit.Stage.sized(w, h, ctx.k)
    _paper(flat, w, h, (244, 238, 222, 255), (150, 140, 120, 255))
    flat.rect(0, 0, w, 74, fill=(178, 28, 34, 255))
    flat.text((46, 38), "CASE FILE  ·  NEXT", "mono_bold", 32, (246, 238, 226), anchor="lm")
    size, lines = kit.fit(title.upper(), "condensed", 150, w - 120, 2, floor=64)
    top = 74 + (h - 74) / 2 - len(lines) * size * 0.55
    for i, line in enumerate(lines):
        flat.text((w / 2, top + i * size * 1.1 + size * 0.55), line, "condensed", size,
                  (26, 26, 30), anchor="mm")
    tile = _finish(flat.img, -2.0, ctx.k)
    s = 1 + 0.12 * (1 - kit.ease_out(drop))
    tile = tile.resize((max(1, int(tile.width * s)), max(1, int(tile.height * s))),
                       Image.BILINEAR)
    cx, cy = st.size[0] / 2, st.size[1] / 2
    kit._composite_clipped(st.img, kit.with_alpha(tile, kit.ease_out(drop)),
                           int(cx - tile.width / 2), int(cy - tile.height / 2))
    if drop >= 1:
        _pin(st, kit.W / 2 - 6, kit.H / 2 - h / 2 + 30, r=24, n=len(title))
    return st.rgb()

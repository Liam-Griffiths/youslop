"""Loudmouth: kinetic type. The words are the video.

Each phrase of the narration is set as a block of type on one big canvas —
the stressed words enormous and in the accent, the small words small — and
the words slam in as they are spoken. The camera travels from block to block:
down to the next line, across, a quarter-turn to read a word set sideways, or
in to a phrase set tiny inside the last one. When the paragraph's voice stops,
the camera pulls back and the whole paragraph is one composition.

Built for motivation, self-improvement, faith and sermons, quotes, poetry and
spoken word, and product announcements — anything where the copy is the
point and there is no picture that would improve it.
"""
from __future__ import annotations

import math

from PIL import Image

from . import kit

KEY = "loudmouth"
LABEL = "Loudmouth"
FOR = "Motivation, faith, quotes, spoken word"
BLURB = ("Kinetic type. Every word slams in as it's said, stressed words huge, "
         "and the camera turns and travels across one giant page.")
LOOKS = [{"key": "", "label": "Ink"}, {"key": "paper", "label": "Paper"},
         {"key": "loud", "label": "Accent ground"}]
FALLBACK_KIND = "phrase"
MIN_HOLD = 0.6
MOVES = ("down", "right", "turn", "zoom")

PLAN = """The format is kinetic typography: the narration's own words, set huge,
appearing exactly as they are spoken. The camera moves over one giant page from
phrase to phrase. Some phrases are set over the paragraph's picture instead,
full-frame, so the video cuts between pure type and type over the scene.

Every cue is one PHRASE of the narration, in order, covering all of it:
{"kind": "phrase", "text": "the exact words spoken, 2-7 of them, with the
  ONE OR TWO stressed words wrapped in *asterisks*", "move": "down|right|turn|zoom"}
- "text" must be the narration's own words, verbatim, in order. Together the
  phrases cover the whole paragraph.
- Stress what a performer would hit: the noun, the number, the turn of the
  argument. Never stress "the", "and", "is".
- "move" is how the camera reaches this phrase: "down" to the next line (the
  default), "right" across, "turn" for a quarter-turn onto a sideways phrase
  (use for a sudden reversal), "zoom" into a tiny phrase (use for an aside or
  an intimate line). Mostly "down"; a turn or zoom at most once a paragraph.
- "image": true sets the phrase over the paragraph's picture, filling the
  frame. Give it to 1-2 phrases per paragraph — the ones that name the scene,
  the person or the thing — never two in a row."""

KIND_DOC = "phrase (with *stressed* words, a camera move, and \"image\": true to set it over the picture)"

LOOK_COLORS = {
    "": {"ground": "#0B0B0D", "ink": "#F4F1EA", "dim": "#8D8A84"},
    "paper": {"ground": "#F1EBDD", "ink": "#1B1A17", "dim": "#8E877A"},
    "loud": {"ground": None, "ink": "#111111", "dim": "#3A3A3A"},
}


def normalise(c: dict) -> dict | None:
    text = str(c.get("text") or "").strip()[:120]
    if not text:
        return None
    move = str(c.get("move") or "down").strip().lower()
    return {"kind": "phrase", "text": text, "move": move if move in MOVES else "down",
            "image": bool(c.get("image"))}


def derive(slide) -> list[dict]:
    cues = []
    for i, part in enumerate(kit.clauses(slide.narration, max_words=6, min_words=2)):
        stress = kit.keyword(part)
        text = " ".join(f"*{w}*" if stress and w.strip(".,;:!?") == stress else w
                        for w in part.split())
        move = "down"
        if i and i % 5 == 2:
            move = "right"
        elif i and i % 7 == 4:
            move = "turn"
        # The opening phrase, and every fourth after it, over the picture.
        cues.append({"kind": "phrase", "text": text, "move": move, "on": kit.head(part),
                     "image": i % 4 == 0})
    return cues


# ---------------------------------------------------------------- blocks
def _palette(ctx) -> dict:
    p = dict(LOOK_COLORS.get(ctx.look, LOOK_COLORS[""]))
    if p["ground"] is None:
        p["ground"] = ctx.accent
        p["hot"] = "#FFFFFF"
    else:
        p["hot"] = ctx.accent
    return p


def _words(text: str) -> list[tuple[str, str]]:
    """(word, weight) — weight is hot, plain or small."""
    out = []
    for raw in text.split():
        hot = raw.startswith("*") or raw.rstrip(".,;:!?").endswith("*")
        word = raw.replace("*", "")
        if not word:
            continue
        bare = word.lower().strip(".,;:!?'\"")
        weight = "hot" if hot else "small" if bare in kit._STOP and len(bare) <= 4 else "plain"
        out.append((word, weight))
    return out


SIZES = {"hot": 210, "plain": 118, "small": 64}
FACE = {"hot": "display", "plain": "display", "small": "sans_bold"}


def _layout(text: str) -> dict:
    """Lines of words with their sizes, in block units (1080p px at scale 1)."""
    words = _words(text)
    lines: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    width = 0.0
    for w, weight in words:
        adv = kit.advance(w + " ", FACE[weight], SIZES[weight])
        if weight == "hot":
            # A stressed word takes a line of its own: it is the line.
            if cur:
                lines.append(cur)
            lines.append([(w, weight)])
            cur, width = [], 0.0
            continue
        if cur and width + adv > 1250:
            lines.append(cur)
            cur, width = [], 0.0
        cur.append((w, weight))
        width += adv
    if cur:
        lines.append(cur)
    placed = []          # (word, weight, x, baseline_y)
    y = 0.0
    bw = 0.0
    for line in lines:
        size = max(SIZES[wt] for _, wt in line)
        x = 0.0
        y += size * 0.92
        for w, wt in line:
            placed.append((w, wt, x, y))
            x += kit.advance(w + " ", FACE[wt], SIZES[wt])
        bw = max(bw, x - kit.advance(" ", FACE[line[-1][1]], SIZES[line[-1][1]]))
        y += size * 0.12
    # Hot words that are much narrower than the block are stretched to its
    # width, the way a type designer would set the one word that matters.
    return {"words": placed, "w": max(1.0, bw), "h": max(1.0, y + 10)}


def _word_tile(word: str, weight: str, color, k: float) -> Image.Image:
    st = kit.Stage.sized(kit.advance(word, FACE[weight], SIZES[weight]) + 20,
                         SIZES[weight] * 1.25, k)
    st.text((4, SIZES[weight] * 0.95), word, FACE[weight], SIZES[weight], color, anchor="ls")
    return st.img


# Words set over a picture: white, the stress in the accent, on a darkened
# frame, whatever the page's own colours are.
OVER = {"ink": "#FFFFFF", "dim": "#E4E4E4"}


def _panel(picture, k: float) -> Image.Image:
    """The picture as a full frame for type to sit on, darkened to read."""
    img = kit.cover(picture, round(kit.W * k), round(kit.H * k)).convert("RGBA")
    img.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, 120)))
    return img


def _blocks(beat, ctx) -> list[dict]:
    if "lm_blocks" in beat.extra:
        return beat.extra["lm_blocks"]
    pal = _palette(ctx)
    blocks: list[dict] = []
    for i, cue in enumerate(beat.cues):
        lay = _layout(cue["text"])
        panel = cue.get("image") and beat.picture is not None
        move = cue["move"] if i else "down"
        if panel:
            move = "down" if move in ("turn", "zoom") else move
        scale, rot = 1.0, 0.0
        if not blocks:
            x, y = 0.0, 0.0
        else:
            p = blocks[-1]
            pw, ph = _extent(p)
            if move == "right":
                rot = 0.0
                x, y = p["x"] + pw + 120 * p["s"], p["y"]
            elif move == "turn":
                rot = 90.0 if (i % 2) else -90.0
                # A sideways block: its footprint is its height wide.
                x, y = p["x"] + pw + 90 * p["s"], p["y"]
            elif move == "zoom":
                scale = p["s"] * 0.32
                x, y = p["x"] + pw * 0.62, p["y"] + ph + 24 * p["s"]
            else:
                x, y = p["x"], p["y"] + ph + 50 * p["s"]
                rot = 0.0
        if panel and blocks and blocks[-1]["s"] != 1.0:
            scale = 1.0
        colors = OVER if panel else pal
        # A picture block is a whole frame with the phrase centred in it.
        bw, bh = (kit.W, kit.H) if panel else (lay["w"], lay["h"])
        ox, oy = ((bw - lay["w"]) / 2, (bh - lay["h"]) / 2) if panel else (0.0, 0.0)
        tiles = []
        for w, wt, wx, wy in lay["words"]:
            color = pal["hot"] if wt == "hot" else colors["dim"] if wt == "small" else colors["ink"]
            tiles.append((_word_tile(w, wt, color, ctx.k), ox + wx, oy + wy - SIZES[wt] * 0.95))
        blocks.append({"x": x, "y": y, "s": scale, "r": rot, "w": bw, "h": bh,
                       "tiles": tiles, "full": None,
                       "panel": _panel(beat.picture, ctx.k) if panel else None,
                       "motion": panel and beat.motion is not None, "words": None})
    beat.extra["lm_blocks"] = blocks
    return blocks


def _extent(b: dict) -> tuple[float, float]:
    """Width and height a block takes on the page, after its rotation."""
    if b["r"]:
        return b["h"] * b["s"], b["w"] * b["s"]
    return b["w"] * b["s"], b["h"] * b["s"]


def _centre(b: dict) -> tuple[float, float]:
    w, h = _extent(b)
    return b["x"] + w / 2, b["y"] + h / 2


def _target(b: dict) -> tuple[float, float, float, float]:
    """Camera centre, zoom and rotation that frames block `b`."""
    cx, cy = _centre(b)
    if b.get("panel") is not None:
        return cx, cy, 1.0 / b["s"], b["r"]     # full-bleed
    z = min(1500 / (b["w"] * b["s"]), 820 / (b["h"] * b["s"]))
    # Never past the scale the type was drawn at: upscaled bitmaps go soft.
    z = min(z, 1.0 / b["s"])
    return cx, cy, z, b["r"]


def _overview(blocks: list[dict]) -> tuple[float, float, float, float]:
    x0 = min(b["x"] for b in blocks)
    y0 = min(b["y"] for b in blocks)
    x1 = max(b["x"] + _extent(b)[0] for b in blocks)
    y1 = max(b["y"] + _extent(b)[1] for b in blocks)
    z = min(1700 / max(1, x1 - x0), 940 / max(1, y1 - y0), 1.0)
    return (x0 + x1) / 2, (y0 + y1) / 2, z, 0.0


def _block_image(b: dict, k: float, reveal: list[float] | None,
                 under: Image.Image | None = None) -> Image.Image:
    """The block flat, with each word at its own reveal (None = all in).

    `under` is this frame of a clip the block is set over; the words are laid
    on it fresh every frame, from a cached layer once they have all landed.
    """
    if under is not None:
        img = under.convert("RGBA")
        if reveal is None:
            if b.get("words") is None:
                b["words"] = Image.new("RGBA", img.size, (0, 0, 0, 0))
                _words_onto(b["words"], b, k, None)
            img.alpha_composite(b["words"])
            return img
        _words_onto(img, b, k, reveal)
        return img
    if reveal is None and b["full"] is not None:
        return b["full"]
    if b.get("panel") is not None:
        img = b["panel"].copy()
    else:
        img = Image.new("RGBA", (max(1, round(b["w"] * k) + 30),
                                 max(1, round(b["h"] * k) + 30)), (0, 0, 0, 0))
    _words_onto(img, b, k, reveal)
    if reveal is None:
        b["full"] = img
    return img


def _words_onto(img: Image.Image, b: dict, k: float, reveal: list[float] | None) -> None:
    for n, (tile, wx, wy) in enumerate(b["tiles"]):
        f = 1.0 if reveal is None else reveal[n]
        if f <= 0:
            continue
        x, y = round(wx * k), round(wy * k)
        if f < 1:
            # The slam: in from larger, fast, landing on its spot.
            s = 1 + 0.55 * (1 - kit.ease_out(f))
            tw, th = max(1, int(tile.width * s)), max(1, int(tile.height * s))
            t2 = kit.with_alpha(tile.resize((tw, th), Image.BILINEAR), kit.clamp(f * 2.2))
            kit._composite_clipped(img, t2, x - (tw - tile.width) // 2,
                                   y - (th - tile.height) // 2)
        else:
            img.alpha_composite(tile, (x, y))


def frame(beat: kit.Beat, ctx, t: float) -> Image.Image:
    pal = _palette(ctx)
    blocks = _blocks(beat, ctx)
    i = beat.at(t)
    start, end = beat.times[i]
    u = t - start
    # Camera: travel to this block in the first moments of its cue.
    prev = _target(blocks[i - 1]) if i else _target(blocks[0])
    cur = _target(blocks[i])
    m = kit.ease_in_out(kit.progress(u, 0, min(0.45, (end - start) * 0.4)))
    cam = [kit.lerp(prev[j], cur[j], m) for j in range(4)]
    # Slow drift in while the block holds, so a held frame is never dead.
    cam[2] *= 1 + 0.03 * kit.clamp(u / 4)
    # The voice has stopped: pull back to the whole page.
    voice_end = beat.lead + beat.spoken
    if beat.length - voice_end > 0.5 and len(blocks) > 1:
        pull = kit.ease_in_out(kit.progress(t, voice_end + 0.05, min(0.9, beat.length - voice_end)))
        if pull > 0:
            over = _overview(blocks)
            cam = [kit.lerp(cam[j], over[j], pull) for j in range(4)]
    cx, cy, z, cr = cam

    st = kit.Stage(ctx.k, pal["ground"])
    rad = math.radians(cr)
    cos, sin = math.cos(rad), math.sin(rad)
    for j, b in enumerate(blocks[: i + 1]):
        if j < i:
            reveal = None
        else:
            # Each word lands on its share of the spoken part of the cue.
            n = len(b["tiles"])
            span = max(0.2, (end - start) * 0.8)
            reveal = [kit.progress(u, span * q / max(1, n), 0.16) for q in range(n)]
            if all(r >= 1 for r in reveal):
                reveal = None
        under = None
        if b.get("motion"):
            # Darkened in the decoder, to the same level as a still panel.
            under = kit.footage(ctx, beat.motion, *ctx.size, dim=0.53).frame(t)
        flat = _block_image(b, ctx.k, reveal, under)
        s = b["s"] * z
        if s * max(flat.size) < 2:
            continue
        bx, by = _centre(b)
        # The block's centre on screen. The camera turning by `cr` turns the
        # page the other way, so offsets rotate by -cr (y points down here).
        dx, dy = (bx - cx) * z, (by - cy) * z
        sx = kit.W / 2 + dx * cos - dy * sin
        sy = kit.H / 2 + dx * sin + dy * cos
        diag = math.hypot(flat.width, flat.height) * s / ctx.k / 2
        if sx + diag < 0 or sx - diag > kit.W or sy + diag < 0 or sy - diag > kit.H:
            continue
        angle = b["r"] - cr
        if abs(angle) <= 0.2:
            # Upright: resize only the part of the block that is on screen —
            # a block the camera has zoomed past would otherwise be scaled
            # to several frames across, every frame.
            X0 = sx * ctx.k - flat.width * s / 2
            Y0 = sy * ctx.k - flat.height * s / 2
            fx0, fy0 = max(0.0, -X0 / s), max(0.0, -Y0 / s)
            fx1 = min(float(flat.width), (st.size[0] - X0) / s)
            fy1 = min(float(flat.height), (st.size[1] - Y0) / s)
            if fx1 - fx0 < 1 or fy1 - fy0 < 1:
                continue
            tw, th = max(1, round((fx1 - fx0) * s)), max(1, round((fy1 - fy0) * s))
            if abs(s - 1.0) < 1e-3:
                # Settled at the scale it was drawn: a crop, not a resample.
                tile = flat.crop((round(fx0), round(fy0), round(fx1), round(fy1)))
            else:
                tile = flat.resize((tw, th), Image.BILINEAR, box=(fx0, fy0, fx1, fy1))
            kit._composite_clipped(st.img, tile, round(X0 + fx0 * s), round(Y0 + fy0 * s))
            continue
        tile = flat.resize((max(1, int(flat.width * s)), max(1, int(flat.height * s))),
                           Image.BILINEAR)
        tile = tile.rotate(angle, expand=True, resample=Image.BILINEAR)
        st.paste(tile, sx - tile.width / ctx.k / 2, sy - tile.height / ctx.k / 2)
    return st.rgb()


def chapter(ctx, title: str, base: Image.Image, u: float) -> Image.Image:
    """The title slams in, huge, on the cut's own ground."""
    colors = LOOK_COLORS.get(ctx.look) or LOOK_COLORS[""]
    ground = colors["ground"] or "#F2D21B"
    st = kit.dim_to(base, ground, 1.0 if u > 0.12 else kit.progress(u, 0, 0.12))
    t = kit.ease_back(kit.progress(u, 0.1, 0.35))
    size, lines = kit.fit(title.upper(), "display", 260, kit.W - 220, 3, floor=90)
    layer = st.layer()
    top = kit.H / 2 - len(lines) * size * 0.55
    for i, line in enumerate(lines):
        layer.text((kit.W / 2, top + i * size * 1.08 + size * 0.5), line, "display", size,
                   colors["ink"], anchor="mm")
    img = layer.img
    s = max(0.05, 0.6 + 0.4 * t)
    img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BILINEAR)
    st.img.alpha_composite(kit.with_alpha(img, kit.clamp(t)),
                           ((st.img.width - img.width) // 2, (st.img.height - img.height) // 2))
    return st.rgb()

"""The end screen: the held card a video finishes on.

An end screen is not just a closing title. YouTube draws its own clickable
elements — the video cards, the subscribe badge — on top of the last stretch of
the picture, and they can only go where the frame leaves room. So a template
here is largely a question of *where the holes are*: every layout puts down
empty plates at element-sized positions, and the creator lines the real elements
up with them in Studio. A card with nowhere to put them is the usual reason an
end screen ends up covering somebody's face.

Frames are composed with Pillow and piped to ffmpeg, exactly as the opening
slate is. Unlike the slate these run 5 to 20 seconds, so the frame the layout
settles into is composed once and cached; only the countdown hairline and the
subscribe pulse are redrawn, and then only over their own few hundred pixels.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from . import intro, motifs, themes, titles
from .channels import channel_dir
from .config import FPS, HEIGHT, WIDTH
from .schema import Channel

Progress = Callable[[str], None]

# Layout, in 1080p pixels. The margin is deliberately generous: YouTube will not
# place an element hard against the frame edge, and a plate the creator cannot
# cover is worse than no plate at all.
MARGIN = 132
PLATE_PAD = 30           # room around a plate for its cast shadow
SQUARE = 400             # a video element set square
WIDE_W, WIDE_H = 672, 378        # and set 16:9
RING = 208               # the subscribe badge

SLOT_LABELS = ["next video", "more like this", "playlist"]

# ------------------------------------------------------------------ templates
# `max_slots` caps the plate count the layout can hold; `cta` is the line used
# when the channel has not written one. `ground` tells the UI whether the card
# runs on ink or on paper, which is most of what its sketch has to show.
TEMPLATES = [
    {"key": "twoup", "label": "Two up", "max_slots": 2, "ground": "dark",
     "wants_backdrop": False, "cta": "More from this series",
     "blurb": "The channel and a subscribe badge on the left, two video plates "
              "on the right. The layout most end screens want to be.",
     "slots_label": "Video plates"},
    {"key": "marquee", "label": "Marquee", "max_slots": 2, "ground": "dark",
     "wants_backdrop": False, "cta": "Watch this next",
     "blurb": "The channel name set large across the top with the plates in "
              "16:9 beneath it. For pointing at one particular video.",
     "slots_label": "Plates"},
    {"key": "afterglow", "label": "Afterglow", "max_slots": 2, "ground": "photo",
     "wants_backdrop": True, "cta": "Keep watching",
     "blurb": "The last picture of the video holds under a scrim and the "
              "plates float over it. The gentlest way to end.",
     "slots_label": "Video plates"},
    {"key": "console", "label": "Console", "max_slots": 3, "ground": "dark",
     "wants_backdrop": False, "cta": "Select the next file",
     "blurb": "A technical grid, mono type and plates drawn in corner by "
              "corner. Pairs with the Signal and Atlas slates.",
     "slots_label": "Plates"},
    {"key": "ledger", "label": "Ledger", "max_slots": 2, "ground": "paper",
     "wants_backdrop": False, "cta": "Next in the series",
     "blurb": "Cream stock, Baskerville and plated frames inside a rule. The "
              "end screen for a Folio channel.",
     "slots_label": "Plates"},
    {"key": "quiet", "label": "Quiet", "max_slots": 2, "ground": "dark",
     "wants_backdrop": False, "cta": "Thank you for watching",
     "blurb": "Near black, one hairline rule, the name small and the plates "
              "low. Says the least of any of them.",
     "slots_label": "Video plates"},
    # Theme-led. The plates sit in the same element-sized places; the ground,
    # the second colour and the icons come from the channel's theme.
    {"key": "arcade", "label": "Arcade", "max_slots": 2, "ground": "dark",
     "wants_backdrop": False, "cta": "Play the next one", "themed": True,
     "blurb": "Cartridge plates on a field of icons under a blinking prompt, "
              "with the wordmark's hard colour shadow. For gaming.",
     "slots_label": "Video plates"},
    {"key": "gloss", "label": "Gloss", "max_slots": 2, "ground": "soft",
     "wants_backdrop": False, "cta": "More like this", "themed": True,
     "blurb": "Soft light and drifting sparkles, the name in Baskerville and "
              "the plates centred beneath it. For beauty and fashion.",
     "slots_label": "Plates"},
    {"key": "sideline", "label": "Sideline", "max_slots": 2, "ground": "dark",
     "wants_backdrop": False, "cta": "Up next", "themed": True,
     "blurb": "A slanted band across a striped field, with the plates upright "
              "over it so a card dropped on one sits square. For sport.",
     "slots_label": "Video plates"},
    {"key": "wordmark", "label": "Wordmark", "max_slots": 3, "ground": "dark",
     "wants_backdrop": False, "cta": "Keep listening", "themed": True,
     "blurb": "The channel name repeated as wallpaper with a band cut out of "
              "it and up to three plates below. For music and talk.",
     "slots_label": "Plates"},
]
TEMPLATE_KEYS = [t["key"] for t in TEMPLATES]


def template(key: str) -> dict:
    for t in TEMPLATES:
        if t["key"] == key:
            return t
    return TEMPLATES[0]


def max_slots(key: str) -> int:
    return int(template(key)["max_slots"])


def wants_backdrop(key: str) -> bool:
    """Does this template read the last picture of the video?"""
    return bool(template(key)["wants_backdrop"])


# ---------------------------------------------------------------- the engine
@dataclass
class Piece:
    """One layer of the card, and how it arrives."""
    layer: Image.Image                      # RGBA, already at its final size
    pos: tuple[int, int]                    # top-left of where it comes to rest
    delay: float = 0.0                      # seconds before it starts to arrive
    dur: float = 0.5
    rise: tuple[int, int] = (0, 30)         # the offset it travels in from


Live = Callable[[float], list[tuple[tuple[int, int], Image.Image]]]


def _play(out_path: Path, ground: Image.Image, pieces: list[Piece],
          duration: float, live: Live | None = None) -> float:
    """Land every piece, then hold. Returns the duration actually rendered."""
    n_frames = int(round(duration * FPS))
    arrived = max((p.delay + p.dur for p in pieces), default=0.0)
    settled: Image.Image | None = None

    def frames():
        nonlocal settled
        for f in range(n_frames):
            t = f / FPS
            if settled is not None:
                frame = settled.copy()
            else:
                frame = ground.copy()
                for p in pieces:
                    a = intro._clamp01((t - p.delay) / max(0.01, p.dur))
                    if a <= 0:
                        continue
                    e = intro._ease_out_cubic(a)
                    img = p.layer
                    # Alpha runs slightly ahead of the move, so a piece is
                    # legible before it has finished settling.
                    alpha = int(255 * min(1.0, a * 1.4))
                    if alpha < 255:
                        img = img.copy()
                        img.putalpha(img.split()[3].point(lambda v: v * alpha // 255))
                    frame.paste(img, (int(round(p.pos[0] + p.rise[0] * (1 - e))),
                                      int(round(p.pos[1] + p.rise[1] * (1 - e)))), img)
                if t >= arrived:
                    settled = frame.copy()
            if live:
                for pos, patch in live(t):
                    frame.paste(patch, pos, patch)
            yield frame

    intro._encode(out_path, frames(), what="the end screen")
    return duration


# ------------------------------------------------------------------- drawing
def _dim(color: tuple[int, int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return color[:3] + (alpha,)


def _plate(w: int, h: int, accent, label: str, paper: bool = False,
           brackets: bool = False, body=None, ink=None, radius: int | None = None,
           edge: int = 2) -> Image.Image:
    """An empty element-sized plate, with its own cast shadow.

    Whatever the creator drops on top of it in Studio covers this exactly, so
    the plate is drawn as something that would look deliberate if they never
    did: a panel, a hairline in the channel accent, and a ghosted play glyph.
    """
    layer = Image.new("RGBA", (w + PLATE_PAD * 2, h + PLATE_PAD * 2), (0, 0, 0, 0))
    x0, y0, x1, y1 = PLATE_PAD, PLATE_PAD, PLATE_PAD + w, PLATE_PAD + h
    radius = radius if radius is not None else (14 if not paper else 4)

    shade = Image.new("L", layer.size, 0)
    ImageDraw.Draw(shade).rounded_rectangle([x0, y0 + 10, x1, y1 + 10], radius,
                                            fill=120 if paper else 165)
    shadow = Image.new("RGBA", layer.size, (30, 24, 16, 0) if paper else (0, 0, 0, 0))
    shadow.putalpha(shade.filter(ImageFilter.GaussianBlur(16)))
    layer = Image.alpha_composite(layer, shadow)

    d = ImageDraw.Draw(layer)
    body = body or ((250, 246, 236, 245) if paper else (23, 26, 33, 232))
    ink = tuple((ink or ((58, 52, 44) if paper else (255, 255, 255)))[:3])
    d.rounded_rectangle([x0, y0, x1, y1], radius, fill=body,
                        outline=_dim(accent, 120 if paper else 150), width=edge)

    if brackets:
        # A console plate is bracketed rather than framed: the corners read as
        # a target the element is about to be dropped into.
        arm = 34
        for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                               (x0, y1, 1, -1), (x1, y1, -1, -1)):
            d.line([(cx, cy), (cx + arm * sx, cy)], fill=_dim(accent, 235), width=4)
            d.line([(cx, cy), (cx, cy + arm * sy)], fill=_dim(accent, 235), width=4)

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 - 16
    r = min(w, h) * 0.13
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ink + (80,), width=3)
    tri = r * 0.46
    d.polygon([(cx - tri * 0.62, cy - tri), (cx - tri * 0.62, cy + tri),
               (cx + tri * 0.86, cy)], fill=ink + (80,))

    if label:
        font = titles._load(titles.KICKER_STACK, 23)
        text = label.upper()
        tw = intro._tracked_width(d, text, font, 3.4)
        titles._tracked(d, ((layer.width - tw) / 2, cy + r + 34), text, font,
                        ink + (120,), 3.4)
    return layer


def _ring(accent, initial: str, paper: bool = False, mono: bool = False,
          body=None, ink=None) -> Image.Image:
    """The round plate the subscribe badge sits on, with the channel's initial."""
    size = RING + PLATE_PAD * 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    box = [PLATE_PAD, PLATE_PAD, PLATE_PAD + RING, PLATE_PAD + RING]

    shade = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shade).ellipse([box[0], box[1] + 10, box[2], box[3] + 10],
                                  fill=110 if paper else 160)
    shadow = Image.new("RGBA", (size, size), (30, 24, 16, 0) if paper else (0, 0, 0, 0))
    shadow.putalpha(shade.filter(ImageFilter.GaussianBlur(15)))
    layer = Image.alpha_composite(layer, shadow)

    d = ImageDraw.Draw(layer)
    d.ellipse(box, fill=body or ((248, 244, 234, 245) if paper else (26, 29, 37, 236)),
              outline=_dim(accent, 210), width=3)
    stack = titles.MONO_STACK if mono else titles.FONT_STACK
    font = titles._load(stack, 96)
    ch = (initial or "•")[0].upper()
    w = d.textlength(ch, font=font)
    asc, _ = font.getmetrics()
    d.text(((size - w) / 2, PLATE_PAD + RING / 2 - asc * 0.62), ch, font=font,
           fill=ink or (_dim(accent, 255) if not paper else (58, 52, 44, 235)))
    return layer


def _pill(text: str, accent, paper: bool = False) -> Image.Image:
    """A SUBSCRIBE lozenge. Not a button — nothing here is clickable."""
    font = titles._load(titles.KICKER_STACK, 24)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    tw = intro._tracked_width(probe, text, font, 4.2)
    w, h = int(tw) + 66, 58
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, w - 1, h - 1], h // 2, fill=_dim(accent, 235))
    ink = (16, 16, 18, 255) if not paper else (250, 247, 240, 255)
    asc, _ = font.getmetrics()
    titles._tracked(d, ((w - tw) / 2, (h - asc) / 2 - 2), text, font, ink, 4.2)
    return layer


def _text_layer(lines: list[tuple[str, object, tuple[int, int, int, int], float]],
                gaps: list[int], align: str = "left",
                shadow: bool = False) -> Image.Image:
    """Stack a few tracked lines into one layer that arrives as a block.

    Each line is (text, font, fill, tracking); `gaps` is the space under each.
    The layer is exactly as wide as its widest line, so the caller positions it
    by that width rather than by guessing at the type.
    """
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    widths = [intro._tracked_width(probe, t, f, tr) for t, f, _c, tr in lines]
    heights = [f.getmetrics()[0] + f.getmetrics()[1] for _t, f, _c, _tr in lines]
    w = int(max(widths + [1])) + 8
    h = int(sum(heights) + sum(gaps[:len(lines)])) + 12
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = 0.0
    for i, (text, font, fill, tr) in enumerate(lines):
        x = 0.0 if align == "left" else (w - widths[i]) / 2
        titles._tracked(d, (x, y), text, font, fill, tr)
        y += heights[i] + (gaps[i] if i < len(gaps) else 0)
    return intro._shadowed(layer) if shadow else layer


# --------------------------------------------------------------- the grounds
def _backdrop(path: Path | None, strength: float, grade: str) -> Image.Image | None:
    """The last picture of the video, knocked back far enough to carry type."""
    if not path or strength <= 0.01 or not Path(path).exists():
        return None
    try:
        img = Image.open(path).convert("RGB")
    except OSError:
        return None
    scale = max(WIDTH / img.width, HEIGHT / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                     Image.LANCZOS)
    img = img.crop(((img.width - WIDTH) // 2, (img.height - HEIGHT) // 2,
                    (img.width - WIDTH) // 2 + WIDTH, (img.height - HEIGHT) // 2 + HEIGHT))
    img = img.filter(ImageFilter.GaussianBlur(9))
    img = ImageEnhance.Color(img).enhance(0.0 if grade == "mono" else 0.45)
    # A picture behind plates has to give up a lot of its contrast, or the type
    # on the plates competes with whatever happens to be under them.
    img = ImageEnhance.Brightness(img).enhance(0.30 + 0.16 * (1 - strength))
    return img


def _ground(spec, accent, backdrop_img: Image.Image | None,
            kind: str) -> Image.Image:
    """The card's ground, with the video's last picture behind it if asked."""
    if kind == "paper":
        base = intro._paper_page()
    elif kind == "grid":
        base = intro._grid(accent).crop((0, 0, WIDTH, HEIGHT))
    elif kind == "flat":
        base = Image.new("RGB", (WIDTH, HEIGHT), (9, 10, 13))
    else:
        base = intro._vgrad((16, 18, 24), (6, 6, 9))

    if backdrop_img is None:
        return base
    # `backdrop` is how far the picture comes through the ground, not a blend of
    # two equals: at 1.0 the ground is gone, at 0.3 it is a texture under it.
    return Image.blend(base, backdrop_img, max(0.0, min(1.0, float(spec.backdrop))))


# ----------------------------------------------------------------- the hold
def _live(spec, accent, duration: float, paper: bool,
          ring_at: tuple[int, int] | None) -> Live:
    """What still moves once the layout has landed.

    Two things, both cheap: a hairline that empties over the length of the card,
    which is the only honest way to show how long it is up for, and a ring that
    breathes out of the subscribe plate every few seconds.
    """
    bar_h = 5
    bar_y = HEIGHT - bar_h - 2
    track = Image.new("RGBA", (WIDTH, bar_h), _dim(accent, 34 if paper else 26))
    patches: list[tuple[tuple[int, int], Image.Image]] = []

    pulse_box = None
    if ring_at:
        span = RING + 96
        pulse_box = (ring_at[0] + PLATE_PAD - 48, ring_at[1] + PLATE_PAD - 48, span)

    def live(t: float):
        patches.clear()
        if spec.countdown:
            left = intro._clamp01(1.0 - t / max(0.5, duration))
            bar = track.copy()
            ImageDraw.Draw(bar).rectangle([0, 0, int(WIDTH * left), bar_h],
                                          fill=_dim(accent, 225))
            patches.append(((0, bar_y), bar))
        if pulse_box:
            # One ring every 2.6s, expanding out of the badge and fading.
            phase = (t % 2.6) / 2.6
            if phase < 0.72:
                x, y, span = pulse_box
                k = intro._ease_out_cubic(phase / 0.72)
                r = RING / 2 + 46 * k
                a = int(150 * (1 - k) ** 1.6)
                if a > 3:
                    patch = Image.new("RGBA", (span, span), (0, 0, 0, 0))
                    c = span / 2
                    ImageDraw.Draw(patch).ellipse([c - r, c - r, c + r, c + r],
                                                  outline=_dim(accent, a), width=3)
                    patches.append(((x, y), patch))
        return patches

    return live


# ------------------------------------------------------------------ helpers
def _row(sizes: list[tuple[int, int]], gap: int, cx: float,
         cy: float) -> list[tuple[int, int]]:
    """Centre a row of boxes on (cx, cy). Returns each box's top-left."""
    total = sum(w for w, _h in sizes) + gap * (len(sizes) - 1)
    x = cx - total / 2
    out = []
    for w, h in sizes:
        out.append((int(round(x)), int(round(cy - h / 2))))
        x += w + gap
    return out


def _at(pos: tuple[int, int]) -> tuple[int, int]:
    """Where a plate's *layer* goes, given where the plate itself should land."""
    return (pos[0] - PLATE_PAD, pos[1] - PLATE_PAD)


def _cta(channel: Channel, key: str) -> str:
    return (channel.outro.cta or "").strip() or template(key)["cta"]


def _n_slots(channel: Channel, key: str) -> int:
    return max(0, min(max_slots(key), int(channel.outro.slots)))


def _video_title(channel: Channel, video_title: str) -> str:
    if not (channel.outro.show_video_title and video_title.strip()):
        return ""
    return video_title.strip()


# ------------------------------------------------------------ twoup template
def _render_twoup(channel: Channel, video_title: str, out_path: Path,
                  backdrop: Path | None, progress: Progress) -> float:
    """Channel on the left, plates on the right. The workhorse."""
    spec, key = channel.outro, "twoup"
    accent = titles._hex(channel.style.accent)
    n = _n_slots(channel, key)
    settle = max(0.25, min(1.6, spec.settle))

    ground = _ground(spec, accent, _backdrop(backdrop, spec.backdrop,
                                             channel.style.grade), "dark")
    pieces: list[Piece] = []

    # The plates fill from the right edge inwards, so dropping from two to one
    # leaves the remaining plate where the eye already expects it. The labels
    # still run left to right: the plate a viewer reads first is the next video.
    ys = int((HEIGHT - SQUARE) / 2) + 6
    for i in range(n):
        x = WIDTH - MARGIN - SQUARE - (n - 1 - i) * (SQUARE + 44)
        pieces.append(Piece(_plate(SQUARE, SQUARE, accent, SLOT_LABELS[i]),
                            _at((x, ys)), delay=0.18 + 0.12 * i,
                            dur=settle, rise=(0, 44)))

    # The call to action heads the plates rather than sitting off on its own,
    # because on its own it is just a second caption saying the same thing.
    cta_font = titles._load(titles.KICKER_STACK, 29)
    cta = _text_layer([(_cta(channel, key).upper(), cta_font,
                        (255, 255, 255, 205), 3.4)], [0], shadow=True)
    pieces.append(Piece(cta, (WIDTH - MARGIN - cta.width, ys - 24 - cta.height),
                        delay=0.32, dur=settle))

    if _video_title(channel, video_title):
        sub = _text_layer([(_video_title(channel, video_title),
                            titles._load(titles.MONO_LIGHT_STACK, 24),
                            (255, 255, 255, 135), 0.0)], [0], shadow=True)
        pieces.append(Piece(sub, (WIDTH - MARGIN - sub.width, ys + SQUARE + 18),
                            delay=0.4, dur=settle))

    name_font = titles._load(titles.FONT_STACK, 74)
    lines = [(channel.name, name_font, (255, 255, 255, 255), 0.5)]
    gaps = [10]
    if channel.tagline:
        lines.append((channel.tagline.upper(), titles._load(titles.KICKER_STACK, 24),
                      (255, 255, 255, 165), 3.2))
        gaps.append(14)
    if spec.handle:
        lines.append((spec.handle, titles._load(titles.MONO_LIGHT_STACK, 26),
                      _dim(accent, 210), 0.0))
        gaps.append(14)
    block = _text_layer(lines, gaps, shadow=True)

    # Name and badge are one column, centred against the plates opposite.
    column = block.height + (42 + RING if spec.subscribe else 0)
    top = ys + (SQUARE - column) // 2
    pieces.append(Piece(block, (MARGIN, top), delay=0.0, dur=settle, rise=(0, 26)))

    ring_at = None
    if spec.subscribe:
        badge_y = top + block.height + 42
        ring_at = _at((MARGIN, badge_y))
        pieces.append(Piece(_ring(accent, channel.name), ring_at,
                            delay=0.12, dur=settle, rise=(-26, 0)))
        pieces.append(Piece(_pill("SUBSCRIBE", accent),
                            (MARGIN + RING + 34, badge_y + RING // 2 - 29),
                            delay=0.24, dur=settle, rise=(-20, 0)))

    duration = _length(spec)
    progress(f"End screen: Two up, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, accent, duration, False, ring_at))


# ---------------------------------------------------------- marquee template
def _render_marquee(channel: Channel, video_title: str, out_path: Path,
                    backdrop: Path | None, progress: Progress) -> float:
    """The name across the top, 16:9 plates beneath, the badge at the foot."""
    spec, key = channel.outro, "marquee"
    accent = titles._hex(channel.style.accent)
    n = max(1, _n_slots(channel, key))
    settle = max(0.25, min(1.6, spec.settle))

    ground = _ground(spec, accent, _backdrop(backdrop, spec.backdrop,
                                             channel.style.grade), "dark")
    pieces: list[Piece] = []

    name_lines = intro._wordmark_lines(channel.name)
    font, size = intro._fit_display(name_lines, WIDTH - MARGIN * 2, 210, cap=190)
    wordmark = _text_layer([(l, font, (255, 255, 255, 255), 1.0) for l in name_lines],
                           [int(size * 0.06)] * len(name_lines), align="centre")
    pieces.append(Piece(wordmark, ((WIDTH - wordmark.width) // 2, 96),
                        delay=0.0, dur=settle, rise=(0, 22)))

    rule = Image.new("RGBA", (360, 3), _dim(accent, 230))
    rule_y = 96 + wordmark.height + 26
    pieces.append(Piece(rule, ((WIDTH - 360) // 2, rule_y), delay=0.16, dur=settle,
                        rise=(0, 0)))

    cta_font = titles._load(titles.KICKER_STACK, 27)
    cta = _text_layer([(_cta(channel, key).upper(), cta_font,
                        (255, 255, 255, 190), 3.6)], [0], align="centre")
    pieces.append(Piece(cta, ((WIDTH - cta.width) // 2, rule_y + 26),
                        delay=0.2, dur=settle))

    # 16:9 plates read as "this video" where a square reads as "a video".
    pw, ph = (WIDE_W, WIDE_H) if n == 1 else (600, 338)
    plate_cy = rule_y + 44 + ph / 2 + 34
    for i, (x, y) in enumerate(_row([(pw, ph)] * n, 52, WIDTH / 2, plate_cy)):
        pieces.append(Piece(_plate(pw, ph, accent, SLOT_LABELS[i]), _at((x, y)),
                            delay=0.26 + 0.1 * i, dur=settle, rise=(0, 46)))

    ring_at = None
    foot_y = int(plate_cy + ph / 2 + 44)
    if spec.subscribe:
        pill = _pill("SUBSCRIBE", accent)
        small = RING // 2
        badge = _ring(accent, channel.name).resize(
            (small + PLATE_PAD * 2, small + PLATE_PAD * 2), Image.LANCZOS)
        total = small + 26 + pill.width
        bx = int((WIDTH - total) / 2)
        ring_at = (bx - PLATE_PAD, foot_y - PLATE_PAD)
        pieces.append(Piece(badge, ring_at, delay=0.4, dur=settle, rise=(0, 18)))
        pieces.append(Piece(pill, (bx + small + 26, foot_y + (small - pill.height) // 2),
                            delay=0.46, dur=settle, rise=(0, 18)))
        ring_at = None      # the pulse is sized for a full-size badge
    elif _video_title(channel, video_title):
        sub = _text_layer([(_video_title(channel, video_title),
                            titles._load(titles.MONO_LIGHT_STACK, 26),
                            (255, 255, 255, 150), 0.0)], [0], align="centre")
        pieces.append(Piece(sub, ((WIDTH - sub.width) // 2, foot_y), delay=0.44,
                            dur=settle))

    duration = _length(spec)
    progress(f"End screen: Marquee, name at {size}px, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, accent, duration, False, ring_at))


# -------------------------------------------------------- afterglow template
def _render_afterglow(channel: Channel, video_title: str, out_path: Path,
                      backdrop: Path | None, progress: Progress) -> float:
    """The video's own last picture holds under a scrim, plates over it."""
    spec, key = channel.outro, "afterglow"
    accent = titles._hex(channel.style.accent)
    n = _n_slots(channel, key)
    settle = max(0.25, min(1.6, spec.settle))

    # This template is the picture: a backdrop of zero would leave it identical
    # to Quiet, so it asks for at least a little even when the knob is down.
    strength = max(0.62, float(spec.backdrop))
    shot = _backdrop(backdrop, strength, channel.style.grade)
    if shot is None:
        progress("No last picture to hold under the end screen; using the gradient")
    ground = Image.blend(intro._vgrad((16, 18, 24), (6, 6, 9)), shot, strength) \
        if shot is not None else intro._vgrad((16, 18, 24), (6, 6, 9))
    # A scrim in the lower half, so the type sits on something predictable
    # whatever the last picture happened to be.
    ground = ground.convert("RGBA")
    scrim = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    col = Image.new("L", (1, HEIGHT))
    col.putdata([int(190 * max(0.0, (y / HEIGHT - 0.34) / 0.66) ** 1.5)
                 for y in range(HEIGHT)])
    scrim.putalpha(col.resize((WIDTH, HEIGHT), Image.BILINEAR))
    ground = Image.alpha_composite(ground, scrim).convert("RGB")

    pieces: list[Piece] = []
    ys = HEIGHT - MARGIN - SQUARE - 30
    for i in range(n):
        x = WIDTH - MARGIN - SQUARE - (n - 1 - i) * (SQUARE + 44)
        pieces.append(Piece(_plate(SQUARE, SQUARE, accent, SLOT_LABELS[i]),
                            _at((x, ys)), delay=0.24 + 0.12 * i,
                            dur=settle, rise=(0, 40)))

    name_font = titles._load(titles.FONT_STACK, 68)
    lines = [(_cta(channel, key).upper(), titles._load(titles.KICKER_STACK, 25),
              _dim(accent, 235), 4.0), (channel.name, name_font, (255, 255, 255, 255), 0.5)]
    gaps = [18, 12]
    if spec.handle:
        lines.append((spec.handle, titles._load(titles.MONO_LIGHT_STACK, 25),
                      (255, 255, 255, 170), 0.0))
        gaps.append(0)
    block = _text_layer(lines, gaps, shadow=True)
    block_top = ys + SQUARE - block.height
    pieces.append(Piece(block, (MARGIN, block_top), delay=0.0, dur=settle,
                        rise=(0, 24)))

    ring_at = None
    if spec.subscribe:
        # Directly over the name, not floated off at the top of the frame: the
        # badge belongs to the channel block, and a picture is behind both.
        ring_at = _at((MARGIN, block_top - 44 - RING))
        pieces.append(Piece(_ring(accent, channel.name), ring_at, delay=0.14,
                            dur=settle, rise=(0, -22)))

    duration = _length(spec)
    progress(f"End screen: Afterglow, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, accent, duration, False, ring_at))


# ---------------------------------------------------------- console template
def _render_console(channel: Channel, video_title: str, out_path: Path,
                    backdrop: Path | None, progress: Progress) -> float:
    """Bracketed plates on a technical grid, everything set in mono."""
    spec, key = channel.outro, "console"
    accent = titles._hex(channel.style.accent)
    n = max(1, _n_slots(channel, key))
    settle = max(0.25, min(1.6, spec.settle))

    ground = _ground(spec, accent, _backdrop(backdrop, spec.backdrop,
                                             channel.style.grade), "grid")
    pieces: list[Piece] = []

    name_font = titles._load(titles.DISPLAY_STACK, 72)
    lines = [(channel.name.upper(), name_font, (255, 255, 255, 255), 2.0)]
    gaps = [14]
    meta = spec.handle or (channel.tagline.upper() if channel.tagline else "")
    if meta:
        lines.append((meta, titles._load(titles.MONO_LIGHT_STACK, 26),
                      _dim(accent, 215), 1.0))
        gaps.append(0)
    block = _text_layer(lines, gaps)
    pieces.append(Piece(block, (MARGIN, 118), delay=0.0, dur=settle, rise=(-24, 0)))

    rule = Image.new("RGBA", (6, 150), _dim(accent, 220))
    pieces.append(Piece(rule, (MARGIN - 34, 112), delay=0.0, dur=settle * 0.7,
                        rise=(0, -40)))

    cta_font = titles._load(titles.MONO_STACK, 26)
    cta = _text_layer([("> " + _cta(channel, key).upper(), cta_font,
                        (255, 255, 255, 195), 2.2)], [0])
    pieces.append(Piece(cta, (MARGIN, 118 + block.height + 34), delay=0.2, dur=settle))

    side = 380 if n >= 3 else SQUARE
    for i, (x, y) in enumerate(_row([(side, side)] * n, 46, WIDTH / 2, HEIGHT * 0.63)):
        pieces.append(Piece(_plate(side, side, accent, SLOT_LABELS[i], brackets=True),
                            _at((x, y)), delay=0.24 + 0.12 * i, dur=settle,
                            rise=(0, 38)))

    ring_at = None
    if spec.subscribe:
        ring_at = _at((WIDTH - MARGIN - RING, 118))
        pieces.append(Piece(_ring(accent, channel.name, mono=True), ring_at,
                            delay=0.12, dur=settle, rise=(26, 0)))

    duration = _length(spec)
    progress(f"End screen: Console, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, accent, duration, False, ring_at))


# ----------------------------------------------------------- ledger template
def _render_ledger(channel: Channel, video_title: str, out_path: Path,
                   backdrop: Path | None, progress: Progress) -> float:
    """A printed closing page: cream stock, Baskerville, plated frames."""
    spec, key = channel.outro, "ledger"
    # A colour mixed for a black slate is invisible on paper, so the accent is
    # printed at half strength here exactly as the Folio slate prints it.
    raw = titles._hex(channel.style.accent)
    accent = tuple(int(c * 0.62) for c in raw[:3]) + (255,)
    n = max(1, _n_slots(channel, key))
    settle = max(0.25, min(1.6, spec.settle))

    ground = _ground(spec, accent, None, "paper")
    ink = (38, 34, 30, 255)
    pieces: list[Piece] = []

    kicker = titles._load(titles.SMALLCAPS_STACK, 26)
    serif = titles._load(titles.SERIF_STACK, 82)
    lines = [(_cta(channel, key).upper(), kicker, (98, 90, 78, 255), 4.4),
             (channel.name, serif, ink, 1.0)]
    gaps = [22, 16]
    if _video_title(channel, video_title):
        lines.append((_video_title(channel, video_title),
                      titles._load(titles.SERIF_ITALIC_STACK, 32),
                      (86, 78, 68, 255), 0.0))
        gaps.append(0)
    block = _text_layer(lines, gaps, align="centre")
    pieces.append(Piece(block, ((WIDTH - block.width) // 2, 118), delay=0.0,
                        dur=settle, rise=(0, 18)))

    for i, w in ((0, 300), (1, 200)):
        rule = Image.new("RGBA", (w, 2 if i else 3), _dim(accent, 230 - i * 70))
        pieces.append(Piece(rule, ((WIDTH - w) // 2, 96 + i * 8), delay=0.08 * i,
                            dur=settle, rise=(0, 0)))

    side = 356
    for i, (x, y) in enumerate(_row([(side, side)] * n, 60, WIDTH / 2,
                                    118 + block.height + 62 + side / 2)):
        pieces.append(Piece(_plate(side, side, accent, SLOT_LABELS[i], paper=True),
                            _at((x, y)), delay=0.24 + 0.12 * i, dur=settle,
                            rise=(0, 34)))

    ring_at = None
    foot = HEIGHT - MARGIN + 4
    if spec.subscribe:
        small = 128
        badge = _ring(accent, channel.name, paper=True).resize(
            (small + PLATE_PAD * 2, small + PLATE_PAD * 2), Image.LANCZOS)
        label = _text_layer([("SUBSCRIBE", kicker, (98, 90, 78, 255), 4.4)], [0])
        total = small + 24 + label.width
        bx = int((WIDTH - total) / 2)
        pieces.append(Piece(badge, (bx - PLATE_PAD, foot - small - 26 - PLATE_PAD),
                            delay=0.42, dur=settle, rise=(0, 16)))
        pieces.append(Piece(label, (bx + small + 24,
                                    foot - small - 26 + (small - label.height) // 2),
                            delay=0.48, dur=settle, rise=(0, 16)))
    elif spec.handle:
        h = _text_layer([(spec.handle, titles._load(titles.SERIF_ITALIC_STACK, 28),
                          (98, 90, 78, 255), 0.0)], [0], align="centre")
        pieces.append(Piece(h, ((WIDTH - h.width) // 2, foot - h.height - 14),
                            delay=0.44, dur=settle))

    duration = _length(spec)
    progress(f"End screen: Ledger, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, accent, duration, True, ring_at))


# ------------------------------------------------------------ quiet template
def _render_quiet(channel: Channel, video_title: str, out_path: Path,
                  backdrop: Path | None, progress: Progress) -> float:
    """Near black, one rule, the plates low and the type small."""
    spec, key = channel.outro, "quiet"
    accent = titles._hex(channel.style.accent)
    n = _n_slots(channel, key)
    settle = max(0.25, min(1.6, spec.settle))

    ground = _ground(spec, accent, _backdrop(backdrop, spec.backdrop,
                                             channel.style.grade), "flat")
    pieces: list[Piece] = []

    cta_font = titles._load(titles.KICKER_STACK, 28)
    lines = [(_cta(channel, key), cta_font, (255, 255, 255, 215), 1.4),
             (channel.name.upper(), titles._load(titles.KICKER_STACK, 22),
              (255, 255, 255, 130), 3.4)]
    gaps = [20, 0]
    if spec.handle:
        lines[1] = (spec.handle.upper(), titles._load(titles.MONO_LIGHT_STACK, 22),
                    (255, 255, 255, 130), 2.2)
    block = _text_layer(lines, gaps, align="centre")
    top = int(HEIGHT * 0.26)
    pieces.append(Piece(block, ((WIDTH - block.width) // 2, top), delay=0.0,
                        dur=settle, rise=(0, 16)))

    rule = Image.new("RGBA", (150, 2), _dim(accent, 200))
    pieces.append(Piece(rule, ((WIDTH - 150) // 2, top - 40), delay=0.1, dur=settle,
                        rise=(0, 0)))

    side = 330
    row_cy = HEIGHT * 0.60
    for i, (x, y) in enumerate(_row([(side, side)] * max(1, n), 56, WIDTH / 2, row_cy)):
        if i >= n:
            break
        pieces.append(Piece(_plate(side, side, accent, SLOT_LABELS[i]), _at((x, y)),
                            delay=0.26 + 0.1 * i, dur=settle, rise=(0, 30)))

    ring_at = None
    if spec.subscribe:
        small = 120
        badge = _ring(accent, channel.name).resize(
            (small + PLATE_PAD * 2, small + PLATE_PAD * 2), Image.LANCZOS)
        by = int(row_cy + side / 2 + 46) if n else int(row_cy)
        pieces.append(Piece(badge, ((WIDTH - small) // 2 - PLATE_PAD, by - PLATE_PAD),
                            delay=0.4, dur=settle, rise=(0, 14)))

    duration = _length(spec)
    progress(f"End screen: Quiet, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, accent, duration, False, ring_at))


# ============================================================================
# The theme-led end screens. Same plates in the same element-sized places — a
# YouTube card does not care what is behind it — but the ground, the second
# colour and the icons come from the channel's theme. The plates themselves stay
# square to the frame even where the artwork is on a slant: an element dropped
# on a rotated plate would sit crooked against it.
# ============================================================================
def _themed_ground(channel: Channel, pal, backdrop: Path | None,
                   kind: str) -> Image.Image:
    """The colourful grounds, with the video's last picture behind if asked."""
    spec = channel.outro
    if kind == "icons":
        base = motifs.gradient((WIDTH, HEIGHT),
                               [motifs.mix(pal.ground, pal.accent2, 0.22), pal.ground,
                                motifs.mix(pal.ground, pal.accent, 0.30)], 118)
        base = Image.alpha_composite(base.convert("RGBA"), motifs.icon_field(
            (WIDTH, HEIGHT), pal.icons, [pal.accent, pal.accent2, pal.ink],
            cell=118, alpha=46, angle=-14, seed=intro._seed(channel)))
    elif kind == "soft":
        base = motifs.radial((WIDTH, HEIGHT), motifs.shade(pal.ground, 1.05),
                             motifs.mix(pal.ground, pal.accent, 0.34),
                             centre=(0.5, 0.36), radius=1.0)
        base = Image.alpha_composite(base.convert("RGBA"), motifs.icon_field(
            (WIDTH, HEIGHT), pal.icons, [pal.accent, motifs.shade(pal.accent2, 0.9)],
            cell=116, alpha=52, angle=7, seed=intro._seed(channel)))
    elif kind == "stripes":
        base = motifs.gradient((WIDTH, HEIGHT),
                               [pal.ground, motifs.shade(pal.ground, 0.5)], 100)
        base = Image.alpha_composite(base.convert("RGBA"), motifs.stripes(
            (WIDTH, HEIGHT), [pal.accent[:3] + (220,), (0, 0, 0, 0),
                              pal.accent2[:3] + (44,), (0, 0, 0, 0)], 74, angle=-24))
    else:                                     # words
        base = motifs.gradient((WIDTH, HEIGHT),
                               [pal.ground, motifs.mix(pal.ground, pal.accent2, 0.2)],
                               135)
        base = Image.alpha_composite(base.convert("RGBA"), motifs.word_field(
            (WIDTH, HEIGHT), channel.name, titles.DISPLAY_STACK,
            [pal.accent, pal.accent2], rows=7, angle=-9, alpha=105))

    shot = _backdrop(backdrop, spec.backdrop, channel.style.grade)
    if shot is not None:
        base = Image.blend(base.convert("RGB"), shot,
                           max(0.0, min(1.0, float(spec.backdrop)))).convert("RGBA")
    return base.convert("RGB")


def _plate_body(pal, lift: float = 0.11):
    """The panel colour: the theme's ground, lifted just off itself.

    Lifting with `shade` overshoots badly on a very dark ground — three
    quarters of the way to white is not a panel, it is a hole — so the lift is
    a small mix toward white and stays in the theme's own colour.
    """
    if pal.light:
        return (255, 253, 249, 250)
    return motifs.mix(pal.ground, (255, 255, 255, 255), lift)[:3] + (242,)


def _themed_plate(pal, w: int, h: int, label: str) -> Image.Image:
    """A plate in the channel's own colours rather than the house graphite."""
    body = _plate_body(pal)
    return _plate(w, h, pal.accent, label, paper=pal.light, body=body,
                  ink=pal.ink if pal.light else (255, 255, 255), edge=4)


def _name_block(channel: Channel, pal, stack, size: int, align: str = "left",
                shadow: bool = True) -> Image.Image:
    """Name, tagline and handle as one arriving block, in the theme's ink."""
    spec = channel.outro
    ink = pal.ink if pal.light else (255, 255, 255, 255)
    lines = [(channel.name, titles._load(stack, size), ink, 0.5)]
    gaps = [12]
    if channel.tagline:
        lines.append((channel.tagline.upper(), titles._load(titles.KICKER_STACK, 24),
                      ink[:3] + (185,), 3.2))
        gaps.append(14)
    if spec.handle:
        lines.append((spec.handle, titles._load(titles.MONO_LIGHT_STACK, 26),
                      _dim(pal.accent, 235), 0.0))
        gaps.append(14)
    return _text_layer(lines, gaps, align=align, shadow=shadow and not pal.light)


# ----------------------------------------------------------- arcade template
def _render_arcade(channel: Channel, video_title: str, out_path: Path,
                   backdrop: Path | None, progress: Progress) -> float:
    """Cartridge plates on a scrolling icon field, under a blinking prompt."""
    spec, key = channel.outro, "arcade"
    pal = themes.palette(channel.style)
    n = _n_slots(channel, key)
    settle = max(0.25, min(1.6, spec.settle))

    ground = _themed_ground(channel, pal, backdrop, "icons")
    ground = Image.alpha_composite(ground.convert("RGBA"),
                                   intro._scanlines(28)).convert("RGB")
    pieces: list[Piece] = []

    ys = int((HEIGHT - SQUARE) / 2) + 14
    for i in range(n):
        x = WIDTH - MARGIN - SQUARE - (n - 1 - i) * (SQUARE + 44)
        pieces.append(Piece(_themed_plate(pal, SQUARE, SQUARE, SLOT_LABELS[i]),
                            _at((x, ys)), delay=0.18 + 0.12 * i, dur=settle,
                            rise=(0, 52)))

    cta_font = titles._load(titles.DISPLAY_STACK, 34)
    cta = _text_layer([(_cta(channel, key).upper(), cta_font,
                        (255, 255, 255, 255), 3.0)], [0], shadow=True)
    pieces.append(Piece(cta, (WIDTH - MARGIN - cta.width, ys - 30 - cta.height),
                        delay=0.3, dur=settle))
    if _video_title(channel, video_title):
        sub = _text_layer([(_video_title(channel, video_title),
                            titles._load(titles.MONO_LIGHT_STACK, 24),
                            (255, 255, 255, 160), 0.0)], [0], shadow=True)
        pieces.append(Piece(sub, (WIDTH - MARGIN - sub.width, ys + SQUARE + 20),
                            delay=0.4, dur=settle))

    # The wordmark carries the same hard colour shadow the arcade slate uses.
    name_lines = intro._wordmark_lines(channel.name)
    font, size = intro._fit_display(name_lines, WIDTH - SQUARE * 2 - 260, 300, cap=150)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    asc, desc = font.getmetrics()
    lead = int(size * 0.88)
    wm_h = lead * (len(name_lines) - 1) + asc + desc
    wm_w = int(max(probe.textlength(l, font=font) for l in name_lines)) + 30
    off = max(5, int(size * 0.06))
    wm = Image.new("RGBA", (wm_w + off, wm_h + off + 16), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wm)
    for dx, dy, fill in ((off, off, pal.accent2), (0, 0, (255, 255, 255, 255))):
        for i, line in enumerate(name_lines):
            wd.text((dx, i * lead + dy), line, font=font, fill=fill)

    column = wm.height + (44 + RING if spec.subscribe else 0)
    top = ys + (SQUARE - column) // 2
    pieces.append(Piece(wm, (MARGIN, top), delay=0.0, dur=settle, rise=(-30, 0)))

    ring_at = None
    if spec.subscribe:
        badge_y = top + wm.height + 44
        ring_at = _at((MARGIN, badge_y))
        pieces.append(Piece(_ring(pal.accent, channel.name, body=_plate_body(pal),
                                  ink=_dim(pal.accent2, 255)),
                            ring_at, delay=0.14, dur=settle, rise=(-26, 0)))
        pieces.append(Piece(_pill("SUBSCRIBE", pal.accent),
                            (MARGIN + RING + 34, badge_y + RING // 2 - 29),
                            delay=0.26, dur=settle, rise=(-20, 0)))

    duration = _length(spec)
    tag = (channel.tagline or "press start").upper()
    tag_font = titles._load(titles.MONO_STACK, 26)
    tag_w = intro._tracked_width(probe, tag, tag_font, 6.0)
    base_live = _live(spec, pal.accent, duration, pal.light, ring_at)

    def live(t: float):
        out = list(base_live(t))
        # A prompt that blinks for the whole hold, which is what an attract
        # screen does and what stops a long card looking frozen.
        if t > settle and (t - settle) % 1.1 < 0.72:
            patch = Image.new("RGBA", (int(tag_w) + 20, 48), (0, 0, 0, 0))
            titles._tracked(ImageDraw.Draw(patch), (0, 0), tag, tag_font,
                            _dim(pal.accent2, 255), 6.0)
            out.append(((MARGIN, HEIGHT - MARGIN + 4), patch))
        return out

    progress(f"End screen: Arcade, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration, live)


# ------------------------------------------------------------ gloss template
def _render_gloss(channel: Channel, video_title: str, out_path: Path,
                  backdrop: Path | None, progress: Progress) -> float:
    """Soft light, plates in a centred row, everything set in the book face."""
    spec, key = channel.outro, "gloss"
    pal = themes.palette(channel.style)
    n = max(0, _n_slots(channel, key))
    settle = max(0.25, min(1.6, spec.settle))

    ground = _themed_ground(channel, pal, backdrop, "soft")
    pieces: list[Piece] = []
    ink = pal.ink if pal.light else (255, 255, 255, 255)

    kicker = titles._load(titles.SMALLCAPS_STACK, 28)
    serif = titles._load(titles.SERIF_STACK, 86)
    lines = [(_cta(channel, key).upper(), kicker, _dim(pal.accent, 245), 5.0),
             (channel.name, serif, ink, 1.0)]
    gaps = [24, 16]
    if _video_title(channel, video_title):
        lines.append((_video_title(channel, video_title),
                      titles._load(titles.SERIF_ITALIC_STACK, 32), ink[:3] + (190,), 0.0))
        gaps.append(0)
    block = _text_layer(lines, gaps, align="centre")
    pieces.append(Piece(block, ((WIDTH - block.width) // 2, 132), delay=0.0,
                        dur=settle, rise=(0, 20)))

    side = 352
    row_cy = 132 + block.height + 74 + side / 2
    for i, (x, y) in enumerate(_row([(side, side)] * n, 56, WIDTH / 2, row_cy)):
        pieces.append(Piece(_themed_plate(pal, side, side, SLOT_LABELS[i]),
                            _at((x, y)), delay=0.24 + 0.12 * i, dur=settle,
                            rise=(0, 34)))

    ring_at = None
    if spec.subscribe:
        small = 132
        badge = _ring(pal.accent, channel.name, paper=pal.light,
                      body=_plate_body(pal),
                      ink=(pal.ink if pal.light else (255, 255, 255, 255))
                      ).resize((small + PLATE_PAD * 2, small + PLATE_PAD * 2), Image.LANCZOS)
        label = _text_layer([("SUBSCRIBE", kicker,
                              (pal.ink[:3] + (225,)) if pal.light
                              else (255, 255, 255, 235), 5.0)], [0])
        total = small + 26 + label.width
        bx = int((WIDTH - total) / 2)
        by = int(min(row_cy + side / 2 + 44, HEIGHT - MARGIN - small))
        pieces.append(Piece(badge, (bx - PLATE_PAD, by - PLATE_PAD), delay=0.42,
                            dur=settle, rise=(0, 16)))
        pieces.append(Piece(label, (bx + small + 26, by + (small - label.height) // 2),
                            delay=0.48, dur=settle, rise=(0, 16)))

    # Sparkles that keep twinkling for the whole hold, as on the slate.
    rnd = random.Random(intro._seed(channel))
    spots = [(rnd.randrange(140, WIDTH - 140), rnd.randrange(90, HEIGHT - 90),
              rnd.uniform(20, 48), rnd.uniform(0, 6.2), rnd.uniform(1.3, 2.8))
             for _ in range(12)]
    duration = _length(spec)
    base_live = _live(spec, pal.accent, duration, pal.light, ring_at)

    def live(t: float):
        out = list(base_live(t))
        for x, y, sz, phase, speed in spots:
            v = 0.5 + 0.5 * math.sin(t * speed + phase)
            a = int(210 * v)
            if a > 12:
                g = motifs.icon("star4", int(sz * (0.6 + v * 0.6)), (255, 255, 255, a))
                out.append(((int(x - g.width / 2), int(y - g.height / 2)), g))
        return out

    progress(f"End screen: Gloss, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration, live)


# --------------------------------------------------------- sideline template
def _render_sideline(channel: Channel, video_title: str, out_path: Path,
                     backdrop: Path | None, progress: Progress) -> float:
    """A slanted band across a striped field, with upright plates over it.

    The band is on the diagonal because that is the sports graphic; the plates
    are not, because a YouTube element dropped on a rotated plate sits crooked
    against it and the whole point of a plate is that something covers it.
    """
    spec, key = channel.outro, "sideline"
    pal = themes.palette(channel.style)
    n = _n_slots(channel, key)
    settle = max(0.25, min(1.6, spec.settle))
    TILT = -9.0

    ground = _themed_ground(channel, pal, backdrop, "stripes").convert("RGBA")
    band_h = 520
    big = Image.new("RGBA", (WIDTH * 2, HEIGHT * 2), (0, 0, 0, 0))
    bd = ImageDraw.Draw(big)
    cy = HEIGHT
    top_e, bot_e = cy - band_h / 2, cy + band_h / 2
    bd.rectangle([0, top_e, WIDTH * 2, bot_e], fill=motifs.shade(pal.ground, 0.85)[:3] + (247,))
    bd.rectangle([0, top_e - 8, WIDTH * 2, top_e], fill=pal.accent)
    bd.rectangle([0, bot_e, WIDTH * 2, bot_e + 8], fill=pal.accent)
    band = big.rotate(TILT, Image.BICUBIC).crop(
        (WIDTH // 2, HEIGHT // 2, WIDTH // 2 + WIDTH, HEIGHT // 2 + HEIGHT))
    ground = Image.alpha_composite(ground, band).convert("RGB")

    pieces: list[Piece] = []
    ys = int((HEIGHT - SQUARE) / 2) + 6
    for i in range(n):
        x = WIDTH - MARGIN - SQUARE - (n - 1 - i) * (SQUARE + 44)
        pieces.append(Piece(_themed_plate(pal, SQUARE, SQUARE, SLOT_LABELS[i]),
                            _at((x, ys)), delay=0.2 + 0.12 * i, dur=settle,
                            rise=(90, 0)))

    block = _name_block(channel, pal, titles.CONDENSED_STACK, 84)
    column = block.height + (44 + RING if spec.subscribe else 0)
    top = ys + (SQUARE - column) // 2
    pieces.append(Piece(block, (MARGIN, top), delay=0.0, dur=settle, rise=(-70, 0)))

    cta_font = titles._load(titles.KICKER_STACK, 28)
    text = _cta(channel, key).upper()
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    tw = intro._tracked_width(probe, text, cta_font, 6.0)
    tab = Image.new("RGBA", (int(tw) + 52, 60), (0, 0, 0, 0))
    ImageDraw.Draw(tab).rectangle([0, 0, tw + 51, 59], fill=pal.accent)
    titles._tracked(ImageDraw.Draw(tab), (26, 14), text, cta_font,
                    motifs.readable_on(pal.accent), 6.0)
    pieces.append(Piece(tab, (WIDTH - MARGIN - tab.width, ys - 26 - tab.height),
                        delay=0.32, dur=settle, rise=(60, 0)))

    if _video_title(channel, video_title):
        sub = _text_layer([(_video_title(channel, video_title).upper(),
                            titles._load(titles.KICKER_STACK, 24),
                            (255, 255, 255, 170), 3.0)], [0], shadow=True)
        pieces.append(Piece(sub, (WIDTH - MARGIN - sub.width, ys + SQUARE + 20),
                            delay=0.42, dur=settle))

    ring_at = None
    if spec.subscribe:
        badge_y = top + block.height + 44
        ring_at = _at((MARGIN, badge_y))
        pieces.append(Piece(_ring(pal.accent, channel.name, body=_plate_body(pal)),
                            ring_at, delay=0.16, dur=settle, rise=(-40, 0)))
        pieces.append(Piece(_pill("SUBSCRIBE", pal.accent),
                            (MARGIN + RING + 34, badge_y + RING // 2 - 29),
                            delay=0.28, dur=settle, rise=(-30, 0)))

    duration = _length(spec)
    progress(f"End screen: Sideline, {n} plate(s), {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, pal.accent, duration, pal.light, ring_at))


# --------------------------------------------------------- wordmark template
def _render_wordmark(channel: Channel, video_title: str, out_path: Path,
                     backdrop: Path | None, progress: Progress) -> float:
    """The name as wallpaper, a band cut out of it, plates below. No pictures."""
    spec, key = channel.outro, "wordmark"
    pal = themes.palette(channel.style)
    n = _n_slots(channel, key)
    settle = max(0.25, min(1.6, spec.settle))

    ground = _themed_ground(channel, pal, backdrop, "words")
    pieces: list[Piece] = []

    name_font, size = intro._fit_tracked(channel.name.upper(), titles.DISPLAY_STACK,
                                         WIDTH - 460, 4.0, cap=132)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    name_w = intro._tracked_width(probe, channel.name.upper(), name_font, 4.0)
    asc, desc = name_font.getmetrics()
    band_h = asc + desc + 108
    band_y = 116

    band = Image.new("RGBA", (WIDTH, band_h), pal.ground[:3] + (240,))
    bd = ImageDraw.Draw(band)
    bd.rectangle([0, 0, WIDTH, 3], fill=pal.accent)
    bd.rectangle([0, band_h - 4, WIDTH, band_h], fill=pal.accent)
    titles._tracked(bd, ((WIDTH - name_w) / 2, 54), channel.name.upper(), name_font,
                    (255, 255, 255, 255), 4.0)
    tag = (channel.tagline or _cta(channel, key)).upper()
    tag_font = titles._load(titles.MONO_STACK, 24)
    tag_w = intro._tracked_width(probe, tag, tag_font, 7.0)
    titles._tracked(bd, ((WIDTH - tag_w) / 2, 20), tag, tag_font,
                    _dim(pal.accent2, 235), 7.0)
    pieces.append(Piece(band, (0, band_y), delay=0.0, dur=settle, rise=(0, -26)))

    side = 356
    row_cy = band_y + band_h + 72 + side / 2
    for i, (x, y) in enumerate(_row([(side, side)] * n, 52, WIDTH / 2, row_cy)):
        pieces.append(Piece(_themed_plate(pal, side, side, SLOT_LABELS[i]),
                            _at((x, y)), delay=0.22 + 0.12 * i, dur=settle,
                            rise=(0, 40)))

    ring_at = None
    if spec.subscribe:
        small = 128
        badge = _ring(pal.accent, channel.name, body=_plate_body(pal)
                      ).resize((small + PLATE_PAD * 2, small + PLATE_PAD * 2), Image.LANCZOS)
        pill = _pill("SUBSCRIBE", pal.accent)
        total = small + 26 + pill.width
        bx = int((WIDTH - total) / 2)
        by = int(min(row_cy + side / 2 + 40, HEIGHT - MARGIN - small + 20))
        pieces.append(Piece(badge, (bx - PLATE_PAD, by - PLATE_PAD), delay=0.42,
                            dur=settle, rise=(0, 16)))
        pieces.append(Piece(pill, (bx + small + 26, by + (small - pill.height) // 2),
                            delay=0.48, dur=settle, rise=(0, 16)))
    elif _video_title(channel, video_title):
        sub = _text_layer([(_video_title(channel, video_title),
                            titles._load(titles.MONO_LIGHT_STACK, 26),
                            (255, 255, 255, 170), 0.0)], [0], align="centre", shadow=True)
        pieces.append(Piece(sub, ((WIDTH - sub.width) // 2,
                                  int(row_cy + side / 2 + 46)), delay=0.44, dur=settle))

    duration = _length(spec)
    progress(f"End screen: Wordmark, {n} plate(s), name at {size}px, {duration:.0f}s")
    return _play(out_path, ground, pieces, duration,
                 _live(spec, pal.accent, duration, pal.light, ring_at))


# ------------------------------------------------------------------ dispatch
_RENDERERS = {
    "twoup": _render_twoup,
    "marquee": _render_marquee,
    "afterglow": _render_afterglow,
    "console": _render_console,
    "ledger": _render_ledger,
    "quiet": _render_quiet,
    "arcade": _render_arcade,
    "gloss": _render_gloss,
    "sideline": _render_sideline,
    "wordmark": _render_wordmark,
}


def _length(spec) -> float:
    """YouTube will not show an end screen shorter than 5s or longer than 20."""
    return max(5.0, min(20.0, float(spec.duration)))


def render_outro(channel: Channel, video_title: str, out_path: Path,
                 backdrop: Path | None = None,
                 progress: Progress = lambda m: None) -> float:
    """Render the end screen to a silent mp4. Returns its duration in seconds."""
    render = _RENDERERS.get(channel.outro.template, _render_twoup)
    return render(channel, video_title, out_path, backdrop, progress)


def preview_path(channel: Channel) -> Path:
    return channel_dir(channel.id) / "cache" / "outro_preview.mp4"

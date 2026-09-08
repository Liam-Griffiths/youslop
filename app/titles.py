"""Lower-left slide typography, rendered to transparent PNGs.

This ffmpeg build has no libfreetype, so drawtext is unavailable. Rendering with
Pillow is the better path anyway: real letter-spacing, a soft shadow and a
gradient scrim so white type survives a bright archival photograph.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import HEIGHT, WIDTH

# Preferred faces, best first. Each entry is (path, ttc index).
FONT_STACK = [
    ("/System/Library/Fonts/Avenir Next.ttc", 2),          # Demi Bold
    ("/System/Library/Fonts/Supplemental/GillSans.ttc", 4),  # SemiBold
    ("/System/Library/Fonts/Supplemental/Futura.ttc", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 1),
]
KICKER_STACK = [
    ("/System/Library/Fonts/Avenir Next.ttc", 5),          # Medium
    ("/System/Library/Fonts/Supplemental/GillSans.ttc", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 0),
]

# Editorial monospace, for slates that want to look like a terminal rather than
# a documentary. Fixed advance also means a per-character reveal never reflows.
_HOME = str(Path.home())
MONO_STACK = [
    (f"{_HOME}/Library/Fonts/iAWriterMonoS-Bold.ttf", 0),
    ("/System/Library/Fonts/Menlo.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Courier New Bold.ttf", 0),
    ("/System/Library/Fonts/Courier.ttc", 1),
]
MONO_LIGHT_STACK = [
    (f"{_HOME}/Library/Fonts/iAWriterMonoS-Regular.ttf", 0),
    ("/System/Library/Fonts/Menlo.ttc", 0),
    ("/System/Library/Fonts/Courier.ttc", 0),
]
CONDENSED_STACK = [
    ("/System/Library/Fonts/Avenir Next Condensed.ttc", 0),   # Bold
    ("/System/Library/Fonts/Supplemental/Futura.ttc", 4),
    ("/System/Library/Fonts/Helvetica.ttc", 1),
]

# Book faces, for the slate that is set as a printed title page. Baskerville is
# the house choice; the fallbacks step through the other transitionals on macOS.
SERIF_STACK = [
    ("/System/Library/Fonts/Supplemental/Baskerville.ttc", 0),      # Regular
    ("/System/Library/Fonts/Supplemental/Hoefler Text.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Didot.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", 0),
]
SERIF_ITALIC_STACK = [
    ("/System/Library/Fonts/Supplemental/Baskerville.ttc", 2),      # Italic
    ("/System/Library/Fonts/Supplemental/Hoefler Text.ttc", 2),
    ("/System/Library/Fonts/Supplemental/Didot.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Georgia Italic.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf", 0),
]
SMALLCAPS_STACK = [
    ("/System/Library/Fonts/Supplemental/Bodoni 72 Smallcaps Book.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Baskerville.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
]

# Heavy display face for slates that need to hit. SF Compact Black is slightly
# condensed and reads as broadcast technical rather than editorial.
DISPLAY_STACK = [
    ("/System/Library/Fonts/SFCompact.ttf", 0),               # Black
    ("/System/Library/Fonts/Supplemental/Futura.ttc", 4),     # Condensed ExtraBold
    ("/System/Library/Fonts/Avenir Next Condensed.ttc", 0),
    ("/System/Library/Fonts/Avenir Next.ttc", 8),             # Heavy
]

# Layout, in 1080p pixels.
MARGIN_X = 104
BASE_Y = 946          # bottom of the title text block
RULE_W, RULE_H = 58, 3
KICKER_SIZE = 21
TITLE_SIZE = 56
KICKER_TRACKING = 3.2


def _load(stack: list[tuple[str, int]], size: int) -> ImageFont.FreeTypeFont:
    for path, index in stack:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha)
    except ValueError:
        return (232, 195, 106, alpha)


def _tracked(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, tracking: float) -> float:
    """Draw letter-spaced text. Returns the advance width."""
    x, y = xy
    start = x
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - start - tracking


def _scrim(size: tuple[int, int]) -> Image.Image:
    """A soft dark wash in the lower left so type never fights the picture."""
    w, h = size
    scrim = Image.new("L", (w, h), 0)
    px = scrim.load()
    top = int(h * 0.52)          # gradient starts just over halfway down
    right = int(w * 0.62)        # and fades out before the right third
    for y in range(top, h):
        vy = (y - top) / max(1, h - top)
        vy = vy * vy                       # ease in, so the top edge is invisible
        for x in range(0, right, 4):       # 4px steps, blurred out below
            vx = 1.0 - (x / right) ** 1.6
            val = int(150 * vy * vx)
            for dx in range(4):
                if x + dx < w:
                    px[x + dx, y] = val
    return scrim.filter(ImageFilter.GaussianBlur(26))


_SCRIM_CACHE: Image.Image | None = None


def scrim_layer() -> Image.Image:
    global _SCRIM_CACHE
    if _SCRIM_CACHE is None:
        _SCRIM_CACHE = _scrim((WIDTH, HEIGHT))
    return _SCRIM_CACHE


# ------------------------------------------------------------------ captions
# The essay format sets the narration on screen instead of a chapter title, so
# the type is much bigger, centred, and sits on a solid plate rather than a
# gradient scrim: it has to hold at a glance over a busy screenshot, and it is
# read while it is being spoken rather than lingered over.
CAPTION_BAND_Y = 858          # centre of the caption block
CAPTION_MAX_W = 1460
CAPTION_PAD_X, CAPTION_PAD_Y = 36, 20
CAPTION_CAP = 62              # largest size before it starts stepping down
CAPTION_LINES = 3


# Where a caption is allowed to end, best first: a full sentence beats a
# clause beats a bare word count. Breaking mid-sentence is what produced cards
# like "To get it on shelves they" followed by "needed a publisher" — legible,
# but it reads as a caption that got cut off rather than one that ended.
_SENTENCE_END = ".!?…"
_CLAUSE_END = ",;:—"


def _split_on(words: list[str], enders: str) -> list[list[str]]:
    """`words`, cut every time one ends with a character in `enders`."""
    atoms: list[list[str]] = []
    run: list[str] = []
    for w in words:
        run.append(w)
        if w.rstrip("\"'”’)").endswith(tuple(enders)):
            atoms.append(run)
            run = []
    if run:
        atoms.append(run)
    return atoms


def _pack(atoms: list[list[str]], max_words: int) -> list[list[str]]:
    """Greedily fill chunks up to `max_words`, never splitting an atom."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    for atom in atoms:
        if cur and len(cur) + len(atom) > max_words:
            chunks.append(cur)
            cur = list(atom)
        else:
            cur += atom
    if cur:
        chunks.append(cur)
    return chunks


def _merge_small(chunks: list[list[str]], min_words: int) -> list[list[str]]:
    """No chunk stands alone with only a couple of words in it.

    A caption that flashes up reading just "But then." before the next one
    replaces it is a stumble, not a beat — fold it into a neighbour instead.
    """
    out: list[list[str]] = []
    for c in chunks:
        if out and len(c) < min_words:
            out[-1] = out[-1] + c
        else:
            out.append(list(c))
    if len(out) > 1 and len(out[0]) < min_words:
        out[1] = out[0] + out[1]
        out.pop(0)
    return out


def essay_chunks(text: str, target_words: int = 12,
                 max_words: int = 17, min_words: int = 4) -> list[str]:
    """Split a paragraph into caption-sized phrases.

    Packing happens at the *sentence* level first — a caption holding two
    short sentences is normal; one that stops before the sentence it started
    does not read as a caption at all, it reads as a cut. `_pack` never merges
    an oversized atom with a neighbour (its own length alone already exceeds
    the budget), so a sentence too long to fit comes out of this pass alone,
    and only that one gets split further — at a clause boundary if it has
    one, at a bare word count only if it must. Sub-dividing a long sentence
    never reconsiders merging its pieces with a different sentence, which is
    what a second, flatter packing pass used to do by accident: it would glue
    the tail clause of a long sentence onto the short sentence in front of it,
    producing a caption that ended mid-sentence regardless.
    """
    words = (text or "").split()
    if not words:
        return []

    chunks: list[list[str]] = []
    for group in _pack(_split_on(words, _SENTENCE_END), max_words):
        if len(group) <= max_words:
            chunks.append(group)
            continue
        for clause in _pack(_split_on(group, _CLAUSE_END), max_words):
            if len(clause) <= max_words:
                chunks.append(clause)
                continue
            # A single clause longer than the budget: no punctuation left to
            # break on, so this is the one place a bare word count decides.
            step = max(1, math.ceil(len(clause) / math.ceil(len(clause) / target_words)))
            chunks += [clause[i:i + step] for i in range(0, len(clause), step)]

    chunks = _merge_small(chunks, min_words)
    return [" ".join(c) for c in chunks]


def _wrap(probe: ImageDraw.ImageDraw, words: list[str], font, max_w: float) -> list[str]:
    lines, line = [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if line and probe.textlength(trial, font=font) > max_w:
            lines.append(line)
            line = w
        else:
            line = trial
    if line:
        lines.append(line)
    return _debalance(probe, lines, font, max_w)


def _debalance(probe: ImageDraw.ImageDraw, lines: list[str], font, max_w: float) -> list[str]:
    """Pull a line back from a true one-word orphan.

    A greedy wrap that happens to leave a single word alone on the last line
    reads as broken rather than as a caption that simply ended — "game," on
    its own line under nine words above it. Two words at the end is normal
    and left alone; this only intervenes on the one-word case, walking a word
    back from the line above as long as it still fits.
    """
    lines = list(lines)
    while len(lines) >= 2 and len(lines[-1].split()) == 1:
        prev_words = lines[-2].split()
        if len(prev_words) <= 1:
            break
        pulled = f"{prev_words[-1]} {lines[-1]}"
        if probe.textlength(pulled, font=font) > max_w:
            break
        lines[-2] = " ".join(prev_words[:-1])
        lines[-1] = pulled
    return lines


def _fit_caption(text: str, max_w: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest size at which `text` fits the measure in `CAPTION_LINES`."""
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    words = text.split()
    size = CAPTION_CAP
    while size > 26:
        font = _load(DISPLAY_STACK, size)
        lines = _wrap(probe, words, font, max_w)
        if len(lines) <= CAPTION_LINES and all(
                probe.textlength(l, font=font) <= max_w for l in lines):
            return font, lines
        size -= 3
    font = _load(DISPLAY_STACK, 26)
    return font, _wrap(probe, words, font, max_w)[:CAPTION_LINES]


def render_caption(text: str, accent: str = "#E8C36A",
                   out_path: Path | None = None) -> Path:
    """One narration caption as a transparent 1920x1080 PNG."""
    card = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)

    font, lines = _fit_caption(" ".join((text or "").split()), CAPTION_MAX_W)
    ascent, descent = font.getmetrics()
    leading = int(font.size * 1.04)
    block_h = leading * (len(lines) - 1) + ascent + descent
    widest = max(d.textlength(l, font=font) for l in lines)

    # The plate: wide enough for the longest line, tall enough for the block.
    x0 = (WIDTH - widest) / 2 - CAPTION_PAD_X
    x1 = (WIDTH + widest) / 2 + CAPTION_PAD_X
    y0 = CAPTION_BAND_Y - block_h / 2 - CAPTION_PAD_Y
    y1 = CAPTION_BAND_Y + block_h / 2 + CAPTION_PAD_Y
    d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=(9, 10, 14, 232))
    # An accent edge along the bottom, so the plate belongs to the channel.
    d.rounded_rectangle([x0, y1 - 7, x1, y1], radius=3, fill=_hex(accent))

    y = y0 + CAPTION_PAD_Y
    for line in lines:
        lw = d.textlength(line, font=font)
        d.text(((WIDTH - lw) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += leading

    out_path = out_path or Path("caption.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(out_path, "PNG")
    return out_path


def render_chapter(title: str, kicker: str = "", accent: str = "#E8C36A",
                   out_path: Path | None = None) -> Path:
    """The chapter card the essay format holds on between sections.

    Full frame rather than a corner card: it lands in a silence, so there is
    nothing else on screen competing with it and no reason to tuck it away.
    """
    card = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    # A near-opaque wash over the outgoing picture: the section break should
    # read as a break, not as a caption over the last shot of the last one.
    card.paste(Image.new("RGBA", (WIDTH, HEIGHT), (9, 10, 14, 232)), (0, 0))
    d = ImageDraw.Draw(card)

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    size = 108
    while size > 46:
        font = _load(DISPLAY_STACK, size)
        lines = _wrap(probe, title.split(), font, WIDTH - 360)
        if len(lines) <= 2:
            break
        size -= 6
    else:
        font, lines = _load(DISPLAY_STACK, 46), [title]

    leading = int(size * 1.06)
    block_h = leading * (len(lines) - 1) + sum(font.getmetrics())
    top = (HEIGHT - block_h) // 2 + (16 if kicker else 0)

    if kicker:
        kf = _load(KICKER_STACK, 24)
        kw = sum(probe.textlength(c, font=kf) for c in kicker.upper()) + 3.4 * (len(kicker) - 1)
        _tracked(d, ((WIDTH - kw) / 2, top - 78), kicker.upper(), kf,
                 (255, 255, 255, 180), 3.4)

    y = top
    for line in lines:
        lw = d.textlength(line, font=font)
        d.text(((WIDTH - lw) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += leading

    rule_w = 96
    d.rectangle([(WIDTH - rule_w) / 2, top + block_h + 30,
                 (WIDTH + rule_w) / 2, top + block_h + 34], fill=_hex(accent))

    out_path = out_path or Path("chapter.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(out_path, "PNG")
    return out_path


def render_title(
    title: str,
    kicker: str = "",
    accent: str = "#E8C36A",
    out_path: Path | None = None,
) -> Path:
    """Render one lower-left title card as a transparent 1920x1080 PNG."""
    card = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    # Scrim first, tinted near-black, so the type sits on its own ground.
    scrim = scrim_layer()
    card.paste(Image.new("RGBA", (WIDTH, HEIGHT), (8, 9, 12, 255)), (0, 0), scrim)

    title_font = _load(FONT_STACK, TITLE_SIZE)
    kicker_font = _load(KICKER_STACK, KICKER_SIZE)

    # Type goes on its own layer so the shadow can be blurred independently.
    text = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)

    y = BASE_Y
    ascent, descent = title_font.getmetrics()
    d.text((MARGIN_X, y - ascent), title, font=title_font, fill=(255, 255, 255, 255))
    top = y - ascent

    if kicker:
        ky = top - KICKER_SIZE - 20
        _tracked(d, (MARGIN_X, ky), kicker.upper(), kicker_font,
                 (255, 255, 255, 190), KICKER_TRACKING)
        top = ky

    # Accent rule above the block.
    rule_y = top - 26
    d.rectangle([MARGIN_X, rule_y, MARGIN_X + RULE_W, rule_y + RULE_H], fill=_hex(accent))

    # Pure-black copy of the type, blurred, sitting under it for separation.
    shadow_alpha = (text.split()[3]
                    .filter(ImageFilter.GaussianBlur(9))
                    .point(lambda v: int(v * 0.8)))
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)

    card = Image.alpha_composite(card, shadow)
    card = Image.alpha_composite(card, text)

    out_path = out_path or Path("title.png")
    card.save(out_path, "PNG")
    return out_path

"""The YouTube thumbnail: 1280×720, one picture, four or five words.

A thumbnail is not a small version of the video. It is read at 120px wide in a
sidebar, on a phone, next to eleven others, so everything here is built for that
size: three lines at most, type fitted to fill its box rather than set at a fixed
size, and a picture that is always knocked back where words sit on top of it.

Same shape as `intro.py`: a TEMPLATES registry the UI reads, one renderer per
style, and a dispatcher. Rendering is pure Pillow and takes about a fifth of a
second, so the client re-renders as you type rather than on a button.
"""
from __future__ import annotations

import math

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from . import motifs, themes, titles
from .schema import Project, Thumb

W, H = 1280, 720

# ------------------------------------------------------------------ templates
# `flip` says the style has sides worth swapping; `light` marks the one that
# runs on paper, so the UI can say so before the accent is printed on cream.
TEMPLATES = [
    {"key": "banner", "label": "Banner", "flip": False, "light": False,
     "blurb": "Full-bleed picture, heavy scrim, headline across the foot. "
              "The safe one — works with almost any photograph."},
    {"key": "split", "label": "Split", "flip": True, "light": False,
     "blurb": "Picture down one side, type on a solid panel down the other, an "
              "accent rule at the seam. The most legible at sidebar size."},
    {"key": "spotlight", "label": "Spotlight", "flip": False, "light": False,
     "blurb": "The frame goes grey and dark except a pool of light on the "
              "subject; the headline lands top-left with a hard accent shadow."},
    {"key": "medallion", "label": "Medallion", "flip": True, "light": False,
     "blurb": "The subject in a ringed circle over a blurred bed of their own "
              "photograph, type stacked beside it. For faces."},
    {"key": "diagonal", "label": "Diagonal", "flip": True, "light": False,
     "blurb": "The picture cut on a slant with an accent slash, type on the "
              "flat side. The loudest of them."},
    {"key": "loupe", "label": "Loupe", "flip": False, "light": False,
     "blurb": "The picture seen through a watchmaker's loupe — magnified and "
              "sharp inside the glass, the bench greyed and soft outside it. "
              "For watches, and anything small enough to need looking at."},
    {"key": "poster", "label": "Poster", "flip": False, "light": True,
     "blurb": "A cream card: the picture plated inside a rule, serif headline "
              "beneath. For books, essays and anything quiet."},
    # Theme-led. These take their second colour, their ground and their icons
    # from the channel's theme rather than painting on one accent over a photo.
    {"key": "sticker", "label": "Sticker", "flip": True, "light": False, "themed": True,
     "blurb": "Outlined type slapped over a field of the theme's icons, the "
              "subject vignetted in beside it. The loudest of them."},
    {"key": "duotone", "label": "Duotone", "flip": False, "light": False, "themed": True,
     "blurb": "The picture flattened into the two theme colours with a band of "
              "type across the foot. Makes any photograph look like the channel."},
    {"key": "gloss", "label": "Gloss", "flip": True, "light": True, "themed": True,
     "blurb": "Soft light, the subject in a ring, sparkles and a serif "
              "headline. For beauty and fashion."},
    {"key": "scoreline", "label": "Scoreline", "flip": False, "light": False, "themed": True,
     "blurb": "A slanted band cut across the picture carrying condensed caps. "
              "For sport and anything competitive."},
    {"key": "tiles", "label": "Tiles", "flip": True, "light": False, "themed": True,
     "blurb": "A panel of icon tiles beside the picture with the headline "
              "plated over them. For food, craft and making."},
]
TEMPLATE_KEYS = [t["key"] for t in TEMPLATES]


def template_meta(key: str) -> dict:
    for t in TEMPLATES:
        if t["key"] == key:
            return t
    return TEMPLATES[0]


# -------------------------------------------------------------------- helpers
def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


class _Source:
    """The chosen photograph, croppable to whatever shape a style wants.

    Each style asks for its own aspect rather than carving up one 16:9 crop, so
    the circle in Medallion and the strip in Poster both keep the subject.
    """

    def __init__(self, path: Path | None, focal: list[float], accent) -> None:
        self.img = Image.open(path).convert("RGB") if path else None
        if self.img is not None:
            self.img = ImageEnhance.Color(self.img).enhance(1.06)
        self.focal = focal if len(focal or []) == 2 else None
        self.accent = accent

    @property
    def ok(self) -> bool:
        return self.img is not None

    def fill(self, w: int, h: int) -> Image.Image:
        if self.img is None:
            return self._placeholder(w, h)
        img = self.img
        scale = max(w / img.width, h / img.height)
        img = img.resize((max(w, round(img.width * scale)),
                          max(h, round(img.height * scale))), Image.LANCZOS)
        if self.focal:
            fx, fy = _clamp(self.focal[0], 0, 1), _clamp(self.focal[1], 0, 1)
        else:
            fx, fy = 0.5, 0.38      # faces sit above centre in most photographs
        left = round(_clamp(fx * img.width - w / 2, 0, img.width - w))
        top = round(_clamp(fy * img.height - h / 2, 0, img.height - h))
        return img.crop((left, top, left + w, top + h))

    def _placeholder(self, w: int, h: int) -> Image.Image:
        """What you get before a picture is picked: a hatched graphite field."""
        bed = Image.new("RGB", (w, h), (19, 20, 25))
        d = ImageDraw.Draw(bed)
        for x in range(-h, w, 54):
            d.line([(x, h), (x + h, 0)], fill=(25, 26, 32), width=13)
        return bed


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> list[str]:
    """Greedy word wrap. A word wider than the measure gets its own line."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        probe = f"{line} {word}".strip()
        if line and draw.textlength(probe, font=font) > max_w:
            lines.append(line)
            line = word
        else:
            line = probe
    if line:
        lines.append(line)
    return lines


def _fit_wrap(text: str, stack: list, box_w: int, box_h: int, max_lines: int = 3,
              cap: int = 150, floor: int = 28, leading: float = 1.02):
    """Largest size at which `text` wraps into the box within `max_lines`.

    Fitting rather than fixing is the whole trick: a three-word headline is set
    enormous, a nine-word one steps down, and neither ever overruns its panel.
    """
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    size = cap
    while size > floor:
        font = titles._load(stack, size)
        lines = _wrap(probe, text, font, box_w)
        if len(lines) <= max_lines:
            widest = max((probe.textlength(l, font=font) for l in lines), default=0)
            asc, desc = font.getmetrics()
            block = int(size * leading) * (len(lines) - 1) + asc + desc
            if widest <= box_w and block <= box_h:
                return font, lines, size
        size -= 3
    font = titles._load(stack, floor)
    return font, _wrap(probe, text, font, box_w)[:max_lines], floor


def _draw_block(d: ImageDraw.ImageDraw, lines: list[str], font, x: float, y: float,
                leading: int, fill, align: str = "left", shadow=None,
                offset: tuple[int, int] = (5, 6)) -> float:
    """Draw wrapped lines, optionally over a hard offset shadow."""
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=font)
        lx = x if align == "left" else (x - lw / 2 if align == "center" else x - lw)
        ly = y + i * leading
        if shadow:
            d.text((lx + offset[0], ly + offset[1]), line, font=font, fill=shadow)
        d.text((lx, ly), line, font=font, fill=fill)
    return y + (len(lines) - 1) * leading + font.getmetrics()[0]


def _tracked_width(d: ImageDraw.ImageDraw, text: str, font, tracking: float) -> float:
    if not text:
        return 0.0
    return sum(d.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)


def _scrim(height: int, strength: float) -> Image.Image:
    """A soft black gradient rising from the foot, for holding type over a photo."""
    col = Image.new("L", (1, height))
    col.putdata([int(255 * _clamp(strength, 0, 1) * ((y / max(1, height - 1)) ** 1.6))
                 for y in range(height)])
    band = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    band.putalpha(col.resize((W, height), Image.BILINEAR))
    return band


def _side_scrim(width: int, strength: float) -> Image.Image:
    """A black gradient falling away from the left edge, for type on a bright sky."""
    row = Image.new("L", (width, 1))
    row.putdata([int(255 * _clamp(strength, 0, 1) * ((1 - x / max(1, width - 1)) ** 1.5))
                 for x in range(width)])
    band = Image.new("RGBA", (width, H), (0, 0, 0, 0))
    band.putalpha(row.resize((width, H), Image.BILINEAR))
    return band


def _over(out: Image.Image, layer: Image.Image) -> None:
    """Composite an RGBA layer onto the frame in place."""
    out.paste(Image.alpha_composite(out.convert("RGBA"), layer).convert("RGB"), (0, 0))


def _text_of(project: Project) -> tuple[str, str]:
    """The headline and kicker actually drawn, with sensible fallbacks."""
    t = project.thumb
    headline = (t.headline or project.title or project.idea or "Untitled").strip()
    if t.uppercase:
        headline = headline.upper()
    return headline, (t.kicker or "").strip().upper()


def _accent(project: Project) -> tuple[int, int, int, int]:
    return titles._hex(project.thumb.accent or project.style.accent)


# --------------------------------------------------------------------- styles
def _render_banner(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """Full-bleed picture, scrim up from the foot, headline across the bottom."""
    t = p.thumb
    out.paste(src.fill(W, H), (0, 0))
    scrim = _scrim(int(H * 0.74), 0.4 + t.dim * 0.72)
    out.paste(Image.new("RGB", scrim.size, (0, 0, 0)), (0, H - scrim.height), scrim)

    headline, kicker = _text_of(p)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    MARGIN = 62
    font, lines, size = _fit_wrap(headline, titles.DISPLAY_STACK, W - MARGIN * 2, 340,
                                  max_lines=3, cap=int(128 * t.text_scale))
    leading = int(size * 1.0)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    top = H - 54 - block_h
    _draw_block(d, lines, font, MARGIN, top, leading, (255, 255, 255, 255))

    d.rectangle([MARGIN, top - 42, MARGIN + 150, top - 30], fill=accent)
    if kicker:
        kf = titles._load(titles.KICKER_STACK, 30)
        titles._tracked(d, (MARGIN + 176, top - 48), kicker, kf,
                        (255, 255, 255, 225), 4.4)
    _over(out, layer)


def _render_split(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """Picture one side, a solid panel of type the other."""
    t = p.thumb
    PANEL = 700
    pic_w = W - PANEL
    px = PANEL if not t.flip else 0
    tx = 0 if not t.flip else W - PANEL

    out.paste(Image.new("RGB", (W, H), (13, 14, 18)), (0, 0))
    out.paste(src.fill(pic_w, H), (px, 0))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # The panel is not a flat fill: a wash across it keeps it from reading as a
    # hole punched in the picture.
    steps = PANEL // 8
    for i in range(steps):
        a = int(30 * (1 - i / steps)) if not t.flip else int(30 * (i / steps))
        d.rectangle([tx + i * 8, 0, tx + i * 8 + 8, H], fill=(255, 255, 255, a))
    seam = px - 4 if not t.flip else px + pic_w - 4
    d.rectangle([seam, 0, seam + 8, H], fill=accent)

    headline, kicker = _text_of(p)
    MARGIN = 58
    box = PANEL - MARGIN * 2
    font, lines, size = _fit_wrap(headline, titles.CONDENSED_STACK, box, 430,
                                  max_lines=4, cap=int(112 * t.text_scale))
    leading = int(size * 1.02)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    kick_h = 66 if kicker else 0
    top = (H - block_h - kick_h) // 2 + kick_h

    if kicker:
        kf = titles._load(titles.KICKER_STACK, 28)
        d.rectangle([tx + MARGIN, top - 58, tx + MARGIN + 44, top - 46], fill=accent)
        titles._tracked(d, (tx + MARGIN + 62, top - 68), kicker, kf,
                        accent[:3] + (240,), 4.0)
    _draw_block(d, lines, font, tx + MARGIN, top, leading, (255, 255, 255, 255))
    d.rectangle([tx + MARGIN, top + block_h + 28, tx + MARGIN + 124,
                 top + block_h + 34], fill=accent)
    _over(out, layer)


def _render_spotlight(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """Everything grey and dark but a pool of light on the subject."""
    t = p.thumb
    base = src.fill(W, H)
    focal = t.focal if len(t.focal) == 2 else [0.62, 0.44]
    # The pool is lifted as well as the rest being dropped: a spotlight that
    # only darkens reads as a dirty lens rather than a light.
    lit = ImageEnhance.Brightness(ImageEnhance.Contrast(base).enhance(1.14)).enhance(1.12)
    dull = ImageEnhance.Color(lit).enhance(0.16)
    dull = ImageEnhance.Brightness(dull).enhance(_clamp(0.54 - t.dim * 0.42, 0.10, 0.66))

    # An ellipse blurred hard, centred on whatever the picture is actually about.
    mask = Image.new("L", (W // 4, H // 4), 0)
    cx, cy = focal[0] * W / 4, focal[1] * H / 4
    rx, ry = W / 4 * 0.30, H / 4 * 0.44
    ImageDraw.Draw(mask).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(17)).resize((W, H), Image.BILINEAR)
    out.paste(Image.composite(lit, dull, mask), (0, 0))
    # The pool can land anywhere, including behind the words. A scrim off the
    # left edge is what keeps the headline readable over a bright sky.
    side = _side_scrim(int(W * 0.66), 0.45 + t.dim * 0.4)
    out.paste(Image.new("RGB", side.size, (0, 0, 0)), (0, 0), side)

    headline, kicker = _text_of(p)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    MARGIN = 58
    font, lines, size = _fit_wrap(headline, titles.DISPLAY_STACK, int(W * 0.60), 420,
                                  max_lines=3, cap=int(134 * t.text_scale))
    leading = int(size * 0.98)
    top = MARGIN + (78 if kicker else 0)
    if kicker:
        kf = titles._load(titles.KICKER_STACK, 28)
        kw = _tracked_width(d, kicker, kf, 4.2)
        d.rounded_rectangle([MARGIN, MARGIN, MARGIN + kw + 42, MARGIN + 48],
                            radius=7, fill=accent)
        titles._tracked(d, (MARGIN + 21, MARGIN + 10), kicker, kf, (14, 13, 12, 255), 4.2)
    # White over an accent shadow: the offset is what makes it punch at 120px.
    _draw_block(d, lines, font, MARGIN, top, leading, (255, 255, 255, 255),
                shadow=accent[:3] + (255,),
                offset=(max(4, size // 22), max(5, size // 18)))
    _over(out, layer)


def _render_medallion(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """The subject in a ringed circle over a blurred bed of their own photograph."""
    t = p.thumb
    bed = src.fill(W, H).filter(ImageFilter.GaussianBlur(22))
    bed = ImageEnhance.Color(bed).enhance(0.65)
    out.paste(Image.blend(bed, Image.new("RGB", (W, H), (8, 9, 12)),
                          _clamp(0.28 + t.dim * 0.42, 0, 0.9)), (0, 0))

    D = 520
    cx = W - 320 if not t.flip else 320
    cy = H // 2
    disc = src.fill(D, D)
    mask = Image.new("L", (D * 2, D * 2), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, D * 2 - 1, D * 2 - 1], fill=255)
    mask = mask.resize((D, D), Image.LANCZOS)

    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse([cx - D / 2 - 16, cy - D / 2 - 10,
                                   cx + D / 2 + 16, cy + D / 2 + 22], fill=(0, 0, 0, 165))
    _over(out, shade.filter(ImageFilter.GaussianBlur(18)))
    out.paste(disc, (cx - D // 2, cy - D // 2), mask)

    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([cx - D / 2 - 8, cy - D / 2 - 8,
                                  cx + D / 2 + 8, cy + D / 2 + 8],
                                 outline=accent, width=10)
    _over(out, ring)

    headline, kicker = _text_of(p)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    MARGIN = 62
    box = W - D - 210
    tx = MARGIN if not t.flip else W - MARGIN - box
    font, lines, size = _fit_wrap(headline, titles.FONT_STACK, box, 430,
                                  max_lines=4, cap=int(104 * t.text_scale))
    leading = int(size * 1.06)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    top = (H - block_h) // 2
    if kicker:
        kf = titles._load(titles.KICKER_STACK, 27)
        titles._tracked(d, (tx, top - 58), kicker, kf, accent[:3] + (240,), 4.2)
    _draw_block(d, lines, font, tx, top, leading, (255, 255, 255, 255),
                shadow=(0, 0, 0, 190), offset=(3, 4))
    d.rectangle([tx, top + block_h + 30, tx + 110, top + block_h + 36], fill=accent)
    _over(out, layer)


def _render_diagonal(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """The picture cut on a slant, an accent slash along the cut."""
    t = p.thumb
    out.paste(Image.new("RGB", (W, H), (12, 13, 17)), (0, 0))

    TOP_X, BOT_X = 560, 830        # where the cut meets the top and bottom edges
    pic = src.fill(W - min(TOP_X, BOT_X) + 60, H)
    poly = [(TOP_X, 0), (W, 0), (W, H), (BOT_X, H)]
    px = min(TOP_X, BOT_X) - 60
    if t.flip:
        poly = [(W - x, y) for x, y in poly]
        pic = pic.transpose(Image.FLIP_LEFT_RIGHT)
        px = 0
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    bed = Image.new("RGB", (W, H), (12, 13, 17))
    bed.paste(pic, (px, 0))
    out.paste(bed, (0, 0), mask)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    slash = [(TOP_X - 34, 0), (TOP_X + 6, 0), (BOT_X + 6, H), (BOT_X - 34, H)]
    if t.flip:
        slash = [(W - x, y) for x, y in slash]
    d.polygon(slash, fill=accent)

    headline, kicker = _text_of(p)
    MARGIN = 56
    box = min(TOP_X, BOT_X) - 34 - MARGIN * 2 + 60
    tx = MARGIN if not t.flip else W - MARGIN - box
    font, lines, size = _fit_wrap(headline, titles.DISPLAY_STACK, box, 440,
                                  max_lines=4, cap=int(118 * t.text_scale))
    leading = int(size * 0.98)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    kick_h = 66 if kicker else 0
    top = (H - block_h - kick_h) // 2 + kick_h
    if kicker:
        kf = titles._load(titles.KICKER_STACK, 28)
        titles._tracked(d, (tx, top - 66), kicker, kf, accent[:3] + (245,), 4.2)
    _draw_block(d, lines, font, tx, top, leading, (255, 255, 255, 255))
    _over(out, layer)


def _render_poster(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """A cream card: the picture plated inside a rule, serif headline beneath."""
    t = p.thumb
    ink = (30, 27, 24)
    rule = tuple(int(c * 0.55) for c in accent[:3])

    # Cream stock with a printed tooth, so the card isn't a flat fill.
    paper = Image.new("RGB", (W, H), (238, 233, 222))
    noise = Image.effect_noise((W // 2, H // 2), 15).resize((W, H), Image.BILINEAR)
    tex = noise.point(lambda v: max(0, v - 118) // 7)
    out.paste(ImageChops.subtract(paper, Image.merge("RGB", (tex, tex, tex))), (0, 0))

    PLATE_W, PLATE_H, PLATE_Y = 1156, 336, 44
    plate = src.fill(PLATE_W, PLATE_H)
    out.paste(plate, ((W - PLATE_W) // 2, PLATE_Y))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([(W - PLATE_W) // 2 - 3, PLATE_Y - 3,
                 (W + PLATE_W) // 2 + 2, PLATE_Y + PLATE_H + 2],
                outline=ink + (70,), width=3)

    headline, kicker = _text_of(p)
    body_top = PLATE_Y + PLATE_H + 30
    if kicker:
        kf = titles._load(titles.SMALLCAPS_STACK, 30)
        kw = _tracked_width(d, kicker, kf, 5.0)
        titles._tracked(d, ((W - kw) / 2, body_top), kicker, kf, ink + (205,), 5.0)
        body_top += 46
    font, lines, size = _fit_wrap(headline, titles.SERIF_STACK, W - 220,
                                  H - body_top - 62, max_lines=2,
                                  cap=int(94 * t.text_scale))
    leading = int(size * 1.02)
    _draw_block(d, lines, font, W // 2, body_top, leading, ink + (255,), align="center")

    d.rectangle([W / 2 - 152, H - 36, W / 2 - 26, H - 33], fill=rule + (230,))
    d.rectangle([W / 2 + 26, H - 36, W / 2 + 152, H - 33], fill=rule + (230,))
    d.polygon([(W / 2, H - 44), (W / 2 + 10, H - 34), (W / 2, H - 24),
               (W / 2 - 10, H - 34)], fill=rule + (230,))
    _over(out, layer)


# ============================================================================
# The theme-led styles. These read the channel's theme for a second colour, a
# ground and a set of icons, so the same style dresses a gaming channel and a
# food channel quite differently. Everything above runs on one accent over a
# photograph; everything below is allowed to be loud.
# ============================================================================
def _disc_mask(cx: float, cy: float, d: int) -> Image.Image:
    """A frame-sized mask with one soft-edged circle in it."""
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse([cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2], fill=255)
    return m


def _render_loupe(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """The picture seen through a watchmaker's loupe, type beside it.

    A loupe is the one object that says horology before the picture inside it
    has been read, and it earns its place mechanically as well: the lens crops
    any photograph to a circle and magnifies it, so a thumbnail that would be
    unreadable at sidebar width still has one sharp, bright, obvious subject.

    Everything outside the glass is knocked back, greyed and thrown slightly out
    of focus, which is what a real loupe does to the rest of the bench.
    """
    t = p.thumb
    # The bench: the same photograph, dimmed and softened.
    bed = src.fill(W, H).filter(ImageFilter.GaussianBlur(9))
    bed = ImageEnhance.Color(bed).enhance(0.22)
    out.paste(Image.blend(bed, Image.new("RGB", (W, H), (7, 8, 11)),
                          _clamp(0.50 + t.dim * 0.42, 0, 0.94)), (0, 0))

    D = 470                                   # the glass
    cx = W - 322 if not t.flip else 322
    cy = H // 2 - 6

    # What the lens shows: the same frame, magnified about the focal point and
    # left sharp and full-colour, because that contrast is the whole effect.
    mag = src.fill(int(W * 1.55), int(H * 1.55))
    lx = int(mag.width * (src.focal[0] if src.focal else 0.5) - D / 2)
    ly = int(mag.height * (src.focal[1] if src.focal else 0.45) - D / 2)
    lx = max(0, min(mag.width - D, lx))
    ly = max(0, min(mag.height - D, ly))
    glass = ImageEnhance.Brightness(mag.crop((lx, ly, lx + D, ly + D))).enhance(1.14)
    glass = ImageEnhance.Color(glass).enhance(1.12)

    mask = Image.new("L", (D * 2, D * 2), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, D * 2 - 1, D * 2 - 1], fill=255)
    mask = mask.resize((D, D), Image.LANCZOS)

    # The barrel throws a shadow onto the bench.
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse([cx - D / 2 - 26, cy - D / 2 - 16,
                                   cx + D / 2 + 26, cy + D / 2 + 38],
                                  fill=(0, 0, 0, 185))
    _over(out, shade.filter(ImageFilter.GaussianBlur(26)))
    out.paste(glass, (cx - D // 2, cy - D // 2), mask)

    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    # Knurling: the milled grip round a loupe barrel, cut as radial teeth.
    r_in, r_out = D / 2 + 10, D / 2 + 34
    # Coarse teeth on purpose. A thumbnail is read at 120px wide, where fine
    # knurling aliases into a grey band and the barrel stops reading as metal.
    for i in range(44):
        a = math.radians(i * 360 / 44)
        ux, uy = math.cos(a), math.sin(a)
        shade_k = 0.52 + 0.48 * abs(math.cos(a - math.radians(215)))
        col = tuple(int(c * shade_k) for c in accent[:3])
        rd.line([cx + ux * r_in, cy + uy * r_in, cx + ux * r_out, cy + uy * r_out],
                fill=col + (255,), width=13)
    rd.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], outline=accent, width=7)
    rd.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out],
               outline=tuple(int(c * 0.6) for c in accent[:3]) + (255,), width=4)
    _over(out, ring)

    # One curved highlight on the glass, top-left, where the light is.
    gleam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gleam)
    gd.arc([cx - D / 2 + 16, cy - D / 2 + 16, cx + D / 2 - 16, cy + D / 2 - 16],
           start=178, end=262, fill=(255, 255, 255, 205), width=22)
    gleam = gleam.filter(ImageFilter.GaussianBlur(11))
    # Clipped to the glass, or the highlight sits on top of the barrel.
    gleam.putalpha(ImageChops.multiply(gleam.getchannel("A"),
                                       _disc_mask(cx, cy, D)))
    _over(out, gleam)

    headline, kicker = _text_of(p)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    MARGIN = 64
    box = W - D - 250
    tx = MARGIN if not t.flip else W - MARGIN - box
    font, lines, size = _fit_wrap(headline, titles.FONT_STACK, box, 440,
                                  max_lines=4, cap=int(112 * t.text_scale))
    leading = int(size * 1.04)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    top = (H - block_h) // 2
    if kicker:
        kf = titles._load(titles.KICKER_STACK, 28)
        titles._tracked(d, (tx, top - 60), kicker, kf, accent[:3] + (245,), 4.4)
    _draw_block(d, lines, font, tx, top, leading, (255, 255, 255, 255),
                shadow=(0, 0, 0, 200), offset=(3, 4))
    d.rectangle([tx, top + block_h + 32, tx + 124, top + block_h + 39], fill=accent)
    _over(out, layer)


def _palette(p: Project):
    """The theme's palette, with the thumbnail's own accent override applied."""
    pal = themes.palette(p.style)
    if (p.thumb.accent or "").strip():
        pal.accent = titles._hex(p.thumb.accent)
    return pal


def _cutout(src: _Source, w: int, h: int, flip: bool = False) -> Image.Image:
    """The subject, blended off its background as far as a thumbnail needs.

    There is no segmentation model here and there does not need to be one. What
    matters is that the picture's inner edge dissolves into the pattern instead
    of ending on a straight line, which is the thing that reads as a pasted-in
    rectangle at sidebar size. So the inner third is a ramp and the corners are
    eased off with an ellipse.
    """
    img = src.fill(w, h)
    ramp = Image.new("L", (w, 1))
    fade = int(w * 0.42)
    ramp.putdata([int(255 * min(1.0, (x / fade) ** 1.3)) if x < fade else 255
                  for x in range(w)])
    mask = ramp.resize((w, h), Image.BILINEAR)
    if flip:
        mask = mask.transpose(Image.FLIP_LEFT_RIGHT)
    soft = Image.new("L", (w, h), 0)
    ImageDraw.Draw(soft).ellipse([-w * 0.30, -h * 0.16, w * 1.30, h * 1.16], fill=255)
    mask = ImageChops.multiply(mask, soft.filter(ImageFilter.GaussianBlur(w * 0.05)))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img, (0, 0))
    out.putalpha(mask)
    return out


def _render_sticker(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """Outlined type slapped over a field of the theme's icons. The loud one."""
    t = p.thumb
    pal = _palette(p)
    ground = motifs.gradient((W, H), [motifs.shade(pal.ground, 1.5), pal.ground,
                                      motifs.mix(pal.ground, pal.accent, 0.2)], 120)
    field = motifs.icon_field((W, H), pal.icons, [pal.accent, pal.accent2, pal.ink],
                              cell=92, alpha=54, angle=-14)
    out.paste(Image.alpha_composite(ground.convert("RGBA"), field).convert("RGB"), (0, 0))

    if src.ok:
        cut = _cutout(src, int(W * 0.58), H, t.flip)
        out.paste(cut, (W - cut.width if not t.flip else 0, 0), cut)

    headline, kicker = _text_of(p)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box_w = int(W * (0.52 if src.ok else 0.86))
    x = 56 if not t.flip else W - box_w - 56
    font, lines, size = _fit_wrap(headline, titles.DISPLAY_STACK, box_w, 430,
                                  max_lines=3, cap=int(132 * t.text_scale))
    leading = int(size * 1.0)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    top = (H - block_h) // 2 + (34 if kicker else 0)

    # Drawn once into its own layer so the outline can be grown off its alpha —
    # a per-letter stroke would thicken every counter and close up the small ones.
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _draw_block(ImageDraw.Draw(text_layer), lines, font, x, top, leading, pal.ink)
    alpha = text_layer.split()[3]
    for grow, color in ((16, motifs.shade(pal.ground, 0.35)), (9, pal.accent2)):
        ring = Image.new("RGBA", (W, H), tuple(color[:3]) + (0,))
        ring.putalpha(alpha.filter(ImageFilter.MaxFilter(grow * 2 + 1)))
        layer = Image.alpha_composite(layer, ring)
    layer = Image.alpha_composite(layer, text_layer)

    d = ImageDraw.Draw(layer)
    if kicker:
        kf = titles._load(titles.DISPLAY_STACK, 40)
        kw = _tracked_width(d, kicker, kf, 3.0)
        d.rounded_rectangle([x - 6, top - 84, x + kw + 34, top - 22], 14, fill=pal.accent)
        titles._tracked(d, (x + 14, top - 76), kicker, kf,
                        motifs.readable_on(pal.accent), 3.0)
    _over(out, layer)


def _render_duotone(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """The picture flattened into the two theme colours, type straight over it.

    A duotone is the cheapest way to make any photograph — an archive scan, a
    press shot, a frame grab — look like it belongs to one channel, because
    every one of them comes out in the same two colours.
    """
    t = p.thumb
    pal = _palette(p)
    grey = src.fill(W, H).convert("L")
    grey = ImageEnhance.Contrast(grey).enhance(1.25)
    # Map black to the darker colour and white to the lighter one.
    dark, light = pal.accent2, pal.accent
    if sum(dark[:3]) > sum(light[:3]):
        dark, light = light, dark
    dark = motifs.mix(pal.ground, dark, 0.72)
    duo = ImageOps.colorize(grey, tuple(dark[:3]), tuple(motifs.shade(light, 1.15)[:3]),
                            blackpoint=10, whitepoint=245)
    out.paste(duo, (0, 0))

    headline, kicker = _text_of(p)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # A band the width of the frame, so the type never has to fight the picture.
    band_top = int(H * 0.58)
    d = ImageDraw.Draw(layer)
    d.rectangle([0, band_top, W, H], fill=motifs.shade(pal.ground, 1.1)[:3] +
                (int(170 + 78 * t.dim),))
    d.rectangle([0, band_top - 8, W, band_top], fill=pal.accent)

    font, lines, size = _fit_wrap(headline, titles.DISPLAY_STACK, W - 116,
                                  H - band_top - 58, max_lines=2,
                                  cap=int(132 * t.text_scale))
    leading = int(size * 0.98)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    top = band_top + (H - band_top - block_h) // 2 + 4
    _draw_block(d, lines, font, 58, top, leading, (255, 255, 255, 255))

    if kicker:
        kf = titles._load(titles.KICKER_STACK, 34)
        kw = _tracked_width(d, kicker, kf, 5.0)
        d.rectangle([58, 46, 58 + kw + 52, 108], fill=pal.accent)
        titles._tracked(d, (84, 60), kicker, kf, motifs.readable_on(pal.accent), 5.0)
    _over(out, layer)


def _render_gloss(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """Soft light, the subject in a ring, and a serif headline beside it."""
    t = p.thumb
    pal = _palette(p)
    light = pal.light
    base = motifs.radial((W, H), motifs.shade(pal.ground, 1.05 if light else 1.9),
                         motifs.mix(pal.ground, pal.accent, 0.4),
                         centre=(0.68 if not t.flip else 0.32, 0.42), radius=1.0)
    base = Image.alpha_composite(base.convert("RGBA"), motifs.icon_field(
        (W, H), pal.icons, [pal.accent, pal.accent2], cell=76, alpha=52, angle=8))
    out.paste(base.convert("RGB"), (0, 0))

    ink = pal.ink if light else (255, 255, 255, 255)
    ring_d = 500
    cx = W - 300 if not t.flip else 300
    cy = H // 2
    if src.ok:
        shot = src.fill(ring_d, ring_d)
        mask = Image.new("L", (ring_d, ring_d), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, ring_d - 1, ring_d - 1], fill=255)
        out.paste(shot, (cx - ring_d // 2, cy - ring_d // 2), mask)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - ring_d // 2 - 12, cy - ring_d // 2 - 12,
               cx + ring_d // 2 + 12, cy + ring_d // 2 + 12],
              outline=pal.accent, width=7)
    for gx, gy, gs in ((cx - 268, cy - 214, 74), (cx + 218, cy + 176, 58),
                       (cx + 236, cy - 168, 42), (cx - 226, cy + 214, 36)):
        g = motifs.icon("sparkle", gs, (255, 255, 255, 235) if not light
                        else motifs.shade(pal.accent, 1.5))
        layer.paste(g, (gx, gy), g)

    headline, kicker = _text_of(p)
    box_w = W - ring_d - 190
    x = 66 if not t.flip else W - box_w - 66
    font, lines, size = _fit_wrap(headline, titles.SERIF_STACK, box_w, 420,
                                  max_lines=3, cap=int(118 * t.text_scale))
    leading = int(size * 1.06)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    top = (H - block_h) // 2 + (30 if kicker else 0)
    if kicker:
        kf = titles._load(titles.SMALLCAPS_STACK, 32)
        titles._tracked(d, (x, top - 76), kicker, kf, pal.accent, 6.0)
    _draw_block(d, lines, font, x, top, leading, ink)
    d.rectangle([x, top + block_h + 30, x + 150, top + block_h + 34], fill=pal.accent)
    _over(out, layer)


def _render_scoreline(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """A slanted band across the picture, condensed caps on it, a number beside."""
    t = p.thumb
    pal = _palette(p)
    out.paste(src.fill(W, H), (0, 0))
    dim = Image.new("RGBA", (W, H), motifs.shade(pal.ground, 0.7)[:3] +
                    (int(70 + 130 * t.dim),))
    _over(out, dim)

    TILT = -8.0
    headline, kicker = _text_of(p)
    font, lines, size = _fit_wrap(headline, titles.CONDENSED_STACK, W - 300, 330,
                                  max_lines=2, cap=int(140 * t.text_scale))
    leading = int(size * 0.94)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    band_h = block_h + 118

    big = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    bd = ImageDraw.Draw(big)
    cy = H
    top_e, bot_e = cy - band_h / 2, cy + band_h / 2
    bd.rectangle([0, top_e, W * 2, bot_e], fill=motifs.shade(pal.ground, 0.8)[:3] + (243,))
    bd.rectangle([0, top_e - 9, W * 2, top_e], fill=pal.accent)
    bd.rectangle([0, bot_e, W * 2, bot_e + 9], fill=pal.accent)
    _draw_block(bd, lines, font, W - (W - 300) / 2 + 40, cy - block_h / 2 - 4,
                leading, (255, 255, 255, 255))
    if kicker:
        kf = titles._load(titles.DISPLAY_STACK, 42)
        kw = _tracked_width(bd, kicker, kf, 3.0)
        bd.rectangle([W - (W - 300) / 2 + 40, top_e - 74,
                      W - (W - 300) / 2 + 40 + kw + 44, top_e - 12], fill=pal.accent)
        titles._tracked(bd, (W - (W - 300) / 2 + 62, top_e - 66), kicker, kf,
                        motifs.readable_on(pal.accent), 3.0)
    band = big.rotate(TILT, Image.BICUBIC).crop((W // 2, H // 2, W // 2 + W, H // 2 + H))
    _over(out, band)


def _render_tiles(p: Project, src: _Source, out: Image.Image, accent) -> None:
    """A panel of icon tiles beside the picture, type plated on top of them."""
    t = p.thumb
    pal = _palette(p)
    PANEL = 720
    px = PANEL if not t.flip else 0
    tx = 0 if not t.flip else W - PANEL

    out.paste(Image.new("RGB", (W, H), pal.ground[:3]), (0, 0))
    out.paste(src.fill(W - PANEL, H), (px, 0))

    cell = PANEL // 4
    panel = Image.new("RGBA", (PANEL, H), pal.ground)
    for r in range((H // cell) + 1):
        for c in range(4):
            col = motifs.mix(pal.ground, pal.accent if (r + c) % 2 else pal.accent2,
                             0.15 + ((r + c) % 3) * 0.05)
            ImageDraw.Draw(panel).rectangle([c * cell, r * cell, (c + 1) * cell - 3,
                                             (r + 1) * cell - 3], fill=col)
            key = pal.icons[(r * 3 + c) % len(pal.icons)]
            g = motifs.icon(key, int(cell * 0.4),
                            (pal.accent if (r + c) % 2 else pal.accent2)[:3] + (135,))
            panel.paste(g, (c * cell + (cell - g.width) // 2,
                            r * cell + (cell - g.height) // 2), g)
    out.paste(panel, (tx, 0), panel)

    headline, kicker = _text_of(p)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    MARGIN = 42
    box = PANEL - MARGIN * 2 - 44
    font, lines, size = _fit_wrap(headline, titles.DISPLAY_STACK, box, 400,
                                  max_lines=3, cap=int(112 * t.text_scale))
    leading = int(size * 1.0)
    block_h = leading * (len(lines) - 1) + font.getmetrics()[0]
    plate_h = block_h + (128 if kicker else 76)
    plate_y = (H - plate_h) // 2
    face = (255, 253, 248, 250) if pal.light else motifs.shade(pal.ground, 1.7)[:3] + (250,)
    d.rounded_rectangle([tx + MARGIN, plate_y, tx + PANEL - MARGIN, plate_y + plate_h],
                        10, fill=face, outline=pal.accent, width=5)
    top = plate_y + (plate_h - block_h) // 2 + (26 if kicker else 0)
    if kicker:
        kf = titles._load(titles.KICKER_STACK, 30)
        kw = _tracked_width(d, kicker, kf, 5.0)
        titles._tracked(d, (tx + PANEL / 2 - kw / 2, top - 62), kicker, kf,
                        pal.accent, 5.0)
    _draw_block(d, lines, font, tx + PANEL / 2, top, leading,
                pal.ink if pal.light else (255, 255, 255, 255), align="center")
    _over(out, layer)


_RENDERERS = {
    "banner": _render_banner,
    "loupe": _render_loupe,
    "split": _render_split,
    "spotlight": _render_spotlight,
    "medallion": _render_medallion,
    "diagonal": _render_diagonal,
    "poster": _render_poster,
    "sticker": _render_sticker,
    "duotone": _render_duotone,
    "gloss": _render_gloss,
    "scoreline": _render_scoreline,
    "tiles": _render_tiles,
}


# --------------------------------------------------------------------- render
def render_thumb(project: Project, root: Path, out_path: Path) -> Path:
    """Draw the thumbnail to a jpeg. Returns the path written."""
    t: Thumb = project.thumb
    accent = _accent(project)
    rel = (t.image or "").strip()
    path = root / rel if rel else None
    src = _Source(path if (path and path.exists()) else None, t.focal, accent)

    meta = template_meta(t.template)
    out = Image.new("RGB", (W, H), (238, 233, 222) if meta["light"] else (10, 11, 14))
    _RENDERERS.get(t.template, _render_banner)(project, src, out, accent)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # YouTube's ceiling is 2MB; quality 90 at 1280×720 lands around 250KB.
    out.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)
    return out_path


def suggest_headlines(project: Project, count: int = 6) -> list[dict]:
    """Ask Claude for thumbnail text: a few words, not the title again."""
    from .llm import MODEL_UTILITY, complete_json

    beats = [s.beat or s.title for s in project.slides[:8] if (s.beat or s.title)]
    prompt = f"""Write thumbnail text for a YouTube documentary video.

TITLE: {project.title or project.idea}
WHAT IT COVERS: {project.outline.get('thesis') or project.idea}
BEATS: {'; '.join(beats[:6]) or 'not available'}

Thumbnail text is read at 120 pixels wide, beside eleven other videos. It is not
the title again: it is the hook the title cannot carry. Two to five words, no
full sentences, no ending punctuation, and nothing that promises what the video
does not deliver. A kicker is an optional one or two word label above it.

Return JSON: a list of {count} objects:
{{"headline": "two to five words", "kicker": "one or two words, or empty"}}"""

    out = complete_json(prompt, model=MODEL_UTILITY, timeout=240)
    if isinstance(out, dict):
        out = out.get("options") or out.get("headlines") or []
    picks: list[dict] = []
    for item in out or []:
        if isinstance(item, str) and item.strip():
            picks.append({"headline": item.strip()[:60], "kicker": ""})
        elif isinstance(item, dict) and str(item.get("headline") or "").strip():
            picks.append({"headline": str(item["headline"]).strip()[:60],
                          "kicker": str(item.get("kicker") or "").strip()[:24]})
    return picks[:count]

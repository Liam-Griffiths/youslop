"""Icons, patterns and colour ramps — the parts the colourful templates share.

A slate, a thumbnail and an end screen for the same channel have to look like
each other, and three copies of "draw a field of little controllers" would drift
apart the first time one of them was improved. So the vocabulary lives here and
the three renderers borrow from it.

Two kinds of pattern earn their place. An **icon field** is a tiled, brick-offset
grid of small glyphs, rotated off-square and printed faintly — it gives a flat
colour something to be without competing with type. A **word field** does the
same with the channel's own name repeated in rows, which is the older trick and
the louder one: it reads as branding even at sidebar size, where an icon is four
pixels across and gone.

Everything here is Pillow primitives at a requested size, so a caller can draw a
26px glyph into a thumbnail and a 300px one into a slate from the same code.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Iterable

from PIL import Image, ImageDraw, ImageFilter

from . import titles

RGBA = tuple[int, int, int, int]


def _c(color, alpha: int | None = None) -> RGBA:
    """Accept a hex string or an rgba tuple, return rgba."""
    if isinstance(color, str):
        out = titles._hex(color)
    else:
        out = tuple(color) + (255,) * (4 - len(color))
    return out[:3] + (alpha if alpha is not None else out[3],)


def mix(a, b, k: float) -> RGBA:
    """Blend two colours. k=0 is all `a`."""
    ca, cb = _c(a), _c(b)
    return tuple(int(ca[i] + (cb[i] - ca[i]) * max(0.0, min(1.0, k))) for i in range(4))


def shade(color, k: float) -> RGBA:
    """Darken (k<1) or lighten (k>1) without leaving the hue behind."""
    c = _c(color)
    if k <= 1:
        return tuple(int(v * k) for v in c[:3]) + (c[3],)
    return tuple(int(v + (255 - v) * (k - 1)) for v in c[:3]) + (c[3],)


def readable_on(bg) -> RGBA:
    """Black or white, whichever survives on this ground."""
    r, g, b = _c(bg)[:3]
    # The line sits high on purpose. A bright green or cyan measures as a
    # mid-tone and takes white by a hair, which is exactly where white fails.
    return (17, 16, 20, 255) if (0.299 * r + 0.587 * g + 0.114 * b) > 170 else (255, 255, 255, 255)


# ------------------------------------------------------------------ gradients
def gradient(size: tuple[int, int], stops: list, angle: float = 90.0) -> Image.Image:
    """A linear gradient through any number of colours, at any angle.

    Built as a one-pixel-wide ramp, stretched and rotated, which costs one
    resize instead of a Python loop over two million pixels.
    """
    w, h = size
    stops = [_c(s) for s in stops] or [(0, 0, 0, 255)]
    if len(stops) == 1:
        return Image.new("RGB", size, stops[0][:3])

    n = 512
    ramp = Image.new("RGB", (1, n))
    px = ramp.load()
    span = n / (len(stops) - 1)
    for y in range(n):
        i = min(len(stops) - 2, int(y / span))
        k = (y - i * span) / span
        px[0, y] = tuple(int(stops[i][j] + (stops[i + 1][j] - stops[i][j]) * k)
                         for j in range(3))
    # Oversize before rotating so no corner of the frame falls off the ramp.
    diag = int(math.hypot(w, h)) + 4
    band = ramp.resize((diag, diag), Image.BILINEAR).rotate(angle - 90, Image.BILINEAR)
    return band.crop(((diag - w) // 2, (diag - h) // 2,
                      (diag - w) // 2 + w, (diag - h) // 2 + h))


def radial(size: tuple[int, int], inner, outer, centre: tuple[float, float] = (0.5, 0.4),
           radius: float = 0.8) -> Image.Image:
    """A soft glow behind everything. Drawn small and scaled up, so it is cheap."""
    w, h = size
    sw, sh = max(2, w // 10), max(2, h // 10)
    field = Image.new("RGB", (sw, sh), _c(outer)[:3])
    d = ImageDraw.Draw(field)
    cx, cy = centre[0] * sw, centre[1] * sh
    steps = 26
    for i in range(steps, 0, -1):
        k = i / steps
        r = radius * max(sw, sh) * k
        d.ellipse([cx - r, cy - r * 0.86, cx + r, cy + r * 0.86],
                  fill=mix(inner, outer, k ** 0.7)[:3])
    return field.filter(ImageFilter.GaussianBlur(3)).resize((w, h), Image.BILINEAR)


# ---------------------------------------------------------------------- icons
# Each glyph draws itself inside a unit box of `s` pixels, at (x, y). They are
# deliberately chunky: these are printed at 30px in a thumbnail pattern, where a
# thin stroke disappears into the jpeg.
def _rr(d, box, r, **kw):
    d.rounded_rectangle(box, r, **kw)


def _controller(d, x, y, s, c):
    d.rounded_rectangle([x, y + s * .26, x + s, y + s * .8], s * .24, fill=c)
    d.ellipse([x - s * .06, y + s * .34, x + s * .32, y + s * .86], fill=c)
    d.ellipse([x + s * .68, y + s * .34, x + s * 1.06, y + s * .86], fill=c)
    # Knocked-out sticks and pad, so it is a controller and not a lozenge.
    hole = (0, 0, 0, 0)
    d.ellipse([x + s * .12, y + s * .44, x + s * .34, y + s * .66], fill=hole)
    d.ellipse([x + s * .66, y + s * .44, x + s * .88, y + s * .66], fill=hole)
    d.rectangle([x + s * .46, y + s * .38, x + s * .54, y + s * .56], fill=hole)
    d.rectangle([x + s * .41, y + s * .43, x + s * .59, y + s * .51], fill=hole)


def _dpad(d, x, y, s, c):
    """A pad, not a plus: the cross is knocked out of a rounded tile."""
    d.rounded_rectangle([x, y, x + s, y + s], s * .18, fill=c)
    a = s * .26
    hole = (0, 0, 0, 0)
    d.rectangle([x + (s - a) / 2, y + s * .16, x + (s + a) / 2, y + s * .84], fill=hole)
    d.rectangle([x + s * .16, y + (s - a) / 2, x + s * .84, y + (s + a) / 2], fill=hole)


def _pixel_heart(d, x, y, s, c):
    u = s / 7
    for cx, cy, w in ((1, 1, 2), (4, 1, 2), (0, 2, 7), (1, 3, 5), (2, 4, 3), (3, 5, 1)):
        d.rectangle([x + cx * u, y + cy * u, x + (cx + w) * u, y + (cy + 1) * u], fill=c)


def _star4(d, x, y, s, c):
    cx, cy, r, w = x + s / 2, y + s / 2, s / 2, s * .16
    d.polygon([(cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w),
               (cx, cy + r), (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w)], fill=c)


def _star5(d, x, y, s, c):
    cx, cy, r = x + s / 2, y + s / 2, s / 2
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * .44
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=c)


def _sparkle(d, x, y, s, c):
    _star4(d, x + s * .12, y + s * .12, s * .76, c)
    _star4(d, x + s * .64, y - s * .02, s * .3, c)


def _lipstick(d, x, y, s, c):
    d.rounded_rectangle([x + s * .3, y + s * .42, x + s * .7, y + s], s * .08, fill=c)
    d.polygon([(x + s * .32, y + s * .42), (x + s * .68, y + s * .42),
               (x + s * .68, y + s * .1), (x + s * .5, y), (x + s * .32, y + s * .18)], fill=c)


def _droplet(d, x, y, s, c):
    d.ellipse([x + s * .16, y + s * .34, x + s * .84, y + s], fill=c)
    d.polygon([(x + s * .5, y), (x + s * .82, y + s * .58), (x + s * .18, y + s * .58)], fill=c)


def _brush(d, x, y, s, c):
    d.polygon([(x + s * .38, y), (x + s * .62, y), (x + s * .56, y + s * .5),
               (x + s * .44, y + s * .5)], fill=c)
    d.rounded_rectangle([x + s * .36, y + s * .5, x + s * .64, y + s], s * .12, fill=c)


def _compact(d, x, y, s, c):
    """A powder compact: two halves on a hinge, which is what makes it not a disc."""
    w = max(2, int(s * .12))
    d.ellipse([x, y, x + s, y + s], outline=c, width=w)
    d.line([(x + s * .04, y + s * .5), (x + s * .96, y + s * .5)], fill=c, width=w)
    d.rectangle([x + s * .38, y + s * .42, x + s * .62, y + s * .58], fill=c)


def _bow(d, x, y, s, c):
    d.polygon([(x, y + s * .2), (x + s * .44, y + s * .5), (x, y + s * .8)], fill=c)
    d.polygon([(x + s, y + s * .2), (x + s * .56, y + s * .5), (x + s, y + s * .8)], fill=c)
    d.ellipse([x + s * .4, y + s * .38, x + s * .6, y + s * .62], fill=c)


def _ball(d, x, y, s, c):
    cx, cy, r = x + s / 2, y + s / 2, s * .2
    d.ellipse([x, y, x + s, y + s], outline=c, width=max(2, int(s * .12)))
    d.regular_polygon((cx, cy, r), 5, rotation=180, fill=c)
    # Seams out to the rim, which is the half of a football people recognise.
    for i in range(5):
        a = -math.pi / 2 + i * 2 * math.pi / 5
        d.line([(cx + r * .9 * math.cos(a), cy + r * .9 * math.sin(a)),
                (cx + s * .46 * math.cos(a), cy + s * .46 * math.sin(a))],
               fill=c, width=max(2, int(s * .08)))


def _whistle(d, x, y, s, c):
    d.rounded_rectangle([x, y + s * .3, x + s * .72, y + s * .8], s * .16, fill=c)
    d.ellipse([x + s * .56, y + s * .18, x + s, y + s * .58], fill=c)
    d.ellipse([x + s * .18, y + s * .44, x + s * .38, y + s * .64], fill=(0, 0, 0, 0))


def _trophy(d, x, y, s, c):
    d.polygon([(x + s * .22, y + s * .08), (x + s * .78, y + s * .08),
               (x + s * .64, y + s * .58), (x + s * .36, y + s * .58)], fill=c)
    d.rectangle([x + s * .42, y + s * .58, x + s * .58, y + s * .8], fill=c)
    d.rounded_rectangle([x + s * .26, y + s * .8, x + s * .74, y + s], s * .06, fill=c)
    d.arc([x + s * .02, y + s * .1, x + s * .34, y + s * .5], 90, 270, fill=c,
          width=max(2, int(s * .1)))
    d.arc([x + s * .66, y + s * .1, x + s * .98, y + s * .5], 270, 90, fill=c,
          width=max(2, int(s * .1)))


def _flag(d, x, y, s, c):
    d.rectangle([x + s * .12, y, x + s * .24, y + s], fill=c)
    d.polygon([(x + s * .24, y + s * .06), (x + s, y + s * .26),
               (x + s * .24, y + s * .5)], fill=c)


def _stopwatch(d, x, y, s, c):
    d.ellipse([x + s * .06, y + s * .18, x + s * .94, y + s], outline=c,
              width=max(2, int(s * .12)))
    d.rectangle([x + s * .38, y, x + s * .62, y + s * .16], fill=c)
    d.line([(x + s * .5, y + s * .58), (x + s * .5, y + s * .34)], fill=c,
           width=max(2, int(s * .1)))


def _note(d, x, y, s, c):
    d.ellipse([x + s * .04, y + s * .62, x + s * .5, y + s], fill=c)
    d.rectangle([x + s * .42, y + s * .06, x + s * .54, y + s * .82], fill=c)
    d.polygon([(x + s * .54, y + s * .06), (x + s, y + s * .2),
               (x + s, y + s * .42), (x + s * .54, y + s * .28)], fill=c)


def _beam(d, x, y, s, c):
    d.ellipse([x, y + s * .6, x + s * .38, y + s * .96], fill=c)
    d.ellipse([x + s * .56, y + s * .48, x + s * .94, y + s * .84], fill=c)
    d.rectangle([x + s * .3, y + s * .08, x + s * .4, y + s * .8], fill=c)
    d.rectangle([x + s * .86, y, x + s * .96, y + s * .68], fill=c)
    d.polygon([(x + s * .3, y + s * .08), (x + s * .96, y), (x + s * .96, y + s * .2),
               (x + s * .3, y + s * .28)], fill=c)


def _wave(d, x, y, s, c):
    w = max(2, int(s * .13))
    for i, h in enumerate((.3, .62, .92, .5, .74, .34)):
        cx = x + s * (.06 + i * .18)
        d.rounded_rectangle([cx, y + s * (1 - h) / 2, cx + w, y + s * (1 + h) / 2],
                            w / 2, fill=c)


def _speaker(d, x, y, s, c):
    d.rounded_rectangle([x + s * .06, y + s * .06, x + s * .94, y + s * .94], s * .14,
                        outline=c, width=max(2, int(s * .1)))
    d.ellipse([x + s * .28, y + s * .44, x + s * .72, y + s * .86], fill=c)
    d.ellipse([x + s * .4, y + s * .16, x + s * .6, y + s * .34], fill=c)


def _disc(d, x, y, s, c):
    d.ellipse([x, y, x + s, y + s], outline=c, width=max(2, int(s * .1)))
    d.ellipse([x + s * .38, y + s * .38, x + s * .62, y + s * .62], fill=c)


def _mic(d, x, y, s, c):
    d.rounded_rectangle([x + s * .34, y, x + s * .66, y + s * .56], s * .16, fill=c)
    d.arc([x + s * .16, y + s * .3, x + s * .84, y + s * .84], 0, 180, fill=c,
          width=max(2, int(s * .1)))
    d.rectangle([x + s * .46, y + s * .78, x + s * .54, y + s], fill=c)


def _column(d, x, y, s, c):
    d.rectangle([x + s * .1, y, x + s * .9, y + s * .12], fill=c)
    d.rectangle([x + s * .06, y + s * .88, x + s * .94, y + s], fill=c)
    for i in range(3):
        cx = x + s * (.2 + i * .27)
        d.rectangle([cx, y + s * .14, cx + s * .13, y + s * .86], fill=c)


def _hourglass(d, x, y, s, c):
    d.rectangle([x + s * .1, y, x + s * .9, y + s * .1], fill=c)
    d.rectangle([x + s * .1, y + s * .9, x + s * .9, y + s], fill=c)
    d.polygon([(x + s * .2, y + s * .1), (x + s * .8, y + s * .1),
               (x + s * .5, y + s * .5)], fill=c)
    d.polygon([(x + s * .2, y + s * .9), (x + s * .8, y + s * .9),
               (x + s * .5, y + s * .5)], fill=c)


def _quill(d, x, y, s, c):
    """A feather with a spine: a bare diagonal reads as a slash, not a pen."""
    d.polygon([(x + s, y), (x + s * .86, y + s * .5), (x + s * .5, y + s * .78),
               (x + s * .2, y + s * .8)], fill=c)
    d.line([(x + s, y), (x, y + s)], fill=c, width=max(2, int(s * .1)))
    for i in range(3):
        k = .3 + i * .2
        d.line([(x + s * (1 - k), y + s * k),
                (x + s * (1 - k * .45), y + s * (k + .2))],
               fill=(0, 0, 0, 0), width=max(1, int(s * .05)))


def _laurel(d, x, y, s, c):
    """A wreath: two branches of leaves curving up to an opening at the top."""
    cx, cy, r = x + s / 2, y + s / 2, s * .4
    box = [cx - r, cy - r, cx + r, cy + r]
    w = max(2, int(s * .07))
    d.arc(box, 100, 200, fill=c, width=w)
    d.arc(box, 340, 80, fill=c, width=w)
    for deg in (108, 130, 152, 174, 196):
        for a in (deg, 180 - deg):          # mirrored across the vertical axis
            rad = math.radians(a)
            px, py = cx + r * math.cos(rad), cy + r * math.sin(rad)
            ox, oy = math.cos(rad), math.sin(rad)
            tx, ty = -oy, ox                # along the branch
            d.polygon([(px + ox * s * .19, py + oy * s * .19),
                       (px + tx * s * .08, py + ty * s * .08),
                       (px - ox * s * .04, py - oy * s * .04),
                       (px - tx * s * .08, py - ty * s * .08)], fill=c)


def _key(d, x, y, s, c):
    d.ellipse([x, y + s * .26, x + s * .48, y + s * .74], outline=c,
              width=max(2, int(s * .13)))
    d.rectangle([x + s * .42, y + s * .44, x + s, y + s * .56], fill=c)
    d.rectangle([x + s * .74, y + s * .56, x + s * .84, y + s * .76], fill=c)


def _chip(d, x, y, s, c):
    d.rounded_rectangle([x + s * .2, y + s * .2, x + s * .8, y + s * .8], s * .1,
                        outline=c, width=max(2, int(s * .12)))
    for i in range(3):
        o = s * (.32 + i * .18)
        d.rectangle([x + o, y, x + o + s * .07, y + s * .2], fill=c)
        d.rectangle([x + o, y + s * .8, x + o + s * .07, y + s], fill=c)
        d.rectangle([x, y + o, x + s * .2, y + o + s * .07], fill=c)
        d.rectangle([x + s * .8, y + o, x + s, y + o + s * .07], fill=c)


def _cursor(d, x, y, s, c):
    d.polygon([(x + s * .2, y), (x + s * .2, y + s * .84), (x + s * .42, y + s * .62),
               (x + s * .56, y + s * .96), (x + s * .72, y + s * .88),
               (x + s * .58, y + s * .56), (x + s * .86, y + s * .5)], fill=c)


def _bolt(d, x, y, s, c):
    d.polygon([(x + s * .62, y), (x + s * .18, y + s * .56), (x + s * .46, y + s * .56),
               (x + s * .34, y + s), (x + s * .82, y + s * .4),
               (x + s * .52, y + s * .4)], fill=c)


def _crown(d, x, y, s, c):
    d.polygon([(x, y + s * .84), (x + s * .12, y + s * .18), (x + s * .34, y + s * .52),
               (x + s * .5, y + s * .08), (x + s * .66, y + s * .52),
               (x + s * .88, y + s * .18), (x + s, y + s * .84)], fill=c)
    d.rectangle([x, y + s * .84, x + s, y + s], fill=c)


def _gem(d, x, y, s, c):
    d.polygon([(x + s * .5, y), (x + s, y + s * .38), (x + s * .5, y + s),
               (x, y + s * .38)], fill=c)


def _bez(p0, p1, p2, n: int = 12) -> list[tuple[float, float]]:
    """Sample a quadratic curve. Pillow has no curves, and a leaf needs two."""
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def _leaf(d, x, y, s, c):
    tip, base = (x + s, y), (x, y + s)
    pts = _bez(base, (x + s * .08, y + s * .18), tip) + \
        _bez(tip, (x + s * .82, y + s * .92), base)
    d.polygon(pts, fill=c)
    d.line([base, tip], fill=(0, 0, 0, 0), width=max(1, int(s * .07)))


def _pot(d, x, y, s, c):
    d.rounded_rectangle([x + s * .1, y + s * .34, x + s * .9, y + s * .92], s * .16, fill=c)
    d.rectangle([x, y + s * .26, x + s, y + s * .38], fill=c)
    d.rectangle([x + s * .44, y + s * .06, x + s * .56, y + s * .26], fill=c)


def _camera(d, x, y, s, c):
    d.rounded_rectangle([x, y + s * .22, x + s, y + s * .9], s * .14, fill=c)
    d.rectangle([x + s * .3, y + s * .1, x + s * .6, y + s * .28], fill=c)
    d.ellipse([x + s * .32, y + s * .38, x + s * .68, y + s * .74], fill=(0, 0, 0, 0))


def _film(d, x, y, s, c):
    d.rectangle([x, y + s * .2, x + s, y + s * .8], fill=c)
    for i in range(4):
        cx = x + s * (.08 + i * .25)
        d.rectangle([cx, y + s * .26, cx + s * .1, y + s * .36], fill=(0, 0, 0, 0))
        d.rectangle([cx, y + s * .64, cx + s * .1, y + s * .74], fill=(0, 0, 0, 0))


def _globe(d, x, y, s, c):
    w = max(2, int(s * .1))
    d.ellipse([x, y, x + s, y + s], outline=c, width=w)
    d.ellipse([x + s * .3, y, x + s * .7, y + s], outline=c, width=max(1, w // 2))
    d.line([(x + s * .04, y + s * .5), (x + s * .96, y + s * .5)], fill=c,
           width=max(1, w // 2))


def _rocket(d, x, y, s, c):
    d.polygon([(x + s * .26, y + s * .48), (x + s * .02, y + s * .92),
               (x + s * .26, y + s * .82)], fill=c)
    d.polygon([(x + s * .74, y + s * .48), (x + s * .98, y + s * .92),
               (x + s * .74, y + s * .82)], fill=c)
    d.polygon([(x + s * .5, y), (x + s * .72, y + s * .34), (x + s * .72, y + s * .9),
               (x + s * .28, y + s * .9), (x + s * .28, y + s * .34)], fill=c)
    d.ellipse([x + s * .38, y + s * .36, x + s * .62, y + s * .6], fill=(0, 0, 0, 0))


def _plus(d, x, y, s, c):
    a = s * .28
    d.rectangle([x + (s - a) / 2, y, x + (s + a) / 2, y + s], fill=c)
    d.rectangle([x, y + (s - a) / 2, x + s, y + (s + a) / 2], fill=c)


def _ring(d, x, y, s, c):
    d.ellipse([x, y, x + s, y + s], outline=c, width=max(2, int(s * .18)))


def _chevron(d, x, y, s, c):
    w = max(2, int(s * .18))
    d.line([(x + s * .2, y + s * .1), (x + s * .8, y + s * .5),
            (x + s * .2, y + s * .9)], fill=c, width=w, joint="curve")


def _triangle(d, x, y, s, c):
    d.polygon([(x + s * .5, y), (x + s, y + s * .88), (x, y + s * .88)], fill=c)


ICONS: dict[str, Callable] = {
    "controller": _controller, "dpad": _dpad, "pixel_heart": _pixel_heart,
    "star4": _star4, "star5": _star5, "sparkle": _sparkle,
    "lipstick": _lipstick, "droplet": _droplet, "brush": _brush,
    "compact": _compact, "bow": _bow,
    "ball": _ball, "whistle": _whistle, "trophy": _trophy, "flag": _flag,
    "stopwatch": _stopwatch,
    "note": _note, "beam": _beam, "wave": _wave, "speaker": _speaker,
    "disc": _disc, "mic": _mic,
    "column": _column, "hourglass": _hourglass, "quill": _quill,
    "laurel": _laurel, "key": _key,
    "chip": _chip, "cursor": _cursor, "bolt": _bolt,
    "crown": _crown, "gem": _gem, "leaf": _leaf, "pot": _pot,
    "camera": _camera, "film": _film, "globe": _globe, "rocket": _rocket,
    "plus": _plus, "ring": _ring, "chevron": _chevron, "triangle": _triangle,
}
ICON_KEYS = sorted(ICONS)


def icon(key: str, size: int, color, pad: float = 0.0) -> Image.Image:
    """One glyph on transparency, sized to `size`."""
    box = int(size + size * pad * 2)
    layer = Image.new("RGBA", (max(1, box), max(1, box)), (0, 0, 0, 0))
    draw = ICONS.get(key)
    if draw:
        draw(ImageDraw.Draw(layer), size * pad, size * pad, size, _c(color))
    return layer


# ------------------------------------------------------------------- patterns
def icon_field(size: tuple[int, int], keys: Iterable[str], colors: list,
               cell: int = 128, glyph: float = 0.46, angle: float = -16.0,
               alpha: int = 40, seed: int = 7, ground=None) -> Image.Image:
    """A brick-offset field of glyphs, rotated off-square.

    Rotation is the whole difference between a pattern and a spreadsheet, and
    every row is offset by half a cell so the eye cannot find the grid.
    """
    w, h = size
    keys = [k for k in keys if k in ICONS] or ["star4"]
    colors = [_c(c) for c in (colors or [(255, 255, 255, 255)])]
    diag = int(math.hypot(w, h)) + cell * 2
    field = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    d = ImageDraw.Draw(field)
    rnd = random.Random(seed)

    g = int(cell * glyph)
    rows = diag // cell + 2
    for row in range(rows):
        y = row * cell
        offset = (cell // 2) if row % 2 else 0
        for col in range(diag // cell + 2):
            x = col * cell + offset - cell
            k = keys[(row * 3 + col * 5 + rnd.randrange(0, 2)) % len(keys)]
            color = colors[(row + col) % len(colors)]
            size_jitter = g * (0.82 + rnd.random() * 0.36)
            ICONS[k](d, x + (cell - size_jitter) / 2, y + (cell - size_jitter) / 2,
                     size_jitter, color[:3] + (alpha,))

    field = field.rotate(angle, Image.BICUBIC)
    field = field.crop(((diag - w) // 2, (diag - h) // 2,
                        (diag - w) // 2 + w, (diag - h) // 2 + h))
    if ground is None:
        return field
    base = Image.new("RGBA", size, _c(ground))
    return Image.alpha_composite(base, field)


def word_field(size: tuple[int, int], text: str, stack: list, colors: list,
               rows: int = 7, angle: float = -12.0, alpha: int = 46,
               outline_every: int = 2, tracking: float = 8.0,
               ground=None) -> Image.Image:
    """The name repeated in stepped rows — branding you can read at 120px.

    Every other row is set as an outline rather than a fill, which is what stops
    a wall of the same word turning into a solid block of colour.
    """
    w, h = size
    text = (text or "").strip().upper() or "CHANNEL"
    colors = [_c(c) for c in (colors or [(255, 255, 255, 255)])]
    diag = int(math.hypot(w, h)) + 40
    field = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    d = ImageDraw.Draw(field)

    row_h = diag / max(1, rows)
    font = titles._load(stack, max(14, int(row_h * 0.74)))
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    unit = sum(probe.textlength(ch, font=font) + tracking for ch in text + "  ")

    for row in range(rows + 1):
        y = row * row_h
        color = colors[row % len(colors)][:3] + (alpha,)
        outlined = outline_every and row % outline_every == 1
        x = -unit * ((row * 0.37) % 1.0)
        while x < diag:
            for ch in text + "  ":
                if outlined:
                    d.text((x, y), ch, font=font, fill=(0, 0, 0, 0),
                           stroke_width=max(1, int(row_h * 0.03)), stroke_fill=color)
                else:
                    d.text((x, y), ch, font=font, fill=color)
                x += probe.textlength(ch, font=font) + tracking
    field = field.rotate(angle, Image.BICUBIC)
    field = field.crop(((diag - w) // 2, (diag - h) // 2,
                        (diag - w) // 2 + w, (diag - h) // 2 + h))
    if ground is None:
        return field
    base = Image.new("RGBA", size, _c(ground))
    return Image.alpha_composite(base, field)


def stripes(size: tuple[int, int], colors: list, width: int = 46,
            angle: float = -22.0) -> Image.Image:
    """Diagonal bands. The oldest sports graphic there is, and still the loudest."""
    w, h = size
    colors = [_c(c) for c in colors] or [(255, 255, 255, 255)]
    diag = int(math.hypot(w, h)) + width * 2
    band = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    for i in range(diag // width + 2):
        d.rectangle([i * width, 0, (i + 1) * width, diag], fill=colors[i % len(colors)])
    band = band.rotate(angle, Image.BICUBIC)
    return band.crop(((diag - w) // 2, (diag - h) // 2,
                      (diag - w) // 2 + w, (diag - h) // 2 + h))


def halftone(size: tuple[int, int], color, cell: int = 22, radius: float = 0.3,
             fade: tuple[float, float] = (0.0, 1.0), angle: float = 0.0) -> Image.Image:
    """A dot screen that thins out across the frame. For the poppier grounds."""
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = _c(color)
    for row, y in enumerate(range(0, h + cell, cell)):
        for col, x in enumerate(range(0, w + cell, cell)):
            k = x / max(1, w)
            v = fade[0] + (fade[1] - fade[0]) * k
            r = cell * radius * v
            if r < 0.4:
                continue
            cx = x + (cell / 2 if row % 2 else 0)
            d.ellipse([cx - r, y - r, cx + r, y + r], fill=c)
    return layer.rotate(angle, Image.BICUBIC) if angle else layer


def noise(size: tuple[int, int], sigma: float = 12.0, alpha: int = 26) -> Image.Image:
    """A little tooth over a flat gradient, so it does not band on a TV."""
    w, h = size
    grain = Image.effect_noise((max(2, w // 2), max(2, h // 2)), sigma) \
        .resize(size, Image.BILINEAR)
    layer = Image.new("RGBA", size, (255, 255, 255, 0))
    layer.putalpha(grain.point(lambda v: int(abs(v - 128) / 128 * alpha)))
    return layer

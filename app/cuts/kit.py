"""What the five drawn cuts share: cue timing, scaled drawing, fonts, easing.

Every cut in this package draws its own frames in Pillow, the way the board
does, but they differ from the board in one important way: they are built from
*cues* rather than templates. A cue is one thing that happens on screen — a
line of code typing in, a polaroid pinned up, a message arriving — and it
carries an `on`, the words of the narration it lands on. Placing each cue at
its words is what keeps a fast cut on the voice: a Flameboat cut changes on
the clause, and a cue that arrives a sentence late is a joke that misses.

There are no word timings in a take, only its duration, so a cue's words are
placed by their position in the paragraph's text — character offset over
character count, scaled into the spoken part of the take. For a steady read
that lands within a few hundred milliseconds, which is inside what a hard cut
needs. A cue whose words cannot be found is spaced evenly between the ones
that can.

Drawing happens at a scale `k` off the 1080p layout: 1.0 for the real render,
the preview's quarter for the in-app preview. Every coordinate a cut writes is
in 1080p pixels and goes through `Stage`, so a preview is the same frame
smaller rather than the full frame drawn and then thrown away — the cost the
board format still pays (see NEXT_STEPS.md, item 2).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import titles
from ..config import FONTS_DIR, HEIGHT, WIDTH

W, H = WIDTH, HEIGHT

# ---------------------------------------------------------------------- fonts
FACES = {
    "display": "ArchivoBlack-Regular.ttf",     # the heavy one, for type that hits
    "condensed": "ArchivoNarrow-Bold.ttf",
    "sans": "Inter-SemiBold.ttf",
    "sans_bold": "Inter-Bold.ttf",
    "sans_med": "Inter-Medium.ttf",
    "mono": "JetBrainsMono-Regular.ttf",
    "mono_bold": "JetBrainsMono-Bold.ttf",
    "serif": "EBGaramond-Regular.ttf",
    "serif_italic": "EBGaramond-Italic.ttf",
    "marker": "PermanentMarker-Regular.ttf",
    "hand": "Caveat-Bold.ttf",
    "typewriter": "JetBrainsMono-Regular.ttf",
}


@lru_cache(maxsize=512)
def font(face: str, px: int) -> ImageFont.FreeTypeFont:
    """A face at a pixel size. Falls back to Pillow's own face if missing."""
    px = max(1, int(px))
    try:
        return ImageFont.truetype(str(FONTS_DIR / FACES.get(face, FACES["sans"])), px)
    except OSError:
        return ImageFont.load_default(px)


_PROBE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def measure(text: str, face: str, px: float) -> tuple[float, float]:
    """Width and height of `text` in 1080p pixels."""
    if not text:
        return 0.0, float(px)
    box = _PROBE.textbbox((0, 0), text, font=font(face, round(px)))
    return float(box[2] - box[0]), float(box[3] - box[1])


def advance(text: str, face: str, px: float) -> float:
    """How far the pen moves for `text` — what laying words end to end needs.

    Not the same as `measure`, which is the ink: a bracket's ink is narrower
    than the space it takes, and spaces have no ink at all.
    """
    return float(font(face, round(px)).getlength(text)) if text else 0.0


def wrap(text: str, face: str, px: float, max_w: float) -> list[str]:
    """Greedy word wrap in 1080p pixels."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and measure(trial, face, px)[0] > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def fit(text: str, face: str, px: float, max_w: float, max_lines: int,
        floor: float = 18) -> tuple[float, list[str]]:
    """The largest size up to `px` at which `text` wraps into `max_lines`."""
    size = float(px)
    while size > floor:
        lines = wrap(text, face, size, max_w)
        if len(lines) <= max_lines and all(measure(l, face, size)[0] <= max_w
                                           for l in lines):
            return size, lines
        size *= 0.92
    return floor, wrap(text, face, floor, max_w)[:max_lines]


# --------------------------------------------------------------------- colour
def rgba(color, alpha: int | None = None) -> tuple[int, int, int, int]:
    if isinstance(color, str):
        c = titles._hex(color)
    else:
        c = tuple(color) + (255,) * (4 - len(color))
    return (c[0], c[1], c[2], c[3] if alpha is None else int(alpha))


def mix(a, b, t: float) -> tuple[int, int, int, int]:
    ca, cb = rgba(a), rgba(b)
    t = clamp(t)
    return tuple(int(ca[i] + (cb[i] - ca[i]) * t) for i in range(4))


# --------------------------------------------------------------------- easing
def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_out(t: float) -> float:
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_back(t: float, s: float = 1.9) -> float:
    """Overshoot and settle — the "pop" a logo or a sticker arrives with."""
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def progress(t: float, start: float, dur: float) -> float:
    return clamp((t - start) / dur) if dur > 0 else (1.0 if t >= start else 0.0)


# ----------------------------------------------------------------------- stage
class Stage:
    """A frame at scale `k`, addressed in 1080p pixels.

    Thin on purpose: it multiplies, and it caches the faces at the scaled
    size. Anything it does not wrap is reachable as `.img` and `.draw` with
    `.p()` to convert a coordinate.
    """

    def __init__(self, k: float, ground=(0, 0, 0, 255), base: Image.Image | None = None):
        self.k = k
        self.size = (max(2, round(W * k)), max(2, round(H * k)))
        if base is not None:
            self.img = base.copy() if base.mode == "RGBA" else base.convert("RGBA")
        else:
            self.img = Image.new("RGBA", self.size, rgba(ground))
        self.draw = ImageDraw.Draw(self.img)

    @classmethod
    def sized(cls, w: float, h: float, k: float, fill=(0, 0, 0, 0)) -> "Stage":
        """A canvas of any size, still addressed in unscaled pixels."""
        s = cls(k)
        s.size = (max(1, round(w * k)), max(1, round(h * k)))
        s.img = Image.new("RGBA", s.size, rgba(fill))
        s.draw = ImageDraw.Draw(s.img)
        return s

    def p(self, v: float) -> int:
        return int(round(v * self.k))

    def box(self, x0, y0, x1, y1) -> tuple[int, int, int, int]:
        return (self.p(x0), self.p(y0), self.p(x1), self.p(y1))

    def font(self, face: str, px: float) -> ImageFont.FreeTypeFont:
        return font(face, round(px * self.k))

    def text(self, xy, text: str, face: str, px: float, fill, anchor: str = "la",
             stroke: float = 0, stroke_fill=None) -> None:
        if not text:
            return
        self.draw.text((xy[0] * self.k, xy[1] * self.k), text,
                       font=self.font(face, px), fill=rgba(fill), anchor=anchor,
                       stroke_width=max(0, round(stroke * self.k)),
                       stroke_fill=rgba(stroke_fill) if stroke_fill is not None else None)

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width: float = 0,
             radius: float = 0) -> None:
        b = self.box(x0, y0, x1, y1)
        if b[2] <= b[0] or b[3] <= b[1]:
            return
        kw = dict(fill=rgba(fill) if fill is not None else None,
                  outline=rgba(outline) if outline is not None else None,
                  width=max(1, self.p(width)) if outline is not None else 0)
        if radius:
            self.draw.rounded_rectangle(b, radius=self.p(radius), **kw)
        else:
            self.draw.rectangle(b, **kw)

    def wash(self, x0, y0, x1, y1, fill, radius: float = 0) -> None:
        """A translucent fill, blended — `rect` writes alpha straight through."""
        b = self.box(x0, y0, x1, y1)
        w, h = b[2] - b[0], b[3] - b[1]
        if w <= 0 or h <= 0:
            return
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        if radius:
            d.rounded_rectangle((0, 0, w - 1, h - 1), radius=self.p(radius), fill=rgba(fill))
        else:
            d.rectangle((0, 0, w, h), fill=rgba(fill))
        _composite_clipped(self.img, tile, b[0], b[1])

    def layer(self, fill=(0, 0, 0, 0)) -> "Stage":
        """A transparent stage the same size, to draw on and composite back."""
        s = Stage(self.k)
        s.img = Image.new("RGBA", self.size, rgba(fill))
        s.draw = ImageDraw.Draw(s.img)
        return s

    def paste(self, tile: Image.Image, x: float, y: float, alpha: float = 1.0) -> None:
        """Composite an already-scaled RGBA tile at a 1080p position."""
        if alpha <= 0.003:
            return
        if alpha < 0.997:
            tile = with_alpha(tile, alpha)
        _composite_clipped(self.img, tile, self.p(x), self.p(y))

    def rgb(self) -> Image.Image:
        return self.img.convert("RGB")


def _composite_clipped(base: Image.Image, tile: Image.Image, x: int, y: int) -> None:
    """alpha_composite refuses offsets off the canvas; crop the tile instead."""
    cx, cy = max(0, -x), max(0, -y)
    rx = min(tile.width, base.width - x)
    ry = min(tile.height, base.height - y)
    if cx >= rx or cy >= ry:
        return
    if (cx, cy, rx, ry) != (0, 0, tile.width, tile.height):
        tile = tile.crop((cx, cy, rx, ry))
    base.alpha_composite(tile, dest=(max(0, x), max(0, y)))


def with_alpha(tile: Image.Image, alpha: float) -> Image.Image:
    tile = tile.copy()
    a = tile.getchannel("A").point(lambda v: int(v * clamp(alpha)))
    tile.putalpha(a)
    return tile


def punch(frame: Image.Image, scale: float, dx: float = 0.0, dy: float = 0.0) -> Image.Image:
    """Zoom a finished frame about its centre, with an optional nudge.

    The punch-in a fast cut lands a word with, and the shake on a joke. A
    scale under ~1.002 and no nudge is returned untouched, so a settled shot
    costs nothing.
    """
    if scale <= 1.002 and abs(dx) < 0.5 and abs(dy) < 0.5:
        return frame
    w, h = frame.size
    cw, ch = w / max(1.0, scale), h / max(1.0, scale)
    x0 = clamp((w - cw) / 2 + dx, 0, w - cw)
    y0 = clamp((h - ch) / 2 + dy, 0, h - ch)
    return frame.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


def shake(t: float, seed: int, amp: float, dur: float = 0.3) -> tuple[float, float]:
    """A decaying jitter for the first `dur` seconds after a hit."""
    if t < 0 or t > dur or amp <= 0:
        return 0.0, 0.0
    fall = 1 - t / dur
    return (amp * fall * math.sin(t * 91 + seed),
            amp * fall * math.cos(t * 77 + seed * 1.7))


# --------------------------------------------------------------------- images
def cover(img: Image.Image, w: int, h: int, focal=(0.5, 0.5)) -> Image.Image:
    """Fill `w`×`h` with `img`, cropping around its focal point."""
    w, h = max(1, int(w)), max(1, int(h))
    s = max(w / img.width, h / img.height)
    rw, rh = max(w, round(img.width * s)), max(h, round(img.height * s))
    x = clamp(focal[0] * rw - w / 2, 0, rw - w)
    y = clamp(focal[1] * rh - h / 2, 0, rh - h)
    return img.resize((w, h), Image.LANCZOS,
                      box=(x / s, y / s, (x + w) / s, (y + h) / s))


def contain(img: Image.Image, w: int, h: int) -> Image.Image:
    s = min(w / img.width, h / img.height)
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                      Image.LANCZOS)


def shadow_of(tile: Image.Image, radius: float, alpha: int = 140) -> Image.Image:
    """A soft drop shadow the shape of `tile`'s alpha."""
    pad = int(radius * 2) + 2
    sh = Image.new("RGBA", (tile.width + pad * 2, tile.height + pad * 2), (0, 0, 0, 0))
    mask = Image.new("L", sh.size, 0)
    mask.paste(tile.getchannel("A").point(lambda v: v * alpha // 255), (pad, pad))
    sh.putalpha(mask.filter(ImageFilter.GaussianBlur(max(0.5, radius))))
    return sh


def vignette(size: tuple[int, int], strength: float = 0.6,
             centre=(0.5, 0.5), color=(0, 0, 0)) -> Image.Image:
    """A dark-edged overlay, computed small and scaled up."""
    sw, sh = 160, 90
    m = Image.new("L", (sw, sh))
    px = m.load()
    for y in range(sh):
        for x in range(sw):
            dx = (x / sw - centre[0]) * 1.25
            dy = (y / sh - centre[1])
            d = math.sqrt(dx * dx + dy * dy) / 0.72
            px[x, y] = int(255 * clamp(strength * d ** 2.2))
    layer = Image.new("RGBA", size, color + (0,))
    layer.putalpha(m.resize(size, Image.BILINEAR))
    return layer


# -------------------------------------------------------------------- footage
MOTION_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".gif"}


def is_motion(path) -> bool:
    return path is not None and str(path).lower().endswith(tuple(MOTION_EXT))


class Footage:
    """A clip or GIF, decoded frame by frame at exactly the size a slot needs.

    One ffmpeg process per (clip, size, framing), cropped to cover and looped
    for as long as it is asked for, read forward as the frames are drawn —
    which is the order every cut asks for them in. Asking for an earlier time
    restarts it, which only the editor's scrub does. A whole paragraph is
    never held in memory, only the current frame.

    `dim` scales the picture's levels (1 = untouched) for type that has to
    read on top of it, done in the decoder rather than per frame here.
    """

    def __init__(self, src, w: int, h: int, fps: int, focal=(0.5, 0.5), dim: float = 1.0):
        self.src, self.w, self.h, self.fps = str(src), max(2, int(w)), max(2, int(h)), fps
        self.focal, self.dim = focal, dim
        self.proc = None
        self.index = -1
        self.raw: bytes | None = None
        self.img: Image.Image | None = None

    def _start(self) -> None:
        import subprocess

        from ..config import FFMPEG

        w, h = self.w, self.h
        fx, fy = (clamp(float(v)) for v in self.focal)
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h}:(iw-{w})*{fx:.3f}:(ih-{h})*{fy:.3f},"
              f"fps={self.fps},format=rgb24")
        if self.dim < 0.999:
            d = f"{max(0.05, self.dim):.3f}"
            vf += f",colorlevels=romax={d}:gomax={d}:bomax={d}"
        self.proc = subprocess.Popen(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-stream_loop", "-1",
             "-i", self.src, "-vf", vf, "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.index = -1

    def frame(self, t: float) -> Image.Image | None:
        """The frame `t` seconds in, as RGB. None if the clip will not decode."""
        want = max(0, int(t * self.fps))
        if self.proc is None or want < self.index:
            self.close()
            self._start()
        size = self.w * self.h * 3
        moved = False
        while self.index < want:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:
                break                       # a broken file: hold the last frame
            self.raw, self.index, moved = buf, self.index + 1, True
        if self.raw is None:
            return None
        if moved or self.img is None:
            self.img = Image.frombytes("RGB", (self.w, self.h), self.raw)
        return self.img

    def close(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None


def footage(ctx, src, w: int, h: int, focal=(0.5, 0.5), dim: float = 1.0) -> Footage:
    """The shared decoder for this clip at this size, made on first use."""
    key = ("footage", str(src), int(w), int(h), tuple(round(f, 3) for f in focal), round(dim, 3))
    if key not in ctx.cache:
        ctx.cache[key] = Footage(src, w, h, ctx.fps, focal, dim)
    return ctx.cache[key]


def close_footage(ctx) -> None:
    for key, value in list(ctx.cache.items()):
        if isinstance(value, Footage):
            value.close()


# ------------------------------------------------------------------- cue time
_WORD = re.compile(r"[\w']+")


def _norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def place(narration: str, cues: list[dict], spoken: float, length: float,
          lead: float = 0.0, min_hold: float = 0.35) -> list[tuple[float, float]]:
    """Start and end of every cue inside a paragraph `length` seconds long.

    The voice runs from `lead` to `lead + spoken`; the rest of `length` is
    the pause after it. The first cue always opens the paragraph, so there is
    never a frame with nothing on it. Returns one (start, end) per cue.
    """
    if not cues:
        return []
    text = _norm(narration)
    total = max(1, len(text))
    anchors: list[float | None] = []
    pos = 0
    for c in cues:
        on = _norm(c.get("on", ""))
        at = -1
        if on:
            words = on.split()
            for n in (len(words), 5, 3, 2):
                probe = " ".join(words[:n])
                if not probe:
                    continue
                at = text.find(probe, pos)
                if at >= 0:
                    break
        if at >= 0:
            anchors.append(at / total)
            pos = at + 1
        else:
            anchors.append(None)
    anchors[0] = 0.0
    # Fill the gaps evenly between the anchors either side of them.
    known = [i for i, a in enumerate(anchors) if a is not None]
    for i, a in enumerate(anchors):
        if a is not None:
            continue
        before = max(j for j in known if j < i)
        after = next((j for j in known if j > i), None)
        lo = anchors[before]
        hi = anchors[after] if after is not None else 1.0
        span = (after if after is not None else len(anchors)) - before
        anchors[i] = lo + (hi - lo) * (i - before) / span
    starts = [0.0] + [lead + spoken * a for a in anchors[1:]]
    # Monotonic, each at least `min_hold` after the last, and inside the
    # paragraph — a crowded paragraph compresses rather than overruns.
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1] + min_hold)
    limit = max(0.0, length - min_hold)
    if starts and starts[-1] > limit:
        squeeze = limit / starts[-1] if starts[-1] > 0 else 0
        starts = [s * squeeze for s in starts]
    ends = starts[1:] + [length]
    return list(zip(starts, ends))


_CLAUSE = re.compile(r"(?<=[.!?;:,—])\s+")


def clauses(text: str, max_words: int = 9, min_words: int = 3) -> list[str]:
    """Narration cut where a fast edit would cut it: on the clause."""
    out: list[str] = []
    for part in _CLAUSE.split((text or "").strip()):
        words = part.split()
        while len(words) > max_words:
            out.append(" ".join(words[:max_words]))
            words = words[max_words:]
        if words:
            out.append(" ".join(words))
    merged: list[str] = []
    for c in out:
        if merged and len(c.split()) < min_words:
            merged[-1] = f"{merged[-1]} {c}"
        else:
            merged.append(c)
    return merged


def head(text: str, words: int = 4) -> str:
    """The opening words of a phrase — what a derived cue lands `on`."""
    return " ".join(_WORD.findall(text)[:words])


def short(text: str, words: int = 6) -> str:
    parts = (text or "").strip().strip(".,;:—").split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


_STOP = set("""a an the and or but so of to in on at by for with from as is are was were
be been being it its it's this that these those there their they them he she his her
we our you your i my me not no do does did have has had will would can could should
just than then into over about up out if when what which who whom how very more most
also only even""".split())


def keyword(text: str) -> str:
    """The word in a phrase most likely to carry the stress: long, not a stopword."""
    words = [w for w in re.findall(r"[A-Za-z0-9$%'.-]+", text or "")
             if w.lower().strip(".'") not in _STOP]
    if not words:
        return ""
    nums = [w for w in words if any(ch.isdigit() for ch in w)]
    if nums:
        return nums[0].strip(".")
    return max(words, key=len).strip(".")


FIGURE = re.compile(r"[$£€]?\d(?:[\d,]*\d)?(?:\.\d+)?(?:\s?(?:%|percent|million|billion|trillion)|[kKmMbBtT]\b)?")


def is_figure(text: str) -> bool:
    """A number worth a panel: money, a percentage, a scale word, or a big
    count. Not a year, and not the "2" out of "2am"."""
    t = text.strip()
    if re.search(r"[$£€%]|percent|million|billion|trillion|\d[kKmMbBtT]\b|\s[kKmMbBtT]\b", t):
        return True
    digits = re.sub(r"\D", "", t)
    return "," in t or (len(digits) >= 3 and not re.fullmatch(r"(1[89]|20)\d\d", digits))


def figure(text: str) -> tuple[str, str] | None:
    """The first figure in a phrase worth putting on screen, and a few words
    of what it counts. None when the phrase has no such number."""
    m = next((m for m in FIGURE.finditer(text or "") if is_figure(m.group())), None)
    if not m:
        return None
    value = m.group().strip().replace(" percent", "%").replace("percent", "%")
    # What it counts is usually the words straight after it ("14 trillion
    # dollars last year"), and otherwise the ones leading up to it.
    after = [w.strip(".,;:!?") for w in text[m.end():].split()][:3]
    before = [w.strip(".,;:!?") for w in text[:m.start()].split()][-3:]
    label = " ".join(w for w in (after if any(after) else before) if w)
    return value, label


# ----------------------------------------------------------------------- beats
@dataclass
class Beat:
    """One paragraph's worth of a cut, timed and ready to draw."""
    slide: Any
    cues: list[dict]
    times: list[tuple[float, float]]
    length: float
    spoken: float
    lead: float
    picture: Image.Image | None = None
    motion: Any = None                 # the clip/GIF behind `picture`, if it moves
    index: int = 0                     # which paragraph of the video this is
    last: bool = False                 # the final paragraph of the video
    extra: dict = field(default_factory=dict)

    def at(self, t: float) -> int:
        """Index of the cue on screen at time `t`."""
        for i, (s, e) in enumerate(self.times):
            if s <= t < e:
                return i
        return len(self.times) - 1 if self.times else 0


@dataclass
class Ctx:
    """Everything video-wide a cut draws with."""
    project: Any
    k: float
    fps: int
    accent: str
    accent2: str
    look: str
    channel: Any = None
    image_for: Any = None              # slide -> local Path or None
    cache: dict = field(default_factory=dict)

    @property
    def size(self) -> tuple[int, int]:
        return (max(2, round(W * self.k)), max(2, round(H * self.k)))


# ----------------------------------------------------------------- chapters
def dim_to(base: Image.Image, ground, amount: float) -> Stage:
    """`base` sunk towards a flat colour, as a Stage to draw the card on."""
    st = Stage(base.width / W, ground)
    st.img = Image.blend(base.convert("RGBA"), st.img, clamp(amount))
    st.draw = ImageDraw.Draw(st.img)
    return st


def chapter_screen(ctx, title: str, base: Image.Image, u: float,
                   ground=(12, 12, 14), ink=(244, 241, 234), accent=None,
                   label: str = "NEXT") -> Image.Image:
    """The plain chapter screen, and the fallback for a cut with none of its
    own: the last frame sinks into the ground, a label and the title come up.
    `u` is seconds since the card began."""
    st = dim_to(base, ground, 0.92 * ease_out(progress(u, 0, 0.4)))
    t = ease_out(progress(u, 0.15, 0.5))
    layer = st.layer()
    size, lines = fit(title.upper(), "display", 120, W - 300, 2, floor=54)
    top = H / 2 - len(lines) * size * 0.55 + 30 * (1 - t)
    layer.text((W / 2, top - 56), label, "mono_bold", 30, accent or ctx.accent, anchor="mm")
    for i, line in enumerate(lines):
        layer.text((W / 2, top + i * size * 1.1 + size * 0.5), line, "display", size,
                   ink, anchor="mm")
    st.img.alpha_composite(with_alpha(layer.img, t))
    return st.rgb()

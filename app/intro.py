"""The channel intro slate: a short animated opening every video in a series shares.

Frames are composed with Pillow and piped to ffmpeg as raw video. Doing the
animation here rather than in an ffmpeg filtergraph buys real easing, per-column
grading and typography that matches the slide titles, and it stays fast because
the expensive compositing work is cached across frames.

Thirteen templates live here. Three need a cast of portraits (columns,
filmstrip, mosaic — mosaic will fill out a short cast with graphic blocks); the
rest are type-led and stand on their own. The last five are theme-led: they read
`themes.palette()` for a second colour, a ground and a set of icons, so the same
template opens a gaming channel and a food channel quite differently.
"""
from __future__ import annotations

import hashlib
import math
import random
import uuid
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from . import ffutil, motifs, themes, titles
from .channels import channel_dir
from .config import FPS, HEIGHT, WIDTH
from .llm import MODEL_UTILITY, complete_json
from .schema import Channel

Progress = Callable[[str], None]

GUTTER = 3               # hairline gap between columns
SETTLE_PAD = 0.18        # beat after the last column lands before the title

# ------------------------------------------------------------------ templates
# Every slate the UI can offer. `needs_images` is what gates the cast panel and
# the render-without-a-slate fallback, so a type-led template works on a channel
# that has never been cast.
# `columns_label` and `stagger_label` are the two optional sliders the channel
# page draws; an empty one is a knob this template has no use for. Every
# template gets the length slider and the `fly_label` one.
TEMPLATES = [
    {"key": "columns", "label": "Columns of faces", "needs_images": True,
     "blurb": "Portraits fly in as vertical columns, then the series title. "
              "For people and history.",
     "columns_label": "Columns", "stagger_label": "Gap between columns",
     "fly_label": "Fly-in time"},
    {"key": "signal", "label": "Signal", "needs_images": False,
     "blurb": "A travelling accent bar wipes a big kinetic wordmark onto a "
              "technical grid. For technology.",
     "columns_label": "", "stagger_label": "Gap between lines",
     "fly_label": "Wipe speed"},
    {"key": "dossier", "label": "Dossier", "needs_images": False,
     "blurb": "A case file opening: ruled card, typed metadata, redaction bars "
              "sliding off the name, a stamp. For investigations.",
     "columns_label": "", "stagger_label": "Gap between redactions",
     "fly_label": "Uncover speed"},
    {"key": "filmstrip", "label": "Filmstrip", "needs_images": True,
     "blurb": "The cast runs past as one sprocketed strip — grain, gate "
              "flicker, weave — until it parks. For archive documentary.",
     "columns_label": "", "stagger_label": "How much film runs past",
     "fly_label": "Time to stop"},
    {"key": "mosaic", "label": "Mosaic", "needs_images": True,
     "blurb": "A wall of faces lands tile by tile in a shuffled order, then a "
              "band opens across it. For ensembles.",
     "columns_label": "Grid width", "stagger_label": "Gap between tiles",
     "fly_label": "Tile landing"},
    {"key": "pulse", "label": "Pulse", "needs_images": False,
     "blurb": "Letter-spacing collapses into the name over a mirrored "
              "spectrum that spikes on the landing. For talk and music.",
     "columns_label": "", "stagger_label": "Spectrum liveliness",
     "fly_label": "Lock-in speed"},
    {"key": "atlas", "label": "Atlas", "needs_images": False,
     "blurb": "A reticle crosses drifting contour country, locks onto "
              "coordinates and unfolds into the title. For places.",
     "columns_label": "", "stagger_label": "Map drift",
     "fly_label": "Reticle travel"},
    {"key": "folio", "label": "Folio", "needs_images": False,
     "blurb": "A cream page turns in and the title sets itself in Baskerville, "
              "line by line. For books and reading.",
     "columns_label": "", "stagger_label": "Gap between lines",
     "fly_label": "Page turn"},
    # The theme-led slates. These read the channel's theme for their second
    # colour, their ground and the icons their patterns are tiled from, so the
    # same template opens a gaming channel and a food channel quite differently.
    {"key": "dial", "label": "Dial", "needs_images": False, "themed": True,
     "blurb": "The frame is a watch dial: sunburst face, chapter ring, applied "
              "indices. The hands sweep up and settle at ten past ten. For "
              "watches and anything mechanical.",
     "columns_label": "", "stagger_label": "Gap between lines",
     "fly_label": "Hand sweep"},
    {"key": "arcade", "label": "Arcade", "needs_images": False, "themed": True,
     "blurb": "A cabinet attract screen: the wordmark drops onto a scrolling "
              "field of icons with a hard colour shadow. For gaming.",
     "columns_label": "Pattern density", "stagger_label": "Gap between lines",
     "fly_label": "Drop speed"},
    {"key": "gloss", "label": "Gloss", "needs_images": False, "themed": True,
     "blurb": "Soft light, drifting sparkles and one sweep of gloss across the "
              "name. For beauty and fashion.",
     "columns_label": "Pattern density", "stagger_label": "",
     "fly_label": "Fade up"},
    {"key": "kickoff", "label": "Kickoff", "needs_images": False, "themed": True,
     "blurb": "Diagonal bands slam in from both edges and the name lands "
              "sheared over a huge number. For sport.",
     "columns_label": "Band width", "stagger_label": "",
     "fly_label": "Slam speed"},
    {"key": "stack", "label": "Stack", "needs_images": False, "themed": True,
     "blurb": "The channel name repeated as its own wallpaper, scrolling, with "
              "a band cut out of it. For music and talk.",
     "columns_label": "Rows of wallpaper", "stagger_label": "",
     "fly_label": "Band opening"},
    {"key": "tiles", "label": "Tiles", "needs_images": False, "themed": True,
     "blurb": "A wall of icon tiles flips over one by one to uncover a plate "
              "carrying the name. For food, craft and making.",
     "columns_label": "Grid width", "stagger_label": "Gap between flips",
     "fly_label": "Flip speed"},
]
TEMPLATE_KEYS = [t["key"] for t in TEMPLATES]


def needs_images(template: str) -> bool:
    """Does this template need a cast before it can render?"""
    for t in TEMPLATES:
        if t["key"] == template:
            return bool(t["needs_images"])
    return True          # unknown template falls back to columns, which does


# ------------------------------------------------------------------- casting
def suggest_subjects(channel: Channel, count: int = 6) -> list[str]:
    """Ask for the faces that should front this channel."""
    prompt = f"""Cast the opening title sequence for a YouTube series.

SERIES NAME: {channel.name}
{f'TAGLINE: {channel.tagline}' if channel.tagline else ''}
WHAT IT COVERS: {channel.concept or 'not specified'}

The sequence is {count} vertical columns, each holding a photograph or painted
portrait of one person, that fly in before the series title appears.

Choose {count} people who fit this series and who a viewer might recognise on
sight. Spread them across eras, fields and parts of the world rather than
picking {count} versions of the same figure.

Each must be someone with a well known public-domain or freely licensed portrait
in the archives, so favour people who died before about 1960, or whose likeness
is heavily photographed and freely licensed.

Return JSON: a list of {count} objects:
{{"name": "the person's name as it would be catalogued",
  "query": "an archive search query for a good portrait of them, 2-4 words",
  "why": "six words on why they fit this series"}}"""

    out = complete_json(prompt, model=MODEL_UTILITY, timeout=300)
    if isinstance(out, dict):
        out = out.get("people") or out.get("subjects") or []
    subjects = []
    for item in out:
        if isinstance(item, str):
            subjects.append(item.strip())
        elif isinstance(item, dict):
            q = (item.get("query") or item.get("name") or "").strip()
            if q:
                subjects.append(q)
    return [s for s in subjects if s][:count]


def align_cast(intro) -> None:
    """Pad the cast's four arrays to one length.

    `subjects`, `images`, `focals` and `credits` are one table read by index:
    the face at `images[i]` belongs to `subjects[i]`. Anything that edits one of
    them has to edit all four, or a portrait ends up under somebody else's name.
    """
    n = len(intro.subjects)
    intro.images = (list(intro.images) + [""] * n)[:n]
    intro.focals = (list(intro.focals) + [[] for _ in range(n)])[:n]
    intro.credits = (list(intro.credits) + [{} for _ in range(n)])[:n]


def _discard_portrait(channel: Channel, rel: str) -> None:
    """Delete a portrait file, unless another cast row still points at it."""
    if not rel or rel in channel.intro.images:
        return
    path = channel_dir(channel.id) / rel
    if path.is_file():
        path.unlink(missing_ok=True)


def remove_cast(channel: Channel, index: int) -> str:
    """Drop one cast member: the name, the portrait, the focus and the credit."""
    intro = channel.intro
    align_cast(intro)
    if not 0 <= index < len(intro.subjects):
        raise IndexError("No cast member at that position.")
    subject = intro.subjects[index]
    rel = intro.images[index]
    for arr in (intro.subjects, intro.images, intro.focals, intro.credits):
        arr.pop(index)
    _discard_portrait(channel, rel)
    return subject


def portrait_options(subject: str, limit: int = 12) -> list[dict]:
    """Portraits that could stand in for one cast member, best first."""
    from . import media

    found = media.search([subject, f"{subject} portrait"], "image", limit=limit,
                         allow_stock=False)
    # Same preference the casting pass uses: a face reads best in a tall frame.
    found.sort(key=lambda c: (c.score + (0.6 if c.height >= c.width else 0)),
               reverse=True)
    return [c.to_dict() for c in found]


def set_portrait(channel: Channel, index: int, cand: dict,
                 progress: Progress = lambda m: None) -> str:
    """Put one candidate into one cast slot. Returns the channel-relative path.

    The file is named for nothing in particular on purpose. `col01`-style stems
    are positional, and positions move when a cast member is removed, so reusing
    them here would eventually overwrite a portrait another row still points at.
    """
    from . import media

    intro = channel.intro
    align_cast(intro)
    if not 0 <= index < len(intro.subjects):
        raise IndexError("No cast member at that position.")
    d = channel_dir(channel.id) / "intro"
    stem = f"cast_{uuid.uuid4().hex[:10]}"
    rel = media.download_to(media.upgrade(dict(cand)), d, stem)
    previous = intro.images[index]
    intro.images[index] = f"intro/{Path(rel).name}"
    intro.credits[index] = {"subject": intro.subjects[index],
                            "title": cand.get("title", ""),
                            "author": cand.get("author", ""),
                            "license": cand.get("license", ""),
                            "source_page": cand.get("source_page", "")}
    # The old focus point was measured on a different picture.
    intro.focals[index] = []
    _discard_portrait(channel, previous)
    progress(f"“{intro.subjects[index]}” recast")
    return intro.images[index]


def adopt_portrait(channel: Channel, index: int, data: bytes, suffix: str,
                   filename: str = "") -> str:
    """Put the creator's own image into one cast slot."""
    intro = channel.intro
    align_cast(intro)
    if not 0 <= index < len(intro.subjects):
        raise IndexError("No cast member at that position.")
    d = channel_dir(channel.id) / "intro"
    d.mkdir(parents=True, exist_ok=True)
    name = f"cast_{uuid.uuid4().hex[:10]}{suffix}"
    (d / name).write_bytes(data)
    previous = intro.images[index]
    intro.images[index] = f"intro/{name}"
    intro.credits[index] = {"subject": intro.subjects[index],
                            "title": filename or name, "author": "you",
                            "license": "your own file", "source_page": ""}
    intro.focals[index] = []
    _discard_portrait(channel, previous)
    return intro.images[index]


def resolve_images(channel: Channel, progress: Progress = lambda m: None) -> list[str]:
    """Find and cache one portrait per subject. Returns channel-relative paths."""
    from . import media

    d = channel_dir(channel.id) / "intro"
    subjects = channel.intro.subjects
    if not subjects:
        raise ValueError("This channel has no intro subjects yet.")

    paths: list[str] = []
    credits: list[dict] = []
    for n, subject in enumerate(subjects, 1):
        progress(f"Casting {n}/{len(subjects)}: {subject}")
        found = media.search([subject, f"{subject} portrait"], "image", limit=8,
                             allow_stock=False)
        # A face works best in a tall column, so prefer the tallest usable frame.
        found.sort(key=lambda c: (c.score + (0.6 if c.height >= c.width else 0)),
                   reverse=True)
        saved = False
        for cand in found[:4]:
            try:
                # This one is being kept, so it earns the full-size rendition.
                rel = media.download_to(media.upgrade(cand.to_dict()), d, f"col{n:02d}")
            except Exception as exc:
                progress(f"  couldn't fetch {cand.provider} option: {str(exc)[:70]}")
                continue
            paths.append(f"intro/{Path(rel).name}")
            credits.append({"subject": subject, "title": cand.title,
                            "author": cand.author, "license": cand.license,
                            "source_page": cand.source_page})
            saved = True
            break
        if not saved:
            # An empty slot rather than a short list: `images` is read against
            # `subjects` by index, so skipping one here would shift every face
            # after it onto the wrong name.
            paths.append("")
            credits.append({"subject": subject})
            progress(f"  ! no usable portrait for “{subject}”")

    channel.intro.images = paths
    channel.intro.credits = credits
    # Focal points are per-image; a re-cast invalidates the old ones.
    channel.intro.focals = [[] for _ in paths]
    progress(f"Cast {len([p for p in paths if p])} of {len(subjects)} columns")
    return paths


# ------------------------------------------------------------------- drawing
def _ease_out_cubic(p: float) -> float:
    return 1 - (1 - p) ** 3


def _ease_in_out(p: float) -> float:
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def _clamp01(p: float) -> float:
    return 0.0 if p < 0 else (1.0 if p > 1 else p)


def _fade(t: float, start: float, length: float) -> float:
    """0 before `start`, easing to 1 over `length` seconds."""
    return _ease_out_cubic(_clamp01((t - start) / max(0.01, length)))


def _squeeze(duration: float, start: float, span: float, tail: float = 0.3) -> float:
    """Scale factor that keeps a `span`-second sequence inside the slate.

    The knobs are independent of length, so a slow setting on a short slate can
    ask for more seconds than there are. Everything that has to be on screen at
    the end is scaled by this rather than being allowed to run off the end.
    """
    room = duration - start - tail
    return 1.0 if span <= room else max(0.15, room / max(0.01, span))


def _encode(out_path: Path, frames: Iterable[Image.Image],
            what: str = "the intro") -> None:
    """Pipe RGB frames through ffmpeg into an h264 file."""
    if not ffutil.encode_frames(frames, out_path):
        raise RuntimeError(f"ffmpeg failed encoding {what}")


def _cast_files(channel: Channel) -> tuple[list[Path], list[list[float] | None]]:
    """The portraits on disk for this channel, with their focal points."""
    root = channel_dir(channel.id)
    focals = channel.intro.focals or []
    out: list[Path] = []
    out_focals: list[list[float] | None] = []
    for i, rel in enumerate(channel.intro.images):
        if not rel:
            continue        # a subject nothing was found for; not a file
        p = root / rel
        if p.is_file():
            out.append(p)
            out_focals.append(focals[i] if i < len(focals) else None)
    if len(out) < 2:
        raise ValueError("This slate needs at least two cast images. "
                         "Add subjects and fetch their portraits first.")
    return out, out_focals


def _seed(channel: Channel) -> int:
    """A stable per-channel number, so a slate looks the same on every render."""
    return int(hashlib.md5(channel.id.encode()).hexdigest()[:8], 16)


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: float) -> float:
    if not text:
        return 0.0
    return sum(draw.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)


def _fit_tracked(text: str, stack, max_w: int, tracking: float, cap: int = 190) -> tuple:
    """Largest size at which `text` still fits the measure at this letter-spacing."""
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    size = cap
    while size > 26:
        font = titles._load(stack, size)
        if _tracked_width(probe, text, font, tracking) <= max_w:
            return font, size
        size -= 3
    return titles._load(stack, 26), 26


def _elide(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> str:
    text = text.strip()
    while text and draw.textlength(text, font=font) > max_w and len(text) > 8:
        text = text[:-2]
    return text


def _grain(n: int = 5, sigma: float = 20.0) -> list[Image.Image]:
    """A few half-res noise fields to cycle, so film grain costs one resize."""
    return [Image.effect_noise((WIDTH // 2, HEIGHT // 2), sigma) for _ in range(n)]


def _column(path: Path, width: int, height: int, grade: str,
            focal: list[float] | None = None) -> Image.Image:
    """Crop one portrait to a column, keeping the subject's face in the frame."""
    img = Image.open(path).convert("RGB")
    # Overscale before cropping. Archive scans usually carry a mat or a border,
    # and cutting 8% off every edge removes it without touching the face.
    scale = max(width / img.width, height / img.height) * 1.09
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                     Image.LANCZOS)

    if focal and len(focal) == 2:
        fx = min(1.0, max(0.0, focal[0]))
        fy = min(1.0, max(0.0, focal[1]))
        left = round(min(max(fx * img.width - width / 2, 0), img.width - width))
        top = round(min(max(fy * img.height - height / 2, 0), img.height - height))
    else:
        left = (img.width - width) // 2
        # Faces sit above centre in most portraits, so favour the top third.
        top = int((img.height - height) * 0.28) if img.height > height else 0
    img = img.crop((left, top, left + width, top + height))

    if grade == "mono":
        img = ImageEnhance.Color(img).enhance(0.0)
    else:
        img = ImageEnhance.Color(img).enhance(0.55)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Brightness(img).enhance(0.82)
    return img


def _title_layer(channel: Channel, video_title: str) -> Image.Image:
    """The series name, rule and video subtitle, centred, on transparency."""
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    name_font = titles._load(titles.FONT_STACK, 104)
    tag_font = titles._load(titles.KICKER_STACK, 22)
    accent = titles._hex(channel.style.accent)

    cy = HEIGHT // 2
    name = channel.name
    nw = d.textlength(name, font=name_font)
    ascent, _ = name_font.getmetrics()
    d.text(((WIDTH - nw) / 2, cy - ascent + 14), name, font=name_font,
           fill=(255, 255, 255, 255))

    rule_w = 78
    d.rectangle([(WIDTH - rule_w) / 2, cy - 96, (WIDTH + rule_w) / 2, cy - 93], fill=accent)

    if channel.tagline:
        tw = d.textlength(channel.tagline.upper(), font=tag_font)
        titles._tracked(d, ((WIDTH - tw - 22) / 2, cy - 148), channel.tagline.upper(),
                        tag_font, (255, 255, 255, 165), 3.0)
    return layer


def _subtitle_layer(channel: Channel, video_title: str) -> Image.Image:
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if not (video_title and channel.intro.show_video_title):
        return layer
    d = ImageDraw.Draw(layer)
    font = titles._load(titles.KICKER_STACK, 32)
    text = video_title.strip()
    while d.textlength(text, font=font) > WIDTH - 320 and len(text) > 12:
        text = text[:-2]
    tw = d.textlength(text, font=font)
    d.text(((WIDTH - tw) / 2, HEIGHT // 2 + 52), text, font=font,
           fill=(255, 255, 255, 205))
    return layer


def _shadowed(layer: Image.Image) -> Image.Image:
    """Composite a blurred black copy under the type so it holds over photos."""
    alpha = layer.split()[3].filter(ImageFilter.GaussianBlur(12)).point(lambda v: int(v * 0.85))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    return Image.alpha_composite(shadow, layer)


# ------------------------------------------------------------ signal template
# Glyphs the decode effect cycles through before a character settles.
_SCRAMBLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&$@/\\|<>+=*"

GRID_STEP = 60


def _grid(accent: tuple[int, int, int, int]) -> Image.Image:
    """A faint technical grid, one tile larger than the frame so it can drift."""
    w, h = WIDTH + GRID_STEP, HEIGHT + GRID_STEP
    img = Image.new("RGB", (w, h), (7, 8, 11))
    d = ImageDraw.Draw(img)
    for x in range(0, w, GRID_STEP):
        d.line([(x, 0), (x, h)], fill=(18, 21, 27))
    for y in range(0, h, GRID_STEP):
        d.line([(0, y), (w, y)], fill=(18, 21, 27))
    # Brighter nodes every fourth intersection, tinted with the channel accent.
    node = tuple(int(c * 0.35) for c in accent[:3])
    for x in range(0, w, GRID_STEP * 4):
        for y in range(0, h, GRID_STEP * 4):
            d.rectangle([x - 1, y - 1, x + 1, y + 1], fill=node)
    return img


def _wordmark_lines(name: str, upper: bool = True) -> list[str]:
    """Break a channel name into one or two balanced lines, upper-case by default."""
    name = name.upper() if upper else name
    words = [w for w in name.split() if w]
    if len(words) <= 1:
        return words or [name]
    if len(words) == 2:
        return words
    # Split at the point that makes the two lines closest in length.
    best, best_gap = 1, 10 ** 9
    for cut in range(1, len(words)):
        a = len(" ".join(words[:cut]))
        b = len(" ".join(words[cut:]))
        if abs(a - b) < best_gap:
            best, best_gap = cut, abs(a - b)
    return [" ".join(words[:best]), " ".join(words[best:])]


def _fit_display(lines: list[str], max_w: int, max_h: int, cap: int = 320,
                 stack: list | None = None):
    """Largest display size that fits the measure *and* the vertical space.

    Fitting to the frame rather than to a fixed size is what makes the wordmark
    fill the slate: a short name gets set enormous, a long one steps down.
    """
    stack = stack or titles.DISPLAY_STACK
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    size = cap
    while size > 48:
        font = titles._load(stack, size)
        widest = max(probe.textlength(l, font=font) for l in lines)
        ascent, descent = font.getmetrics()
        block = int(size * 0.86) * (len(lines) - 1) + ascent + descent
        if widest <= max_w and block <= max_h:
            return font, size
        size -= 4
    return titles._load(titles.DISPLAY_STACK, 48), 48


def _sheen(accent: tuple[int, int, int, int]) -> Image.Image:
    """A narrow vertical shine that crosses the frame once, after the landing."""
    w = 300
    band = Image.new("L", (w, HEIGHT), 0)
    px = band.load()
    for x in range(w):
        v = 1 - abs((x / w) * 2 - 1)
        a = int(120 * v ** 3)
        for y in range(0, HEIGHT, 3):
            px[x, y] = a
            if y + 1 < HEIGHT:
                px[x, y + 1] = a
            if y + 2 < HEIGHT:
                px[x, y + 2] = a
    out = Image.new("RGBA", (w, HEIGHT), (255, 255, 255, 0))
    out.putalpha(band)
    return out


def _glow(accent: tuple[int, int, int, int], w: int, h: int) -> Image.Image:
    """A soft accent bloom that sits behind the wordmark and breathes."""
    g = Image.new("L", (w // 8, h // 8), 0)
    d = ImageDraw.Draw(g)
    d.ellipse([-g.width // 6, g.height // 6, g.width, g.height * 5 // 6], fill=110)
    g = g.filter(ImageFilter.GaussianBlur(14)).resize((w, h), Image.BILINEAR)
    bloom = Image.new("RGBA", (w, h), accent[:3] + (0,))
    bloom.putalpha(g)
    return bloom


def _rgb_split(frame: Image.Image, dx: int) -> Image.Image:
    """Offset the red and blue channels: two frames of this reads as impact."""
    r, g, b = frame.split()
    return Image.merge("RGB", (ImageChops.offset(r, dx, 0), g,
                               ImageChops.offset(b, -dx, 0)))


def _render_signal(channel: Channel, video_title: str, out_path: Path,
                   progress: Progress) -> float:
    """A kinetic type slate: the wordmark is wiped in by a travelling accent bar.

    Built for channels about technology rather than biography, where there is no
    cast of faces to show. The name is set large and left-aligned in a heavy
    display face; an accent bar sweeps across each line and leaves the letters
    behind it, and the frame takes a two-frame channel split on each landing.
    """
    spec = channel.intro
    accent = titles._hex(channel.style.accent)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    MARGIN = 132
    lines = _wordmark_lines(channel.name)
    # Fit to the frame: the wordmark should own the slate, not float in it.
    font, size = _fit_display(lines, WIDTH - MARGIN - 96, HEIGHT - 430)
    ascent, descent = font.getmetrics()
    leading = int(size * 0.86)

    block_h = leading * (len(lines) - 1) + ascent + descent
    # Centre the whole group (kicker above, video title below), not just the
    # wordmark, or the block reads as sitting high in the frame.
    KICKER_SPACE, SUB_SPACE = 74, 96
    top = (HEIGHT - (KICKER_SPACE + block_h + SUB_SPACE)) // 2 + KICKER_SPACE

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    line_w = [probe.textlength(l, font=font) for l in lines]

    # Each line is drawn once into its own full-frame layer, so revealing it is
    # a crop-and-paste rather than a redraw.
    layers, bounds = [], []
    for i, line in enumerate(lines):
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((MARGIN, top + i * leading), line,
                                   font=font, fill=(255, 255, 255, 255))
        layers.append(_shadowed(layer))
        bounds.append((top + i * leading, top + i * leading + ascent + descent))

    kicker_font = titles._load(titles.MONO_LIGHT_STACK, 21)
    sub_font = titles._load(titles.MONO_LIGHT_STACK, 27)

    grid = _grid(accent)
    glow = _glow(accent, WIDTH, block_h + 260)
    sheen = _sheen(accent)

    # Timeline. The UI's stagger and fly-duration drive the reveal.
    wipe = max(0.18, min(1.2, spec.fly_duration * 0.7))
    gap = max(0.06, min(0.6, spec.stagger * 2.2))
    line_start = [0.42 + i * gap for i in range(len(lines))]
    line_end = [s + wipe for s in line_start]
    settled = max(line_end)
    sub_in = settled + 0.30
    bar_w = max(8, size // 16)

    proc = ffutil.frame_pipe(out_path)

    try:
        for f in range(n_frames):
            t = f / FPS
            drift = int((t * 26) % GRID_STEP)
            frame = grid.crop((drift, drift, drift + WIDTH, drift + HEIGHT)).copy()

            # Bloom behind the type, breathing slowly so the hold stays alive.
            pulse = 0.42 + 0.14 * math.sin(t * 1.9)
            if t > 0.2:
                bl = glow.copy()
                bl.putalpha(bl.split()[3].point(lambda v: int(v * pulse)))
                frame.paste(Image.new("RGB", bl.size, accent[:3]),
                            (0, top - 130), bl)

            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)

            # Vertical anchor rule down the left margin, drawing top to bottom.
            if t > 0.12:
                p = min(1.0, (t - 0.12) / 0.5)
                y0, y1 = top - 74, top + block_h + 96
                d.rectangle([MARGIN - 34, y0, MARGIN - 30,
                             y0 + (y1 - y0) * _ease_out_cubic(p)], fill=accent)

            # Kicker, snapping in against a solid accent tick.
            if channel.tagline and t > 0.22:
                a = int(200 * min(1.0, (t - 0.22) / 0.28))
                ky = top - 62
                d.rectangle([MARGIN, ky + 5, MARGIN + 15, ky + 18],
                            fill=accent[:3] + (a,))
                titles._tracked(d, (MARGIN + 27, ky), channel.tagline.upper(),
                                kicker_font, (255, 255, 255, a), 3.6)

            impact = False
            for i in range(len(lines)):
                if t < line_start[i]:
                    continue
                p = min(1.0, (t - line_start[i]) / wipe)
                eased = _ease_out_cubic(p)
                reveal = int(MARGIN + line_w[i] * eased)
                y0, y1 = bounds[i]

                # Letters appear behind the travelling bar.
                shown = layers[i].crop((0, y0 - 12, reveal, y1 + 12))
                layer.paste(shown, (0, y0 - 12), shown)

                if p < 1.0:
                    d.rectangle([reveal, y0 + 2, reveal + bar_w, y1 - 2], fill=accent)
                elif t - line_end[i] < 2.0 / FPS:
                    impact = True

            # Video title, bottom left, under a thin rule.
            if video_title and spec.show_video_title and t > sub_in:
                a = int(215 * min(1.0, (t - sub_in) / 0.4))
                ty = top + block_h + 4
                d.rectangle([MARGIN, ty, MARGIN + 54, ty + 2],
                            fill=accent[:3] + (a,))
                text = video_title.strip()
                while probe.textlength(text, font=sub_font) > WIDTH - MARGIN - 160 \
                        and len(text) > 12:
                    text = text[:-2]
                d.text((MARGIN, ty + 18), text, font=sub_font,
                       fill=(255, 255, 255, a))

            # A hairline at the very bottom that fills as the slate plays.
            d.rectangle([0, HEIGHT - 3, WIDTH * (t / duration), HEIGHT - 1],
                        fill=accent[:3] + (150,))

            frame = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")

            # One shine across the finished wordmark, straight after it lands.
            sp = (t - settled - 0.03) / 0.42
            if 0.0 <= sp <= 1.0:
                x = int(-sheen.width + sp * (WIDTH + sheen.width))
                frame.paste(Image.new("RGB", sheen.size, (255, 255, 255)), (x, 0), sheen)

            if impact:
                frame = _rgb_split(frame, 7)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed encoding the intro (exit {code})")

    progress(f"Signal slate rendered: {duration:.1f}s, {n_frames} frames, "
             f"{len(lines)} line(s) at {size}px")
    return duration


# ----------------------------------------------------------- dossier template
def _paper() -> Image.Image:
    """A near-black card with a faint tooth, so the frame is never dead flat."""
    base = Image.new("RGB", (WIDTH, HEIGHT), (10, 10, 12))
    noise = Image.effect_noise((WIDTH // 2, HEIGHT // 2), 26) \
        .resize((WIDTH, HEIGHT), Image.BILINEAR)
    tex = noise.point(lambda v: max(0, v - 132) // 5)
    return ImageChops.add(base, Image.merge("RGB", (tex, tex, tex)))


def _stamp(text: str, accent) -> Image.Image:
    """A rubber stamp: tracked mono inside a double rule, rotated off-square."""
    font = titles._load(titles.MONO_STACK, 34)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    w = int(_tracked_width(probe, text, font, 6.0)) + 80
    h = 108
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([2, 2, w - 3, h - 3], outline=accent[:3] + (235,), width=5)
    d.rectangle([14, 14, w - 15, h - 15], outline=accent[:3] + (105,), width=2)
    titles._tracked(d, (40, h / 2 - 24), text, font, accent[:3] + (245,), 6.0)
    # Rubbed edges: coarse noise eats into the ink the way a real stamp does.
    speckle = Image.effect_noise((w, h), 78).point(lambda v: 255 if v > 104 else 96)
    layer.putalpha(ImageChops.multiply(layer.split()[3], speckle))
    return layer.rotate(-8, resample=Image.BICUBIC, expand=True)


def _render_dossier(channel: Channel, video_title: str, out_path: Path,
                    progress: Progress) -> float:
    """A case file being opened: typed mono, redactions sliding off, a stamp.

    For channels that investigate rather than narrate. Nothing moves fast: the
    card rules itself in, the metadata types, and the series name is uncovered
    by bars that slide off the type rather than a wipe.
    """
    spec = channel.intro
    accent = titles._hex(channel.style.accent)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    M, INSET = 152, 60
    lines = _wordmark_lines(channel.name)
    font, size = _fit_display(lines, WIDTH - 2 * M - 60, 300, cap=190,
                              stack=titles.CONDENSED_STACK)
    ascent, descent = font.getmetrics()
    leading = int(size * 0.94)
    block_h = leading * (len(lines) - 1) + ascent + descent

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    line_w = [probe.textlength(l, font=font) for l in lines]

    mono = titles._load(titles.MONO_LIGHT_STACK, 23)
    mono_bold = titles._load(titles.MONO_STACK, 21)
    sub_font = titles._load(titles.MONO_LIGHT_STACK, 27)
    char_w = probe.textlength("M", font=mono)

    seed = _seed(channel)
    code = f"{seed % 9000 + 1000}-{chr(65 + seed % 26)}"
    subject = (channel.tagline or channel.concept or channel.name).upper()
    meta = [f"FILE No.  {code}",
            f"SUBJECT   {_elide(probe, subject, mono, 620)}",
            "STATUS    DECLASSIFIED"]

    has_sub = bool(video_title and spec.show_video_title)
    meta_h = 34 * len(meta)
    group = 92 + block_h + 40 + meta_h + (86 if has_sub else 0)
    top = max(INSET + 78, (HEIGHT - group) // 2)
    header_y, name_top = top, top + 92
    meta_top = name_top + block_h + 40
    sub_y = meta_top + meta_h + 46

    name_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    nd = ImageDraw.Draw(name_layer)
    for i, line in enumerate(lines):
        nd.text((M, name_top + i * leading), line, font=font, fill=(244, 242, 236, 255))

    paper = _paper()
    stamp = _stamp("DECLASSIFIED", accent)

    # Timeline: rules, then typing, then the redactions come off.
    type_start = 0.30
    type_rate = max(9.0, 30.0 / max(0.25, spec.fly_duration))     # characters/sec
    bars_show = 0.40
    gap = max(0.08, min(0.8, spec.stagger * 2.6))
    bar_len = max(0.28, min(1.4, spec.fly_duration * 1.2))
    k = _squeeze(duration, 0.62, gap * (len(lines) - 1) + bar_len + 0.38 + 0.4)
    gap, bar_len, type_rate = gap * k, bar_len * k, type_rate / k
    bar_start = [0.62 + i * gap for i in range(len(lines))]
    stamp_at = max(bar_start) + bar_len + 0.12 * k
    sub_at = stamp_at + 0.26 * k

    def frames():
        for f in range(n_frames):
            t = f / FPS
            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)

            # The card rules itself in, one side at a time, clockwise.
            edge = accent[:3] + (120,)
            x0, y0, x1, y1 = INSET, INSET, WIDTH - INSET, HEIGHT - INSET
            p = _clamp01((t - 0.08) / 0.9) * 4
            if p > 0:
                d.rectangle([x0, y0, x0 + (x1 - x0) * min(1, p), y0 + 2], fill=edge)
            if p > 1:
                d.rectangle([x1 - 2, y0, x1, y0 + (y1 - y0) * min(1, p - 1)], fill=edge)
            if p > 2:
                d.rectangle([x1 - (x1 - x0) * min(1, p - 2), y1 - 2, x1, y1], fill=edge)
            if p > 3:
                d.rectangle([x0, y1 - (y1 - y0) * min(1, p - 3), x0 + 2, y1], fill=edge)

            a = int(230 * _fade(t, 0.18, 0.3))
            if a:
                d.rectangle([M, header_y, M + 46, header_y + 3], fill=accent[:3] + (a,))
                titles._tracked(d, (M, header_y + 20), "CASE FILE", mono_bold,
                                (255, 255, 255, a), 5.5)

            # Metadata types itself out, line after line, with a blinking caret.
            budget = int(max(0.0, t - type_start) * type_rate)
            y = meta_top
            for row in meta:
                if budget <= 0:
                    break
                shown = row[:budget]
                d.text((M, y), shown, font=mono, fill=(212, 212, 206, 235))
                if len(shown) < len(row) and int(t * 2.6) % 2 == 0:
                    cx = M + char_w * len(shown)
                    d.rectangle([cx + 2, y + 4, cx + char_w - 2, y + 26],
                                fill=accent[:3] + (220,))
                budget -= len(row)
                y += 34

            # Redaction bars slide right off the name, uncovering it as they go.
            if t >= bars_show:
                layer.paste(name_layer, (0, 0), name_layer)
                for i in range(len(lines)):
                    ly0 = name_top + i * leading - 12
                    ly1 = ly0 + ascent + descent + 14
                    travel = line_w[i] + 46
                    bx = M - 16
                    if t > bar_start[i]:
                        bx += travel * _ease_in_out(_clamp01((t - bar_start[i]) / bar_len))
                    if bx < M + line_w[i] + 22:
                        # Lighter than the card, not darker: a true black bar
                        # would be invisible on a black slate.
                        box = [bx, ly0, bx + line_w[i] + 30, ly1]
                        d.rectangle(box, fill=(26, 26, 31, 255))
                        d.rectangle(box, outline=accent[:3] + (110,), width=2)

            if t > sub_at and has_sub:
                text = _elide(probe, video_title, sub_font, WIDTH - 2 * M - 300)
                shown = text[:int((t - sub_at) * 26)]
                d.rectangle([M, sub_y, M + 54, sub_y + 2], fill=accent[:3] + (200,))
                d.text((M, sub_y + 22), shown, font=sub_font, fill=(255, 255, 255, 215))
                if int(t * 2.6) % 2 == 0:
                    cx = M + probe.textlength(shown, font=sub_font)
                    d.rectangle([cx + 3, sub_y + 26, cx + 16, sub_y + 52],
                                fill=accent[:3] + (220,))

            frame = Image.alpha_composite(paper.convert("RGBA"), layer)

            # The stamp lands last, punched on with a little overshoot.
            if t > stamp_at:
                sp = _clamp01((t - stamp_at) / 0.26)
                scale = 1.55 - 0.55 * _ease_out_cubic(sp)
                sw, sh = max(1, int(stamp.width * scale)), max(1, int(stamp.height * scale))
                sc = stamp.resize((sw, sh), Image.BICUBIC)
                alpha = int(255 * min(1.0, sp * 1.8))
                sc.putalpha(sc.split()[3].point(lambda v: v * alpha // 255))
                frame.paste(sc, (WIDTH - 300 - sw // 2, HEIGHT - 268 - sh // 2), sc)

            yield frame.convert("RGB")

    _encode(out_path, frames())
    progress(f"Dossier slate rendered: {duration:.1f}s, file {code}, "
             f"{len(lines)} redaction(s) at {size}px")
    return duration


# --------------------------------------------------------- filmstrip template
def _sprockets(band_top: int, band_h: int, accent) -> Image.Image:
    """Film base: matte bands with punched perforations above and below."""
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    base = (9, 9, 11, 255)
    d.rectangle([0, 0, WIDTH, band_top], fill=base)
    d.rectangle([0, band_top + band_h, WIDTH, HEIGHT], fill=base)
    for x in range(22, WIDTH, 96):
        for cy in (band_top - 44, band_top + band_h + 44):
            d.rounded_rectangle([x, cy - 14, x + 46, cy + 14], radius=6,
                                fill=(31, 32, 37, 255))
    d.rectangle([0, band_top - 3, WIDTH, band_top - 1], fill=accent[:3] + (95,))
    d.rectangle([0, band_top + band_h + 1, WIDTH, band_top + band_h + 3],
                fill=accent[:3] + (95,))
    return layer


def _render_filmstrip(channel: Channel, video_title: str, out_path: Path,
                      progress: Progress) -> float:
    """The cast runs past as a sprocketed strip that slows to a stop.

    Where the columns template flies each face in from the left, this one keeps
    a single continuous piece of film moving: grain, gate flicker and a little
    weave, then the strip parks and the series name comes up over it.
    """
    spec = channel.intro
    accent = titles._hex(channel.style.accent)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))
    sources, focals = _cast_files(channel)

    CELL_W, CELL_H, GAP = 306, 664, 14
    pitch = CELL_W + GAP
    band_top = (HEIGHT - CELL_H) // 2
    # How much film runs past, and how long it takes to stop, are the two knobs.
    travel = WIDTH * (0.55 + max(0.03, min(0.30, spec.stagger)) * 7.0)
    n_cells = int((WIDTH + travel) // pitch) + 3

    # One long piece of film, built once; every frame is a crop of it. Taller
    # than the frame by the weave amplitude so the gate wander has somewhere to go.
    strip = Image.new("RGB", (n_cells * pitch, HEIGHT + 16), (6, 6, 8))
    cut: dict[int, Image.Image] = {}
    for i in range(n_cells):
        k = i % len(sources)
        if k not in cut:
            cut[k] = _column(sources[k], CELL_W, CELL_H, channel.style.grade, focals[k])
        strip.paste(cut[k], (i * pitch, band_top + 8))
    progress(f"Filmstrip: {n_cells} frames cut from {len(sources)} portraits")

    sprockets = _sprockets(band_top + 14, CELL_H - 28, accent)
    grains = _grain(6, 24)
    rnd = random.Random(_seed(channel))
    flicker = [1.0 - rnd.random() * 0.07 for _ in range(n_frames)]
    weave = [rnd.randint(0, 16) for _ in range(n_frames)]

    settle = max(1.0, min(duration * 0.8, duration * 0.56 * (spec.fly_duration / 0.62)))
    title_in = settle + 0.16

    # The title block is drawn once; only its rules and opacity animate.
    cy = HEIGHT // 2
    name_font, name_size = _fit_display([channel.name], WIDTH - 620, 150, cap=104,
                                        stack=titles.FONT_STACK)
    tag_font = titles._load(titles.KICKER_STACK, 22)
    sub_font = titles._load(titles.MONO_LIGHT_STACK, 26)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    text_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    nw = probe.textlength(channel.name, font=name_font)
    n_asc, _ = name_font.getmetrics()
    td.text(((WIDTH - nw) / 2, cy - n_asc + 16), channel.name, font=name_font,
            fill=(255, 255, 255, 255))
    if channel.tagline:
        tw = _tracked_width(probe, channel.tagline.upper(), tag_font, 3.4)
        titles._tracked(td, ((WIDTH - tw) / 2, cy - 138), channel.tagline.upper(),
                        tag_font, (255, 255, 255, 175), 3.4)
    if video_title and spec.show_video_title:
        text = _elide(probe, video_title, sub_font, WIDTH - 520)
        td.text(((WIDTH - probe.textlength(text, font=sub_font)) / 2, cy + 118),
                text, font=sub_font, fill=(255, 255, 255, 200))
    text_layer = _shadowed(text_layer)
    dark = Image.new("RGB", (WIDTH, HEIGHT), (6, 7, 10))

    def frames():
        for f in range(n_frames):
            t = f / FPS
            ox = int(travel * (1 - _ease_out_cubic(_clamp01(t / settle))))
            wy = weave[f] if t < settle else 8
            frame = strip.crop((ox, wy, ox + WIDTH, wy + HEIGHT)).copy()
            frame = Image.alpha_composite(frame.convert("RGBA"), sprockets).convert("RGB")

            if flicker[f] < 0.995:
                frame = ImageEnhance.Brightness(frame).enhance(flicker[f])
            g = grains[f % len(grains)].resize((WIDTH, HEIGHT), Image.BILINEAR) \
                .point(lambda v: max(0, v - 128) // 6)
            frame = ImageChops.add(frame, Image.merge("RGB", (g, g, g)))

            if t > title_in:
                a = _fade(t, title_in, 0.55)
                frame = Image.blend(frame, dark, 0.66 * a)
                lit = Image.alpha_composite(frame.convert("RGBA"), text_layer)
                frame = Image.blend(frame, lit.convert("RGB"), a)
                # Two rules open outward from the centre, bracketing the name.
                rule = int(320 * _ease_out_cubic(_clamp01((t - title_in) / 0.7)))
                d = ImageDraw.Draw(frame)
                for y in (cy - 96, cy + 88):
                    d.rectangle([WIDTH / 2 - rule, y, WIDTH / 2 + rule, y + 2],
                                fill=accent[:3])
            yield frame

    _encode(out_path, frames())
    progress(f"Filmstrip slate rendered: {duration:.1f}s, name at {name_size}px")
    return duration


# ------------------------------------------------------------ mosaic template
def _render_mosaic(channel: Channel, video_title: str, out_path: Path,
                   progress: Progress) -> float:
    """A wall of faces that builds tile by tile, then a band opens across it.

    Columns are orderly and left to right; this is deliberately not. Tiles land
    in a shuffled order, each shrinking into place, and a short cast is padded
    out with numbered graphic blocks so the grid never repeats a face twice in a row.
    """
    spec = channel.intro
    accent = titles._hex(channel.style.accent)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))
    sources, focals = _cast_files(channel)

    cols = max(3, min(6, spec.columns))
    rows = 3
    tw, th = WIDTH // cols, HEIGHT // rows
    cells = []
    for r in range(rows):
        for c in range(cols):
            cells.append((c * tw, r * th,
                          tw + (WIDTH - tw * cols if c == cols - 1 else 0),
                          th + (HEIGHT - th * rows if r == rows - 1 else 0)))

    rnd = random.Random(_seed(channel))
    order = list(range(len(cells)))
    rnd.shuffle(order)

    def block(w: int, h: int, n: int) -> Image.Image:
        """A graphic tile, for when the cast is shorter than the grid."""
        im = Image.new("RGB", (w, h), (12, 13, 16))
        d = ImageDraw.Draw(im)
        d.rectangle([7, 7, w - 8, h - 8],
                    outline=tuple(int(v * 0.40) for v in accent[:3]), width=2)
        f = titles._load(titles.MONO_STACK, 30)
        titles._tracked(d, (26, h - 58), f"{n:02d}", f,
                        tuple(int(v * 0.85) for v in accent[:3]), 4.0)
        return im

    # Who goes where is decided by grid position, not by the landing order: the
    # diagonal walk means neither the cell to the right nor the one below holds
    # the same portrait, even when the whole cast is two people.
    n = len(sources)
    who = [((r * (cols + 1)) + c) % n for r in range(rows) for c in range(cols)]
    # A fifth of the wall at most goes to graphic blocks, which is what keeps a
    # short cast from reading as one face on repeat.
    for ci in order[:max(0, min(len(cells) // 5, len(cells) - n))]:
        who[ci] = -1

    seen: dict[int, int] = {}
    tiles: list[Image.Image] = [None] * len(cells)      # type: ignore[list-item]
    for ci, (x, y, w, h) in enumerate(cells):
        k = who[ci]
        if k < 0:
            tiles[ci] = block(w, h, ci + 1)
            continue
        rep = seen.get(k, 0)
        seen[k] = rep + 1
        focal, grade = focals[k], channel.style.grade
        if rep:
            # Later passes over the cast are cropped lower and printed black and
            # white, so a repeat reads as another plate rather than the same tile.
            fx, fy = (focal[0], focal[1]) if focal and len(focal) == 2 else (0.5, 0.32)
            focal = [fx, min(0.86, fy + 0.13 * min(rep, 2))]
            grade = "mono" if rep % 2 else grade
        tiles[ci] = _column(sources[k], w, h, grade, focal)
    n_blocks = sum(1 for k in who if k < 0)
    progress(f"Mosaic: {cols}×{rows} tiles, {len(cells) - n_blocks} faces, "
             f"{n_blocks} blocks")

    gap = max(0.03, min(0.26, spec.stagger))
    pop = max(0.16, min(0.8, spec.fly_duration * 0.55))
    k = _squeeze(duration, 0.0, (len(cells) - 1) * gap + pop + 0.42 + 0.45)
    gap, pop = gap * k, pop * k
    complete = (len(cells) - 1) * gap + pop
    band_at = complete + 0.18 * k
    text_at = band_at + 0.24 * k
    BAND_H = 264

    base = Image.new("RGB", (WIDTH, HEIGHT), (8, 8, 10))
    dark = Image.new("RGB", (WIDTH, HEIGHT), (7, 8, 10))

    cy = HEIGHT // 2
    name_font, name_size = _fit_display([channel.name], WIDTH - 520, 130, cap=96,
                                        stack=titles.FONT_STACK)
    _cap = name_font.getbbox("H")
    name_dy = -(_cap[1] + _cap[3]) / 2   # centre the capitals, not the em box
    tag_font = titles._load(titles.KICKER_STACK, 21)
    sub_font = titles._load(titles.MONO_LIGHT_STACK, 26)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    wall: Image.Image | None = None      # cached once every tile has landed

    def frames():
        nonlocal wall
        for f in range(n_frames):
            t = f / FPS
            if wall is not None:
                frame = wall.copy()
            else:
                frame = base.copy()
                landed = 0
                for rank, ci in enumerate(order):
                    p = _clamp01((t - rank * gap) / pop)
                    if p <= 0:
                        continue
                    x, y, w, h = cells[ci]
                    if p >= 1:
                        landed += 1
                        frame.paste(tiles[ci], (x, y))
                        continue
                    # Each tile drops in slightly oversized and shrinks to fit,
                    # so the grid is never seen through a gap.
                    e = _ease_out_cubic(p)
                    s = 1.0 + 0.18 * (1 - e)
                    sw, sh = int(w * s), int(h * s)
                    im = tiles[ci].resize((sw, sh), Image.BILINEAR)
                    ox, oy = (sw - w) // 2, (sh - h) // 2
                    im = im.crop((ox, oy, ox + w, oy + h))
                    frame.paste(Image.blend(Image.new("RGB", (w, h), (8, 8, 10)), im, e),
                                (x, y))
                if landed == len(cells):
                    d = ImageDraw.Draw(frame)
                    for c in range(1, cols):
                        d.rectangle([c * tw - 1, 0, c * tw, HEIGHT], fill=accent[:3])
                    for r in range(1, rows):
                        d.rectangle([0, r * th - 1, WIDTH, r * th], fill=accent[:3])
                    wall = frame.copy()

            if t > band_at:
                bp = _ease_out_cubic(_clamp01((t - band_at) / 0.45))
                frame = Image.blend(frame, dark, 0.46 * bp)
                half = int(BAND_H / 2 * bp)
                if half > 2:
                    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
                    d = ImageDraw.Draw(layer)
                    d.rectangle([0, cy - half, WIDTH, cy + half], fill=(7, 8, 11, 238))
                    d.rectangle([0, cy - half, WIDTH, cy - half + 3], fill=accent)
                    d.rectangle([0, cy + half - 3, WIDTH, cy + half], fill=accent)

                    a = int(255 * _fade(t, text_at, 0.4))
                    if a:
                        nw = probe.textlength(channel.name, font=name_font)
                        d.text(((WIDTH - nw) / 2, cy + name_dy - 16), channel.name,
                               font=name_font, fill=(255, 255, 255, a))
                        if channel.tagline:
                            tag = channel.tagline.upper()
                            twid = _tracked_width(probe, tag, tag_font, 3.4)
                            titles._tracked(d, ((WIDTH - twid) / 2, cy - 98), tag,
                                            tag_font, (255, 255, 255, int(a * 0.7)), 3.4)
                    # The video title rides inside the band too: below it the
                    # wall's own furniture would be reading through the type.
                    if video_title and spec.show_video_title:
                        sa = int(210 * _fade(t, text_at + 0.2, 0.4))
                        if sa and half > BAND_H / 2 - 2:
                            text = _elide(probe, video_title, sub_font, WIDTH - 520)
                            d.text(((WIDTH - probe.textlength(text, font=sub_font)) / 2,
                                    cy + 62), text, font=sub_font,
                                   fill=(255, 255, 255, sa))
                    frame = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")
            yield frame

    _encode(out_path, frames())
    progress(f"Mosaic slate rendered: {duration:.1f}s, {len(cells)} tiles, "
             f"name at {name_size}px")
    return duration


# ------------------------------------------------------------- pulse template
def _vgrad(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    col = Image.new("RGB", (1, HEIGHT))
    px = col.load()
    for y in range(HEIGHT):
        k = y / (HEIGHT - 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3))
    return col.resize((WIDTH, HEIGHT), Image.BILINEAR)


def _render_pulse(channel: Channel, video_title: str, out_path: Path,
                  progress: Progress) -> float:
    """The name's letter-spacing collapses into place over a live spectrum.

    A slate for shows that are listened to as much as watched. The only motion
    on the type is tracking — no wipe, no fly-in — while a mirrored bar spectrum
    runs underneath and spikes on the landing.
    """
    spec = channel.intro
    accent = titles._hex(channel.style.accent)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    name = channel.name.upper()
    TRACK_OPEN, TRACK_SET = 44.0, 9.0
    font, size = _fit_tracked(name, titles.KICKER_STACK, WIDTH - 300, TRACK_OPEN, cap=132)
    tag_font = titles._load(titles.MONO_STACK, 20)
    sub_font = titles._load(titles.MONO_LIGHT_STACK, 26)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    advances = [probe.textlength(c, font=font) for c in name]
    adv_sum = sum(advances)
    asc, _ = font.getmetrics()

    # `name_y` is the text top; everything else is placed off the ascent so the
    # tagline and the rules never crowd the wordmark, whatever size it lands at.
    name_y = int(HEIGHT * 0.40)
    base_y = int(HEIGHT * 0.755)
    tag_y = name_y - 118
    rule_top, rule_bot = name_y - 56, name_y + asc + 30
    sub_y = rule_bot + 34

    N = 108
    rnd = random.Random(_seed(channel))
    liveliness = max(0.03, min(0.30, spec.stagger)) / 0.13
    phase = [rnd.uniform(0, 6.283) for _ in range(N)]
    speed = [(1.7 + rnd.random() * 3.6) * liveliness for _ in range(N)]
    # Taller in the middle of the frame, so the spectrum reads as one shape.
    weight = [0.30 + 0.70 * math.sin(math.pi * (i + 0.5) / N) ** 0.75 for i in range(N)]
    bar_w = WIDTH / N

    lock_at = 0.34
    lock_len = max(0.35, min(1.6, spec.fly_duration * 1.6))
    k = _squeeze(duration, lock_at, lock_len + 0.28 + 0.4)
    lock_len = lock_len * k
    landed = lock_at + lock_len
    sub_at = landed + 0.28 * k
    bg = _vgrad((13, 14, 19), (5, 5, 7))

    def frames():
        for f in range(n_frames):
            t = f / FPS
            frame = bg.copy()
            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)

            # Envelope: rises, spikes as the name locks, settles to an idle.
            env = 0.55 * _fade(t, 0.12, 0.5)
            if t > landed:
                env += 0.85 * math.exp(-(t - landed) * 3.4)
            env = min(1.25, env)
            for i in range(N):
                v = 0.5 + 0.5 * math.sin(t * speed[i] * 3.2 + phase[i])
                h = 5 + 188 * weight[i] * v * env
                x = i * bar_w
                d.rectangle([x + 2, base_y - h, x + bar_w - 3, base_y + h],
                            fill=accent[:3] + (150,))
            # The baseline draws outward from the centre before the bars matter.
            half = WIDTH / 2 * _ease_out_cubic(_clamp01(t / 0.45))
            d.rectangle([WIDTH / 2 - half, base_y - 1, WIDTH / 2 + half, base_y + 1],
                        fill=accent[:3] + (215,))

            if channel.tagline:
                a = int(190 * _fade(t, 0.16, 0.4))
                if a:
                    tag = channel.tagline.upper()
                    twid = _tracked_width(probe, tag, tag_font, 6.0)
                    titles._tracked(d, ((WIDTH - twid) / 2, tag_y), tag,
                                    tag_font, (255, 255, 255, a), 6.0)

            # Tracking is the whole move: wide open, closing to a set line.
            p = _ease_out_cubic(_clamp01((t - lock_at) / lock_len))
            track = TRACK_OPEN + (TRACK_SET - TRACK_OPEN) * p
            a = int(255 * min(1.0, _clamp01((t - lock_at) / (lock_len * 0.55))))
            if a:
                total = adv_sum + track * (len(name) - 1)
                x = (WIDTH - total) / 2
                for ch, w in zip(name, advances):
                    d.text((x, name_y), ch, font=font, fill=(255, 255, 255, a))
                    x += w + track

            # Two rules chase the type outward and stop where it settles.
            if t > lock_at:
                rw = 300 * _ease_out_cubic(_clamp01((t - lock_at) / (lock_len + 0.2)))
                for y in (rule_top, rule_bot):
                    d.rectangle([WIDTH / 2 - rw, y, WIDTH / 2 + rw, y + 2],
                                fill=accent[:3] + (170,))

            if video_title and spec.show_video_title:
                sa = int(215 * _fade(t, sub_at, 0.4))
                if sa:
                    text = _elide(probe, video_title, sub_font, WIDTH - 520)
                    d.text(((WIDTH - probe.textlength(text, font=sub_font)) / 2,
                            sub_y), text, font=sub_font, fill=(255, 255, 255, sa))

            yield Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")

    _encode(out_path, frames())
    progress(f"Pulse slate rendered: {duration:.1f}s, wordmark at {size}px")
    return duration


# ------------------------------------------------------------- atlas template
def _contour_map(accent, seed: int, pad: int) -> Image.Image:
    """Topographic country: a graticule with two ranges of contour lines."""
    w, h = WIDTH + pad, HEIGHT + pad
    img = Image.new("RGB", (w, h), (6, 7, 9))
    d = ImageDraw.Draw(img)
    for x in range(0, w, 160):
        d.line([(x, 0), (x, h)], fill=(15, 17, 21))
    for y in range(0, h, 160):
        d.line([(0, y), (w, y)], fill=(15, 17, 21))

    rnd = random.Random(seed)
    tint = tuple(int(c * 0.30) for c in accent[:3])
    for cx, cy, base, rings in ((w * 0.26, h * 0.66, 78, 15), (w * 0.72, h * 0.30, 62, 12)):
        ph = [rnd.uniform(0, 6.283) for _ in range(3)]
        for k in range(rings):
            r = base + k * 44
            pts = []
            for deg in range(0, 361, 6):
                th = math.radians(deg)
                wob = (1 + 0.17 * math.sin(3 * th + ph[0] + k * 0.28)
                       + 0.09 * math.sin(5 * th + ph[1] - k * 0.19)
                       + 0.05 * math.sin(8 * th + ph[2]))
                pts.append((cx + r * wob * math.cos(th) * 1.32, cy + r * wob * math.sin(th)))
            major = k % 5 == 0
            shade = 24 + k
            d.line(pts, fill=tint if major else (shade, shade + 3, shade + 6),
                   width=2 if major else 1)
    return img


def _render_atlas(channel: Channel, video_title: str, out_path: Path,
                  progress: Progress) -> float:
    """A crosshair crosses contour country, locks on, and opens onto the title.

    Made for series about places and expeditions. The frame is a map that never
    stops drifting; the only hard move is the reticle, which scrambles its
    coordinates until it settles and then unfolds into the wordmark.
    """
    spec = channel.intro
    accent = titles._hex(channel.style.accent)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    PAD = 120
    seed = _seed(channel)
    board = _contour_map(accent, seed, PAD)
    mono = titles._load(titles.MONO_STACK, 22)
    mono_l = titles._load(titles.MONO_LIGHT_STACK, 26)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    lat, lon = seed % 78 + 5, seed // 78 % 168 + 5
    coord = f"{lat:02d}°{seed % 60:02d}′N   {lon:03d}°{seed // 60 % 60:02d}′E"

    name = channel.name.upper()
    font, size = _fit_tracked(name, titles.CONDENSED_STACK, WIDTH - 520, 8.0, cap=128)
    name_w = _tracked_width(probe, name, font, 8.0)
    # Centre on the capitals rather than the em box, or the wordmark sits low
    # between the brackets by however much descender room the face carries.
    _cap = font.getbbox("H")
    cap_dy = -(_cap[1] + _cap[3]) / 2
    tag_font = titles._load(titles.MONO_STACK, 19)

    x0, y0 = WIDTH * 0.80, HEIGHT * 0.22
    tx, ty = WIDTH * 0.5, HEIGHT * 0.47
    fly_at = 0.22
    fly_len = max(0.5, min(2.0, spec.fly_duration * 2.0))
    k = _squeeze(duration, fly_at, fly_len + 0.70 + 0.45)
    fly_len = fly_len * k
    lock = fly_at + fly_len
    open_at = lock + 0.22 * k
    text_at = open_at + 0.18 * k
    sub_at = text_at + 0.30 * k
    rnd = random.Random(seed)
    drift_rate = max(0.03, min(0.30, spec.stagger)) * 70

    def frames():
        for f in range(n_frames):
            t = f / FPS
            drift = int((t * drift_rate) % PAD)
            frame = board.crop((drift, drift, drift + WIDTH, drift + HEIGHT)).copy()
            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)

            p = _ease_in_out(_clamp01((t - fly_at) / fly_len))
            cx, cy = x0 + (tx - x0) * p, y0 + (ty - y0) * p
            box = 460 - 250 * p
            # The reticle hands the frame over: it fades as the brackets unfold,
            # so the readout is never left sitting across the wordmark.
            handover = 1 - _fade(t, open_at, 0.45)
            a = int(235 * _fade(t, fly_at, 0.25) * handover)

            # The scope lines stay, faintly, as the ground the title sits on.
            scope = int(70 * _fade(t, fly_at, 0.25) * (0.32 + 0.68 * handover))
            d.rectangle([0, cy - 1, WIDTH, cy], fill=accent[:3] + (scope,))
            d.rectangle([cx - 1, 0, cx, HEIGHT], fill=accent[:3] + (scope,))

            if a:
                arm = box * 0.22
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        bx, by = cx + sx * box / 2, cy + sy * box / 2
                        d.rectangle([min(bx, bx - sx * arm), by - 2,
                                     max(bx, bx - sx * arm), by], fill=accent[:3] + (a,))
                        d.rectangle([bx - 2, min(by, by - sy * arm),
                                     bx, max(by, by - sy * arm)], fill=accent[:3] + (a,))
                d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=accent[:3] + (a,), width=2)

                # The readout only stops scrambling once the reticle stops.
                text = coord
                if t < lock:
                    text = "".join(str(rnd.randrange(10)) if c.isdigit() else c
                                   for c in coord)
                titles._tracked(d, (cx + box / 2 + 22, cy - 12), text, mono,
                                (255, 255, 255, a), 2.4)
                if t >= lock:
                    tag_a = int(255 * (0.55 + 0.45 * math.sin(t * 9)))
                    d.rectangle([cx - box / 2 - 74, cy - 14, cx - box / 2 - 22, cy + 14],
                                outline=accent[:3] + (tag_a,), width=2)
                    titles._tracked(d, (cx - box / 2 - 64, cy - 10), "LK", mono,
                                    accent[:3] + (tag_a,), 2.0)

            # The brackets unfold sideways and hand the frame to the wordmark.
            if t > open_at:
                op = _ease_out_cubic(_clamp01((t - open_at) / 0.55))
                half = (box / 2) + (name_w / 2 + 70 - box / 2) * op
                for y in (cy - 112, cy + 112):
                    d.rectangle([cx - half, y, cx + half, y + 2],
                                fill=accent[:3] + (200,))
                na = int(255 * _fade(t, text_at, 0.45))
                if na:
                    rise = 16 * (1 - _fade(t, text_at, 0.45))
                    titles._tracked(d, (cx - name_w / 2, cy + cap_dy + rise),
                                    name, font, (255, 255, 255, na), 8.0)
                if channel.tagline:
                    ta = int(190 * _fade(t, text_at + 0.12, 0.4))
                    if ta:
                        tag = channel.tagline.upper()
                        tw = _tracked_width(probe, tag, tag_font, 5.0)
                        titles._tracked(d, (cx - tw / 2, cy - 96), tag, tag_font,
                                        (255, 255, 255, ta), 5.0)

            if video_title and spec.show_video_title:
                sa = int(215 * _fade(t, sub_at, 0.4))
                if sa:
                    text = _elide(probe, video_title, mono_l, WIDTH - 560)
                    d.text((cx - probe.textlength(text, font=mono_l) / 2, cy + 132),
                           text, font=mono_l, fill=(255, 255, 255, sa))

            yield Image.alpha_composite(frame.convert("RGBA"),
                                        _shadowed(layer)).convert("RGB")

    _encode(out_path, frames())
    progress(f"Atlas slate rendered: {duration:.1f}s, locked on {coord}, "
             f"wordmark at {size}px")
    return duration


# ------------------------------------------------------------- folio template
def _paper_page() -> Image.Image:
    """A sheet of cream stock: printed tooth, and a wash so it isn't a flat fill."""
    paper = Image.new("RGB", (WIDTH, HEIGHT), (238, 233, 222))
    noise = Image.effect_noise((WIDTH // 2, HEIGHT // 2), 15) \
        .resize((WIDTH, HEIGHT), Image.BILINEAR)
    tex = noise.point(lambda v: max(0, v - 118) // 7)
    paper = ImageChops.subtract(paper, Image.merge("RGB", (tex, tex, tex)))
    vig = Image.new("L", (WIDTH // 8, HEIGHT // 8), 0)
    ImageDraw.Draw(vig).ellipse([-vig.width * 0.22, -vig.height * 0.3,
                                 vig.width * 1.22, vig.height * 1.3], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(9)).resize((WIDTH, HEIGHT), Image.BILINEAR)
    return Image.composite(paper, Image.new("RGB", (WIDTH, HEIGHT), (207, 200, 186)), vig)


def _turn_bands() -> tuple[Image.Image, Image.Image]:
    """The shadow the incoming sheet casts, and the catch of light on its edge."""
    sw = 150
    row = Image.new("L", (sw, 1))
    row.putdata([int(165 * (x / sw) ** 2.4) for x in range(sw)])
    shadow = Image.new("RGBA", (sw, HEIGHT), (26, 22, 18, 0))
    shadow.putalpha(row.resize((sw, HEIGHT), Image.BILINEAR))

    hw = 90
    row = Image.new("L", (hw, 1))
    row.putdata([int(96 * (1 - x / hw) ** 2.0) for x in range(hw)])
    sheen = Image.new("RGBA", (hw, HEIGHT), (255, 252, 244, 0))
    sheen.putalpha(row.resize((hw, HEIGHT), Image.BILINEAR))
    return shadow, sheen


def _roman(n: int) -> str:
    out, n = "", max(1, n)
    for value, sign in ((100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"),
                        (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= value:
            out += sign
            n -= value
    return out


def _render_folio(channel: Channel, video_title: str, out_path: Path,
                  progress: Progress) -> float:
    """A printed title page: the sheet turns in, then the type sets itself.

    The only slate that runs on cream rather than black, which is most of why it
    reads as a book channel before a word of it is legible. Baskerville centred
    on a classic title-page measure, a lozenge ornament between the name and the
    video's own title in italic, and a roman folio at the foot.
    """
    spec = channel.intro
    accent = titles._hex(channel.style.accent)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    INK = (32, 29, 26)
    # The channel accent is mixed for black slates; on paper it has to be printed
    # darker or the rules disappear into the stock.
    RULE = tuple(int(c * 0.52) for c in accent[:3])

    lines = _wordmark_lines(channel.name, upper=False)
    name_font, size = _fit_display(lines, WIDTH - 660, 300, cap=148,
                                   stack=titles.SERIF_STACK)
    ascent, descent = name_font.getmetrics()
    leading = int(size * 1.06)
    block_h = leading * (len(lines) - 1) + ascent + descent

    kick_font = titles._load(titles.SMALLCAPS_STACK, 26)
    sub_font = titles._load(titles.SERIF_ITALIC_STACK, 34)
    folio_font = titles._load(titles.SERIF_STACK, 24)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    has_kick = bool(channel.tagline)
    has_sub = bool(video_title and spec.show_video_title)
    kick_h = 62 if has_kick else 0
    sub_h = 74 if has_sub else 0
    group = 96 + kick_h + block_h + 92 + sub_h + 96
    top = (HEIGHT - group) // 2

    y_rule_top = top + 40
    y_kick = y_rule_top + 46
    y_name = y_kick + kick_h
    y_orn = y_name + block_h + 46
    y_sub = y_orn + 44
    y_rule_bot = y_sub + sub_h + 40
    folio = _roman(_seed(channel) % 24 + 1)

    page = _paper_page()
    # What the sheet slides over is the page beneath, not a dark board: a slate
    # that cuts into the video shouldn't flash black before it turns cream.
    beneath = ImageEnhance.Brightness(page).enhance(0.86)
    shadow, sheen = _turn_bands()

    # Timeline: the sheet is laid down, the rules rule, then the type sets in
    # reading order — kicker, name, ornament, video title.
    turn_at = 0.10
    turn = max(0.4, min(2.2, spec.fly_duration * 1.6))
    gap = max(0.08, min(0.7, spec.stagger * 2.4))
    k = _squeeze(duration, turn_at, turn + 0.35 + 3 * gap + 0.5)
    turn, gap = turn * k, gap * k
    landed = turn_at + turn
    rules_at = landed + 0.10 * k
    beats = [rules_at + 0.25 * k + i * gap for i in range(4)]

    def rule_pair(d, y: int, half: float, alpha: int) -> None:
        """A thick rule with a hairline under it, the way a title page sets them."""
        d.rectangle([WIDTH / 2 - half, y, WIDTH / 2 + half, y + 3], fill=RULE + (alpha,))
        d.rectangle([WIDTH / 2 - half * 0.72, y + 9, WIDTH / 2 + half * 0.72, y + 10],
                    fill=RULE + (int(alpha * 0.8),))

    def frames():
        for f in range(n_frames):
            t = f / FPS
            p = _ease_out_cubic(_clamp01((t - turn_at) / turn))
            edge = int(WIDTH * (1 - p))

            if edge <= 0:
                frame = page.copy()
            else:
                frame = beneath.copy()
                frame.paste(page.crop((edge, 0, WIDTH, HEIGHT)), (edge, 0))
                frame.paste(Image.new("RGB", sheen.size, (255, 252, 244)),
                            (edge, 0), sheen)
                frame.paste(Image.new("RGB", shadow.size, (26, 22, 18)),
                            (edge - shadow.width, 0), shadow)
                ImageDraw.Draw(frame).rectangle([edge, 0, edge + 1, HEIGHT],
                                                fill=(150, 141, 124))

            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)

            if t > rules_at:
                rp = _ease_out_cubic(_clamp01((t - rules_at) / 0.6))
                rule_pair(d, y_rule_top, 300 * rp, 230)
                rule_pair(d, y_rule_bot, 300 * rp, 230)

            def rise(beat: int) -> tuple[int, float]:
                k = _fade(t, beats[beat], 0.5)
                return int(255 * k), 10 * (1 - k)

            if has_kick:
                a, dy = rise(0)
                if a:
                    tag = channel.tagline.upper()
                    tw = _tracked_width(probe, tag, kick_font, 5.0)
                    titles._tracked(d, ((WIDTH - tw) / 2, y_kick + dy), tag,
                                    kick_font, INK + (int(a * 0.8),), 5.0)

            a, dy = rise(1)
            if a:
                for i, line in enumerate(lines):
                    lw = probe.textlength(line, font=name_font)
                    d.text(((WIDTH - lw) / 2, y_name + i * leading + dy), line,
                           font=name_font, fill=INK + (a,))

            a, _ = rise(2)
            if a:
                cx = WIDTH / 2
                d.rectangle([cx - 105, y_orn - 1, cx - 26, y_orn + 1], fill=RULE + (a,))
                d.rectangle([cx + 26, y_orn - 1, cx + 105, y_orn + 1], fill=RULE + (a,))
                d.polygon([(cx, y_orn - 9), (cx + 11, y_orn), (cx, y_orn + 9),
                           (cx - 11, y_orn)], fill=RULE + (a,))

            if has_sub:
                a, dy = rise(3)
                if a:
                    text = _elide(probe, video_title, sub_font, WIDTH - 720)
                    d.text(((WIDTH - probe.textlength(text, font=sub_font)) / 2,
                            y_sub + dy), text, font=sub_font, fill=INK + (int(a * 0.88),))

            if t > beats[3] + 0.2:
                a = int(150 * _fade(t, beats[3] + 0.2, 0.5))
                fw = probe.textlength(folio, font=folio_font)
                d.text(((WIDTH - fw) / 2, HEIGHT - 116), folio, font=folio_font,
                       fill=INK + (a,))

            yield Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")

    _encode(out_path, frames())
    progress(f"Folio slate rendered: {duration:.1f}s, {len(lines)} line(s) at "
             f"{size}px, folio {folio}")
    return duration


# -------------------------------------------------------------------- render
def _render_columns(channel: Channel, video_title: str, out_path: Path,
                    progress: Progress) -> float:
    """The original slate: portraits fly in as columns, then the series title."""
    spec = channel.intro
    root = channel_dir(channel.id)
    sources = [root / rel for rel in spec.images]
    sources = [p for p in sources if p.exists()]
    if len(sources) < 2:
        raise ValueError("This channel's intro needs at least two cast images. "
                         "Add subjects and fetch their portraits first.")

    n_cols = max(2, min(8, spec.columns))
    # Reuse the cast cyclically if there are fewer portraits than columns.
    order = [i % len(sources) for i in range(n_cols)]
    picks = [sources[i] for i in order]
    focals = [(spec.focals[i] if i < len(spec.focals) else None) for i in order]

    col_w = (WIDTH - GUTTER * (n_cols - 1)) // n_cols
    leftover = WIDTH - (col_w * n_cols + GUTTER * (n_cols - 1))
    progress(f"Building {n_cols} columns at {col_w}px")

    columns = [_column(p, col_w + (leftover if i == n_cols - 1 else 0), HEIGHT,
                       channel.style.grade, focals[i])
               for i, p in enumerate(picks)]
    targets = [i * (col_w + GUTTER) for i in range(n_cols)]

    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))
    settle = spec.stagger * (n_cols - 1) + spec.fly_duration
    title_in = settle + SETTLE_PAD
    title_len = 0.55
    sub_in = title_in + 0.42
    scrim_len = 0.7

    accent = titles._hex(channel.style.accent)
    black = Image.new("RGB", (WIDTH, HEIGHT), (7, 8, 11))
    scrim = Image.new("RGB", (WIDTH, HEIGHT), (6, 7, 10))
    title = _shadowed(_title_layer(channel, video_title))
    subtitle = _shadowed(_subtitle_layer(channel, video_title))

    settled: Image.Image | None = None    # cached once every column has landed
    settled_scrimmed: Image.Image | None = None

    proc = ffutil.frame_pipe(out_path)

    try:
        for f in range(n_frames):
            t = f / FPS

            if settled is not None:
                frame = settled
            else:
                frame = black.copy()
                landed = 0
                for i, col in enumerate(columns):
                    p = (t - i * spec.stagger) / spec.fly_duration
                    p = 0.0 if p < 0 else (1.0 if p > 1 else p)
                    if p <= 0:
                        continue
                    eased = _ease_out_cubic(p)
                    x = round(targets[i] - (targets[i] + col.width) * (1 - eased))
                    frame.paste(col, (x, 0))
                    if p >= 1:
                        landed += 1
                if landed == n_cols:
                    # Nothing moves from here on, so draw the furniture once.
                    d = ImageDraw.Draw(frame)
                    for i in range(1, n_cols):
                        x = targets[i] - GUTTER
                        d.rectangle([x, 0, x + GUTTER - 1, HEIGHT], fill=accent[:3])
                    settled = frame
                    settled_scrimmed = Image.blend(frame, scrim, 0.62)

            if t >= title_in and settled is not None:
                a_scrim = min(1.0, (t - title_in + 0.15) / scrim_len)
                base = Image.blend(settled, settled_scrimmed, a_scrim)

                a_title = min(1.0, max(0.0, (t - title_in) / title_len))
                if a_title > 0:
                    lit = Image.alpha_composite(base.convert("RGBA"), title)
                    base = Image.blend(base, lit.convert("RGB"), a_title)

                a_sub = min(1.0, max(0.0, (t - sub_in) / title_len))
                if a_sub > 0:
                    lit = Image.alpha_composite(base.convert("RGBA"), subtitle)
                    base = Image.blend(base, lit.convert("RGB"), a_sub)
                frame = base

            proc.stdin.write(frame.tobytes())

        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed encoding the intro (exit {code})")

    progress(f"Intro slate rendered: {duration:.1f}s, {n_frames} frames")
    return duration


# ============================================================================

def _dial_face(pal, ground, accent, size: int, seed: int) -> Image.Image:
    """The dial as its own round object on a transparent square, side `size`.

    Kept separate from the frame so the slate can push in on it, crop it and
    slide it about. Everything here is fixed for the whole shot — the hands are
    the only part that moves, and they are drawn later, in frame coordinates.
    """
    R = size // 2
    face = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    plate = Image.new("RGB", (size, size), ground[:3])

    # Sunburst: a soleil dial is brushed radially, so the light runs out from
    # the centre in spokes rather than across the face.
    burst = Image.new("L", (size, size), 0)
    bd = ImageDraw.Draw(burst)
    rnd = random.Random(seed)
    for i in range(900):
        a = i * math.pi / 450
        v = 118 + int(74 * math.sin(a * 9 + seed % 7)) + rnd.randint(-24, 24)
        bd.line([R, R, R + math.cos(a) * R * 1.02, R + math.sin(a) * R * 1.02],
                fill=max(0, min(255, v)), width=2)
    burst = burst.filter(ImageFilter.GaussianBlur(0.7))

    lift = 40 if not pal.light else -26
    pd = ImageDraw.Draw(plate)
    for y in range(size):
        k = 1 - abs(y - R * 0.72) / (size * 1.05)
        pd.line([0, y, size, y],
                fill=tuple(max(0, min(255, int(g + lift * k))) for g in ground[:3]))
    plate = Image.composite(
        Image.new("RGB", plate.size, tuple(
            max(0, min(255, int(g + (34 if not pal.light else -20)))) for g in ground[:3])),
        plate, burst.point(lambda v: int(v * 0.52)))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    face.paste(plate, (0, 0), mask)

    d = ImageDraw.Draw(face)
    cx = cy = R

    # Chapter ring: every minute a hairline, every fifth longer and heavier.
    r_out = R * 0.955
    for m in range(60):
        a = math.radians(m * 6 - 90)
        five = m % 5 == 0
        r_in = r_out - (R * 0.058 if five else R * 0.027)
        d.line([cx + math.cos(a) * r_in, cy + math.sin(a) * r_in,
                cx + math.cos(a) * r_out, cy + math.sin(a) * r_out],
               fill=accent[:3] + (255 if five else 150,),
               width=max(2, int(R * 0.009)) if five else max(1, int(R * 0.004)))

    # Applied batons, doubled at twelve, omitted at three for the date.
    r_i = r_out - R * 0.103
    baton = R * 0.121
    for h in range(12):
        if h == 3:
            continue
        a = math.radians(h * 30 - 90)
        ux, uy = math.cos(a), math.sin(a)
        px, py = -uy, ux
        for off in ((-R * 0.020, R * 0.020) if h == 0 else (0,)):
            bx, by = cx + px * off, cy + py * off
            half = R * (0.0134 if h == 0 else 0.0156)
            d.polygon([
                (bx + ux * r_i + px * half, by + uy * r_i + py * half),
                (bx + ux * r_i - px * half, by + uy * r_i - py * half),
                (bx + ux * (r_i - baton) - px * half, by + uy * (r_i - baton) - py * half),
                (bx + ux * (r_i - baton) + px * half, by + uy * (r_i - baton) + py * half),
            ], fill=accent[:3] + (236,))

    # The date aperture the missing baton makes room for.
    dx, dy = cx + (r_i - R * 0.060), cy
    w, hgt = R * 0.094, R * 0.067
    d.rounded_rectangle([dx - w, dy - hgt, dx + w, dy + hgt], radius=int(R * 0.012),
                        fill=tuple(max(0, min(255, g + (48 if not pal.light else -32)))
                                   for g in ground[:3]) + (255,),
                        outline=accent[:3] + (175,), width=max(1, int(R * 0.005)))
    d.text((dx, dy), f"{seed % 28 + 1}",
           font=titles._load(titles.CONDENSED_STACK, max(12, int(R * 0.098))),
           fill=pal.ink[:3] + (238,), anchor="mm")

    # The bezel, with a soft inner glow so the edge reads as polished metal.
    for i in range(int(R * 0.032)):
        k = 1 - i / max(1, R * 0.032)
        d.ellipse([i, i, size - 1 - i, size - 1 - i],
                  outline=accent[:3] + (int(64 * k),), width=1)
    d.ellipse([1, 1, size - 2, size - 2], outline=accent[:3] + (205,),
              width=max(2, int(R * 0.008)))
    return face


def _dial_ground(pal, ground, accent, seed: int) -> Image.Image:
    """What the dial sits on: a dark bench with concentric machining and a wash.

    The first cut of this slate put the dial on flat black, which read as a
    cut-out rather than a photograph. The rings are what give the rest of the
    frame something to be.
    """
    base = Image.new("RGB", (WIDTH, HEIGHT), ground[:3])
    d = ImageDraw.Draw(base)
    lo = tuple(max(0, min(255, int(g * (0.55 if not pal.light else 1.06))))
               for g in ground[:3])
    hi = tuple(max(0, min(255, int(g + (26 if not pal.light else -16))))
               for g in ground[:3])
    for y in range(HEIGHT):
        k = y / HEIGHT
        d.line([0, y, WIDTH, y],
               fill=tuple(int(a + (b - a) * k) for a, b in zip(hi, lo)))

    # Concentric turning marks, struck from the same centre the dial will sit on
    # so the whole frame reads as one machined surface.
    rings = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rings)
    ox, oy = WIDTH * 0.68, HEIGHT * 0.5
    rnd = random.Random(seed ^ 0x5EED)
    r = 40.0
    while r < WIDTH * 1.6:
        a = int(26 + 16 * math.sin(r / 90.0)) + rnd.randint(-5, 5)
        rd.ellipse([ox - r, oy - r, ox + r, oy + r],
                   outline=accent[:3] + (max(0, a),), width=1)
        r *= 1.038
    # A second set from off the left edge, so the empty side of the frame is
    # machined too rather than being a black rectangle the type sits on.
    r = 60.0
    while r < WIDTH * 1.1:
        a = int(15 + 9 * math.sin(r / 130.0)) + rnd.randint(-4, 4)
        rd.ellipse([-WIDTH * 0.22 - r, HEIGHT * 0.30 - r,
                    -WIDTH * 0.22 + r, HEIGHT * 0.30 + r],
                   outline=accent[:3] + (max(0, a),), width=1)
        r *= 1.052
    base = Image.alpha_composite(base.convert("RGBA"),
                                 rings.filter(ImageFilter.GaussianBlur(0.5)))

    # A pool of light under where the dial will sit, so it is lit rather than
    # pasted on.
    glow = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(glow).ellipse(
        [ox - HEIGHT * 0.78, oy - HEIGHT * 0.78, ox + HEIGHT * 0.78, oy + HEIGHT * 0.78],
        fill=30)
    # Warm grey rather than the accent itself. Pasting a lifted gold across the
    # frame does not read as light on a dark bench, it reads as a colour cast:
    # #E8C36A brightened is very close to yellow, and the whole slate went olive.
    warm = tuple(int(g * 0.22 + 92) for g in accent[:3])
    base.paste(Image.new("RGB", (WIDTH, HEIGHT), warm),
               (0, 0), glow.filter(ImageFilter.GaussianBlur(240)))

    # A vignette, so the corners fall away and the dial is the lit thing.
    vig = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(vig).ellipse(
        [-WIDTH * 0.30, -HEIGHT * 0.55, WIDTH * 1.30, HEIGHT * 1.55], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(190)).point(lambda v: int((255 - v) * 0.72))
    base.paste(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)), (0, 0), vig)
    return base.convert("RGB")


def _hand(d, cx: float, cy: float, angle: float, length: float, width: float,
          colour, counter: float = 0.0, taper: float = 0.55) -> None:
    """One watch hand: a tapered baton with a short counterweight tail."""
    a = math.radians(angle - 90)
    ux, uy = math.cos(a), math.sin(a)
    px, py = -uy, ux
    tipw, basew = width * taper, width
    d.polygon([
        (cx + ux * length + px * tipw, cy + uy * length + py * tipw),
        (cx + ux * length - px * tipw, cy + uy * length - py * tipw),
        (cx - ux * counter - px * basew, cy - uy * counter - py * basew),
        (cx - ux * counter + px * basew, cy - uy * counter + py * basew),
    ], fill=colour)


def _render_dial(channel: Channel, video_title: str, out_path: Path,
                 progress: Progress) -> float:
    """A watch dial, shot close and pushed in on, with the title over it.

    The dial is the picture, not the page: it is bigger than the frame, cropped
    by it, and set off to the right so the type has somewhere of its own to be.
    It pushes in for the whole slate, which is what keeps the shot alive once
    the hands have arrived.

    The hands still settle at ten past ten. That position is why the wordmark
    can sit where it does — at any other hour the minute hand sweeps up through
    the left of the frame and straight across the type.
    """
    spec = channel.intro
    pal = themes.palette(channel.style)
    accent, ground, ink = pal.accent, pal.ground, pal.ink
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))
    seed = _seed(channel)

    bench = _dial_ground(pal, ground, accent, seed)
    # Rendered once at the largest it will ever be drawn, then scaled down per
    # frame. Drawing the face 165 times would cost more than the whole slate.
    DIAL_MAX = int(HEIGHT * 1.30)
    face = _dial_face(pal, ground, accent, DIAL_MAX, seed)

    cx_d, cy_d = WIDTH * 0.68, HEIGHT * 0.50
    # The move settles a little short of the end rather than running to the last
    # frame: the seconds hand carries the shot from there, so the dial arriving
    # early costs nothing and reads as a camera coming to rest.
    r_start = HEIGHT * 0.621            # where it begins, close on the dial
    r_end = HEIGHT * 0.515              # and where it comes to rest
    settle = 0.88

    # Type. Left of the dial's centre, at a size that owns the frame rather than
    # sitting on the dial as printing.
    measure = int(cx_d - HEIGHT * 0.30 - WIDTH * 0.065)
    lines = _wordmark_lines(channel.name, upper=True)
    name_font, size = _fit_display(lines, measure, int(HEIGHT * 0.42), cap=170,
                                   stack=titles.DISPLAY_STACK)
    tag_font = titles._load(titles.SERIF_ITALIC_STACK, max(22, int(size * 0.26)))
    sub_font = titles._load(titles.SMALLCAPS_STACK, max(18, int(size * 0.20)))

    ascent, descent = name_font.getmetrics()
    leading = int(size * 0.88)
    block_h = leading * (len(lines) - 1) + ascent + descent
    x_type = int(WIDTH * 0.065)
    has_tag = bool(channel.tagline)
    has_sub = bool(video_title and spec.show_video_title)
    tag_h = int(size * 0.42) if has_tag else 0
    sub_h = int(size * 0.40) if has_sub else 0
    group = block_h + tag_h + sub_h + int(size * 0.22)
    y_top = (HEIGHT - group) // 2
    y_tag = y_top + block_h + int(size * 0.20)
    y_sub = y_tag + tag_h + int(size * 0.10)

    # A scrim under the type: the dial is busy where they meet, and type over a
    # chapter ring is unreadable however large it is set.
    scrim = Image.new("L", (WIDTH, HEIGHT), 0)
    sd = ImageDraw.Draw(scrim)
    edge = int(WIDTH * 0.62)
    for x in range(edge):
        sd.line([x, 0, x, HEIGHT], fill=int(214 * (1 - (x / edge) ** 1.7)))
    scrim = scrim.filter(ImageFilter.GaussianBlur(24))
    scrim_ink = Image.new("RGB", (WIDTH, HEIGHT),
                          tuple(int(g * 0.35) for g in ground[:3]) if not pal.light
                          else (250, 247, 240))

    travel = max(0.5, min(3.2, spec.fly_duration * 2.4))
    gap = max(0.06, min(0.5, spec.stagger * 1.6))
    k = _squeeze(duration, 0.10, travel + 0.5 + 2 * gap + 0.6)
    travel, gap = travel * k, gap * k
    start_at = 0.10
    landed = start_at + travel
    beats = [landed - 0.30 * k, landed + 0.02 * k + gap, landed + 0.02 * k + 2 * gap]

    HOUR_END, MIN_END = 10 * 30 + 10 * 0.5, 10 * 6

    def frames():
        for f in range(n_frames):
            t = f / FPS
            p = _ease_out_cubic(_clamp01((t - start_at) / travel))
            # The push-in runs the whole slate, not just the entrance: a shot
            # that arrives and then holds still dies on the last second.
            push = _ease_in_out(_clamp01(t / max(0.6, duration * settle)))
            R = r_start + (r_end - r_start) * push
            drift = (1 - push) * HEIGHT * 0.02

            frame = bench.copy()
            d_size = max(8, int(R * 2))
            scaled = face.resize((d_size, d_size), Image.LANCZOS)
            frame.paste(scaled, (int(cx_d - R), int(cy_d - R + drift)), scaled)

            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            hd = ImageDraw.Draw(layer)
            hy = cy_d + drift
            secs = 210 + 360 * (t / duration)
            _hand(hd, cx_d, hy, HOUR_END * p, R * 0.52, R * 0.026,
                  accent[:3] + (255,), counter=R * 0.10)
            _hand(hd, cx_d, hy, MIN_END * p, R * 0.76, R * 0.019,
                  accent[:3] + (255,), counter=R * 0.12)
            _hand(hd, cx_d, hy, secs, R * 0.80, R * 0.006,
                  pal.accent2[:3] + (235,), counter=R * 0.20, taper=1.0)
            hub = R * 0.030
            hd.ellipse([cx_d - hub, hy - hub, cx_d + hub, hy + hub],
                       fill=accent[:3] + (255,))
            hd.ellipse([cx_d - hub * 0.38, hy - hub * 0.38,
                        cx_d + hub * 0.38, hy + hub * 0.38], fill=ground[:3] + (255,))
            frame = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")

            # The type, over everything, behind its own scrim.
            a_name = _fade(t, beats[0], 0.6)
            if a_name > 0.01:
                frame.paste(scrim_ink, (0, 0),
                            scrim.point(lambda v: int(v * a_name)))
            tl = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            td = ImageDraw.Draw(tl)
            if a_name > 0.01:
                # Rising as it fades, so the title arrives rather than appears.
                rise = int((1 - a_name) * size * 0.16)
                for i, line in enumerate(lines):
                    td.text((x_type, y_top + i * leading + rise), line,
                            font=name_font, fill=ink[:3] + (int(255 * a_name),),
                            anchor="la")
                td.rectangle([x_type, y_top - int(size * 0.20),
                              x_type + int(measure * 0.42 * a_name),
                              y_top - int(size * 0.20) + max(2, int(size * 0.030))],
                             fill=accent[:3] + (int(255 * a_name),))
            if has_tag:
                a = _fade(t, beats[1], 0.5)
                if a > 0.01:
                    td.text((x_type, y_tag), channel.tagline, font=tag_font,
                            fill=accent[:3] + (int(235 * a),), anchor="la")
            if has_sub:
                a = _fade(t, beats[2], 0.5)
                if a > 0.01:
                    td.text((x_type, y_sub), video_title.upper(), font=sub_font,
                            fill=ink[:3] + (int(205 * a),), anchor="la")
            frame = Image.alpha_composite(frame.convert("RGBA"), tl).convert("RGB")
            yield frame

    _encode(out_path, frames(), what="the dial slate")
    progress(f"Dial slate rendered: {duration:.1f}s, wordmark at {size}px, "
             f"dial {r_start / r_end:.2f}x to 1.00x over {duration * settle:.1f}s, "
             f"hands at 10:10")
    return duration


# The theme-led slates. Everything above this line is built from one accent on
# black; everything below is built from a theme's pair of colours, its ground
# and its icons, so a gaming channel and a beauty channel do not open the same
# way with the gold swapped out. `columns` is reused as pattern density here,
# which is why the channel page relabels that slider per template.
# ============================================================================
def _ease_out_back(p: float, overshoot: float = 1.7) -> float:
    """Lands past the mark and settles back. The difference between a drop and a bounce."""
    p = _clamp01(p)
    c = overshoot + 1
    return 1 + c * (p - 1) ** 3 + overshoot * (p - 1) ** 2


def _shear(layer: Image.Image, k: float) -> Image.Image:
    """Slant a layer. Pillow has no oblique, and condensed caps want one."""
    w, h = layer.size
    pad = int(abs(k) * h) + 2
    wide = Image.new("RGBA", (w + pad * 2, h), (0, 0, 0, 0))
    wide.paste(layer, (pad, 0))
    return wide.transform(wide.size, Image.AFFINE, (1, k, -k * h, 0, 1, 0),
                          Image.BICUBIC)


def _scanlines(alpha: int = 34) -> Image.Image:
    """Every other line darkened. Two pixels of CRT for almost nothing."""
    line = Image.new("RGBA", (1, 4), (0, 0, 0, 0))
    line.putpixel((0, 2), (0, 0, 0, alpha))
    line.putpixel((0, 3), (0, 0, 0, alpha // 2))
    return line.resize((WIDTH, HEIGHT), Image.NEAREST)


def _density(spec, lo: int, hi: int) -> int:
    """The columns slider, reused as how tight a pattern is tiled."""
    k = (max(3, min(8, int(spec.columns))) - 3) / 5.0
    return int(hi + (lo - hi) * k)


def _outlined(text_layer: Image.Image, color, width: int) -> Image.Image:
    """A hard outline around a type layer, drawn by dilating its own alpha."""
    alpha = text_layer.split()[3]
    grown = alpha.filter(ImageFilter.MaxFilter(width * 2 + 1))
    ring = Image.new("RGBA", text_layer.size, tuple(color[:3]) + (0,))
    ring.putalpha(grown)
    return Image.alpha_composite(ring, text_layer)


# ----------------------------------------------------------- arcade template
def _render_arcade(channel: Channel, video_title: str, out_path: Path,
                   progress: Progress) -> float:
    """A cabinet attract screen: pattern scrolls, the wordmark drops and bounces.

    The two theme colours do all the work — one for the type, the other for the
    hard shadow behind it — over a field of the theme's own icons that never
    stops moving, because an arcade screen that holds still looks broken.
    """
    spec = channel.intro
    pal = themes.palette(channel.style)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    cell = _density(spec, 74, 150)
    ground = motifs.gradient((WIDTH, HEIGHT),
                             [motifs.mix(pal.ground, pal.accent2, 0.22), pal.ground,
                              motifs.mix(pal.ground, pal.accent, 0.30)], 118)
    # One field, twice as wide as the frame, scrolled under it forever.
    field = motifs.icon_field((WIDTH * 2, HEIGHT), pal.icons,
                              [pal.accent, pal.accent2, pal.ink], cell=cell,
                              alpha=46, angle=-14, seed=_seed(channel))
    scan = _scanlines()

    lines = _wordmark_lines(channel.name)
    font, size = _fit_display(lines, WIDTH - 260, 470, cap=250)
    leading = int(size * 0.86)
    asc, desc = font.getmetrics()
    block_h = leading * (len(lines) - 1) + asc + desc
    top = int(HEIGHT * 0.42 - block_h / 2)

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    word_layers = []
    for i, text in enumerate(lines):
        w = int(probe.textlength(text, font=font)) + 40
        layer = Image.new("RGBA", (w, asc + desc + 24), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((20, 8), text, font=font, fill=pal.ink)
        layer = _outlined(layer, motifs.shade(pal.ground, 0.4), 5)
        word_layers.append((layer, int((WIDTH - w) / 2), top + i * leading - 8))

    tag_font = titles._load(titles.MONO_STACK, 30)
    sub_font = titles._load(titles.KICKER_STACK, 32)
    tag = (channel.tagline or "PRESS START").upper()
    tag_w = _tracked_width(probe, tag, tag_font, 7.0)

    drop = max(0.2, min(1.2, spec.fly_duration))
    gap = max(0.03, min(0.3, spec.stagger))
    k = _squeeze(duration, 0.15, gap * (len(lines) - 1) + drop + 0.5)
    drop, gap = drop * k, gap * k
    landed = 0.15 + gap * (len(lines) - 1) + drop
    shadow_off = max(6, int(size * 0.055))

    def frames():
        for f in range(n_frames):
            t = f / FPS
            # The pattern never stops: a slate that parks looks like a still.
            shift = int((t * 46) % WIDTH)
            frame = ground.copy()
            frame.paste(field.crop((shift, 0, shift + WIDTH, HEIGHT)), (0, 0),
                        field.crop((shift, 0, shift + WIDTH, HEIGHT)))

            for i, (layer, x, y) in enumerate(word_layers):
                p = _clamp01((t - (0.15 + gap * i)) / drop)
                if p <= 0:
                    continue
                e = _ease_out_back(p)
                dy = int((1 - e) * -260)
                a = int(255 * min(1.0, p * 2.2))
                img = layer
                if a < 255:
                    img = layer.copy()
                    img.putalpha(img.split()[3].point(lambda v: v * a // 255))
                # The hard shadow is the second theme colour, not a black blur:
                # that is what makes the type read as a decal rather than a title.
                sh = Image.new("RGBA", img.size, pal.accent2[:3] + (0,))
                sh.putalpha(img.split()[3].point(lambda v: v * a // 255))
                frame.paste(sh, (x + shadow_off, y + dy + shadow_off), sh)
                frame.paste(img, (x, y + dy), img)

            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            if t > landed + 0.1:
                # Blink, with a duty cycle that reads as neon rather than a fault.
                on = (t - landed) % 1.1 < 0.72
                if on:
                    titles._tracked(d, ((WIDTH - tag_w) / 2, top + block_h + 46),
                                    tag, tag_font, pal.accent2, 7.0)
            if video_title and spec.show_video_title:
                a = int(230 * _fade(t, landed + 0.25, 0.45))
                if a:
                    text = _elide(probe, video_title, sub_font, WIDTH - 420)
                    d.text(((WIDTH - probe.textlength(text, font=sub_font)) / 2,
                            top + block_h + 116), text, font=sub_font,
                           fill=(255, 255, 255, a))
            frame = Image.alpha_composite(frame.convert("RGBA"), layer)
            frame = Image.alpha_composite(frame, scan).convert("RGB")
            # Two frames of channel split as the last line lands.
            if 0 <= t - landed < 2 / FPS:
                frame = _rgb_split(frame, 7)
            yield frame

    _encode(out_path, frames(), what="the arcade slate")
    progress(f"Arcade slate rendered: {duration:.1f}s, wordmark at {size}px, "
             f"pattern at {cell}px")
    return duration


# ------------------------------------------------------------ gloss template
def _render_gloss(channel: Channel, video_title: str, out_path: Path,
                  progress: Progress) -> float:
    """Soft light, a scatter of sparkles, and one sweep of gloss across the type.

    The beauty slate, and the second one that runs light rather than on black.
    Nothing here slams: the name fades up while a highlight travels over it, and
    the sparkles keep twinkling long after everything else has settled.
    """
    spec = channel.intro
    pal = themes.palette(channel.style)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))
    ink = pal.ink if pal.light else (255, 255, 255, 255)

    cell = _density(spec, 78, 150)
    base = motifs.radial((WIDTH, HEIGHT), motifs.shade(pal.ground, 1.06),
                         motifs.mix(pal.ground, pal.accent, 0.34),
                         centre=(0.5, 0.34), radius=0.95).convert("RGBA")
    base = Image.alpha_composite(base, motifs.icon_field(
        (WIDTH, HEIGHT), pal.icons, [pal.accent, motifs.shade(pal.accent2, 0.9)],
        cell=cell, alpha=58, angle=6, seed=_seed(channel)))
    base = Image.alpha_composite(base, motifs.noise((WIDTH, HEIGHT), 10, 14)).convert("RGB")

    name = channel.name
    name_font, size = _fit_tracked(name.upper(), titles.SMALLCAPS_STACK,
                                   WIDTH - 460, 14.0, cap=150)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    name_w = _tracked_width(probe, name.upper(), name_font, 14.0)
    asc, _ = name_font.getmetrics()
    name_y = int(HEIGHT * 0.44)

    # The wordmark is drawn once; the sweep is a mask over this layer, so the
    # gloss travels across the letters instead of across the whole frame.
    word = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    titles._tracked(ImageDraw.Draw(word), ((WIDTH - name_w) / 2, name_y),
                    name.upper(), name_font, ink, 14.0)
    sweep_w = 340
    sweep = Image.new("L", (sweep_w, HEIGHT), 0)
    sd = ImageDraw.Draw(sweep)
    for x in range(sweep_w):
        v = 1 - abs((x / sweep_w) * 2 - 1)
        sd.line([(x, 0), (x, HEIGHT)], fill=int(210 * v ** 2.4))

    tag_font = titles._load(titles.SERIF_ITALIC_STACK, 34)
    sub_font = titles._load(titles.SERIF_ITALIC_STACK, 30)
    rnd = random.Random(_seed(channel))
    twinkles = [(rnd.randrange(120, WIDTH - 120), rnd.randrange(90, HEIGHT - 90),
                 rnd.uniform(18, 46), rnd.uniform(0, 6.2), rnd.uniform(1.4, 3.0))
                for _ in range(16)]

    rise = max(0.25, min(1.4, spec.fly_duration * 1.5))
    k = _squeeze(duration, 0.1, rise + 1.3)
    rise *= k
    sweep_at = 0.1 + rise * 0.7
    sweep_len = 0.9 * k
    tag_at = 0.1 + rise * 0.5
    sub_at = sweep_at + sweep_len * 0.6

    def frames():
        for f in range(n_frames):
            t = f / FPS
            frame = base.copy().convert("RGBA")

            for x, y, s, phase, speed in twinkles:
                v = 0.5 + 0.5 * math.sin(t * speed + phase)
                a = int(200 * v * _fade(t, 0.05, 0.6))
                if a > 8:
                    # Always white: a sparkle is a highlight, and the theme ink
                    # on a blush ground reads as a speck of dirt instead.
                    g = motifs.icon("star4", int(s * (0.6 + v * 0.6)),
                                    (255, 255, 255, a))
                    frame.paste(g, (int(x - g.width / 2), int(y - g.height / 2)), g)

            a = int(255 * _ease_out_cubic(_clamp01((t - 0.1) / rise)))
            if a:
                w = word.copy()
                w.putalpha(w.split()[3].point(lambda v: v * a // 255))
                frame = Image.alpha_composite(frame, w)
                # Gloss: the same letters again in white, masked to a travelling band.
                if sweep_at <= t <= sweep_at + sweep_len:
                    p = (t - sweep_at) / sweep_len
                    x = int(-sweep_w + p * (WIDTH + sweep_w * 2))
                    band = Image.new("L", (WIDTH, HEIGHT), 0)
                    band.paste(sweep, (x, 0))
                    shine = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 0))
                    shine.putalpha(ImageChops.multiply(band, word.split()[3]))
                    frame = Image.alpha_composite(frame, shine)

            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            if channel.tagline:
                ta = int(220 * _fade(t, tag_at, 0.5))
                if ta:
                    tw = probe.textlength(channel.tagline, font=tag_font)
                    d.text(((WIDTH - tw) / 2, name_y - 78), channel.tagline,
                           font=tag_font, fill=pal.accent[:3] + (ta,))
            # Two hairlines opening outward from under the name.
            rw = 300 * _ease_out_cubic(_clamp01((t - tag_at) / (rise + 0.3)))
            if rw > 2:
                d.rectangle([WIDTH / 2 - rw, name_y + asc + 42,
                             WIDTH / 2 + rw, name_y + asc + 43.5],
                            fill=pal.accent[:3] + (190,))
            if video_title and spec.show_video_title:
                sa = int(225 * _fade(t, sub_at, 0.5))
                if sa:
                    text = _elide(probe, video_title, sub_font, WIDTH - 520)
                    d.text(((WIDTH - probe.textlength(text, font=sub_font)) / 2,
                            name_y + asc + 66), text, font=sub_font,
                           fill=(pal.ink[:3] if pal.light else (255, 255, 255)) + (sa,))
            yield Image.alpha_composite(frame, layer).convert("RGB")

    _encode(out_path, frames(), what="the gloss slate")
    progress(f"Gloss slate rendered: {duration:.1f}s, name at {size}px on "
             f"{'paper' if pal.light else 'ink'}")
    return duration


# ---------------------------------------------------------- kickoff template
def _render_kickoff(channel: Channel, video_title: str, out_path: Path,
                    progress: Progress) -> float:
    """Diagonal bands slam in, then a slanted panel slides over them with the name.

    The sports slate. Bands alone are unreadable — condensed white caps on a
    field of stripes is a test card, not a title — so the stripes are the border
    treatment and a rotated panel carries the type, which is how a broadcast
    lower third has always solved the same problem. Everything is on the same
    slant, including the letters.
    """
    spec = channel.intro
    pal = themes.palette(channel.style)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))
    TILT = -9.0

    ground = motifs.gradient((WIDTH, HEIGHT),
                             [pal.ground, motifs.shade(pal.ground, 0.5)], 100)
    band_w = _density(spec, 44, 104)
    bands = motifs.stripes((WIDTH, HEIGHT),
                           [pal.accent, (0, 0, 0, 0), pal.accent2[:3] + (46,),
                            (0, 0, 0, 0)], band_w, angle=TILT - 15)

    # A number pulled off the channel id: stable, and nobody has to type it.
    number = str(_seed(channel) % 90 + 10)

    lines = _wordmark_lines(channel.name)
    font, size = _fit_display(lines, WIDTH - 520, 330, cap=190,
                              stack=titles.CONDENSED_STACK)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    asc, desc = font.getmetrics()
    leading = int(size * 0.92)
    block_h = leading * (len(lines) - 1) + asc + desc

    # The panel is built flat and rotated, so its edges and the type on it share
    # one slant instead of two that nearly agree.
    panel_h = block_h + 190
    big = Image.new("RGBA", (WIDTH * 2, HEIGHT * 2), (0, 0, 0, 0))
    bd = ImageDraw.Draw(big)
    cy = HEIGHT
    top_e, bot_e = cy - panel_h / 2, cy + panel_h / 2
    bd.rectangle([0, top_e, WIDTH * 2, bot_e], fill=motifs.shade(pal.ground, 0.75)[:3] + (242,))
    bd.rectangle([0, top_e - 7, WIDTH * 2, top_e], fill=pal.accent)
    bd.rectangle([0, bot_e, WIDTH * 2, bot_e + 7], fill=pal.accent)

    # Sized to the panel and set inside it: a number that overhangs the band
    # ends up floating over the stripes, which reads as a bug.
    num_font = titles._load(titles.DISPLAY_STACK, int(panel_h * 0.94))
    nw = bd.textlength(number, font=num_font)
    nasc, ndesc = num_font.getmetrics()
    bd.text((WIDTH * 1.5 - nw - 90, cy - (nasc + ndesc) / 2 + ndesc * 0.4), number,
            font=num_font, fill=pal.ink[:3] + (28,))

    ty = cy - block_h / 2 - 6
    for i, text in enumerate(lines):
        tw = probe.textlength(text, font=font)
        bd.text((WIDTH - tw / 2, ty + i * leading), text, font=font, fill=pal.ink)
    if channel.tagline:
        tf = titles._load(titles.KICKER_STACK, 28)
        text = channel.tagline.upper()
        tw = _tracked_width(probe, text, tf, 6.0)
        bd.rectangle([WIDTH - tw / 2 - 26, top_e + 26, WIDTH + tw / 2 + 26, top_e + 76],
                     fill=pal.accent)
        titles._tracked(bd, (WIDTH - tw / 2, top_e + 34), text, tf,
                        motifs.readable_on(pal.accent), 6.0)

    panel = big.rotate(TILT, Image.BICUBIC).crop(
        (WIDTH // 2, HEIGHT // 2, WIDTH // 2 + WIDTH, HEIGHT // 2 + HEIGHT))

    # The video title rides a bar of its own, built and rotated the same way so
    # there are not two slants in the frame that nearly agree.
    title_bar = None
    sub_font = titles._load(titles.KICKER_STACK, 30)
    if video_title and spec.show_video_title:
        text = _elide(probe, video_title.upper(), sub_font, WIDTH - 520)
        tw = _tracked_width(probe, text, sub_font, 4.0)
        tb = Image.new("RGBA", (WIDTH * 2, HEIGHT * 2), (0, 0, 0, 0))
        td = ImageDraw.Draw(tb)
        by = bot_e + 66
        td.rectangle([WIDTH - tw / 2 - 30, by, WIDTH + tw / 2 + 30, by + 64],
                     fill=motifs.shade(pal.ground, 0.55)[:3] + (238,))
        td.rectangle([WIDTH - tw / 2 - 30, by, WIDTH - tw / 2 - 24, by + 64],
                     fill=pal.accent)
        titles._tracked(td, (WIDTH - tw / 2, by + 14), text, sub_font,
                        (255, 255, 255, 255), 4.0)
        title_bar = tb.rotate(TILT, Image.BICUBIC).crop(
            (WIDTH // 2, HEIGHT // 2, WIDTH // 2 + WIDTH, HEIGHT // 2 + HEIGHT))

    slam = max(0.15, min(0.9, spec.fly_duration))
    k = _squeeze(duration, 0.0, slam + 1.0)
    slam *= k
    landed = 0.12 + slam

    def frames():
        for f in range(n_frames):
            t = f / FPS
            frame = ground.copy().convert("RGBA")

            # The bands arrive as two halves closing on the centre.
            p = _ease_out_cubic(_clamp01(t / max(0.01, slam)))
            if p > 0:
                half = int(WIDTH / 2 * p)
                left = bands.crop((0, 0, half, HEIGHT))
                right = bands.crop((WIDTH - half, 0, WIDTH, HEIGHT))
                frame.paste(left, (int(-WIDTH / 2 * (1 - p)), 0), left)
                frame.paste(right, (int(WIDTH - half + WIDTH / 2 * (1 - p)), 0), right)

            pp = _clamp01((t - 0.12) / max(0.01, slam))
            if pp > 0:
                e = _ease_out_cubic(pp)
                dx = int((1 - e) * -WIDTH)
                img = panel
                a = int(255 * min(1.0, pp * 3.0))
                if a < 255:
                    img = panel.copy()
                    img.putalpha(img.split()[3].point(lambda v: v * a // 255))
                # Streaks trailing the panel while it is still travelling.
                if pp < 0.9:
                    for st in range(1, 3):
                        ghost = img.copy()
                        ghost.putalpha(ghost.split()[3].point(
                            lambda v: int(v * (0.2 / st) * (1 - pp))))
                        frame.paste(ghost, (dx - st * 70, 0), ghost)
                frame.paste(img, (dx, 0), img)

            if title_bar is not None:
                sa = int(255 * _fade(t, landed + 0.2, 0.4))
                if sa:
                    bar = title_bar
                    if sa < 255:
                        bar = title_bar.copy()
                        bar.putalpha(bar.split()[3].point(lambda v: v * sa // 255))
                    frame.paste(bar, (0, 0), bar)
            yield frame.convert("RGB")

    _encode(out_path, frames(), what="the kickoff slate")
    progress(f"Kickoff slate rendered: {duration:.1f}s, name at {size}px on a "
             f"{panel_h}px panel, number {number}")
    return duration


# ------------------------------------------------------------ stack template
def _render_stack(channel: Channel, video_title: str, out_path: Path,
                  progress: Progress) -> float:
    """The name as its own wallpaper, scrolling, with one band cut out of it.

    No pictures and no icons: the channel name repeated across the whole frame
    in stepped rows, half of them outlined, travelling slowly sideways. A band
    opens across the middle and sets the name once, properly, in the clear.
    """
    spec = channel.intro
    pal = themes.palette(channel.style)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    rows = max(5, min(11, 14 - max(3, min(8, int(spec.columns)))))
    wall = motifs.word_field((WIDTH * 2, HEIGHT), channel.name, titles.DISPLAY_STACK,
                             [pal.accent, pal.accent2], rows=rows, angle=-9,
                             alpha=120, ground=None)
    ground = motifs.gradient((WIDTH, HEIGHT),
                             [pal.ground, motifs.mix(pal.ground, pal.accent2, 0.22)],
                             135).convert("RGBA")

    name_font, size = _fit_tracked(channel.name.upper(), titles.DISPLAY_STACK,
                                   WIDTH - 340, 4.0, cap=170)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    name_w = _tracked_width(probe, channel.name.upper(), name_font, 4.0)
    asc, desc = name_font.getmetrics()
    band_h = asc + desc + 96
    band_y = int(HEIGHT * 0.5 - band_h / 2)

    tag_font = titles._load(titles.MONO_STACK, 24)
    sub_font = titles._load(titles.KICKER_STACK, 30)

    open_len = max(0.25, min(1.4, spec.fly_duration * 1.4))
    k = _squeeze(duration, 0.25, open_len + 0.9)
    open_len *= k
    open_at = 0.25
    landed = open_at + open_len

    def frames():
        for f in range(n_frames):
            t = f / FPS
            shift = int((t * 34) % WIDTH)
            frame = ground.copy()
            crop = wall.crop((shift, 0, shift + WIDTH, HEIGHT))
            frame = Image.alpha_composite(frame, crop)

            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            p = _ease_out_cubic(_clamp01((t - open_at) / open_len))
            if p > 0:
                h = band_h * p
                y0 = HEIGHT / 2 - h / 2
                d.rectangle([0, y0, WIDTH, y0 + h], fill=pal.ground[:3] + (238,))
                d.rectangle([0, y0 - 3, WIDTH, y0], fill=pal.accent)
                d.rectangle([0, y0 + h, WIDTH, y0 + h + 3], fill=pal.accent)
            a = int(255 * _clamp01((t - open_at - open_len * 0.45) / max(0.01, open_len * 0.6)))
            if a:
                titles._tracked(d, ((WIDTH - name_w) / 2, band_y + 48),
                                channel.name.upper(), name_font,
                                (255, 255, 255, a), 4.0)
            if channel.tagline:
                ta = int(210 * _fade(t, landed - 0.15, 0.4))
                if ta:
                    text = channel.tagline.upper()
                    tw = _tracked_width(probe, text, tag_font, 7.0)
                    titles._tracked(d, ((WIDTH - tw) / 2, band_y + 16), text,
                                    tag_font, pal.accent2[:3] + (ta,), 7.0)
            if video_title and spec.show_video_title:
                sa = int(235 * _fade(t, landed + 0.15, 0.45))
                if sa:
                    text = _elide(probe, video_title, sub_font, WIDTH - 460)
                    tw = probe.textlength(text, font=sub_font)
                    d.rectangle([(WIDTH - tw) / 2 - 22, band_y + band_h + 44,
                                 (WIDTH + tw) / 2 + 22, band_y + band_h + 98],
                                fill=pal.ground[:3] + (int(sa * 0.85),))
                    d.text(((WIDTH - tw) / 2, band_y + band_h + 52), text,
                           font=sub_font, fill=(255, 255, 255, sa))
            yield Image.alpha_composite(frame, layer).convert("RGB")

    _encode(out_path, frames(), what="the stack slate")
    progress(f"Stack slate rendered: {duration:.1f}s, {rows} rows of wallpaper, "
             f"name at {size}px")
    return duration


# ------------------------------------------------------------ tiles template
def _render_tiles(channel: Channel, video_title: str, out_path: Path,
                  progress: Progress) -> float:
    """A wall of icon tiles flips over, one by one, to uncover a plate.

    The most literal use of the icon set: every tile holds one, alternating
    between the two theme colours, and each flips on its horizontal axis in a
    shuffled order. Works on paper themes as well as ink ones, which is why the
    food and craft theme opens on it.
    """
    spec = channel.intro
    pal = themes.palette(channel.style)
    duration = max(2.5, min(12.0, spec.duration))
    n_frames = int(round(duration * FPS))

    cols = max(4, min(9, int(spec.columns) + 1))
    tile = WIDTH // cols
    rows = HEIGHT // tile + 1
    ground = Image.new("RGB", (WIDTH, HEIGHT), pal.ground[:3])

    rnd = random.Random(_seed(channel))
    faces: list[list[Image.Image]] = []
    order: list[tuple[int, int]] = []
    for r in range(rows):
        row = []
        for c in range(cols):
            back = motifs.mix(pal.ground, pal.accent if (r + c) % 2 else pal.accent2,
                              0.14 + ((r * 3 + c) % 3) * 0.05)
            face = Image.new("RGBA", (tile, tile), back)
            key = pal.icons[(r * 5 + c * 3 + rnd.randrange(2)) % len(pal.icons)]
            g = motifs.icon(key, int(tile * 0.42),
                            (pal.accent if (r + c) % 2 else pal.accent2)[:3] + (150,))
            face.paste(g, ((tile - g.width) // 2, (tile - g.height) // 2), g)
            row.append(face)
            order.append((r, c))
        faces.append(row)
    rnd.shuffle(order)

    # The plate that lands last, carrying the type.
    plate_w, plate_h = int(WIDTH * 0.62), int(HEIGHT * 0.42)
    plate_x, plate_y = (WIDTH - plate_w) // 2, int(HEIGHT * 0.29)
    plate = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    face_col = motifs.shade(pal.ground, 1.6) if not pal.light else (255, 253, 248, 252)
    pd.rounded_rectangle([0, 0, plate_w - 1, plate_h - 1], 10, fill=face_col,
                         outline=pal.accent, width=4)
    name_lines = _wordmark_lines(channel.name, upper=False)
    nf, nsize = _fit_display(name_lines, plate_w - 90, plate_h - 150, cap=110,
                             stack=titles.FONT_STACK)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    asc, desc = nf.getmetrics()
    lead = int(nsize * 1.02)
    block = lead * (len(name_lines) - 1) + asc + desc
    ny = (plate_h - block) // 2 + (18 if channel.tagline else 0)
    for i, line in enumerate(name_lines):
        tw = probe.textlength(line, font=nf)
        pd.text(((plate_w - tw) / 2, ny + i * lead), line, font=nf, fill=pal.ink)
    if channel.tagline:
        tf = titles._load(titles.KICKER_STACK, 24)
        text = channel.tagline.upper()
        tw = _tracked_width(probe, text, tf, 5.0)
        titles._tracked(pd, ((plate_w - tw) / 2, ny - 46), text, tf,
                        pal.accent[:3] + (235,), 5.0)

    sub_font = titles._load(titles.KICKER_STACK, 30)
    flip = max(0.12, min(0.5, spec.fly_duration * 0.6))
    gap = max(0.01, min(0.09, spec.stagger * 0.35))
    total_flip = gap * (len(order) - 1) + flip
    k = _squeeze(duration, 0.05, total_flip + 0.9)
    flip, gap = flip * k, gap * k
    landed = 0.05 + gap * (len(order) - 1) + flip

    def frames():
        for f in range(n_frames):
            t = f / FPS
            frame = ground.copy()
            for i, (r, c) in enumerate(order):
                p = _clamp01((t - (0.05 + gap * i)) / flip)
                if p <= 0:
                    continue
                # Flipping is a vertical squash through zero and back out.
                scale = abs(math.cos(min(1.0, p) * math.pi))
                h = max(1, int(tile * (scale if p < 1 else 1)))
                face = faces[r][c]
                if h != tile:
                    face = face.resize((tile, h), Image.BILINEAR)
                frame.paste(face, (c * tile, r * tile + (tile - h) // 2), face)

            pa = _clamp01((t - landed + 0.35) / 0.45)
            if pa > 0:
                e = _ease_out_back(pa, 1.3)
                w = max(2, int(plate_w * e))
                h = max(2, int(plate_h * e))
                pl = plate.resize((w, h), Image.BILINEAR) if e < 0.999 else plate
                frame.paste(pl, (plate_x + (plate_w - w) // 2,
                                 plate_y + (plate_h - h) // 2), pl)

            if video_title and spec.show_video_title:
                sa = int(240 * _fade(t, landed + 0.2, 0.4))
                if sa:
                    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
                    d = ImageDraw.Draw(layer)
                    text = _elide(probe, video_title, sub_font, WIDTH - 460)
                    tw = probe.textlength(text, font=sub_font)
                    y = plate_y + plate_h + 40
                    d.rounded_rectangle([(WIDTH - tw) / 2 - 24, y, (WIDTH + tw) / 2 + 24,
                                         y + 58], 8, fill=pal.accent[:3] + (int(sa * .92),))
                    d.text(((WIDTH - tw) / 2, y + 12), text, font=sub_font,
                           fill=motifs.readable_on(pal.accent)[:3] + (sa,))
                    frame = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")
            yield frame

    _encode(out_path, frames(), what="the tiles slate")
    progress(f"Tiles slate rendered: {duration:.1f}s, {cols}×{rows} tiles at "
             f"{tile}px, name at {nsize}px")
    return duration


_RENDERERS = {
    "signal": _render_signal,
    "dossier": _render_dossier,
    "filmstrip": _render_filmstrip,
    "mosaic": _render_mosaic,
    "pulse": _render_pulse,
    "atlas": _render_atlas,
    "folio": _render_folio,
    "dial": _render_dial,
    "arcade": _render_arcade,
    "gloss": _render_gloss,
    "kickoff": _render_kickoff,
    "stack": _render_stack,
    "tiles": _render_tiles,
}


def render_intro(channel: Channel, video_title: str, out_path: Path,
                 progress: Progress = lambda m: None) -> float:
    """Render the slate to a silent mp4. Returns its duration in seconds."""
    render = _RENDERERS.get(channel.intro.template, _render_columns)
    return render(channel, video_title, out_path, progress)


def preview_path(channel: Channel) -> Path:
    return channel_dir(channel.id) / "cache" / "intro_preview.mp4"


# --------------------------------------------------------------------- sting
# The slate's own sting. A creator drops in a whole track and takes a window of
# it, so the trim, the level and the fade live here rather than in the render:
# the finished video and the preview below have to sound the same, and there is
# only one place that decides what that sounds like.
def sting_window(intro, slate_len: float) -> tuple[float, float, float]:
    """(start, span, fade) — where in the file the window sits and how long it
    runs. The span covers the slate plus the tail it rings on for."""
    tail = max(0.0, float(intro.music_tail))
    span = max(0.1, slate_len + tail)
    start = max(0.0, float(intro.music_start))
    return start, span, max(0.0, min(float(intro.music_fade), span))


def sting_chain(intro, slate_len: float, fmt: str, lufs: float,
                makeup: float = 0.0) -> str:
    """Filter chain for one sting input: the window, levelled and faded.

    Deliberately ends before any `adelay` the caller adds — nothing may follow
    that filter, or the silence it inserts lands at the wrong end of the branch.
    """
    start, span, fade = sting_window(intro, slate_len)
    chain = (f"{fmt},"
             f"atrim=start={start:.3f}:duration={span:.3f},asetpts=N/SR/TB,"
             f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11,"
             f"volume={float(intro.music_db) + makeup:.1f}dB,"
             f"afade=t=in:st=0:d=0.35")
    if fade > 0.05:
        chain += f",afade=t=out:st={max(0.0, span - fade):.3f}:d={fade:.3f}"
    return chain


def sting_file(channel: Channel) -> Path | None:
    rel = channel.intro.music
    if not rel:
        return None
    path = channel_dir(channel.id) / rel
    return path if path.exists() else None


def mux_sting(channel: Channel, video: Path, slate_len: float,
              progress: Progress = lambda m: None) -> bool:
    """Lay the sting over a rendered slate preview. Never fatal.

    The window runs past the slate by `music_tail`, because in a finished video
    the sting rings on over the first slide. There is no first slide here, so
    the last frame is held for that beat rather than cutting the ring-out off.
    """
    src = sting_file(channel)
    if src is None:
        return False
    start, span, _ = sting_window(channel.intro, slate_len)
    tail = max(0.0, span - slate_len)
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    # The preview is the sting on its own, so it is levelled to where it will
    # sit once the finished mix is mastered to -14 LUFS — not to that number
    # itself, or every level below the voice would sound the same here.
    lufs = float(channel.voice.target_lufs)
    chain = sting_chain(channel.intro, slate_len, fmt, lufs, makeup=-14.0 - lufs)
    tmp = video.with_suffix(".sting.mp4")
    args = ["-i", str(video), "-i", str(src),
            "-filter_complex",
            f"[0:v]tpad=stop_mode=clone:stop_duration={tail:.3f}[v];"
            f"[1:a]{chain}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(tmp)]
    try:
        ffutil.run(args, timeout=300)
        tmp.replace(video)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        progress("Could not lay the sting over the preview "
                 f"({str(exc).strip()[-120:]})")
        return False
    progress(f"Sting over the preview: {channel.intro.music_filename or src.name}"
             f", from {start:.1f}s for {span:.1f}s")
    return True

"""The handwritten board: white ink on a grey-blue slide, revealed as you talk.

The other two formats stage a photograph. This one stages an *argument*. The
frame is a board someone is writing on while they explain something — a line
lands, a bullet gets ticked off, a picture is taped up, a number is circled —
and by the end of the paragraph the whole slide is there. It is the cut a fast
technical explainer runs in, where the words on screen are the structure of the
point rather than a transcript of the voice.

Ten templates (`TEMPLATES`), all drawn with the primitives in `app/diagram.py`,
so the board and anything drawn on it share one hand. Each takes the same small
pile of content off the slide —

    board_lead     the line the slide is about
    board_points   up to six short lines under it
    board_note     a footnote, caption or attribution
    diagram        a diagram spec, for the template that draws one
    the chosen picture, when the template has a place for one

— and no slide is ever required to carry any of it: `content()` derives a
passable lead and points straight from the narration, so switching an existing
video to this format produces boards rather than blank slides. `board_template`
left on "auto" picks the template that fits what the slide actually has, and
avoids repeating whatever the slide before it used.

The reveal is the point. Every element carries a beat number; the beats are
spread across the paragraph's own recorded duration, so the slide fills up at
the pace of the read rather than on a fixed timer. See `diagram.schedule`.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import diagram as dg
from . import ffutil
from .config import FPS, HEIGHT, WIDTH
from .diagram import INK, INK_FAINT, INK_SOFT, Box, Mark
from .schema import Project, Slide

MARGIN = 140
BODY = Box(MARGIN, 118, WIDTH - 2 * MARGIN, HEIGHT - 236)

# ------------------------------------------------------------------ templates
# `wants` is what makes a template a sensible automatic choice for a slide:
# "picture" needs a chosen image, "points" needs at least two lines, "diagram"
# needs a spec. A template with nothing in `wants` works on any slide at all.
TEMPLATES = [
    {"key": "statement", "label": "Statement", "wants": [],
     "blurb": "One line, as big as it will go, underlined by hand. For the "
              "sentence the whole paragraph is built around."},
    {"key": "bullets", "label": "Bullets", "wants": ["points"],
     "blurb": "A heading and up to six lines, each ticked on as you reach it. "
              "The workhorse."},
    {"key": "steps", "label": "Steps", "wants": ["points"],
     "blurb": "Numbered circles across the frame with arrows between them. For "
              "a sequence with an order that matters."},
    {"key": "versus", "label": "Versus", "wants": ["points"],
     "blurb": "Two columns either side of a circled “vs”. Write points as "
              "“this | that” to pair them up row by row."},
    {"key": "code", "label": "Code", "wants": ["points"],
     "blurb": "A sketched window of monospaced lines, revealed one at a time. "
              "Start a line with > to call it out in the accent colour."},
    {"key": "stat", "label": "Number", "wants": [],
     "blurb": "One figure, enormous, with a scribbled ring round it and a "
              "caption underneath."},
    {"key": "quote", "label": "Quote", "wants": [],
     "blurb": "A quotation in big handwriting between drawn quote marks, the "
              "attribution written in last."},
    {"key": "taped", "label": "Taped photo", "wants": ["picture"],
     "blurb": "The picture taped up on the board at an angle, with a "
              "handwritten caption and an arrow pointing at it."},
    {"key": "split", "label": "Split", "wants": ["picture"],
     "blurb": "Writing down the left, the picture framed on the right, a "
              "wobbly rule between them."},
    {"key": "diagram", "label": "Diagram", "wants": ["diagram"],
     "blurb": "A full-frame diagram from the diagram tool, drawn element by "
              "element. See app/diagram.py."},
]
TEMPLATE_KEYS = [t["key"] for t in TEMPLATES]
DEFAULT_TEMPLATE = "bullets"


def template(key: str) -> dict:
    for t in TEMPLATES:
        if t["key"] == key:
            return t
    return TEMPLATES[1]


# -------------------------------------------------------------------- content
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE = re.compile(r"\s*[;:—]\s+|\s+(?:—|–)\s+")
_NUMBERISH = re.compile(r"^[^\w]*[\d][\d,.\s]*[%×x]?\s*\w{0,12}[^\w]*$")


def _short(text: str, words: int = 8) -> str:
    """One line's worth: handwriting at size cannot absorb a sentence."""
    parts = text.strip().strip(".,;:—").split()
    out = " ".join(parts[:words])
    return out + ("…" if len(parts) > words else "")


def derive(slide: Slide) -> tuple[str, list[str]]:
    """A lead and some points for a slide nobody has written a board for.

    Pulled straight out of the narration: the first sentence becomes the line
    the slide is about, and the clauses after it become the lines under it.
    Crude on purpose — it exists so the format never renders an empty board,
    not to replace writing the thing properly.
    """
    sentences = [s for s in _SENTENCE.split(slide.narration.strip()) if s.strip()]
    if not sentences:
        return slide.title or "", []
    lead = slide.title or _short(sentences[0], 9)
    points: list[str] = []
    for sentence in (sentences if slide.title else sentences[1:]):
        for clause in _CLAUSE.split(sentence):
            clause = clause.strip()
            if len(clause.split()) >= 3:
                points.append(_short(clause, 7))
        if len(points) >= 4:
            break
    return lead, points[:4]


def content(slide: Slide) -> dict:
    """Everything a template draws, authored or derived, in one dict."""
    lead = (getattr(slide, "board_lead", "") or "").strip()
    points = [p.strip() for p in (getattr(slide, "board_points", None) or []) if p.strip()]
    if not lead and not points:
        lead, points = derive(slide)
    return {
        "lead": lead or slide.title,
        "points": points[:6],
        "note": (getattr(slide, "board_note", "") or "").strip(),
        "diagram": getattr(slide, "diagram", None) or {},
    }


def pick(slide: Slide, has_picture: bool, previous: str = "", index: int = -1) -> str:
    """Which template a slide on "auto" should get.

    Shape first — a number is a number, code is code — then the picture, on
    every third board that has one, then whatever the slide actually has to
    draw, and finally a nudge away from whatever the slide before it used,
    because three bulleted boards in a row is a slide deck.

    `index` is the slide's place in the video. Without it (-1) a picture is
    only used when the slide has nothing else to draw.
    """
    chosen = (getattr(slide, "board_template", "") or "auto").strip()
    if chosen in TEMPLATE_KEYS:
        return chosen
    c = content(slide)
    lead, points = c["lead"], c["points"]
    if c["diagram"]:
        return "diagram"
    if lead.startswith(("“", '"')) or lead.startswith("'"):
        return "quote"
    if _NUMBERISH.match(lead):
        return "stat"
    if any(p.lstrip().startswith(">") for p in points) or sum(
            1 for p in points if re.search(r"[(){};=]|\w+\.\w+\(", p)) >= 2:
        return "code"
    if any("|" in p for p in points):
        return "versus"
    # Pictures as illustration, not as the format: a board that has one shows
    # it one time in three, alternating taped up and framed beside the
    # writing, and never twice running.
    if (has_picture and index >= 0 and index % 3 == 0
            and previous not in ("split", "taped")):
        return "split" if points and (index // 3) % 2 else "taped"
    options: list[str] = []
    if len(points) >= 3 and all(len(p.split()) <= 6 for p in points[:3]):
        options.append("steps")
    if points:
        options.append("bullets")
    if has_picture:
        options += ["split", "taped"]
    if not points:
        options.append("statement")
    options.append(DEFAULT_TEMPLATE)
    for option in options:
        if option != previous:
            return option
    return options[0]


# -------------------------------------------------------------------- photos
@dataclass
class Photo:
    """A prepared picture and where it sits. Drawn under the ink of its beat."""
    order: int
    tile: Image.Image
    xy: tuple[int, int]


@dataclass
class Sheet:
    """One finished board: what to draw, under what, in what order."""
    marks: list[Mark] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)

    @property
    def beats(self) -> int:
        orders = [m.order for m in self.marks] + [p.order for p in self.photos]
        return (max(orders) + 1) if orders else 1


def _poster(src: Path, cache: Path) -> Path | None:
    """A still from a clip, so a board can tape up a video candidate too."""
    out = cache / f"poster_{src.stem}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        ffutil.run(["-ss", "0.6", "-i", str(src), "-frames:v", "1",
                    "-q:v", "3", str(out)])
    except Exception:
        return None
    return out if out.exists() else None


def _load_photo(src: Path | None, cache: Path) -> Image.Image | None:
    if src is None or not src.exists():
        return None
    if src.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
        src = _poster(src, cache)
        if src is None:
            return None
    try:
        return Image.open(src).convert("RGB")
    except Exception:
        return None


def _tape(onto: Image.Image, cx: float, cy: float, angle: float,
          w: int = 132, h: int = 44) -> None:
    """A strip of masking tape: translucent, slightly crooked, stuck on top."""
    strip = Image.new("RGBA", (w, h), (236, 238, 224, 96))
    ImageDraw.Draw(strip).rectangle((0, 0, w - 1, h - 1),
                                    outline=(255, 255, 255, 60), width=2)
    strip = strip.rotate(angle, expand=True, resample=Image.BICUBIC)
    onto.alpha_composite(strip, (int(cx - strip.width / 2),
                                 int(cy - strip.height / 2)))


def _photo_tile(img: Image.Image, box: Box, *, border: int = 14,
                angle: float = 0.0, taped: bool = False,
                rng: random.Random | None = None) -> tuple[Image.Image, tuple[int, int]]:
    """Fit a picture inside `box` as a bordered, shadowed, optionally taped print."""
    rng = rng or random.Random(7)
    scale = min((box.w - border * 2) / img.width, (box.h - border * 2) / img.height)
    w, h = max(2, int(img.width * scale)), max(2, int(img.height * scale))
    photo = img.resize((w, h), Image.LANCZOS)
    pad = 56
    tile = Image.new("RGBA", (w + border * 2 + pad * 2, h + border * 2 + pad * 2),
                     (0, 0, 0, 0))
    card = Image.new("RGBA", (w + border * 2, h + border * 2), (244, 246, 248, 255))
    card.paste(photo, (border, border))
    # The shadow is the thing that makes it read as a print on a surface rather
    # than a rectangle cut out of the slide.
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 118))
    tile.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)),
                         (pad + 6, pad + 12))
    tile.alpha_composite(card, (pad, pad))
    if angle:
        tile = tile.rotate(angle, expand=True, resample=Image.BICUBIC)
    if taped:
        for fx in (0.26, 0.74):
            _tape(tile, tile.width * fx, pad + rng.uniform(-6, 10),
                  rng.uniform(-24, 24))
    x = int(box.x + (box.w - tile.width) / 2)
    y = int(box.y + (box.h - tile.height) / 2)
    return tile, (x, y)


# ----------------------------------------------------------------- templates
def _lead_marks(order: int, lead: str, box: Box, hand: str, accent: str,
                rng: random.Random, size: int = 76,
                rule: bool = True) -> tuple[list[Mark], float]:
    marks, h = dg.text_block(order, lead, box.x, box.y, size, box.w,
                             anchor="lt", max_lines=2, hand=hand)
    if rule and lead:
        width = min(box.w * 0.62,
                    dg.measure(lead.split()[0] if len(lead) > 40 else lead,
                               size, hand=hand)[0])
        marks += dg._underline_marks(order, box.x, box.y + h + 12, width, rng,
                                     color=accent, width=6)
        h += 34
    return marks, h


def _note_marks(order: int, note: str, hand: str) -> list[Mark]:
    if not note:
        return []
    marks, _ = dg.text_block(order, note, MARGIN, HEIGHT - 86, 28,
                             WIDTH - 2 * MARGIN, color=INK_SOFT, anchor="lb",
                             max_lines=2, hand=hand)
    return marks


def _t_statement(c, ctx) -> Sheet:
    """One line, as big as the frame will take, arriving a phrase at a time."""
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    lead = c["lead"] or (c["points"][0] if c["points"] else "")
    size, lines = dg.fit_lines(lead, 132, BODY.w, 3, hand=hand)
    marks: list[Mark] = []
    step = size * 1.16
    top = BODY.y + (BODY.h - step * len(lines)) / 2 - 20
    for i, line in enumerate(lines):
        marks.append(Mark(i, "text", [(BODY.x, top + step * i)], text=line,
                          size=size, color=INK, anchor="lt", font="hand"))
    if lines:
        last = lines[-1]
        marks += dg._underline_marks(
            len(lines) - 1, BODY.x, top + step * len(lines) + 14,
            min(BODY.w, dg.measure(last, size, hand=hand)[0]), rng,
            color=accent, width=8)
    for i, point in enumerate(c["points"][:2]):
        pm, _ = dg.text_block(len(lines) + i, point, BODY.x,
                              top + step * len(lines) + 86 + i * 54, 38,
                              BODY.w * 0.8, color=INK_SOFT, anchor="lt",
                              max_lines=1, hand=hand)
        marks += pm
    marks += _note_marks(len(lines) + 2, c["note"], hand)
    return Sheet(marks)


def _t_bullets(c, ctx) -> Sheet:
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    marks, h = _lead_marks(0, c["lead"], BODY, hand, accent, rng, size=78)
    top = BODY.y + h + 54
    points = c["points"][:6]
    room = BODY.y + BODY.h - top
    slot = min(132.0, room / max(1, len(points)))
    size = 56 if len(points) <= 4 else 46
    for i, point in enumerate(points):
        order = 1 + i
        y = top + slot * i
        accented = point.startswith("*")
        text = point.lstrip("*").strip()
        color = accent if accented else INK
        # The dash is drawn, not typed: a hyphen in a handwriting face reads as
        # a typo, and a stroke reads as someone ticking the line off.
        marks.append(Mark(order, "stroke",
                          dg._wobble((BODY.x, y + size * 0.52),
                                     (BODY.x + 44, y + size * 0.48), rng, 1.4),
                          color=accent if accented else INK_FAINT, width=5))
        pm, _ = dg.text_block(order, text, BODY.x + 76, y, size,
                              BODY.w - 76, color=color, anchor="lt",
                              max_lines=2, hand=hand)
        marks += pm
    marks += _note_marks(len(points) + 1, c["note"], hand)
    return Sheet(marks)


def _t_steps(c, ctx) -> Sheet:
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    marks, h = _lead_marks(0, c["lead"], BODY, hand, accent, rng, size=70)
    points = c["points"][:5] or [c["lead"]]
    n = len(points)
    top = BODY.y + h + 70
    room = BODY.h - h - 70
    cy = top + room * 0.38
    slot = BODY.w / n
    rad = min(96.0, slot * 0.30)
    for i, point in enumerate(points):
        order = 1 + i
        cx = BODY.x + slot * (i + 0.5)
        accented = point.startswith("*")
        text = point.lstrip("*").strip()
        color = accent if accented else INK
        marks += dg._ellipse_marks(order, cx, cy, rad, rad, rng, color=color,
                                   width=5)
        nm, _ = dg.text_block(order, str(i + 1), cx, cy, int(rad * 1.1),
                              rad * 1.6, color=color, anchor="mm", max_lines=1,
                              hand=hand)
        marks += nm
        pm, _ = dg.text_block(order, text, cx, cy + rad + 38, 46, slot - 36,
                              color=color, anchor="mt", max_lines=3, hand=hand)
        marks += pm
        if i:
            marks += dg._arrow_marks(order, (cx - slot + rad + 16, cy),
                                     (cx - rad - 18, cy), rng, color=INK_FAINT,
                                     width=4)
    marks += _note_marks(n + 1, c["note"], hand)
    return Sheet(marks)


def _t_versus(c, ctx) -> Sheet:
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    marks, h = _lead_marks(0, c["lead"], BODY, hand, accent, rng, size=66)
    points = c["points"]
    if any("|" in p for p in points):
        rows = [[s.strip() for s in p.split("|")[:2]] for p in points if p.strip()]
        left = [r[0] for r in rows]
        right = [r[1] if len(r) > 1 else "" for r in rows]
    else:
        half = max(1, (len(points) + 1) // 2)
        left, right = points[:half], points[half:]
    top = BODY.y + h + 92
    mid = BODY.x + BODY.w / 2
    col_w = BODY.w / 2 - 110
    marks.append(Mark(1, "stroke",
                      dg._wobble((mid, top - 30), (mid, BODY.y + BODY.h), rng, 3.0),
                      color=INK_FAINT, width=3, alpha=0.8))
    rows = max(len(left), len(right))
    rad = 58
    vs_y = top + min(150.0, (BODY.y + BODY.h - top) / max(1, rows)) * rows / 2
    marks += dg._ellipse_marks(1, mid, vs_y, rad, rad * 0.82, rng,
                               color=accent, width=5)
    vm, _ = dg.text_block(1, "vs", mid, vs_y, 50, rad * 1.5, color=accent,
                          anchor="mm", max_lines=1, hand=hand)
    marks += vm
    slot = min(150.0, (BODY.y + BODY.h - top) / max(1, rows))
    for i in range(rows):
        for side, items in ((0, left), (1, right)):
            if i >= len(items) or not items[i]:
                continue
            order = 2 + i * 2 + side
            x = BODY.x if side == 0 else mid + 86
            text = items[i].lstrip("*").strip()
            color = accent if items[i].startswith("*") else INK
            y = top + slot * i
            marks.append(Mark(order, "stroke",
                              dg._wobble((x, y + 30), (x + 30, y + 28), rng, 1.2),
                              color=INK_FAINT, width=4))
            pm, _ = dg.text_block(order, text, x + 52, y, 48, col_w - 52,
                                  color=color, anchor="lt", max_lines=2, hand=hand)
            marks += pm
    marks += _note_marks(2 + rows * 2, c["note"], hand)
    return Sheet(marks)


def _t_code(c, ctx) -> Sheet:
    """A sketched window of monospace. Lines with > on them get called out."""
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    marks, h = _lead_marks(0, c["lead"], BODY, hand, accent, rng, size=62,
                           rule=False)
    lines = c["points"][:8] or [c["lead"]]
    top = BODY.y + h + 46
    room = BODY.y + BODY.h - top
    size_guess = 44 if len(lines) <= 6 else 36
    card = Box(BODY.x, top, BODY.w,
               min(room, 150 + size_guess * 1.6 * len(lines)))
    marks += dg._rect_marks(1, card.x, card.y, card.w, card.h, rng,
                            color=INK_FAINT, width=3)
    marks.append(Mark(1, "stroke",
                      dg._wobble((card.x, card.y + 56), (card.x + card.w, card.y + 56),
                                 rng, 1.4), color=INK_FAINT, width=3))
    for i, fx in enumerate((34, 72, 110)):
        marks += dg._ellipse_marks(1, card.x + fx, card.y + 28, 11, 11, rng,
                                   color=INK_FAINT, width=3)
    size = size_guess
    step = min(size * 1.7, (card.h - 118) / max(1, len(lines)))
    for i, raw in enumerate(lines):
        order = 2 + i
        hot = raw.lstrip().startswith(">")
        text = raw.lstrip().lstrip(">").rstrip() if hot else raw.rstrip()
        y = card.y + 86 + step * i
        lm, _ = dg.text_block(order, text, card.x + 48, y, size, card.w - 96,
                              color=accent if hot else INK, anchor="lt",
                              max_lines=1, mark_font="mono", hand=hand)
        marks += lm
        if hot:
            w = min(card.w - 96, dg.measure(text, size, "mono", hand)[0])
            marks += dg._rect_marks(order, card.x + 32, y - 12, w + 34,
                                    size * 1.5, rng, color=accent, width=4)
    marks += _note_marks(2 + len(lines), c["note"], hand)
    return Sheet(marks)


def _t_stat(c, ctx) -> Sheet:
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    figure = c["lead"] or (c["points"][0] if c["points"] else "")
    caption = c["points"][0] if (c["points"] and c["lead"]) else c["note"]
    cx, cy = WIDTH / 2, HEIGHT * 0.46
    size, lines = dg.fit_lines(figure, 300, BODY.w * 0.74, 1, hand=hand)
    marks = [Mark(0, "text", [(cx, cy)], text=lines[0] if lines else "",
                  size=size, color=accent, anchor="mm")]
    w = dg.measure(lines[0] if lines else "", size, hand=hand)[0]
    marks += dg._ellipse_marks(1, cx, cy, w * 0.62 + 46, size * 0.78, rng,
                               color=INK, width=7, sweep=1.12)
    if caption:
        cm, _ = dg.text_block(2, caption, cx, cy + size * 0.80 + 56, 50,
                              BODY.w * 0.72, color=INK, anchor="mt",
                              max_lines=2, hand=hand)
        marks += cm
    if c["note"] and caption != c["note"]:
        marks += _note_marks(3, c["note"], hand)
    return Sheet(marks)


def _t_quote(c, ctx) -> Sheet:
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    quote = (c["lead"] or "").strip("“”\"'")
    inner = Box(BODY.x + 130, BODY.y + 60, BODY.w - 200, BODY.h - 150)
    size, lines = dg.fit_lines(quote, 92, inner.w, 4, hand=hand)
    step = size * 1.2
    top = inner.y + (inner.h - step * len(lines)) / 2
    marks: list[Mark] = []
    # The quote marks are drawn rather than set: a typographic pair at this
    # size looks printed, and nothing else on this board is. Each one is a
    # comma — a short hook that curls back on itself.
    for ox in (0, 54):
        x = inner.x - 112 + ox
        y = top - 24
        hook = [(x + 26, y), (x + 6, y + 30), (x - 2, y + 58), (x + 14, y + 70),
                (x + 30, y + 62)]
        marks.append(Mark(0, "stroke", hook, color=accent, width=10))
    for i, line in enumerate(lines):
        marks.append(Mark(1 + i, "text", [(inner.x, top + step * i)], text=line,
                          size=size, color=INK, anchor="lt"))
    attribution = c["note"] or (c["points"][0] if c["points"] else "")
    if attribution:
        order = 1 + len(lines)
        y = top + step * len(lines) + 54
        marks.append(Mark(order, "stroke",
                          dg._wobble((inner.x, y + 24), (inner.x + 66, y + 22), rng, 1.4),
                          color=accent, width=5))
        am, _ = dg.text_block(order, attribution, inner.x + 92, y, 42,
                              inner.w - 92, color=INK_SOFT, anchor="lt",
                              max_lines=1, hand=hand)
        marks += am
    return Sheet(marks)


def _t_taped(c, ctx) -> Sheet:
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    img = ctx["image"]
    if img is None:
        return _t_statement(c, ctx)
    marks, h = _lead_marks(0, c["lead"], Box(BODY.x, BODY.y, BODY.w * 0.5, 200),
                           hand, accent, rng, size=62)
    frame = Box(WIDTH * 0.30, BODY.y + h + 40, WIDTH * 0.62,
                BODY.y + BODY.h - (BODY.y + h + 40) - 20)
    tile, xy = _photo_tile(img, frame, angle=rng.uniform(-2.6, 2.6), taped=True,
                           rng=rng)
    photos = [Photo(1, tile, xy)]
    points = c["points"][:3]
    # Each line goes under the last one's real height: a point that wraps to
    # two lines used to be overwritten by the one after it.
    y = BODY.y + h + 64
    for i, point in enumerate(points):
        pm, ph = dg.text_block(2 + i, point.lstrip("*").strip(), BODY.x, y, 40,
                               WIDTH * 0.24,
                               color=accent if point.startswith("*") else INK,
                               anchor="lt", max_lines=2, hand=hand)
        marks += pm
        y += ph + 22
    # An arrow out from under the writing, into the side of the print.
    marks += dg._arrow_marks(2 + len(points), (BODY.x + 40, y + 24),
                             (xy[0] + 56, xy[1] + tile.height * 0.62), rng,
                             color=accent, width=4)
    marks += _note_marks(3 + len(points), c["note"], hand)
    return Sheet(marks, photos)


def _t_split(c, ctx) -> Sheet:
    hand, accent, rng = ctx["hand"], ctx["accent"], ctx["rng"]
    img = ctx["image"]
    if img is None:
        return _t_bullets(c, ctx)
    left = Box(BODY.x, BODY.y, BODY.w * 0.44, BODY.h)
    marks, h = _lead_marks(0, c["lead"], left, hand, accent, rng, size=64)
    top = left.y + h + 48
    points = c["points"][:4]
    slot = min(120.0, (left.y + left.h - top) / max(1, len(points) or 1))
    for i, point in enumerate(points):
        order = 2 + i
        y = top + slot * i
        text = point.lstrip("*").strip()
        color = accent if point.startswith("*") else INK
        marks.append(Mark(order, "stroke",
                          dg._wobble((left.x, y + 26), (left.x + 32, y + 24), rng, 1.2),
                          color=INK_FAINT, width=4))
        pm, _ = dg.text_block(order, text, left.x + 54, y, 44, left.w - 54,
                              color=color, anchor="lt", max_lines=2, hand=hand)
        marks += pm
    divider = BODY.x + BODY.w * 0.48
    marks.append(Mark(1, "stroke",
                      dg._wobble((divider, BODY.y), (divider, BODY.y + BODY.h),
                                 rng, 3.4), color=INK_FAINT, width=3, alpha=0.8))
    frame = Box(divider + 56, BODY.y + 10, BODY.x + BODY.w - divider - 56,
                BODY.h - 20)
    tile, xy = _photo_tile(img, frame, angle=rng.uniform(-1.4, 1.4), rng=rng)
    marks += _note_marks(2 + len(points), c["note"], hand)
    return Sheet(marks, [Photo(1, tile, xy)])


def _t_diagram(c, ctx) -> Sheet:
    spec = dict(c["diagram"] or {})
    if not spec:
        return _t_bullets(c, ctx)
    if not spec.get("title") and c["lead"]:
        spec["title"] = c["lead"]
    if not spec.get("note") and c["note"]:
        spec["note"] = c["note"]
    try:
        marks = dg.marks_for(spec, dg.FULL, ctx["accent"], ctx["hand"])
    except ValueError:
        return _t_bullets(c, ctx)
    return Sheet(marks)


DRAW = {
    "statement": _t_statement, "bullets": _t_bullets, "steps": _t_steps,
    "versus": _t_versus, "code": _t_code, "stat": _t_stat, "quote": _t_quote,
    "taped": _t_taped, "split": _t_split, "diagram": _t_diagram,
}


# ------------------------------------------------------------------ assembly
def build(slide: Slide, key: str, accent: str, hand: str,
          image: Image.Image | None = None) -> Sheet:
    """One slide's board, as marks and photos with their beats."""
    c = content(slide)
    ctx = {"accent": accent, "hand": hand, "image": image,
           "rng": random.Random(dg._seed(slide.id, key))}
    sheet = DRAW.get(key, _t_bullets)(c, ctx)
    orders = sorted({m.order for m in sheet.marks} | {p.order for p in sheet.photos})
    index = {o: i for i, o in enumerate(orders)}
    for m in sheet.marks:
        m.order = index[m.order]
    for p in sheet.photos:
        p.order = index[p.order]
    return sheet


def _compose(base: Image.Image, sheet: Sheet, reveal: dict[int, float],
             lo: int, hi: int, hand: str) -> None:
    """Draw beats [lo, hi) of `sheet` onto `base` — photos under their ink."""
    for photo in sheet.photos:
        if not lo <= photo.order < hi:
            continue
        f = reveal.get(photo.order, 1.0)
        if f <= 0.001:
            continue
        tile = photo.tile
        if f < 0.999:
            tile = tile.copy()
            tile.putalpha(tile.getchannel("A").point(lambda v: int(v * f)))
        rise = int((1 - f) * 26)
        base.alpha_composite(tile, (photo.xy[0], photo.xy[1] + rise))
    live = [m for m in sheet.marks if lo <= m.order < hi]
    if live:
        dg.draw_marks(base, live, reveal, hand)


def frames(sheet: Sheet, seconds: float, ground: Image.Image, hand: str,
           settle: float = 0.5):
    """A board filling up over `seconds`, as RGB frames at `FPS`.

    Beats that have finished are folded into the base and never redrawn, so
    holding on a finished board costs one copy per frame rather than a redraw.
    """
    plan = dg.schedule(sheet.beats, seconds, settle=settle)
    base = ground.convert("RGBA")
    settled = 0
    for i in range(max(2, int(round(seconds * FPS)))):
        reveal = dg.reveal_at(plan, i / FPS)
        done = settled
        while done < sheet.beats and reveal.get(done, 0.0) >= 1.0:
            done += 1
        if done > settled:
            _compose(base, sheet, {o: 1.0 for o in range(settled, done)},
                     settled, done, hand)
            settled = done
        if settled >= sheet.beats:
            yield base.convert("RGB")
            continue
        frame = base.copy()
        _compose(frame, sheet, reveal, settled, sheet.beats, hand)
        yield frame.convert("RGB")


def _ground_for(project: Project, channel=None) -> Image.Image:
    """The empty board for this video, with the channel's host on it if it has one."""
    style = project.style
    base = dg.ground(getattr(style, "board_ground", "") or dg.GROUND,
                     float(getattr(style, "board_grain", 0.5)))
    av = getattr(channel, "avatar", None)
    if av and av.enabled and av.path:
        from .channels import channel_dir
        src = channel_dir(channel.id) / av.path
        if src.is_file():
            try:
                host = Image.open(src).convert("RGBA")
            except Exception:
                return base
            h = int(max(0.1, min(0.4, av.scale)) * HEIGHT)
            w = max(1, int(host.width * h / host.height))
            host = host.resize((w, h), Image.LANCZOS)
            margin = 40
            x = WIDTH - w - margin if av.position != "bottom_left" else margin
            base = base.convert("RGBA")
            base.alpha_composite(host, (x, HEIGHT - h - margin))
            base = base.convert("RGB")
    return base


def render_segment(project: Project, group: list[tuple[Slide, float]],
                   seg_len: float, out: Path, channel=None,
                   cache: Path | None = None, image_for=None,
                   crf: int = 18, extra: tuple[str, ...] = ()) -> Path:
    """One board per paragraph in `group`, encoded to exactly `seg_len`.

    Called from `render._render_segment` when the video is in board format.
    `image_for` hands back the picture chosen for a slide, if any; the two
    templates that use one fall back to a type-only board without it.

    The board is always drawn at 1080p — the layout is in pixels — so `extra`
    is where the in-app preview puts the scale down to its own frame size.
    """
    style = project.style
    hand = getattr(style, "board_hand", "") or dg.DEFAULT_HAND
    accent = style.accent
    cache = cache or out.parent
    ground = _ground_for(project, channel)
    settle = max(0.18, min(1.2, float(getattr(style, "board_settle", 0.5))))

    previous = ""
    plan: list[tuple[Sheet, float]] = []
    spent = 0.0
    for n, (slide, dur) in enumerate(group):
        img = None
        src = image_for(slide) if image_for else None
        if src is not None:
            img = _load_photo(src, cache)
        index = next((i for i, s in enumerate(project.slides) if s.id == slide.id), -1)
        key = pick(slide, img is not None, previous, index)
        previous = key
        # The last board absorbs any rounding so the segment comes out at
        # exactly the length the audio was cut to.
        length = (seg_len - spent) if n == len(group) - 1 else min(dur, seg_len - spent)
        spent += length
        if length <= 0.05:
            continue
        plan.append((build(slide, key, accent, hand, img), length))

    def stream():
        for sheet, length in plan:
            yield from frames(sheet, length, ground, hand, settle)

    # `-t` so the segment comes out at exactly the length the audio was cut
    # to, whatever rounding the per-board frame counts accumulated.
    if not ffutil.encode_frames(stream(), out, crf=crf,
                                extra=(*extra, "-t", f"{seg_len:.3f}")) or not out.exists():
        raise RuntimeError("Could not encode the board segment.")
    return out


def still(project: Project, slide: Slide, out: Path, channel=None,
          image: Path | None = None, at: float = 1.0) -> Path:
    """One finished board as a PNG — what the slide editor previews."""
    style = project.style
    hand = getattr(style, "board_hand", "") or dg.DEFAULT_HAND
    img = _load_photo(image, out.parent) if image else None
    index = next((i for i, s in enumerate(project.slides) if s.id == slide.id), -1)
    key = pick(slide, img is not None, index=index)
    sheet = build(slide, key, style.accent, hand, img)
    base = _ground_for(project, channel).convert("RGBA")
    reveal = {o: 1.0 for o in range(sheet.beats)} if at >= 1.0 else dg.reveal_at(
        dg.schedule(sheet.beats, 1.0), at)
    _compose(base, sheet, reveal, 0, sheet.beats, hand)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out)
    return out

"""Hand-drawn diagrams, generated from a short spec a person or an agent writes.

Some paragraphs are not about a photograph. "The request hits the edge, then the
cache, then your server" has no archive image — it has a *shape*, and the only
honest visual is to draw it. This module is that: a declarative spec in, a
diagram out, rendered as if someone had drawn it on the slide with a marker.

The spec is deliberately small enough to write by hand and obvious enough for a
model to fill in without a schema in front of it:

    {"kind": "flow",
     "title": "What happens when you hit enter",
     "nodes": [{"id": "b", "label": "Browser"},
               {"id": "e", "label": "Edge cache", "accent": true},
               {"id": "s", "label": "Your server", "note": "the slow bit"}],
     "edges": [{"from": "b", "to": "e", "label": "GET /"},
               {"from": "e", "to": "s", "label": "miss", "dashed": true}],
     "note": "99% never reach the server"}

Nine layouts (`KINDS`) read that same spec and arrange it differently, so
switching a diagram from a flow to a stack is one word, not a rewrite.

Everything is drawn as *marks* — jittered polylines and handwritten text, each
carrying a reveal order. That single list is what makes the two outputs the same
drawing: `render_still` draws every mark at full ink, and `frames` walks time
across them so the diagram arrives the way it would on a whiteboard, one element
at a time, strokes inking in left to right. A diagram handed back by
`candidate()` is a plain `MediaCandidate`-shaped dict with `local_path` set, so
the rest of the render path — Ken Burns, the essay slide, grading — treats it
exactly like a downloaded photograph, the same deal `app/maps.py` gets.

The palette lives here rather than in `themes.py` because it is not a channel's
choice: white ink on a cool grey board is what the handwritten format *is*. See
`app/board.py`, which draws its slides with these same primitives.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import ffutil, titles
from .config import FPS, HEIGHT, WIDTH
from .schema import MediaCandidate

# ------------------------------------------------------------------ palette
# The board: a cool slate grey-blue, dark enough for white ink to sing and far
# enough from black that it reads as a surface rather than a void.
GROUND = "#3A4552"
GROUND_LOW = "#2F3843"      # the corners, so the frame has some depth
INK = "#FFFFFF"
INK_SOFT = "#C3CCD6"        # notes, captions, anything secondary
INK_FAINT = "#8795A4"       # rules, scaffolding, things that shouldn't be read

# The hand. Bundled first, macOS faces behind — see the note in titles.py for
# why the order is that way round. Shantell Sans is the house choice: of the
# open marker faces it is the one that holds its weight at caption size, where
# a lighter hand like Architects Daughter disappears, and it keeps a true
# lowercase, which Permanent Marker does not.
HAND_STACKS = {
    "marker": [titles._bundled("ShantellSans-SemiBold.ttf"),
               ("/System/Library/Fonts/MarkerFelt.ttc", 1),
               ("/System/Library/Fonts/Supplemental/ChalkboardSE.ttc", 2),
               ("/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf", 0)],
    "bradley": [titles._bundled("Caveat-Bold.ttf"),
                ("/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf", 0),
                ("/System/Library/Fonts/MarkerFelt.ttc", 1),
                ("/System/Library/Fonts/Supplemental/ChalkboardSE.ttc", 2)],
    "chalk": [titles._bundled("RockSalt-Regular.ttf"),
              ("/System/Library/Fonts/Supplemental/Chalkduster.ttf", 0),
              ("/System/Library/Fonts/Supplemental/ChalkboardSE.ttc", 1),
              ("/System/Library/Fonts/MarkerFelt.ttc", 0)],
    "casual": [titles._bundled("PatrickHand-Regular.ttf"),
               ("/System/Library/Fonts/Skia.ttf", 0),
               ("/System/Library/Fonts/Supplemental/ChalkboardSE.ttc", 1),
               ("/System/Library/Fonts/MarkerFelt.ttc", 0)],
    "poster": [titles._bundled("PermanentMarker-Regular.ttf"),
               ("/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf", 0),
               ("/System/Library/Fonts/MarkerFelt.ttc", 1)],
}
HAND_KEYS = list(HAND_STACKS)
DEFAULT_HAND = "marker"

HANDS = [
    {"key": "marker", "label": "Marker", "blurb": "Even felt-tip. The default, "
     "and the most legible of these at small sizes."},
    {"key": "bradley", "label": "Ballpoint", "blurb": "Looser and more slanted — "
     "a note written quickly rather than lettered."},
    {"key": "chalk", "label": "Chalk", "blurb": "Dusty and textured. Charming "
     "in a title, hard work in a paragraph."},
    {"key": "casual", "label": "Casual", "blurb": "Upright and rounded, halfway "
     "between handwriting and a typeface."},
    {"key": "poster", "label": "Poster", "blurb": "All caps, thick and loud. "
     "For a board that is shouting one thing."},
]


def hand_stack(key: str) -> list[tuple[str, int]]:
    return HAND_STACKS.get(key or DEFAULT_HAND, HAND_STACKS[DEFAULT_HAND])


# ------------------------------------------------------------------- layouts
KINDS = [
    {"key": "flow", "label": "Flow", "needs_edges": True,
     "blurb": "Boxes left to right with arrows between them. The default, and "
              "right for anything that happens in an order.",
     "wants": "3-5 nodes; edges from one to the next"},
    {"key": "stack", "label": "Stack", "needs_edges": False,
     "blurb": "Layers piled up, widest at the bottom. For architecture, "
              "abstraction levels, anything where one thing sits on another.",
     "wants": "3-6 nodes, top layer first"},
    {"key": "tree", "label": "Tree", "needs_edges": False,
     "blurb": "One root and its children fanning out below. For a breakdown, "
              "a taxonomy, the options branching off a decision.",
     "wants": "first node is the root; the rest are its children"},
    {"key": "cycle", "label": "Cycle", "needs_edges": False,
     "blurb": "A ring of steps with arrows round it. For a loop that has no "
              "beginning — a feedback cycle, a release process.",
     "wants": "3-6 nodes in order"},
    {"key": "hub", "label": "Hub", "needs_edges": False,
     "blurb": "One thing in the middle, everything else spoked off it. For a "
              "dependency, a bottleneck, a single point of failure.",
     "wants": "first node is the hub; the rest are spokes"},
    {"key": "timeline", "label": "Timeline", "needs_edges": False,
     "blurb": "A drawn line with ticks along it. For dates, versions, the "
              "order things actually happened in.",
     "wants": "nodes in chronological order; put the date in `note`"},
    {"key": "compare", "label": "Compare", "needs_edges": False,
     "blurb": "Two headed columns side by side. For this-versus-that, before "
              "and after, the tradeoff being argued about.",
     "wants": "two `group` values; nodes split between them"},
    {"key": "venn", "label": "Overlap", "needs_edges": False,
     "blurb": "Two or three circles that intersect. For what two things share, "
              "and the sweet spot in the middle.",
     "wants": "2-3 nodes; a third node labels the overlap if you add one"},
    {"key": "grid", "label": "Cards", "needs_edges": False,
     "blurb": "A grid of equal cards. For a set with no order to it — four "
              "approaches, six features, the things on a list.",
     "wants": "2-8 nodes, any order"},
]
KIND_KEYS = [k["key"] for k in KINDS]
DEFAULT_KIND = "flow"

# What to hand a model that is being asked to write one of these. Kept here
# rather than in `script_gen` so the API can serve the same text to an agent
# driving the tool from outside — see GET /api/diagram/kinds.
SPEC_DOC = """A diagram spec is one JSON object:

{"kind": one of """ + ", ".join(f'"{k}"' for k in KIND_KEYS) + """,
 "title": "a short handwritten heading, 2-6 words, or \\"\\" for none",
 "nodes": [{"id": "short-id",
            "label": "1-4 words — this is lettered by hand, so it must be short",
            "note": "" or 3-6 words of secondary detail set under the label,
            "group": "" or a column heading (compare only),
            "accent": false or true to pick this one out in the accent colour}],
 "edges": [{"from": "node id", "to": "node id",
            "label": "" or 1-3 words on the arrow,
            "dashed": false or true}],
 "note": "" or one short line in the bottom corner,
 "reveal": "sequence" to draw it element by element, or "all" to land at once}

Rules that matter:
- Labels are handwritten at size. Four words is the ceiling, two is better.
- 3-6 nodes. A diagram with nine boxes in it is a table, and reads as noise.
- Only "flow" needs edges; every other layout infers its own connections from
  the order of `nodes`. Giving a stack or a cycle edges does nothing.
- Never restate the narration in the diagram. It carries the shape; the voice
  carries the argument."""


# ---------------------------------------------------------------------- marks
@dataclass
class Mark:
    """One thing drawn, and when it arrives.

    `order` groups marks that should appear together — a box, its label and the
    arrow into it are one beat, not three. Everything else is geometry.
    """
    order: int
    kind: str = "stroke"                 # stroke | text | wash
    pts: list[tuple[float, float]] = field(default_factory=list)
    text: str = ""
    size: int = 40
    width: int = 3
    color: str = INK
    anchor: str = "mm"                   # a PIL text anchor
    font: str = "hand"                   # hand | mono
    alpha: float = 1.0                   # ink strength at full reveal
    radius: float = 0.0                  # wash only


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return titles._hex(color, alpha)


def _seed(*parts) -> int:
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.sha1(raw.encode()).hexdigest()[:8], 16)


# ----------------------------------------------------------------- primitives
def _wobble(p0, p1, rng: random.Random, amount: float = 2.0,
            overshoot: float = 0.0) -> list[tuple[float, float]]:
    """A straight line as a hand would draw it: slightly bowed, never exact.

    The bow is one smooth arc rather than per-point noise, because real noise
    reads as a shaky line and a confident hand draws a curve.
    """
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    if overshoot:
        x0 -= dx / length * overshoot * rng.uniform(0.3, 1.0)
        y0 -= dy / length * overshoot * rng.uniform(0.3, 1.0)
        x1 += dx / length * overshoot * rng.uniform(0.3, 1.0)
        y1 += dy / length * overshoot * rng.uniform(0.3, 1.0)
        dx, dy = x1 - x0, y1 - y0
    bow = rng.uniform(-amount, amount) * min(1.0, length / 220)
    steps = max(2, min(24, int(length / 26)))
    out = []
    for i in range(steps + 1):
        t = i / steps
        arc = math.sin(t * math.pi) * bow
        out.append((x0 + dx * t + nx * arc, y0 + dy * t + ny * arc))
    return out


def _rect_marks(order: int, x: float, y: float, w: float, h: float,
                rng: random.Random, color: str = INK, width: int = 3,
                radius: float = 0.0) -> list[Mark]:
    """A box, drawn as four separate strokes that overshoot at the corners."""
    corners = [((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)),
               ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))]
    return [Mark(order, "stroke", _wobble(a, b, rng, 1.6, overshoot=4.0),
                 color=color, width=width)
            for a, b in corners]


def _ellipse_marks(order: int, cx: float, cy: float, rx: float, ry: float,
                   rng: random.Random, color: str = INK, width: int = 3,
                   sweep: float = 1.06) -> list[Mark]:
    """A circle drawn in one pass, slightly out of round and over-closed."""
    start = rng.uniform(0, math.tau)
    steps = max(28, int((rx + ry) / 3))
    pts = []
    for i in range(steps + 1):
        t = i / steps
        a = start + t * math.tau * sweep
        wob = 1.0 + math.sin(a * 2.3 + start) * 0.018 + math.sin(a * 3.7) * 0.012
        pts.append((cx + math.cos(a) * rx * wob, cy + math.sin(a) * ry * wob))
    return [Mark(order, "stroke", pts, color=color, width=width)]


def _arrow_marks(order: int, p0, p1, rng: random.Random, color: str = INK,
                 width: int = 3, dashed: bool = False) -> list[Mark]:
    """A line with a head on it. Dashed is drawn as separate short strokes."""
    out: list[Mark] = []
    if dashed:
        x0, y0 = p0
        x1, y1 = p1
        length = math.hypot(x1 - x0, y1 - y0) or 1.0
        dash, gap = 16.0, 11.0
        t = 0.0
        while t < length - dash * 0.5:
            a = (x0 + (x1 - x0) * t / length, y0 + (y1 - y0) * t / length)
            t2 = min(length, t + dash)
            b = (x0 + (x1 - x0) * t2 / length, y0 + (y1 - y0) * t2 / length)
            out.append(Mark(order, "stroke", _wobble(a, b, rng, 0.6),
                            color=color, width=width))
            t = t2 + gap
    else:
        out.append(Mark(order, "stroke", _wobble(p0, p1, rng, 2.2),
                        color=color, width=width))
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    size = 15 + width * 2
    for spread in (2.55, -2.55):
        tip = (p1[0] + math.cos(ang + spread) * size,
               p1[1] + math.sin(ang + spread) * size)
        out.append(Mark(order, "stroke", _wobble(p1, tip, rng, 0.7),
                        color=color, width=width))
    return out


def _underline_marks(order: int, x: float, y: float, w: float,
                     rng: random.Random, color: str = INK,
                     width: int = 5) -> list[Mark]:
    """The double scribble under a word that someone wanted you to notice."""
    one = _wobble((x, y), (x + w, y), rng, 3.0, overshoot=6.0)
    two = _wobble((x + 8, y + 7), (x + w - 14, y + 9), rng, 3.4)
    return [Mark(order, "stroke", one, color=color, width=width),
            Mark(order, "stroke", two, color=color, width=max(2, width - 2),
                 alpha=0.62)]


# ---------------------------------------------------------------------- type
_PROBE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def font_for(mark_font: str, size: int, hand: str = DEFAULT_HAND) -> ImageFont.FreeTypeFont:
    stack = titles.MONO_STACK if mark_font == "mono" else hand_stack(hand)
    return titles._load(stack, size)


def measure(text: str, size: int, mark_font: str = "hand",
            hand: str = DEFAULT_HAND) -> tuple[float, float]:
    box = _PROBE.textbbox((0, 0), text or " ", font=font_for(mark_font, size, hand))
    return box[2] - box[0], box[3] - box[1]


def fit_lines(text: str, size: int, max_w: float, max_lines: int = 3,
              mark_font: str = "hand", hand: str = DEFAULT_HAND
              ) -> tuple[int, list[str]]:
    """Step the size down until `text` wraps inside `max_w` in `max_lines`."""
    words = (text or "").split()
    if not words:
        return size, []
    while size > 13:
        font = font_for(mark_font, size, hand)
        lines, cur = [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if _PROBE.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
        if len(lines) <= max_lines and all(
                _PROBE.textlength(l, font=font) <= max_w for l in lines):
            return size, lines
        size = int(size * 0.92)
    return size, [" ".join(words)]


def text_block(order: int, text: str, x: float, y: float, size: int,
               max_w: float, *, color: str = INK, anchor: str = "lt",
               max_lines: int = 3, mark_font: str = "hand",
               hand: str = DEFAULT_HAND, leading: float = 1.18,
               alpha: float = 1.0) -> tuple[list[Mark], float]:
    """A wrapped run of handwriting. Returns its marks and the height it took."""
    size, lines = fit_lines(text, size, max_w, max_lines, mark_font, hand)
    if not lines:
        return [], 0.0
    step = size * leading
    height = step * len(lines)
    top = y if anchor[1] in "ta" else (y - height / 2 if anchor[1] == "m"
                                       else y - height)
    marks = []
    for n, line in enumerate(lines):
        marks.append(Mark(order, "text", [(x, top + step * n)], text=line,
                          size=size, color=color, anchor=f"{anchor[0]}t",
                          font=mark_font, alpha=alpha))
    return marks, height


# ------------------------------------------------------------------ the spec
def normalise(spec: dict | str) -> dict:
    """Clean a spec written by a person or a model into something drawable.

    Forgiving on purpose: a model that wrote `"from"`/`"to"` as labels rather
    than ids, or left `kind` off, should get a diagram rather than an error.
    """
    if isinstance(spec, str):
        spec = json.loads(spec)
    if not isinstance(spec, dict):
        raise ValueError("A diagram spec is a JSON object.")
    kind = str(spec.get("kind") or DEFAULT_KIND).strip().lower()
    if kind not in KIND_KEYS:
        kind = DEFAULT_KIND
    nodes_in = spec.get("nodes") or spec.get("items") or spec.get("steps") or []
    if isinstance(nodes_in, str):
        nodes_in = [n for n in nodes_in.split("\n") if n.strip()]
    nodes: list[dict] = []
    for n, raw in enumerate(nodes_in[:8]):
        if isinstance(raw, str):
            raw = {"label": raw}
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("text") or raw.get("name") or "").strip()
        if not label:
            continue
        nodes.append({
            "id": str(raw.get("id") or label)[:40],
            "label": label[:56],
            "note": str(raw.get("note") or raw.get("detail") or "").strip()[:72],
            "group": str(raw.get("group") or raw.get("column") or "").strip()[:28],
            "accent": bool(raw.get("accent") or raw.get("highlight")),
        })
    if not nodes:
        raise ValueError("A diagram needs at least one node with a label.")
    by_id = {n["id"]: n for n in nodes}
    by_label = {n["label"].lower(): n for n in nodes}
    edges: list[dict] = []
    for raw in (spec.get("edges") or spec.get("links") or [])[:12]:
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("from") or raw.get("source") or "").strip()
        dst = str(raw.get("to") or raw.get("target") or "").strip()
        a = by_id.get(src) or by_label.get(src.lower())
        b = by_id.get(dst) or by_label.get(dst.lower())
        if not a or not b or a is b:
            continue
        edges.append({"from": a["id"], "to": b["id"],
                      "label": str(raw.get("label") or "").strip()[:28],
                      "dashed": bool(raw.get("dashed"))})
    reveal = "all" if str(spec.get("reveal") or "").lower() == "all" else "sequence"
    return {
        "kind": kind,
        "title": str(spec.get("title") or "").strip()[:80],
        "note": str(spec.get("note") or spec.get("footnote") or "").strip()[:120],
        "nodes": nodes,
        "edges": edges,
        "reveal": reveal,
    }


# ----------------------------------------------------------------- geometry
@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    def inset(self, dx: float, dy: float | None = None) -> "Box":
        dy = dx if dy is None else dy
        return Box(self.x + dx, self.y + dy, self.w - 2 * dx, self.h - 2 * dy)


# Generous margins: a diagram that is also allowed to be a Ken Burns still
# gets zoomed into by up to a tenth, and a label clipped by that move is worse
# than one drawn a little smaller.
FULL = Box(150, 120, WIDTH - 300, HEIGHT - 240)


def _node_box_marks(order: int, node: dict, box: Box, rng: random.Random,
                    accent: str, hand: str, size: int = 44) -> list[Mark]:
    """A labelled box: the frame, the label, and its note if it has one."""
    color = accent if node["accent"] else INK
    marks = _rect_marks(order, box.x, box.y, box.w, box.h, rng, color=color,
                        width=4 if node["accent"] else 3)
    note = node["note"]
    label_marks, label_h = text_block(
        order, node["label"], box.x + box.w / 2, box.y + box.h / 2, size,
        box.w - 34, color=color, anchor="mm", max_lines=2, hand=hand)
    if note:
        # The note hangs off the bottom of the label block, both of them
        # centred on the box as one unit rather than each on its own.
        label_marks, label_h = text_block(
            order, node["label"], box.x + box.w / 2,
            box.y + box.h / 2 - 13, size, box.w - 34, color=color,
            anchor="mm", max_lines=2, hand=hand)
        note_marks, _ = text_block(
            order, note, box.x + box.w / 2, box.y + box.h / 2 + label_h / 2 + 2,
            max(20, int(size * 0.56)), box.w - 26, color=INK_SOFT, anchor="mt",
            max_lines=2, hand=hand)
        label_marks = label_marks + note_marks
    return marks + label_marks


def _heading_marks(spec: dict, box: Box, rng: random.Random, accent: str,
                   hand: str) -> tuple[list[Mark], Box]:
    """The title and the footnote, and what is left of the box between them."""
    marks: list[Mark] = []
    top = box.y
    if spec["title"]:
        title_marks, h = text_block(0, spec["title"], box.x, top, 62,
                                    box.w * 0.82, anchor="lt", max_lines=2,
                                    hand=hand)
        marks += title_marks
        w = min(box.w * 0.82, measure(spec["title"].split("\n")[0], 62, hand=hand)[0])
        marks += _underline_marks(0, box.x, top + h + 10, min(w, box.w * 0.5),
                                  rng, color=accent, width=5)
        top += h + 46
    bottom = box.y + box.h
    if spec["note"]:
        note_marks, h = text_block(99, spec["note"], box.x, bottom, 26,
                                   box.w * 0.7, color=INK_SOFT, anchor="lb",
                                   max_lines=2, hand=hand)
        marks += note_marks
        bottom -= h + 24
    return marks, Box(box.x, top, box.w, max(120.0, bottom - top))


# ----------------------------------------------------------------- the nine
def _layout_flow(spec, box, rng, accent, hand) -> list[Mark]:
    nodes = spec["nodes"][:5]
    n = len(nodes)
    gap = 86 if n <= 4 else 60
    bw = (box.w - gap * (n - 1)) / n
    bh = min(box.h * 0.60, 250)
    y = box.y + (box.h - bh) / 2
    marks: list[Mark] = []
    places = {}
    for i, node in enumerate(nodes):
        x = box.x + i * (bw + gap)
        places[node["id"]] = Box(x, y, bw, bh)
        marks += _node_box_marks(1 + i * 2, node, places[node["id"]], rng,
                                 accent, hand, size=46 if n <= 3 else 38)
    # Edges the spec declared, plus — if it declared none — the obvious chain.
    edges = spec["edges"] or [{"from": nodes[i]["id"], "to": nodes[i + 1]["id"],
                               "label": "", "dashed": False}
                              for i in range(n - 1)]
    position = {node["id"]: i for i, node in enumerate(nodes)}
    for edge in edges:
        a, b = places.get(edge["from"]), places.get(edge["to"])
        if not a or not b:
            continue
        # An arrow arrives on the beat of the box it leaves, so a box and the
        # line out of it are drawn as one gesture.
        order = 2 + position[edge["from"]] * 2
        if a.x < b.x:
            p0 = (a.x + a.w + 10, a.y + a.h / 2)
            p1 = (b.x - 12, b.y + b.h / 2)
        else:
            # A backward edge arcs under the row rather than crossing the boxes.
            p0 = (a.x + a.w / 2, a.y + a.h + 10)
            p1 = (b.x + b.w / 2, b.y + b.h + 10)
            mid = (p0[0] + p1[0]) / 2, p0[1] + 92
            marks += [Mark(order, "stroke", _wobble(p0, mid, rng, 3.0),
                           color=INK_FAINT, width=3)]
            marks += _arrow_marks(order, mid, p1, rng, color=INK_FAINT, width=3,
                                  dashed=edge["dashed"])
            if edge["label"]:
                lm, _ = text_block(order, edge["label"], mid[0], mid[1] + 10, 26,
                                   abs(p1[0] - p0[0]) * 0.7 + 60, color=INK_SOFT,
                                   anchor="mt", max_lines=1, hand=hand)
                marks += lm
            continue
        marks += _arrow_marks(order, p0, p1, rng, color=INK_FAINT, width=3,
                              dashed=edge["dashed"])
        if edge["label"]:
            lm, _ = text_block(order, edge["label"], (p0[0] + p1[0]) / 2,
                               p0[1] - 18, 27, abs(p1[0] - p0[0]) + 54,
                               color=INK_SOFT, anchor="mb", max_lines=1, hand=hand)
            marks += lm
    return marks


def _layout_stack(spec, box, rng, accent, hand) -> list[Mark]:
    nodes = spec["nodes"][:6]
    n = len(nodes)
    gap = 16
    bh = (box.h - gap * (n - 1)) / n
    marks: list[Mark] = []
    for i, node in enumerate(nodes):
        # Widest at the bottom: the layer everything else rests on.
        shrink = (n - 1 - i) * (box.w * 0.055)
        bw = box.w - shrink
        x = box.x + shrink / 2
        y = box.y + i * (bh + gap)
        marks += _node_box_marks(1 + i, node, Box(x, y, bw, bh), rng, accent,
                                 hand, size=42 if n <= 4 else 36)
    return marks


def _layout_tree(spec, box, rng, accent, hand) -> list[Mark]:
    root, kids = spec["nodes"][0], spec["nodes"][1:5]
    rw, rh = min(box.w * 0.36, 460), 150
    root_box = Box(box.x + (box.w - rw) / 2, box.y, rw, rh)
    marks = _node_box_marks(1, root, root_box, rng, accent, hand, size=48)
    if not kids:
        return marks
    gap = 44
    kw = (box.w - gap * (len(kids) - 1)) / len(kids)
    kh = min(box.h - rh - 130, 200)
    ky = box.y + box.h - kh
    for i, kid in enumerate(kids):
        kx = box.x + i * (kw + gap)
        marks += _arrow_marks(2 + i, (root_box.x + rw / 2, root_box.y + rh + 8),
                              (kx + kw / 2, ky - 12), rng, color=INK_FAINT, width=3)
        marks += _node_box_marks(2 + i, kid, Box(kx, ky, kw, kh), rng, accent,
                                 hand, size=38 if len(kids) <= 3 else 32)
    return marks


def _layout_cycle(spec, box, rng, accent, hand) -> list[Mark]:
    nodes = spec["nodes"][:6]
    n = len(nodes)
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    rx, ry = min(box.w * 0.34, 520), box.h * 0.36
    rad = min(140.0, ry * 0.62, rx * 0.42)
    marks: list[Mark] = []
    pts = []
    for i in range(n):
        a = -math.pi / 2 + i * math.tau / n
        pts.append((cx + math.cos(a) * rx, cy + math.sin(a) * ry))
    for i, node in enumerate(nodes):
        x, y = pts[i]
        color = accent if node["accent"] else INK
        marks += _ellipse_marks(1 + i * 2, x, y, rad, rad * 0.78, rng,
                                color=color, width=4 if node["accent"] else 3)
        lm, h = text_block(1 + i * 2, node["label"], x, y, 40, rad * 1.7,
                           color=color, anchor="mm", max_lines=2, hand=hand)
        marks += lm
        if node["note"]:
            nm, _ = text_block(1 + i * 2, node["note"], x, y + h / 2 + 6, 24,
                               rad * 1.8, color=INK_SOFT, anchor="mt",
                               max_lines=1, hand=hand)
            marks += nm
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        ang = math.atan2(y1 - y0, x1 - x0)
        p0 = (x0 + math.cos(ang) * (rad + 14), y0 + math.sin(ang) * (rad * 0.78 + 14))
        p1 = (x1 - math.cos(ang) * (rad + 20), y1 - math.sin(ang) * (rad * 0.78 + 20))
        marks += _arrow_marks(2 + i * 2, p0, p1, rng, color=INK_FAINT, width=3)
    return marks


def _layout_hub(spec, box, rng, accent, hand) -> list[Mark]:
    hub, spokes = spec["nodes"][0], spec["nodes"][1:7]
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    hub_r = min(210.0, box.h * 0.27)
    marks = _ellipse_marks(1, cx, cy, hub_r, hub_r * 0.82, rng,
                           color=accent, width=5)
    lm, _ = text_block(1, hub["label"], cx, cy, 44, hub_r * 1.6, color=accent,
                       anchor="mm", max_lines=2, hand=hand)
    marks += lm
    if not spokes:
        return marks
    rx, ry = box.w * 0.40, box.h * 0.40
    for i, node in enumerate(spokes):
        a = -math.pi / 2 + (i + 0.5) * math.tau / len(spokes)
        x, y = cx + math.cos(a) * rx, cy + math.sin(a) * ry
        bw, bh = min(370.0, box.w * 0.25), 124.0
        nb = Box(x - bw / 2, y - bh / 2, bw, bh)
        edge = (cx + math.cos(a) * (hub_r + 12), cy + math.sin(a) * (hub_r * 0.82 + 12))
        stop = (x - math.cos(a) * bw * 0.46, y - math.sin(a) * bh * 0.60)
        marks += _arrow_marks(2 + i, edge, stop, rng, color=INK_FAINT, width=3)
        marks += _node_box_marks(2 + i, node, nb, rng, accent, hand, size=34)
    return marks


def _layout_timeline(spec, box, rng, accent, hand) -> list[Mark]:
    nodes = spec["nodes"][:6]
    n = len(nodes)
    y = box.y + box.h * 0.52
    marks = [Mark(1, "stroke", _wobble((box.x, y), (box.x + box.w, y), rng, 2.4,
                                       overshoot=10.0), color=INK, width=4)]
    slot = box.w / n
    for i, node in enumerate(nodes):
        x = box.x + slot * (i + 0.5)
        color = accent if node["accent"] else INK
        up = i % 2 == 0          # alternate above and below, so labels breathe
        marks.append(Mark(2 + i, "stroke",
                          _wobble((x, y - 16), (x, y + 16), rng, 1.0),
                          color=color, width=4))
        marks += _ellipse_marks(2 + i, x, y, 11, 11, rng, color=color, width=3)
        if node["note"]:
            nm, nh = text_block(2 + i, node["note"], x,
                                y - 36 if up else y + 36, 32, slot - 24,
                                color=accent, anchor="mb" if up else "mt",
                                max_lines=1, hand=hand)
            marks += nm
        else:
            nh = 0.0
        lm, _ = text_block(2 + i, node["label"], x,
                           y - 48 - nh if up else y + 48 + nh, 42, slot - 18,
                           color=color, anchor="mb" if up else "mt",
                           max_lines=2, hand=hand)
        marks += lm
    return marks


def _layout_compare(spec, box, rng, accent, hand) -> list[Mark]:
    nodes = spec["nodes"]
    groups: list[str] = []
    for node in nodes:
        g = node["group"] or ("" if not groups else groups[-1])
        if g and g not in groups:
            groups.append(g)
    if len(groups) < 2:
        # No headings given: split the list down the middle, which is what a
        # bare list of items in a comparison almost always meant.
        half = max(1, (len(nodes) + 1) // 2)
        cols = [("", nodes[:half]), ("", nodes[half:])]
    else:
        cols = [(g, [n for n in nodes if (n["group"] or groups[0]) == g])
                for g in groups[:2]]
    mid = box.x + box.w / 2
    marks = [Mark(1, "stroke",
                  _wobble((mid, box.y + 8), (mid, box.y + box.h - 8), rng, 3.0),
                  color=INK_FAINT, width=3, alpha=0.7)]
    col_w = box.w / 2 - 54
    for c, (heading, items) in enumerate(cols):
        x = box.x + c * (box.w / 2) + (0 if c == 0 else 54)
        top = box.y
        if heading:
            hm, hh = text_block(1, heading, x, top, 54, col_w, anchor="lt",
                                max_lines=1, color=accent if c == 0 else INK,
                                hand=hand)
            marks += hm
            marks += _underline_marks(1, x, top + hh + 8,
                                      min(col_w, measure(heading, 54, hand=hand)[0]),
                                      rng, color=accent if c == 0 else INK_FAINT,
                                      width=4)
            top += hh + 52
        # Items are spread down whatever is left rather than stacked at the
        # top: two items in a column half a frame tall otherwise leave the
        # bottom of the slide empty and the comparison looking unfinished.
        items = items[:4]
        # Spread, but not indefinitely: two items pushed half a frame apart
        # stop reading as a list and start reading as two unrelated notes.
        slot = min(230.0, (box.y + box.h - top) / max(1, len(items)))
        for i, node in enumerate(items):
            order = 2 + i * 2 + c
            color = accent if node["accent"] else INK
            y = top + slot * i
            marks.append(Mark(order, "stroke",
                              _wobble((x, y + 26), (x + 32, y + 26), rng, 1.2),
                              color=INK_FAINT, width=4))
            lm, h = text_block(order, node["label"], x + 52, y, 44,
                               col_w - 52, color=color, anchor="lt",
                               max_lines=2, hand=hand)
            marks += lm
            if node["note"]:
                nm, _ = text_block(order, node["note"], x + 52, y + h + 6, 27,
                                   col_w - 52, color=INK_SOFT, anchor="lt",
                                   max_lines=2, hand=hand)
                marks += nm
    return marks


def _layout_venn(spec, box, rng, accent, hand) -> list[Mark]:
    """Two or three circles that overlap, labelled in their own lobes.

    Labels sit inside each circle rather than outside it: outside, a third
    circle's caption falls off the bottom of the frame, and the whole point of
    this layout is the middle, which needs the room.
    """
    nodes = spec["nodes"]
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    two = len(nodes) <= 3
    if two:
        r = min(box.h * 0.46, box.w * 0.23)
        d = r * 0.58
        centres = [(cx - d, cy), (cx + d, cy)]
        lobes = [(cx - d - r * 0.46, cy), (cx + d + r * 0.46, cy)]
    else:
        r = min(box.h * 0.32, box.w * 0.21)
        d = r * 0.60
        centres, lobes = [], []
        for a in (-math.pi / 2, math.pi / 6, math.pi * 5 / 6):
            centres.append((cx + math.cos(a) * d, cy + math.sin(a) * d))
            lobes.append((cx + math.cos(a) * (d + r * 0.48),
                          cy + math.sin(a) * (d + r * 0.48)))
    marks: list[Mark] = []
    for i, node in enumerate(nodes[:len(centres)]):
        color = accent if node["accent"] else INK
        marks += _ellipse_marks(1 + i, centres[i][0], centres[i][1], r, r, rng,
                                color=color, width=4)
    for i, node in enumerate(nodes[:len(centres)]):
        color = accent if node["accent"] else INK
        lm, h = text_block(1 + i, node["label"], lobes[i][0], lobes[i][1], 40,
                           r * 1.05, color=color, anchor="mm", max_lines=2,
                           hand=hand)
        marks += lm
        if node["note"]:
            nm, _ = text_block(1 + i, node["note"], lobes[i][0],
                               lobes[i][1] + h / 2 + 6, 24, r * 1.1,
                               color=INK_SOFT, anchor="mt", max_lines=2, hand=hand)
            marks += nm
    # One node past the circles names the overlap — the thing the diagram is
    # usually being drawn to point at in the first place.
    if len(nodes) > len(centres):
        overlap = nodes[len(centres)]
        lm, _ = text_block(1 + len(centres), overlap["label"], cx,
                           cy if two else cy + r * 0.12, 34, r * 0.92,
                           color=accent, anchor="mm", max_lines=2, hand=hand)
        marks += lm
    return marks


def _layout_grid(spec, box, rng, accent, hand) -> list[Mark]:
    nodes = spec["nodes"][:8]
    n = len(nodes)
    cols = 2 if n <= 4 else 3
    rows = math.ceil(n / cols)
    gap = 42
    cw = (box.w - gap * (cols - 1)) / cols
    ch = (box.h - gap * (rows - 1)) / rows
    marks: list[Mark] = []
    for i, node in enumerate(nodes):
        r, c = divmod(i, cols)
        marks += _node_box_marks(
            1 + i, node,
            Box(box.x + c * (cw + gap), box.y + r * (ch + gap), cw, ch),
            rng, accent, hand, size=46 if cols == 2 else 34)
    return marks


LAYOUTS = {
    "flow": _layout_flow, "stack": _layout_stack, "tree": _layout_tree,
    "cycle": _layout_cycle, "hub": _layout_hub, "timeline": _layout_timeline,
    "compare": _layout_compare, "venn": _layout_venn, "grid": _layout_grid,
}


def marks_for(spec: dict, box: Box | None = None, accent: str = "#E8C36A",
              hand: str = DEFAULT_HAND) -> list[Mark]:
    """Every mark in one diagram, in the order it should be drawn."""
    spec = normalise(spec)
    box = box or FULL
    rng = random.Random(_seed(json.dumps(spec, sort_keys=True)))
    head, inner = _heading_marks(spec, box, rng, accent, hand)
    body = LAYOUTS[spec["kind"]](spec, inner, rng, accent, hand)
    marks = head + body
    # Re-index so the orders are dense and start at zero whatever the layout
    # handed back. The reveal schedule counts beats, not labels.
    seen = sorted({m.order for m in marks})
    index = {o: i for i, o in enumerate(seen)}
    for m in marks:
        m.order = index[m.order]
    return marks


# ---------------------------------------------------------------- the surface
_GRAIN: Image.Image | None = None


def _grain() -> Image.Image:
    """A fixed sheet of noise, built once, that gives the board its tooth."""
    global _GRAIN
    if _GRAIN is None:
        noise = Image.effect_noise((WIDTH // 3, HEIGHT // 3), 42).convert("L")
        _GRAIN = noise.resize((WIDTH, HEIGHT), Image.BILINEAR).filter(
            ImageFilter.GaussianBlur(0.6))
    return _GRAIN


def ground(ground_color: str = GROUND, grain: float = 0.5) -> Image.Image:
    """The empty board: a cool wash, darker at the corners, lightly grained."""
    base = Image.new("RGB", (WIDTH, HEIGHT), _hex(ground_color)[:3])
    low = Image.new("RGB", (WIDTH, HEIGHT), _hex(GROUND_LOW)[:3])
    # A soft radial falloff, built from a blurred ellipse rather than computed
    # per pixel: a hundred frames of per-pixel maths is a visible wait.
    mask = Image.new("L", (WIDTH // 4, HEIGHT // 4), 255)
    ImageDraw.Draw(mask).ellipse(
        (-WIDTH // 16, -HEIGHT // 16, WIDTH // 4 + WIDTH // 16,
         HEIGHT // 4 + HEIGHT // 16), fill=70)
    mask = mask.resize((WIDTH, HEIGHT), Image.BILINEAR).filter(
        ImageFilter.GaussianBlur(70))
    base = Image.composite(low, base, mask)
    if grain > 0.01:
        g = _grain().point(lambda v: int(128 + (v - 128) * min(1.0, grain) * 0.30))
        base = Image.blend(base, Image.merge("RGB", (g, g, g)), 0.10 * min(1.0, grain))
    return base


# ------------------------------------------------------------------- drawing
def _prefix(pts: list[tuple[float, float]], f: float) -> list[tuple[float, float]]:
    """The first `f` of a polyline by length — a stroke still being drawn."""
    if f >= 0.999 or len(pts) < 2:
        return pts
    segs = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            for i in range(len(pts) - 1)]
    total = sum(segs) or 1.0
    want = total * f
    out = [pts[0]]
    run = 0.0
    for i, seg in enumerate(segs):
        if run + seg >= want:
            t = (want - run) / (seg or 1.0)
            out.append((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t,
                        pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t))
            break
        run += seg
        out.append(pts[i + 1])
    return out


def _draw_text(layer: Image.Image, mark: Mark, f: float, hand: str) -> None:
    """Handwriting, revealed left to right as if it were being written."""
    font = font_for(mark.font, mark.size, hand)
    x, y = mark.pts[0]
    alpha = int(255 * mark.alpha * min(1.0, f / 0.3 if f < 0.3 else 1.0))
    fill = _hex(mark.color, max(0, min(255, alpha)))
    if f >= 0.995:
        ImageDraw.Draw(layer, "RGBA").text((x, y), mark.text, font=font,
                                           fill=fill, anchor=mark.anchor)
        return
    w = max(8.0, _PROBE.textlength(mark.text, font=font))
    pad = int(mark.size * 1.6)
    tile = Image.new("RGBA", (int(w) + pad * 2, int(mark.size * 2.6) + pad), (0, 0, 0, 0))
    ox = pad if mark.anchor[0] == "l" else (
        tile.width - pad if mark.anchor[0] == "r" else tile.width / 2)
    ImageDraw.Draw(tile, "RGBA").text((ox, pad / 2), mark.text, font=font,
                                      fill=fill, anchor=f"{mark.anchor[0]}t")
    # A soft-edged wipe: the nib position, with the last few millimetres of ink
    # still catching up, which is what stops it reading as a sliding panel.
    mask = Image.new("L", tile.size, 0)
    cut = int((tile.width - pad) * f) + pad // 2
    ImageDraw.Draw(mask).rectangle((0, 0, cut, tile.height), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(mark.size * 0.22))
    tile.putalpha(Image.composite(tile.getchannel("A"),
                                  Image.new("L", tile.size, 0), mask))
    tx = x - ox
    ty = y - pad / 2 if mark.anchor[1] in "ta" else y - tile.height / 2
    layer.alpha_composite(tile, (int(tx), int(ty)))


def draw_marks(layer: Image.Image, marks: list[Mark], reveal: dict[int, float],
               hand: str = DEFAULT_HAND) -> None:
    """Paint `marks` onto an RGBA layer at the per-order reveal in `reveal`."""
    draw = ImageDraw.Draw(layer, "RGBA")
    for mark in marks:
        f = reveal.get(mark.order, 1.0)
        if f <= 0.001:
            continue
        if mark.kind == "text":
            _draw_text(layer, mark, f, hand)
        elif mark.kind == "wash":
            x, y = mark.pts[0]
            r = mark.radius
            draw.ellipse((x - r, y - r, x + r, y + r),
                         fill=_hex(mark.color, int(255 * mark.alpha * f)))
        else:
            pts = _prefix(mark.pts, f)
            if len(pts) >= 2:
                draw.line(pts, fill=_hex(mark.color, int(255 * mark.alpha)),
                          width=mark.width, joint="curve")


# -------------------------------------------------------------------- timing
def schedule(n_beats: int, seconds: float, reveal: str = "sequence",
             settle: float = 0.55) -> list[tuple[float, float]]:
    """When each beat starts drawing and how long its stroke takes.

    The whole diagram lands inside the first two thirds of the shot: a drawing
    still arriving as the narration moves on reads as late, not as paced.
    """
    if n_beats <= 0:
        return []
    if reveal == "all":
        return [(0.0, min(0.5, seconds * 0.4))] * n_beats
    usable = max(0.4, seconds * 0.66)
    step = usable / n_beats
    dur = min(settle, max(0.22, step * 1.35))
    return [(i * step, dur) for i in range(n_beats)]


def reveal_at(plan: list[tuple[float, float]], t: float) -> dict[int, float]:
    """How far each beat has been drawn at `t` seconds in."""
    out = {}
    for i, (start, dur) in enumerate(plan):
        if t <= start:
            out[i] = 0.0
        elif t >= start + dur:
            out[i] = 1.0
        else:
            p = (t - start) / (dur or 1.0)
            out[i] = 1 - (1 - p) ** 2       # ease out: the nib slows into place
    return out


# -------------------------------------------------------------------- output
def render_still(spec: dict, accent: str = "#E8C36A", *, box: Box | None = None,
                 hand: str = DEFAULT_HAND, grain: float = 0.5,
                 ground_color: str = GROUND) -> Image.Image:
    """The finished diagram, every mark inked, on the board."""
    marks = marks_for(spec, box, accent, hand)
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw_marks(layer, marks, {m.order: 1.0 for m in marks}, hand)
    base = ground(ground_color, grain).convert("RGBA")
    base.alpha_composite(layer)
    return base.convert("RGB")


def frames(spec: dict, seconds: float, accent: str = "#E8C36A", *,
           box: Box | None = None, hand: str = DEFAULT_HAND, grain: float = 0.5,
           ground_color: str = GROUND):
    """The diagram arriving, one beat at a time, as RGB frames at `FPS`.

    Beats that have finished drawing are folded down into a settled base image
    and never redrawn, so a long hold on a finished diagram costs almost
    nothing per frame — the same trick the slate animations use.
    """
    spec = normalise(spec)
    marks = marks_for(spec, box, accent, hand)
    beats = (max(m.order for m in marks) + 1) if marks else 0
    plan = schedule(beats, seconds, spec["reveal"])
    base = ground(ground_color, grain).convert("RGBA")
    settled = 0                     # beats already composited into `base`
    total = max(2, int(round(seconds * FPS)))
    for i in range(total):
        t = i / FPS
        reveal = reveal_at(plan, t)
        done = settled
        while done < beats and reveal.get(done, 0.0) >= 1.0:
            done += 1
        if done > settled:
            fold = [m for m in marks if settled <= m.order < done]
            draw_marks(base, fold, {m.order: 1.0 for m in fold}, hand)
            settled = done
        live = [m for m in marks if m.order >= settled and reveal.get(m.order, 0) > 0]
        if not live:
            yield base.convert("RGB")
            continue
        frame = base.copy()
        draw_marks(frame, live, reveal, hand)
        yield frame.convert("RGB")


def _encode(frame_iter, out_path: Path) -> int:
    """Pillow frames straight into ffmpeg, the way `app/maps.py` does it."""
    return ffutil.encode_frames(frame_iter, out_path)


DEFAULT_SECONDS = 7.0


def candidate(spec: dict, dest: Path, accent: str = "#E8C36A", *,
              motion: str = "reveal", seconds: float = DEFAULT_SECONDS,
              hand: str = DEFAULT_HAND, grain: float = 0.5) -> dict | None:
    """Render a spec into `dest` and hand back a media candidate for it.

    `motion` is "reveal" for the drawn-in clip or "still" for one flat frame.
    The result is shaped exactly like a downloaded photograph, which is what
    lets the normal render path stage it without knowing what it is.
    """
    spec = normalise(spec)
    dest.mkdir(parents=True, exist_ok=True)
    stem = f"diagram_{uuid.uuid4().hex[:10]}"
    title = spec["title"] or spec["nodes"][0]["label"]
    poster = ""
    if motion == "still":
        out = dest / f"{stem}.png"
        render_still(spec, accent, hand=hand, grain=grain).save(out)
        kind, local = "image", out.name
        duration = 0.0
    else:
        out = dest / f"{stem}.mp4"
        seconds = max(2.5, min(20.0, float(seconds)))
        n = _encode(frames(spec, seconds, accent, hand=hand, grain=grain), out)
        if not n:
            return None
        kind, local = "video", out.name
        duration = round(n / FPS, 3)
        # A poster frame, because a local mp4 cannot sit in an <img> tag and
        # the picker would otherwise show a broken thumbnail. Same convention
        # the generated establishing shots use — see app/maps.py.
        shot = dest / f"{stem}_poster.jpg"
        render_still(spec, accent, hand=hand, grain=grain).save(shot, quality=88)
        poster = f"media/{shot.name}" if dest.name == "media" else shot.name
    cand = MediaCandidate(
        id=f"diagram_{uuid.uuid4().hex[:8]}",
        provider="diagram",
        kind=kind,
        title=f"{title} — {spec['kind']} diagram",
        source_page="",
        author="drawn here",
        license="yours",
        width=WIDTH,
        height=HEIGHT,
        duration=duration,
        # Above every search hit. A diagram was asked for by name; an archive
        # photograph that happened to score well should not outrank it.
        score=3.0,
        query=spec["kind"],
        thumb=poster,
    )
    d = cand.to_dict()
    d["local_path"] = f"media/{local}" if dest.name == "media" else local
    d["diagram"] = spec
    return d

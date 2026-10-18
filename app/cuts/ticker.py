"""Ticker: money, told on a markets terminal.

Near-black navy, a hairline grid, mono figures. A number the narrator says
rolls up to its value with a green or red change chip beside it; a line chart
draws itself left to right and lands on a pulsing dot; a comparison grows as
bars; a headline sits over the paragraph's picture in a lower third.

Built for personal finance, investing, crypto, economics and business-news
channels — an audience that trusts a number more when it looks like it came
off a terminal.

Every figure on screen is one the writer was given. A chart whose shape is a
sketch of the narration rather than real data says so in its corner.
"""
from __future__ import annotations

import math
import re

from PIL import Image

from . import kit

KEY = "ticker"
LABEL = "Ticker"
FOR = "Personal finance, investing, economics"
BLURB = ("A markets terminal. Figures roll up to their value, charts draw "
         "themselves, bars grow, headlines sit over the picture.")
LOOKS = [{"key": "", "label": "Terminal"}, {"key": "amber", "label": "Amber"}]
FALLBACK_KIND = "headline"
MIN_HOLD = 1.0

KINDS = {"stat", "chart", "bars", "headline"}

PLAN = """The format is a markets terminal: dark navy, hairline grid, mono figures.
Each cue is one panel that takes the screen.

Cue kinds — every cue is an object with "kind", "on" and the fields listed:
- {"kind": "stat", "value": "the figure as written, e.g. $4.2T, 7.5%, 1,200",
   "label": "what it is, 2-6 words", "delta": "optional change, e.g. +12% or -3.1%"}
  The figure rolls up to its value. The workhorse.
- {"kind": "chart", "title": "2-6 words", "points": [4-12 numbers, oldest first],
   "unit": "$, %, or empty", "start": "label for the first point, e.g. 2015",
   "end": "label for the last point", "illustrative": true|false}
  A line that draws itself. Set "illustrative": true whenever the points are
  a sketch of a trend the narration describes rather than real figures.
- {"kind": "bars", "title": "2-6 words", "items": [{"label": "...", "value": number}]}
  2-5 bars, for a comparison.
- {"kind": "headline", "kicker": "ONE OR TWO WORDS", "text": "max 10 words"}
  A headline over the paragraph's picture. For context, people and events.

Rules: 1-4 cues per paragraph. NEVER invent a figure: every value, delta and
bar must be stated in the narration or the research facts. When there is no
number, use a headline. Mark any sketched chart "illustrative": true."""

KIND_DOC = "stat · chart · bars · headline"

UP, DOWN = "#1FD686", "#FF4D5E"
LOOKS_COLORS = {"": {"ground": "#060A12", "grid": "#101828", "ink": "#E9EEF7",
                     "dim": "#7C8AA5", "panel": "#0C1220", "hi": "#4FB3FF"},
                "amber": {"ground": "#0A0804", "grid": "#1A140A", "ink": "#FFD9A0",
                          "dim": "#A0815A", "panel": "#120E07", "hi": "#FFB000"}}
BAR_H = 76


def _s(v, n):
    return str(v or "").strip()[:n]


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").replace("$", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def normalise(c: dict) -> dict | None:
    kind = str(c.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None
    if kind == "stat":
        value = _s(c.get("value"), 14)
        return {"kind": kind, "value": value, "label": _s(c.get("label"), 48),
                "delta": _s(c.get("delta"), 10)} if value else None
    if kind == "chart":
        pts = [p for p in (_num(x) for x in (c.get("points") or [])[:16]) if p is not None]
        return {"kind": kind, "title": _s(c.get("title"), 48), "points": pts,
                "unit": _s(c.get("unit"), 3), "start": _s(c.get("start"), 12),
                "end": _s(c.get("end"), 12),
                "illustrative": bool(c.get("illustrative"))} if len(pts) >= 2 else None
    if kind == "bars":
        items = []
        for it in (c.get("items") or [])[:5]:
            if isinstance(it, dict) and _num(it.get("value")) is not None:
                items.append({"label": _s(it.get("label"), 22), "value": _num(it.get("value"))})
        return {"kind": kind, "title": _s(c.get("title"), 48), "items": items} if len(items) >= 2 else None
    text = _s(c.get("text"), 90)
    return {"kind": kind, "kicker": _s(c.get("kicker"), 18).upper() or "MARKETS",
            "text": text} if text else None


def derive(slide) -> list[dict]:
    parts = kit.clauses(slide.narration, max_words=12, min_words=4)
    cues: list[dict] = [{"kind": "headline", "kicker": (slide.beat or "MARKETS").upper()[:18],
                         "text": kit.short(slide.title or (parts[0] if parts else ""), 9),
                         "on": ""}]
    for n, part in enumerate(parts):
        found = kit.figure(part)
        if found and len(cues) < 4:
            # A figure in the opening clause lands after the headline has
            # had a moment, not on top of it.
            on = kit.head(part) if n else kit.head(" ".join(part.split()[3:]))
            cues.append({"kind": "stat", "value": found[0], "label": found[1], "on": on})
    return cues


# ---------------------------------------------------------------- chrome
def _pal(ctx) -> dict:
    return LOOKS_COLORS.get(ctx.look, LOOKS_COLORS[""])


def _ground(ctx) -> Image.Image:
    key = ("tk_ground", ctx.look, ctx.k)
    if key in ctx.cache:
        return ctx.cache[key]
    pal = _pal(ctx)
    st = kit.Stage(ctx.k, pal["ground"])
    for x in range(0, kit.W, 80):
        st.rect(x, BAR_H, x + 1, kit.H, fill=pal["grid"])
    for y in range(BAR_H, kit.H, 80):
        st.rect(0, y, kit.W, y + 1, fill=pal["grid"])
    st.img.alpha_composite(kit.vignette(st.size, 0.5))
    # Top bar: the video's title on an accent block, a session label opposite.
    st.rect(0, 0, kit.W, BAR_H, fill=pal["panel"])
    st.rect(0, BAR_H - 2, kit.W, BAR_H, fill=pal["grid"])
    title = (getattr(ctx.project, "title", "") or "").upper()
    size, lines = kit.fit(title, "condensed", 36, 1100, 1, floor=20)
    st.text((48, BAR_H / 2), lines[0] if lines else "", "condensed", size, pal["ink"], anchor="lm")
    st.text((kit.W - 48, BAR_H / 2), "MARKETS · EXPLAINED", "mono_bold", 24, pal["dim"],
            anchor="rm")
    ctx.cache[key] = st.img
    return st.img


# ---------------------------------------------------------------- panels
def _split(value: str) -> tuple[str, float | None, str, int]:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", value)
    if not m:
        return value, None, "", 0
    num = m.group()
    decimals = len(num.split(".")[1]) if "." in num else 0
    return value[:m.start()], float(num.replace(",", "")), value[m.end():], decimals


def _fmt(v: float, unit: str, decimals: int) -> str:
    s = f"{v:,.{decimals}f}"
    if unit == "%":
        return s + "%"
    return (unit + s) if unit else s


def _chip(st, x, y, delta: str, px=44, anchor_left=True):
    down = delta.strip().startswith("-")
    color = DOWN if down else UP
    w = kit.advance(delta, "mono_bold", px) + 90
    st.rect(x, y - px * 0.8, x + w, y + px * 0.8, fill=kit.mix("#000000", color, 0.22),
            outline=color, width=3, radius=14)
    tx, ty = x + 34, y
    tri = [(tx - 14, ty + 10), (tx + 14, ty + 10), (tx, ty - 14)] if not down else \
        [(tx - 14, ty - 10), (tx + 14, ty - 10), (tx, ty + 14)]
    st.draw.polygon([(st.p(a), st.p(b)) for a, b in tri], fill=kit.rgba(color))
    st.text((x + 62, y), delta, "mono_bold", px, color, anchor="lm")


def _p_stat(st, cue, u, dur, ctx, picture):
    pal = _pal(ctx)
    pre, num, post, dec = _split(cue["value"])
    f = kit.ease_out(kit.progress(u, 0.05, min(1.0, dur * 0.5)))
    text = cue["value"] if num is None or f >= 1 else f"{pre}{num * f:,.{dec}f}{post}"
    size, _ = kit.fit(cue["value"], "mono_bold", 220, 1500, 1, floor=80)
    cy = kit.H * 0.46
    st.text((kit.W / 2, cy), text, "mono_bold", size, pal["ink"], anchor="mm")
    if cue.get("label"):
        st.text((kit.W / 2, cy - size * 0.62 - 30), cue["label"].upper(), "condensed", 54,
                pal["dim"], anchor="mb")
    if cue.get("delta") and u > 0.5:
        w = kit.advance(cue["delta"], "mono_bold", 52) + 90
        _chip(st, kit.W / 2 - w / 2, cy + size * 0.62 + 60, cue["delta"], 52)
    return f >= 1 and u > 0.6


def _p_chart(st, cue, u, dur, ctx, picture):
    pal = _pal(ctx)
    pts = cue["points"]
    lo, hi = min(pts), max(pts)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    x0, x1, y0, y1 = 200, kit.W - 200, 250, kit.H - 150
    color = UP if pts[-1] >= pts[0] else DOWN
    st.text((x0, 160), cue["title"].upper(), "condensed", 60, pal["ink"], anchor="lm")
    if cue.get("illustrative"):
        st.text((x1, 160), "ILLUSTRATIVE", "mono_bold", 24, pal["dim"], anchor="rm")
    dec = 0 if (hi - lo) > 20 else 1 if (hi - lo) > 2 else 2
    for j in range(5):
        v = lo + (hi - lo) * j / 4
        y = y1 - (y1 - y0) * j / 4
        st.rect(x0, y, x1, y + 1, fill=kit.mix(pal["grid"], pal["dim"], 0.3))
        st.text((x0 - 24, y), _fmt(v, cue.get("unit", ""), dec), "mono", 24, pal["dim"], anchor="rm")
    if cue.get("start"):
        st.text((x0, y1 + 40), cue["start"], "mono", 26, pal["dim"], anchor="lm")
    if cue.get("end"):
        st.text((x1, y1 + 40), cue["end"], "mono", 26, pal["dim"], anchor="rm")
    f = kit.ease_in_out(kit.progress(u, 0.1, min(1.6, dur * 0.6)))
    n = len(pts)
    xy = [(x0 + (x1 - x0) * j / (n - 1), y1 - (y1 - y0) * (p - lo) / (hi - lo))
          for j, p in enumerate(pts)]
    # Cut the polyline at f of the way along, interpolating the last segment.
    reach = f * (n - 1)
    shown = xy[: int(reach) + 1]
    if int(reach) < n - 1:
        a, b = xy[int(reach)], xy[int(reach) + 1]
        r = reach - int(reach)
        shown.append((kit.lerp(a[0], b[0], r), kit.lerp(a[1], b[1], r)))
    if len(shown) >= 2:
        area = st.layer()
        poly = [(st.p(x), st.p(y)) for x, y in shown]
        area.draw.polygon(poly + [(st.p(shown[-1][0]), st.p(y1)), (st.p(shown[0][0]), st.p(y1))],
                          fill=kit.rgba(color, 46))
        st.img.alpha_composite(area.img)
        st.draw.line(poly, fill=kit.rgba(color), width=max(1, st.p(6)), joint="curve")
    ex, ey = shown[-1]
    r = 22 if f >= 1 else 14
    st.wash(ex - r, ey - r, ex + r, ey + r, kit.rgba(color, 70), radius=r)
    st.draw.ellipse(st.box(ex - 11, ey - 11, ex + 11, ey + 11), fill=kit.rgba(color))
    if f >= 1:
        label = _fmt(pts[-1], cue.get("unit", ""), dec)
        st.text((ex - 20, ey - 40), label, "mono_bold", 44, color, anchor="rb")
    return f >= 1


def _p_bars(st, cue, u, dur, ctx, picture):
    pal = _pal(ctx)
    items = cue["items"]
    top = max(abs(i["value"]) for i in items) or 1
    st.text((200, 160), cue["title"].upper(), "condensed", 60, pal["ink"], anchor="lm")
    n = len(items)
    y0, y1 = 270, kit.H - 110
    slot = (y1 - y0) / n
    bh = min(110, slot * 0.62)
    x0, x1 = 560, kit.W - 300
    for j, it in enumerate(items):
        f = kit.ease_out(kit.progress(u, 0.1 + j * 0.15, 0.7))
        y = y0 + slot * j + (slot - bh) / 2
        st.text((x0 - 30, y + bh / 2), it["label"], "sans_bold", 44, pal["ink"], anchor="rm")
        w = (x1 - x0) * abs(it["value"]) / top * f
        color = ctx.accent if j == max(range(n), key=lambda q: items[q]["value"]) else pal["hi"]
        st.rect(x0, y, x0 + max(2, w), y + bh, fill=color, radius=8)
        dec = 0 if top > 100 else 1
        st.text((x0 + w + 24, y + bh / 2), _fmt(it["value"] * f, "", dec), "mono_bold", 44,
                pal["ink"], anchor="lm")
    return u > 0.1 + n * 0.15 + 0.8


def _p_headline(st, cue, u, dur, ctx, picture):
    pal = _pal(ctx)
    if picture is not None:
        key = ("tk_pic", id(picture), ctx.k)
        if key not in ctx.cache:
            img = kit.cover(picture, st.p(kit.W), st.p(kit.H - BAR_H)).convert("RGBA")
            # Duotone toward the terminal: the photo is context, not the show.
            img = Image.blend(img, Image.new("RGBA", img.size, kit.rgba(pal["ground"])), 0.35)
            ctx.cache[key] = img
        st.img.alpha_composite(ctx.cache[key], (0, st.p(BAR_H)))
    key = ("tk_shade", ctx.k)
    if key not in ctx.cache:
        shade = st.layer()
        for j in range(40):
            a = int(220 * (j / 39) ** 1.4)
            y = kit.H * 0.45 + j * (kit.H * 0.55) / 40
            shade.rect(0, y, kit.W, y + (kit.H * 0.55) / 40 + 2, fill=(4, 6, 12, a))
        ctx.cache[key] = shade.img
    st.img.alpha_composite(ctx.cache[key])
    f = kit.ease_out(kit.progress(u, 0.05, 0.35))
    size, lines = kit.fit(cue["text"], "display", 84, 1500, 2, floor=40)
    ty = kit.H - 70 - (len(lines) - 1) * size * 1.1
    x = 120 - (1 - f) * 80
    kw = kit.advance(cue["kicker"], "mono_bold", 30) + 44
    st.rect(x, ty - size - 70, x + kw, ty - size - 22, fill=ctx.accent)
    st.text((x + 22, ty - size - 46), cue["kicker"], "mono_bold", 30, "#0A0A0A", anchor="lm")
    for j, line in enumerate(lines):
        st.text((x, ty + j * size * 1.1), line, "display", size, "#FFFFFF", anchor="ls")
    return f >= 1


PANELS = {"stat": _p_stat, "chart": _p_chart, "bars": _p_bars, "headline": _p_headline}


def frame(beat: kit.Beat, ctx, t: float) -> Image.Image:
    i = beat.at(t)
    cue = beat.cues[i]
    start, end = beat.times[i]
    u, dur = t - start, max(0.2, end - start)
    if cue["kind"] == "headline" and beat.motion is not None:
        clip = kit.footage(ctx, beat.motion, ctx.size[0], round((kit.H - BAR_H) * ctx.k),
                           dim=0.65).frame(t)
        if clip is not None:
            # The clip plays under the shade and the type, which are drawn
            # once onto a clear layer and reused once they have slid in.
            over = beat.extra.get(("tk_over", i))
            if over is None:
                lay = kit.Stage(ctx.k, (0, 0, 0, 0))
                if _p_headline(lay, cue, u, dur, ctx, None):
                    beat.extra[("tk_over", i)] = lay.img
                over = lay.img
            base = _ground(ctx).copy()
            base.paste(clip, (0, round(BAR_H * ctx.k)))
            base.alpha_composite(over)
            return base.convert("RGB")
    key = ("tk_settled", i)
    body = beat.extra.get(key)
    if body is None:
        st = kit.Stage(ctx.k, base=_ground(ctx))
        settled = PANELS[cue["kind"]](st, cue, u, dur, ctx, beat.picture)
        body = st.img
        if settled:
            beat.extra[key] = body
    return body.convert("RGB")


def chapter(ctx, title: str, base: Image.Image, u: float) -> Image.Image:
    """A terminal section header between two screens of figures."""
    c = LOOKS_COLORS.get(ctx.look) or LOOKS_COLORS[""]
    st = kit.dim_to(base, c["ground"], 0.93 * kit.ease_out(kit.progress(u, 0, 0.3)))
    t = kit.ease_out(kit.progress(u, 0.15, 0.45))
    layer = st.layer()
    size, lines = kit.fit(title.upper(), "mono_bold", 92, kit.W - 340, 2, floor=44)
    top = kit.H / 2 - len(lines) * size * 0.6
    layer.rect(150, top - 110, 150 + 8, top + len(lines) * size * 1.2 + 24, fill=c["hi"])
    layer.text((190, top - 70), "SECTION  ▸", "mono_bold", 32, c["hi"], anchor="lm")
    for i, line in enumerate(lines):
        layer.text((190, top + i * size * 1.2 + size * 0.5), line, "mono_bold", size,
                   c["ink"], anchor="lm")
    layer.rect(150, top + len(lines) * size * 1.2 + 44, 150 + (kit.W - 300) * t,
               top + len(lines) * size * 1.2 + 48, fill=c["grid"])
    st.img.alpha_composite(kit.with_alpha(layer.img, t))
    return st.rgb()

"""Flameboat: the rapid-fire tech explainer.

Dark ground, a new thing on screen every clause, hard cuts only. Code types
itself into an editor and the line that matters lights up; a terminal runs a
command and the output spills; a client box, an arrow and a server box pop on
one after the other. And every so often the picture for the paragraph cuts
in with a caption on it — the meme beat, the one that undercuts the line
before it — with a shake on the way in.

Built for developer and tech-culture channels: the audience that watches at
1.5x, reads code faster than prose and gets the joke before the narrator
finishes it.
"""
from __future__ import annotations

import re

from PIL import Image, ImageChops, ImageDraw

from . import kit

KEY = "flameboat"
LABEL = "Flameboat"
FOR = "Dev tools, programming, tech news"
BLURB = ("Rapid-fire tech explainer. B-roll, code that types itself, terminals, boxes "
         "and arrows, and a meme on the joke — a hard cut on every clause.")
LOOKS = [{"key": "", "label": "Charcoal"}, {"key": "midnight", "label": "Midnight blue"}]
FALLBACK_KIND = "title"
MIN_HOLD = 0.45

GROUNDS = {"": ("#0E1014", "#171A21"), "midnight": ("#0A0F1F", "#121A33")}
INK = "#F2F4F8"
INK_DIM = "#8A93A6"
CYAN = "#5FD4FF"

KINDS = {"image", "title", "code", "term", "diagram", "meme", "logo", "post", "stat"}

PLAN = """The format is a rapid-fire tech explainer in the style of the fastest
developer channels: near-black background, a NEW visual on almost every clause
of the narration (every 5-10 spoken words), hard cuts, dry humour. Never hold
one visual for more than about 4 seconds of speech.

It is a VISUAL format. The narrator is already saying the words; the screen
shows the thing — the picture, the code, the shape of the system — not the
sentence again. Most cues should carry almost no text.

Cue kinds — every cue is an object with "kind", "on" and the fields listed:
- {"kind": "image", "focus": "left|center|right", "label": "optional, max 4 words"}
  The paragraph's picture as a fast B-roll cut, pushing in. The workhorse.
  Use it two or three times a paragraph with a different "focus" each time;
  each reads as a different shot of the same scene.
- {"kind": "code", "lang": "js|py|rs|go|ts|sh|sql|...", "lines": ["2-6 lines"], "hot": 0}
  Real, correct, minimal code that types in. "hot" is the 1-based line to
  light up once it has typed (0 for none). Trim to the lines that matter.
- {"kind": "term", "cmd": "a shell command", "out": ["0-3 short output lines"]}
- {"kind": "diagram", "nodes": ["2-4 labels, 1-2 words each"], "label": ""}
  Boxes joined by arrows, popping on left to right. Client -> API -> DB.
- {"kind": "logo", "text": "a product, language or tool name", "sub": ""}
  The name popping on as a badge. Only names, never real logos.
- {"kind": "stat", "value": "a number as said, e.g. 10x, 40ms, 2.3M", "label": "1-3 words"}
- {"kind": "meme", "top": "", "bottom": "caption, 2-5 words"}
  The paragraph's picture with a meme caption, landing with a shake. The joke
  beat: undercut or exaggerate the line before it ("this is fine").
- {"kind": "title", "text": "a short sentence, 4-8 words", "hot": "the phrase within
  it that a highlighter would go over, or \"\" to highlight the whole line"}
  A line punching in with a highlighter swiped across it. For the sentence
  the point turns on — at most two per paragraph. Never a lone word.
- {"kind": "post", "handle": "@an_invented_handle", "text": "max 12 words"}
  A social post as a joke. Always invented — never a real person. At most one
  in every three paragraphs.

Rules: 4-9 cues per paragraph. Vary the kinds; at least half should be image,
code, term, diagram, logo or meme. At most one meme per paragraph and only on
a genuine joke beat. Code is real and would run.
NEVER invent a figure: a stat's value must be a number the narration says.
With no number to show, use an image or a diagram instead."""

KIND_DOC = "image · code · term · diagram · logo · stat · meme · title · post"


# --------------------------------------------------------------------- cues
def _s(v, n: int) -> str:
    return str(v or "").strip()[:n]


def _words(v, n: int) -> str:
    """At most `n` words. The screen is not for sentences in this cut."""
    return " ".join(str(v or "").split()[:n])


def normalise(c: dict) -> dict | None:
    kind = str(c.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None
    if kind == "image":
        focus = str(c.get("focus") or "center").lower()
        return {"kind": kind, "focus": focus if focus in FOCUS else "center",
                "label": _words(c.get("label"), 4)[:32]}
    if kind == "title":
        text = _words(c.get("text"), 8)[:70]
        return {"kind": kind, "text": text, "hot": _words(c.get("hot"), 8)[:70]} if text else None
    if kind == "code":
        lines = [str(l).rstrip()[:70] for l in (c.get("lines") or []) if str(l).strip()][:9]
        try:
            hot = int(c.get("hot") or 0)
        except (TypeError, ValueError):
            hot = 0
        return {"kind": kind, "lang": _s(c.get("lang"), 8) or "js", "lines": lines,
                "hot": hot if 0 < hot <= len(lines) else 0} if lines else None
    if kind == "term":
        cmd = _s(c.get("cmd"), 70)
        out = [str(l).replace("✓", "+").replace("✔", "+").replace("✗", "x")[:70] for l in (c.get("out") or []) if str(l).strip()][:5]
        return {"kind": kind, "cmd": cmd, "out": out} if cmd else None
    if kind == "diagram":
        nodes = [_s(n, 18) for n in (c.get("nodes") or []) if str(n).strip()][:4]
        return {"kind": kind, "nodes": nodes, "label": _s(c.get("label"), 50)} if len(nodes) >= 2 else None
    if kind == "logo":
        text = _s(c.get("text"), 22)
        return {"kind": kind, "text": text, "sub": _s(c.get("sub"), 40)} if text else None
    if kind == "stat":
        value = _s(c.get("value"), 12)
        return {"kind": kind, "value": value, "label": _s(c.get("label"), 40)} if value else None
    if kind == "meme":
        return {"kind": kind, "top": _words(c.get("top"), 5)[:40],
                "bottom": _words(c.get("bottom"), 6)[:48]}
    if kind == "post":
        text = _words(c.get("text"), 14)[:110]
        handle = _s(c.get("handle"), 24) or "@someone"
        return {"kind": kind, "handle": handle if handle.startswith("@") else "@" + handle,
                "text": text} if text else None
    return None


_CODEISH = re.compile(r"[(){};=<>]|\w+\.\w+\(|=>")


def derive(slide) -> list[dict]:
    """Picture-led: B-roll of the paragraph's picture, cut with the odd line
    of the narration highlighted and any figure it states."""
    parts = kit.clauses(slide.narration, max_words=8, min_words=4)
    cues: list[dict] = []
    focus = ["center", "left", "right"]
    shots = 0
    for i, part in enumerate(parts[:8]):
        on = kit.head(part)
        found = kit.figure(part)
        if found:
            cues.append({"kind": "stat", "value": found[0], "label": found[1], "on": on})
        elif _CODEISH.search(part):
            cues.append({"kind": "code", "lang": "js", "lines": [part], "on": on})
        elif i % 2 == 1 and 4 <= len(part.split()) <= 8 and part.rstrip()[-1:] in ".,;:?!—":
            # Only a whole clause: a line cut off mid-sentence reads as a typo.
            line = " ".join(part.strip(" ,;:—").split()[:8])
            cues.append({"kind": "title", "text": line, "hot": "", "on": on})
        else:
            cues.append({"kind": "image", "focus": focus[shots % 3], "label": "", "on": on})
            shots += 1
    return cues


# ------------------------------------------------------------------ syntax
_KEYWORDS = set("""const let var function return if else for while do switch case break
continue new class extends import from export default async await try catch finally
throw def lambda pass yield with as in is not and or None True False null undefined
true false fn pub mut impl struct enum trait match use mod self Self go func package
type interface select from where join on insert update delete create table into values
public private static void int string bool echo sudo npm npx pip cargo git docker""".split())
_TOKEN = re.compile(r"(?P<comment>//.*|#.*|--.*)|(?P<string>\"[^\"]*\"?|'[^']*'?|`[^`]*`?)"
                    r"|(?P<number>\b\d[\d_.]*\b)|(?P<word>[A-Za-z_$][\w$]*)|(?P<other>\s+|.)")
COLORS = {"comment": "#6B7489", "string": "#A8E07A", "number": "#F7C26B",
          "keyword": "#FF7AB6", "func": CYAN, "plain": "#E8EAF0", "punct": "#AEB6C7"}


def tokens(line: str, lang: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in _TOKEN.finditer(line):
        kind = m.lastgroup
        text = m.group()
        if kind == "comment" and text.startswith("#") and lang in ("js", "ts", "rs", "go", "css"):
            kind = "punct"
        if kind == "word":
            rest = line[m.end():m.end() + 1]
            kind = ("keyword" if text in _KEYWORDS else
                    "func" if rest == "(" else "plain")
        elif kind == "other":
            kind = "plain" if text.isspace() else "punct"
        out.append((kind, text))
    return out


# ------------------------------------------------------------------ ground
def _ground(ctx) -> Image.Image:
    key = ("fb_ground", ctx.look, ctx.k)
    if key not in ctx.cache:
        lo, hi = GROUNDS.get(ctx.look, GROUNDS[""])
        st = kit.Stage(ctx.k, lo)
        # A faint dot grid: enough texture that the frame is not a void.
        dot = kit.rgba(hi)
        r = max(1, st.p(2))
        for y in range(30, kit.H, 60):
            for x in range(30, kit.W, 60):
                st.draw.ellipse((st.p(x) - r, st.p(y) - r, st.p(x) + r, st.p(y) + r), fill=dot)
        st.img.alpha_composite(kit.vignette(st.size, 0.55))
        ctx.cache[key] = st.img
    return ctx.cache[key]


def _window(st: kit.Stage, x0, y0, x1, y1, title: str, ground="#151922") -> None:
    sh = Image.new("RGBA", (st.p(x1 - x0), st.p(y1 - y0)), (0, 0, 0, 255))
    st.img.alpha_composite(kit.shadow_of(sh, st.p(26), 150),
                           dest=(st.p(x0) - st.p(54), st.p(y0) - st.p(40)))
    st.rect(x0, y0, x1, y1, fill=ground, outline="#2A3140", width=2, radius=18)
    st.rect(x0, y0, x1, y0 + 56, fill="#1C212C", radius=18)
    st.rect(x0, y0 + 36, x1, y0 + 56, fill="#1C212C")
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        cx, cy = x0 + 34 + i * 30, y0 + 28
        st.draw.ellipse(st.box(cx - 9, cy - 9, cx + 9, cy + 9), fill=kit.rgba(c))
    st.text(((x0 + x1) / 2, y0 + 29), title, "mono", 22, INK_DIM, anchor="mm")


# ------------------------------------------------------------------- shots
def _hot_range(words: list[str], hot: str) -> tuple[int, int]:
    """Which words of the line the highlighter covers: the `hot` phrase if it
    is in there, the whole line if not."""
    bare = [w.lower().strip(".,!?;:'\"") for w in words]
    want = [w.lower().strip(".,!?;:'\"") for w in hot.split()]
    if want:
        for i in range(len(bare) - len(want) + 1):
            if bare[i:i + len(want)] == want:
                return i, i + len(want)
    return 0, len(words)


def _rich_title(st: kit.Stage, text: str, hot: str, accent: str, cy: float,
                swipe: float = 1.0) -> None:
    """A line of type with a highlighter swiped across the phrase that
    matters, `swipe` of the way along it."""
    size, lines = kit.fit(text, "display", 112, 1500, 3, floor=48)
    step = size * 1.22
    top = cy - step * len(lines) / 2 + step / 2
    words = text.split()
    lo, hi = _hot_range(words, hot)
    space = kit.advance(" ", "display", size)
    # Lay every word out first, so the swipe can run across line breaks in
    # reading order.
    laid, n = [], 0
    for li, line in enumerate(lines):
        lw = line.split()
        widths = [kit.advance(w, "display", size) for w in lw]
        x = kit.W / 2 - (sum(widths) + space * (len(lw) - 1)) / 2
        for w, wd in zip(lw, widths):
            laid.append((n, w, x, top + li * step, wd))
            x += wd + space
            n += 1
    lit = [l for l in laid if lo <= l[0] < hi]
    pad = size * 0.16
    widths = []
    for k, (idx, w, x, y, wd) in enumerate(lit):
        # A band runs on through the space to the next highlighted word on
        # the same line, and stops a little past the last one.
        joined = k + 1 < len(lit) and lit[k + 1][3] == y
        widths.append(wd + (space if joined else pad))
    reach = sum(widths) * kit.ease_out(swipe)
    # The band is drawn into a mask as well as onto the frame: words go down
    # white, then again in dark only where the band is, so a word the swipe
    # is halfway across is dark on yellow and white on black at once.
    band = Image.new("L", st.size, 0)
    bd = ImageDraw.Draw(band)
    for k, (idx, w, x, y, wd) in enumerate(lit):
        if reach <= 0:
            break
        span = min(widths[k], reach)
        reach -= widths[k]
        lead = pad if k == 0 or lit[k - 1][3] != y else 0
        box = (x - lead, y - size * 0.62, x + span, y + size * 0.58)
        st.rect(*box, fill=accent)
        bd.rectangle(st.box(*box), fill=255)
    for idx, w, x, y, wd in laid:
        st.text((x, y), w, "display", size, INK, anchor="lm")
    if lit and band.getbbox():
        dark = st.layer()
        for idx, w, x, y, wd in lit:
            dark.text((x, y), w, "display", size, "#111111", anchor="lm")
        dark.img.putalpha(ImageChops.multiply(dark.img.getchannel("A"), band))
        st.img.alpha_composite(dark.img)


def _shot_title(st, cue, u, dur, ctx):
    swipe = kit.progress(u, 0.12, min(0.5, dur * 0.35))
    _rich_title(st, cue["text"], cue.get("hot", ""), ctx.accent, kit.H / 2, swipe)
    return swipe >= 1


def _shot_stat(st, cue, u, dur, ctx):
    s = kit.ease_back(kit.progress(u, 0, 0.28))
    size, _ = kit.fit(cue["value"], "display", 300, 1500, 1, floor=80)
    st.text((kit.W / 2, kit.H * 0.44), cue["value"], "display", size * max(0.2, s),
            ctx.accent, anchor="mm")
    if cue.get("label"):
        a = kit.progress(u, 0.18, 0.2)
        st.text((kit.W / 2, kit.H * 0.44 + size * 0.62 + 40), cue["label"], "sans_bold",
                56, kit.rgba(INK, int(255 * a)), anchor="mt")
    return u > 0.45


def _shot_logo(st, cue, u, dur, ctx):
    s = kit.ease_back(kit.progress(u, 0, 0.32), 2.4)
    if s <= 0.01:
        return False
    px = 120 * s
    tw, _ = kit.measure(cue["text"], "display", px)
    pad = 70 * s
    cy = kit.H * (0.45 if cue.get("sub") else 0.5)
    st.rect(kit.W / 2 - tw / 2 - pad, cy - px * 0.85, kit.W / 2 + tw / 2 + pad, cy + px * 0.85,
            fill=kit.mix("#1B2030", ctx.accent, 0.12), outline=ctx.accent, width=5 * s,
            radius=40 * s)
    st.text((kit.W / 2, cy), cue["text"], "display", px, INK, anchor="mm")
    if cue.get("sub"):
        a = kit.progress(u, 0.25, 0.2)
        st.text((kit.W / 2, cy + px + 70), cue["sub"], "sans_bold", 50,
                kit.rgba(INK_DIM, int(255 * a)), anchor="mt")
    return u > 0.5


def _shot_code(st, cue, u, dur, ctx):
    lines = cue["lines"]
    n = len(lines)
    px = 46 if n <= 5 else 40 if n <= 7 else 34
    longest = max(kit.measure(l, "mono", px)[0] for l in lines)
    if longest > 1440:
        px *= 1440 / longest
    lh = px * 1.55
    w = min(1600, max(980, longest + 220))
    h = 56 + 60 + lh * n + 40
    x0, y0 = (kit.W - w) / 2, (kit.H - h) / 2
    _window(st, x0, y0, x0 + w, y0 + h, f"main.{cue['lang']}")
    # Lines arrive in under half the shot, so the hot line has time to land.
    budget = max(0.3, min(0.5 * dur, 0.16 * n))
    per = budget / n
    hot = cue.get("hot", 0)
    lit = hot and u > budget + 0.15
    cursor = None
    for i, line in enumerate(lines):
        start = i * per
        if u < start:
            break
        f = kit.progress(u, start, per * 0.9)
        shown = line[: max(1, int(round(len(line) * f)))] if f < 1 else line
        y = y0 + 56 + 44 + lh * i
        if lit and i + 1 == hot:
            st.wash(x0 + 8, y - lh * 0.12, x0 + w - 8, y + lh * 0.88,
                    kit.rgba(ctx.accent, 38))
            st.rect(x0 + 8, y - lh * 0.12, x0 + 16, y + lh * 0.88, fill=ctx.accent)
        st.text((x0 + 40, y + lh * 0.38), str(i + 1), "mono", px * 0.8,
                kit.rgba("#4B5468"), anchor="lm")
        x = x0 + 110
        for kind, text in tokens(shown, cue["lang"]):
            color = COLORS[kind]
            if lit and i + 1 != hot:
                color = kit.mix(color, "#151922", 0.62)
            st.text((x, y + lh * 0.38), text, "mono", px, color, anchor="lm")
            x += kit.advance(text, "mono", px)
        cursor = (x, y)
    if cursor and (int(u * 2.4) % 2 == 0 or u < budget):
        cx, cy = cursor
        st.wash(cx + 4, cy, cx + 4 + px * 0.55, cy + lh * 0.76, kit.rgba(ctx.accent, 200))
    return False


def _shot_term(st, cue, u, dur, ctx):
    out = cue.get("out") or []
    px = 42
    lh = px * 1.5
    w, h = 1480, 56 + 60 + lh * (1 + len(out)) + 50
    x0, y0 = (kit.W - w) / 2, (kit.H - h) / 2
    _window(st, x0, y0, x0 + w, y0 + h, "zsh", ground="#0B0D11")
    type_t = min(0.9, 0.4 * dur, 0.035 * len(cue["cmd"]))
    f = kit.progress(u, 0.05, type_t)
    shown = cue["cmd"][: int(round(len(cue["cmd"]) * f))]
    y = y0 + 56 + 40 + lh * 0.4
    st.text((x0 + 40, y), "~", "mono_bold", px, CYAN, anchor="lm")
    st.text((x0 + 84, y), "$", "mono_bold", px, "#28C840", anchor="lm")
    st.text((x0 + 130, y), shown, "mono", px, INK, anchor="lm")
    if f < 1 or int(u * 2.4) % 2 == 0:
        cx = x0 + 130 + kit.advance(shown, "mono", px) + 6
        st.wash(cx, y - lh * 0.34, cx + px * 0.55, y + lh * 0.34, kit.rgba(INK, 200))
    for i, line in enumerate(out):
        if u < 0.05 + type_t + 0.12 + i * 0.07:
            break
        color = "#FF6B6B" if re.search(r"\b(error|fail|denied)\b", line, re.I) else \
            "#28C840" if re.search(r"\b(ok|done|success|passed)\b", line, re.I) else INK_DIM
        st.text((x0 + 40, y + lh * (i + 1)), line, "mono", px * 0.9, color, anchor="lm")
    return False


def _shot_diagram(st, cue, u, dur, ctx):
    nodes = cue["nodes"]
    n = len(nodes)
    bw, bh = min(380, 1500 / n - 110), 170
    gap = (1600 - bw * n) / max(1, n - 1)
    x_start = (kit.W - (bw * n + gap * (n - 1))) / 2
    cy = kit.H * (0.54 if cue.get("label") else 0.5)
    step = min(0.32, 0.6 * dur / n)
    if cue.get("label"):
        st.text((kit.W / 2, cy - bh / 2 - 110), cue["label"], "display", 60, INK, anchor="mm")
    for i, label in enumerate(nodes):
        f = kit.progress(u, i * step, 0.26)
        if f <= 0:
            break
        s = kit.ease_back(f)
        x = x_start + i * (bw + gap)
        cx = x + bw / 2
        hw, hh = bw / 2 * s, bh / 2 * s
        color = ctx.accent if i == n - 1 else CYAN
        st.rect(cx - hw, cy - hh, cx + hw, cy + hh, fill=kit.mix("#161B26", color, 0.1),
                outline=color, width=5, radius=22)
        size, lines = kit.fit(label, "sans_bold", 50 * s, bw - 40, 2, floor=10)
        for li, line in enumerate(lines):
            st.text((cx, cy + (li - (len(lines) - 1) / 2) * size * 1.15), line, "sans_bold",
                    size, INK, anchor="mm")
        if i:
            a0 = x - gap + 18
            ae = kit.lerp(a0, x - 22, kit.ease_out(f))
            st.draw.line(st.box(a0, cy, ae, cy), fill=kit.rgba(INK_DIM), width=max(1, st.p(6)))
            if f > 0.6:
                st.draw.polygon([(st.p(ae + 4), st.p(cy)), (st.p(ae - 22), st.p(cy - 16)),
                                 (st.p(ae - 22), st.p(cy + 16))], fill=kit.rgba(INK_DIM))
    return u > n * step + 0.3


def _shot_meme(st, cue, u, dur, ctx, picture):
    if picture is not None:
        key = ("fb_meme", id(picture), ctx.k)
        if key not in ctx.cache:
            ctx.cache[key] = kit.cover(picture, st.size[0], st.size[1]).convert("RGBA")
        st.img.alpha_composite(ctx.cache[key])
    else:
        st.img.paste(kit.rgba("#3A0E12"), (0, 0, *st.size))
        st.text((kit.W / 2, kit.H / 2), "[ visual not found ]", "mono", 48, "#FF9B9B",
                anchor="mm")
    _meme_text(st, cue)
    return False


def _meme_text(st, cue) -> None:
    """The caption, top and bottom, in outlined impact-style type."""
    for text, y, anchor in ((cue.get("top"), 70, "mt"), (cue.get("bottom"), kit.H - 70, "mb")):
        if not text:
            continue
        size, lines = kit.fit(text.upper(), "display", 96, 1700, 2, floor=40)
        step = size * 1.08
        for i, line in enumerate(lines if anchor == "mt" else reversed(lines)):
            yy = y + i * step if anchor == "mt" else y - i * step
            st.text((kit.W / 2, yy), line, "display", size, "#FFFFFF", anchor=anchor,
                    stroke=size * 0.08, stroke_fill="#000000")


def _shot_post(st, cue, u, dur, ctx):
    f = kit.ease_out(kit.progress(u, 0, 0.22))
    w = 1180
    size, lines = kit.fit(cue["text"], "sans", 54, w - 120, 5, floor=30)
    h = 200 + len(lines) * size * 1.32 + 110
    x0 = (kit.W - w) / 2
    y0 = (kit.H - h) / 2 + (1 - f) * 60
    card = st.layer()
    card.rect(x0, y0, x0 + w, y0 + h, fill="#15181F", outline="#2C3240", width=2, radius=28)
    card.draw.ellipse(card.box(x0 + 50, y0 + 46, x0 + 140, y0 + 136),
                      fill=kit.rgba(ctx.accent))
    card.text((x0 + 95, y0 + 91), cue["handle"][1:2].upper(), "display", 46, "#111", anchor="mm")
    card.text((x0 + 166, y0 + 66), cue["handle"][1:].replace("_", " ").title(), "sans_bold",
              40, INK, anchor="lm")
    card.text((x0 + 166, y0 + 112), cue["handle"], "sans_med", 32, INK_DIM, anchor="lm")
    for i, line in enumerate(lines):
        card.text((x0 + 60, y0 + 186 + i * size * 1.32), line, "sans", size, INK)
    yb = y0 + h - 64
    for j, label in enumerate(("12.4K reposts", "88K likes", "3.1M views")):
        card.text((x0 + 60 + j * 330, yb), label, "sans_med", 30, INK_DIM, anchor="lm")
    st.img.alpha_composite(kit.with_alpha(card.img, f) if f < 1 else card.img)
    return u > 0.3


FOCUS = {"left": 0.18, "center": 0.5, "right": 0.82}


def _shot_image(st, cue, u, dur, ctx, picture):
    """The picture, full-frame. The push-in happens in `frame` so the drawn
    shot itself is still and can be cached."""
    if picture is not None:
        key = ("fb_img", id(picture), cue["focus"], ctx.k)
        if key not in ctx.cache:
            # Oversized so the push-in never shows an edge.
            w, h = round(st.size[0] * 1.12), round(st.size[1] * 1.12)
            img = kit.cover(picture, w, h, (FOCUS[cue["focus"]], 0.45)).convert("RGBA")
            ctx.cache[key] = img.crop(((w - st.size[0]) // 2, (h - st.size[1]) // 2,
                                       (w - st.size[0]) // 2 + st.size[0],
                                       (h - st.size[1]) // 2 + st.size[1]))
        st.img.alpha_composite(ctx.cache[key])
    elif cue.get("label"):
        st.text((kit.W / 2, kit.H / 2), cue["label"], "display", 120, INK, anchor="mm")
    if picture is not None:
        _image_label(st, cue)
    return True


def _image_label(st, cue) -> None:
    if cue.get("label"):
        w = kit.advance(cue["label"], "sans_bold", 40) + 48
        st.wash(70, kit.H - 140, 70 + w, kit.H - 76, (0, 0, 0, 170), radius=10)
        st.text((94, kit.H - 108), cue["label"], "sans_bold", 40, INK, anchor="lm")


def _moving(beat: kit.Beat, ctx, i: int, t: float) -> Image.Image | None:
    """A picture or meme cue over a clip or GIF: this frame of it, captioned.

    The clip runs on the paragraph's clock, so cutting away and back lands
    later in it, the way B-roll does. None when there is no clip, or it will
    not decode — the still poster is drawn instead.
    """
    cue = beat.cues[i]
    if beat.motion is None or cue["kind"] not in ("image", "meme"):
        return None
    lead = beat.cues[_image_run(beat, i)[0]] if cue["kind"] == "image" else cue
    fx = FOCUS.get(lead.get("focus", "center"), 0.5)
    base = kit.footage(ctx, beat.motion, *ctx.size, (fx, 0.45)).frame(t)
    if base is None:
        return None
    key = ("fb_over", i)
    if key not in beat.extra:
        st = kit.Stage(ctx.k, (0, 0, 0, 0))
        (_meme_text if cue["kind"] == "meme" else _image_label)(st, lead)
        beat.extra[key] = st.img if st.img.getbbox() else None
    over = beat.extra[key]
    if over is None:
        return base
    return Image.alpha_composite(base.convert("RGBA"), over).convert("RGB")


SHOTS = {"title": _shot_title, "stat": _shot_stat, "logo": _shot_logo, "code": _shot_code,
         "term": _shot_term, "diagram": _shot_diagram, "post": _shot_post}


# ------------------------------------------------------------------- frame
def _image_run(beat: kit.Beat, i: int) -> tuple[int, int]:
    """The first and last cue of the unbroken run of picture cues around `i`.

    Back-to-back picture cues are one shot: one framing, one push.
    """
    a = b = i
    while a > 0 and beat.cues[a - 1]["kind"] == "image":
        a -= 1
    while b + 1 < len(beat.cues) and beat.cues[b + 1]["kind"] == "image":
        b += 1
    return a, b


def frame(beat: kit.Beat, ctx, t: float) -> Image.Image:
    i = beat.at(t)
    cue = beat.cues[i]
    start, end = beat.times[i]
    u, dur = t - start, max(0.1, end - start)
    settled_key = ("fb_settled", beat.slide.id, i)
    cached = beat.extra.get(settled_key)
    moving = _moving(beat, ctx, i, t)
    if moving is not None:
        img = moving
    elif cached is not None:
        img = cached
    else:
        st = kit.Stage(ctx.k, base=_ground(ctx))
        if cue["kind"] == "meme":
            settled = _shot_meme(st, cue, u, dur, ctx, beat.picture)
        elif cue["kind"] == "image":
            settled = _shot_image(st, beat.cues[_image_run(beat, i)[0]], u, dur, ctx,
                                  beat.picture)
        else:
            settled = SHOTS[cue["kind"]](st, cue, u, dur, ctx)
        img = st.rgb()
        if settled:
            beat.extra[settled_key] = img
    # Every cut lands with a punch-in; the meme lands with a shake and keeps
    # creeping in, which is what sells it as a reaction rather than a slide.
    if cue["kind"] == "meme":
        dx, dy = kit.shake(u, i * 7 + beat.index, 22 * ctx.k, 0.35)
        return kit.punch(img, 1.04 + 0.05 * kit.clamp(u / dur), dx, dy)
    if cue["kind"] == "image":
        # B-roll: in hard, then one steady push toward the side it framed.
        # The push belongs to the run of picture cues, not to each cue —
        # restarting it on every cue read as the same zoom looping.
        a, b = _image_run(beat, i)
        ru = t - beat.times[a][0]
        rdur = max(0.2, beat.times[b][1] - beat.times[a][0])
        hit = 0.06 * (1 - kit.ease_out(kit.progress(ru, 0, 0.14)))
        push = 0.07 * kit.clamp(ru / rdur)
        side = {"left": -1, "center": 0, "right": 1}[beat.cues[a]["focus"]]
        return kit.punch(img, 1.0 + hit + push, side * push * 260 * ctx.k, 0)
    zoom = 1 + 0.09 * (1 - kit.ease_out(kit.progress(u, 0, 0.16)))
    return kit.punch(img, zoom)


def chapter(ctx, title: str, base: Image.Image, u: float) -> Image.Image:
    """A terminal prompt types the next chapter's name."""
    lo, hi = GROUNDS.get(ctx.look, GROUNDS[""])
    st = kit.dim_to(base, lo, 0.94 * kit.ease_out(kit.progress(u, 0, 0.3)))
    text = title
    shown = text[:int(len(text) * kit.progress(u, 0.2, 0.7))]
    size, lines = kit.fit(title, "mono_bold", 96, kit.W - 400, 2, floor=44)
    x = 130
    y = kit.H / 2 - size * 0.7
    st.text((x, y - size * 1.25), "// next chapter", "mono", 34, INK_DIM, anchor="lm")
    done, drawn, last_y = 0, "", y
    for i, line in enumerate(lines):
        part = shown[done:done + len(line) + 1].strip()
        done += len(line) + 1
        if not part and i:
            break
        drawn = ("> " if i == 0 else "  ") + part
        last_y = y + i * size * 1.25
        st.text((x, last_y), drawn, "mono_bold", size, INK, anchor="lm")
    if shown != text or int(u * 2.4) % 2 == 0:
        w = kit.advance(drawn, "mono_bold", size)
        st.rect(x + w + 10, last_y - size * 0.45, x + w + 10 + size * 0.5,
                last_y + size * 0.45, fill=CYAN)
    return st.rgb()

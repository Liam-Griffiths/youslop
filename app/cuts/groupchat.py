"""Group Chat: the story told as the thread it happened in.

A message thread fills the middle of the frame over a blurred, darkened copy
of the paragraph's picture. As the narrator tells the story, the messages
arrive — the other side's after a moment of typing dots, the narrator's own
in blue on the right — with photos dropped into the thread and grey system
lines for the time jumps and the "left the group" moments. The thread carries
over from paragraph to paragraph, so the conversation scrolls on through the
whole video until a chapter starts a new one.

Built for storytime: Reddit and forum readings, relationship and family drama,
roommate and landlord sagas, scam-baiting, workplace stories — the content
that already lives in screenshots of chats.
"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import kit

KEY = "groupchat"
LABEL = "Group Chat"
FOR = "Storytime, Reddit readings, drama"
BLURB = ("The story plays out as a message thread — typing dots, bubbles — "
         "cutting away to the scene and back as it goes.")
LOOKS = [{"key": "", "label": "Dark mode"}, {"key": "light", "label": "Light mode"}]
FALLBACK_KIND = "msg"
MIN_HOLD = 0.9

KINDS = {"msg", "photo", "notice", "image"}
FOCUS = {"left": 0.2, "center": 0.5, "right": 0.8}

PLAN = """The format is a storytime video staged as a message thread: the frame is
a chat window, and as the narrator tells the story the messages arrive in it.
The narrator is "me" (blue bubbles on the right); everyone else is on the left
under their name. The thread carries on from paragraph to paragraph.

Cue kinds — every cue is an object with "kind", "on" and the fields listed:
- {"kind": "msg", "from": "me" or a first name / role ("Mom", "Landlord"),
   "text": "the message, max 20 words, written like a real text"}
- {"kind": "photo", "from": "me" or a name}
  The paragraph's picture sent as a photo. At most one per paragraph.
- {"kind": "notice", "text": "a system line: a time ('Tuesday 11:42 PM'),
   'Jake left the group', 'Missed call from Mom'"}
- {"kind": "image", "focus": "left|center|right", "caption": "optional, max 6 words"}
  CUTS AWAY from the thread to the paragraph's picture, full-frame, pushing
  in — the scene the messages are about. The next message cuts back to the
  thread. Use one or two per paragraph, between messages, so the video moves
  between the chat and the world it's happening in; vary "focus".

Rules: 3-6 cues per paragraph. Write the messages the story describes or
implies — what was actually said, in text-speak if it fits the person, never
the narration repeated. Keep each person's voice consistent across the video.
Use the same names for the same people in every paragraph. When the narration
is pure reflection with nothing said, give it one "notice" or one short "me"
message."""

KIND_DOC = "msg (from me / a name) · image (cut away to the picture) · photo · notice"

PANEL_W = 1040
PANEL_X = (kit.W - PANEL_W) / 2
TOP, BOTTOM = 34, kit.H - 34
HEADER = 120
INPUT = 96
TEXT_PX = 40
MAX_BUBBLE = 700
SENDER_COLORS = ["#FF9F43", "#2ED1A2", "#C08BFF", "#FF6B9A", "#58B9FF", "#E8D44D"]

THEMES = {
    "": {"panel": "#0B0B0F", "header": "#16161C", "them": "#26262E", "them_ink": "#F2F2F5",
         "me": "#2E7CF6", "me_ink": "#FFFFFF", "muted": "#8C8C99", "input": "#1C1C23"},
    "light": {"panel": "#FFFFFF", "header": "#F4F4F7", "them": "#E9E9EE", "them_ink": "#111114",
              "me": "#2E7CF6", "me_ink": "#FFFFFF", "muted": "#8A8A94", "input": "#F0F0F4"},
}


def _s(v, n):
    return str(v or "").strip()[:n]


def normalise(c: dict) -> dict | None:
    kind = str(c.get("kind") or "").strip().lower()
    if kind == "typing":
        return None
    if kind not in KINDS:
        return None
    who = _s(c.get("from"), 18) or "me"
    if who.lower() in ("me", "i", "narrator", "you"):
        who = "me"
    if kind == "msg":
        text = _s(c.get("text"), 160)
        return {"kind": kind, "from": who, "text": text} if text else None
    if kind == "photo":
        return {"kind": kind, "from": who}
    if kind == "image":
        focus = str(c.get("focus") or "center").lower()
        return {"kind": kind, "focus": focus if focus in FOCUS else "center",
                "caption": " ".join(str(c.get("caption") or "").split()[:6])[:48]}
    text = _s(c.get("text"), 50)
    return {"kind": kind, "text": text} if text else None


def derive(slide) -> list[dict]:
    """Quoted speech becomes the other side's messages; the rest is mine."""
    import re
    quotes = re.findall(r"[\"“]([^\"”]{3,140})[\"”]", slide.narration)
    if quotes:
        msgs = [{"kind": "msg", "from": "Them" if i % 2 == 0 else "me", "text": q,
                 "on": kit.head(q)} for i, q in enumerate(quotes[:4])]
    else:
        parts = kit.clauses(slide.narration, max_words=14, min_words=5)
        msgs = [{"kind": "msg", "from": "me", "text": kit.short(p, 14), "on": kit.head(p)}
                for p in parts[1:3]]
    # Open on the scene, then cut to the thread; a long one cuts away again.
    cues = [{"kind": "image", "focus": "center", "caption": "", "on": ""}] + msgs[:1]
    if len(msgs) > 1:
        cues += [{"kind": "image", "focus": "right", "caption": "", "on": msgs[1]["on"]}]
        cues += [dict(m, on="") for m in msgs[1:2]] + msgs[2:]
    return cues


# -------------------------------------------------------------- the thread
def _theme(ctx) -> dict:
    return THEMES.get(ctx.look, THEMES[""])


def _senders(ctx) -> list[str]:
    key = "gc_senders"
    if key not in ctx.cache:
        from . import BY_KEY, cues_for
        names: list[str] = []
        for s in ctx.project.slides:
            for c in cues_for(BY_KEY[KEY], s):
                who = c.get("from")
                if who and who != "me" and who not in names:
                    names.append(who)
        ctx.cache[key] = names
    return ctx.cache[key]


def _title(ctx) -> str:
    names = _senders(ctx)
    if not names:
        return "Notes to self"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:2]) + (f" +{len(names) - 2}" if len(names) > 2 else "")


def _rounded(img: Image.Image, r: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), r, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _bubble(ctx, cue: dict, picture, first_of_run: bool) -> tuple[Image.Image, float, str]:
    """A message as a tile, its height in 1080p px, and which side it sits."""
    th = _theme(ctx)
    k = ctx.k
    kind = cue["kind"]
    if kind == "notice":
        h = 64
        st = kit.Stage.sized(PANEL_W, h, k)
        st.text((PANEL_W / 2, h / 2), cue["text"], "sans_med", 28, th["muted"], anchor="mm")
        return st.img, h, "mid"
    me = cue["from"] == "me"
    name_h = 0 if me or not first_of_run else 40
    senders = _senders(ctx)
    name_color = SENDER_COLORS[senders.index(cue["from"]) % len(SENDER_COLORS)] if (
        cue["from"] in senders) else th["muted"]
    if kind == "photo":
        pw, ph = 560, 400
        st = kit.Stage.sized(pw + 10, ph + name_h + 10, k)
        if name_h:
            st.text((20, 18), cue["from"], "sans_bold", 28, name_color, anchor="lm")
        if picture is not None:
            img = _rounded(kit.cover(picture, st.p(pw), st.p(ph)), st.p(34))
            st.img.alpha_composite(img, (0, st.p(name_h)))
        else:
            st.rect(0, name_h, pw, name_h + ph, fill=th["them"], radius=34)
            st.text((pw / 2, name_h + ph / 2), "Photo", "sans_med", 34, th["muted"], anchor="mm")
        return st.img, ph + name_h + 14, "right" if me else "left"
    lines = kit.wrap(cue["text"], "sans_med", TEXT_PX, MAX_BUBBLE - 64)[:7]
    lw = max(kit.advance(l, "sans_med", TEXT_PX) for l in lines) if lines else 40
    bw, bh = lw + 64, 34 + len(lines) * TEXT_PX * 1.3
    st = kit.Stage.sized(bw + 10, bh + name_h + 10, k)
    if name_h:
        st.text((20, 18), cue["from"], "sans_bold", 28, name_color, anchor="lm")
    st.rect(0, name_h, bw, name_h + bh, fill=th["me"] if me else th["them"], radius=36)
    for i, line in enumerate(lines):
        st.text((32, name_h + 17 + i * TEXT_PX * 1.3 + TEXT_PX * 0.98), line, "sans_med",
                TEXT_PX, th["me_ink"] if me else th["them_ink"], anchor="ls")
    return st.img, bh + name_h + 14, "right" if me else "left"


def _history(ctx, beat) -> list[tuple[dict, object]]:
    """The last dozen messages before this paragraph, since the last chapter."""
    from . import BY_KEY, cues_for, load_picture
    out: list[tuple[dict, object]] = []
    for s in ctx.project.slides:
        if s.id == beat.slide.id:
            break
        if (getattr(s, "chapter", "") or "").strip():
            out = []
        cues = cues_for(BY_KEY[KEY], s)
        pic = load_picture(ctx, s, None) if any(c["kind"] == "photo" for c in cues) else None
        out += [(c, pic) for c in cues if c["kind"] != "image"]
    if (getattr(beat.slide, "chapter", "") or "").strip():
        return []
    return out[-12:]


def _tiles(ctx, beat) -> list[dict]:
    if "gc_tiles" in beat.extra:
        return beat.extra["gc_tiles"]
    hist = _history(ctx, beat)
    seq = hist + [(c, beat.picture) for c in beat.cues if c["kind"] != "image"]
    # How many of this paragraph's messages are already in the thread when
    # cue i starts — cut-aways don't add to it.
    before, n = [], 0
    for c in beat.cues:
        before.append(n)
        n += c["kind"] != "image"
    beat.extra["gc_before"] = before
    tiles = []
    last_from = None
    for cue, pic in seq:
        who = cue.get("from") if cue["kind"] != "notice" else None
        img, h, side = _bubble(ctx, cue, pic, who != last_from)
        tiles.append({"img": img, "h": h, "side": side, "from": who})
        last_from = who
    beat.extra["gc_tiles"] = tiles
    beat.extra["gc_hist"] = len(hist)
    return tiles


def _ground(ctx, beat) -> Image.Image:
    key = "gc_ground"
    if key in beat.extra:
        return beat.extra[key]
    size = ctx.size
    if beat.picture is not None:
        small = kit.cover(beat.picture, max(2, size[0] // 8), max(2, size[1] // 8))
        g = small.filter(ImageFilter.GaussianBlur(3)).resize(size, Image.BILINEAR).convert("RGBA")
        g.alpha_composite(Image.new("RGBA", size, (0, 0, 0, 150)))
    else:
        g = Image.new("RGBA", size, kit.rgba(kit.mix("#0B0B10", ctx.accent, 0.18)))
    st = kit.Stage(ctx.k, base=g)
    th = _theme(ctx)
    shadow = Image.new("RGBA", (st.p(PANEL_W), st.p(BOTTOM - TOP)), (0, 0, 0, 255))
    st.img.alpha_composite(kit.shadow_of(shadow, st.p(30), 170),
                           (st.p(PANEL_X) - st.p(62), st.p(TOP) - st.p(50)))
    st.rect(PANEL_X, TOP, PANEL_X + PANEL_W, BOTTOM, fill=th["panel"], radius=46)
    # Header: a round avatar with the initial, the thread's name, a status.
    st.rect(PANEL_X, TOP, PANEL_X + PANEL_W, TOP + HEADER, fill=th["header"], radius=46)
    st.rect(PANEL_X, TOP + HEADER - 46, PANEL_X + PANEL_W, TOP + HEADER, fill=th["header"])
    title = _title(ctx)
    ax, ay = PANEL_X + 80, TOP + HEADER / 2
    st.draw.ellipse(st.box(ax - 36, ay - 36, ax + 36, ay + 36),
                    fill=kit.rgba(SENDER_COLORS[0] if _senders(ctx) else ctx.accent))
    st.text((ax, ay + 2), title[:1].upper(), "sans_bold", 36, "#FFFFFF", anchor="mm")
    st.text((ax + 62, ay - 16), title, "sans_bold", 36, th["them_ink"], anchor="lm")
    st.text((ax + 62, ay + 24), "online" if len(_senders(ctx)) <= 1 else
            f"{len(_senders(ctx)) + 1} people", "sans_med", 26, th["muted"], anchor="lm")
    # Input bar.
    iy = BOTTOM - INPUT
    st.rect(PANEL_X + 30, iy + 18, PANEL_X + PANEL_W - 120, BOTTOM - 22, fill=th["input"],
            radius=30)
    st.text((PANEL_X + 64, (iy + BOTTOM) / 2 - 2), "Message", "sans_med", 30, th["muted"],
            anchor="lm")
    cx = PANEL_X + PANEL_W - 70
    st.draw.ellipse(st.box(cx - 30, iy + 18, cx + 30, iy + 78), fill=kit.rgba(th["me"]))
    st.text((cx, iy + 47), "↑", "sans_bold", 36, "#FFFFFF", anchor="mm")
    beat.extra[key] = st.img
    return st.img


def _typing(st: kit.Stage, x: float, y: float, u: float, th: dict) -> None:
    st.rect(x, y, x + 130, y + 74, fill=th["them"], radius=37)
    for j in range(3):
        bob = (1 + math.sin(u * 9 - j * 0.9)) / 2
        c = kit.mix(th["muted"], th["them_ink"], bob * 0.6)
        cx, cy = x + 36 + j * 29, y + 37 - bob * 6
        st.draw.ellipse(st.box(cx - 9, cy - 9, cx + 9, cy + 9), fill=c)


def _caption(st: kit.Stage, cue: dict) -> None:
    if cue.get("caption"):
        size, lines = kit.fit(cue["caption"], "sans_bold", 64, 1500, 2, floor=36)
        y = kit.H - 90 - (len(lines) - 1) * size * 1.2
        for j, line in enumerate(lines):
            st.text((kit.W / 2, y + j * size * 1.2), line, "sans_bold", size, "#FFFFFF",
                    anchor="ms", stroke=size * 0.07, stroke_fill="#000000")


def _cutaway(beat: kit.Beat, ctx, cue: dict, u: float, dur: float, t: float) -> Image.Image:
    """The paragraph's picture — or its clip, playing — full-frame, pushing in
    toward its focus."""
    fx = FOCUS[cue["focus"]]
    moving = (kit.footage(ctx, beat.motion, *ctx.size, (fx, 0.45)).frame(t)
              if beat.motion is not None else None)
    if moving is not None:
        key = ("gc_cap", cue.get("caption", ""))
        if key not in beat.extra:
            st = kit.Stage(ctx.k, (0, 0, 0, 0))
            _caption(st, cue)
            beat.extra[key] = st.img if st.img.getbbox() else None
        over = beat.extra[key]
        base = moving if over is None else Image.alpha_composite(
            moving.convert("RGBA"), over).convert("RGB")
    else:
        key = ("gc_cut", cue["focus"], cue.get("caption", ""))
        base = beat.extra.get(key)
        if base is None:
            st = kit.Stage(ctx.k)
            w, h = round(st.size[0] * 1.12), round(st.size[1] * 1.12)
            img = kit.cover(beat.picture, w, h, (fx, 0.45)).convert("RGBA")
            st.img.alpha_composite(img.crop(((w - st.size[0]) // 2, (h - st.size[1]) // 2,
                                             (w - st.size[0]) // 2 + st.size[0],
                                             (h - st.size[1]) // 2 + st.size[1])))
            _caption(st, cue)
            base = beat.extra[key] = st.rgb()
    side = {"left": -1, "center": 0, "right": 1}[cue["focus"]]
    push = 0.08 * kit.clamp(u / dur)
    return kit.punch(base, 1.0 + push, side * push * 240 * ctx.k, 0)


def frame(beat: kit.Beat, ctx, t: float) -> Image.Image:
    th = _theme(ctx)
    tiles = _tiles(ctx, beat)
    n_hist = beat.extra["gc_hist"]
    i = beat.at(t)
    start, end = beat.times[i]
    u = t - start
    cue = beat.cues[i]
    if cue["kind"] == "image" and beat.picture is not None:
        return _cutaway(beat, ctx, cue, u, max(0.2, end - start), t)
    # The other side types before their message lands; mine just sends. A
    # cut-away with no picture to cut to just holds the thread.
    typing = 0.0
    if cue["kind"] not in ("notice", "image") and cue.get("from") != "me":
        typing = min(0.7, (end - start) * 0.3)
    arrive = 1.0 if cue["kind"] == "image" else kit.ease_out(kit.progress(u, typing, 0.28))
    settled_key = ("gc_settled", i)
    if arrive >= 1 and settled_key in beat.extra:
        return beat.extra[settled_key]
    adds = cue["kind"] != "image"
    shown = n_hist + beat.extra["gc_before"][i] + (1 if adds and arrive > 0 else 0)
    st = kit.Stage(ctx.k, base=_ground(ctx, beat))
    clip = st.layer()
    floor = BOTTOM - INPUT - 16
    typing_h = 90 if (typing and arrive <= 0) else 0
    # Stack from the bottom up; the newest message pushes the rest up as it
    # arrives rather than appearing in a gap left for it.
    y = floor - typing_h
    if adds and arrive > 0:
        y += tiles[shown - 1]["h"] * (1 - arrive)
    me_last = max((j for j in range(shown) if tiles[j]["side"] == "right"), default=-1)
    for j in range(shown - 1, -1, -1):
        tile = tiles[j]
        y -= tile["h"]
        if y + tile["h"] < TOP + HEADER:
            break
        tw = tile["img"].width / ctx.k
        x = (PANEL_X + PANEL_W - 34 - tw if tile["side"] == "right" else
             PANEL_X + 34 if tile["side"] == "left" else PANEL_X)
        a = arrive if adds and j == shown - 1 and arrive > 0 else 1.0
        clip.paste(tile["img"], x, y + (1 - a) * 30, alpha=a)
        if j == me_last and j == shown - 1 and tile["side"] == "right" and a >= 1:
            clip.text((PANEL_X + PANEL_W - 44, y + tile["h"] - 4), "Delivered", "sans_med", 22,
                      th["muted"], anchor="rt")
    if typing_h:
        _typing(clip, PANEL_X + 34, floor - 82, u, th)
    # Messages scroll under the header, not over it.
    mask = Image.new("L", st.size, 0)
    ImageDraw.Draw(mask).rectangle(st.box(PANEL_X, TOP + HEADER, PANEL_X + PANEL_W,
                                          BOTTOM - INPUT), fill=255)
    clip.img.putalpha(ImageChops.multiply(clip.img.getchannel("A"), mask))
    st.img.alpha_composite(clip.img)
    out = st.rgb()
    if arrive >= 1:
        beat.extra[settled_key] = out
    return out


def chapter(ctx, title: str, base: Image.Image, u: float) -> Image.Image:
    """The thread dims and a system notice announces what comes next."""
    th = THEMES.get(ctx.look) or THEMES[""]
    st = kit.dim_to(base, th["panel"], 0.8 * kit.ease_out(kit.progress(u, 0, 0.4)))
    t = kit.ease_out(kit.progress(u, 0.15, 0.4))
    layer = st.layer()
    size, lines = kit.fit(title, "sans_bold", 78, PANEL_W - 200, 2, floor=44)
    h = len(lines) * size * 1.2 + 120
    layer.rect(kit.W / 2 - PANEL_W / 2 + 40, kit.H / 2 - h / 2, kit.W / 2 + PANEL_W / 2 - 40,
               kit.H / 2 + h / 2, fill=th["header"], radius=40)
    layer.text((kit.W / 2, kit.H / 2 - h / 2 + 40), "NEW CHAPTER", "sans_med", 26,
               th["muted"], anchor="mm")
    for i, line in enumerate(lines):
        layer.text((kit.W / 2, kit.H / 2 - h / 2 + 100 + i * size * 1.2 + size * 0.5), line,
                   "sans_bold", size, th["them_ink"], anchor="mm")
    st.img.alpha_composite(kit.with_alpha(layer.img, t))
    return st.rgb()

"""The drawn cuts: five more ways to stage a video, each aimed at a channel
the photographic formats do not serve.

    flameboat   rapid-fire tech explainer — code, terminals, memes, hard cuts
    casefile    true crime on a lamp-lit corkboard, joined up with red string
    loudmouth   kinetic type — the words are the video
    groupchat   storytime told as the message thread it happened in
    ticker      money on a markets terminal — rolling figures and drawn charts

Each is a module with the same shape (see `kit.py` for the shared parts):

    KEY, LABEL, FOR, BLURB    what the picker shows
    LOOKS                     the cut's variants, picked with `style.cut_look`
    PLAN                      what the writer is told to put on screen
    normalise(cue) -> dict    one cue, cleaned, or None to drop it
    derive(slide) -> [cues]   cues from the narration, for an unplanned slide
    frame(beat, ctx, t)       one RGB frame, `t` seconds into the paragraph

Cues live on the slide under the cut's key (`slide.cues["flameboat"]`), so
switching a video between cuts keeps what was written for each. A slide with
nothing written for the current cut is drawn from its own narration, the same
promise the board makes: changing format never produces a blank video.
"""
from __future__ import annotations

import math
from pathlib import Path

from ..config import FPS, HEAD_PAD, WIDTH, WORDS_PER_MINUTE
from .. import ffutil
from . import casefile, flameboat, groupchat, kit, loudmouth, ticker

MODULES = [flameboat, casefile, loudmouth, groupchat, ticker]
BY_KEY = {m.KEY: m for m in MODULES}
KEYS = list(BY_KEY)

# Hard cuts between segments. Every cut here either cuts on the clause by
# design or carries its own picture across the seam (the board, the thread),
# and a crossfade over either reads as a mistake. One frame rather than zero,
# so the xfade chain in `render.render` keeps its shape.
HARD_CUT = 1.0 / FPS


def is_cut(fmt: str) -> bool:
    return (fmt or "") in BY_KEY


def info() -> list[dict]:
    """What the format picker and the look selector need."""
    return [{"key": m.KEY, "label": m.LABEL, "for": m.FOR, "blurb": m.BLURB,
             "looks": m.LOOKS, "kinds": getattr(m, "KIND_DOC", "")}
            for m in MODULES]


def transition_for(style) -> float:
    """The crossfade a video's segments are joined with."""
    if is_cut(getattr(style, "format", "")):
        return HARD_CUT
    return max(0.0, float(style.transition))


def normalise(module, cues) -> list[dict]:
    if not isinstance(cues, list):
        return []
    out = []
    for c in cues[:24]:
        if isinstance(c, dict):
            clean = module.normalise(c)
            if clean:
                clean["on"] = str(c.get("on") or "").strip()[:120]
                out.append(clean)
    return out


def cues_for(module, slide) -> list[dict]:
    """The slide's cues for this cut: written if there are any, derived if not."""
    written = normalise(module, (getattr(slide, "cues", None) or {}).get(module.KEY))
    return written or normalise(module, module.derive(slide)) or [
        {"kind": module.FALLBACK_KIND, "text": kit.short(slide.narration, 6), "on": ""}]


def spoken_of(slide, dur: float) -> float:
    take = float((getattr(slide, "take", None) or {}).get("duration") or 0.0)
    if take > 0:
        return min(take, dur)
    return min(dur, max(2.0, slide.word_count / WORDS_PER_MINUTE * 60))


def make_ctx(project, size: tuple[int, int], fps: int, channel=None,
             image_for=None):
    style = project.style
    return kit.Ctx(project=project, k=size[0] / WIDTH, fps=fps,
                   accent=style.accent or "#E8C36A",
                   accent2=getattr(style, "accent2", "") or "#7FA6B8",
                   look=getattr(style, "cut_look", "") or "",
                   channel=channel, image_for=image_for)


def source_for(ctx, slide):
    """The file behind the slide's picture — an image, a clip or a GIF.

    A paragraph holding the picture before it (`picture_every`, or "hold")
    has none of its own: it shows its run's.
    """
    if ctx.image_for is None:
        return None
    memo = ctx.cache.setdefault("sources", {})
    if slide.id not in memo:
        src = ctx.image_for(slide)
        if src is None:
            slides = ctx.project.slides
            at = next((i for i, s in enumerate(slides) if s.id == slide.id), 0)
            for prev in reversed(slides[:at]):
                src = ctx.image_for(prev)
                if src is not None:
                    break
        memo[slide.id] = src
    return memo[slide.id]


def load_picture(ctx, slide, cache_dir: Path | None):
    """The slide's chosen picture as a Pillow image — a clip's or a GIF's
    poster frame, for the places that want a still (a polaroid, a print)."""
    if ctx.image_for is None:
        return None
    memo = ctx.cache.setdefault("pictures", {})
    if slide.id in memo:
        return memo[slide.id]
    from .. import board
    cache_dir = cache_dir or ctx.cache.get("dir")
    if cache_dir is None:
        import tempfile
        cache_dir = Path(tempfile.gettempdir()) / "youslop_cuts"
    src = source_for(ctx, slide)
    img = board._load_photo(src, Path(cache_dir)) if src else None
    if img is not None and max(img.size) > 2200:
        img.thumbnail((2200, 2200))
    memo[slide.id] = img
    return img


def beat_for(module, ctx, slide, length: float, lead: float, spoken: float,
             cache_dir: Path | None = None) -> kit.Beat:
    cues = cues_for(module, slide)
    times = kit.place(slide.narration, cues, spoken, length, lead=lead,
                      min_hold=getattr(module, "MIN_HOLD", 0.35))
    slides = ctx.project.slides
    index = next((i for i, s in enumerate(slides) if s.id == slide.id), 0)
    src = source_for(ctx, slide)
    return kit.Beat(slide=slide, cues=cues, times=times, length=length,
                    spoken=spoken, lead=lead,
                    picture=load_picture(ctx, slide, cache_dir),
                    motion=src if kit.is_motion(src) else None, index=index,
                    last=index == len(slides) - 1)


def render_segment(project, group, seg_len: float, out: Path, *, channel=None,
                   image_for=None, size=None, fps: int = FPS, crf: int = 18,
                   lead_in: float = 0.0, cache_dir: Path | None = None,
                   chapter: tuple[str, str] | None = None, hold: float = 0.0,
                   frames: tuple[int, int] | None = None) -> Path:
    """One held group of paragraphs in the video's cut, to exactly `seg_len`.

    `lead_in` is where the voice starts inside the segment — the opening
    silence of the video, if this is its first paragraph — so the cues land
    on the words rather than that far ahead of them.

    `chapter` is the title of the section that starts next. Its screen takes
    the last `hold` seconds of the segment — the silence the narration leaves
    for it — drawn by the cut's own `chapter()` so it looks like it belongs.
    """
    module = BY_KEY[project.style.format]
    size = size or (WIDTH, round(WIDTH * 9 / 16))
    ctx = make_ctx(project, size, fps, channel, image_for)
    ctx.cache["dir"] = cache_dir
    beats: list[kit.Beat] = []
    spent = 0.0
    for n, (slide, dur) in enumerate(group):
        lead = lead_in if n == 0 else 0.0
        length = (seg_len - spent) if n == len(group) - 1 else min(dur + lead, seg_len - spent)
        spent += length
        if length <= 0.05:
            continue
        beats.append(beat_for(module, ctx, slide, length, lead,
                              spoken_of(slide, dur), cache_dir))

    title = (chapter[0] if chapter else "").strip()
    card_at = seg_len - hold if title and hold > 0.2 else None
    draw_card = getattr(module, "chapter", None) or kit.chapter_screen

    # Frames are counted off the segment's whole length, not beat by beat.
    # Rounding each beat to whole frames could leave the segment a frame short
    # of `seg_len`, and with a one-frame hard cut the join into the next
    # segment then lands past this one's end — ffmpeg's xfade ends the video
    # there and the rest of the render plays over a frozen frame.
    total = frame_count(seg_len, fps)
    # `frames` draws only [a, b) of them — one piece of a long segment, the
    # rest drawn elsewhere at the same time. Every cut draws a frame from its
    # time alone (the editor's stills rely on that), so a piece starting
    # midway looks exactly as it would have in one long run.
    first, stop = frames if frames else (0, total)
    starts = []
    t0 = 0.0
    for beat in beats:
        starts.append(t0)
        t0 += beat.length

    def stream():
        k = 0
        for i in range(first, min(stop, total)):
            t = i / fps
            while k + 1 < len(beats) and t >= starts[k + 1] - 1e-9:
                k += 1
            beat = beats[k]
            frame = module.frame(beat, ctx, min(t - starts[k], max(0.0, beat.length - 1e-3)))
            if card_at is not None and t >= card_at:
                frame = draw_card(ctx, title, frame, t - card_at)
            yield frame

    try:
        # No -t: it trims the last frame whenever `seg_len` falls between two
        # frame times, which is the shortfall the frame count above prevents.
        ok = ffutil.encode_frames(stream(), out, size=ctx.size, fps=fps, crf=crf)
    finally:
        kit.close_footage(ctx)
    if not ok or not out.exists():
        raise RuntimeError(f"Could not encode the {module.LABEL} segment.")
    return out


def frame_count(seg_len: float, fps: int) -> int:
    """Frames in a segment: rounded up, so it is never shorter than asked."""
    return max(1, math.ceil(seg_len * fps - 1e-6))


def still(project, slide, out: Path, *, channel=None, image_for=None,
          at: float = 0.5, cache_dir: Path | None = None) -> Path:
    """One frame of a paragraph in its cut, `at` of the way through — the
    picture the pictures tab shows for it."""
    module = BY_KEY[project.style.format]
    ctx = make_ctx(project, (WIDTH, round(WIDTH * 9 / 16)), FPS, channel, image_for)
    ctx.k = 0.5
    ctx.cache["dir"] = cache_dir
    dur = max(2.5, slide.word_count / WORDS_PER_MINUTE * 60 + 0.5)
    spoken = spoken_of(slide, dur)
    length = spoken + 0.5
    beat = beat_for(module, ctx, slide, length, 0.0, spoken, cache_dir)
    t = kit.clamp(at) * (length - 0.05)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        module.frame(beat, ctx, t).save(out)
    finally:
        kit.close_footage(ctx)
    return out


def head_pad_for(project, slide) -> float:
    """The opening silence, on the first paragraph of the video only."""
    return HEAD_PAD if project.slides and project.slides[0].id == slide.id else 0.0

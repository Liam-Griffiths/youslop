"""Assemble slides, narration and music into the finished video."""
from __future__ import annotations

import concurrent.futures as cf
import math
import os
import random
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from . import audio as audio_mod
from . import cuts, ffutil, media, sysinfo, titles
from .config import (
    FPS, HEAD_PAD, HEIGHT, MUSIC_DIR, PARAGRAPH_GAP, TAIL_PAD, WIDTH,
    WORDS_PER_MINUTE,
)
from .schema import AUTO_MUSIC, Project, Slide, chapter_title, group_slides
from .store import project_dir

Progress = Callable[[str], None]

GRADES = {
    "warm": "colorbalance=rs=0.035:bs=-0.045,eq=saturation=0.95:contrast=1.05:gamma=0.99",
    "neutral": "eq=contrast=1.03:saturation=0.98",
    "cool": "colorbalance=rs=-0.03:bs=0.05,eq=saturation=0.96:contrast=1.04",
    "mono": "hue=s=0,eq=contrast=1.10:gamma=1.02",
}

# Ken Burns moves, cycled so consecutive slides never repeat a motion.
MOVES = ["in_center", "out_center", "in_left", "in_right", "out_left"]


def _vignette(strength: float) -> str:
    """Map 0..1 onto a believable lens falloff. 0 disables the filter."""
    if strength <= 0.01:
        return ""
    angle = math.pi / 6 + max(0.0, min(1.0, strength)) * (math.pi / 4 - math.pi / 6)
    return f"vignette=angle={angle:.4f}:mode=forward:eval=init"


# How far inside the frame edge a focal point must stay. At 0.14 the subject
# can drift toward an edge for composition but never leaves the picture.
FOCAL_INSET = 0.14


def _clamp_to_focal(desired: str, focal_px: float, span: str, extent: str) -> str:
    """Wrap a pan expression so the focal point stays inside the visible window.

    `span` is the visible width/height expression (iw/zoom), `extent` the full
    image dimension. The window is pushed just far enough to keep the point in
    frame, and still clamped to the image so we never pan past the edge.
    """
    lo = f"max(0,{focal_px:.2f}-({span})*{1 - FOCAL_INSET:.2f})"
    hi = f"min({extent}-({span}),{focal_px:.2f}-({span})*{FOCAL_INSET:.2f})"
    # If the window is too small to satisfy both, the low bound wins, which
    # keeps the point visible rather than honouring the framing preference.
    return f"clip({desired},{lo},max({lo},{hi}))"


def _kenburns(move: str, frames: int, amount: float,
              focal_px: tuple[float, float] | None = None,
              size: tuple[int, int] = (WIDTH, HEIGHT), fps: int = FPS) -> str:
    """A zoompan expression driven by frame number, so motion is perfectly linear."""
    n = max(2, frames)
    t = f"(on/{n - 1})"
    if move.startswith("in"):
        z = f"1+{amount:.4f}*{t}"
    else:
        z = f"1+{amount:.4f}-{amount:.4f}*{t}"

    if move.endswith("center"):
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif move.endswith("left"):
        x, y = f"(iw-iw/zoom)*(1-{t})", "ih/2-(ih/zoom/2)"
    else:
        x, y = f"(iw-iw/zoom)*{t}", "ih/2-(ih/zoom/2)"

    if focal_px:
        fx, fy = focal_px
        x = _clamp_to_focal(x, fx, "iw/zoom", "iw")
        y = _clamp_to_focal(y, fy, "ih/zoom", "ih")

    return (f"zoompan=z='{z}':x='{x}':y='{y}':"
            f"d={n}:s={size[0]}x{size[1]}:fps={fps}")


def _cover_crop(src: Path, box_w: int, box_h: int,
                focal: list[float] | None) -> tuple[str, tuple[float, float] | None]:
    """Scale to cover `box`, then crop toward the focal point rather than centre.

    Returns the filter fragment and where the focal point ends up inside the
    cropped frame, in pixels, for the pan clamp to use.
    """
    try:
        sw, sh = ffutil.dimensions(src)
    except Exception:
        sw = sh = 0
    if not sw or not sh:
        return (f"scale={box_w}:{box_h}:force_original_aspect_ratio=increase,"
                f"crop={box_w}:{box_h},setsar=1"), None

    scale = max(box_w / sw, box_h / sh)
    cw, chh = max(box_w, round(sw * scale)), max(box_h, round(sh * scale))

    if focal and len(focal) == 2:
        fx, fy = min(1.0, max(0.0, focal[0])), min(1.0, max(0.0, focal[1]))
        # Centre the crop window on the point, then pull it back inside the image.
        ox = min(max(fx * cw - box_w / 2, 0), cw - box_w)
        oy = min(max(fy * chh - box_h / 2, 0), chh - box_h)
        focal_px = (fx * cw - ox, fy * chh - oy)
    else:
        ox, oy = (cw - box_w) / 2, (chh - box_h) / 2
        focal_px = None

    return (f"scale={cw}:{chh},crop={box_w}:{box_h}:{ox:.0f}:{oy:.0f},setsar=1"), focal_px


def _slide_durations(project: Project, use_estimates: bool) -> list[tuple[Slide, float]]:
    """Screen time per paragraph: the take plus the pause the narration leaves.

    The pause comes from `audio.paragraph_gaps`, the same list the narration bed
    is padded with, so the pictures cannot drift away from the voice.
    """
    gaps = audio_mod.gap_map(project)
    out: list[tuple[Slide, float]] = []
    for s in project.slides:
        take = s.take or {}
        d = float(take.get("duration") or 0.0)
        if d <= 0:
            if not use_estimates:
                continue
            d = max(2.5, s.word_count / WORDS_PER_MINUTE * 60)
        out.append((s, round(d + gaps.get(s.id, PARAGRAPH_GAP), 3)))
    return out


def _picture_groups(project: Project,
                    plan: list[tuple[Slide, float]]) -> list[list[tuple[Slide, float]]]:
    """Split the timed paragraphs into runs that share one picture.

    `style.picture_every` sets the default run length — raise it when the
    archives are thin and each picture simply stays up for several paragraphs,
    with the Ken Burns move stretched across the whole hold. The rule itself
    lives in `schema.group_slides`, so the UI and the renderer cannot disagree
    about which paragraph needs a picture.
    """
    by_id = {s.id: d for s, d in plan}
    runs = group_slides([s for s, _d in plan], project.style.picture_every)
    return [[(s, by_id[s.id]) for s in run] for run in runs if run]


CHUNK_SECONDS = 20.0


def _draw_segment(job: tuple) -> tuple[int, int, Path, bool]:
    """One chunk of a drawn-cut segment, in a worker process of its own.

    Returns which segment and chunk it was, the file, and whether it went to
    the GPU — chunks are joined without re-encoding, which is only safe when
    they all came out of the same encoder.
    """
    (project, group, seg_len, index, out, channel, chapter, threads,
     i, chunk, frames) = job
    _render_segment(project, group, seg_len, index, out, channel=channel,
                    chapter=chapter, threads=threads, frames=frames)
    return i, chunk, out, bool(ffutil.gpu_status()["active"])


def _draw_segments(project: Project, groups, seg_lens, slide_at: int, seg_dir: Path,
                   channel, free_mb, progress: Progress) -> list[Path]:
    """Every picture's segment in a drawn cut, drawn across worker processes."""
    import multiprocessing as mp

    jobs = []
    split: dict[int, int] = {}
    for i, group in enumerate(groups):
        seg_len = seg_lens[i + slide_at]
        total = cuts.frame_count(seg_len, FPS)
        n = max(1, round(total / (CHUNK_SECONDS * FPS)))
        split[i] = n
        chapter = (chapter_card(project, groups[i + 1][0][0])
                   if i + 1 < len(groups) else None)
        name = f"seg{i + slide_at:04d}"
        for c in range(n):
            a, b = total * c // n, total * (c + 1) // n
            out = seg_dir / (f"{name}.mp4" if n == 1 else f"{name}.part{c:02d}.mp4")
            jobs.append((project, group, seg_len, i + slide_at, out, channel, chapter,
                         0, i, c, (a, b)))
    cores = os.cpu_count() or 4
    workers = max(1, min(len(jobs), cores - 1, 15))
    if free_mb is not None:
        workers = max(1, min(workers, int(free_mb // 800)))
    threads = max(1, cores // workers)
    jobs = [j[:7] + (threads,) + j[8:] for j in jobs]
    progress(f"Drawing {len(groups)} pictures as {len(jobs)} pieces, {workers} at a time")

    # spawn, not fork: the app process has a web server and job threads
    # running, and a forked copy of those is how a child hangs on a lock it
    # inherited mid-use. It is also what macOS does anyway.
    parts: dict[int, dict[int, tuple[Path, bool]]] = {i: {} for i in range(len(groups))}
    done = 0
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("spawn")) as pool:
        for i, c, out, gpu in pool.map(_draw_segment, jobs):
            parts[i][c] = (out, gpu)
            done += 1
            if done % 5 == 0 or done == len(jobs):
                progress(f"  pieces {done}/{len(jobs)}")

    paths = []
    for i in range(len(groups)):
        if split[i] == 1:
            paths.append(parts[i][0][0])
            continue
        out = seg_dir / f"seg{i + slide_at:04d}.mp4"
        pieces = [parts[i][c] for c in range(split[i])]
        listing = seg_dir / f"seg{i + slide_at:04d}.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p, _gpu in pieces))
        if len({gpu for _p, gpu in pieces}) == 1:
            # Same encoder, same settings, each piece starting on a keyframe:
            # the pieces join as they are, without decoding anything.
            ffutil.run(["-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(out)])
        else:
            # The GPU gave out partway, so the pieces disagree about their
            # encoding; joined by re-encoding on the CPU instead.
            _pre, _vf, codec = ffutil.h264(out, crf=18, gpu=False)
            ffutil.run(["-f", "concat", "-safe", "0", "-i", str(listing),
                        *codec, "-an", str(out)])
        for p, _gpu in pieces:
            p.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)
        paths.append(out)
    return paths


def chapter_card(project: Project, slide: Slide) -> tuple[str, str] | None:
    """The chapter card drawn before `slide`, as (title, kicker), or None.

    The words come from `schema.chapter_title`, which the narration timing
    reads too. The kicker stays empty on purpose: `beat` is the outline beat
    the paragraph serves, and it lags a section behind at a boundary — it
    printed "Steam Changes The Deal" over the card announcing "The PC Bang
    Problem" — so there is nothing on a slide that honestly captions one.
    """
    title = chapter_title(project, slide)
    return (title, "") if title else None


def is_lead(project: Project, slide: Slide) -> bool:
    """Does this slide need a picture of its own, or does it hold the last one?"""
    return any(run and run[0] == slide.id for run in project.picture_runs())


def _chosen(project: Project, slide: Slide) -> tuple[Path | None, str, list[float]]:
    """The slide's downloaded asset, its kind, and its focal point if one is set."""
    cand = next((c for c in slide.candidates if c["id"] == slide.chosen_id), None)
    if not cand or not cand.get("local_path"):
        return None, "image", []
    p = project_dir(project.id) / cand["local_path"]
    return (p if p.exists() else None), cand.get("kind", "image"), (cand.get("focal") or [])


def _reframe(size: tuple[int, int], fps: int) -> tuple[str, ...]:
    """Output args fitting a full-size frame pipe into `size` at `fps`.

    The Pillow-drawn formats — boards, diagrams, designed slides — lay
    themselves out in 1080p pixels and draw every frame, so a smaller preview
    of one is a scale and a frame drop on the encode rather than a smaller
    canvas. Empty for a full-size render, which leaves the pipe untouched.
    """
    if size == (WIDTH, HEIGHT) and fps == FPS:
        return ()
    return ("-vf", f"scale={size[0]}:{size[1]}", "-r", str(fps))


# A type card, a host portrait, an essay picture: one still image held over a
# whole segment. Handed to ffmpeg as `-loop 1 -i card.png` it is re-read and
# re-decoded for every output frame, and an essay segment stacks a dozen or
# more of them — measured on a real one, that single detail cost 26.9s against
# 4.9s for the same 20s of preview. Fed as one frame and held by `loop` inside
# the filtergraph instead, each still is decoded, scaled and (for the essay
# stage) blurred once, and the finished frame is repeated.
#
# The exception is a Ken Burns still, which stays on `-loop 1`: `zoompan`
# holds the frame itself, taking one decode for the whole move, and the spare
# input frames are what let it overrun the segment rather than coming up a
# frame short at the end.
HOLD_STILL = "loop=loop=-1:size=1"


def _still_input(path: Path, fps: int) -> list[str]:
    return ["-framerate", str(fps), "-i", str(path)]


def _render_custom_style(project: Project, group: list[tuple[Slide, float]],
                         seg_len: float, out: Path,
                         size: tuple[int, int] = (WIDTH, HEIGHT),
                         fps: int = FPS, crf: int = 17) -> Path | None:
    """Stage one held paragraph in the video's saved slide style.

    The spec drawn here is the one `script_gen.plan_custom_slides` already
    filled for this paragraph and left on the slide, so rendering is only
    drawing — no model call, no archive fetch, on what may be the thirtieth
    segment of a long render. Returns None when there is nothing to draw, which
    is the caller's signal to fall back to the documentary cut.
    """
    from . import custom_slide, slide_styles

    slide = group[0][0]
    spec = slide.custom or {}
    if not spec.get("elements"):
        style = slide_styles.get(slide_styles.id_from_format(project.style.format))
        if not style:
            return None
        spec = style.spec            # unfilled: the style's own placeholders
    try:
        frames = custom_slide.frames(
            spec, seg_len, hand=getattr(project.style, "board_hand", "marker"),
            media_root=project_dir(project.id) / "media")
        # The slide is always drawn at full size — the layout is in 1080p
        # pixels — so a smaller frame is a scale on the way into the encoder.
        if not ffutil.encode_frames(frames, out, crf=crf,
                                    extra=_reframe(size, fps)):
            return None
    except (ValueError, TypeError, OSError):
        return None
    return out


# ------------------------------------------------------------------- segments
def _clip_source(src: Path, seg_len: float, crop: str) -> tuple[list[str], str]:
    """Inputs and a filtergraph that make a clip fill `seg_len` seconds.

    Archive clips are routinely shorter than the paragraph they sit under. A
    hard loop reads as a mistake, so a short clip is first slowed a little (up to
    a third), and if it still comes up short it is laid end to end with a half
    second dissolve at each seam, which reads as a considered cut instead.
    """
    XF = 0.5
    base = f"{crop},fps={FPS}"
    try:
        clip = float(ffutil.duration(src))
    except Exception:
        clip = 0.0
    if clip <= 0.3:
        # Unreadable duration: fall back to the blunt loop rather than failing.
        return ["-stream_loop", "-1", "-i", str(src)], f"[0:v]{base}[base]"

    stretch = min(1.35, max(1.0, seg_len / clip)) if clip < seg_len else 1.0
    slow = f",setpts={stretch:.4f}*PTS" if stretch > 1.001 else ""
    effective = clip * stretch
    if effective >= seg_len - 0.05:
        return ["-i", str(src)], f"[0:v]{base}{slow}[base]"

    repeats = math.ceil((seg_len - XF) / max(0.2, effective - XF))
    if repeats > 8:
        # A two second clip under a minute of narration: dissolving eight times
        # would be sillier than simply running it round.
        return ["-stream_loop", "-1", "-i", str(src)], f"[0:v]{base}{slow}[base]"

    inputs: list[str] = []
    parts: list[str] = []
    for i in range(repeats):
        inputs += ["-i", str(src)]
        parts.append(f"[{i}:v]{base}{slow},format=yuv420p[c{i}]")
    last = "[c0]"
    for i in range(1, repeats):
        offset = i * (effective - XF)
        label = "[base]" if i == repeats - 1 else f"[x{i}]"
        parts.append(f"{last}[c{i}]xfade=transition=fade:duration={XF}:"
                     f"offset={offset:.3f}{label}")
        last = label
    return inputs, ";".join(parts)


# The essay slide, in 1080p pixels. The card is sized to the picture rather
# than the picture fitted to a fixed card: a 4:3 scan in a 2:1 frame is mostly
# matte, and the border reads as a frame around nothing. These are the bounds
# it is fitted inside — the band above the captions, which live at
# `titles.CAPTION_BAND_Y`; the two halves of this layout have to be read
# together.
ESSAY_MAX_W, ESSAY_MAX_H = 1480, 624
ESSAY_TOP, ESSAY_BAND_H = 44, 664
ESSAY_BORDER = 8

_SAFE_NAME = re.compile(r"[^A-Za-z0-9]+")

CAPTION_MIN_HOLD = 1.0   # a caption on screen for less than this can't be read


def _caption_timings(chunks: list[str], budget: float) -> list[float]:
    """How long each caption in `chunks` holds, within `budget` seconds total.

    Proportional to word count, not an even split — a 6-word caption and an
    18-word one were getting the same time on screen, which read as either
    rushed or padded depending on which one you were looking at. A floor
    keeps a short caption from flashing by unreadably; if the floors alone
    would overrun the budget (a paragraph chopped into many short captions),
    everything is scaled back down together rather than overrunning `dur`.
    """
    if not chunks:
        return []
    words = [max(1, len(c.split())) for c in chunks]
    total = sum(words)
    raw = [budget * w / total for w in words]
    shares = [max(CAPTION_MIN_HOLD, s) for s in raw]
    if budget > 0 and sum(shares) > budget:
        scale = budget / sum(shares)
        shares = [s * scale for s in shares]
    return shares


def _essay_card(src: Path | None, k: float = 1.0) -> tuple[int, int, int, int]:
    """Card size and position for one picture: its own shape, centred.

    `k` scales the layout off its 1080p figures, for a frame rendered smaller
    than the finished one (see `preview_segment`).
    """
    try:
        sw, sh = ffutil.dimensions(src) if src else (0, 0)
    except Exception:
        sw, sh = 0, 0
    if sw <= 0 or sh <= 0:
        sw, sh = 16, 9
    scale = min(ESSAY_MAX_W * k / sw, ESSAY_MAX_H * k / sh)
    # Even dimensions: odd ones make the scaler and the encoder both unhappy.
    bw = max(2, int(round(sw * scale)) // 2 * 2)
    bh = max(2, int(round(sh * scale)) // 2 * 2)
    return (bw, bh, (round(WIDTH * k) - bw) // 2,
            round(ESSAY_TOP * k) + (round(ESSAY_BAND_H * k) - bh) // 2)


def _essay_stage(source: str, accent: str, src: Path | None,
                 size: tuple[int, int] = (WIDTH, HEIGHT),
                 fps: int = FPS, hold: bool = False) -> str:
    """Filtergraph putting `source` in a bordered slide over a blur of itself.

    Ends on [base], which is the label the grade tail downstream expects, so
    an essay segment grades and vignettes exactly like a documentary one.
    `hold` composes a single still frame and repeats it (see HOLD_STILL);
    without it the source is a clip and every frame is staged as it arrives.
    """
    w, h = size
    k = w / WIDTH
    bw, bh, box_x, box_y = _essay_card(src, k)
    border = max(1, round(ESSAY_BORDER * k))
    inner_w, inner_h = bw - 2 * border, bh - 2 * border
    return (
        f"{source}split=2[ebg][efg];"
        # The fill: cropped to the frame, blurred right down, pushed back so the
        # slide on top of it reads as the subject rather than competing. The
        # blur is in pixels, so it scales with the frame or a smaller render
        # comes out twice as soft as the cut it is standing in for.
        f"[ebg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},gblur=sigma={34 * k:.2f},"
        f"eq=brightness=-0.16:saturation=1.15[ebgout];"
        # The slide: the whole picture, never cropped — an archive screenshot
        # loses its point when the edges are cut off — inside its own border.
        f"[efg]scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
        f"pad={inner_w}:{inner_h}:(ow-iw)/2:(oh-ih)/2:color=#0B0C10,"
        f"pad={bw}:{bh}:{border}:{border}:color={accent}[ecard];"
        f"[ebgout][ecard]overlay={box_x}:{box_y}:format=auto"
        + (f",{HOLD_STILL}" if hold else "") + "[base]"
    )


def _render_segment(
    project: Project, group: list[tuple[Slide, float]], seg_len: float,
    index: int, out: Path, channel=None, chapter: tuple[str, str] | None = None,
    threads: int = 0, size: tuple[int, int] = (WIDTH, HEIGHT),
    fps: int = FPS, crf: int = 18, preset: str = "veryfast",
    frames: tuple[int, int] | None = None,
) -> Path:
    """Render one held picture to a silent mp4 of exactly `seg_len` seconds.

    A group is one or more consecutive paragraphs sharing a picture. The first
    slide in it supplies the visual; every slide in it can still put its own
    title on screen, at its own moment inside the hold.

    `style.format` decides how that picture is staged: the documentary cut
    fills the frame and drifts across it, the essay cut sets the whole picture
    inside a bordered slide and puts the narration on screen underneath, and
    the board cut hands the whole segment to `app/board.py`, which draws it
    rather than photographing it.

    `size` and `fps` are the frame this segment is rendered at: the finished
    1080p30 for a real render, a quarter of the frame at half the rate for the
    in-app preview (`preview_segment`). Everything measured in pixels — the
    essay card, the blur, the type cards — scales with `size`, so a preview is
    the same picture seen smaller rather than a differently composed one.
    """
    style = project.style
    w, h = size
    if style.format.startswith("custom:"):
        rendered = _render_custom_style(project, group, seg_len, out, size,
                                        fps, crf)
        if rendered is not None:
            return rendered
        # The style was deleted, or this paragraph has no filled spec yet:
        # fall through to the documentary cut rather than abort the render.
    if cuts.is_cut(style.format):
        # The drawn cuts join on a hard cut, so `seg_len` carries one frame
        # of overlap; the voice starts half of that in, plus the opening
        # silence on the video's first paragraph.
        lead_in = (cuts.transition_for(style) / 2
                   + cuts.head_pad_for(project, group[0][0]))
        return cuts.render_segment(
            project, group, seg_len, out, channel=channel,
            image_for=lambda s: _chosen(project, s)[0], size=size, fps=fps,
            crf=crf, lead_in=lead_in, cache_dir=project_dir(project.id) / "cuts",
            chapter=chapter, frames=frames,
            hold=max(0.9, min(3.2, audio_mod.gap_map(project).get(
                group[-1][0].id, PARAGRAPH_GAP) - 0.12)))
    if style.format == "board":
        from . import board as board_mod
        return board_mod.render_segment(
            project, group, seg_len, out, channel=channel,
            cache=project_dir(project.id) / "board",
            image_for=lambda s: _chosen(project, s)[0],
            crf=crf, extra=_reframe(size, fps))
    essay = style.format == "essay"
    slide = group[0][0]
    src, kind, focal = _chosen(project, slide)
    frames = max(2, int(round(seg_len * fps)))
    grade = GRADES.get(style.grade, GRADES["warm"])
    vig = _vignette(style.vignette)
    # The type cards are drawn once at 1080p and cached for the real render;
    # a smaller frame scales them on the way in rather than drawing a second set.
    card_fit = "" if (w, h) == (WIDTH, HEIGHT) else f",scale={w}:{h}"

    inputs: list[str] = []
    chain: list[str] = []
    pre_graph = ""            # set by sources that need more than one input

    if src is None:
        # Nothing picked or the download failed: a graded slate keeps the cut
        # intact rather than aborting the whole render.
        inputs += ["-f", "lavfi", "-i",
                   f"color=c=#12131a:s={w}x{h}:r={fps}:d={seg_len:.3f}"]
        chain.append("null")
    elif essay:
        # The essay slide: the whole picture, uncropped, inside an accent
        # border, over a blurred fill of itself. One source feeds both layers.
        if kind == "video":
            crop, _ = _cover_crop(src, w, h, focal)
            clip_inputs, clip_graph = _clip_source(src, seg_len, crop)
            inputs += clip_inputs
            pre_graph = (f"{clip_graph};"
                         + _essay_stage("[base]", style.accent, src, size=size,
                                        fps=fps))
        else:
            # A still essay slide never changes: the stage is composed from the
            # one frame and then held, rather than blurred again every frame.
            inputs += _still_input(src, fps)
            pre_graph = _essay_stage("[0:v]", style.accent, src, size=size,
                                     fps=fps, hold=True)
    elif kind == "video":
        crop, _ = _cover_crop(src, w, h, focal)
        clip_inputs, pre_graph = _clip_source(src, seg_len, crop)
        inputs += clip_inputs
    elif style.ken_burns:
        inputs += ["-loop", "1", "-i", str(src)]
        # Oversample to 2x output before the zoom so the pan stays subpixel-smooth.
        crop, focal_px = _cover_crop(src, w * 2, h * 2, focal)
        chain.append(crop)
        chain.append(_kenburns(MOVES[index % len(MOVES)], frames,
                               style.ken_burns_amount, focal_px, size, fps))
    else:
        # A still with the drift switched off: staged once, then held.
        inputs += _still_input(src, fps)
        crop, _focal_px = _cover_crop(src, w * 2, h * 2, focal)
        chain.append(crop)
        chain.append(f"scale={w}:{h}")
        chain.append(HOLD_STILL)

    tail = [c for c in (grade, vig, "format=yuv420p") if c]
    if pre_graph:
        # The source built [base] itself (a looped clip); grade what came out.
        graph = f"{pre_graph};[base]{','.join(tail)}[graded]"
        base_label = "[graded]"
    else:
        graph = f"[0:v]{','.join(c for c in chain + tail if c)}[base]"
        base_label = "[base]"
    n_inputs = inputs.count("-i")      # sources may take several inputs each
    last = base_label

    # The host, if this channel has one: a still, pinned in a corner for the
    # whole segment. Under the captions in the stack, so it can never cover a
    # word if the two ever meet.
    av = getattr(channel, "avatar", None) if essay else None
    if av and av.enabled and av.path:
        from .channels import channel_dir
        av_src = channel_dir(channel.id) / av.path
        if av_src.is_file():
            av_h = int(max(0.1, min(0.4, av.scale)) * h)
            margin = round(40 * h / HEIGHT)
            x = f"W-w-{margin}" if av.position != "bottom_left" else str(margin)
            graph += (
                f";[{n_inputs}:v]format=rgba,scale=-1:{av_h},{HOLD_STILL}[avatar]"
                f";{last}[avatar]overlay={x}:H-h-{margin}:format=auto[av]"
            )
            inputs += _still_input(av_src, fps)
            n_inputs += 1
            last = "[av]"

    # Type over the picture. The documentary cut announces a chapter once per
    # paragraph; the essay cut sets the narration itself, a phrase at a time.
    offset = 0.0
    for n, (member, dur) in enumerate(group):
        if essay:
            chunks = titles.essay_chunks(member.narration)
            # Across the spoken part only. `dur` carries the pause that follows
            # the paragraph, and a caption still on screen through a chapter
            # break reads as one that has been left up by mistake.
            spoken = float((member.take or {}).get("duration") or 0.0) or dur * 0.85
            shares = _caption_timings(chunks, min(dur, spoken))
            cap_offset = 0.0
            for c, text in enumerate(chunks):
                card = (project_dir(project.id) / "titles"
                        / f"{member.id}_cap{c:02d}.png")
                titles.render_caption(text, accent=style.accent, out_path=card)
                start = offset + cap_offset
                end = min(seg_len - 0.05, start + shares[c])
                cap_offset += shares[c]
                if end <= start + 0.25:
                    continue
                idx = n_inputs
                inputs += _still_input(card, fps)
                n_inputs += 1
                # Quick on, quick off: a caption that dissolves like a title
                # reads as sluggish against the pace of the read.
                graph += (
                    f";[{idx}:v]format=rgba{card_fit},{HOLD_STILL},"
                    f"fade=t=in:st={start:.3f}:d=0.14:alpha=1,"
                    f"fade=t=out:st={max(start + 0.15, end - 0.16):.3f}:d=0.16:alpha=1"
                    f"[cap{n}_{c}]"
                    f";{last}[cap{n}_{c}]overlay=0:0:format=auto[v{n}_{c}]"
                )
                last = f"[v{n}_{c}]"
        elif member.title:
            card = project_dir(project.id) / "titles" / f"{member.id}.png"
            titles.render_title(member.title, kicker=member.beat or "",
                                accent=style.accent, out_path=card)
            idx = n_inputs
            inputs += _still_input(card, fps)
            n_inputs += 1
            start = offset + 0.55
            hold = min(6.0, max(2.0, dur - 1.2))
            fade_out_at = min(seg_len - 0.9, start + hold)
            if fade_out_at > start + 0.4:
                graph += (
                    f";[{idx}:v]format=rgba{card_fit},{HOLD_STILL},"
                    f"fade=t=in:st={start:.3f}:d=0.75:alpha=1,"
                    f"fade=t=out:st={fade_out_at:.3f}:d=0.85:alpha=1[ttl{n}]"
                    f";{last}[ttl{n}]overlay=0:0:format=auto[v{n}]"
                )
                last = f"[v{n}]"
        offset += dur

    # The chapter card for the section that starts next. It lands in the long
    # silence `audio.GAP_CHAPTER` opens at the end of this segment, so the
    # video pauses on the title and then the new section begins. Every format
    # that composes its picture here can carry one; the board and designed-
    # slide cuts draw their own frames and never reach this far.
    if chapter:
        title, kicker = chapter
        card = (project_dir(project.id) / "titles"
                / f"chapter_{_SAFE_NAME.sub('_', title)[:40]}.png")
        titles.render_chapter(title, kicker=kicker, accent=style.accent,
                              out_path=card)
        # Timed off the actual silence rather than a share of the segment, so
        # the card comes up as the voice stops instead of over its last words.
        gap = audio_mod.gap_map(project).get(group[-1][0].id, PARAGRAPH_GAP)
        hold = max(0.9, min(3.2, gap - 0.12))
        start = max(0.2, seg_len - hold)
        inputs += _still_input(card, fps)
        graph += (
            f";[{n_inputs}:v]format=rgba{card_fit},{HOLD_STILL},"
            f"fade=t=in:st={start:.3f}:d=0.45:alpha=1[chap]"
            f";{last}[chap]overlay=0:0:format=auto[vchap]"
        )
        n_inputs += 1
        last = "[vchap]"

    ffutil.run([
        *inputs, "-filter_complex", graph, "-map", last,
        "-t", f"{seg_len:.3f}", "-r", str(fps),
        *ffutil.video_args(out, crf=crf, preset=preset),
        "-pix_fmt", "yuv420p", "-an", str(out),
    ], threads=threads)
    return out


# ---------------------------------------------------------------------- intro
def _slate_channel(project: Project):
    """What the slate and the end screen are drawn from, series or not.

    A video in a channel is drawn from that channel. A standalone one is drawn
    from a channel made up on the spot out of the video itself: its title
    where the series name goes, its subtitle for the line beneath, its own
    colours, and the opening and closing specs the video carries. The slate
    renderers only ever read a Channel, so this is the whole of what it takes
    to give a one-off video the same openings a series gets.

    Returns None when the video belongs to a channel that is no longer on
    disk, which the callers report rather than guess around.
    """
    from . import channels
    from .schema import Channel, IntroSpec, OutroSpec, Style

    if project.channel_id:
        return channels.load_or_none(project.channel_id)
    # Copies, not the project's own specs: the renderers are free to settle a
    # template or a length on the channel they are handed, and none of that
    # should turn into a change to the video that gets saved.
    return Channel(
        id="", name=project.title or "Untitled", tagline=project.subtitle,
        style=Style(**project.style.to_dict()),
        intro=IntroSpec(**project.intro.to_dict()),
        outro=OutroSpec(**project.outro.to_dict()),
    )


def _solo_slate(project: Project) -> bool:
    """Is this a standalone video with an opening card of its own?"""
    return bool(not project.channel_id and project.intro.template)


def _has_slate(project: Project) -> bool:
    """Will this video open on a slate? Asked without rendering one."""
    from . import channels, intro as intro_mod

    if not project.use_intro:
        return False
    if not project.channel_id:
        return _solo_slate(project)
    channel = channels.load_or_none(project.channel_id)
    return bool(channel and not (intro_mod.needs_images(channel.intro.template)
                                 and len(channel.intro.images or []) < 2))


def _build_intro(project: Project, progress: Progress,
                 out: Path | None = None) -> tuple[Path | None, float]:
    """Render this video's opening slate, if it has one. Never fatal."""
    if not project.use_intro:
        return None, 0.0
    from . import intro as intro_mod

    solo = not project.channel_id
    if solo and not project.intro.template:
        return None, 0.0            # a standalone video opens cold by default

    channel = _slate_channel(project)
    if channel is None:
        progress("This video's channel is gone; rendering without a slate")
        return None, 0.0
    # Only the cast-led templates need portraits; the type-led ones stand
    # alone. A standalone video has no cast to draw on, so it is held to the
    # type-led ones rather than failing on a template it cannot fill.
    if intro_mod.needs_images(channel.intro.template):
        if solo:
            channel.intro.template = intro_mod.SOLO_DEFAULT
        elif len(channel.intro.images or []) < 2:
            progress(f"Channel “{channel.name}” has no cast yet; rendering without a slate")
            return None, 0.0

    out = out or project_dir(project.id) / "segments" / "intro.mp4"
    try:
        # A standalone slate already carries the video's title as its name;
        # passing it again would set the same words twice on one card.
        title = "" if solo else (project.title or "")
        length = intro_mod.render_intro(channel, title, out, progress)
    except Exception as exc:
        # A broken slate must not cost the creator a whole render.
        progress(f"Intro slate failed ({str(exc)[:100]}); rendering without it")
        return None, 0.0
    return out, length


# ------------------------------------------------------------------ presenter
def _render_presenter(project: Project, seg_len: float, out: Path) -> Path:
    """Cut the camera clip to length and put it in the video's house style."""
    pres = project.presenter
    src = project_dir(project.id) / pres.path
    style = project.style
    crop, _ = _cover_crop(src, WIDTH, HEIGHT, pres.focal or None)

    chain = [crop, f"fps={FPS}"]
    if style.grade in GRADES:
        # A face is the one thing that must not look processed, so the grade is
        # applied at half strength and Ken Burns never touches it.
        chain.append(GRADES[style.grade])
    vig = _vignette(style.vignette * 0.6)
    if vig:
        chain.append(vig)
    chain.append("format=yuv420p")

    ffutil.run([
        "-ss", f"{max(0.0, pres.trim_start):.3f}", "-i", str(src),
        "-t", f"{seg_len:.3f}",
        "-filter_complex", f"[0:v]{','.join(chain)}[v]", "-map", "[v]",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", str(out),
    ])
    return out


def _build_presenter(project: Project, transition: float,
                     progress: Progress) -> tuple[Path | None, float, float]:
    """Returns (source clip, clean screen time, segment length)."""
    pres = project.presenter
    if not pres.usable():
        return None, 0.0, 0.0
    src = project_dir(project.id) / pres.path
    if not src.exists():
        progress("The camera clip is missing from disk; rendering without it")
        return None, 0.0, 0.0

    # The dissolves either side eat into the clip itself rather than freezing a
    # frame, which is what a talking head should do: it simply fades up and out.
    seg_len = pres.duration
    clean = max(0.5, seg_len - transition)
    progress(f"Camera clip: {pres.filename} — {clean:.1f}s on screen")
    return src, clean, seg_len


def _last_picture(project: Project) -> Path | None:
    """The picture the video finishes on, for an end screen that holds it.

    A clip is skipped rather than having a frame pulled out of it: the card
    wants one still it can blur, and reaching into ffmpeg for a poster frame is
    a lot of machinery for a background.
    """
    for slide in reversed(project.slides):
        src, kind, _focal = _chosen(project, slide)
        if src and kind == "image":
            return src
    return None


def _build_outro(project: Project, progress: Progress,
                 out: Path | None = None) -> tuple[Path | None, float]:
    """The end screen this video closes on, if it has one. Never fatal.

    In a channel that is the channel's card; standalone it is the video's own,
    drawn from its title and colours (see `_slate_channel`).
    """
    if not project.use_outro:
        return None, 0.0
    from . import outro as outro_mod

    channel = _slate_channel(project)
    if channel is None or not channel.outro.enabled:
        return None, 0.0

    backdrop = None
    if outro_mod.wants_backdrop(channel.outro.template) or channel.outro.backdrop > 0.01:
        backdrop = _last_picture(project)

    out = out or project_dir(project.id) / "segments" / "outro.mp4"
    try:
        length = outro_mod.render_outro(channel, project.title or "", out,
                                        backdrop, progress)
    except Exception as exc:
        # A broken end screen must not cost the creator a whole render.
        progress(f"End screen failed ({str(exc)[:100]}); rendering without it")
        return None, 0.0
    return out, length


# ---------------------------------------------------------------------- music
def pick_music(project: Project,
               progress: Callable[[str], None] = lambda m: None) -> Path | None:
    """The video's music bed, or None for narration alone.

    Nothing selected means silence. Anything else would render a video with
    music the creator never asked for, and a bed is the one element you cannot
    miss on the way past.
    """
    if not project.music:
        return None
    if project.music != AUTO_MUSIC:
        chosen = MUSIC_DIR / project.music
        if chosen.exists():
            return chosen
        # Named a track that has since been deleted. Silence is the honest
        # answer; substituting another one would be a change nobody made.
        progress(f"The chosen bed “{project.music}” is no longer in "
                 f"assets/music; rendering without one")
        return None
    tracks = sorted(
        p for p in MUSIC_DIR.iterdir()
        if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
    )
    if not tracks:
        return None
    # Deterministic per project, so re-renders keep the same bed.
    return tracks[random.Random(project.id).randrange(len(tracks))]


def _music_loops(track: Path, total: float) -> bool:
    """Whether the bed has to run round to cover the video. Log dressing only."""
    try:
        return ffutil.duration(track) < total - 0.5
    except Exception:
        return False


def _sting_branch(idx: int, offset: float, length: float, intro,
                  fmt: str, voice_lufs: float = -16.0, label: str = "sting") -> str:
    """The slate's own sting. `adelay` goes last: nothing may follow it.

    The window, the level and the fade come from `intro.sting_chain`, which the
    slate preview uses too, so the two cannot drift apart.
    """
    from . import intro as intro_mod
    delay = int(round(offset * 1000))
    return (f"[{idx}:a]"
            + intro_mod.sting_chain(intro, length, fmt, voice_lufs)
            + (f",adelay={delay}|{delay}" if offset > 0.01 else "")
            + f"[{label}];")


def _audio_graph(project: Project, n_video: int, total: float, has_music: bool,
                 presenter: tuple[int, float, float, float] | None = None,
                 sting: list[tuple[int, float, float, Any, str]] | None = None,
                 music_fade: float = 5.0) -> str:
    """Voice (narration + any camera clip) plus a music bed.

    The camera clip's audio joins the *voice* bus rather than sitting alongside
    it, so it is levelled with the narration
    and the whole thing masters as one voice.
    """
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    nar = f"[{n_video}:a]"
    # Whatever the voice chain landed the takes on. Everything that is measured
    # *against* the narration — the camera clip, the slate's sting, the music bed
    # before music_db is applied — is normalised to the same number, so those
    # settings keep meaning "this far under the voice" if the target ever moves.
    vlufs = project.voice.target_lufs

    if presenter:
        idx, offset, trim_start, clip_len = presenter
        delay = int(round(offset * 1000))
        # The clip is trimmed inside the graph rather than with an input -ss, and
        # nothing follows adelay. Both matter: seeking the input leaves the first
        # packet with a non-zero PTS, and an apad/atrim pair after adelay throws
        # the inserted silence to the end of the branch instead of the front,
        # which lands the camera audio at 0:00 over the title slate.
        pre = (f"[{idx}:a]{fmt},"
               f"atrim=start={trim_start:.3f}:duration={clip_len:.3f},"
               f"asetpts=N/SR/TB,"
               f"loudnorm=I={vlufs:.1f}:TP=-1.5:LRA=11,"
               f"adelay={delay}|{delay}[pres];")
        voice_src = "[voicemix]"
        voice = (f"{pre}"
                 f"{nar}{fmt},apad,atrim=duration={total:.3f}[narpad];"
                 f"[narpad][pres]amix=inputs=2:duration=longest:normalize=0[voicemix];")
    else:
        pre = ""
        voice_src = "[voicepad]"
        voice = f"{nar}{fmt},apad,atrim=duration={total:.3f}[voicepad];"

    # One entry per sting — the slate's and the end card's — each (input index,
    # when it starts, how long its picture runs, the spec it is windowed by, and
    # "intro" or "outro").
    stings = list(sting or [])
    sting_graph = "".join(
        _sting_branch(i, off, ln, spec, fmt, vlufs, label=f"sting{k}")
        for k, (i, off, ln, spec, _role) in enumerate(stings))
    sting_tags = "".join(f"[sting{k}]" for k in range(len(stings)))

    if not has_music:
        if stings:
            return (voice + sting_graph +
                    f"{voice_src}{sting_tags}amix=inputs={1 + len(stings)}:"
                    f"duration=longest:normalize=0[mix];"
                    f"[mix]loudnorm=I=-14:TP=-1.0:LRA=11[aout]")
        return voice + f"{voice_src}loudnorm=I=-14:TP=-1.0:LRA=11[aout]"

    mus = f"[{n_video + 1 + (1 if presenter else 0) + len(stings)}:a]"
    fade = max(0.5, min(18.0, music_fade))
    fade_out_at = max(0.5, total - fade)

    # When the slate has a sting of its own, the bed holds off until the slate is
    # over. `afade` with a start time silences everything before it, so this needs
    # no adelay: the bed simply fades up as the sting rings out.
    bed_in_at = 0.0
    opening = next((s for s in stings if s[4] == "intro"), None)
    if opening:
        bed_in_at = max(0.0, opening[1] + opening[2] - 0.35)

    # Normalise the bed to the same loudness the voice takes were normalised to
    # before attenuating it. Without this, music_db is an offset from
    # whatever level the track happened to be mastered at, so a quiet track
    # vanishes and a loud one buries the narration. Now it means what it says:
    # this many dB below the voice.
    return (
        voice + sting_graph +
        f"{mus}{fmt},"
        f"atrim=duration={total:.3f},"
        f"loudnorm=I={vlufs:.1f}:TP=-2.0:LRA=11,"
        f"volume={project.style.music_db:.1f}dB,"
        f"afade=t=in:st={bed_in_at:.3f}:d=3,"
        f"afade=t=out:st={fade_out_at:.3f}:d={fade:.3f}[bed];"
        # The bed sits at a fixed level under the voice. It used to be
        # sidechain-compressed against the narration; that pumped audibly and
        # was taken out, so `music_db` alone sets how far under it sits.
        + f"{voice_src}[bed]{sting_tags}amix=inputs={2 + len(stings)}:"
          f"duration=longest:normalize=0[mix];"
        + f"[mix]loudnorm=I=-14:TP=-1.0:LRA=11[aout]"
    )


MEMORY_LOW_MB = 4096      # below this, a long render risks getting OS-killed
SWAP_PRESSURE_HIGH = 0.85  # swap this full means the system has nowhere left to page to


def _memory_check(progress: Progress) -> None:
    """Warn, never block, when the machine looks too tight to finish a render.

    An OS out-of-memory kill (systemd-oomd on Linux, the same idea elsewhere)
    takes the whole process with it — there is no exception for `jobs.py` to
    catch and no "FAILED:" line in the log, just silence where the render used
    to be. This is the one point before the heavy work starts where the
    creator can still do something about it.
    """
    mb = sysinfo.available_mb()
    if mb is not None and mb < MEMORY_LOW_MB:
        progress(f"Warning: only {mb:.0f}MB of memory free. A long render can be "
                 "killed by the OS partway through on a system this tight — "
                 "closing other apps first is worth doing.")
        return
    swap = sysinfo.swap_pressure()
    if swap is not None and swap > SWAP_PRESSURE_HIGH:
        progress(f"Warning: swap is {swap * 100:.0f}% full. The system has little "
                 "room left before it starts killing processes under memory "
                 "pressure — closing other apps first is worth doing.")


# ---------------------------------------------------------------------- render
def render(project: Project, progress: Progress = lambda m: None,
           preview: bool = False) -> dict:
    """Full render. `preview` uses estimated timings when nothing is recorded."""
    if project.style.format == "stage":
        # The 3D explainer has its library and cast but not yet its renderer
        # (docs/3d-explainer.md, build order step 3). Say so, rather than
        # falling through to the documentary cut with no pictures.
        raise ValueError("3D explainer videos cannot be rendered yet: the scene "
                         "renderer is still being built. Switch the format on the "
                         "Render tab to render this script another way.")
    _memory_check(progress)

    root = project_dir(project.id)
    seg_dir = root / "segments"
    shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True, exist_ok=True)

    plan = _slide_durations(project, use_estimates=preview)
    groups = _picture_groups(project, plan)
    if not plan:
        raise ValueError(
            "No recorded takes yet. Record the narration, or use Preview render "
            "to see the cut with estimated timings."
        )

    # A take whose file no longer matches its metadata would slide the pictures
    # off the voice by however much it lies, so it is caught before anything is
    # rendered rather than discovered in the finished cut.
    problems, repaired = audio_mod.audit_takes(project, root)
    if repaired:
        progress("Take durations re-measured from the files on disk")
    if problems and not preview:
        raise ValueError("These takes need re-recording before this will render: "
                         + "; ".join(problems))
    if problems:
        progress("Preview: " + "; ".join(problems))

    # Only the lead of each picture group ever reaches the screen — the rest of
    # the group holds that same picture rather than fetching its own. Handing
    # download_chosen anything wider fetches images the cut never shows and is
    # what was getting renders rate-limited.
    lead_slides = [group[0][0] for group in groups]
    failed = media.download_chosen(project, progress, only=lead_slides)
    if failed:
        progress(f"{len(failed)} asset(s) could not be downloaded; those slides "
                 "fall back to a graded slate")

    T = cuts.transition_for(project.style)

    # Head and tail padding live on the first and last segments so that every
    # crossfade stays centred on its paragraph boundary. One duration per held
    # picture, which is one or more paragraphs long.
    durations = [round(sum(d for _s, d in g), 3) for g in groups]
    if len(groups) < len(plan):
        held = len(plan) - len(groups)
        progress(f"{len(groups)} pictures across {len(plan)} paragraphs "
                 f"({held} paragraph(s) hold the picture already on screen)")
    durations[0] += HEAD_PAD
    durations[-1] += TAIL_PAD

    # The channel slate, if this video belongs to a channel that has one, is
    # simply another segment on the front of the chain. Everything downstream
    # shifts by its length, including where the narration starts.
    intro_path, intro_len = _build_intro(project, progress)
    if intro_path:
        durations.insert(0, intro_len)

    # The camera clip is a segment like any other. Where it lands decides how
    # much of the timeline sits before the first narrated paragraph.
    pres_src, pres_clean, pres_seg_len = _build_presenter(project, T, progress)
    pres_index = -1
    if pres_src:
        pos = project.presenter.position
        if pos == "start":
            pres_index = 0
        elif pos == "end":
            pres_index = len(durations)
        else:                                   # after_intro
            pres_index = 1 if intro_path else 0
        durations.insert(pres_index, pres_clean)

    outro_path, outro_len = _build_outro(project, progress)
    if outro_path:
        durations.append(outro_len)

    seg_lens = [d + T for d in durations]
    # The clip supplies its own footage for the dissolves, so its segment is
    # exactly as long as the trimmed clip rather than d + T.
    if pres_src:
        seg_lens[pres_index] = pres_seg_len
    total = sum(durations) + T

    # Where the clip's own audio has to land to stay in sync with its picture.
    pres_offset = sum(durations[:pres_index]) if pres_src else 0.0

    # Index of the first slide, and therefore how much timeline precedes the
    # first narrated word.
    slide_at = (1 if intro_path else 0)
    if pres_src and pres_index <= slide_at:
        slide_at += 1
    pre_slides = sum(durations[:slide_at])

    progress(f"Rendering {len(durations)} segments, {total / 60:.1f} min total")

    # ------------------------------------------------------------ narration
    narration = root / "out" / "narration.wav"
    lead_in = T / 2 + pre_slides
    if preview and not any(s.take for s in project.slides):
        ffutil.run(["-f", "lavfi", "-i",
                    f"anullsrc=r=48000:cl=mono:d={total:.3f}",
                    "-c:a", "pcm_s16le", str(narration)])
        progress("Preview: narration track is silent")
    else:
        audio_mod.build_narration(project, narration, lead_in=lead_in)
        progress(f"Narration bed built ({ffutil.duration(narration) / 60:.1f} min)")

    # ------------------------------------------------------------- segments
    workers = max(2, min(6, (os.cpu_count() or 4) // 2))
    # An essay-format segment's caption overlays build a filter graph a few
    # dozen nodes deep (one chain per caption), and was measured peaking
    # around 4-5GB of RSS per encode — ffmpeg's own thread/filter-thread caps
    # (see ffutil.run) barely move this number; it is the depth of the chain
    # itself, not the threading, and there is no cheap knob for that short of
    # changing how essay captions are composited. Until that is rebuilt, the
    # only lever here is running fewer of them at once: six in parallel on a
    # machine that is already tight on memory is exactly how a render becomes
    # the thing that tips the system into an OOM kill.
    free_mb = sysinfo.available_mb()
    if free_mb is not None:
        workers = max(1, min(workers, int(free_mb // 5000)))
    # ffmpeg's decode/encode/filter threading all default to "auto" against
    # the whole machine independently, which is wrong when several of these
    # run at once regardless of the point above — still worth capping so a
    # lighter format (documentary, with far fewer overlay nodes) doesn't
    # needlessly oversubscribe every core per worker.
    seg_threads = max(1, (os.cpu_count() or 4) // workers)
    done = 0
    # Loaded once rather than per segment: the essay format reads the host
    # avatar off it, and every segment would otherwise re-read the same file.
    from . import channels as channels_mod
    seg_channel = channels_mod.load_or_none(project.channel_id)

    def work(i: int) -> tuple[int, Path]:
        out = seg_dir / f"seg{i + slide_at:04d}.mp4"
        # A section starting in the next group is announced at the end of this
        # one, in the silence that precedes it.
        chapter = (chapter_card(project, groups[i + 1][0][0])
                   if i + 1 < len(groups) else None)
        _render_segment(project, groups[i], seg_lens[i + slide_at], i + slide_at,
                        out, channel=seg_channel, chapter=chapter, threads=seg_threads)
        return i, out

    # The drawn cuts paint every frame in Python, and Python threads take turns
    # on one interpreter lock: six "parallel" workers were drawing at little
    # more than one core's pace. Those segments go to separate processes
    # instead — each its own interpreter, on its own core — and a long one is
    # cut into chunks of about CHUNK_SECONDS so that one minute-long picture
    # does not leave every other core idle while it finishes. A drawing
    # process peaks around a quarter of a gigabyte, so cores rather than
    # memory set the count; one core is left for the encoders and the app.
    if cuts.is_cut(project.style.format):
        seg_paths = _draw_segments(project, groups, seg_lens, slide_at, seg_dir,
                                   seg_channel, free_mb, progress)
    else:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            results = {}
            for i, path in pool.map(work, range(len(groups))):
                results[i] = path
                done += 1
                if done % 3 == 0 or done == len(groups):
                    progress(f"  segments {done}/{len(groups)}")
            seg_paths = [results[i] for i in range(len(groups))]

    if intro_path:
        # The slate is already the right length; pad it to seg_len so its tail
        # has something to crossfade out of, exactly like every other segment.
        held = seg_dir / "intro_held.mp4"
        ffutil.run(["-i", str(intro_path),
                    "-vf", f"tpad=stop_mode=clone:stop_duration={T + 0.5:.3f}",
                    "-t", f"{seg_lens[0]:.3f}", "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-an", str(held)])
        seg_paths.insert(0, held)

    if pres_src:
        clip = _render_presenter(project, pres_seg_len, seg_dir / "presenter.mp4")
        seg_paths.insert(pres_index, clip)

    if outro_path:
        # Like the slate, the card is already the right length; it is padded on
        # its last frame so the dissolve into it has somewhere to land.
        held = seg_dir / "outro_held.mp4"
        ffutil.run(["-i", str(outro_path),
                    "-vf", f"tpad=stop_mode=clone:stop_duration={T + 0.5:.3f}",
                    "-t", f"{seg_lens[-1]:.3f}", "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-an", str(held)])
        seg_paths.append(held)

    # ------------------------------------------------------ final assembly
    # Input order is load-bearing: the filtergraph refers to inputs by index, so
    # they are appended in one place and the index is tracked as we go.
    music = pick_music(project, progress)
    inputs: list[str] = []
    for p in seg_paths:
        inputs += ["-i", str(p)]
    next_idx = len(seg_paths)

    inputs += ["-i", str(narration)]
    next_idx += 1

    # The camera clip is re-opened here purely for its audio, trimmed the same
    # way as its picture so the two stay locked together.
    presenter_audio = None
    if pres_src and project.presenter.has_audio:
        presenter_audio = (next_idx, pres_offset,
                           max(0.0, project.presenter.trim_start), pres_seg_len)
        inputs += ["-i", str(pres_src)]
        next_idx += 1
        progress(f"Camera audio joins the voice bus at {pres_offset:.1f}s")

    # The slate's and the end card's own stings, if they have them.
    sting_audio: list = []
    stings = _stings_for(project, bool(intro_path), bool(outro_path))
    if "intro" in stings:
        sting_file, spec = stings["intro"]
        # The slate is the first segment unless a camera clip was put ahead
        # of it, in which case the sting waits for that clip to finish.
        intro_offset = durations[0] if (pres_src and pres_index == 0) else 0.0
        sting_audio.append((next_idx, intro_offset, intro_len, spec, "intro"))
        inputs += ["-i", str(sting_file)]
        next_idx += 1
        window = float(spec.music_start)
        progress(f"Slate sting: {spec.music_filename or sting_file.name}"
                 + (f", from {window:.1f}s into it" if window > 0.05 else "")
                 + (f" (starting at {intro_offset:.1f}s)" if intro_offset else ""))
    if "outro" in stings:
        sting_file, spec = stings["outro"]
        outro_offset = sum(durations[:-1])
        sting_audio.append((next_idx, outro_offset, outro_len, spec, "outro"))
        inputs += ["-i", str(sting_file)]
        next_idx += 1
        progress(f"End card sting: {spec._spec.sting_filename or sting_file.name}"
                 f" (starting at {outro_offset:.1f}s)")

    if music:
        # -stream_loop -1 runs the bed round for as long as the video needs; the
        # graph then trims it to length. A five minute track under a twenty-five
        # minute video plays five times.
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        progress(f"Music bed: {music.name}"
                 + (", looped to length" if _music_loops(music, total) else "")
                 + (" — held back until the slate ends"
                    if any(s[4] == "intro" for s in sting_audio) else ""))
    elif not project.music:
        progress("No music bed chosen, rendering narration only")
    else:
        progress("Rendering narration only")

    # Crossfade chain: each xfade starts T seconds before the previous clip ends.
    # Every segment is padded with a few copies of its last frame first. The
    # offsets come from the planned lengths, and a segment that came out even a
    # fraction of a frame short would put the next join past its end — xfade
    # then ends the whole video stream there and the rest of the render plays
    # over a frozen picture. The padding is overlapped by the next segment or
    # trimmed by -t, so it never shows.
    pad = f"tpad=stop_mode=clone:stop_duration={4 / FPS:.4f}"
    if len(seg_paths) == 1:
        video_graph = "[0:v]null[vout]"
    else:
        parts = [f"[{i}:v]{pad}[p{i}]" for i in range(len(seg_paths))]
        offset = seg_lens[0] - T
        prev = "[p0]"
        for i in range(1, len(seg_paths)):
            label = "[vout]" if i == len(seg_paths) - 1 else f"[x{i}]"
            parts.append(
                f"{prev}[p{i}]xfade=transition=fade:duration={T:.3f}:"
                f"offset={offset:.3f}{label}"
            )
            prev = label
            offset += seg_lens[i] - T
        video_graph = ";".join(parts)

    # An end screen is long enough that where the bed gives out is a decision,
    # so the card carries the fade length; without one the default stands.
    music_fade = 5.0
    if outro_path:
        card = _slate_channel(project)
        if card:
            music_fade = float(card.outro.music_fade)

    graph = video_graph + ";" + _audio_graph(project, len(seg_paths), total,
                                             bool(music), presenter_audio, sting_audio,
                                             music_fade)

    safe = "".join(c if c.isalnum() or c in " -_" else "" for c in (project.title or "video"))
    out_name = (safe.strip().replace(" ", "_") or "video")[:60] + (
        "_preview.mp4" if preview else ".mp4")
    out_path = root / "out" / out_name

    def encode(gpu: bool) -> None:
        pre, vf, codec = ffutil.h264(out_path, crf=19, preset="medium", gpu=gpu)
        full = graph + (f";[vout]fps={FPS},{vf}[venc]" if vf else "")
        ffutil.run([
            *pre, *inputs, "-filter_complex", full,
            "-map", "[venc]" if vf else "[vout]", "-map", "[aout]",
            "-t", f"{total:.3f}",
            *codec, "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(out_path),
        ], timeout=7200)

    gpu = ffutil.gpu_status()["active"]
    progress("Encoding final cut, this is the slow part"
             + (f" — on the GPU ({ffutil.gpu_encoder()['label']})" if gpu else ""))
    try:
        encode(gpu)
    except ffutil.FFError as exc:
        if not gpu:
            raise
        # The GPU took the job and then failed it. The CPU has never failed
        # this encode, so it gets the same graph rather than the render dying.
        ffutil.gpu_failed(str(exc))
        progress("The GPU encoder failed; encoding on the CPU instead "
                 f"({str(exc).strip().splitlines()[-1][:120]})")
        encode(False)

    result = {
        "output": f"out/{out_path.name}",
        "duration": round(ffutil.duration(out_path), 2),
        "size_mb": round(out_path.stat().st_size / 1e6, 1),
        "slides": len(plan),
        "pictures": len(groups),
        "preview": preview,
        "music": music.name if music else "",
    }
    if not preview:
        project.status = "rendered"
    project.render = result
    progress(f"Done: {result['output']} — {result['duration'] / 60:.1f} min, "
             f"{result['size_mb']} MB")
    return result


# ------------------------------------------------------------- live preview
# One picture's worth of the cut, at a quarter of the frame and half the frame
# rate — a check on the picture, the framing and the words, not a proof of the
# encode. Rendering the whole video to see one picture is the thing this
# exists to avoid, so it is deliberately cheap: everything is composed exactly
# as the finished cut composes it, just small.
PREVIEW_SCALE = 0.25
PREVIEW_FPS = max(1, FPS // 2)
PREVIEW_CRF = 30


def preview_size() -> tuple[int, int]:
    """The preview frame, even on both axes because the encoder insists."""
    return (max(2, round(WIDTH * PREVIEW_SCALE) // 2 * 2),
            max(2, round(HEIGHT * PREVIEW_SCALE) // 2 * 2))


def _segments_before_slides(project: Project) -> int:
    """How many segments a full render puts in front of the first paragraph.

    The Ken Burns move cycles on the segment index (see MOVES), so previewing
    one picture has to count the slate and the camera clip the same way
    `render` does, or the picture drifts the other way than it will in the
    finished cut. Nothing is rendered here — this only asks whether those
    segments would be.
    """
    n = 1 if _has_slate(project) else 0
    pres = project.presenter
    if (pres.usable() and (project_dir(project.id) / pres.path).exists()
            and pres.position in ("start", "after_intro")):
        n += 1
    return n


def preview_opening(project: Project, kind: str,
                    progress: Progress = lambda m: None) -> dict:
    """Render this video's own opening card or end card, on its own, to play.

    Full size and full rate, unlike `preview_segment`: both cards are a few
    seconds of generated frames rather than a minute of staged archive, so
    there is nothing to save by rendering them small, and what a card needs
    checking for — whether the title fits, whether the plates land where
    YouTube's elements will — is exactly what a smaller frame hides.
    """
    cache = project_dir(project.id) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"opening_{kind}.webm"
    build = _build_outro if kind == "outro" else _build_intro
    path, length = build(project, progress, out)
    if path is None:
        raise ValueError("Nothing to preview: turn this card on first.")
    return {
        "path": f"cache/{out.name}",
        "kind": kind,
        "seconds": round(length, 2),
        "rendered_at": round(out.stat().st_mtime),
    }


# Bump when anything about how a proxy is composed changes, so every cached one
# is rebuilt rather than trusted.
PROXY_VERSION = 1


def _stat(path: Path | None) -> list[int] | None:
    try:
        s = path.stat()      # type: ignore[union-attr]
    except (OSError, AttributeError):
        return None
    return [s.st_mtime_ns, s.st_size]


def _proxy_key(project: Project, groups: list[list[tuple[Slide, float]]],
               index: int, channel: Any) -> str:
    """Everything a proxy's pixels or sound depend on, as one short hash.

    The timeline plays cached proxies, so "is this one still right" has to be
    answerable without rendering it: if any word, picture, take file, cue,
    style knob or neighbouring chapter changed, the hash does too.
    """
    import dataclasses
    import hashlib
    import json

    root = project_dir(project.id)
    group = groups[index]
    lead = group[0][0]
    nxt = groups[index + 1][0][0] if index + 1 < len(groups) else None
    slides = []
    for s, d in group:
        row = dataclasses.asdict(s)
        # Search results nobody picked cannot change the picture on screen.
        row["candidates"] = [c for c in s.candidates if c["id"] == s.chosen_id]
        take = (s.take or {}).get("path")
        slides.append([row, d, _stat(root / take) if take else None])
    pic = _chosen(project, lead)[0]
    blob = json.dumps(
        [PROXY_VERSION, index, slides, _stat(pic),
         chapter_card(project, nxt) if nxt else None,
         dataclasses.asdict(project.style),
         dataclasses.asdict(channel) if dataclasses.is_dataclass(channel) else None,
         _segments_before_slides(project), list(preview_size()), PREVIEW_FPS],
        default=str, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _proxy_paths(project: Project, lead: Slide) -> tuple[Path, Path]:
    cache = project_dir(project.id) / "cache"
    return cache / f"seg_{lead.id}.webm", cache / f"seg_{lead.id}.key"


def _proxy_ready(project: Project, groups, index: int, channel: Any) -> bool:
    out, keyfile = _proxy_paths(project, groups[index][0][0])
    try:
        return (out.exists() and out.stat().st_size > 0
                and keyfile.read_text() == _proxy_key(project, groups, index, channel))
    except OSError:
        return False


def _segment_timing(project: Project, groups, index: int) -> tuple[float, float, float]:
    """(screen seconds, crossfade, length of the segment's file).

    The screen time carries the opening and closing silence on the first and
    last picture; the file is longer by one crossfade, half of it either side.
    """
    T = cuts.transition_for(project.style)
    dur = round(sum(d for _s, d in groups[index]), 3)
    if index == 0:
        dur += HEAD_PAD
    if index == len(groups) - 1:
        dur += TAIL_PAD
    return dur, T, dur + T


def _build_proxy(project: Project, groups, index: int, progress: Progress,
                 *, reuse: bool, download: bool = True) -> dict:
    from . import channels as channels_mod
    group = groups[index]
    lead = group[0][0]
    channel = channels_mod.load_or_none(project.channel_id)
    out, keyfile = _proxy_paths(project, lead)
    size = preview_size()
    key = _proxy_key(project, groups, index, channel)
    dur, T, seg_len = _segment_timing(project, groups, index)

    def result() -> dict:
        return {
            "path": f"cache/{out.name}", "slide": lead.id, "key": key,
            "picture": index + 1, "pictures": len(groups),
            "paragraphs": len(group), "seconds": round(seg_len, 2),
            "width": size[0], "height": size[1], "fps": PREVIEW_FPS,
            "rendered_at": round(out.stat().st_mtime),
        }

    if (reuse and out.exists() and out.stat().st_size > 0
            and keyfile.exists() and keyfile.read_text() == key):
        return result()

    if download and media.download_chosen(project, progress, only=[lead]):
        progress("That picture could not be downloaded; this is the graded "
                 "slate the render would fall back to")

    chapter = (chapter_card(project, groups[index + 1][0][0])
               if index + 1 < len(groups) else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    # `.webm` is what makes these play in the app's own window on a Linux
    # desktop that has no H.264 decoder — see `ffutil.video_args`.
    mute = out.with_name(f"seg_{lead.id}_mute.webm")

    progress(f"Picture {index + 1} of {len(groups)}: {seg_len:.1f}s "
             f"at {size[0]}×{size[1]}, {PREVIEW_FPS}fps")
    _render_segment(project, group, seg_len,
                    index + _segments_before_slides(project), mute,
                    channel=channel, chapter=chapter, size=size,
                    fps=PREVIEW_FPS, crf=PREVIEW_CRF, preset="ultrafast",
                    threads=max(2, min(8, os.cpu_count() or 4)))

    # Where the voice lands inside the segment: half a crossfade in, plus the
    # opening silence if this is the top of the video. The same arithmetic the
    # full render's narration bed uses, for one group of paragraphs.
    voice = out.with_name(f"seg_{lead.id}.wav")
    try:
        audio_mod.build_slice(project, [s for s, _d in group], voice,
                              T / 2 + (HEAD_PAD if index == 0 else 0.0))
    except (ValueError, ffutil.FFError):
        progress("Nothing recorded for this bit yet, so it plays silent")
        os.replace(mute, out)
    else:
        ffutil.run(["-i", str(mute), "-i", str(voice),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    *ffutil.audio_args(out, bitrate="96k"),
                    "-t", f"{seg_len:.3f}", str(out)])
        mute.unlink(missing_ok=True)
        voice.unlink(missing_ok=True)
    keyfile.write_text(key)
    progress(f"Preview ready: {out.stat().st_size / 1e6:.1f} MB")
    return result()


def _groups_for_preview(project: Project) -> list[list[tuple[Slide, float]]]:
    return _picture_groups(project, _slide_durations(project, use_estimates=True))


def preview_segment(project: Project, slide_id: str,
                    progress: Progress = lambda m: None) -> dict:
    """The one picture this paragraph sits under, rendered small, with its voice.

    Nothing about the composition is simplified: the same group, the same
    timings, the same titles and the same grade as the finished cut, at a
    quarter of the frame and half the rate — which answers "is this the right
    picture, pointed the right way" in seconds rather than by re-rendering the
    whole video to find out.
    Paragraphs with nothing recorded yet get their estimated length, exactly
    as a preview cut gives them. Always re-rendered: this is the button.
    """
    groups = _groups_for_preview(project)
    index = next((i for i, g in enumerate(groups)
                  if any(s.id == slide_id for s, _d in g)), -1)
    if index < 0:
        raise ValueError("That paragraph is not in the cut.")
    return _build_proxy(project, groups, index, progress, reuse=False)


def proxy_segment(project: Project, index: int,
                  progress: Progress = lambda m: None, *, download: bool = True) -> dict:
    """The same small render, kept: the timeline plays these back to back, so
    one that is still right for the current script is reused rather than drawn
    again."""
    groups = _groups_for_preview(project)
    if not 0 <= index < len(groups):
        raise ValueError("That picture is not in the cut.")
    return _build_proxy(project, groups, index, progress, reuse=True, download=download)


# ------------------------------------------------------------ timeline slates
def _slate_has(project: Project, kind: str) -> bool:
    if kind == "intro":
        return _has_slate(project)
    if not project.use_outro:
        return False
    channel = _slate_channel(project)
    return bool(channel and channel.outro.enabled)


def _slate_key(project: Project, kind: str) -> str:
    import dataclasses
    import hashlib
    import json

    channel = _slate_channel(project)
    extra = None
    if kind == "outro":
        extra = _stat(_last_picture(project))      # the card can sit on it
    # Not the whole channel: a standalone one is made up on the spot, with an
    # id and a timestamp that differ every time it is asked for.
    parts = ([channel.name, channel.tagline, dataclasses.asdict(channel.intro),
              dataclasses.asdict(channel.outro), dataclasses.asdict(channel.style)]
             if channel else None)
    blob = json.dumps([PROXY_VERSION, kind, project.title, parts, extra, list(preview_size()), PREVIEW_FPS],
                      default=str, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _slate_paths(project: Project, kind: str) -> tuple[Path, Path]:
    cache = project_dir(project.id) / "cache"
    return cache / f"tl_{kind}.webm", cache / f"tl_{kind}.json"


def _slate_state(project: Project, kind: str) -> dict | None:
    """What the timeline knows about the slate or end card, or None for none.

    A slate's length is only learned by drawing it (each template settles its
    own), so until it has been drawn this is the length it was asked for, and
    `known` says so. Drawing it records the real one beside the proxy.
    """
    import json
    if not _slate_has(project, kind):
        return None
    out, meta = _slate_paths(project, kind)
    key = _slate_key(project, kind)
    try:
        saved = json.loads(meta.read_text())
    except (OSError, ValueError):
        saved = {}
    if saved.get("key") == key:
        if saved.get("none"):
            return None                     # tried, and there is nothing to draw
        if out.exists() and out.stat().st_size > 0:
            return {"length": float(saved["length"]), "known": True, "ready": True,
                    "key": key, "stamp": round(out.stat().st_mtime)}
    channel = _slate_channel(project)
    if kind == "intro":
        est = max(2.5, min(12.0, float(project.intro.duration if not project.channel_id
                                       else channel.intro.duration)))
    else:
        from . import outro as outro_mod
        est = outro_mod._length(channel.outro)
    return {"length": round(est, 3), "known": False, "ready": False, "key": key,
            "stamp": round(out.stat().st_mtime) if out.exists() else 0,
            "have": out.exists() and out.stat().st_size > 0}


def _build_slate_proxy(project: Project, kind: str, progress: Progress) -> dict:
    """Draw the slate or end card as the finished cut would, then shrink it."""
    import json
    out, meta = _slate_paths(project, kind)
    state = _slate_state(project, kind)
    if state and state["ready"]:
        return {"ref": kind, "rendered_at": state["stamp"]}
    key = _slate_key(project, kind)
    out.parent.mkdir(parents=True, exist_ok=True)
    full = out.with_name(f"tl_{kind}_full.mp4")
    progress(f"Drawing the {'opening slate' if kind == 'intro' else 'end card'}")
    build = _build_intro if kind == "intro" else _build_outro
    path, length = build(project, progress, full)
    if path is None:
        meta.write_text(json.dumps({"key": key, "none": True}))
        out.unlink(missing_ok=True)
        raise ValueError("There is nothing to draw there: the "
                         + ("slate" if kind == "intro" else "end card")
                         + " cannot be made for this video.")
    w, h = preview_size()
    ffutil.run(["-i", str(full), "-vf", f"scale={w}:{h},fps={PREVIEW_FPS}", "-an",
                *ffutil.video_args(out, crf=PREVIEW_CRF), "-pix_fmt", "yuv420p", str(out)])
    full.unlink(missing_ok=True)
    meta.write_text(json.dumps({"key": key, "length": round(float(length), 3)}))
    return {"ref": kind, "rendered_at": round(out.stat().st_mtime)}


def proxy_ref(project: Project, ref: str, progress: Progress = lambda m: None,
              *, download: bool = True) -> dict:
    """Draw one timeline entry: "intro", "outro", or a picture's number."""
    if ref in ("intro", "outro"):
        if not _slate_has(project, ref):
            raise ValueError("There is no such card in this video.")
        return _build_slate_proxy(project, ref, progress)
    out = proxy_segment(project, int(ref), progress, download=download)
    out["ref"] = ref
    return out


# --------------------------------------------------------------- timeline mix
def _layout(project: Project) -> dict:
    """The cut's running order in picture time, slates included.

    The same list of durations `render` builds: slate, pictures, end card, each
    one's screen time with the head and tail padding on the first and last
    picture. Picture time starts at the first frame of whatever opens the video.
    """
    groups = _groups_for_preview(project)
    T = cuts.transition_for(project.style)
    intro = _slate_state(project, "intro")
    outro = _slate_state(project, "outro")
    body = [_segment_timing(project, groups, i)[0] for i in range(len(groups))]
    pre = intro["length"] if intro else 0.0
    total = pre + sum(body) + (outro["length"] if outro else 0.0)
    return {"groups": groups, "T": T, "intro": intro, "outro": outro,
            "body": body, "pre": pre, "total": total}


def _mix_paths(project: Project) -> tuple[Path, Path]:
    cache = project_dir(project.id) / "cache"
    return cache / "timeline_mix.webm", cache / "timeline_mix.key"


def _stings_for(project: Project, intro: bool = True, outro: bool = True) -> dict:
    """The slate's and the end card's own stings: role -> (file, spec).

    A channel's video takes its opening sting from the channel; a standalone
    one carries its own in the project folder. The end card's sting is read
    the same two ways. The spec handed back is what `intro.sting_chain` reads
    — the end card's fields are renamed onto that shape, with no tail, since
    the card is the last thing in the video and has nothing to ring over.
    """
    from types import SimpleNamespace
    from . import channels as channels_mod
    if project.channel_id:
        ch = channels_mod.load_or_none(project.channel_id)
        if not ch:
            return {}
        root, spec_in, spec_out = channels_mod.channel_dir(ch.id), ch.intro, ch.outro
    else:
        root = project_dir(project.id)
        spec_in, spec_out = project.intro, project.outro
    out: dict = {}
    if intro and spec_in.music and (root / spec_in.music).exists():
        out["intro"] = (root / spec_in.music, spec_in)
    if outro and getattr(spec_out, "sting", "") and (root / spec_out.sting).exists():
        out["outro"] = (root / spec_out.sting, SimpleNamespace(
            music_start=spec_out.sting_start, music_tail=0.0,
            music_fade=spec_out.sting_fade, music_db=spec_out.sting_db,
            _spec=spec_out))
    return out


def _sting_params(spec) -> dict:
    import dataclasses
    return (dataclasses.asdict(spec) if dataclasses.is_dataclass(spec)
            else {k: v for k, v in vars(spec).items() if not k.startswith("_")})


def _mix_key(project: Project, lay: dict) -> str:
    import dataclasses
    import hashlib
    import json

    root = project_dir(project.id)
    takes = [[s.id, _stat(root / s.take["path"]) if (s.take or {}).get("path") else None]
             for s in project.slides]
    music = pick_music(project)
    stings = _stings_for(project, bool(lay["intro"]), bool(lay["outro"]))
    card = _slate_channel(project) if lay["outro"] else None
    blob = json.dumps(
        [PROXY_VERSION, takes, lay["body"], lay["pre"], lay["total"],
         lay["intro"] and lay["intro"]["length"], lay["outro"] and lay["outro"]["length"],
         audio_mod.paragraph_gaps(project),
         str(music), _stat(music),
         {role: [str(f), _stat(f), _sting_params(spec)] for role, (f, spec) in stings.items()},
         project.style.music_db, project.voice.target_lufs,
         float(card.outro.music_fade) if card else 5.0],
        default=str, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _mix_state(project: Project, lay: dict) -> dict:
    music = pick_music(project)
    sting = _stings_for(project, bool(lay["intro"]), bool(lay["outro"]))
    audible = bool(music or sting or any(s.take for s in project.slides))
    out, keyfile = _mix_paths(project)
    key = _mix_key(project, lay) if audible else ""
    have = out.exists() and out.stat().st_size > 0
    try:
        fresh = have and keyfile.read_text() == key
    except OSError:
        fresh = False
    return {"audible": audible, "ready": bool(audible and fresh), "have": bool(audible and have),
            "stamp": round(out.stat().st_mtime) if have else 0,
            "path": f"cache/{out.name}", "music": music.name if music else "",
            "sting": bool(sting), "stings": sorted(sting)}


def build_mix(project: Project, progress: Progress = lambda m: None) -> dict:
    """The whole cut's sound, as one file: narration, the slate's sting and the
    music bed under the voice.

    Built with `_audio_graph`, the graph the finished render mixes with, so it
    ducks, fades and levels the same way. Audio only, so it takes a few seconds
    however long the video is; the player uses it as the clock and plays the
    picture proxies silently against it.
    """
    lay = _layout(project)
    state = _mix_state(project, lay)
    if not state["audible"]:
        return state
    if state["ready"]:
        return state
    out, keyfile = _mix_paths(project)
    root = project_dir(project.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    T, pre, total = lay["T"], lay["pre"], lay["total"]

    gaps = audio_mod.gap_map(project)
    plan = dict((s.id, d) for s, d in _slide_durations(project, use_estimates=True))
    fill = {s.id: max(0.1, plan[s.id] - gaps.get(s.id, PARAGRAPH_GAP))
            for s in project.slides if not s.take and s.id in plan}
    narration = out.with_name("timeline_narration.wav")
    # No T/2 on the lead-in, unlike the finished cut: this track is laid against
    # picture time, where a picture's window starts at its boundary.
    audio_mod.build_narration(project, narration, lead_in=pre, fill=fill)

    inputs = ["-i", str(narration)]
    n = 1
    sting_audio = []
    stings = _stings_for(project, bool(lay["intro"]), bool(lay["outro"]))
    if "intro" in stings:
        sting_audio.append((n, 0.0, lay["intro"]["length"], stings["intro"][1], "intro"))
        inputs += ["-i", str(stings["intro"][0])]
        n += 1
    if "outro" in stings:
        sting_audio.append((n, lay["total"] - lay["outro"]["length"],
                            lay["outro"]["length"], stings["outro"][1], "outro"))
        inputs += ["-i", str(stings["outro"][0])]
        n += 1
    music = pick_music(project, progress)
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
    music_fade = 5.0
    if lay["outro"]:
        card = _slate_channel(project)
        if card:
            music_fade = float(card.outro.music_fade)
    graph = _audio_graph(project, 0, total, bool(music), None, sting_audio, music_fade)
    progress("Mixing the sound for the whole cut"
             + (f" with the bed “{music.stem}”" if music else ", narration only"))
    ffutil.run([*inputs, "-filter_complex", graph, "-map", "[aout]",
                "-t", f"{total:.3f}", "-ar", "48000",
                *ffutil.audio_args(out, bitrate="96k"), str(out)], timeout=900)
    narration.unlink(missing_ok=True)
    keyfile.write_text(_mix_key(project, lay))
    return _mix_state(project, lay)


def timeline(project: Project) -> dict:
    """The cut laid out in time, without rendering anything.

    Every number is the one the full render uses — the same durations, the
    same pauses, the same head and tail padding — in picture time, which starts
    at the first frame of the slate if there is one. Paragraphs with no
    recording use their estimated length and say so; a slate or end card not
    yet drawn uses the length it was asked for.
    """
    from . import channels as channels_mod
    lay = _layout(project)
    groups, T = lay["groups"], lay["T"]
    channel = channels_mod.load_or_none(project.channel_id)
    index_of = {s.id: i for i, s in enumerate(project.slides)}
    segments: list[dict] = []
    t = 0.0

    def slate_row(kind: str, st: dict, start: float) -> dict:
        out, _meta = _slate_paths(project, kind)
        return {
            "ref": kind, "type": kind, "n": 0, "group": -1, "lead": "",
            "start": round(start, 3), "duration": round(st["length"], 3), "skip": 0.0,
            "kind": "", "problems": [], "paragraphs": [],
            "ready": st["ready"], "have": bool(st["ready"] or st.get("have")),
            "estimated": not st["known"], "stamp": st["stamp"],
            "path": f"cache/{out.name}",
        }

    if lay["intro"]:
        segments.append(slate_row("intro", lay["intro"], t))
        t += lay["intro"]["length"]
    for i, group in enumerate(groups):
        dur = lay["body"][i]
        lead = group[0][0]
        head = HEAD_PAD if i == 0 else 0.0
        paras = []
        pt = t + head
        for s, d in group:
            paras.append({
                "id": s.id, "index": index_of[s.id], "start": round(pt, 3),
                "duration": d, "text": s.narration, "title": s.title,
                "chapter": s.chapter, "words": s.word_count,
                "recorded": bool(s.take), "section": s.section,
            })
            pt += d
        _path, kind, _focal = _chosen(project, lead)
        problems = []
        if not lead.chosen_id:
            problems.append("no picture chosen")
        missing = sum(1 for s, _d in group if not s.take)
        if missing:
            problems.append(f"{missing} paragraph{'s' if missing > 1 else ''} not recorded"
                            " (estimated length)")
        # Only the documentary cut holds one frame; every other format redraws
        # as the paragraphs change, so a long run there is not a still picture.
        if dur > 25 and project.style.format == "kenburns":
            problems.append(f"the same picture holds for {dur:.0f}s")
        out, _keyfile = _proxy_paths(project, lead)
        segments.append({
            "ref": str(i), "type": "picture", "n": i + 1, "group": i, "lead": lead.id,
            "start": round(t, 3), "duration": round(dur, 3), "skip": round(T / 2, 3),
            "kind": kind, "problems": problems, "paragraphs": paras,
            "ready": _proxy_ready(project, groups, i, channel),
            # Something to play, even if the script has moved on since.
            "have": out.exists() and out.stat().st_size > 0,
            "stamp": round(out.stat().st_mtime) if out.exists() else 0,
            "path": f"cache/{out.name}",
        })
        t += dur
    if lay["outro"]:
        segments.append(slate_row("outro", lay["outro"], t))
        t += lay["outro"]["length"]
    for n, seg in enumerate(segments):
        seg["index"] = n
    size = preview_size()
    pres = project.presenter
    return {
        "segments": segments, "total": round(t, 3), "fps": PREVIEW_FPS,
        "width": size[0], "height": size[1],
        "format": project.style.format,
        "mix": _mix_state(project, lay),
        "camera_clip": bool(pres.usable() and (project_dir(project.id) / pres.path).exists()),
        "estimated": any(not s.take for s in project.slides),
    }


# --------------------------------------------------------------- attribution
def _one_line(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def credits_text(project: Project) -> str:
    """An attribution block to paste into the video description."""
    lines = [f"{project.title}", ""]
    if project.subtitle:
        lines[0] = f"{project.title} — {project.subtitle}"
    lines.append("Image and footage credits:")
    seen = set()
    for slide in project.slides:
        cand = next((c for c in slide.candidates if c["id"] == slide.chosen_id), None)
        if not cand:
            continue
        key = cand.get("source_page") or cand.get("url")
        if key in seen:
            continue
        seen.add(key)
        # The creator's own uploads need no credit line.
        if cand.get("license") == "your own file":
            continue
        bits = [_one_line(cand.get("title") or "Untitled", 120)]
        if cand.get("author"):
            # Archive author fields can be whole paragraphs of wiki markup.
            bits.append(f"by {_one_line(cand['author'], 80)}")
        if cand.get("license"):
            bits.append(f"({cand['license']})")
        if cand.get("source_page"):
            bits.append(cand["source_page"])
        lines.append("- " + " ".join(bits))
    # The channel slate carries its own cast, credited the same way.
    if project.channel_id and project.use_intro:
        from . import channels
        channel = channels.load_or_none(project.channel_id)
        if channel and channel.intro.credits:
            lines += ["", f"Opening titles for “{channel.name}”:"]
            for c in channel.intro.credits:
                bits = [f"{c.get('subject', '')} —", c.get("title") or "portrait"]
                if c.get("author"):
                    bits.append(f"by {c['author']}")
                if c.get("license"):
                    bits.append(f"({c['license']})")
                if c.get("source_page"):
                    bits.append(c["source_page"])
                lines.append("- " + " ".join(bits))

    music = pick_music(project)          # credits list the bed, they do not log
    if music:
        lines += ["", f"Music: {music.stem}"]
    lines += ["", "Verify every licence before publishing. Some archives place "
                  "conditions on commercial reuse."]
    return "\n".join(lines)

"""Assemble slides, narration and music into the finished video."""
from __future__ import annotations

import concurrent.futures as cf
import math
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from . import audio as audio_mod
from . import cuts, ffutil, media, scenes, sysinfo, titles
from . import shots as shots_mod
from .config import (
    FPS, HEAD_PAD, HEIGHT, MUSIC_DIR, PARAGRAPH_GAP, TAIL_PAD, WIDTH,
    WORDS_PER_MINUTE,
)
from .schema import AUTO_MUSIC, Project, Slide, chapter_title, group_slides
from .store import project_dir
from .take_edits import take_duration, take_words, kept_ranges

Progress = Callable[[str], None]

# Peak child RSS measured 2026-10-31 on Ryzen 7 7840-class, 8 cores,
# Radeon 780M: essay 2058.29 MB, kenburns 1406.14 MB (1080p30, CPU H.264,
# pf0bf417b's deepest group: 3 paragraphs). Rounded up to 500 MB; unmeasured
# formats use the larger allowance. Reproduce with scripts/measure_segment_rss.py.
SEGMENT_RSS_MB = {"essay": 2500, "kenburns": 1500, "default": 2500}

GRADES = {
    "warm": "colorbalance=rs=0.035:bs=-0.045,eq=saturation=0.95:contrast=1.05:gamma=0.99",
    "neutral": "eq=contrast=1.03:saturation=0.98",
    "cool": "colorbalance=rs=-0.03:bs=0.05,eq=saturation=0.96:contrast=1.04",
    "mono": "hue=s=0,eq=contrast=1.10:gamma=1.02",
}

CAMERA_OPS = ("set", "creep_in", "creep_out", "punch", "reveal")
EASE = {
    "linear": "{t}",
    "expo_out": "(1-pow(2,-10*{t}))",
    "power2_inout": "if(lt({t},0.5),2*{t}*{t},1-pow(-2*{t}+2,2)/2)",
}
# Real xfade names; ignore unsupported strings from user-edited FrameSpecs.
NAMED_XFADES = frozenset("""
    wipeleft wiperight wipeup wipedown slideleft slideright slideup slidedown
    circlecrop rectcrop distance fadeblack fadewhite radial smoothleft smoothright
    smoothup smoothdown circleopen circleclose vertopen vertclose horzopen horzclose
    dissolve pixelize diagtl diagtr diagbl diagbr hlslice hrslice vuslice vdslice
    hblur fadegrays wipetl wipetr wipebl wipebr squeezeh squeezev zoomin fadefast
    fadeslow hlwind hrwind vuwind vdwind coverleft coverright coverup coverdown
    revealleft revealright revealup revealdown
""".split())
JOIN_XFADE = {
    "fade": "transition=fade",
    "dip": "transition=fadeblack",
    "cut": "transition=custom:expr='if(gt(P,0.5),A,B)'",
}


def _join_preference(prev_group, next_group, frame) -> str:
    prev, nxt = prev_group[-1][0], next_group[0][0]
    if nxt.chapter or _dips_into([next_group], 0):
        return "dip"
    if prev.section != nxt.section:
        return next((name for name in frame.transition_types
                     if name in NAMED_XFADES), "fade")
    return "cut" if prev.beat == nxt.beat else "fade"


def _join_for(prev_group, next_group, frame) -> str:
    from .learning import choose
    preferred = _join_preference(prev_group, next_group, frame)
    candidates = [preferred, *frame.transition_types, *JOIN_XFADE]
    return choose('join', [n for n in candidates if n in JOIN_XFADE or n in NAMED_XFADES], frame)


def _join_graph(seg_lens, T, groups, frame, slide_at, *, group_indices=None, sponsor_indices=()):
    """Join files with the same overlap regardless of the transition cause."""
    pad = f"tpad=stop_mode=clone:stop_duration={4 / FPS:.4f}"
    if len(seg_lens) == 1:
        video_graph = "[0:v]null[vout]"
    else:
        parts = [f"[{i}:v]{pad}[p{i}]" for i in range(len(seg_lens))]
        offset = seg_lens[0] - T
        prev = "[p0]"
        for i in range(1, len(seg_lens)):
            label = "[vout]" if i == len(seg_lens) - 1 else f"[x{i}]"
            group_index = group_indices.get(i, -1) if group_indices is not None else i - slide_at
            from .learning import choose
            join = (_join_for(groups[group_index - 1], groups[group_index], frame)
                    if 0 < group_index < len(groups) else choose("join", ["fade", *JOIN_XFADE], frame))
            # Stage dips already fade inside their segments; avoid a second dip.
            if join == "dip" and _dips_into(groups, group_index):
                join = choose("join", ["fade", "cut"], frame)
            if i in sponsor_indices or i - 1 in sponsor_indices:
                join = "cut"
            transition = JOIN_XFADE.get(join, f"transition={join}")
            parts.append(
                f"{prev}[p{i}]xfade={transition}:duration={T:.3f}:"
                f"offset={offset:.3f}{label}"
            )
            prev = label
            offset += seg_lens[i] - T
        video_graph = ";".join(parts)

    return video_graph


def _pick_op(frame, index, prev_op, is_cut_in, is_payoff) -> str:
    cycle = ("creep_in", "set", "creep_out", "reveal")
    choices = (["punch"] if is_payoff else []) + [
        cycle[(index + n) % len(cycle)] for n in range(len(cycle))]
    from .learning import choose
    eligible = [op for op in choices if op != prev_op
                and not (frame.snap_on_cut and is_cut_in
                         and op in {"creep_out", "reveal"})]
    # Repetition is preferable to selecting a rejected look.
    alternatives = [op for op in CAMERA_OPS if op not in eligible]
    return choose('camera', [*eligible, *alternatives], frame)


def camera_plan(project, groups) -> list[str]:
    """One deterministic camera op per picture group, shared by every caller."""
    from .learning import effective_frame
    frame = effective_frame(project)
    payoffs = {loop.get("payoff_beat") for loop in
               ((project.outline or {}).get("hook") or {}).get("open_loops", [])}
    plan = []
    for i, group in enumerate(groups):
        lead = group[0][0]
        plan.append(_pick_op(
            frame, i, plan[-1] if plan else None,
            i > 0 and _join_for(groups[i - 1], group, frame) == "cut",
            bool(lead.chapter) or bool(lead.beat and lead.beat in payoffs)))
    return plan


def _camera_amount(project, op, index):
    frame = project.frame
    low, high = ((frame.punch_min, frame.punch_max) if op == "punch"
                 else (frame.creep_min, frame.creep_max))
    target = high if index % 2 else (low + high) / 2
    return (target - 1) * project.style.ken_burns_amount / 0.10


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
              size: tuple[int, int] = (WIDTH, HEIGHT), fps: int = FPS,
              ease: str = "linear", origin: str = "center",
              move_max_s: float = 0.6) -> str:
    """Frame-driven camera motion; arrivals reach their target then hold."""
    n = max(2, frames)
    t = (f"min(1,on/{max(1, round(move_max_s * fps))})"
         if move in {"punch", "reveal"} else f"(on/{n - 1})")
    e = EASE[ease].format(t=t)
    if ease == "expo_out":
        e = f"if(gte({t},1),1,{e})"
    if move == "set":
        z = "1"
    elif move in {"creep_in", "punch"}:
        z = f"1+{amount:.4f}*{e}"
    else:
        z = f"1+{amount:.4f}-{amount:.4f}*{e}"
    x = "iw/2-(iw/zoom/2)"
    y = "(ih-ih/zoom)*0.33" if origin == "top" and not focal_px else "ih/2-(ih/zoom/2)"
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
        d = take_duration(take)
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
    boundaries = _sponsor_placements(project, plan)
    groups = []
    for run in runs:
        group = []
        for slide in run:
            group.append((slide, by_id[slide.id]))
            if slide.id in boundaries:
                groups.append(group)
                group = []
        if group:
            groups.append(group)
    return groups


def _sponsor_placements(project, plan):
    from . import sponsors
    intro = _slate_state(project, "intro") if project.sponsors else None
    return sponsors.placements(project, plan, intro["length"] if intro else 0.0)


def _sponsor_audio(project, entries, inputs, next_idx, lead=0.0):
    """Append read inputs in the same order the audio graph indexes them."""
    from . import sponsors
    audio = []
    for slot, start in entries:
        if (slot.take or {}).get("path"):
            inputs += ["-i", str(project_dir(project.id) / slot.take["path"])]
            audio.append((next_idx, start + lead, sponsors.duration(slot)))
            next_idx += 1
    return audio, next_idx


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
                   channel, free_mb, progress: Progress, *, targets=None) -> list[Path]:
    """Every picture's segment in a drawn cut, drawn across worker processes."""
    import multiprocessing as mp

    targets = targets or [seg_dir / f"seg{i + slide_at:04d}.mp4" for i in range(len(groups))]
    scratch = seg_dir / "pieces"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir()
    expected_gpu = bool(ffutil.gpu_status()["active"])
    scene_cut = cuts.uses_scene(project.style)
    jobs = []
    split: dict[int, int] = {}
    for i, group in enumerate(groups):
        if _segment_ready(targets[i]):
            continue
        seg_len = seg_lens[i + slide_at]
        total = cuts.frame_count(seg_len, FPS)
        n = 1 if scene_cut or group[0][0].on_camera or (group[0][0].cues or {}).get('blocks') else max(1, round(total / (CHUNK_SECONDS * FPS)))
        split[i] = n
        chapter = (chapter_card(project, groups[i + 1][0][0])
                   if i + 1 < len(groups) else None)
        name = f"seg{i + slide_at:04d}"
        for c in range(n):
            a, b = total * c // n, total * (c + 1) // n
            out = scratch / (f"{name}.mp4" if n == 1 else f"{name}.part{c:02d}.mp4")
            jobs.append((project, group, seg_len, i + slide_at, out, channel, chapter,
                         0, i, c, (a, b)))
    if not jobs:
        scratch.rmdir()
        return targets
    cores = os.cpu_count() or 4
    workers = max(1, min(len(jobs), cores - 1, 3 if scene_cut else 15))
    if free_mb is not None:
        workers = max(1, min(workers, int(free_mb // 800)))
    threads = max(1, cores // workers)
    jobs = [j[:7] + (threads,) + j[8:] for j in jobs]
    progress(f"Drawing {len(groups)} pictures as {len(jobs)} pieces, {workers} at a time")

    # spawn, not fork: the app process has a web server and job threads
    # running, and a forked copy of those is how a child hangs on a lock it
    # inherited mid-use. It is also what macOS does anyway.
    parts: dict[int, dict[int, tuple[Path, bool]]] = {i: {} for i in range(len(groups))}

    def finish(i):
        # A GPU fallback must never leave CPU pixels under the GPU cache key.
        if any(gpu != expected_gpu for _path, gpu in parts[i].values()):
            targets[i] = targets[i].with_suffix(".uncached.mp4")
        if split[i] == 1:
            _publish_segment(parts[i][0][0], targets[i])
            return
        out = targets[i].with_suffix(".partial.mp4")
        pieces = [parts[i][c] for c in range(split[i])]
        listing = scratch / f"seg{i + slide_at:04d}.txt"
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
        _publish_segment(out, targets[i])

    done = 0
    error = None
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("spawn")) as pool:
        futures = [pool.submit(_draw_segment, job) for job in jobs]
        for future in cf.as_completed(futures):
            try:
                i, c, out, gpu = future.result()
                parts[i][c] = (out, gpu)
                if len(parts[i]) == split[i]:
                    finish(i)
            except Exception as exc:
                error = error or exc
            done += 1
            if done % 5 == 0 or done == len(jobs):
                progress(f"  pieces {done}/{len(jobs)}")
    if error:
        raise error

    shutil.rmtree(scratch)
    return targets


DIP = 0.45      # seconds each side of a dip through black


def _dips_into(groups, i: int) -> bool:
    """Does the group at `i` ask to be dipped into (a 3D shot's `join`)?"""
    if not 0 <= i < len(groups):
        return False
    lead = groups[i][0][0]
    return ((lead.shot or {}).get("intent") or {}).get("join") == "dip" and shots_mod.is_3d(lead)


def _stage_clips(project: Project, groups, seg_lens: list[float], size: tuple[int, int],
                 fps: int, progress: Progress, preview: bool) -> None:
    """Draw every 3D shot the cut needs before the segments are composed.
    Refuses a real render with shots missing; a preview shows a slate."""
    groups_and_lengths = [(g, seg_lens[i]) for i, g in enumerate(groups) if not g[0][0].on_camera]
    groups = [g for g, _length in groups_and_lengths]
    seg_lens = [length for _g, length in groups_and_lengths]
    if not groups:
        return
    st = shots_mod.status(project)
    missing = shots_mod.missing_shots(project, groups)
    if missing and not preview:
        raise ValueError(f"{len(missing)} 3D paragraph(s) have no shot yet. Plan the "
                         "shots on the Stage tab first.")
    if missing:
        progress(f"Preview: {len(missing)} 3D paragraph(s) have no shot yet and show a slate")
    if st["counts"]["flagged"]:
        progress(f"{st['counts']['flagged']} 3D shot(s) are flagged on the Stage tab; "
                 "rendering them as they are")
    if st["counts"]["stale"]:
        progress(f"{st['counts']['stale']} 3D shot(s) were solved for an older version of "
                 "their paragraph or model; solve them again on the Stage tab")
    gone = {s.id for s in missing}
    wanted = [(g[0][0], seg_lens[i]) for i, g in enumerate(groups)
              if shots_mod.is_3d(g[0][0]) and g[0][0].id not in gone]
    shots_mod.ensure_clips(project, wanted, size, fps, progress)


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


def _picture_source(project: Project, slide: Slide) -> Slide:
    """A sponsor may split a held picture, but the resumed asset stays put."""
    if any(slot.enabled for slot in project.sponsors):
        placed = _sponsor_placements(project, _slide_durations(project, True))
        for run in group_slides(project.slides, project.style.picture_every):
            for index, member in enumerate(run):
                if member.id == slide.id and any(s.id in placed for s in run[:index]):
                    return run[0]
    return slide


def _chosen(project: Project, slide: Slide, *, preview: bool = False) -> tuple[Path | None, str, list[float]]:
    """The slide's downloaded asset, its kind, and its focal point if one is set."""
    slide = _picture_source(project, slide)
    cand = next((c for c in slide.candidates if c["id"] == slide.chosen_id), None)
    if cand and cand.get("provider") == "footage":
        from .media.footage import resolve
        return resolve(cand, preview=preview), "video", (cand.get("focal") or [])
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
    if slide.custom_html:
        from . import custom_scenes
        root = project_dir(project.id) / 'media'
        ctx = custom_scenes.html_context(root, slide.custom_html, spec, seg_len, project)
        return custom_scenes.render(root, ctx, None, out, size=size, fps=fps, crf=crf)
    if not spec.get("elements"):
        style = slide_styles.get(slide_styles.id_from_format(project.style.format))
        if not style:
            return None
        spec = style.spec            # unfilled: the style's own placeholders
    try:
        if project.style.custom_engine != "pillow":
            from . import custom_scenes
            root = project_dir(project.id) / "media"
            ctx, ground = custom_scenes.context(
                root, spec, seg_len, hand=getattr(project.style, "board_hand", "marker"))
            return custom_scenes.render(root, ctx, ground, out, size=size, fps=fps, crf=crf)
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
def _clip_source(src: Path, seg_len: float, crop: str, span: tuple[float, float] | None = None) -> tuple[list[str], str]:
    """Inputs and a filtergraph that make a clip fill `seg_len` seconds.

    Archive clips are routinely shorter than the paragraph they sit under. A
    hard loop reads as a mistake, so a short clip is first slowed a little (up to
    a third), and if it still comes up short it is laid end to end with a half
    second dissolve at each seam, which reads as a considered cut instead.
    """
    XF = 0.5
    base = f"{crop},fps={FPS}"
    seek = (["-ss", f"{span[0]:.3f}", "-t", f"{span[1] - span[0]:.3f}"] if span else [])
    input_args = [*seek, "-i", str(src)]
    try:
        clip = span[1] - span[0] if span else float(ffutil.duration(src))
    except Exception:
        clip = 0.0
    if span and clip <= 0.3:
        return input_args, f"[0:v]{base},tpad=stop_mode=clone:stop_duration={seg_len:.3f}[base]"
    if clip <= 0.3:
        # Unreadable duration: fall back to the blunt loop rather than failing.
        return ["-stream_loop", "-1", "-i", str(src)], f"[0:v]{base}[base]"

    stretch = min(1.35, max(1.0, seg_len / clip)) if clip < seg_len else 1.0
    slow = f",setpts={stretch:.4f}*PTS" if stretch > 1.001 else ""
    effective = clip * stretch
    if effective >= seg_len - 0.05:
        return input_args, f"[0:v]{base}{slow}[base]"

    repeats = math.ceil((seg_len - XF) / max(0.2, effective - XF))
    if span and repeats > 8:
        return input_args, f"[0:v]{base},loop=loop=-1:size={max(1, round(clip * FPS))}:start=0{slow}[base]"
    if repeats > 8:
        # A two second clip under a minute of narration: dissolving eight times
        # would be sillier than simply running it round.
        return ["-stream_loop", "-1", "-i", str(src)], f"[0:v]{base}{slow}[base]"

    inputs: list[str] = []
    parts: list[str] = []
    for i in range(repeats):
        inputs += input_args
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


def _caption_timings(chunks: list[str], budget: float, frame) -> list[float]:
    """How long each caption in `chunks` holds, within `budget` seconds total.

    Proportional to word count, not an even split — a 6-word caption and an
    18-word one were getting the same time on screen, which read as either
    rushed or padded depending on which one you were looking at. A floor
    keeps a short caption from flashing by unreadably; if the floors alone
    would overrun the budget (a paragraph chopped into many short captions),
    everything is scaled back down together rather than overrunning `dur`.
    """
    return titles.caption_timings(chunks, budget, frame)


def _essay_phrases(project, member, dur, *, lead_in=0.0, last_line=False):
    spoken = take_duration(member.take) or dur * .85
    words = (take_words(member.take)
             if project.style.captions_engine != 'pillow' else [])
    plan = titles.phrases(member.narration, words, duration=min(dur, spoken),
                          frame=project.frame, lead_in=lead_in)
    if last_line and plan:
        plan[-1]['t1'] = max(plan[-1]['t1'], plan[-1]['t0'] + project.frame.last_line_min_s)
    return plan


def _title_hold(frame, title, dur):
    return max(0.0, min(dur - 1.2, frame.title_hold_base_s
                        + frame.title_hold_per_word_s * len(title.split())))


def _title_timing(project, member, dur, lead, last_line=False):
    start = (lead + max(0.0, member.title_at) if member.title_at is not None
             else project.frame.arrive_s)
    hold = (max(0.0, member.title_hold) if member.title_hold is not None
            else _title_hold(project.frame, member.title, dur))
    if last_line and member.title_hold is None:
        hold = max(hold, project.frame.last_line_min_s)
    return start, hold


def _title_window(project, member, dur, lead, offset, seg_len, last_line=False):
    arrival, hold = _title_timing(project, member, dur, lead, last_line)
    start = offset + arrival
    exit_s = project.frame.arrive_s * project.frame.exit_ratio
    return (start, min(seg_len - exit_s, start + hold),
            max(0.0, min(hold, seg_len - exit_s - offset - arrival)))


def _chapter_override(project, group):
    index = next(i for i, s in enumerate(project.slides) if s.id == group[-1][0].id)
    return project.slides[index + 1].chapter_hold if index + 1 < len(project.slides) else None


def _tail_pad(project, groups):
    """Extend only the final picture when its last line needs more reading time."""
    member, dur = groups[-1][-1]
    frame = project.frame
    if project.style.format == "essay":
        lead = cuts.transition_for(project.style) / 2 + cuts.head_pad_for(project, groups[-1][0][0])
        plan = _essay_phrases(project, member, dur, lead_in=lead, last_line=True)
        needed = (plan[-1]['t0'] + frame.last_line_min_s + .05
                  if project.style.captions_engine == 'pillow' and plan else
                  plan[-1]['t1'] + .05 if plan else 0)
    elif project.style.format == "kenburns" and member.title:
        needed = frame.arrive_s + max(frame.last_line_min_s,
                                     _title_hold(frame, member.title, dur)) + frame.arrive_s * frame.exit_ratio
    else:
        needed = 0
    return max(TAIL_PAD, needed - dur)


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


def _segment_graph(
    project: Project, group: list[tuple[Slide, float]], seg_len: float,
    op: str, channel=None, chapter: tuple[str, str] | None = None,
    size: tuple[int, int] = (WIDTH, HEIGHT), fps: int = FPS,
    dip_out: bool = False, camera_index: int = 0, last_line: bool = False,
    hide: frozenset = frozenset(), *, prepare_only: bool = False,
) -> tuple[list[str], str, str]:
    """Return input args, filtergraph and output label for a photographic segment.

    Retains title PNG drawing and stage clip generation as side effects;
    photographic formats never run ffmpeg here.
    """
    style = project.style
    frame = project.frame
    w, h = size
    essay = style.format == "essay" and not group[0][0].on_camera
    camera_captions = style.format == "essay" and group[0][0].on_camera
    slide = group[0][0]
    # Segment proxies use preview_size(); full output uses (WIDTH, HEIGHT).
    src, kind, focal = _chosen(project, slide, preview=size != (WIDTH, HEIGHT))
    source_slide = _picture_source(project, slide)
    candidate = next((c for c in source_slide.candidates if c['id'] == source_slide.chosen_id), {})
    span = ((candidate['in_s'], candidate['out_s'])
            if src and candidate.get('provider') == 'footage' else None)
    dip_in = False
    if not slide.on_camera and style.format == "stage" and shots_mod.is_3d(slide):
        # The shot, drawn by the stage at exactly this segment's length and
        # frame size; a paragraph with no solved shot gets the slate.
        clip = shots_mod.ensure_clips(project, [(slide, seg_len)], size, fps).get(slide.id)
        src, kind, focal = (clip if clip and clip.exists() else None), "video", []
        dip_in = ((slide.shot or {}).get("intent") or {}).get("join") == "dip"
    frames = max(2, int(round(seg_len * fps)))
    grade = GRADES.get(style.grade, GRADES["warm"])
    vig = _vignette(style.vignette)
    # The type cards are drawn once at 1080p and cached for the real render;
    # a smaller frame scales them on the way in rather than drawing a second set.
    card_fit = "" if (w, h) == (WIDTH, HEIGHT) else f",scale={w}:{h}"

    inputs: list[str] = []
    chain: list[str] = []
    pre_graph = ""            # set by sources that need more than one input

    if slide.on_camera:
        inputs, camera_chain = _camera_source(project, slide, seg_len, size, fps)
        chain.append(camera_chain)
        grade = vig = ""  # The shared camera look already includes these.
    elif src is None:
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
            clip_inputs, clip_graph = _clip_source(src, seg_len, crop, span)
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
        clip_inputs, pre_graph = _clip_source(src, seg_len, crop, span)
        inputs += clip_inputs
    elif style.ken_burns:
        inputs += ["-loop", "1", "-i", str(src)]
        # Oversample to 2x output before the zoom so the pan stays subpixel-smooth.
        crop, focal_px = _cover_crop(src, w * 2, h * 2, focal)
        chain.append(crop)
        chain.append(_kenburns(op, frames,
                               _camera_amount(project, op, camera_index), focal_px, size, fps,
                               ease="expo_out" if op in {"punch", "reveal"} else "linear",
                               origin=frame.camera_origin, move_max_s=frame.move_max_s))
    else:
        # A still with the drift switched off: staged once, then held.
        inputs += _still_input(src, fps)
        crop, _focal_px = _cover_crop(src, w * 2, h * 2, focal)
        chain.append(crop)
        chain.append(f"scale={w}:{h}")
        chain.append(HOLD_STILL)

    # A dip through black: the shot before fades out, this one fades up.
    dips = [f"fade=t=in:st=0:d={DIP:.2f}" if dip_in else "",
            f"fade=t=out:st={max(0.0, seg_len - DIP):.3f}:d={DIP:.2f}" if dip_out else ""]
    tail = [c for c in (grade, vig, *dips, "format=yuv420p") if c]
    if pre_graph:
        # The source built [base] itself (a looped clip); grade what came out.
        graph = f"{pre_graph};[base]{','.join(tail)}[graded]"
        base_label = "[graded]"
    else:
        graph = f"[0:v]{','.join(c for c in chain + tail if c)}[base]"
        base_label = "[base]"
    n_inputs = inputs.count("-i")      # sources may take several inputs each
    last = base_label

    if slide.on_camera:
        from .camera_overlays import compose
        inputs, graph, last = compose(project, slide, inputs, graph, last, size, fps,
                                      prepare_only=prepare_only)
        n_inputs = inputs.count('-i')

    if 'graphics' not in hide and not slide.on_camera and any(s.overlays for s, _ in group):
        from .block_overlays import compose
        inputs, graph, last = compose(project, group, inputs, graph, last, size, fps,
                                      channel, prepare_only=prepare_only)
        n_inputs = inputs.count('-i')

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
    if (essay or camera_captions) and style.captions_engine != 'pillow' and 'titles' not in hide:
        plan, offset = [], 0.0
        lead = cuts.transition_for(style) / 2 + cuts.head_pad_for(project, group[0][0])
        for n, (member, dur) in enumerate(group):
            for phrase in _essay_phrases(project, member, dur, lead_in=lead,
                    last_line=last_line and n == len(group) - 1):
                start, end = offset + phrase['t0'], min(seg_len - .05, offset + phrase['t1'])
                if end > start + .25:
                    plan.append(dict(text=phrase['text'], t0=start, t1=end))
            offset += dur
        if plan:
            ctx = scenes.context_base(project, channel)
            ctx.update(phrases=plan, duration=seg_len)
            clip = scenes.caption_plates(project, ctx, size=size, fps=fps,
                                         render=not prepare_only)
            inputs += ['-i', str(clip)]
            graph += (f';{last}[{n_inputs}:v]overlay=0:0:'
                      'eof_action=pass:repeatlast=0:format=auto[vcaptions]')
            n_inputs += 1
            last = '[vcaptions]'

    offset = 0.0
    for n, (member, dur) in enumerate(group):
        if "titles" in hide or ((essay or camera_captions) and style.captions_engine != "pillow"):
            offset += dur
            continue
        if essay:
            chunks = titles.essay_chunks(member.narration)
            # Across the spoken part only. `dur` carries the pause that follows
            # the paragraph, and a caption still on screen through a chapter
            # break reads as one that has been left up by mistake.
            spoken = take_duration(member.take) or dur * 0.85
            shares = _caption_timings(chunks, min(dur, spoken), frame)
            if last_line and n == len(group) - 1 and shares:
                shares[-1] = max(shares[-1], frame.last_line_min_s)
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
            title_size = round(HEIGHT * (frame.title_height_pct_min
                                          + frame.title_height_pct_max) / 200 / 0.72)
            card = project_dir(project.id) / "titles" / f"{member.id}_{title_size}.png"
            titles.render_title(member.title, kicker=member.beat or "",
                                accent=style.accent, out_path=card, size=title_size)
            idx = n_inputs
            inputs += _still_input(card, fps)
            n_inputs += 1
            start, fade_out_at, _ = _title_window(
                project, member, dur, cuts.transition_for(style) / 2
                + cuts.head_pad_for(project, group[0][0]), offset, seg_len,
                last_line and n == len(group) - 1)
            if fade_out_at > start:
                graph += (
                    f";[{idx}:v]format=rgba{card_fit},{HOLD_STILL},"
                    f"fade=t=in:st={start:.3f}:d={frame.arrive_s:.3f}:alpha=1,"
                    f"fade=t=out:st={fade_out_at:.3f}:d={frame.arrive_s * frame.exit_ratio:.3f}:alpha=1[ttl{n}]"
                    f";{last}[ttl{n}]overlay=0:0:format=auto[v{n}]"
                )
                last = f"[v{n}]"
        offset += dur

    # The chapter card for the section that starts next. It lands in the long
    # silence `audio.GAP_CHAPTER` opens at the end of this segment, so the
    # video pauses on the title and then the new section begins. Every format
    # that composes its picture here can carry one; the board and designed-
    # slide cuts draw their own frames and never reach this far.
    if chapter and "chapters" not in hide:
        title, kicker = chapter
        card = (project_dir(project.id) / "titles"
                / f"chapter_{_SAFE_NAME.sub('_', title)[:40]}.png")
        titles.render_chapter(title, kicker=kicker, accent=style.accent,
                              out_path=card)
        # Timed off the actual silence rather than a share of the segment, so
        # the card comes up as the voice stops instead of over its last words.
        gap = audio_mod.gap_map(project).get(group[-1][0].id, PARAGRAPH_GAP)
        hold = max(frame.arrive_s, min(gap, frame.arrive_s + frame.title_hold_base_s
                                      + frame.title_hold_per_word_s * len(title.split())))
        override = _chapter_override(project, group)
        if override is not None:
            hold = min(gap, max(0.0, override))
        start = max(0.2, seg_len - hold)
        inputs += _still_input(card, fps)
        graph += (
            f";[{n_inputs}:v]format=rgba{card_fit},{HOLD_STILL},"
            f"fade=t=in:st={start:.3f}:d={frame.arrive_s:.3f}:alpha=1[chap]"
            f";{last}[chap]overlay=0:0:format=auto[vchap]"
        )
        n_inputs += 1
        last = "[vchap]"

    return inputs, graph, last


def _overlay_tail(out: Path, card: Path, start: float, *, crf=18, threads=0):
    """Replace the picture tail with an opaque scene; preserve the source on failure."""
    temporary = out.with_name(out.stem + '.chapter' + out.suffix)
    try:
        ffutil.run([
            '-i', str(out), '-itsoffset', f'{start:.6f}', '-i', str(card),
            '-filter_complex',
            f"[0:v][1:v]overlay=enable='gte(t,{start:.6f})':eof_action=pass[v]",
            '-map', '[v]', *ffutil.video_args(temporary, crf=crf),
            '-pix_fmt', 'yuv420p', '-an', str(temporary)], threads=threads)
        os.replace(temporary, out)
    finally:
        temporary.unlink(missing_ok=True)


def _chapter_tail(project, out, chapter, seg_len, hold, size, fps, crf, threads, channel):
    if chapter and seg_len > hold + 0.2:
        ctx = scenes.context_base(project, channel)
        ctx['vars'].update(title=chapter[0], kicker=chapter[1])
        from . import scene_builder
        _, html, ctx = scenes._prepare(project, 'cards/chapter.html', ctx, hold, size, fps,
                                      ('chapter-builder-v1', scene_builder.MOTIONS, crf))
        card = html.with_suffix('.mp4')
        if not card.exists():
            scene_builder.render(project, 'cards/chapter.html', ctx, card,
                                 seconds=hold, size=size, fps=fps, crf=crf)
        _overlay_tail(out, card, seg_len - hold, crf=crf, threads=threads)
    return out


def _render_segment(
    project: Project, group: list[tuple[Slide, float]], seg_len: float,
    index: int, out: Path, channel=None, chapter: tuple[str, str] | None = None,
    threads: int = 0, size: tuple[int, int] = (WIDTH, HEIGHT),
    fps: int = FPS, crf: int = 18, preset: str = "veryfast",
    frames: tuple[int, int] | None = None, dip_out: bool = False,
    op: str = "set", camera_index: int = 0, last_line: bool = False,
    hide: frozenset = frozenset(),
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
    if "chapters" in hide:
        chapter = None
    style = project.style
    lead_in = (cuts.transition_for(style) / 2
               + cuts.head_pad_for(project, group[0][0]))
    hold = max(0.9, min(3.2, audio_mod.gap_map(project).get(
        group[-1][0].id, PARAGRAPH_GAP) - 0.12))
    override = _chapter_override(project, group)
    if override is not None:
        hold = min(audio_mod.gap_map(project)[group[-1][0].id], max(0.0, override))
    if group[0][0].on_camera:
        return _camera_segment(project, group, seg_len, out, size, fps,
                               channel=channel, chapter=chapter, threads=threads,
                               crf=crf, preset=preset, last_line=last_line, hide=hide)
    if ('graphics' not in hide and any(s.overlays for s, _ in group) and not cuts.is_cut(style.format)
            and ((group[0][0].cues or {}).get('blocks') or scenes.handles(style.format)
                 or style.format.startswith('custom:'))):
        from copy import deepcopy
        import tempfile
        from .block_overlays import compose, run_graph
        # These base renderers own their graphs. Reuse them, then composite graphics.
        base_group = [(deepcopy(s), d) for s, d in group]
        for member, _ in base_group:
            member.overlays = []
        with tempfile.TemporaryDirectory(dir=out.parent, prefix='overlay-base-') as work:
            base = Path(work) / 'base.mp4'
            _render_segment(project, base_group, seg_len, index, base, channel,
                None, threads, size, fps, crf, preset, dip_out=dip_out, op=op,
                camera_index=camera_index, last_line=last_line, hide=hide)
            inputs, graph, last = compose(project, group, ['-i', str(base)],
                '[0:v]null[base]', '[base]', size, fps, channel)
            script = Path(work) / 'graph.ffgraph'
            script.write_text(graph)
            run_graph([*inputs, '-filter_complex_script', str(script), '-map', last,
                '-t', f'{seg_len:.3f}', '-r', str(fps),
                *ffutil.video_args(out, crf=crf, preset=preset),
                '-pix_fmt', 'yuv420p', '-an', str(out)], threads=threads)
        return _chapter_tail(project, out, chapter, seg_len, hold, size,
                             fps, crf, threads, channel)
    if (group[0][0].cues or {}).get('blocks'):
        from . import blocks, scene_builder
        from copy import deepcopy
        slide = group[0][0]
        cue = slide.cues['blocks'][0]  # One background selection; overlays have a separate contract.
        block = deepcopy(blocks.discover().get(cue['block']))
        if block is None:
            raise ValueError(f"Block missing: {cue['block']}")
        block['meta']['duration'] = dict(mode='range', min=0)
        ctx = scenes.context_base(project, channel)
        ctx.update(narration=slide.narration, take=slide.take, research=project.research)
        template, ctx = blocks.prepare(cue['block'], cue['vars'],
            '9:16' if project.aspect == 'portrait' else '16:9', seg_len, context=ctx, _block=block)
        scene_builder.render(project_dir(project.id), template, ctx, out,
                             seconds=seg_len, size=size, fps=fps, crf=crf, frames=frames)
        return _chapter_tail(project, out, chapter, seg_len, hold, size,
                             fps, crf, threads, channel)
    if not cuts.is_cut(style.format) and scenes.handles(style.format):
        return scenes.render_segment(
            project, group, seg_len, out, size=size, fps=fps, crf=crf,
            chapter=chapter, lead_in=lead_in, hold=hold, channel=channel, hide=hide)
    if style.format.startswith("custom:"):
        rendered = _render_custom_style(project, group, seg_len, out, size,
                                        fps, crf)
        if rendered is not None:
            return _chapter_tail(project, rendered, chapter, seg_len, hold, size,
                                 fps, crf, threads, channel)
        # The style was deleted, or this paragraph has no filled spec yet:
        # fall through to the documentary cut rather than abort the render.
    if cuts.is_cut(style.format):
        # The drawn cuts join on a hard cut, so `seg_len` carries one frame
        # of overlap; the voice starts half of that in, plus the opening
        # silence on the video's first paragraph.
        return cuts.render_segment(
            project, group, seg_len, out, channel=channel,
            image_for=lambda s: _chosen(project, s)[0], size=size, fps=fps,
            crf=crf, lead_in=lead_in, cache_dir=project_dir(project.id) / "cuts",
            chapter=chapter, frames=frames,
            hold=hold, hide=hide)
    if style.format == "board":
        from . import board as board_mod
        board_mod.render_segment(
            project, group, seg_len, out, channel=channel,
            cache=project_dir(project.id) / "board",
            image_for=lambda s: _chosen(project, s)[0],
            crf=crf, extra=_reframe(size, fps))
        return _chapter_tail(project, out, chapter, seg_len, hold, size,
                             fps, crf, threads, channel)
    from . import stage
    scene_chapter = bool(chapter and style.chapter_engine == "scene" and stage.browser())
    inputs, graph, last = _segment_graph(
        project, group, seg_len, op, channel, None if scene_chapter else chapter, size, fps, dip_out,
        camera_index, last_line, hide)

    args = [*inputs, "-filter_complex", graph, "-map", last,
            "-t", f"{seg_len:.3f}", "-r", str(fps),
            *ffutil.video_args(out, crf=crf, preset=preset),
            "-pix_fmt", "yuv420p", "-an", str(out)]
    if any(s.overlays for s, _ in group):
        import tempfile
        with tempfile.TemporaryDirectory(dir=out.parent, prefix='overlay-graph-') as work:
            script = Path(work) / 'graph.ffgraph'
            script.write_text(graph)
            i = args.index('-filter_complex')
            args[i:i+2] = ['-filter_complex_script', str(script)]
            from .block_overlays import run_graph
            run_graph(args, threads=threads)
    else:
        ffutil.run(args, threads=threads)
    if scene_chapter:
        return _chapter_tail(project, out, chapter, seg_len, hold, size,
                             fps, crf, threads, channel)
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
    from .schema import Channel, FrameSpec, IntroSpec, OutroSpec, Style

    if project.channel_id:
        channel = channels.load_or_none(project.channel_id)
        if channel:
            inherited_blocks = channel.style.block_theme
            channel.style = Style(**project.style.to_dict())
            channel.style.block_theme = inherited_blocks
            channel.frame = FrameSpec.from_dict(project.frame.to_dict())
        if channel and project.format_look:
            channel.intro = IntroSpec(**project.format_look['intro'])
            channel.outro = OutroSpec(**project.format_look['outro'])
            inherited_blocks = channel.style.block_theme
            channel.style = Style(**project.style.to_dict())
            channel.style.block_theme = inherited_blocks
        if channel:
            from .learning import choose, effective_frame
            from . import themes
            key = choose('theme', [channel.style.theme, *themes.theme_keys()], effective_frame(project))
            if key != channel.style.theme:
                themes.apply_to_style(channel.style, key, False)
        return channel
    # Copies, not the project's own specs: the renderers are free to settle a
    # template or a length on the channel they are handed, and none of that
    # should turn into a change to the video that gets saved.
    return Channel(
        id="", name=project.title or "Untitled", tagline=project.subtitle,
        style=Style(**project.style.to_dict()),
        frame=FrameSpec.from_dict(project.frame.to_dict()),
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
    return bool(channel and len(channel.intro.images or []) >=
                intro_mod.minimum_images(channel.intro.template))


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
        elif len(channel.intro.images or []) < intro_mod.minimum_images(channel.intro.template):
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
def _camera_look(style, focal, size, src, fps, *, take=None, target=110.0, punch=1.0) -> str:
    """Correct paragraph takes gently; retain the legacy presenter look."""
    scaled = tuple(round(v * punch / 2) * 2 for v in size) if punch != 1 else size
    crop, point = _cover_crop(src, *scaled, focal)
    if scaled != size:
        point = point or [v / 2 for v in scaled]
        x, y = [min(big - small, max(0, at - small / 2))
                for big, small, at in zip(scaled, size, point)]
        crop += f',crop={size[0]}:{size[1]}:{x:.3f}:{y:.3f}'
    chain = [crop, f"fps={fps}"]
    if take is not None:
        from .camera import correction_filter
        chain.append(correction_filter(take, target))
        grades = {
            "warm": "colorbalance=rs=0.0175:bs=-0.0225,eq=saturation=0.975:contrast=1.025:gamma=0.995",
            "neutral": "eq=contrast=1.015:saturation=0.99",
            "cool": "colorbalance=rs=-0.015:bs=0.025,eq=saturation=0.98:contrast=1.02",
            "mono": "hue=s=0.5,eq=contrast=1.05:gamma=1.01",
        }
        if take.get("look", "auto") != "as_shot":
            chain.append(grades.get(style.grade, ""))
    elif style.grade in GRADES:
        chain.append(GRADES[style.grade])
    vig = _vignette(style.vignette * 0.6)
    if vig and (take is None or take.get("look", "auto") != "as_shot"):
        chain.append(vig)
    chain.append("format=yuv420p")
    return ','.join(x for x in chain if x)


def _camera_source(project, slide, seg_len, size, fps):
    """Align picture speech to the voice's lead-in, then keep real tail frames."""
    from .camera import target
    take = project.active_take(slide) or {}
    root = project_dir(project.id)
    video = root / take.get("video", "")
    if not take.get("video") or not video.is_file():
        raise ValueError(f"Camera picture missing for paragraph {slide.id}")
    lead = cuts.transition_for(project.style) / 2 + cuts.head_pad_for(project, slide)
    raw = root / take.get("raw_path", "")
    start, pre, pad = 0.0, 0.0, lead
    src = video
    if take.get("raw_path") and raw.is_file():
        src = raw
        speech = float(take.get("video_start", (take.get("trimmed") or [0])[0]
                                + float(take.get("av_offset", 0))))
        start = max(0.0, speech - lead)
        pre = speech - start
        pad = max(0.0, lead - pre)
    if take.get("cuts") or (take.get('punch', True) and any(o.get('kind') == 'cutaway' for o in take.get('overlays', []))):
        return ["-i", str(src)], _camera_cut_source(
            project, take, src, start + pre, lead, seg_len, size, fps)
    length = pre + float(take["duration"]) + float(take.get("tail", 0))
    chain = (f"setpts=PTS-STARTPTS,trim=start={start:.6f}:duration={length:.6f},"
             f"setpts=PTS-STARTPTS,"
             f"tpad=start_mode=clone:start_duration={pad:.6f}:"
             f"stop_mode=clone:stop_duration={seg_len:.6f},"
             + _camera_look(project.style, take.get("focal"), size, src, fps,
                            take=take, target=target(project)))
    return ["-i", str(src)], chain


def _camera_cut_source(project, take, src, speech, lead, seg_len, size, fps):
    from .camera import target
    ranges, offset, pieces = kept_ranges(take), 0., []
    # A return from a cutaway is another camera edit, even without a pause cut.
    from .camera_overlays import validate
    returns = [o['at'] + o['dur'] for o in validate(take, take.get('overlays', [])) if o['kind'] == 'cutaway']
    for a, b in ranges:
        points = [a, *sorted(a + t - offset for t in returns if offset < t < offset + b - a), b]
        pieces.extend(zip(points, points[1:]))
        offset += b - a
    ranges = pieces
    n = len(ranges)
    graph = ['setpts=PTS-STARTPTS,split=' + str(n)
             + ''.join(f'[ks{j}]' for j in range(n))]
    punch = (project.frame.punch_min + project.frame.punch_max) / 2
    elapsed, frames, labels = lead, 0, []
    for j, (a, b) in enumerate(ranges):
        # Pre-roll follows the first surviving word, tail follows the last.
        start = max(0, speech + a - (lead if j == 0 and a == 0 else 0))
        end = speech + b + (float(take.get('tail', 0)) if j == n - 1 and b == take['duration'] else 0)
        pad = max(0, lead - (speech + a - start)) if j == 0 else 0
        elapsed += b - a + (end - speech - b)
        count = round(elapsed * fps) - frames
        frames += count
        if count <= 0:
            graph.append(f'[ks{j}]nullsink')
            continue
        labels.append(f'[kp{j}]')
        graph.append(f'[ks{j}]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,'
                     f'tpad=start_mode=clone:start_duration={pad:.6f},'
                     + _camera_look(project.style, take.get('focal'), size, src, fps,
                                    take=take, target=target(project),
                                    punch=punch if j % 2 and take.get('punch', True) else 1).replace(f'fps={fps},', '')
                     + f',tpad=stop_mode=clone:stop_duration={seg_len},fps={fps},'
                     f'trim=end_frame={count},settb=AVTB,setpts=N/({fps}*TB)[kp{j}]')
    graph.append(''.join(labels) + f'concat=n={len(labels)}:v=1:a=0,'
                 f'tpad=stop_mode=clone:stop_duration={seg_len:.6f}')
    return ';'.join(graph)


def camera_thumbnail(project, slide) -> Path:
    """Cache one frame of the trimmed camera video, independent of proxies."""
    import hashlib
    take = project.active_take(slide) or {}
    src = project_dir(project.id) / take.get("video", "")
    if not take.get("video") or not src.is_file():
        raise ValueError("Camera picture missing")
    key = hashlib.sha1(str((src, _stat(src))).encode()).hexdigest()[:16]
    out = project_dir(project.id) / "cache" / f"camera_{slide.id}_{key}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        ffutil.run(["-i", str(src), "-frames:v", "1", "-vf", "scale=240:-2",
                    "-an", str(out)])
    return out


def _camera_segment(project, group, seg_len, out, size, fps, *, channel=None,
                    chapter=None, threads=0, crf=18, preset="veryfast",
                    last_line=False, hide=frozenset()):
    # Camera footage uses photographic titles/cards in every format. This graph
    # only draws static cards once; the moving picture stays entirely in ffmpeg.
    inputs, graph, last = _segment_graph(project, group, seg_len, "set", channel,
                                        chapter, size, fps, last_line=last_line, hide=hide)
    import tempfile
    with tempfile.TemporaryDirectory(prefix='camera-graph-', dir=out.parent) as work:
        script = Path(work) / 'graph.txt'
        script.write_text(graph)
        args = [*inputs, "-filter_complex_threads", str(threads or 2),
                "-filter_complex_script", str(script), "-map", last,
                "-t", f"{seg_len:.3f}", "-r", str(fps),
                *ffutil.video_args(out, crf=crf, preset=preset),
                "-pix_fmt", "yuv420p", "-an", str(out)]
        try:
            ffutil.run(args, threads=threads)
        except ffutil.FFError as exc:
            if "Unrecognized option 'filter_complex_script'" not in str(exc):
                raise
            args[args.index('-filter_complex_script')] = '-/filter_complex'
            ffutil.run(args, threads=threads)
    return out


def _render_presenter(project: Project, seg_len: float, out: Path) -> Path:
    """Cut the camera clip to length and put it in the video's house style."""
    pres = project.presenter
    src = project_dir(project.id) / pres.path
    style = project.style
    chain = _camera_look(style, pres.focal or None, (WIDTH, HEIGHT), src, FPS)

    ffutil.run([
        "-ss", f"{max(0.0, pres.trim_start):.3f}", "-i", str(src),
        "-t", f"{seg_len:.3f}",
        "-filter_complex", f"[0:v]{chain}[v]", "-map", "[v]",
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
        from . import packs
        chosen = packs.resolve(project.music, 'music') if '/' in project.music else MUSIC_DIR / project.music
        if isinstance(chosen, Path) and chosen.is_file():
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
                 music_fade: float = 5.0, sponsor_audio=(), sponsor_windows=()) -> str:
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

    if sponsor_audio:
        branches = []
        for k, (idx, offset, length) in enumerate(sponsor_audio):
            delay = round(offset * 1000)
            branches.append(f"[{idx}:a]{fmt},atrim=duration={length:.3f},asetpts=N/SR/TB,"
                            f"adelay={delay}|{delay}[sponsor{k}];")
        voice += "".join(branches) + voice_src + "".join(
            f"[sponsor{k}]" for k in range(len(sponsor_audio))) + (
            f"amix=inputs={1 + len(sponsor_audio)}:duration=longest:normalize=0[sponsorvoice];")
        voice_src = "[sponsorvoice]"

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
                    f"[mix]loudnorm=I={project.frame.voice_lufs:.1f}:TP=-1.0:LRA=11[aout]")
        return voice + f"{voice_src}loudnorm=I={project.frame.voice_lufs:.1f}:TP=-1.0:LRA=11[aout]"

    mus = f"[{n_video + 1 + (1 if presenter else 0) + len(stings) + len(sponsor_audio)}:a]"
    fade = max(0.5, min(18.0, music_fade))
    fade_out_at = max(0.5, total - fade)

    # When the slate has a sting of its own, the bed holds off until the slate is
    # over. `afade` with a start time silences everything before it, so this needs
    # no adelay: the bed simply fades up as the sting rings out.
    bed_in_at = 0.0
    opening = next((s for s in stings if s[4] == "intro"), None)
    if opening:
        bed_in_at = max(0.0, opening[1] + opening[2] - 0.35)

    sponsor_duck = "".join(
        f"volume={project.style.sponsor_music_db:.1f}dB:enable='between(t,{start:.3f},{start + length:.3f})',"
        for start, length in sponsor_windows)

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
        + sponsor_duck +
        f"afade=t=in:st={bed_in_at:.3f}:d=3,"
        f"afade=t=out:st={fade_out_at:.3f}:d={fade:.3f}[bed];"
        # The bed sits at a fixed level under the voice. It used to be
        # sidechain-compressed against the narration; that pumped audibly and
        # was taken out, so `music_db` alone sets how far under it sits.
        + f"{voice_src}[bed]{sting_tags}amix=inputs={2 + len(stings)}:"
          f"duration=longest:normalize=0[mix];"
        + f"[mix]loudnorm=I={project.frame.voice_lufs:.1f}:TP=-1.0:LRA=11[aout]"
    )


def _master_audio_graph(project: Project, inputs: list[str], graph: str,
                        total: float, n_video: int, progress: Progress) -> str:
    """Measure only the sound, then preserve its dynamics with a linear master.

    `_audio_graph` ends with the master loudnorm; earlier loudnorms belong to
    the voice/bed/sting buses and stay untouched, including on fallback.
    """
    before, _ = graph.rsplit("loudnorm=", 1)
    target = project.frame.voice_lufs
    # Segment inputs are plain -i/path pairs. All subsequent inputs are audio
    # sources, including a camera file whose video must never be decoded here.
    audio_inputs = []
    for arg in inputs[2 * n_video:]:
        if arg == "-i":
            audio_inputs.append("-vn")
        audio_inputs.append(arg)
    measure_graph = re.sub(r"\[(\d+):a\]",
                           lambda m: f"[{int(m[1]) - n_video}:a]", before)
    measure_graph += f"loudnorm=I={target:.1f}:TP=-1.0:LRA=20:print_format=json[aout]"
    progress("Measuring the audio for linear master normalization")
    started = time.monotonic()
    try:
        _, log = ffutil.capture([
            *audio_inputs, "-filter_complex_threads", "2",
            "-filter_complex", measure_graph, "-map", "[aout]",
            "-t", f"{total:.3f}", "-f", "null", "-"], timeout=900)
        measured = audio_mod._parse_loudnorm(log)
        if measured is None:
            raise ValueError("silent audio or invalid loudnorm report")
        i, tp, lra, thresh, offset = (float(measured[k]) for k in
                                     ("input_i", "input_tp", "input_lra",
                                      "input_thresh", "target_offset"))
        # ffmpeg falls back to dynamic if either of these bounds is exceeded.
        # 20 LU accommodates normal mixes; expand for unusual material rather
        # than compressing it. Keep a little headroom for report rounding.
        master_lra = max(20, math.ceil(lra + 0.1))
        safe_target = min(target, -1.0 - tp + i - max(0.0, offset) - 0.1)
        safe_target = round(safe_target, 3)
        if not (-70 <= i <= 0 and -99 <= tp <= 99 and 0 <= lra <= 50
                and -99 <= thresh <= 0 and -99 <= offset <= 99
                and master_lra <= 50 and -70 <= safe_target <= -5):
            raise ValueError("loudnorm measurement outside supported bounds")
    except (ffutil.FFError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        progress(f"Warning: master measurement failed ({exc}); using single-pass normalization")
        return graph
    if safe_target < target:
        progress(f"Master target reduced from {target:.1f} to {safe_target:.3f} LUFS "
                 "to keep linear normalization below -1 dBTP")
    progress(f"Master normalization: linear, target {safe_target:.3f} LUFS, "
             f"LRA {master_lra} (audio measurement {time.monotonic() - started:.2f}s)")
    return (before + f"loudnorm=I={safe_target:.3f}:TP=-1.0:LRA={master_lra}:"
            f"measured_I={i}:measured_TP={tp}:measured_LRA={lra}:"
            f"measured_thresh={thresh}:offset={offset}:linear=true:print_format=summary[aout]")


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
SEGMENT_VERSION = 1


def _block_versions(slide):
    from . import block_library
    cues = (slide.cues or {}).get('blocks', [])
    refs = [cue['block'] for cue in cues] + [o['block_id'] for o in slide.overlays]
    library = block_library.registry()
    missing = [ref for ref in refs if ref not in library]
    if missing:
        raise ValueError(f'Block missing: {missing[0]}')
    return [block_library.signature(library[ref]) for ref in refs]


def _segment_key(project, group, settings) -> str:
    """Exact inputs of a finished picture segment, excluding unused candidates."""
    import dataclasses
    import hashlib
    import json
    from .block_theme import cache_owner

    root = project_dir(project.id)
    rows = []
    for slide, duration in group:
        row = dataclasses.asdict(slide)
        if (slide.cues or {}).get('blocks') or slide.overlays:
            row['block_versions'] = _block_versions(slide)
            from .block_theme import values
            row['block_theme'] = values(project, settings.get('channel'))
        overlay_ids = {o.get('source', {}).get('candidate_id') for o in (project.active_take(slide) or {}).get('overlays', [])} if slide.on_camera else set()
        row["candidates"] = [c for c in slide.candidates if c["id"] == slide.chosen_id or c['id'] in overlay_ids]
        if overlay_ids:
            row['overlay_files'] = [_stat(root / c['local_path']) for c in row['candidates'] if c.get('local_path')]
        take = slide.take or {}
        files = []
        for field in (("path", "video", "raw_path") if slide.on_camera else ("path", "video")):
            path = root / take[field] if take.get(field) else None
            digest = None
            if path and path.is_file():
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha1").hexdigest()
            files.append([str(path), _stat(path), digest])
        picture = _chosen(project, slide)[0]
        rows.append([row, duration, files, str(picture), _stat(picture)])
    source = _picture_source(project, group[0][0])
    picture = _chosen(project, group[0][0])[0]
    channel = settings.get("channel")
    graph = None
    if not ((group[0][0].cues or {}).get('blocks') or scenes.handles(project.style.format) or cuts.is_cut(project.style.format)
            or project.style.format == "board" or project.style.format.startswith("custom:")):
        graph = _segment_graph(project, group, settings["seg_len"], prepare_only=True,
                               **{k: settings[k] for k in (
                                   "op", "channel", "chapter", "size", "fps", "dip_out",
                                   "camera_index", "last_line")})
    from .camera import target
    if group[0][0].on_camera:
        rows[0].append(target(project))
    spec = [SEGMENT_VERSION, scenes.SCENE_VERSION, project.title, project.subtitle,
            rows, str(picture), _stat(picture),
            [c for c in source.candidates if c["id"] == source.chosen_id],
            cache_owner(project.style), project.frame.to_dict(),
            cache_owner(channel),
            {k: v for k, v in settings.items() if k != "channel"}, graph,
            ffutil.video_args("segment.mp4", crf=settings["crf"], preset=settings["preset"]),
            ffutil.h264("segment.mp4", crf=settings["crf"], preset=settings["preset"])]
    return hashlib.sha1(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


def _segment_ready(path):
    return path.is_file() and path.stat().st_size > 0


def _publish_segment(temp, out):
    if not _segment_ready(temp):
        raise ValueError(f"Empty segment: {temp.name}")
    os.replace(temp, out)


def _sweep_segments(directory, keep):
    # Only render scratch lives here; never touch takes or source media.
    for path in directory.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()


def render(project: Project, progress: Progress = lambda m: None,
           preview: bool = False) -> dict:
    """Render a cut, retaining completed picture segments after any failure."""
    try:
        return _render(project, progress, preview)
    except Exception:
        directory = project_dir(project.id) / "segments"
        kept = sum(_segment_ready(p) for p in directory.glob("*.mp4")
                   if re.fullmatch(r"[0-9a-f]{40}\.mp4", p.name))
        progress(f"resumable: {kept} segments kept")
        raise


def _render(project: Project, progress: Progress, preview: bool) -> dict:
    """Full render. `preview` uses estimated timings when nothing is recorded."""
    from .learning import resolve_choices
    resolve_choices(project)
    _memory_check(progress)

    root = project_dir(project.id)
    seg_dir = root / "segments"
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

    if not preview:
        for slots in _sponsor_placements(project, plan).values():
            for slot in slots:
                if not (slot.take or {}).get("path"):
                    raise ValueError(f"Sponsor {slot.id} has no recorded take")

    # Only the lead of each picture group ever reaches the screen — the rest of
    # the group holds that same picture rather than fetching its own. Handing
    # download_chosen anything wider fetches images the cut never shows and is
    # what was getting renders rate-limited.
    lead_slides = list({s.id: s for group in groups
                        for s in [_picture_source(project, group[0][0])] if not s.on_camera}.values())
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
    durations[-1] += _tail_pad(project, groups)

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

    # A 3D explainer's shots are drawn first, in one browser run, so each
    # scene's models load once; the segments then cut them in like clips.
    if project.style.format == "stage":
        _stage_clips(project, groups, [seg_lens[i + slide_at] for i in range(len(groups))],
                     (WIDTH, HEIGHT), FPS, progress, preview)

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
    # Keep the conservative essay budget while Pillow remains available.
    # T5.1 scene RSS must be re-measured with T0.8 before reducing it.
    per = SEGMENT_RSS_MB.get(project.style.format, SEGMENT_RSS_MB["default"])
    free_mb = sysinfo.available_mb()
    if free_mb is not None:
        workers = max(1, min(workers, int(free_mb // per)))
    if not cuts.is_cut(project.style.format):
        memory = f"{free_mb:.0f} MB free" if free_mb is not None else "free memory unknown"
        progress(f"{workers} segments at a time ({memory}, {per} MB each)")
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

    ops = camera_plan(project, groups)

    settings = []
    paths = []
    for i, group in enumerate(groups):
        chapter = (chapter_card(project, groups[i + 1][0][0])
                   if i + 1 < len(groups) else None)
        opts = dict(seg_len=seg_lens[i + slide_at], channel=seg_channel,
                    chapter=chapter, threads=seg_threads, size=(WIDTH, HEIGHT), fps=FPS,
                    crf=18, preset="veryfast", dip_out=_dips_into(groups, i + 1),
                    op=ops[i], camera_index=i, last_line=i == len(groups) - 1,
                    index=i + slide_at,
                    **({"chunk_seconds": CHUNK_SECONDS} if cuts.is_cut(project.style.format) else {}))
        settings.append(opts)
        paths.append(seg_dir / f"{_segment_key(project, group, opts)}.mp4")
    missing = [i for i, path in enumerate(paths) if not _segment_ready(path)]
    progress(f"reused {len(groups) - len(missing)} of {len(groups)} segments")

    def work(i: int) -> tuple[int, Path]:
        out = paths[i]
        temp = out.with_suffix(".partial.mp4")
        opts = dict(settings[i])
        seg_len, index = opts.pop("seg_len"), opts.pop("index")
        encoder = ffutil.h264("segment.mp4", crf=opts["crf"], preset=opts["preset"])
        _render_segment(project, groups[i], seg_len, index, temp, **opts)
        if encoder != ffutil.h264("segment.mp4", crf=opts["crf"], preset=opts["preset"]):
            out = paths[i] = out.with_suffix(".uncached.mp4")
        _publish_segment(temp, out)
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
                                   seg_channel, free_mb, progress, targets=paths)
    else:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            for i, path in pool.map(work, missing):
                done += 1
                if done % 3 == 0 or done == len(missing):
                    progress(f"  segments {len(groups) - len(missing) + done}/{len(groups)}")
            seg_paths = paths

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

    from . import sponsors
    placed = _sponsor_placements(project, plan)
    base_paths, base_durations, base_lens = seg_paths, durations, seg_lens
    seg_paths, durations, seg_lens = [], [], []
    group_indices, sponsor_indices, sponsor_entries, old_to_new = {}, set(), [], {}
    group_at = {slide_at + i: i for i in range(len(groups))}
    for old, (path, dur, length) in enumerate(zip(base_paths, base_durations, base_lens)):
        old_to_new[old] = len(seg_paths)
        seg_paths.append(path)
        durations.append(dur)
        seg_lens.append(length)
        if old not in group_at:
            continue
        gi = group_at[old]
        group_indices[len(seg_paths) - 1] = gi
        for slot in placed.get(groups[gi][-1][0].id, []):
            seconds = sponsors.duration(slot)
            start = sum(durations)
            ctx = scenes.context_base(project, seg_channel)
            ctx.update(slot.vars)
            ctx["vars"] = {**ctx["vars"], **slot.vars}
            ctx.update(script=slot.script, variant=slot.variant, take=slot.take, word_offset=T / 2)
            clip = scenes.ensure_clip(project, slot.template, ctx,
                                      seconds=seconds + T, size=(WIDTH, HEIGHT), fps=FPS)
            sponsor_indices.add(len(seg_paths))
            sponsor_entries.append((slot, start))
            seg_paths.append(clip)
            durations.append(seconds)
            seg_lens.append(seconds + T)
    total = sum(durations) + T
    if pres_src:
        pres_offset = sum(durations[:old_to_new[pres_index]])

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

    sponsor_audio, next_idx = _sponsor_audio(project, sponsor_entries, inputs, next_idx, T / 2)
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
    from .learning import effective_frame
    video_graph = _join_graph(seg_lens, T, groups, effective_frame(project), slide_at,
                              group_indices=group_indices, sponsor_indices=sponsor_indices)

    # An end screen is long enough that where the bed gives out is a decision,
    # so the card carries the fade length; without one the default stands.
    music_fade = 5.0
    if outro_path:
        card = _slate_channel(project)
        if card:
            music_fade = float(card.outro.music_fade)

    audio_graph = _audio_graph(project, len(seg_paths), total,
                               bool(music), presenter_audio, sting_audio,
                               music_fade, sponsor_audio,
                               [(start + T / 2, sponsors.duration(slot))
                                for slot, start in sponsor_entries])
    graph = video_graph + ";" + _master_audio_graph(
        project, inputs, audio_graph, total, len(seg_paths), progress)

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

    _sweep_segments(seg_dir, {path.name for path in paths
                              if re.fullmatch(r"[0-9a-f]{40}\.mp4", path.name)})

    result = {
        "output": f"out/{out_path.name}",
        "duration": round(ffutil.duration(out_path), 2),
        "size_mb": round(out_path.stat().st_size / 1e6, 1),
        "slides": len(plan),
        "pictures": len(groups),
        "preview": preview,
        "music": music.name if music else "",
    }
    result["verify"] = _verify_output(out_path, project, groups, durations,
                                      group_indices, T, progress)
    if not preview:
        project.status = "rendered"
    from .stages import render_signature
    result['stage_signature'] = render_signature(project)
    project.render = result
    progress(f"Done: {result['output']} — {result['duration'] / 60:.1f} min, "
             f"{result['size_mb']} MB")
    return result


def _verify_output(path, project, groups, durations, group_indices, T, progress):
    """Use the mux's actual layout, including skipped takes and inserted clips."""
    import json
    from . import verify

    report_path = project_dir(project.id) / "render" / "verify.json"
    try:
        segments, start = [], 0.0
        for index, duration in enumerate(durations):
            paragraphs = []
            if index in group_indices:
                gi = group_indices[index]
                pt = start + T / 2 + (HEAD_PAD if gi == 0 else 0)
                for slide, seconds in groups[gi]:
                    paragraphs.append({"id": slide.id, "word_times": [
                        {**w, "start": pt + w["start"], "end": pt + w["end"]}
                        for w in take_words(slide.take)]})
                    pt += seconds
            # Joins switch pictures at the midpoint of their overlap.
            segments.append({"start": start + T / 2, "duration": duration,
                             "paragraphs": paragraphs})
            start += duration
        progress("Verifying the finished file")
        report = verify.run(path, {"segments": segments}, project.frame)
        summary = {"p0": report["counts"]["P0"], "p1": report["counts"]["P1"],
                   "path": "render/verify.json"}
    except Exception as exc:
        # Analysis failure must not discard a successfully encoded file.
        report = {"error": str(exc), "findings": []}
        summary = {"error": str(exc), "path": "render/verify.json"}
        progress(f"Verification unavailable: {exc}")
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    except OSError as exc:
        summary = {"error": f"Could not save verification: {exc}"}
        progress(summary["error"])
    return summary


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

    Nothing is rendered here; this only asks whether those segments exist.
    Camera selection uses picture-group indices independently of these cards.
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
PROXY_VERSION = 2


PREVIEW_LAYERS = frozenset({'titles', 'cues', 'chapters', 'music', 'stings', 'notes', 'graphics'})


def _hidden_suffix(hide):
    import hashlib
    return '_h' + hashlib.sha1(','.join(sorted(hide)).encode()).hexdigest()[:8] if hide else ''


def _layers(project, segs):
    """Render-free spans in picture time; reuse the renderer's timing plan."""
    layers = {key: [] for key in PREVIEW_LAYERS}
    layers['sponsors'] = []
    layers['graphics'] = []
    slides = {s.id: s for s in project.slides}
    total = sum(s['duration'] for s in segs)

    def add(row, ident, sid, a, b, text, kind, src='auto', **extra):
        a, b = max(0.0, a), min(total, b)
        if b > a:
            layers[row].append(dict(id=ident, sid=sid, t0=round(a, 3), t1=round(b, 3),
                                    text=text, kind=kind, src=src, **extra))

    previous = None
    last_picture = next((s for s in reversed(segs) if s['type'] == 'picture'), None)
    for seg in segs:
        if seg['type'] == 'sponsor':
            add('sponsors', seg['sponsor'], '', seg['start'], seg['start'] + seg['duration'],
                seg['script'], 'sponsor')
        if seg['type'] != 'picture':
            continue
        group = [(slides[q['id']], q['duration']) for q in seg['paragraphs']]
        cue_rows = {}
        if cuts.is_cut(project.style.format):
            lead = cuts.transition_for(project.style) / 2 + cuts.head_pad_for(project, group[0][0])
            cue_rows = {sid: cues for sid, cues, _ in cuts.timed_cues(
                project, group, seg['duration'] + cuts.transition_for(project.style), lead)}
        for q in seg['paragraphs']:
            slide, timing = slides[q['id']], q['timing']
            if slide.overlays and not slide.on_camera and not cuts.is_cut(project.style.format):
                from . import block_overlays, blocks
                library = blocks.discover()
                for item in block_overlays.resolved(slide.take, slide.overlays, q.get('duration')):
                    a = q['start'] + item['at']
                    add('graphics', item['id'], slide.id, a, a + item['dur'],
                        library[item['block_id']]['meta']['name'], 'overlay', item['src'])
            if (slide.title and timing['title_hold']['value'] > 0
                    and project.style.format != 'essay' and not cuts.is_cut(project.style.format)):
                a = timing['title_at']['start']
                add('titles', slide.id, slide.id, a,
                    a + timing['title_hold']['value'] + project.frame.arrive_s * project.frame.exit_ratio,
                    slide.title, 'title', 'user' if 'user' in
                    (timing['title_at']['src'], timing['title_hold']['src']) else 'auto')
            if project.style.format == 'essay':
                head = cuts.head_pad_for(project, group[0][0])
                plan = _essay_phrases(project, slide, q['duration'],
                    lead_in=head + seg['skip'],
                    last_line=seg is last_picture and q is seg['paragraphs'][-1])
                origin = q['start'] - head - seg['skip']
                for i, phrase in enumerate(plan):
                    a = origin + phrase['t0']
                    b = min(seg['start'] + seg['duration'] + seg['skip'] - .05, origin + phrase['t1'])
                    if b > a + .25:
                        add('titles', f'{slide.id}:cap{i}', slide.id, a, b, phrase['text'], 'title')
            for i, (cue, span) in enumerate(zip(cue_rows.get(slide.id, []), timing['cues'])):
                add('cues', f'{slide.id}:{i}', slide.id, span['start'], span['end'],
                    next((cue[k] for k in ('text', 'caption', 'headline', 'title') if cue.get(k)), ''),
                    'cue', span['src'], cue=i, cue_kind=cue.get('kind', ''))
            if chapter_title(project, slide) and previous:
                end = previous['start'] + previous['duration']
                add('chapters', slide.id, slide.id, end + previous['skip'] - timing['chapter_hold']['value'],
                    end, chapter_title(project, slide), 'chapter', timing['chapter_hold']['src'])
        previous = seg
    music = pick_music(project)
    stings = _stings_for(project, any(s['type'] == 'intro' for s in segs),
                         any(s['type'] == 'outro' for s in segs))
    if music:
        opening = next((s for s in segs if s['type'] == 'intro'), None)
        start = max(0, opening['duration'] - 0.35) if opening and 'intro' in stings else 0
        add('music', 'music', '', start, total, music.name, 'music')
    for role, (path, spec) in stings.items():
        seg = next(s for s in segs if s['type'] == role)
        from .intro import sting_window
        _, span, _ = sting_window(spec, seg['duration'])
        add('stings', role, '', seg['start'], seg['start'] + span, path.name, 'sting')
    return layers


def _stat(path: Path | None) -> list[int] | None:
    try:
        s = path.stat()      # type: ignore[union-attr]
    except (OSError, AttributeError):
        return None
    return [s.st_mtime_ns, s.st_size]


def _proxy_key(project: Project, groups: list[list[tuple[Slide, float]]],
               index: int, channel: Any, hide: frozenset = frozenset()) -> str:
    """Everything a proxy's pixels or sound depend on, as one short hash.

    The timeline plays cached proxies, so "is this one still right" has to be
    answerable without rendering it: if any word, picture, take file, cue,
    style knob or neighbouring chapter changed, the hash does too.
    """
    import dataclasses
    import hashlib
    import json
    from .block_theme import cache_owner

    root = project_dir(project.id)
    group = groups[index]
    lead = group[0][0]
    nxt = groups[index + 1][0][0] if index + 1 < len(groups) else None
    slides = []
    for s, d in group:
        row = dataclasses.asdict(s)
        if (s.cues or {}).get('blocks') or s.overlays:
            row['block_versions'] = _block_versions(s)
            from .block_theme import values
            row['block_theme'] = values(project, channel)
        # Search results nobody picked cannot change the picture on screen.
        overlay_ids = {o.get('source', {}).get('candidate_id') for o in (project.active_take(s) or {}).get('overlays', [])} if s.on_camera else set()
        row["candidates"] = [c for c in s.candidates if c["id"] == s.chosen_id or c['id'] in overlay_ids]
        if overlay_ids:
            row['overlay_files'] = [_stat(root / c['local_path']) for c in row['candidates'] if c.get('local_path')]
        take = (s.take or {}).get("path")
        slides.append([row, d, _stat(root / take) if take else None])
        if s.on_camera:
            camera = project.active_take(s) or {}
            slides[-1].append([_stat(root / camera[k]) if camera.get(k) else None
                               for k in ("video", "raw_path")])
    pic = _chosen(project, lead, preview=True)[0]
    from .camera import target
    if lead.on_camera:
        slides[0].append(target(project))
    blob = json.dumps(
        [PROXY_VERSION, sorted(hide), scenes.SCENE_VERSION, project.title, project.subtitle,
         index, [sum(d for _, d in g) for g in groups[:index]], slides, _stat(pic),
         [c for c in _picture_source(project, lead).candidates
          if c["id"] == _picture_source(project, lead).chosen_id],
         _segment_timing(project, groups, index), index == len(groups) - 1,
         chapter_card(project, nxt) if nxt else None,
         nxt.chapter_hold if nxt else None,
         cache_owner(project.style), project.frame.to_dict(),
         camera_plan(project, groups)[index],
         cache_owner(channel),
         _segments_before_slides(project), list(preview_size()), PREVIEW_FPS],
        default=str, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _proxy_paths(project: Project, lead: Slide, hide: frozenset = frozenset()) -> tuple[Path, Path]:
    cache = project_dir(project.id) / "cache"
    suffix = _hidden_suffix(hide)
    return cache / f"seg_{lead.id}{suffix}.webm", cache / f"seg_{lead.id}{suffix}.key"


def _proxy_ready(project: Project, groups, index: int, channel: Any, hide: frozenset = frozenset()) -> bool:
    out, keyfile = _proxy_paths(project, groups[index][0][0], hide)
    try:
        return (out.exists() and out.stat().st_size > 0
                and keyfile.read_text() == _proxy_key(project, groups, index, channel, hide))
    except (OSError, ValueError):  # ValueError: a block it uses is missing (pack removed)
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
        dur += _tail_pad(project, groups)
    return dur, T, dur + T


def _build_proxy(project: Project, groups, index: int, progress: Progress,
                 *, reuse: bool, download: bool = True, hide: frozenset = frozenset()) -> dict:
    from . import channels as channels_mod
    group = groups[index]
    lead = group[0][0]
    channel = channels_mod.load_or_none(project.channel_id)
    out, keyfile = _proxy_paths(project, lead, hide)
    size = preview_size()
    key = _proxy_key(project, groups, index, channel, hide)
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

    if download and not lead.on_camera and not (lead.cues or {}).get('blocks') and media.download_chosen(project, progress, only=[_picture_source(project, lead)]):
        progress("That picture could not be downloaded; this is the graded "
                 "slate the render would fall back to")

    chapter = (chapter_card(project, groups[index + 1][0][0])
               if index + 1 < len(groups) else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    # `.webm` is what makes these play in the app's own window on a Linux
    # desktop that has no H.264 decoder — see `ffutil.video_args`.
    mute = out.with_name(out.stem + "_mute.webm")

    progress(f"Picture {index + 1} of {len(groups)}: {seg_len:.1f}s "
             f"at {size[0]}×{size[1]}, {PREVIEW_FPS}fps")
    _render_segment(project, group, seg_len,
                    index + _segments_before_slides(project), mute,
                    channel=channel, chapter=chapter, size=size,
                    dip_out=_dips_into(groups, index + 1),
                    op=camera_plan(project, groups)[index], camera_index=index,
                    last_line=index == len(groups) - 1, hide=hide,
                    fps=PREVIEW_FPS, crf=PREVIEW_CRF, preset="ultrafast",
                    threads=max(2, min(8, os.cpu_count() or 4)))

    # Where the voice lands inside the segment: half a crossfade in, plus the
    # opening silence if this is the top of the video. The same arithmetic the
    # full render's narration bed uses, for one group of paragraphs.
    voice = out.with_suffix(".wav")
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
    from .learning import resolve_choices
    resolve_choices(project)
    groups = _groups_for_preview(project)
    index = next((i for i, g in enumerate(groups)
                  if any(s.id == slide_id for s, _d in g)), -1)
    if index < 0:
        raise ValueError("That paragraph is not in the cut.")
    return _build_proxy(project, groups, index, progress, reuse=False)


def proxy_segment(project: Project, index: int,
                  progress: Progress = lambda m: None, *, download: bool = True,
                  hide: frozenset = frozenset()) -> dict:
    """The same small render, kept: the timeline plays these back to back, so
    one that is still right for the current script is reused rather than drawn
    again."""
    from .learning import resolve_choices
    resolve_choices(project)
    groups = _groups_for_preview(project)
    if not 0 <= index < len(groups):
        raise ValueError("That picture is not in the cut.")
    return _build_proxy(project, groups, index, progress, reuse=True, download=download, hide=hide)


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
              dataclasses.asdict(channel.outro), dataclasses.asdict(channel.style),
              channel.frame.to_dict()]
             if channel else None)
    blob = json.dumps([PROXY_VERSION, scenes.SCENE_VERSION, kind, project.title,
                       parts, extra, list(preview_size()), PREVIEW_FPS],
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


def _sponsor_preview(project, slot):
    """Prepare a core block at the read's actual duration, without capturing."""
    from copy import deepcopy
    from . import blocks, sponsors, scene_builder
    block_id = 'sponsor_' + slot.variant
    block = deepcopy(blocks.discover()[block_id])
    block['meta']['duration'] = dict(mode='range', min=0)
    ctx = scenes.context_base(project)
    # Ink is supported by the sponsor scene but is not a core-block variable.
    if 'ink' in slot.vars:
        ctx['ink'] = slot.vars['ink']
    ctx.update(script=slot.script, take=slot.take, word_offset=0)
    values = {k: v for k, v in slot.vars.items() if k in block['meta']['variables']}
    template, ctx = blocks.prepare(block_id, values, '16:9', sponsors.duration(slot),
                                   context=ctx, _block=block)
    take_path = (slot.take or {}).get('path')
    key, _html = scenes._key(template, ctx, sponsors.duration(slot), preview_size(),
                            PREVIEW_FPS, ('sponsor-proxy-v1', scene_builder.MOTIONS,
                                          _stat(project_dir(project.id) / take_path) if take_path else None))
    out = project_dir(project.id) / 'cache' / f'tl_sponsor_{key}.mp4'
    return template, ctx, out


def sponsor_proxy(project, slot_id, progress=lambda m: None, *, audible=False):
    import tempfile
    from . import scene_builder, sponsors
    slot = next((s for s in project.sponsors if s.id == slot_id), None)
    if slot is None:
        raise ValueError('Sponsor slot not found')
    template, ctx, out = _sponsor_preview(project, slot)
    seconds = sponsors.duration(slot)
    if not out.exists() or not out.stat().st_size:
        progress('Drawing one sponsor segment at quarter size')
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=out.parent, prefix='sponsor-') as work:
            pending = Path(work) / 'preview.mp4'
            scene_builder.render(project, template, ctx, pending, seconds=seconds,
                                 size=preview_size(), fps=PREVIEW_FPS, crf=PREVIEW_CRF)
            pending.replace(out)
    if audible and slot.take and slot.take.get('path'):
        voiced = out.with_name(out.stem + '_voice.mp4')
        if not voiced.exists():
            ffutil.run(['-i', str(out), '-i', str(project_dir(project.id) / slot.take['path']),
                        '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
                        *ffutil.audio_args(voiced), '-af', 'apad', '-t', str(seconds), str(voiced)])
        out = voiced
    return dict(ref=f'sponsor:{slot.id}', path=f'cache/{out.name}',
                rendered_at=round(out.stat().st_mtime))


def proxy_ref(project: Project, ref: str, progress: Progress = lambda m: None,
              *, download: bool = True, hide: frozenset = frozenset()) -> dict:
    """Draw one timeline entry: a slate, sponsor:<id>, or picture number."""
    if ref.startswith("sponsor:"):
        return sponsor_proxy(project, ref.removeprefix("sponsor:"), progress)
    if ref in ("intro", "outro"):
        if not _slate_has(project, ref):
            raise ValueError("There is no such card in this video.")
        return _build_slate_proxy(project, ref, progress)
    out = proxy_segment(project, int(ref), progress, download=download, hide=hide)
    out["ref"] = ref
    return out


# --------------------------------------------------------------- timeline mix
def _layout(project: Project) -> dict:
    """The cut's running order in picture time, slates included.

    The same list of durations `render` builds: slate, pictures, end card, each
    one's screen time with the head and tail padding on the first and last
    picture. Picture time starts at the first frame of whatever opens the video.
    """
    from .learning import resolve_choices
    resolve_choices(project)
    groups = _groups_for_preview(project)
    T = cuts.transition_for(project.style)
    intro = _slate_state(project, "intro")
    outro = _slate_state(project, "outro")
    body = [_segment_timing(project, groups, i)[0] for i in range(len(groups))]
    pre = intro["length"] if intro else 0.0
    total = pre + sum(body) + (outro["length"] if outro else 0.0)
    from . import sponsors
    placed = _sponsor_placements(project, _slide_durations(project, True))
    entries, t = [], pre
    for group, seconds in zip(groups, body):
        t += seconds
        for slot in placed.get(group[-1][0].id, []):
            entries.append((slot, t))
            t += sponsors.duration(slot)
    total += sum(sponsors.duration(slot) for slot, _ in entries)
    return {"groups": groups, "T": T, "intro": intro, "outro": outro,
            "body": body, "pre": pre, "total": total, "sponsors": entries}


def _mix_paths(project: Project, hide: frozenset = frozenset()) -> tuple[Path, Path]:
    cache = project_dir(project.id) / "cache"
    suffix = _hidden_suffix(hide)
    return cache / f"timeline_mix{suffix}.webm", cache / f"timeline_mix{suffix}.key"


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


def _mix_key(project: Project, lay: dict, hide: frozenset = frozenset()) -> str:
    import dataclasses
    import hashlib
    import json

    root = project_dir(project.id)
    takes = [[s.id, (s.take or {}).get('cuts', []),
              _stat(root / s.take["path"]) if (s.take or {}).get("path") else None]
             for s in project.slides]
    music = pick_music(project)
    stings = _stings_for(project, bool(lay["intro"]), bool(lay["outro"]))
    card = _slate_channel(project) if lay["outro"] else None
    blob = json.dumps(
        [PROXY_VERSION, "linear-master-v1", project.frame.voice_lufs,
         sorted(hide), takes, lay["body"], lay["pre"], lay["total"],
         lay["intro"] and lay["intro"]["length"], lay["outro"] and lay["outro"]["length"],
         audio_mod.paragraph_gaps(project),
         str(music), _stat(music),
         {role: [str(f), _stat(f), _sting_params(spec)] for role, (f, spec) in stings.items()},
         project.style.music_db, project.voice.target_lufs, project.style.sponsor_music_db,
         [[dataclasses.asdict(slot), start, _stat(root / slot.take["path"])
           if (slot.take or {}).get("path") else None] for slot, start in lay["sponsors"]],
         float(card.outro.music_fade) if card else 5.0],
        default=str, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _mix_state(project: Project, lay: dict, hide: frozenset = frozenset()) -> dict:
    music = None if "music" in hide else pick_music(project)
    sting = {} if "stings" in hide else _stings_for(project, bool(lay["intro"]), bool(lay["outro"]))
    audible = bool(music or sting or any(s.take for s in project.slides)
                   or any(slot.take for slot, _ in lay["sponsors"]))
    out, keyfile = _mix_paths(project, hide)
    key = _mix_key(project, lay, hide) if audible else ""
    have = out.exists() and out.stat().st_size > 0
    try:
        fresh = have and keyfile.read_text() == key
    except OSError:
        fresh = False
    return {"audible": audible, "ready": bool(audible and fresh), "have": bool(audible and have),
            "stamp": round(out.stat().st_mtime) if have else 0,
            "path": f"cache/{out.name}", "music": music.name if music else "",
            "sting": bool(sting), "stings": sorted(sting)}


def build_mix(project: Project, progress: Progress = lambda m: None, *,
              hide: frozenset = frozenset()) -> dict:
    """The whole cut's sound, as one file: narration, the slate's sting and the
    music bed under the voice.

    Built with `_audio_graph`, the graph the finished render mixes with, so it
    ducks, fades and levels the same way. Audio only, so it takes a few seconds
    however long the video is; the player uses it as the clock and plays the
    picture proxies silently against it.
    """
    lay = _layout(project)
    state = _mix_state(project, lay, hide)
    if not state["audible"]:
        return state
    if state["ready"]:
        return state
    out, keyfile = _mix_paths(project, hide)
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
    stings = {} if "stings" in hide else _stings_for(project, bool(lay["intro"]), bool(lay["outro"]))
    if "intro" in stings:
        sting_audio.append((n, 0.0, lay["intro"]["length"], stings["intro"][1], "intro"))
        inputs += ["-i", str(stings["intro"][0])]
        n += 1
    if "outro" in stings:
        sting_audio.append((n, lay["total"] - lay["outro"]["length"],
                            lay["outro"]["length"], stings["outro"][1], "outro"))
        inputs += ["-i", str(stings["outro"][0])]
        n += 1
    sponsor_audio, n = _sponsor_audio(project, lay["sponsors"], inputs, n)
    music = None if "music" in hide else pick_music(project, progress)
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
    music_fade = 5.0
    if lay["outro"]:
        card = _slate_channel(project)
        if card:
            music_fade = float(card.outro.music_fade)
    from . import sponsors
    graph = _audio_graph(project, 0, total, bool(music), None, sting_audio, music_fade,
                         sponsor_audio, [(start, sponsors.duration(slot)) for slot, start in lay["sponsors"]])
    graph = _master_audio_graph(project, inputs, graph, total, 0, progress)
    progress("Mixing the sound for the whole cut"
             + (f" with the bed “{music.stem}”" if music else ", narration only"))
    ffutil.run([*inputs, "-filter_complex", graph, "-map", "[aout]",
                "-t", f"{total:.3f}", "-ar", "48000",
                *ffutil.audio_args(out, bitrate="96k"), str(out)], timeout=900)
    narration.unlink(missing_ok=True)
    keyfile.write_text(_mix_key(project, lay, hide))
    return _mix_state(project, lay, hide)


def timeline(project: Project, hide: frozenset = frozenset()) -> dict:
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
    ops = camera_plan(project, groups)
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
        file_lead = T / 2 + cuts.head_pad_for(project, lead)
        cue_times = {}
        if cuts.is_cut(project.style.format):
            _, _, length = _segment_timing(project, groups, i)
            cue_times = {sid: (cues, times) for sid, cues, times in
                         cuts.timed_cues(project, group, length, file_lead)}
        _, _, segment_length = _segment_timing(project, groups, i)
        paragraph_offset = 0.0
        for n, (s, d) in enumerate(group):
            start, end, title_hold = _title_window(project, s, d, file_lead, paragraph_offset,
                                      segment_length,
                                      i == len(groups) - 1 and n == len(group) - 1)
            arrival = start - paragraph_offset
            timing = {
                "title_at": {"value": round(arrival - file_lead, 3),
                             "start": round(pt + arrival - file_lead, 3),
                             "src": "user" if s.title_at is not None else "auto"},
                "title_hold": {"value": title_hold, "src": "user" if s.title_hold is not None else "auto"},
                "gap": {"value": audio_mod.gap_map(project)[s.id],
                        "src": "user" if s.gap_override is not None else "auto"},
                "chapter_hold": {"value": 0.0, "src": "user" if s.chapter_hold is not None else "auto"},
                "cues": [],
            }
            if chapter_title(project, s) and index_of[s.id] > 0:
                gap = audio_mod.gap_map(project)[project.slides[index_of[s.id] - 1].id]
                default = (max(0.9, min(3.2, gap - 0.12)) if scenes.handles(project.style.format)
                           or cuts.is_cut(project.style.format) or project.style.format == "board"
                           or project.style.format.startswith("custom:") else
                           max(project.frame.arrive_s, min(gap, project.frame.arrive_s
                               + project.frame.title_hold_base_s
                               + project.frame.title_hold_per_word_s * len(chapter_title(project, s).split()))))
                timing["chapter_hold"]["value"] = min(gap, max(0.0, s.chapter_hold)) if s.chapter_hold is not None else default
            if s.id in cue_times:
                cues, times = cue_times[s.id]
                timing["cues"] = [{"at": round(t + a - T / 2 - pt, 3),
                                   "start": round(t + a - T / 2, 3),
                                   "end": round(t + b - T / 2, 3),
                                   "src": "user" if "at" in cue else "auto"}
                                  for cue, (a, b) in zip(cues, times)]
            paras.append({
                "id": s.id, "index": index_of[s.id], "start": round(pt, 3),
                "duration": d, "text": s.narration, "title": s.title,
                "chapter": s.chapter, "words": s.word_count, "timing": timing,
                "spoken": cuts.spoken_of(s, d),
                "word_times": [{**w, "start": round(pt + w["start"], 3),
                                "end": round(pt + w["end"], 3)}
                               for w in take_words(s.take)],
                "effective_cues": cue_times.get(s.id, ([], []))[0],
                "recorded": bool(s.take), "section": s.section, "on_camera": s.on_camera,
            })
            if s.on_camera:
                take = project.active_take(s) or {}
                paras[-1]['camera_edit'] = {k: take.get(k, default) for k, default in
                    [('duration', 0), ('cuts', []), ('words', []), ('punch', True), ('overlays', [])]}
                paras[-1]['camera_edit']['effective_duration'] = take_duration(take)
            pt += d
            paragraph_offset += d
        _path, kind, _focal = _chosen(project, lead)
        problems = []
        if not lead.on_camera and not (lead.cues or {}).get('blocks') and not _picture_source(project, lead).chosen_id:
            problems.append("no picture chosen")
        missing = sum(1 for s, _d in group if not s.take)
        if missing:
            problems.append(f"{missing} paragraph{'s' if missing > 1 else ''} not recorded"
                            " (estimated length)")
        # Only the documentary cut holds one frame; every other format redraws
        # as the paragraphs change, so a long run there is not a still picture.
        if not lead.on_camera and dur > 25 and project.style.format == "kenburns":
            problems.append(f"the same picture holds for {dur:.0f}s")
        out, _keyfile = _proxy_paths(project, lead, hide)
        segments.append({
            "ref": str(i), "type": "picture", "n": i + 1, "group": i, "lead": lead.id,
            "start": round(t, 3), "duration": round(dur, 3), "skip": round(T / 2, 3),
            "kind": "camera" if lead.on_camera else kind, "camera": ops[i], "problems": problems, "paragraphs": paras,
            **({"camera_stamp": _stat(project_dir(project.id) / (project.active_take(lead) or {}).get("video", ""))}
               if lead.on_camera else {}),
            "ready": _proxy_ready(project, groups, i, channel, hide),
            # Something to play, even if the script has moved on since.
            "have": out.exists() and out.stat().st_size > 0,
            "stamp": round(out.stat().st_mtime) if out.exists() else 0,
            "path": f"cache/{out.name}",
        })
        t += dur
        from . import sponsors
        for slot, start in lay["sponsors"]:
            if abs(start - t) > 0.001:
                continue
            seconds = sponsors.duration(slot)
            _template, _ctx, out = _sponsor_preview(project, slot)
            ready = out.exists() and out.stat().st_size > 0
            segments.append({"ref": f"sponsor:{slot.id}", "type": "sponsor", "n": 0,
                             "group": -1, "lead": "", "start": round(t, 3),
                             "duration": seconds, "skip": 0.0, "paragraphs": [],
                             "sponsor": slot.id, "script": slot.script, "variant": slot.variant,
                             "kind": "scene", "problems": [] if slot.take else ["sponsor not recorded"],
                             "ready": ready, "have": ready, "estimated": not bool(slot.take),
                             "stamp": round(out.stat().st_mtime) if ready else 0,
                             "path": f"cache/{out.name}"})
            t += seconds
    if lay["outro"]:
        segments.append(slate_row("outro", lay["outro"], t))
        t += lay["outro"]["length"]
    for n, seg in enumerate(segments):
        seg["index"] = n
    from . import sponsors
    size = preview_size()
    pres = project.presenter
    return {
        "sponsor_suggestions": sponsors.suggest_slots(project),
        "layers": _layers(project, segments),
        "segments": segments, "total": round(t, 3), "fps": PREVIEW_FPS,
        "width": size[0], "height": size[1],
        "format": project.style.format,
        "title_exit": project.frame.arrive_s * project.frame.exit_ratio,
        "last_line_min_s": project.frame.last_line_min_s,
        "mix": _mix_state(project, lay, hide),
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
        from . import packs
        credit = next((item['credits'] for pack in packs.scan() for item in pack.music()
                       if item['path'] == music), {})
        line = f"Music: {credit.get('title', music.stem)}"
        line += f" by {credit['artist']}" if credit.get('artist') else ''
        line += f" ({credit['licence']})" if credit.get('licence') else ''
        line += f" {credit['url']}" if credit.get('url') else ''
        lines += ["", line]
    lines += ["", "Verify every licence before publishing. Some archives place "
                  "conditions on commercial reuse."]
    return "\n".join(lines)

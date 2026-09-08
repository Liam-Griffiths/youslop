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
from . import ffutil, media, titles
from .config import (
    FPS, HEAD_PAD, HEIGHT, MUSIC_DIR, PARAGRAPH_GAP, TAIL_PAD, WIDTH,
    WORDS_PER_MINUTE,
)
from .schema import AUTO_MUSIC, Project, Slide, group_slides
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
              focal_px: tuple[float, float] | None = None) -> str:
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
            f"d={n}:s={WIDTH}x{HEIGHT}:fps={FPS}")


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


def _essay_card(src: Path | None) -> tuple[int, int, int, int]:
    """Card size and position for one picture: its own shape, centred."""
    try:
        sw, sh = ffutil.dimensions(src) if src else (0, 0)
    except Exception:
        sw, sh = 0, 0
    if sw <= 0 or sh <= 0:
        sw, sh = 16, 9
    scale = min(ESSAY_MAX_W / sw, ESSAY_MAX_H / sh)
    # Even dimensions: odd ones make the scaler and the encoder both unhappy.
    bw = max(2, int(round(sw * scale)) // 2 * 2)
    bh = max(2, int(round(sh * scale)) // 2 * 2)
    return bw, bh, (WIDTH - bw) // 2, ESSAY_TOP + (ESSAY_BAND_H - bh) // 2


def _essay_stage(source: str, accent: str, src: Path | None,
                 fps: bool = False) -> str:
    """Filtergraph putting `source` in a bordered slide over a blur of itself.

    Ends on [base], which is the label the grade tail downstream expects, so
    an essay segment grades and vignettes exactly like a documentary one.
    """
    bw, bh, box_x, box_y = _essay_card(src)
    inner_w, inner_h = bw - 2 * ESSAY_BORDER, bh - 2 * ESSAY_BORDER
    rate = f",fps={FPS}" if fps else ""
    return (
        f"{source}split=2[ebg][efg];"
        # The fill: cropped to the frame, blurred right down, pushed back so the
        # slide on top of it reads as the subject rather than competing.
        f"[ebg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},gblur=sigma=34,eq=brightness=-0.16:saturation=1.15"
        f"{rate}[ebgout];"
        # The slide: the whole picture, never cropped — an archive screenshot
        # loses its point when the edges are cut off — inside its own border.
        f"[efg]scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
        f"pad={inner_w}:{inner_h}:(ow-iw)/2:(oh-ih)/2:color=#0B0C10,"
        f"pad={bw}:{bh}:{ESSAY_BORDER}:{ESSAY_BORDER}:color={accent}{rate}[ecard];"
        f"[ebgout][ecard]overlay={box_x}:{box_y}:format=auto[base]"
    )


def _render_segment(
    project: Project, group: list[tuple[Slide, float]], seg_len: float,
    index: int, out: Path, channel=None, chapter: tuple[str, str] | None = None
) -> Path:
    """Render one held picture to a silent mp4 of exactly `seg_len` seconds.

    A group is one or more consecutive paragraphs sharing a picture. The first
    slide in it supplies the visual; every slide in it can still put its own
    title on screen, at its own moment inside the hold.

    `style.format` decides how that picture is staged: the documentary cut
    fills the frame and drifts across it, the essay cut sets the whole picture
    inside a bordered slide and puts the narration on screen underneath.
    """
    style = project.style
    essay = style.format == "essay"
    slide = group[0][0]
    src, kind, focal = _chosen(project, slide)
    frames = max(2, int(round(seg_len * FPS)))
    grade = GRADES.get(style.grade, GRADES["warm"])
    vig = _vignette(style.vignette)

    inputs: list[str] = []
    chain: list[str] = []
    pre_graph = ""            # set by sources that need more than one input

    if src is None:
        # Nothing picked or the download failed: a graded slate keeps the cut
        # intact rather than aborting the whole render.
        inputs += ["-f", "lavfi", "-i",
                   f"color=c=#12131a:s={WIDTH}x{HEIGHT}:r={FPS}:d={seg_len:.3f}"]
        chain.append("null")
    elif essay:
        # The essay slide: the whole picture, uncropped, inside an accent
        # border, over a blurred fill of itself. One source feeds both layers.
        if kind == "video":
            crop, _ = _cover_crop(src, WIDTH, HEIGHT, focal)
            clip_inputs, clip_graph = _clip_source(src, seg_len, crop)
            inputs += clip_inputs
            pre_graph = (f"{clip_graph};"
                         + _essay_stage("[base]", style.accent, src))
        else:
            inputs += ["-loop", "1", "-i", str(src)]
            pre_graph = _essay_stage("[0:v]", style.accent, src, fps=True)
    elif kind == "video":
        crop, _ = _cover_crop(src, WIDTH, HEIGHT, focal)
        clip_inputs, pre_graph = _clip_source(src, seg_len, crop)
        inputs += clip_inputs
    else:
        inputs += ["-loop", "1", "-i", str(src)]
        # Oversample to 2x output before the zoom so the pan stays subpixel-smooth.
        crop, focal_px = _cover_crop(src, WIDTH * 2, HEIGHT * 2, focal)
        chain.append(crop)
        if style.ken_burns:
            chain.append(_kenburns(MOVES[index % len(MOVES)], frames,
                                   style.ken_burns_amount, focal_px))
        else:
            chain.append(f"scale={WIDTH}:{HEIGHT},fps={FPS}")

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
            av_h = int(max(0.1, min(0.4, av.scale)) * HEIGHT)
            margin = 40
            x = f"W-w-{margin}" if av.position != "bottom_left" else str(margin)
            graph += (
                f";[{n_inputs}:v]format=rgba,scale=-1:{av_h}[avatar]"
                f";{last}[avatar]overlay={x}:H-h-{margin}:format=auto[av]"
            )
            inputs += ["-loop", "1", "-i", str(av_src)]
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
                inputs += ["-loop", "1", "-i", str(card)]
                n_inputs += 1
                # Quick on, quick off: a caption that dissolves like a title
                # reads as sluggish against the pace of the read.
                graph += (
                    f";[{idx}:v]format=rgba,"
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
            inputs += ["-loop", "1", "-i", str(card)]
            n_inputs += 1
            start = offset + 0.55
            hold = min(6.0, max(2.0, dur - 1.2))
            fade_out_at = min(seg_len - 0.9, start + hold)
            if fade_out_at > start + 0.4:
                graph += (
                    f";[{idx}:v]format=rgba,fade=t=in:st={start:.3f}:d=0.75:alpha=1,"
                    f"fade=t=out:st={fade_out_at:.3f}:d=0.85:alpha=1[ttl{n}]"
                    f";{last}[ttl{n}]overlay=0:0:format=auto[v{n}]"
                )
                last = f"[v{n}]"
        offset += dur

    # The chapter card for the section that starts next. It lands in the long
    # silence `audio.GAP_CHAPTER` opens at the end of this segment, so the
    # video pauses on the title and then the new section begins.
    if chapter and essay:
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
        inputs += ["-loop", "1", "-i", str(card)]
        graph += (
            f";[{n_inputs}:v]format=rgba,"
            f"fade=t=in:st={start:.3f}:d=0.45:alpha=1[chap]"
            f";{last}[chap]overlay=0:0:format=auto[vchap]"
        )
        n_inputs += 1
        last = "[vchap]"

    ffutil.run([
        *inputs, "-filter_complex", graph, "-map", last,
        "-t", f"{seg_len:.3f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", str(out),
    ])
    return out


# ---------------------------------------------------------------------- intro
def _build_intro(project: Project, progress: Progress) -> tuple[Path | None, float]:
    """Render this project's channel slate, if it has one. Never fatal."""
    if not (project.channel_id and project.use_intro):
        return None, 0.0
    from . import channels, intro as intro_mod

    channel = channels.load_or_none(project.channel_id)
    if channel is None:
        progress("This video's channel is gone; rendering without a slate")
        return None, 0.0
    # Only the cast-led templates need portraits; the type-led ones stand alone.
    if intro_mod.needs_images(channel.intro.template) and len(channel.intro.images or []) < 2:
        progress(f"Channel “{channel.name}” has no cast yet; rendering without a slate")
        return None, 0.0

    out = project_dir(project.id) / "segments" / "intro.mp4"
    try:
        length = intro_mod.render_intro(channel, project.title or "", out, progress)
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


def _build_outro(project: Project, progress: Progress) -> tuple[Path | None, float]:
    """The channel's end screen, if it has one turned on. Never fatal."""
    if not (project.channel_id and project.use_outro):
        return None, 0.0
    from . import channels, outro as outro_mod

    channel = channels.load_or_none(project.channel_id)
    if channel is None or not channel.outro.enabled:
        return None, 0.0

    backdrop = None
    if outro_mod.wants_backdrop(channel.outro.template) or channel.outro.backdrop > 0.01:
        backdrop = _last_picture(project)

    out = project_dir(project.id) / "segments" / "outro.mp4"
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
                  fmt: str, voice_lufs: float = -16.0) -> str:
    """The slate's own sting. `adelay` goes last: nothing may follow it.

    The window, the level and the fade come from `intro.sting_chain`, which the
    slate preview uses too, so the two cannot drift apart.
    """
    from . import intro as intro_mod
    delay = int(round(offset * 1000))
    return (f"[{idx}:a]"
            + intro_mod.sting_chain(intro, length, fmt, voice_lufs)
            + (f",adelay={delay}|{delay}" if offset > 0.01 else "")
            + "[sting];")


def _audio_graph(project: Project, n_video: int, total: float, has_music: bool,
                 presenter: tuple[int, float, float, float] | None = None,
                 sting: tuple[int, float, float, Any] | None = None,
                 music_fade: float = 5.0) -> str:
    """Voice (narration + any camera clip) plus a ducked music bed.

    The camera clip's audio joins the *voice* bus rather than sitting alongside
    it, so the music ducks under your on-camera delivery exactly as it does
    under the narration, and the whole thing masters as one voice.
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

    sting_graph = ""
    if sting:
        s_idx, s_off, s_len, s_intro = sting
        sting_graph = _sting_branch(s_idx, s_off, s_len, s_intro, fmt, vlufs)

    if not has_music:
        if sting:
            return (voice + sting_graph +
                    f"{voice_src}[sting]amix=inputs=2:duration=longest:normalize=0[mix];"
                    f"[mix]loudnorm=I=-14:TP=-1.0:LRA=11[aout]")
        return voice + f"{voice_src}loudnorm=I=-14:TP=-1.0:LRA=11[aout]"

    mus = f"[{n_video + 1 + (1 if presenter else 0) + (1 if sting else 0)}:a]"
    ratio = max(2.0, min(20.0, 1 + abs(project.style.duck_db) / 1.4))
    fade = max(0.5, min(18.0, music_fade))
    fade_out_at = max(0.5, total - fade)

    # When the slate has a sting of its own, the bed holds off until the slate is
    # over. `afade` with a start time silences everything before it, so this needs
    # no adelay: the bed simply fades up as the sting rings out.
    bed_in_at = 0.0
    if sting:
        bed_in_at = max(0.0, sting[1] + sting[2] - 0.35)

    # Normalise the bed to the same loudness the voice takes were normalised to
    # before attenuating it. Without this, music_db is an offset from
    # whatever level the track happened to be mastered at, so a quiet track
    # vanishes and a loud one buries the narration. Now it means what it says:
    # this many dB below the voice.
    return (
        voice + sting_graph +
        f"{voice_src}asplit=2[voice][key];"
        f"{mus}{fmt},"
        f"atrim=duration={total:.3f},"
        f"loudnorm=I={vlufs:.1f}:TP=-2.0:LRA=11,"
        f"volume={project.style.music_db:.1f}dB,"
        f"afade=t=in:st={bed_in_at:.3f}:d=3,"
        f"afade=t=out:st={fade_out_at:.3f}:d={fade:.3f}[bed];"
        f"[bed][key]sidechaincompress=threshold=0.025:ratio={ratio:.2f}:"
        f"attack=25:release=550:makeup=1:level_sc=1[duck];"
        + (f"[voice][duck][sting]amix=inputs=3:duration=longest:normalize=0[mix];"
           if sting else
           f"[voice][duck]amix=inputs=2:duration=longest:normalize=0[mix];")
        + f"[mix]loudnorm=I=-14:TP=-1.0:LRA=11[aout]"
    )


# ---------------------------------------------------------------------- render
def render(project: Project, progress: Progress = lambda m: None,
           preview: bool = False) -> dict:
    """Full render. `preview` uses estimated timings when nothing is recorded."""
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

    T = max(0.0, float(project.style.transition))

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
    done = 0
    # Loaded once rather than per segment: the essay format reads the host
    # avatar off it, and every segment would otherwise re-read the same file.
    from . import channels as channels_mod
    seg_channel = channels_mod.load_or_none(project.channel_id)

    def work(i: int) -> tuple[int, Path]:
        out = seg_dir / f"seg{i + slide_at:04d}.mp4"
        # A section starting in the next group is announced at the end of this
        # one, in the silence that precedes it.
        chapter = None
        if i + 1 < len(groups):
            nxt = groups[i + 1][0][0]
            if nxt.title:
                # Title only. `beat` is the outline beat the paragraph serves,
                # which lags a section behind at a boundary — it printed "Steam
                # Changes The Deal" over the card announcing "The PC Bang
                # Problem" — so it is the wrong field to caption a chapter with.
                chapter = (nxt.title, "")
        _render_segment(project, groups[i], seg_lens[i + slide_at], i + slide_at,
                        out, channel=seg_channel, chapter=chapter)
        return i, out

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

    # The slate's own sting, if the channel has one.
    sting_audio = None
    if intro_path:
        from . import channels as channels_mod
        ch = channels_mod.load_or_none(project.channel_id)
        rel = ch.intro.music if ch else ""
        sting_file = (channels_mod.channel_dir(ch.id) / rel) if (ch and rel) else None
        if sting_file and sting_file.exists():
            # The slate is the first segment unless a camera clip was put ahead
            # of it, in which case the sting waits for that clip to finish.
            intro_offset = durations[0] if (pres_src and pres_index == 0) else 0.0
            sting_audio = (next_idx, intro_offset, intro_len, ch.intro)
            inputs += ["-i", str(sting_file)]
            next_idx += 1
            window = float(ch.intro.music_start)
            progress(f"Slate sting: {ch.intro.music_filename or sting_file.name}"
                     + (f", from {window:.1f}s into it" if window > 0.05 else "")
                     + (f" (starting at {intro_offset:.1f}s)" if intro_offset else ""))

    if music:
        # -stream_loop -1 runs the bed round for as long as the video needs; the
        # graph then trims it to length. A five minute track under a twenty-five
        # minute video plays five times.
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        progress(f"Music bed: {music.name}"
                 + (", looped to length" if _music_loops(music, total) else "")
                 + (" — held back until the slate ends" if sting_audio else ""))
    elif not project.music:
        progress("No music bed chosen, rendering narration only")
    else:
        progress("Rendering narration only")

    # Crossfade chain: each xfade starts T seconds before the previous clip ends.
    if len(seg_paths) == 1:
        video_graph = "[0:v]null[vout]"
    else:
        parts = []
        offset = seg_lens[0] - T
        prev = "[0:v]"
        for i in range(1, len(seg_paths)):
            label = "[vout]" if i == len(seg_paths) - 1 else f"[x{i}]"
            parts.append(
                f"{prev}[{i}:v]xfade=transition=fade:duration={T:.3f}:"
                f"offset={offset:.3f}{label}"
            )
            prev = label
            offset += seg_lens[i] - T
        video_graph = ";".join(parts)

    # An end screen is long enough that where the bed gives out is a decision,
    # so the card carries the fade length; without one the default stands.
    music_fade = 5.0
    if outro_path:
        from . import channels as channels_mod
        ch = channels_mod.load_or_none(project.channel_id)
        if ch:
            music_fade = float(ch.outro.music_fade)

    graph = video_graph + ";" + _audio_graph(project, len(seg_paths), total,
                                             bool(music), presenter_audio, sting_audio,
                                             music_fade)

    safe = "".join(c if c.isalnum() or c in " -_" else "" for c in (project.title or "video"))
    out_name = (safe.strip().replace(" ", "_") or "video")[:60] + (
        "_preview.mp4" if preview else ".mp4")
    out_path = root / "out" / out_name

    progress("Encoding final cut, this is the slow part")
    ffutil.run([
        *inputs, "-filter_complex", graph,
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(out_path),
    ], timeout=7200)

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


# --------------------------------------------------------------- attribution
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
        bits = [cand.get("title") or "Untitled"]
        if cand.get("author"):
            bits.append(f"by {cand['author']}")
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

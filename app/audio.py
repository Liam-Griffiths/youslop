"""Narration take processing: clean, trim and level each recorded paragraph."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import NamedTuple

from . import ffutil
from .config import HEAD_PAD, PARAGRAPH_GAP, TAIL_PAD
from .schema import Project, Voice, chapter_title


# How the pause after a paragraph varies with how that paragraph ended. Speech
# does not leave the same hole after a comma as after the end of a chapter, and
# an even 0.35s everywhere is the thing that makes a cut sound assembled.
GAP_MID = 0.55          # ended mid-thought: comma, dash, no terminal stop
GAP_QUESTION = 1.25     # a question or an exclamation earns a beat to land
GAP_BEAT = 1.35         # the outline moves on to its next beat
GAP_SECTION = 2.1       # a chapter title comes up, or intro -> main -> conclusion
GAP_LAST = 1.0          # before the tail padding
# The essay format holds a full chapter card in that silence rather than
# putting a title in the corner of a shot that is still talking, so the break
# has to be long enough to read one. Both the narration bed and the picture
# timing come from `paragraph_gaps`, so lengthening it here moves the voice and
# the pictures together and they cannot drift apart.
GAP_CHAPTER = 5.2


def paragraph_gaps(project: Project) -> list[float]:
    """The silence to leave after each recorded paragraph, in slide order.

    One list, read by both the narration builder and the picture timing, so the
    two can never disagree about where a paragraph ends.
    """
    base = max(0.05, min(2.5, float(getattr(project.style, "paragraph_gap", PARAGRAPH_GAP))))
    # Every slide, recorded or not: "does a new section start after this one" is
    # a question about the script, not about what happens to be recorded today.
    slides = project.slides
    gaps: list[float] = []
    for i, s in enumerate(slides):
        nxt = slides[i + 1] if i + 1 < len(slides) else None
        text = (s.narration or "").strip()
        end = text[-1:] if text else "."
        factor = 1.0
        if end in ",;:" or (end and end not in ".!?…\"'"):
            factor = GAP_MID          # the sentence runs on; keep it moving
        elif end in "?!":
            factor = GAP_QUESTION
        if nxt is None:
            factor = GAP_LAST
        else:
            # Graded, because scripts move to a new outline beat every paragraph
            # or two and a full breath that often just sounds slow. The long one
            # is kept for where the video itself announces a chapter.
            if (nxt.beat or "") != (s.beat or ""):
                factor = max(factor, GAP_BEAT)
            if nxt.title or (nxt.section or "") != (s.section or ""):
                factor = max(factor, GAP_SECTION)
            # A card the viewer has to read needs a hole to be read in. Marked
            # by hand in any format, or — in the essay cut, where it has always
            # worked this way — by the next paragraph carrying a title.
            if (nxt.chapter or "").strip() or (
                    nxt.title and getattr(project.style, "format", "") == "essay"):
                factor = max(factor, GAP_CHAPTER)
        gaps.append(round(base * factor, 3))
    return gaps


def gap_map(project: Project) -> dict[str, float]:
    """Slide id -> the pause that follows it."""
    return {s.id: g for s, g in zip(project.slides, paragraph_gaps(project))}


# --------------------------------------------------------------- take cleanup
# Every take is measured before it is touched. A fixed threshold cannot work
# across takes: one paragraph peaks at -21dBFS and another, read softer, never
# gets above -35, so a level that means "silence" in the first is mid-sentence
# in the second. The old chain used one (-42dB) and ate whole trailing clauses.
#
# The measurement is a 20ms RMS envelope, and everything below is decided from
# it: where speech really starts and ends, and how loud the room is, which is
# what the denoiser needs to know to subtract the room without eating the voice.
FRAME = 0.02            # seconds of audio per level reading
SMOOTH = 5              # readings averaged for "is this speech" (100ms)
WIDE = 11               # readings averaged for "is this a click" (220ms)
CORE_RUN = 5            # sustained speech needed to anchor a take (100ms)
CORE_OVER = 15.0        # dB above the room tone that certainly is speech
CORE_UNDER = 20.0       # ...or this far below the loudest part of the take
EDGE_DROP = 14.0        # dB below the speech threshold where a word has ended
EDGE_OVER = 6.0         # ...but never closer than this to the room tone
REACH = 1.20            # furthest the edge search walks out from the speech
HEAD_ROOM = 0.06        # audio kept before the first word
TAIL_ROOM = 0.14        # audio kept after the last word, so it can decay
HEAD_FADE = 0.02
TAIL_FADE = 0.09        # long enough to swallow anything at the very edge
CLICK_OVER = 12.0       # dB above the room tone, with no speech around it


def _levels(path: Path) -> list[float]:
    """A 20ms RMS envelope of the file, in dBFS."""
    graph = (
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono,"
        "highpass=f=80,"
        f"asetnsamples=n={int(48000 * FRAME)}:p=0,"
        "astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )
    out, _ = ffutil.capture(["-i", str(path), "-af", graph, "-f", "null", "-"])
    env: list[float] = []
    for line in out.splitlines():
        if "RMS_level=" not in line:
            continue
        try:
            v = float(line.rsplit("=", 1)[1])
        except ValueError:
            v = -120.0
        env.append(-120.0 if v != v or v < -120.0 else v)   # -inf, nan, silence
    return env


def _mean(env: list[float], n: int) -> list[float]:
    """Centred running mean, in dB.

    Averaging in dB rather than in power is deliberate: it is what makes a click
    invisible here. One 20ms bang at -20dBFS among -56dBFS room tone averages to
    -49dB over 100ms — nowhere near speech — while a spoken syllable, which is
    sustained, keeps its level. The edge search can then be generous without
    ever mistaking the mouse for a word.
    """
    half = n // 2
    out = []
    for i in range(len(env)):
        lo, hi = max(0, i - half), min(len(env), i + half + 1)
        out.append(sum(env[lo:hi]) / (hi - lo))
    return out


def _pct(ordered: list[float], q: float) -> float:
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * q)))]


class Span(NamedTuple):
    """Where the speech sits in a take, and the levels either side of it."""
    start: float
    end: float
    floor: float        # room tone, dBFS
    peak: float         # the speech itself, dBFS


def speech_span(env: list[float]) -> Span | None:
    """Where the speech is, and the levels around it. None if there is none.

    Found in two moves. First anchor on something that is certainly speech — a
    sustained run well above the room tone — which a click cannot fake. Then
    walk outwards from the anchor while the audio is still above the room, so
    quiet trailing syllables, the tail of a breath and the natural decay of the
    room all survive, and stop at any isolated bang on the way out.
    """
    if len(env) < CORE_RUN + 2:
        return None
    sm, wide = _mean(env, SMOOTH), _mean(env, WIDE)
    ordered = sorted(env)
    floor = _pct(ordered, 0.10)
    peak = _pct(ordered, 0.95)
    hi = max(floor + CORE_OVER, peak - CORE_UNDER)
    lo = max(floor + EDGE_OVER, hi - EDGE_DROP)

    n = len(env)
    runs = [i for i in range(n - CORE_RUN + 1)
            if all(sm[j] >= hi for j in range(i, i + CORE_RUN))]
    if not runs:
        return None

    def bang(i: int) -> bool:
        # Loud, but with nothing sustained around it: a mouse, a desk knock.
        return env[i] - floor >= CLICK_OVER and wide[i] < hi - 6.0

    s, e = runs[0], runs[-1] + CORE_RUN - 1
    stop = max(0, s - int(REACH / FRAME))
    while s > stop and sm[s - 1] > lo and not bang(s - 1):
        s -= 1
    stop = min(n - 1, e + int(REACH / FRAME))
    while e < stop and sm[e + 1] > lo and not bang(e + 1):
        e += 1

    start = max(0.0, s * FRAME - HEAD_ROOM)
    end = (e + 1) * FRAME + TAIL_ROOM
    return Span(start, end, floor, peak)


# ------------------------------------------------------------------- de-room
# A roomy take is not a noisy one, so no denoiser can touch it: it is your own
# voice arriving a few milliseconds late off the walls behind you. Two things
# actually move it.
#
# The expander is the one that matters. Reflections only ever exist *under* the
# direct sound — between words, and for the 100-200ms after each one, where
# they sit some 10-15dB below the voice with nothing else in the way. An
# expander whose threshold is set from this take's own speech level therefore
# leaves every spoken frame alone (measured on a real take: 0.0dB of gain
# change on speech, quiet syllables included) and pulls down only what is left
# over in between. The gate under it takes the last of the room out of the
# true gaps.
#
# The other is tone. A small room piles its reflections into a 300-500Hz honk,
# and that reads as "boxy" long before anyone would call it an echo. Dipping
# there while putting body back at 180Hz is most of the distance between
# "recorded across a desk" and "recorded into a microphone".
TAIL_UNDER = 13.0       # dB below this take's speech level, where the tails are
FLOOR_OVER = 8.0        # dB above the room tone, for the gate under that


def _lin(db: float) -> str:
    """dB -> the 0..1 amplitude agate wants."""
    return f"{10 ** (db / 20):.6f}"


def voice_chain(span: Span, voice: Voice | None = None,
                measured: dict | None = None) -> str:
    """The cleanup applied to one take, in order.

    trim/fade   - only the speech, with a fade over each cut so the join is
                  silent and any transient sitting on the edge is swallowed
    highpass    - desk rumble and room boom below the voice
    adeclick    - impulsive noise: a keyboard, a mouse, a lip smack
    afftdn      - broadband denoise, told the room's actual level. Guessing
                  this is what makes denoised speech sound underwater.
    agate x2    - the de-room pair above: tails first, then the gaps
    equalizer   - body at 180, the boxy 430Hz out, presence at 3.1k
    treble      - a little air on top, which is most of what "good mic"
                  sounds like and the first thing denoising takes away
    deesser     - pay for that lift by holding the sibilance down
    acompressor - even out the read so quiet ends of sentences stay audible
    loudnorm    - every take lands on the same perceived level
    """
    v = voice or Voice()
    start, end, floor, peak = span
    length = max(0.1, end - start)
    nf = min(-20.0, max(-80.0, floor + 3.0))
    room = max(0.0, min(1.0, v.de_room))

    chain = [
        f"atrim=start={start:.3f}:end={end:.3f}",
        "asetpts=N/SR/TB",
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono",
        f"highpass=f={max(40.0, min(160.0, v.low_cut)):.0f}:poles=2",
        "adeclick=w=55:o=75:t=2:b=2",
        f"afftdn=nf={nf:.0f}:nr={6 + 16 * max(0.0, min(1.0, v.denoise)):.0f}:nt=w:tn=1",
    ]

    if room > 0.02:
        # Tails: threshold off the speech level, so a quiet read and a loud one
        # get the same treatment. Range is what you actually hear — past about
        # 14dB the room stops sounding smaller and starts sounding switched off.
        chain.append(
            f"agate=threshold={_lin(peak - TAIL_UNDER)}:ratio={1.8 + 2.4 * room:.2f}"
            f":range={_lin(-(5.0 + 14.0 * room))}:attack=6:release={150 - 50 * room:.0f}"
            ":knee=8:detection=rms:link=average"
        )
        # The gaps. Kept clear of the speech even on a take read into a loud
        # room, where floor + 8 could otherwise land inside the voice.
        chain.append(
            f"agate=threshold={_lin(min(floor + FLOOR_OVER, peak - 22.0))}:ratio=3"
            f":range={_lin(-(8.0 + 14.0 * room))}:attack=12:release=350"
            ":knee=6:detection=rms:link=average"
        )

    chain += [
        f"equalizer=f=180:t=q:w=0.9:g={v.warmth:.2f}",
        f"equalizer=f=430:t=q:w=1.15:g={-abs(v.box_cut):.2f}",
        f"equalizer=f=3100:t=q:w=1.2:g={v.presence:.2f}",
        f"treble=f=9500:g={v.air:.2f}",
        f"deesser=i={max(0.0, min(1.0, v.sibilance)):.2f}:m=0.5:f=0.5",
    ]

    comp = max(0.0, min(1.0, v.compression))
    chain.append(
        f"acompressor=threshold={-14.0 - 10.0 * comp:.0f}dB:ratio={2.0 + 2.0 * comp:.2f}"
        ":attack=10:release=170:knee=6"
    )
    chain += [
        f"afade=t=in:st=0:d={HEAD_FADE}",
        f"afade=t=out:st={max(0.0, length - TAIL_FADE):.3f}:d={TAIL_FADE}",
    ]

    norm = f"loudnorm=I={v.target_lufs:.1f}:TP=-1.5:LRA=11"
    if measured:
        # Second pass: one static gain from the measured loudness, instead of
        # the moving gain a single pass applies. Takes then match each other,
        # and the compressor above is not fighting a second set of dynamics.
        norm += (f":measured_I={measured['input_i']}"
                 f":measured_TP={measured['input_tp']}"
                 f":measured_LRA={measured['input_lra']}"
                 f":measured_thresh={measured['input_thresh']}"
                 f":offset={measured['target_offset']}:linear=true")
    chain.append(norm)
    return ",".join(chain)


def _measure(raw_path: Path, span: Span, voice: Voice | None) -> dict | None:
    """Run the chain to nowhere to learn how loud the result comes out."""
    chain = voice_chain(span, voice) + ":print_format=json"
    try:
        _, log = ffutil.capture(["-i", str(raw_path), "-af", chain, "-f", "null", "-"])
    except ffutil.FFError:
        return None
    blocks = re.findall(r"\{[^{}]*input_i[^{}]*\}", log, re.S)
    if not blocks:
        return None
    try:
        got = json.loads(blocks[-1])
    except json.JSONDecodeError:
        return None
    need = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if any(got.get(k) in (None, "-inf", "inf", "nan") for k in need):
        return None
    return got


def process_take(raw_path: Path, out_path: Path, voice: Voice | None = None) -> dict:
    """Clean one uploaded take into a 48k mono wav. Returns take metadata.

    Written to a scratch file and moved into place only once it is known good.
    A re-record that fails — a silent mic, a browser that hands over a truncated
    blob — must not take the previous take down with it, which is how a project
    ends up with metadata claiming twenty seconds over an empty file.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    span = speech_span(_levels(raw_path))
    if span is None:
        raise ValueError("That take is silent or too short. Check your microphone.")
    total = ffutil.duration(raw_path)
    if total:
        span = span._replace(end=min(span.end, total))
    chain = voice_chain(span, voice, _measure(raw_path, span, voice))

    tmp = out_path.with_suffix(".part.wav")
    try:
        ffutil.run(["-i", str(raw_path), "-af", chain,
                    "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(tmp)])
        dur = ffutil.duration(tmp)
        if dur < 0.25:
            raise ValueError("That take is silent or too short. Check your microphone.")
        tmp.replace(out_path)
    finally:
        tmp.unlink(missing_ok=True)
    return {"duration": round(dur, 3), "recorded_at": time.time(),
            "trimmed": [round(span.start, 3), round(span.end, 3)],
            "room_db": round(span.floor, 1), "speech_db": round(span.peak, 1)}


# ------------------------------------------------------------- the mic check
# What the setup panel puts in front of you before a script gets read into a
# room that was never going to work. All of it is measured off one short test
# recording; none of it is a guess about your gear.
def _true_peak(path: Path) -> float:
    """The loudest single sample in the file, dBFS. -120 when silent."""
    try:
        _, log = ffutil.capture(
            ["-i", str(path), "-af", "astats=measure_perchannel=Peak_level"
             ":measure_overall=Peak_level", "-f", "null", "-"])
    except ffutil.FFError:
        return -120.0
    found = re.findall(r"Peak level dB:\s*(-?[\d.]+|-?inf)", log)
    vals = [float(x) for x in found if x not in ("-inf", "inf")]
    return max(vals) if vals else -120.0


def _offset_decay(env: list[float], peak: float) -> float:
    """How many dB the take falls in the 200ms after a word ends.

    The plainest reverb measurement there is. A voice recorded close in a dead
    room drops off a cliff — better than 22dB — because there is nothing left
    once the mouth stops. A live room keeps answering, and lands nearer 12.
    """
    sm = _mean(env, SMOOTH)
    edge = peak - 10.0
    drops = []
    for i in range(len(sm) - 11):
        if sm[i] > edge >= sm[i + 1]:
            drops.append(sm[i] - min(sm[i + 1:i + 11]))
    if not drops:
        return 0.0
    drops.sort()
    return drops[len(drops) // 2]


def analyse(path: Path) -> dict:
    """Measure one test recording and say, in words, what is wrong with it."""
    env = _levels(path)
    span = speech_span(env)
    if span is None:
        return {"ok": False, "notes": ["Nothing but room tone in that recording — "
                                       "is the right microphone selected?"]}
    inside = env[int(span.start / FRAME):int(span.end / FRAME) + 1] or env
    # The floor *inside* the speech is the room answering back; the floor
    # outside it is only how quiet the room is when nobody is talking.
    between = _pct(sorted(inside), 0.10)
    contrast = span.peak - between
    decay = _offset_decay(env, span.peak)
    tp = _true_peak(path)

    # One number for the room, off the two measurements, each scaled between
    # what a bad desk mic in a bare room reads and what a close mic in a
    # treated one reads. Nothing here is a guess about your gear: both ends
    # were set from real takes.
    score = max(0.0, min(100.0, (contrast - 25.0) / 20.0 * 50.0
                                + (decay - 12.0) / 12.0 * 50.0))
    verdict = ("dry" if score >= 70 else "controlled" if score >= 50
               else "live" if score >= 30 else "echoey")

    notes: list[str] = []
    if verdict in ("live", "echoey"):
        notes.append(
            f"The room is answering you back — your voice only pulls {contrast:.0f}dB "
            f"clear of its own reflections, and falls {decay:.0f}dB in the 200ms "
            "after each word. Get closer to the mic than feels natural (a hand's "
            "width), put something soft behind you, and keep the mic off the desk "
            "surface. De-room below will take the rest.")
    if tp > -3.0:
        notes.append(f"Peaks are hitting {tp:.1f}dBFS — close to clipping. "
                     "Turn the input gain down a notch; loudness is set here, "
                     "not at the microphone.")
    elif span.peak < -34.0:
        notes.append(f"The read is quiet ({span.peak:.0f}dBFS). It will still "
                     "normalise, but bringing the gain up leaves less room tone "
                     "to lift with it.")
    if span.floor > -48.0:
        notes.append(f"The room itself is loud at {span.floor:.0f}dBFS — a fan, "
                     "a fridge or the computer. Denoise handles a steady one, "
                     "but it is cheaper to switch it off.")
    if not notes:
        notes.append("Nothing to fix — this is a good place to read in.")

    return {
        "ok": True,
        "speech_db": round(span.peak, 1),
        "room_db": round(span.floor, 1),
        "peak_db": round(tp, 1),
        "contrast": round(contrast, 1),
        "decay": round(decay, 1),
        "verdict": verdict,
        "room_score": round(score),
        "duration": round(span.end - span.start, 2),
        "notes": notes,
    }


def audit_takes(project: Project, root: Path) -> tuple[list[str], bool]:
    """Check every take on disk still matches what the project believes.

    Returns the problems worth stopping for, and whether any duration was
    quietly corrected. The picture timeline is built from these numbers, so a
    take that no longer matches its metadata is a desync waiting to happen.
    """
    problems: list[str] = []
    repaired = False
    for n, s in enumerate(project.slides, 1):
        take = s.take or {}
        if not take.get("path"):
            continue
        path = root / take["path"]
        if not path.exists():
            problems.append(f"paragraph {n}: the take file is missing")
            continue
        try:
            real = float(ffutil.duration(path))
        except Exception:
            real = 0.0
        if real < 0.25:
            problems.append(f"paragraph {n}: the take is empty — re-record it")
            continue
        if abs(real - float(take.get("duration") or 0.0)) > 0.05:
            take["duration"] = round(real, 3)
            repaired = True
    return problems, repaired


def slide_durations(project: Project) -> list[tuple[str, float]]:
    """Screen time per slide: the take plus the pause that follows it."""
    gaps = gap_map(project)
    out = []
    for s in project.slides:
        take = s.take or {}
        d = float(take.get("duration") or 0.0)
        if d <= 0:
            continue
        out.append((s.id, round(d + gaps.get(s.id, PARAGRAPH_GAP), 3)))
    return out


def build_narration(project: Project, out_path: Path, lead_in: float,
                    fill: dict[str, float] | None = None) -> float:
    """Concatenate every take into one continuous narration bed.

    `lead_in` is silence before the first word, which lets the opening image and
    the first crossfade breathe. Returns the total duration. `fill` maps a slide
    id to the seconds of silence to leave for a paragraph with no take, which is
    how the timeline preview keeps unrecorded paragraphs in their place.
    """
    return _concat_takes(project, project.slides, out_path,
                         head=lead_in + HEAD_PAD, tail=TAIL_PAD, fill=fill)


def build_slice(project: Project, slides: list, out_path: Path,
                head: float) -> float:
    """The takes for `slides` alone, as one bed starting `head` seconds in.

    What the in-app segment preview plays under one picture. `head` is the
    whole delay before the first word rather than a lead-in on top of
    `HEAD_PAD`: a slice lands wherever in the cut its segment starts, which is
    not the top of the video and so carries none of the opening padding.
    """
    return _concat_takes(project, slides, out_path, head=head, tail=0.0)


def _concat_takes(project: Project, slides: list, out_path: Path,
                  head: float, tail: float,
                  fill: dict[str, float] | None = None) -> float:
    from .store import project_dir

    root = project_dir(project.id)
    wanted = {s.id for s in slides}
    fill = fill or {}
    takes = [(s, s.take if (s.take and s.take.get("path")) else None) for s in project.slides
             if s.id in wanted and ((s.take and s.take.get("path")) or s.id in fill)]
    if not takes:
        raise ValueError("Nothing recorded yet.")

    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    gaps = gap_map(project)

    for i, (slide, take) in enumerate(takes):
        if take:
            inputs += ["-i", str(root / take["path"])]
        else:
            inputs += ["-f", "lavfi", "-t", f"{max(0.1, fill[slide.id]):.3f}",
                       "-i", "anullsrc=r=48000:cl=mono"]
        pad_before = head if i == 0 else 0.0
        # The pause after each take is the one the picture timing also uses; the
        # last take additionally carries the music-only outro.
        pad_after = (gaps.get(slide.id, PARAGRAPH_GAP)
                     + (tail if i == len(takes) - 1 else 0.0))
        pre = f"adelay={int(pad_before * 1000)}|{int(pad_before * 1000)}," if pad_before else ""
        filters.append(
            f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono,"
            f"{pre}apad=pad_dur={pad_after}[a{i}]"
        )
        labels.append(f"[a{i}]")

    graph = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    ffutil.run([*inputs, "-filter_complex", graph, "-map", "[out]",
                "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out_path)])
    return ffutil.duration(out_path)

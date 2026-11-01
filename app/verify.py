"""Report problems in a finished encode with one probe and one analysis pass."""
from __future__ import annotations

import re
from pathlib import Path

from . import ffutil
from .schema import FrameSpec

_NUMBER = r"[-+]?\d+(?:\.\d+)?"


def run(path: str | Path, story: dict | None = None,
        frame: FrameSpec | None = None) -> dict:
    """`story` has segments with absolute `word_times` on their paragraphs.

    An arbitrary file needs no story. Bitrate is a P2 heuristic: the floor is
    1 Mbps at 720p, scaled by pixel count (250 kbps minimum).
    Findings never decide whether an encode can be used.
    """
    info = ffutil.probe(path)
    streams = info.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    fmt = info.get("format", {})
    duration = float(fmt.get("duration") or 0)
    findings = []

    def add(severity, kind, t, detail):
        findings.append(dict(severity=severity, kind=kind,
                             t=round(max(0.0, t), 3), detail=detail))

    args = ["-threads", "2", "-filter_threads", "2", "-i", str(path)]
    if video:
        args += ["-map", "0:v:0", "-vf", "blackdetect=d=0.3:pix_th=0.10"]
    if audio:
        args += ["-map", "0:a:0", "-af",
                 "ebur128=framelog=verbose,silencedetect=n=-50dB:d=1.5"]
    _, log = ffutil.capture([*args, "-f", "null", "-"])

    for start, end in re.findall(
            rf"black_start:({_NUMBER})\s+black_end:({_NUMBER})", log):
        start, end = float(start), float(end)
        # Fades in and out and dips through black between sections (2 x DIP)
        # are deliberate and stay under a second.
        if end - start < 1.0 - 1e-6:
            continue
        level = "P0" if start <= 0.001 or end >= duration - 2 else "P1"
        add(level, "black_run", start, f"Black from {start:.3f}s to {end:.3f}s")

    if video and audio and video.get("duration") and audio.get("duration"):
        delta = abs(float(video["duration"]) - float(audio["duration"]))
        if delta > 0.1 + 1e-6:
            add("P0", "av_delta", min(float(video["duration"]), float(audio["duration"])),
                f"Audio/video durations differ by {delta:.3f}s")

    if video:
        bitrate = float(video.get("bit_rate") or fmt.get("bit_rate") or 0)
        floor = max(250_000, 1_000_000 * int(video.get("width") or 0)
                    * int(video.get("height") or 0) / (1280 * 720))
        # A cut of still pictures compresses far below this, so it is a hint.
        if bitrate and bitrate < floor:
            add("P2", "bitrate_low", 0,
                f"Video bitrate {bitrate / 1000:.0f} kbps; floor {floor / 1000:.0f} kbps")

    loudness = re.findall(rf"\bI:\s*({_NUMBER}|-inf)\s+LUFS", log)
    measured = float(loudness[-1]) if loudness else None
    target = (frame or FrameSpec()).voice_lufs
    if measured is not None and abs(measured - target) > 2:
        add("P1", "loudness_off", 0,
            f"Integrated loudness {measured:g} LUFS; target {target:g} LUFS")

    # A silence_end at EOF still describes a silent tail. Interior pauses do not.
    events = re.findall(rf"silence_(start|end):\s*({_NUMBER})", log)
    silence_start = None
    audio_end = float((audio or {}).get("duration") or duration)
    for kind, value in events:
        value = float(value)
        if kind == "start":
            silence_start = value
        elif value < audio_end - 0.05:
            silence_start = None
    if silence_start is not None and duration - silence_start > 1.5:
        add("P1", "silent_tail", silence_start,
            f"Silent tail lasts {duration - silence_start:.3f}s")

    for seg in (story or {}).get("segments", []):
        edges = (seg["start"], seg["start"] + seg["duration"])
        for para in seg.get("paragraphs", []):
            words = para.get("word_times", [])
            if not words:
                continue
            for word, key in ((words[0], "start"), (words[-1], "end")):
                t = word[key]
                if min(abs(t - edge) for edge in edges) <= 0.05 + 1e-6:
                    add("P2" if word.get("src", "est") == "est" else "P1",
                        "clipped_word", t,
                        f"Paragraph {para['id']} {key} word is within 0.05s of a segment edge")

    findings.sort(key=lambda f: (f["t"], f["severity"], f["kind"]))
    return {"findings": findings,
            "counts": {level: sum(f["severity"] == level for f in findings)
                       for level in ("P0", "P1", "P2")},
            "duration": duration, "loudness_lufs": measured if measured != float('-inf') else None}

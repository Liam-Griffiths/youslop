"""Thin ffmpeg/ffprobe wrappers.

Everything that runs ffmpeg goes through here, including the raw-frame pipes
the generated animations use. That matters more than tidiness: the binary is
resolved in exactly one place (`config._binary`, bundled copy first), and an
app launched from the Finder inherits a PATH that has no Homebrew in it, so a
second place constructing its own argv would be a second thing to find out
about the hard way.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable

from .config import FFMPEG, FFPROBE, FPS, HEIGHT, WIDTH


class FFError(RuntimeError):
    pass


def run(args: list[str], timeout: int = 3600) -> str:
    """Run ffmpeg with the noisy banner off, raising with the real error tail."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise FFError("ffmpeg failed:\n" + "\n".join(tail[-12:]))
    return proc.stderr


def capture(args: list[str], timeout: int = 3600) -> tuple[str, str]:
    """Run ffmpeg for what it reports rather than what it writes.

    Filters that report — astats, loudnorm — print to stdout and to the log at
    info level, which `run` deliberately silences, so analysis passes come
    through here instead.
    """
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "info", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        raise FFError("ffmpeg failed:\n" + "\n".join(tail[-12:]))
    return proc.stdout, proc.stderr


# ----------------------------------------------------------- frame pipes
# Pillow composes the generated slates, maps, diagrams and boards frame by
# frame; ffmpeg takes them as raw RGB on stdin. Streamed, never buffered as a
# whole clip — a three minute board at 1080p would be nine gigabytes.
def frame_pipe(out_path: Path, *, size: tuple[int, int] = (WIDTH, HEIGHT),
               fps: int = FPS, crf: int = 17,
               extra: Iterable[str] = ()) -> subprocess.Popen:
    """An ffmpeg process waiting for raw RGB frames on stdin."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
         "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-an", *extra, str(out_path)],
        stdin=subprocess.PIPE,
    )


def encode_frames(frames: Iterable, out_path: Path, **kw) -> int:
    """Write an iterable of Pillow images to `out_path`. Returns the count.

    A broken pipe is swallowed on purpose: ffmpeg exiting early (a full disk,
    a bad argument) closes stdin, and the useful error is its exit code, not
    the write that happened to notice first.
    """
    proc = frame_pipe(out_path, **kw)
    n = 0
    try:
        for frame in frames:
            proc.stdin.write(frame.tobytes())
            n += 1
        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        code = proc.wait()
    return n if code == 0 else 0


def probe(path: str | Path) -> dict:
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFError(f"ffprobe failed on {path}: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout)


def duration(path: str | Path) -> float:
    info = probe(path)
    d = (info.get("format") or {}).get("duration")
    if d:
        return float(d)
    for st in info.get("streams", []):
        if st.get("duration"):
            return float(st["duration"])
    return 0.0


def dimensions(path: str | Path) -> tuple[int, int]:
    for st in probe(path).get("streams", []):
        if st.get("codec_type") == "video":
            return int(st.get("width") or 0), int(st.get("height") or 0)
    return 0, 0


def has_audio(path: str | Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))

"""Thin ffmpeg/ffprobe wrappers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import FFMPEG, FFPROBE


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

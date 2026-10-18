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
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterable

from .config import FFMPEG, FFPROBE, FPS, HEIGHT, WIDTH


class FFError(RuntimeError):
    pass


# ffmpeg's decode, encode and filtergraph threading all independently default
# to "auto" — and "auto" does not mean "one pool shared sensibly," it means
# each of the three picks its own thread count against the whole machine. A
# segment with a dozen caption overlays chains a few dozen filter nodes on top
# of that, and the measured result on a 16-core machine was upwards of 400
# threads for *one* ffmpeg process. Six of those running at once — one per
# parallel segment worker — is what turns a render into a system-wide
# memory-thrashing stall rather than six times faster.
#
# The CLI flags (`-threads`, `-filter_threads`, `-filter_complex_threads`)
# only ever cut that thread count by about half, though — the bulk of it, and
# nearly all of the actual memory (measured at several GB of RSS per process),
# turned out to be an OpenMP thread pool inside the bundled ffmpeg's own image
# decoding, spun up once per `-loop 1 -i some.png` input and sized to every
# core by default regardless of any ffmpeg flag. `OMP_NUM_THREADS` is the only
# thing that reaches it — setting it (and the handful of other libraries that
# honour the same convention) alongside the CLI flags was what actually took
# one process from ~3.5GB of RSS down to under 200MB.
_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
)


def _default_threads() -> int:
    return max(1, min(4, os.cpu_count() or 4))


def run(args: list[str], timeout: int = 3600, threads: int = 0) -> str:
    """Run ffmpeg with the noisy banner off, raising with the real error tail.

    `threads` caps decode, encode and filter-graph threading together — pass
    it explicitly whenever more than one ffmpeg may run at once (see
    `render.py`'s segment pool), since "auto" threading assumes it owns the
    whole machine. 0 (the default) still applies a low cap rather than true
    "auto", because even a single such process was measured oversubscribing
    the machine on its own.
    """
    n = str(threads) if threads > 0 else str(_default_threads())
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if "-threads" not in args:
        cmd += ["-threads", n]
    if "-filter_threads" not in args:
        cmd += ["-filter_threads", n]
    if "-filter_complex" in args and "-filter_complex_threads" not in args:
        cmd += ["-filter_complex_threads", n]
    cmd += args
    env = {**os.environ, **{v: n for v in _THREAD_ENV_VARS}}
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
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


# ------------------------------------------------------------ codec choice
# What a file is encoded with follows from what has to play it, and there are
# two different answers.
#
# A finished render is for YouTube, so it is H.264 and AAC in mp4 — the only
# pair every platform, player and uploader agrees on.
#
# A *preview* is only ever played in this app's own window. On Linux that
# window is WebKitGTK decoding through GStreamer, and a desktop with only
# gst-plugins-base and -good installed — which is most of them, including the
# packages this project's own README used to list — has no H.264 or AAC
# decoder at all: `avdec_h264` ships in gst-libav, which nothing pulls in by
# default. The result is a broken play button on a perfectly good file. VP9
# and Opus in WebM decode with what is already there (`vp9dec` and `opusdec`
# are in -good and -base), and measured at preview sizes they cost the same
# as x264: 0.6s against 0.5s for a 5s 1080p slate, at half the file size.
#
# So: a preview path simply ends in `.webm` and gets VP9/Opus; everything
# else gets H.264/AAC. Nothing else in the codebase has to know.
VP9_SPEED = ("-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1")
# VP9's quality scale runs further than x264's for the same picture, so a
# CRF written for x264 is shifted rather than passed through.
VP9_CRF_SHIFT = 6


def is_preview(out_path: str | Path) -> bool:
    return Path(out_path).suffix.lower() == ".webm"


def video_args(out_path: str | Path, *, crf: int = 18,
               preset: str = "veryfast") -> list[str]:
    """How to encode the video of `out_path`, decided by its extension."""
    if is_preview(out_path):
        return ["-c:v", "libvpx-vp9", *VP9_SPEED,
                "-crf", str(min(63, crf + VP9_CRF_SHIFT)), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]


def audio_args(out_path: str | Path, *, bitrate: str = "128k") -> list[str]:
    """How to encode the audio of `out_path`, decided by its extension."""
    if is_preview(out_path):
        return ["-c:a", "libopus", "-b:a", bitrate]
    return ["-c:a", "aac", "-b:a", bitrate]


# ---------------------------------------------------------- GPU encoding
# The finished cut, and every drawn segment on the way to it, can be encoded
# on the graphics chip instead of the CPU: VA-API on Linux (AMD and Intel),
# NVENC on an NVIDIA card, VideoToolbox on a Mac. Drawing the frames stays on
# the CPU either way — the gain is that the encode stops competing with it.
#
# Chosen in Settings ("Video encoder"): auto uses the GPU when one answers a
# test encode, cpu never does, gpu insists (and still falls back, loudly,
# rather than fail a render). A test encode rather than a list of encoders:
# the bundled ffmpeg lists all of them on every machine, and listed is not
# the same as working.
_HW_LOCK = threading.Lock()
_HW: dict = {}           # "probe" -> the working encoder or None; "broken" -> bool


def encoder_mode() -> str:
    """auto, cpu or gpu — read on every call, so Settings applies at once."""
    v = os.environ.get("YOUSLOP_ENCODER", "").strip().lower()
    if not v:
        try:
            from . import settings as settings_mod
            v = settings_mod.load_file().get("video_encoder", "").strip().lower()
        except Exception:
            v = ""
    return v if v in ("auto", "cpu", "gpu") else "auto"


def _candidates() -> list[dict]:
    """Hardware H.264 encoders worth trying here, best first. Each says what
    goes before the inputs, what the last filter must end with, and the codec
    arguments for a given x264 CRF."""
    out = []
    if sys.platform == "darwin":
        out.append({"name": "h264_videotoolbox", "label": "Apple VideoToolbox",
                    "pre": [], "vf": "", "pix_fmt": True,
                    # q:v is 1-100, higher is better; ~64 matches CRF 18.
                    "args": lambda crf: ["-c:v", "h264_videotoolbox", "-q:v",
                                         str(max(30, min(90, 100 - crf * 2))),
                                         "-allow_sw", "0", "-profile:v", "high"]})
        return out
    out.append({"name": "h264_nvenc", "label": "NVIDIA NVENC",
                "pre": [], "vf": "", "pix_fmt": True,
                "args": lambda crf: ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                                     "-cq", str(crf + 1), "-b:v", "0", "-profile:v", "high"]})
    for node in sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []:
        out.append({"name": "h264_vaapi", "label": f"VA-API ({node.name})",
                    "pre": ["-vaapi_device", str(node)], "vf": "format=nv12,hwupload",
                    "pix_fmt": False,
                    "args": lambda crf: ["-c:v", "h264_vaapi", "-rc_mode", "CQP",
                                         "-qp", str(crf + 1), "-profile:v", "high"]})
    return out


def _try(enc: dict) -> bool:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "probe.mp4"
        vf = ["-vf", enc["vf"]] if enc["vf"] else []
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               *enc["pre"], "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30", "-t", "0.5",
               *vf, *enc["args"](20), *(["-pix_fmt", "yuv420p"] if enc["pix_fmt"] else []),
               str(out)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0 and out.exists() and out.stat().st_size > 1000


def gpu_encoder() -> dict | None:
    """The first hardware encoder that survives a test encode, or None."""
    with _HW_LOCK:
        if "probe" not in _HW:
            _HW["probe"] = next((e for e in _candidates() if _try(e)), None)
        return _HW["probe"]


def gpu_status() -> dict:
    enc = gpu_encoder()
    return {"mode": encoder_mode(), "available": bool(enc),
            "encoder": enc["label"] if enc else "",
            "active": bool(enc) and encoder_mode() != "cpu" and not _HW.get("broken")}


def gpu_failed(why: str = "") -> None:
    """A hardware encode failed for real: use the CPU for the rest of this run
    of the app rather than failing the next one the same way."""
    _HW["broken"] = True
    _HW["why"] = why[-300:]


def _use_gpu(out_path: str | Path) -> dict | None:
    if is_preview(out_path) or encoder_mode() == "cpu" or _HW.get("broken"):
        return None
    return gpu_encoder()


def h264(out_path: str | Path, *, crf: int = 18, preset: str = "veryfast",
         gpu: bool = True) -> tuple[list[str], str, list[str]]:
    """How to encode `out_path` as H.264: (before the inputs, the filter the
    picture must finish with, the codec arguments). The CPU path is x264 with
    `-pix_fmt yuv420p`; a GPU path brings its own device and pixel format."""
    enc = _use_gpu(out_path) if gpu else None
    if enc is None:
        return [], "", [*video_args(out_path, crf=crf, preset=preset), "-pix_fmt", "yuv420p"]
    return (list(enc["pre"]), enc["vf"],
            [*enc["args"](crf), *(["-pix_fmt", "yuv420p"] if enc["pix_fmt"] else [])])


# ----------------------------------------------------------- frame pipes
# Pillow composes the generated slates, maps, diagrams and boards frame by
# frame; ffmpeg takes them as raw RGB on stdin. Streamed, never buffered as a
# whole clip — a three minute board at 1080p would be nine gigabytes.
def frame_pipe(out_path: Path, *, size: tuple[int, int] = (WIDTH, HEIGHT),
               fps: int = FPS, crf: int = 17,
               extra: Iterable[str] = (), gpu: bool = False) -> subprocess.Popen:
    """An ffmpeg process waiting for raw RGB frames on stdin.

    `gpu` lets the encode go to the graphics chip when Settings allows it;
    only `encode_frames` asks for that, because only it knows how to start
    again on the CPU if the GPU refuses."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pre, vf, codec = h264(out_path, crf=crf, gpu=gpu) if not is_preview(out_path) else (
        [], "", [*video_args(out_path, crf=crf), "-pix_fmt", "yuv420p"])
    extra = list(extra)
    if vf:
        # The upload to the GPU has to be the picture's last step, after any
        # scale the caller asked for.
        if "-vf" in extra:
            at = extra.index("-vf") + 1
            extra[at] = f"{extra[at]},{vf}"
        else:
            extra = ["-vf", vf, *extra]
    return subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *pre,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
         "-r", str(fps), "-i", "-",
         *codec, "-an", *extra, str(out_path)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE if gpu else None,
    )


def encode_frames(frames: Iterable, out_path: Path, **kw) -> int:
    """Write an iterable of Pillow images to `out_path`. Returns the count.

    A broken pipe is swallowed on purpose: ffmpeg exiting early (a full disk,
    a bad argument) closes stdin, and the useful error is its exit code, not
    the write that happened to notice first.

    The encode goes to the GPU when Settings allows. The first few frames are
    held back until it has taken them: a GPU encoder that is going to refuse
    (a missing driver, a busy device) does so on its first frames, and then
    it is dropped for the rest of the session and the same frames go to the
    CPU instead, with nothing lost.
    """
    import itertools
    it = iter(frames)
    head = list(itertools.islice(it, HELD_FRAMES))
    if not head:
        return 0

    def attempt(gpu: bool) -> tuple[int, int, bytes]:
        proc = frame_pipe(out_path, gpu=gpu, **kw)
        n = 0
        try:
            try:
                for frame in head:
                    proc.stdin.write(frame.tobytes())
                    n += 1
                if not (gpu and n < len(head)):
                    for frame in it:
                        proc.stdin.write(frame.tobytes())
                        n += 1
                proc.stdin.close()
            except BrokenPipeError:
                pass
        finally:
            err = proc.stderr.read() if proc.stderr else b""
            code = proc.wait()
        return code, n, err

    gpu = _use_gpu(out_path) is not None
    code, n, err = attempt(gpu)
    if code == 0:
        return n
    if gpu and n <= len(head):
        gpu_failed(err.decode(errors="replace"))
        code, n, _ = attempt(False)
        return n if code == 0 else 0
    return 0


HELD_FRAMES = 4


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

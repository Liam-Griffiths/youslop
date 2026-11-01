"""Camera picture and cleaned voice, both cut from the same detected span."""
import logging
from fractions import Fraction
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

from . import audio, ffutil
from .schema import Voice

TAIL_S = 2.5


def suggest_cuts(take) -> list[dict]:
    """Internal pauses only, on the cleaned take's original clock."""
    from .take_edits import cut_ranges
    # Callers resolve relative paths against the project before invoking this.
    env = audio._levels(Path(take['path']))
    span = audio.speech_span(env)
    if not span:
        return []
    threshold = span.floor + (span.peak - span.floor) * .35
    from .words import _runs
    runs = _runs(env, threshold)
    removed = cut_ranges(take)
    return [{'a': round(b + .15, 6), 'b': round(c - .15, 6)}
            for (_, b), (c, _) in zip(runs, runs[1:])
            if c - b > .6 and b >= span.start and c <= span.end
            and not any(a < c - .15 and end > b + .15 for a, end in removed)]


def measure(path: Path) -> dict:
    """One 1 fps ffmpeg pass; clipping is measured before any resizing."""
    with TemporaryDirectory(prefix="corkbored-camera-stats-") as folder:
        stats, clipped = Path(folder) / "stats", Path(folder) / "clipped"
        graph = ("[0:v:0]fps=1:round=up,format=yuv444p,split[a][b];"
                 f"[a]signalstats,metadata=print:file={stats}[s];"
                 "[b]lut=y='if(gt(val,250),255,0)':u=128:v=128,"
                 f"signalstats,metadata=print:file={clipped}[c]")
        ffutil.run(["-i", str(path), "-filter_complex", graph,
                    "-map", "[s]", "-map", "[c]", "-an", "-f", "null", "-"], threads=1)
        def average(file, key):
            values = [float(line.split("=", 1)[1]) for line in file.read_text().splitlines()
                      if line.startswith(f"lavfi.signalstats.{key}=")]
            if not values:
                raise ValueError("No camera measurement samples")
            return sum(values) / len(values)
        return {**{key: average(stats, key) for key in ("YAVG", "UAVG", "VAVG")},
                "clipped": average(clipped, "YAVG") / 255}


def target(project) -> float:
    values = [(project.active_take(s) or {}).get("measure", {}).get("YAVG")
              for s in project.slides if s.on_camera]
    return median(v for v in values if v is not None) if any(v is not None for v in values) else 110.0


def correction(take, luma_target=110.0) -> tuple[float, list[float]]:
    """Bounded exposure and RGB cast offsets, shared by render and checks."""
    stats = take.get("measure", {})
    if take.get("look", "auto") == "as_shot" or "YAVG" not in stats:
        return 0.0, [0.0] * 3
    cap = lambda v, limit: max(-limit, min(limit, v))
    brightness = cap((luma_target - stats["YAVG"]) / 255, .06)
    u, v = stats.get("UAVG", 128) - 128, stats.get("VAVG", 128) - 128
    rgb = [-1.402 * v / 255, (.344 * u + .714 * v) / 255, -1.772 * u / 255]
    return brightness, [cap(x, .025) for x in rgb]


def correction_filter(take, luma_target=110.0) -> str:
    brightness, rgb = correction(take, luma_target)
    if not brightness and not any(rgb):
        return ""
    balance = ":".join(f"{c}{zone}={v:.6f}" for c, v in zip("rgb", rgb) for zone in "smh")
    return (f"eq=brightness={brightness:.6f}:contrast=1"
            + (f",colorbalance={balance}:pl=1" if any(rgb) else ""))


def process_camera_take(raw: Path, out_wav: Path, out_mp4: Path,
                        voice: Voice | None = None) -> dict:
    """Clean the voice, keeping up to TAIL_S of trailing picture for the gap.

    Outputs must be fresh paths. The raw recording is never modified.
    trimmed remains audio-relative; video_start is relative to the video stream.
    """
    if out_wav.exists() or out_mp4.exists():
        raise ValueError("Camera outputs must be fresh paths")
    info = ffutil.probe(raw)
    streams = info.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    sound = next((s for s in streams if s["codec_type"] == "audio"), None)
    if not video or not sound:
        raise ValueError("A camera take needs both video and audio")
    if int(video.get("width", 0)) < 640:
        raise ValueError("Camera footage must be at least 640 pixels wide")
    offset = float(sound.get("start_time") or 0) - float(video.get("start_time") or 0)
    logging.getLogger(__name__).info("Camera audio minus video start: %.3f s", offset)
    with TemporaryDirectory(prefix="corkbored-camera-") as folder:
        extracted = Path(folder) / "audio.wav"
        ffutil.run(["-i", str(raw), "-map", "0:a:0", "-vn", "-ac", "1",
                    "-ar", "48000", "-c:a", "pcm_s16le", str(extracted)])
        meta = audio.process_take(extracted, out_wav, voice)
    start, end = meta["trimmed"]
    video_start = start + offset
    if video_start < 0:
        raise ValueError("The first spoken audio precedes the camera picture")
    # Stream duration is relative to its own start, unlike format.duration.
    fmt_duration = (info.get("format") or {}).get("duration")
    if video.get("duration"):
        video_duration = float(video["duration"])
    elif fmt_duration:
        video_duration = float(fmt_duration) - float(video.get("start_time") or 0)
    else:
        # Browser recordings carry no duration at all; read the packets.
        video_duration = ffutil.stream_end(raw, "v") - float(video.get("start_time") or 0)
    if end + offset > video_duration + 1 / 30:
        raise ValueError("The camera picture ends before the spoken audio")
    tail = max(0.0, min(TAIL_S, video_duration - end - offset))
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    # Reset to video-relative timestamps before the accurate output seek.
    ffutil.run(["-i", str(raw), "-ss", str(video_start),
                "-t", str(end - start + tail), "-map", "0:v:0",
                "-vf", "setpts=PTS-STARTPTS,fps=30", "-an",
                "-c:v", "libx264", "-crf", "16", "-preset", "veryfast",
                "-g", "30", "-pix_fmt", "yuv420p", str(out_mp4)])
    result = next(s for s in ffutil.probe(out_mp4)["streams"] if s["codec_type"] == "video")
    return {**meta, "tail": round(tail, 6), "width": result["width"],
            "height": result["height"], "fps": float(Fraction(result["avg_frame_rate"])),
            "kind": "camera", "av_offset": round(offset, 6),
            "sync_warning": abs(offset) > 0.1, "sync_corrected": True,
            "video_start": round(video_start, 6), "measure": measure(out_mp4)}

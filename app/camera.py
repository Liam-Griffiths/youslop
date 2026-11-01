"""Camera picture and cleaned voice, both cut from the same detected span."""
import logging
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from . import audio, ffutil
from .schema import Voice

TAIL_S = 2.5


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
            "sync_warning": abs(offset) > 0.1, "video_start": round(video_start, 6)}

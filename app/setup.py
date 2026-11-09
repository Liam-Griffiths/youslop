"""Read-only first-run checks. Never starts a model, browser or download."""
import sys

from . import config, llm, paths, settings, stage, stt, sysinfo, tts, youtube


def ffmpeg_check():
    # Version only: no encode, media reads, or renderer probes.
    return config.ffmpeg_ready()


def checks() -> dict:
    ffmpeg_ok, ffmpeg_detail = ffmpeg_check()
    chromium_ok, chromium_detail = stage.available()
    root = paths.data_root()
    channel_ids = [p.parent.name for p in (root / "channels").glob("*/channel.json")]
    return {
        "needed": settings.setup_needed(),
        "ffmpeg": {"ready": ffmpeg_ok, "detail": ffmpeg_detail},
        "chromium": {"ready": chromium_ok, "detail": chromium_detail,
                     "path": stage.browser()},
        "llm": llm.backend_status(),
        "tts": tts.status(),
        "stt": stt.setup_status(refresh=True),
        "paths": paths.describe(),
        # macOS's helper runs two subprocesses; keep this endpoint cheap.
        "system": {"available_ram_mb": sysinfo.available_mb() if sys.platform != "darwin" else None,
                   "gpu": None},
        "youtube": {"available": youtube.available(),
                    "connected": any(youtube.status(cid)["connected"] for cid in channel_ids)},
    }

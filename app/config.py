"""Global paths, tunables and environment wiring."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT / "projects"
CHANNELS_DIR = ROOT / "channels"
STATIC_DIR = ROOT / "static"
MUSIC_DIR = ROOT / "assets" / "music"
TTS_DIR = ROOT / "assets" / "tts"
LIBRARY_DIR = ROOT / "assets" / "library"
CACHE_DIR = ROOT / ".cache"

for _d in (PROJECTS_DIR, CHANNELS_DIR, MUSIC_DIR, TTS_DIR,
           LIBRARY_DIR / "files", LIBRARY_DIR / "thumbs", CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_dotenv()

# ---------------------------------------------------------------- binaries
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"

# ---------------------------------------------------------------- models
# Routed through the local Claude Code CLI, so these are aliases not API ids.
MODEL_SCRIPT = os.environ.get("VB_MODEL_SCRIPT", "opus")
MODEL_UTILITY = os.environ.get("VB_MODEL_UTILITY", "sonnet")

# ---------------------------------------------------------------- api keys
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
STORYBLOCKS_PUBLIC = os.environ.get("STORYBLOCKS_PUBLIC_KEY", "")
STORYBLOCKS_SECRET = os.environ.get("STORYBLOCKS_SECRET_KEY", "")

# A local SearXNG instance (see docker-compose.searxng.yml) the research step
# searches before writing a script. No key: it's your own instance, not a
# metered API. "" disables research grounding — the writer falls back to its
# own hedging instructions, same as before this existed.
SEARXNG_URL = os.environ.get("SEARXNG_URL", "").rstrip("/")

# A Google Cloud "Desktop app" OAuth client, for publishing a rendered video
# straight to YouTube. "" disables the feature entirely — the channel page's
# YouTube panel just says so rather than offering a connect button that would
# fail. See the README for the two-minute Cloud Console setup.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

USER_AGENT = os.environ.get(
    "VB_USER_AGENT",
    "youslop/1.0 (local research tool; contact: set VB_USER_AGENT)",
)

# ---------------------------------------------------------------- narration
# Kokoro runs locally: no key, no request, nothing leaves the machine. The two
# files are a one-off download; see the README.
KOKORO_MODEL = TTS_DIR / os.environ.get("VB_KOKORO_MODEL", "kokoro-v1.0.onnx")
KOKORO_VOICES = TTS_DIR / os.environ.get("VB_KOKORO_VOICES", "voices-v1.0.bin")

# ---------------------------------------------------------------- video
WIDTH, HEIGHT, FPS = 1920, 1080, 30
WORDS_PER_MINUTE = 158          # measured narration pace for documentary reads
PARAGRAPH_GAP = 0.35            # silence appended after each recorded take
HEAD_PAD = 0.6                  # silence before the first word
TAIL_PAD = 1.8                  # music-only outro after the last word

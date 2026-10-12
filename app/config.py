"""Global paths, tunables and environment wiring."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .paths import SOURCE_ROOT, data_root, resource_root

# Kept for anything that still reaches for it; `DATA` and `RESOURCES` are the
# two that actually matter. See app/paths.py for why they are not the same.
ROOT = SOURCE_ROOT
RESOURCES = resource_root()
DATA = data_root()

# Read-only, shipped with the program.
STATIC_DIR = RESOURCES / "static"
FONTS_DIR = RESOURCES / "resources" / "fonts"

# Written to, belongs to the creator.
PROJECTS_DIR = DATA / "projects"
CHANNELS_DIR = DATA / "channels"
MUSIC_DIR = DATA / "assets" / "music"
TTS_DIR = DATA / "assets" / "tts"
LIBRARY_DIR = DATA / "assets" / "library"
CACHE_DIR = DATA / ".cache"
LOG_DIR = DATA / "logs"

WRITABLE_DIRS = (PROJECTS_DIR, CHANNELS_DIR, MUSIC_DIR, TTS_DIR,
                 LIBRARY_DIR / "files", LIBRARY_DIR / "thumbs", CACHE_DIR, LOG_DIR)


def ensure_dirs() -> None:
    """Create the data folders. Called at startup, never at import.

    At import it would run inside a read-only application bundle — or in any
    process that merely imports this module to read a constant — and raise
    before anything had a chance to report it properly.
    """
    for d in WRITABLE_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def _read_dotenv_file(env: Path) -> dict[str, str]:
    """One .env-shaped file, parsed into a plain dict — no writes to os.environ
    here, so the caller can control precedence against other sources."""
    out: dict[str, str] = {}
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _load_environment() -> None:
    """Fold the two file-based configuration sources into the process
    environment, so a real environment variable set by the shell or by
    `run.sh` always wins over either file.

    Precedence, lowest to highest: `settings.json` < `.env` < a real env var.
    `settings.json` is what an installed app's Settings page writes (see
    `app/settings.py`) — the lowest priority, since it is meant to be edited
    casually. `.env` is the development override it has always been, read
    from the data folder first so an installed copy has somewhere to put one
    at all, then the checkout, which is where it has always lived. Both are
    merged into one dict *before* touching `os.environ`, because two separate
    `setdefault` passes would get this backwards — whichever ran first would
    block the second from ever applying.
    """
    from . import settings as settings_mod

    merged: dict[str, str] = {}
    merged.update(settings_mod.environment_overrides())
    env_file = next((p for p in (DATA / ".env", ROOT / ".env") if p.exists()), None)
    if env_file is not None:
        merged.update(_read_dotenv_file(env_file))
    for k, v in merged.items():
        os.environ.setdefault(k, v)


_load_environment()

# ---------------------------------------------------------------- binaries
# Bundled copy first, then an explicit override, then whatever is on PATH.
# The order matters more than it looks: an app launched from the Finder
# inherits a PATH without /opt/homebrew/bin or /usr/local/bin, so `which`
# finds nothing on a machine where ffmpeg is plainly installed. Resolving to
# the bare name as a last resort keeps the error message recognisable.
BIN_DIR = RESOURCES / "resources" / "bin"


def _binary(name: str, override: str = "") -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    bundled = BIN_DIR / exe
    if bundled.is_file():
        return str(bundled)
    if override and Path(override).is_file():
        return override
    return shutil.which(name) or name


FFMPEG = _binary("ffmpeg", os.environ.get("YOUSLOP_FFMPEG", ""))
FFPROBE = _binary("ffprobe", os.environ.get("YOUSLOP_FFPROBE", ""))
def _find_claude_cli() -> str:
    """Where the Claude Code CLI actually is, for a process that may not have
    a real PATH.

    A GUI app launched from the Finder (or by `open`, or as an installed
    `.app`) inherits a bare system PATH — no shell profile is ever sourced —
    so `shutil.which("claude")` comes back empty even when the CLI is right
    there in `~/.local/bin`, which is exactly where most installs put it.
    Checked in the same order a user would reasonably expect: an explicit
    override, then PATH (covers a dev shell and `./run.sh`), then every
    common install location directly.
    """
    override = os.environ.get("CLAUDE_BIN", "").strip()
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for candidate in (
        home / ".local" / "bin" / "claude",
        home / ".npm-global" / "bin" / "claude",
        home / ".claude" / "local" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.is_file():
            return str(candidate)
    return "claude"      # nothing found; fails with a readable error at call time


CLAUDE_BIN = _find_claude_cli()


def ffmpeg_ready() -> tuple[bool, str]:
    """Is there a working ffmpeg? Checked at startup, not at first render.

    A render that dies forty minutes into a project because the encoder was
    never there is the worst possible moment to find out.
    """
    import subprocess
    try:
        out = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True,
                             timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run ffmpeg ({FFMPEG}): {type(exc).__name__}"
    if out.returncode != 0:
        return False, f"ffmpeg at {FFMPEG} exited {out.returncode}"
    if "libx264" not in out.stdout:
        return False, (f"The ffmpeg at {FFMPEG} was built without libx264, "
                       "which every render needs.")
    return True, out.stdout.splitlines()[0] if out.stdout else "ffmpeg ok"

# ---------------------------------------------------------------- models
# Aliases, not API ids: the CLI backend takes `--model opus`. The API backend
# (see app/llm.py) maps the same alias onto a real model id, so every caller
# in this codebase keeps writing "opus" / "sonnet" regardless of which
# backend answers it.
MODEL_SCRIPT = os.environ.get("VB_MODEL_SCRIPT", "opus")
MODEL_UTILITY = os.environ.get("VB_MODEL_UTILITY", "sonnet")

# How hard the model thinks before answering — the same five-level scale the
# `claude` CLI's own `--effort` flag and the Anthropic API's `output_config`
# both use, which is what lets one setting drive either backend identically.
# "" (the default) omits the knob entirely and takes whichever backend's own
# default applies, rather than this app silently picking one.
EFFORT = os.environ.get("YOUSLOP_EFFORT", "").strip().lower()

# ---------------------------------------------------------------- llm backend
# Two ways to reach Claude. "cli" shells out to a logged-in Claude Code CLI —
# no API key, billed to the user's subscription, and the only backend that
# existed before this. "api" calls the Anthropic Messages API directly with
# a key, for a machine that was never going to have Claude Code installed.
# "auto" (the default) picks the CLI when one is on PATH — it costs the user
# nothing extra — and falls back to the API key otherwise. See
# app/llm.py:resolve_backend().
LLM_BACKEND = os.environ.get("YOUSLOP_LLM_BACKEND", "auto").strip().lower()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

# A third, fully-local backend: an Ollama daemon on this machine, no account,
# no key, nothing leaving it — the same promise Kokoro makes for narration,
# extended to script-writing. Deliberately never chosen by `auto`: a local 7B
# model writes a noticeably worse script than Claude, and picking it silently
# because no CLI or key was found would hand someone a worse video without
# them ever deciding that tradeoff themselves. Only `YOUSLOP_LLM_BACKEND=ollama`
# selects it. See app/llm.py:_complete_ollama().
OLLAMA_URL = os.environ.get("YOUSLOP_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("YOUSLOP_OLLAMA_MODEL", "qwen2.5:7b-instruct")

# ---------------------------------------------------------------- api keys
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")

# A reaction-GIF lookup — deliberately not an archive-search provider. It is
# never part of the automatic gather for a slide, only a manual search a
# creator reaches for on purpose; see app/reactions.py for why that split
# matters. Free key from developers.giphy.com.
GIPHY_KEY = os.environ.get("GIPHY_API_KEY", "")
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

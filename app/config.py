"""Global paths, tunables and environment wiring."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import brand
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
MODELS_DIR = DATA / "assets" / "models"      # the 3D model library, see app/models3d.py
CACHE_DIR = DATA / ".cache"
LOG_DIR = DATA / "logs"

WRITABLE_DIRS = (PROJECTS_DIR, CHANNELS_DIR, MUSIC_DIR, TTS_DIR,
                 LIBRARY_DIR / "files", LIBRARY_DIR / "thumbs", MODELS_DIR, CACHE_DIR, LOG_DIR)


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

    brand.promote_legacy(os.environ)
    merged: dict[str, str] = {}
    merged.update(settings_mod.environment_overrides())
    env_file = next((p for p in (DATA / ".env", ROOT / ".env") if p.exists()), None)
    if env_file is not None:
        dot = _read_dotenv_file(env_file)
        brand.promote_legacy(dot)
        merged.update(dot)
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


FFMPEG = _binary("ffmpeg", brand.env("FFMPEG", ""))
FFPROBE = _binary("ffprobe", brand.env("FFPROBE", ""))
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
MODEL_SCRIPT = brand.env("MODEL_SCRIPT", "opus")
MODEL_UTILITY = brand.env("MODEL_UTILITY", "sonnet")

# How hard the model thinks before answering — the same five-level scale the
# `claude` CLI's own `--effort` flag and the Anthropic API's `output_config`
# both use, which is what lets one setting drive either backend identically.
# "" (the default) omits the knob entirely and takes whichever backend's own
# default applies, rather than this app silently picking one.
EFFORT = brand.env("EFFORT", "").strip().lower()

# ---------------------------------------------------------------- llm backend
# Two ways to reach Claude. "cli" shells out to a logged-in Claude Code CLI —
# no API key, billed to the user's subscription, and the only backend that
# existed before this. "api" calls the Anthropic Messages API directly with
# a key, for a machine that was never going to have Claude Code installed.
# "auto" (the default) picks the CLI when one is on PATH — it costs the user
# nothing extra — and falls back to the API key otherwise. See
# app/llm.py:resolve_backend().
LLM_BACKEND = brand.env("LLM_BACKEND", "auto").strip().lower()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

# A third, fully-local backend: an Ollama daemon on this machine, no account,
# no key, nothing leaving it — the same promise Kokoro makes for narration,
# extended to script-writing. Deliberately never chosen by `auto`: a local 7B
# model writes a noticeably worse script than Claude, and picking it silently
# because no CLI or key was found would hand someone a worse video without
# them ever deciding that tradeoff themselves. Only `CORKBORED_LLM_BACKEND=ollama`
# selects it. See app/llm.py:_complete_ollama().
OLLAMA_URL = brand.env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = brand.env("OLLAMA_MODEL", "qwen2.5:7b-instruct")
# Ollama's context window per call. Its own default is far smaller than a
# research dossier (up to ~20 sources), and it truncates silently when a prompt
# overflows, so this is always sent explicitly.
OLLAMA_CONTEXT = int(brand.env("OLLAMA_CONTEXT", "32768") or 32768)

# LM Studio (https://lmstudio.ai), the other local option, and the easier one:
# load a model in its Developer tab, start the server, choose "lmstudio" here.
# No key. Opt-in only, for the same reason as Ollama above. The URL can point
# at any local server that speaks the OpenAI chat-completions protocol
# (llama.cpp's llama-server, Jan, vLLM); LM Studio-only extras such as
# reading the loaded model's context length are skipped when they're missing.
# A blank model means "whichever model is loaded right now", detected per call
# (cached briefly), so swapping models in LM Studio needs no settings change.
# The utility model is optional: blank uses the script model, which avoids
# LM Studio unloading one model to load the other between calls.
def _lmstudio_default_url() -> str:
    """LM Studio's own server address on this machine, read from its config.

    LM Studio's port is 1234 by default but configurable, and an install can
    serve elsewhere (1235 was seen). Its server settings live in
    `~/.lmstudio/apps/<app>/.internal/http-server-config.json` (older builds:
    `~/.lmstudio/.internal/`). A cheap file read, no network.
    """
    import json
    home = Path.home() / ".lmstudio"
    for f in [*sorted(home.glob("apps/*/.internal/http-server-config.json")),
              home / ".internal" / "http-server-config.json"]:
        try:
            port = int(json.loads(f.read_text()).get("port") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if port:
            return f"http://127.0.0.1:{port}/v1"
    return "http://127.0.0.1:1234/v1"


LMSTUDIO_URL = (brand.env("LMSTUDIO_URL", "").strip() or _lmstudio_default_url()).rstrip("/")
LMSTUDIO_MODEL = brand.env("LMSTUDIO_MODEL", "").strip()
LMSTUDIO_MODEL_UTILITY = brand.env("LMSTUDIO_MODEL_UTILITY", "").strip()
# For the steps that read pictures (reviewing shots, identifying people,
# labelling footage). Blank prefers a loaded vision model, else the script one.
LMSTUDIO_MODEL_VISION = brand.env("LMSTUDIO_MODEL_VISION", "").strip()
# Ask LM Studio to constrain replies to valid JSON for JSON calls. Turned off
# automatically for the session if the server rejects `response_format`.
LMSTUDIO_JSON_MODE = brand.env("LMSTUDIO_JSON_MODE", "1").strip() not in ("0", "false", "no", "")
# Whether a local reasoning model thinks before answering. "auto" lets it
# think when writing the script and skips thinking for everything else
# (planning, titles, JSON chores): on Qwen 3.5 9B that took a small JSON call
# from 84 s to 4 s with the same answer. "on" always thinks; "off" never does.
LMSTUDIO_THINKING = brand.env("LMSTUDIO_THINKING", "auto").strip().lower()
# Call timeouts were sized for hosted models. A local model on a laptop can be
# several times slower, so local backends multiply every timeout by this.
LOCAL_TIMEOUT_FACTOR = max(1.0, float(brand.env("LOCAL_TIMEOUT_FACTOR", "3") or 3))

# Other chat providers, opt-in only. All three speak the OpenAI chat-completions
# protocol, so one client serves them (see app/llm.py). The model names are
# defaults that were not verified against each provider's live model list when
# written; set the env vars to whatever the account actually has. "script" is
# what the "opus" alias resolves to and "utility" what "sonnet" resolves to.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
XAI_API_KEY = os.environ.get("XAI_API_KEY", "").strip()
OPENAI_COMPAT = {
    "openai": {
        "label": "OpenAI", "base": "https://api.openai.com/v1",
        "key": OPENAI_API_KEY,
        "script": brand.env("OPENAI_MODEL_SCRIPT", "gpt-5.6-sol"),
        "utility": brand.env("OPENAI_MODEL_UTILITY", "gpt-5.6-luna"),
    },
    "deepseek": {
        "label": "DeepSeek", "base": "https://api.deepseek.com",
        "key": DEEPSEEK_API_KEY,
        "script": brand.env("DEEPSEEK_MODEL_SCRIPT", "deepseek-reasoner"),
        "utility": brand.env("DEEPSEEK_MODEL_UTILITY", "deepseek-chat"),
    },
    "grok": {
        "label": "Grok (xAI)", "base": "https://api.x.ai/v1",
        "key": XAI_API_KEY,
        "script": brand.env("GROK_MODEL_SCRIPT", "grok-4"),
        "utility": brand.env("GROK_MODEL_UTILITY", "grok-4-1-fast-non-reasoning"),
    },
}

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
# Where research finds its results: "searxng", "claude" (Claude's own web
# search, needs ANTHROPIC_API_KEY, no server to run) or "auto" — SearXNG if a
# URL is set, else Claude's search if a key is. See app/research.py.
SEARCH_BACKEND = brand.env("SEARCH_BACKEND", "auto").strip().lower()
# Brave Search API — free tier, key from brave.com/search/api. Used when set.
BRAVE_SEARCH_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
# How far the research step goes. "quick" is one pass of search and synthesis;
# "deep" is Claude's research mode — rounds of planning, follow-up searches and
# page reads before it writes. Both need SEARXNG_URL. See app/research.py.
RESEARCH_MODE = brand.env("RESEARCH_MODE", "quick").strip().lower()

# A Google Cloud "Desktop app" OAuth client, for publishing a rendered video
# straight to YouTube. "" disables the feature entirely — the channel page's
# YouTube panel just says so rather than offering a connect button that would
# fail. See the README for the two-minute Cloud Console setup.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

def _user_agent(contact: str) -> str:
    """The User-Agent for archive and research requests.

    Wikimedia rejects (HTTP 403) a client string with no way to reach anyone:
    the old default, "corkbored/1.0 (local research tool; contact: set …)",
    lost every Wikipedia search and page on a fresh install (measured
    2026-11-08). A product token plus the site URL passes; a contact the user
    adds in Settings, usually an email address, is appended to it.
    """
    contact = contact.strip()
    if "/" in contact.split(" ")[0]:
        return contact                       # already a full User-Agent
    base = f"{brand.NAME}/1.0 (+https://{brand.SITE_URL}"
    return f"{base}; {contact})" if contact else f"{base})"


USER_AGENT = _user_agent(brand.env("USER_AGENT", ""))

# ---------------------------------------------------------------- narration
# Kokoro runs locally: no key, no request, nothing leaves the machine. The two
# files are a one-off download; see the README.
KOKORO_MODEL = TTS_DIR / brand.env("KOKORO_MODEL", "kokoro-v1.0.onnx")
KOKORO_VOICES = TTS_DIR / brand.env("KOKORO_VOICES", "voices-v1.0.bin")

# ---------------------------------------------------------------- video
WIDTH, HEIGHT, FPS = 1920, 1080, 30
WORDS_PER_MINUTE = 158          # measured narration pace for documentary reads
PARAGRAPH_GAP = 0.35            # silence appended after each recorded take
HEAD_PAD = 0.6                  # silence before the first word
TAIL_PAD = 1.8                  # music-only outro after the last word

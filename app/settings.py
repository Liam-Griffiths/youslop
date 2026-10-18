"""Settings: what used to be a `.env` you hand-edited, now a file the UI
writes.

A development checkout still has `.env`, and that keeps working — nothing
here removes it. But an installed app has no repository to put a `.env` file
in, and no reason to expect its user owns a text editor comfortable with one.
`settings.json`, in the data folder, is the same idea with a form around it.

**Precedence, lowest to highest: `settings.json` < `.env` < a real environment
variable.** `.env` stays the development override it always was; a variable
set by the actual shell or by `run.sh` always wins over either file — nobody
editing Settings should be able to silently undo a deployment's own
configuration. See `config._load_environment()`, which is where this ordering
is actually applied.

Every value here becomes an environment variable at startup — the mechanism
this project already uses everywhere a key or a URL is configurable — so nothing
downstream of `config.py` needs to know Settings exists at all.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import data_root


@dataclass(frozen=True)
class Field:
    key: str            # the name this travels under in settings.json and the API
    env: str             # the environment variable it becomes
    label: str
    help: str = ""
    secret: bool = False   # never echoed back in a GET; only "is one set"
    group: str = "General"
    # (value, label) pairs. A plain text input when empty; a <select> of
    # exactly these choices when not — used for anything with a fixed,
    # correct set of answers (which backend, which model, how hard it
    # thinks), where free text just invites a typo an API call then fails on.
    options: tuple[tuple[str, str], ...] = ()
    # What this actually resolves to when nothing is set here — the literal
    # default the matching `config.py` constant falls back to. Without this,
    # an unset <select> just shows whichever option happens to be listed
    # first, which silently lied about "Utility model" being Opus when the
    # real default (`MODEL_UTILITY`'s own fallback) is Sonnet.
    default: str = ""


# The whole of what Settings can configure — everything `.env.example` lists,
# as a form instead of a file. Order here is UI order.
FIELDS: list[Field] = [
    Field("llm_backend", "YOUSLOP_LLM_BACKEND", "How to reach Claude",
         "Auto prefers a signed-in Claude Code CLI — it costs nothing beyond "
         "your subscription — and falls back to the API key below.",
         group="Claude", options=(
             ("auto", "Auto — CLI if signed in, else the API key"),
             ("cli", "Claude Code CLI only"),
             ("api", "Anthropic API only"),
             ("ollama", "Local model (Ollama) — opt in deliberately"),
             ("openai", "OpenAI (ChatGPT) — API key"),
             ("deepseek", "DeepSeek — API key"),
             ("grok", "Grok (xAI) — API key"),
         ), default="auto"),
    Field("openai_api_key", "OPENAI_API_KEY", "OpenAI API key", secret=True,
         help="For the OpenAI option above. Billed per token to your OpenAI account.",
         group="Claude"),
    Field("deepseek_api_key", "DEEPSEEK_API_KEY", "DeepSeek API key", secret=True,
         help="For the DeepSeek option above. Billed per token to your DeepSeek account.",
         group="Claude"),
    Field("xai_api_key", "XAI_API_KEY", "xAI (Grok) API key", secret=True,
         help="For the Grok option above. Billed per token to your xAI account.",
         group="Claude"),
    Field("ollama_context", "YOUSLOP_OLLAMA_CONTEXT", "Local model context window",
         "How much text the local model can read in one call. Research on a big "
         "subject can send tens of thousands of tokens of sources; anything past "
         "this is silently cut off. Larger needs more memory.", group="Claude",
         options=(
             ("8192", "8k tokens"),
             ("16384", "16k tokens"),
             ("32768", "32k tokens — default"),
             ("65536", "64k tokens — needs a lot of memory"),
         ), default="32768"),
    Field("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic API key", secret=True,
         help="Only needed if Claude Code isn't installed. Billed per token.",
         group="Claude"),
    Field("model_script", "VB_MODEL_SCRIPT", "Script-writing model",
         "The paragraphs themselves — the one place quality is worth paying "
         "for.", group="Claude", options=(
             ("opus", "Opus — best writing, the default"),
             ("sonnet", "Sonnet — faster and cheaper, noticeably plainer prose"),
             ("haiku", "Haiku — fastest, for a rough draft only"),
         ), default="opus"),
    Field("model_utility", "VB_MODEL_UTILITY", "Utility model",
         "The fiddly bits — planning which picture each paragraph wants, "
         "thumbnail text, pronunciation. Structured, not prose; sonnet is "
         "normally plenty.", group="Claude", options=(
             ("opus", "Opus"),
             ("sonnet", "Sonnet — the default"),
             ("haiku", "Haiku — fastest, for the simplest calls"),
         ), default="sonnet"),
    Field("effort", "YOUSLOP_EFFORT", "How hard it thinks",
         "Applies to both models above and both the CLI and API backends — "
         "the same scale either way. Higher costs more time and, on the API "
         "backend, more money. Blank leaves it at the backend's own default "
         "(high).", group="Claude", options=(
             ("", "Default"),
             ("low", "Low — fastest, for simple calls"),
             ("medium", "Medium"),
             ("high", "High"),
             ("xhigh", "Extra high"),
             ("max", "Max — slowest, when correctness matters most"),
         )),
    Field("llm_ollama_model", "YOUSLOP_OLLAMA_MODEL", "Local model (Ollama)",
         "Only used when \"How to reach Claude\" above is set to ollama — a "
         "fully local, no-account backend. Noticeably lower script quality "
         "than Claude; opt in deliberately, it is never chosen automatically.",
         group="Claude"),
    Field("elevenlabs_api_key", "ELEVENLABS_API_KEY", "ElevenLabs API key", secret=True,
         help="For narration in an ElevenLabs voice, your cloned voices included. "
         "Billed per character to your ElevenLabs plan. Works as soon as it's "
         "saved.", group="Voices"),
    Field("openai_api_key", "OPENAI_API_KEY", "OpenAI API key", secret=True,
         help="For narration in an OpenAI voice. Billed per character to your "
         "OpenAI account. Works as soon as it's saved.", group="Voices"),
    Field("pexels_api_key", "PEXELS_API_KEY", "Pexels", secret=True,
         help="Free key — adds stock photos and video clips.", group="Archives"),
    Field("pixabay_api_key", "PIXABAY_API_KEY", "Pixabay", secret=True,
         help="Free key — same.", group="Archives"),
    Field("giphy_api_key", "GIPHY_API_KEY", "Giphy", secret=True,
         help="Free key from developers.giphy.com. Reaction GIFs for a slide "
         "you deliberately want one on — \"reaction gif\" on the picture "
         "search. Never part of the automatic search; rights are not "
         "cleared by using this.", group="Archives"),
    Field("nypl_token", "NYPL_TOKEN", "NYPL Digital Collections", secret=True,
         help="Free, instant, from api.repo.nypl.org.", group="Archives"),
    Field("storyblocks_public_key", "STORYBLOCKS_PUBLIC_KEY", "Storyblocks public key",
         secret=True, group="Archives"),
    Field("storyblocks_secret_key", "STORYBLOCKS_SECRET_KEY", "Storyblocks secret key",
         secret=True, group="Archives"),
    Field("storyblocks_project_id", "STORYBLOCKS_PROJECT_ID", "Storyblocks project id",
         group="Archives"),
    Field("storyblocks_user_id", "STORYBLOCKS_USER_ID", "Storyblocks user id",
         group="Archives"),
    Field("searxng_url", "SEARXNG_URL", "SearXNG URL",
         "A local instance the script writer searches before writing a word. "
         "Blank skips research grounding.", group="Research"),
    Field("brave_search_api_key", "BRAVE_SEARCH_API_KEY", "Brave Search API key",
         "Free key from brave.com/search/api (the Data for Search plan). Used "
         "for research when set, ahead of the no-key scrape.",
         secret=True, group="Research"),
    Field("search_backend", "YOUSLOP_SEARCH_BACKEND", "Where research searches",
         "Auto takes the first of these that is set up: your SearXNG URL, a "
         "Brave key, your Anthropic key (Claude's own search, billed per search), "
         "or otherwise a plain scrape of DuckDuckGo that needs no key.",
         group="Research", options=(
             ("auto", "Auto — the best one that is set up"),
             ("searxng", "SearXNG — your own instance"),
             ("brave", "Brave Search — needs a Brave key"),
             ("claude", "Claude's web search — needs an Anthropic API key"),
             ("scrape", "DuckDuckGo scrape — no key, no setup"),
         ), default="auto"),
    Field("research_mode", "YOUSLOP_RESEARCH_MODE", "Research depth",
         "Quick is one search pass, then the script is written. Deep is "
         "Claude's research mode: it plans, runs follow-up searches and reads "
         "pages over several rounds before writing. Deep takes longer and makes "
         "more Claude calls.", group="Research", options=(
             ("quick", "Quick — one search pass"),
             ("deep", "Deep — Claude's research mode, several rounds"),
         ), default="quick"),
    Field("google_client_id", "GOOGLE_CLIENT_ID", "Google OAuth client id",
         group="Publishing"),
    Field("google_client_secret", "GOOGLE_CLIENT_SECRET", "Google OAuth client secret",
         secret=True, help="A Google Cloud \"Desktop app\" client, for publishing "
         "a render straight to YouTube. Blank hides that panel.", group="Publishing"),
    Field("video_encoder", "YOUSLOP_ENCODER", "Video encoder",
         "Where the finished video is encoded. Auto uses the graphics chip "
         "when it passes a test encode — VA-API on Linux, NVENC on NVIDIA, "
         "VideoToolbox on a Mac — and the CPU otherwise. Drawing the frames "
         "is CPU work either way.",
         group="Rendering", options=(
             ("auto", "Auto — the GPU if it works, else the CPU"),
             ("gpu", "GPU — prefer the graphics chip"),
             ("cpu", "CPU — x264, slower, slightly smaller files"),
         ), default="auto"),
    Field("user_agent", "VB_USER_AGENT", "Contact string for archive requests",
         "Wikimedia and Nominatim ask automated clients to identify "
         "themselves with a contact — put an email address here.",
         group="General"),
]
FIELDS_BY_KEY = {f.key: f for f in FIELDS}

SETTINGS_PATH_NAME = "settings.json"


def path() -> Path:
    return data_root() / SETTINGS_PATH_NAME


def load_file() -> dict[str, str]:
    """What's on disk. `{}` if there is nothing, or it doesn't parse."""
    p = path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: str(v) for k, v in data.items() if k in FIELDS_BY_KEY and str(v).strip()}


def save_file(values: dict[str, str]) -> dict[str, str]:
    """Merge `values` into settings.json and write it back. Unknown keys are
    rejected rather than silently dropped — a typo in a client should be loud.
    """
    unknown = sorted(set(values) - set(FIELDS_BY_KEY))
    if unknown:
        raise ValueError(f"Not a setting: {', '.join(unknown)}")
    current = load_file()
    for k, v in values.items():
        v = str(v).strip()
        if v:
            current[k] = v
        else:
            current.pop(k, None)   # an empty value clears it, same as .env

    d = data_root()
    d.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(current, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return current


def environment_overrides() -> dict[str, str]:
    """`{env_var: value}` for everything Settings has set. The lowest-priority
    layer `config._load_environment()` folds in — see that function for why
    order matters here."""
    stored = load_file()
    return {FIELDS_BY_KEY[k].env: v for k, v in stored.items() if k in FIELDS_BY_KEY}


def status() -> list[dict[str, Any]]:
    """Every field, for the Settings page: its current value (redacted if
    secret), whether it's actually set, and whether a real environment
    variable is overriding whatever is in the file — editing a field Settings
    can't actually change would be a trap, so the UI needs to know.
    """
    stored = load_file()
    out = []
    for f in FIELDS:
        from_file = stored.get(f.key, "")
        env_value = os.environ.get(f.env, "")
        # A real env var wins once the process has started (see
        # config._load_environment()); "locked" means editing this field here
        # would have no effect until that variable is unset.
        locked = bool(env_value) and env_value != from_file
        out.append({
            "key": f.key, "env": f.env, "label": f.label, "help": f.help,
            "secret": f.secret, "group": f.group,
            "value": "" if f.secret else from_file,
            "set": bool(from_file),
            "locked": locked,
            "options": [{"value": v, "label": lbl} for v, lbl in f.options],
            "default": f.default,
        })
    return out

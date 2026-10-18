"""Narration read by a hosted voice service: ElevenLabs or OpenAI.

The local model (`tts.py`) is the default for good reasons — free, private,
unmetered. These are here for the channel that wants a voice it cannot get on
a CPU: an ElevenLabs voice with real range, or one cloned from the creator.
The trade is the one the local model was chosen to avoid, so it is made
visible rather than hidden: every read is billed by the character to the
creator's own account, and the UI says how many characters before it sends
a whole script.

What comes back is handed to the same finishing chain as a Kokoro read
(`tts._finish_chain`), so a cloud take is a take like any other — trimmed,
levelled to the same loudness, 48kHz mono — and nothing downstream can tell.

Keys come from Settings (or the environment) and are read on every call
rather than once at startup, so pasting one in works without a restart.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import httpx

from . import settings as settings_mod


class CloudVoiceError(RuntimeError):
    pass


ENGINES: list[dict] = [
    {"key": "elevenlabs", "label": "ElevenLabs",
     "setting": "elevenlabs_api_key", "env": "ELEVENLABS_API_KEY",
     "blurb": "The most natural reads, your own cloned voices included. Billed "
              "per character to your ElevenLabs plan.",
     "models": [
         {"id": "eleven_multilingual_v2", "label": "Multilingual v2 — the most expressive"},
         {"id": "eleven_turbo_v2_5", "label": "Turbo v2.5 — faster, half the credits"},
         {"id": "eleven_flash_v2_5", "label": "Flash v2.5 — fastest, cheapest"},
     ],
     # ElevenLabs' own range for voice_settings.speed.
     "speed": (0.7, 1.2),
     # A premade voice every account has, so a fresh pick reads something.
     "default_voice": "JBFqnCBsd6RMkjVDRZzb"},
    {"key": "openai", "label": "OpenAI",
     "setting": "openai_api_key", "env": "OPENAI_API_KEY",
     "blurb": "A small fixed set of clean voices that can be steered by the "
              "video's tone. Billed per character to your OpenAI account.",
     "models": [
         {"id": "gpt-4o-mini-tts", "label": "gpt-4o-mini-tts — follows the tone"},
         {"id": "tts-1-hd", "label": "tts-1-hd — steadier, no steering"},
         {"id": "tts-1", "label": "tts-1 — fastest"},
     ],
     "speed": (0.7, 1.3),
     "default_voice": "onyx"},
]
BY_KEY = {e["key"]: e for e in ENGINES}
KEYS = list(BY_KEY)

# OpenAI's voices are a fixed list with no API to enumerate them.
OPENAI_VOICES = [
    {"id": "onyx", "label": "Onyx", "note": "Deep and even. The documentary default."},
    {"id": "echo", "label": "Echo", "note": "Lighter male voice, clear and quick."},
    {"id": "fable", "label": "Fable", "note": "British-leaning storyteller."},
    {"id": "ash", "label": "Ash", "note": "Relaxed and conversational."},
    {"id": "ballad", "label": "Ballad", "note": "Soft and melodic."},
    {"id": "verse", "label": "Verse", "note": "Expressive, with range."},
    {"id": "alloy", "label": "Alloy", "note": "Neutral and balanced."},
    {"id": "nova", "label": "Nova", "note": "Bright and energetic."},
    {"id": "shimmer", "label": "Shimmer", "note": "Warm and gentle."},
    {"id": "coral", "label": "Coral", "note": "Friendly and upbeat."},
    {"id": "sage", "label": "Sage", "note": "Calm and considered."},
]

_VOICE_ID = re.compile(r"^[\w-]{1,64}$")


def valid_voice_id(voice: str) -> bool:
    return bool(_VOICE_ID.match(voice or ""))


def default_model(engine: str) -> str:
    return BY_KEY[engine]["models"][0]["id"]


def api_key(engine: str) -> str:
    """The key, from the environment first and then Settings — read now, not
    at startup, so one pasted into Settings works straight away."""
    e = BY_KEY[engine]
    return (os.environ.get(e["env"], "").strip()
            or settings_mod.load_file().get(e["setting"], "").strip())


def status(engine: str) -> dict:
    e = BY_KEY[engine]
    ready = bool(api_key(engine))
    return {"key": engine, "label": e["label"], "blurb": e["blurb"], "ready": ready,
            "metered": True, "models": e["models"], "speed": list(e["speed"]),
            "default_voice": e["default_voice"],
            "detail": "" if ready else f"Add your {e['label']} API key in Settings."}


def clamp_speed(engine: str, speed: float) -> float:
    lo, hi = BY_KEY[engine]["speed"]
    return round(max(lo, min(hi, float(speed or 1.0))), 2)


# ------------------------------------------------------------------- errors
def _fail(engine: str, resp: httpx.Response) -> CloudVoiceError:
    """A message a creator can act on, not a status code."""
    label = BY_KEY[engine]["label"]
    try:
        body = resp.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("status")
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        detail = body["error"].get("message")
    detail = str(detail or resp.text[:200] or "").strip()
    code = resp.status_code
    # Checked before the status code: ElevenLabs reports an empty account as
    # a 401 too, and "check your key" is the wrong advice for that.
    if code == 402 or re.search(r"quota|credits|insufficient", detail, re.I):
        return CloudVoiceError(f"{label} says the account is out of credits. ({detail})")
    if code == 401:
        return CloudVoiceError(f"{label} refused the API key. Check it in Settings. ({detail})")
    if code == 429:
        return CloudVoiceError(f"{label} is rate-limiting us; try again in a minute. ({detail})")
    if code in (400, 404, 422) and "voice" in detail.lower():
        return CloudVoiceError(f"{label} doesn't know that voice. Pick another. ({detail})")
    return CloudVoiceError(f"{label} returned {code}: {detail}")


def _post(engine: str, url: str, timeout: float = 120.0, **kw) -> httpx.Response:
    """POST with a couple of retries for the failures that are worth one."""
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = httpx.post(url, timeout=timeout, **kw)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(2.0 * (attempt + 1))
            last = _fail(engine, resp)
            continue
        if resp.status_code >= 400:
            raise _fail(engine, resp)
        return resp
    if isinstance(last, CloudVoiceError):
        raise last
    raise CloudVoiceError(f"Could not reach {BY_KEY[engine]['label']}: {last}")


# ------------------------------------------------------------------- voices
_VOICE_CACHE: dict[str, tuple[float, list[dict]]] = {}


def voices(engine: str, refresh: bool = False) -> list[dict]:
    """The voices this account can use, in the shape the picker draws."""
    if engine == "openai":
        return [dict(v, accent="OpenAI", sex="", preview_url="") for v in OPENAI_VOICES]
    key = api_key(engine)
    if not key:
        raise CloudVoiceError(status(engine)["detail"])
    cached = _VOICE_CACHE.get(engine)
    if cached and not refresh and time.time() - cached[0] < 600:
        return cached[1]
    try:
        resp = httpx.get("https://api.elevenlabs.io/v1/voices",
                         headers={"xi-api-key": key}, timeout=30)
    except httpx.HTTPError as exc:
        raise CloudVoiceError(f"Could not reach ElevenLabs: {exc}")
    if resp.status_code >= 400:
        raise _fail(engine, resp)
    out = []
    for v in resp.json().get("voices", []):
        labels = v.get("labels") or {}
        # Your own (cloned, designed) voices first, then the library ones.
        mine = v.get("category") in ("cloned", "generated", "professional")
        out.append({
            "id": v.get("voice_id", ""), "label": v.get("name", "?"),
            "accent": "Your voices" if mine else (labels.get("accent") or "Other").title(),
            "sex": labels.get("gender", ""),
            "note": ", ".join(x for x in (labels.get("description"), labels.get("age"),
                                          labels.get("use_case")) if x),
            "preview_url": v.get("preview_url") or "",
        })
    out.sort(key=lambda v: (v["accent"] != "Your voices", v["accent"], v["label"]))
    _VOICE_CACHE[engine] = (time.time(), out)
    return out


# ------------------------------------------------------------ voice library
# ElevenLabs' Voice Library is the thousands of voices other people have shared
# — the ones on their website. `voices()` above only lists the ones already in
# this account ("My Voices" plus the premade set); a library voice has to be
# added to the account before the API will read with it. These two do that
# from inside the app: search with a preview, then add the one you like.
LIBRARY_USE_CASES = [
    ("", "Any use"),
    ("narrative_story", "Narration & story"),
    ("informative_educational", "Informative & educational"),
    ("conversational", "Conversational"),
    ("characters_animation", "Characters"),
    ("social_media", "Social media"),
    ("entertainment_tv", "Entertainment & TV"),
    ("advertisement", "Advertisement"),
]


def library_search(query: str = "", gender: str = "", use_case: str = "",
                   accent: str = "", page: int = 0, page_size: int = 30) -> dict:
    """One page of the shared Voice Library, in the shape the picker draws."""
    key = api_key("elevenlabs")
    if not key:
        raise CloudVoiceError(status("elevenlabs")["detail"])
    params = {"page_size": max(1, min(100, page_size)), "page": max(0, page),
              "language": "en", "sort": "trending"}
    if query.strip():
        params["search"] = query.strip()[:80]
    if gender in ("male", "female", "neutral"):
        params["gender"] = gender
    if use_case and use_case in dict(LIBRARY_USE_CASES):
        params["use_cases"] = use_case
    if accent.strip():
        params["accent"] = accent.strip().lower()[:40]
    try:
        resp = httpx.get("https://api.elevenlabs.io/v1/shared-voices", params=params,
                         headers={"xi-api-key": key}, timeout=30)
    except httpx.HTTPError as exc:
        raise CloudVoiceError(f"Could not reach ElevenLabs: {exc}")
    if resp.status_code >= 400:
        raise _fail("elevenlabs", resp)
    body = resp.json()
    out = []
    for v in body.get("voices", []):
        out.append({
            "id": v.get("voice_id", ""), "owner": v.get("public_owner_id", ""),
            "label": v.get("name", "?"),
            "accent": (v.get("accent") or "").title(), "sex": v.get("gender", ""),
            "age": (v.get("age") or "").replace("_", " "),
            "use_case": (v.get("use_case") or "").replace("_", " "),
            "note": (v.get("description") or v.get("descriptive") or "")[:160],
            "preview_url": v.get("preview_url") or "",
            "uses": v.get("cloned_by_count") or v.get("usage_character_count_1y") or 0,
        })
    return {"voices": out, "has_more": bool(body.get("has_more")), "page": page}


def library_add(owner: str, voice_id: str, name: str) -> str:
    """Add a library voice to this account. Returns the id to read with —
    ElevenLabs gives the added copy an id of its own."""
    key = api_key("elevenlabs")
    if not key:
        raise CloudVoiceError(status("elevenlabs")["detail"])
    if not (valid_voice_id(owner) and valid_voice_id(voice_id)):
        raise CloudVoiceError("That isn't a library voice.")
    resp = _post("elevenlabs",
                 f"https://api.elevenlabs.io/v1/voices/add/{owner}/{voice_id}",
                 timeout=30, headers={"xi-api-key": key},
                 json={"new_name": (name or "Library voice").strip()[:60]})
    new_id = (resp.json() or {}).get("voice_id") or voice_id
    _VOICE_CACHE.pop("elevenlabs", None)      # the account's list just changed
    return new_id


# --------------------------------------------------------------- synthesis
def synthesise(engine: str, text: str, out_path: Path, voice: str, model: str = "",
               speed: float = 1.0, previous_text: str = "", next_text: str = "",
               style: str = "") -> Path:
    """Read `text` into an audio file at `out_path` (its extension is set
    here: .mp3 for ElevenLabs, .wav for OpenAI). Returns the path written.

    `previous_text` and `next_text` are the paragraphs either side; ElevenLabs
    uses them to carry intonation across the seam, so a script read paragraph
    by paragraph doesn't restart its delivery at every one. `style` is the
    video's tone, which OpenAI's steerable model reads as direction.
    """
    key = api_key(engine)
    if not key:
        raise CloudVoiceError(status(engine)["detail"])
    if not valid_voice_id(voice):
        raise CloudVoiceError("Pick a voice first.")
    model = model or default_model(engine)
    speed = clamp_speed(engine, speed)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if engine == "elevenlabs":
        body = {"text": text, "model_id": model,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                                   "style": 0.0, "use_speaker_boost": True,
                                   "speed": speed}}
        if previous_text:
            body["previous_text"] = previous_text[-1000:]
        if next_text:
            body["next_text"] = next_text[:1000]
        resp = _post(engine,
                     f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
                     "?output_format=mp3_44100_128",
                     headers={"xi-api-key": key, "Accept": "audio/mpeg"}, json=body)
        out = out_path.with_suffix(".mp3")
    elif engine == "openai":
        body = {"model": model, "voice": voice, "input": text[:4096],
                "response_format": "wav", "speed": speed}
        if model == "gpt-4o-mini-tts":
            body["instructions"] = (
                "You are narrating a video. Read clearly and naturally, at an even "
                "pace, like a documentary narrator"
                + (f", in a {style} tone" if style else "") + ". Do not rush.")
        resp = _post(engine, "https://api.openai.com/v1/audio/speech",
                     headers={"Authorization": f"Bearer {key}"}, json=body)
        out = out_path.with_suffix(".wav")
    else:
        raise CloudVoiceError(f"Not a voice service: {engine}")

    if len(resp.content) < 1024:
        raise CloudVoiceError(f"{BY_KEY[engine]['label']} sent back no audio.")
    out.write_bytes(resp.content)
    return out


# ------------------------------------------------------------ pronunciation
def aliases(entries: list[dict]) -> dict[str, str]:
    """The pronunciation guide as plain-text substitutions.

    Hosted voices take text, not Kokoro's phonemes, so an entry's respelling
    is what they are given instead: "ELL-on" becomes "Ellon", read as a word.
    An entry with only IPA has nothing a text voice can use, and is skipped.
    """
    out: dict[str, str] = {}
    for e in entries or []:
        term, respell = str(e.get("term") or "").strip(), str(e.get("respell") or "").strip()
        if not term or not respell:
            continue
        word = " ".join("".join(part.lower() for part in chunk.split("-"))
                        for chunk in respell.split())
        if term[:1].isupper():
            word = word[:1].upper() + word[1:]
        out[term] = word
    return out


def apply_aliases(text: str, table: dict[str, str]) -> str:
    for term in sorted(table, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", table[term], text)
    return text

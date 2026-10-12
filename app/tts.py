"""Narration read by a local model instead of by you.

Kokoro is an 82M-parameter model that runs on the CPU through onnxruntime. It
is here rather than an API because a narration pass is thousands of sentences:
nothing leaves the machine, nothing is metered, and a re-write at midnight costs
nothing but the time. Apache-2.0, weights included, which is the part that
matters for a channel that earns money.

What comes out is a take in exactly the shape the recorder produces, so
everything downstream — the gaps, the picture timing, the narration bed, the
render — cannot tell the two apart and does not need to.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable

from . import ffutil
from .config import KOKORO_MODEL, KOKORO_VOICES
from .schema import Voice

Progress = Callable[[str], None]

# The model holds ~330MB resident, so it is loaded once and shared. Synthesis
# itself is not thread safe, hence the lock: paragraphs are cheap enough that
# one at a time still beats real time, and onnxruntime uses every core anyway.
_MODEL = None
_LOCK = threading.Lock()


class TTSError(RuntimeError):
    pass


# The English voices, which are the ones a documentary channel wants. Kokoro
# ships 54 across eight languages; the rest are reachable by id but are not
# offered here, because a picker of 54 names in four alphabets helps nobody.
# "quality" is Kokoro's own grading of how much training audio a voice had.
VOICES: list[dict] = [
    {"id": "bm_george",   "label": "George",   "accent": "British",  "sex": "male",
     "note": "Measured and dry. The default: it narrates rather than performs."},
    {"id": "bm_fable",    "label": "Fable",    "accent": "British",  "sex": "male",
     "note": "Warmer and a little theatrical. Suits stories about people."},
    {"id": "bm_daniel",   "label": "Daniel",   "accent": "British",  "sex": "male",
     "note": "Lighter and quicker. Good for explainers."},
    {"id": "bm_lewis",    "label": "Lewis",    "accent": "British",  "sex": "male",
     "note": "Deeper, slower. Heavy on gravitas; easy to overdo."},
    {"id": "bf_emma",     "label": "Emma",     "accent": "British",  "sex": "female",
     "note": "Calm and even. The most neutral of the British women."},
    {"id": "bf_isabella", "label": "Isabella", "accent": "British",  "sex": "female",
     "note": "Rounder, more expressive."},
    {"id": "bf_alice",    "label": "Alice",    "accent": "British",  "sex": "female",
     "note": "Brighter and younger-sounding."},
    {"id": "bf_lily",     "label": "Lily",     "accent": "British",  "sex": "female",
     "note": "Soft and close. Reads intimate rather than broadcast."},
    {"id": "am_michael",  "label": "Michael",  "accent": "American", "sex": "male",
     "note": "Steady mid-Atlantic documentary read."},
    {"id": "am_fenrir",   "label": "Fenrir",   "accent": "American", "sex": "male",
     "note": "Deeper and more deliberate."},
    {"id": "am_puck",     "label": "Puck",     "accent": "American", "sex": "male",
     "note": "Livelier, with more range. Good for a lighter channel."},
    {"id": "am_adam",     "label": "Adam",     "accent": "American", "sex": "male",
     "note": "Plain and unhurried."},
    {"id": "af_bella",    "label": "Bella",    "accent": "American", "sex": "female",
     "note": "The best-trained voice in the set. Rich and confident."},
    {"id": "af_nicole",   "label": "Nicole",   "accent": "American", "sex": "female",
     "note": "Quieter, closer to the mic. Almost whispered on soft lines."},
    {"id": "af_heart",    "label": "Heart",    "accent": "American", "sex": "female",
     "note": "Warm and open."},
    {"id": "af_sarah",    "label": "Sarah",    "accent": "American", "sex": "female",
     "note": "Crisp and businesslike."},
]

VOICE_IDS = {v["id"] for v in VOICES}
DEFAULT_VOICE = "bm_george"


def is_installed() -> bool:
    """Whether the package imports. Says nothing about the weights."""
    try:
        import kokoro_onnx  # noqa: F401
    except Exception:
        return False
    return True


def weights_present() -> bool:
    return KOKORO_MODEL.is_file() and KOKORO_VOICES.is_file()


def status() -> dict:
    """What the UI needs to decide whether to offer an AI read at all."""
    installed, weights = is_installed(), weights_present()
    return {
        "ready": installed and weights,
        "installed": installed,
        "weights": weights,
        "model_path": str(KOKORO_MODEL),
        "voices": VOICES,
        "default_voice": DEFAULT_VOICE,
        "detail": (
            "" if installed and weights
            else (
                "pip install kokoro-onnx soundfile"
                if not installed
                else f"Model files missing from {KOKORO_MODEL.parent}"
            )
        ),
    }


def _model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    if not is_installed():
        raise TTSError("The kokoro-onnx package is not installed. "
                       "Run: pip install kokoro-onnx soundfile")
    if not weights_present():
        raise TTSError(f"Kokoro's model files are not in {KOKORO_MODEL.parent}. "
                       "See the README for the two downloads.")
    from kokoro_onnx import Kokoro
    _MODEL = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
    return _MODEL


def _lang_for(voice: str) -> str:
    """Kokoro wants the language separately, and the voice id encodes it."""
    return "en-gb" if voice.startswith(("bm_", "bf_")) else "en-us"


# Things that are written for the eye and have to be said. A narrator reading
# "1971-73" as two numbers, or spelling out "Dr", is the tell that gives a
# synthetic read away fastest, and it is cheap to fix before the model sees it.
_SPOKEN = [
    (re.compile(r"\bDr\.?\s"), "Doctor "),
    (re.compile(r"\bMr\.?\s"), "Mister "),
    (re.compile(r"\bMrs\.?\s"), "Missus "),
    (re.compile(r"\bSt\.?\s"), "Saint "),
    (re.compile(r"\bvs\.?\s"), "versus "),
    (re.compile(r"\betc\.?"), "et cetera"),
    (re.compile(r"\be\.g\.?"), "for example"),
    (re.compile(r"\bi\.e\.?"), "that is"),
    # An en-dash between numbers is a range, and is read "to".
    (re.compile(r"(\d)\s*[–—-]\s*(\d)"), r"\1 to \2"),
    # Decades: 1970s -> nineteen seventies is beyond a regex, but the bare
    # apostrophe form is not, and is the one that trips the model up.
    (re.compile(r"'(\d0)s\b"), r"\1s"),
]


# ------------------------------------------------------------------- years
# A bare "1996" is read by the model as "one thousand nine hundred and ninety
# six", which is how a quantity is said, not a year. Every documentary script is
# full of these, so they are rewritten to the way a narrator would actually say
# them before the model ever sees them.
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]
# "the nineteen nineties", not "the nineteen ninety s".
_DECADES = {0: "hundreds", 10: "tens", 20: "twenties", 30: "thirties",
            40: "forties", 50: "fifties", 60: "sixties", 70: "seventies",
            80: "eighties", 90: "nineties"}


def _two_digit(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def say_year(year: int) -> str:
    """A year as a narrator says it: 1996 -> nineteen ninety six."""
    century, rest = divmod(year, 100)
    if 2000 <= year <= 2009:
        return "two thousand" + (f" {_ONES[rest]}" if rest else "")
    if rest == 0:
        return f"{_two_digit(century)} hundred"
    if rest < 10:
        return f"{_two_digit(century)} oh {_ONES[rest]}"
    return f"{_two_digit(century)} {_two_digit(rest)}"


def say_decade(year: int) -> str:
    """A decade as it is said: 1990s -> nineteen nineties, 2000s -> two thousands."""
    century, rest = divmod(year, 100)
    if year < 2000 or year >= 2100:
        return f"{_two_digit(century)} {_DECADES.get(rest, _two_digit(rest) + 's')}"
    if rest == 0:
        return "two thousands"
    return f"twenty {_DECADES.get(rest, _two_digit(rest) + 's')}"


# 1100-2099 only. Below that a four digit number in a script is far more likely
# to be a quantity than a date, and "twelve hundred" is the wrong reading of
# "1200 employees".
_YEAR = re.compile(r"\b(1[1-9]\d{2}|20\d{2})\b")
_DECADE = re.compile(r"\b(1[1-9]\d0|20\d0)s\b")


def _years_spoken(text: str) -> str:
    text = _DECADE.sub(lambda m: say_decade(int(m.group(1))), text)
    return _YEAR.sub(lambda m: say_year(int(m.group(1))), text)


def spoken_form(text: str) -> str:
    """The paragraph as it should be *said*, not as it is written."""
    out = " ".join((text or "").split())
    for pattern, repl in _SPOKEN:
        out = pattern.sub(repl, out)
    # After the ranges are opened out ("1971-73" -> "1971 to 73"), so the year
    # on the left of a range is spoken as a year too.
    out = _years_spoken(out)
    # An ellipsis reads as a hard stop; a comma keeps the line moving.
    out = out.replace("…", ", ").replace("...", ", ")
    return out.strip()


# ---------------------------------------------------------- pronunciation
# Kokoro reaches its phonemes through espeak, which is good at English and
# unreliable at names: "Elon" comes out ɪlˈɒn, "ih-LON", stressed on the wrong
# syllable. The guide fixes those one at a time.
#
# Phonemes rather than respellings are what gets stored, because a respelling is
# a guess at espeak's spelling rules and frequently loses — "Ehlon" reads as
# "AY-lon". A respelling is how an entry is *written*; `phonemes_for` turns it
# into the thing that actually decides the sound, which can then be heard and
# corrected.
def phonemise(text: str, lang: str = "en-gb") -> str:
    """What espeak makes of a piece of text, filtered to Kokoro's vocabulary."""
    said = spoken_form(text)
    if not said:
        return ""
    return _model().tokenizer.phonemize(said, lang).strip()


_STRESS = "ˈˌ"


def _strip_stress(phonemes: str) -> str:
    return "".join(c for c in phonemes if c not in _STRESS)


# Stress marks, punctuation and whitespace carry no sound of their own. An entry
# made only of those says nothing, however non-empty the string looks — "???"
# survives espeak and the vocabulary filter as a bare "?".
_VOICELESS = set(_STRESS) | set(" \t!\"(),.:;?—“”…→↓↗↘")


def has_phones(phonemes: str) -> bool:
    return any(c not in _VOICELESS for c in phonemes or "")


def clean_ipa(ipa: str) -> str:
    """Explicit phonemes, less anything Kokoro has no token for.

    Kokoro's vocabulary is 114 symbols. Anything outside it is dropped on the
    way in anyway; dropping it here means the entry that gets stored is the one
    that will actually be spoken, and a mis-typed symbol is visible immediately.
    """
    ipa = (ipa or "").strip()
    if not ipa:
        return ""
    try:
        vocab = _model().tokenizer.vocab
    except Exception:
        return ipa
    return "".join(c for c in ipa if c in vocab).strip()


def from_respelling(respell: str, lang: str = "en-gb") -> str:
    """Phonemes for a respelling like "ELL-on", where CAPS mark the stress.

    Handing the whole respelling to espeak does not work. Hyphens make it stress
    every part — "ell-on" comes out ˈɛlˈɒn, two primary stresses in one word —
    and capitals make it spell letters out, so "rod-REE-gess" is read as
    "rod-ar-ee-ee-gess". Each syllable is therefore phonemised on its own in
    lower case, stripped of whatever stress espeak guessed, and the one primary
    stress is placed where the capitals said to put it.
    """
    parts = [p for p in re.split(r"[-\s.·]+", (respell or "").strip()) if p]
    if not parts:
        return ""
    # A part in full capitals is the stressed syllable; failing that, one that
    # merely starts with a capital; failing that, the first.
    hint = next((i for i, p in enumerate(parts) if p.isupper() and len(p) > 1), None)
    if hint is None:
        hint = next((i for i, p in enumerate(parts)
                     if p[:1].isupper() and not p.islower()), 0)
    out = []
    for i, part in enumerate(parts):
        phon = _strip_stress(phonemise(part.lower(), lang))
        if has_phones(phon):
            out.append(("ˈ" if i == hint else "") + phon)
    joined = "".join(out)
    return joined if has_phones(joined) else ""


def phonemes_for(entry: dict, lang: str = "en-gb") -> str:
    """The phonemes one guide entry contributes. Explicit IPA wins."""
    ipa = clean_ipa(entry.get("ipa") or "")
    if has_phones(ipa):
        return ipa
    got = from_respelling(entry.get("respell") or "", lang)
    return got if has_phones(got) else ""


def build_lexicon(entries: list[dict], lang: str = "en-gb") -> dict[str, str]:
    """term (lowercased) -> phonemes, for the entries that resolve to anything."""
    out: dict[str, str] = {}
    for entry in entries or []:
        term = (entry.get("term") or "").strip()
        if not term:
            continue
        try:
            phon = phonemes_for(entry, lang)
        except Exception:
            continue
        if phon:
            out[term.lower()] = phon
    return out


def _lexicon_pattern(lexicon: dict[str, str]) -> re.Pattern | None:
    if not lexicon:
        return None
    # Longest first, so "Elon Musk" is matched before "Elon". \b is wrong at the
    # edges of a term that starts or ends in punctuation, so the boundary is
    # asserted only where the term itself begins or ends with a word character.
    terms = sorted(lexicon, key=len, reverse=True)
    parts = []
    for t in terms:
        body = re.escape(t)
        parts.append((r"\b" if t[:1].isalnum() else "") + body
                     + (r"\b" if t[-1:].isalnum() else ""))
    return re.compile("(" + "|".join(parts) + ")", re.I)


def phonemise_with_lexicon(text: str, lexicon: dict[str, str],
                           lang: str = "en-gb") -> tuple[str, int]:
    """Phonemes for a paragraph with the guide applied. Returns (phonemes, hits).

    The text either side of a match is phonemised in runs rather than word by
    word, so espeak still sees enough context to place stress and liaison
    normally; only the matched terms are substituted wholesale.
    """
    said = spoken_form(text)
    pattern = _lexicon_pattern(lexicon)
    if not said or pattern is None:
        return (phonemise(said, lang) if said else ""), 0

    pieces: list[str] = []
    hits = 0
    last = 0
    for m in pattern.finditer(said):
        run = said[last:m.start()]
        if run.strip():
            pieces.append(phonemise(run, lang))
        pieces.append(lexicon[m.group(1).lower()])
        hits += 1
        last = m.end()
    tail = said[last:]
    if tail.strip():
        pieces.append(phonemise(tail, lang))
    return _join(pieces), hits


def _join(pieces: list[str]) -> str:
    """Space-separated, except before punctuation, which stays welded on."""
    out = ""
    for piece in (p for p in pieces if p):
        if out and not piece[:1] in ",.;:!?…":
            out += " "
        out += piece
    return out.strip()


def synthesise(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0,
               lexicon: dict[str, str] | None = None):
    """Raw samples for one paragraph. Returns (samples, sample_rate)."""
    said = spoken_form(text)
    if not said:
        raise TTSError("There is nothing to say in that paragraph.")
    if voice not in VOICE_IDS:
        voice = DEFAULT_VOICE
    model = _model()
    lang = _lang_for(voice)
    speed = max(0.5, min(1.5, float(speed)))
    with _LOCK:
        if lexicon:
            phonemes, hits = phonemise_with_lexicon(said, lexicon, lang)
            # Only take the phoneme path when the guide actually applies. Text is
            # the better-trodden route through the model, so a paragraph with no
            # names in it should not be sent a different way.
            if hits and phonemes:
                return model.create(phonemes, voice=voice, speed=speed,
                                    lang=lang, is_phonemes=True)
        return model.create(said, voice=voice, speed=speed, lang=lang)


# A synthetic read has no room, no hiss and no mouth noise, so the recorded-take
# chain — de-noise, de-room, de-ess — has nothing to remove and would only smear
# it. All this needs is the sample rate everything else runs at, a gentle
# high-pass under the voice, and the same loudness every take lands on.
def _finish_chain(voice_spec: Voice | None) -> str:
    target = float(getattr(voice_spec, "target_lufs", -16.0) or -16.0)
    return (
        # Kokoro occasionally leaves a breath of DC-ish rumble at a phrase edge.
        "highpass=f=65,"
        # Trim the silence Kokoro pads the ends with. The gap that follows a
        # paragraph is decided by audio.paragraph_gaps, and a take that carries
        # its own tail would be added on top of it.
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.02:"
        "detection=peak,"
        "areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.02:"
        "detection=peak,"
        "areverse,"
        f"loudnorm=I={target:.1f}:TP=-1.5:LRA=11"
    )


def speak_to_file(text: str, out_path: Path, voice: str = DEFAULT_VOICE,
                  speed: float = 1.0, voice_spec: Voice | None = None,
                  lexicon: dict[str, str] | None = None) -> dict:
    """Synthesise one paragraph into a finished take. Returns take metadata.

    Written to a scratch file and moved into place only once it is known good,
    for the same reason a re-record is: a failure must not take the previous
    take down with it.
    """
    import soundfile as sf

    samples, rate = synthesise(text, voice, speed, lexicon)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = out_path.with_suffix(".raw.wav")
    tmp = out_path.with_suffix(".part.wav")
    try:
        sf.write(str(raw), samples, rate)
        ffutil.run(["-i", str(raw), "-af", _finish_chain(voice_spec),
                    "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(tmp)])
        dur = ffutil.duration(tmp)
        if dur < 0.15:
            raise TTSError("That paragraph came back silent.")
        tmp.replace(out_path)
    finally:
        raw.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return {"duration": round(dur, 3), "recorded_at": time.time(),
            "voice": voice, "speed": round(float(speed), 2), "synthetic": True}


def preview_path(voice: str, cache_dir: Path) -> Path:
    return cache_dir / f"voice_{voice}.wav"


SAMPLE_LINE = ("Two albums, recorded in Detroit, and neither of them sold. "
               "He went back to demolition work, and never knew that half a "
               "world away he had become a legend.")


def preview(voice: str, cache_dir: Path, speed: float = 1.0) -> Path:
    """One line in a voice, cached, so the picker can be listened through."""
    out = preview_path(voice, cache_dir)
    if out.is_file() and out.stat().st_size > 4096:
        return out
    speak_to_file(SAMPLE_LINE, out, voice, speed)
    return out

"""Word timing from model phonemes or a deliberately low-confidence envelope."""
from __future__ import annotations

import re
from pathlib import Path

from . import audio, tts

FRAME = audio.FRAME


def _runs(env: list[float], floor_db: float, merge_s=0.15) -> list[tuple[float, float]]:
    """Voiced intervals; merge pauses shorter than merge_s."""
    runs = []
    for i, level in enumerate(env):
        if level <= floor_db:
            continue
        start, end = i * FRAME, (i + 1) * FRAME
        if runs and start - runs[-1][1] < merge_s:
            runs[-1] = (runs[-1][0], end)
        else:
            runs.append((start, end))
    return runs


def _syllables(word: str) -> int:
    return max(1, len(re.findall(r"[aeiouy]+", word.lower())))


def spread(words: list[str], runs: list[tuple[float, float]]) -> list[dict]:
    """Lay words over voiced time in proportion to vowel groups, skipping gaps."""
    if not words or not runs:
        return []
    total = sum(end - start for start, end in runs)
    weights = [_syllables(word) for word in words]
    unit = total / sum(weights)

    def position(offset: float, *, end: bool = False) -> float:
        for start, stop in runs:
            length = stop - start
            if offset < length or (end and offset <= length):
                return start + offset
            offset -= length
        return runs[-1][1]

    result, used = [], 0
    for word, weight in zip(words, weights):
        start = position(used * unit)
        used += weight
        stop = position(used * unit, end=True)
        result.append({"w": word, "start": round(start, 3),
                       "end": round(stop, 3), "src": "est"})
    return result


def _text_words(text: str) -> tuple[list[str], list[str]]:
    spoken = tts.spoken_form(text).split()
    original = text.split()
    return spoken, original if len(original) == len(spoken) else spoken


def estimate(path: Path, text: str) -> list[dict]:
    env = audio._levels(path)
    span = audio.speech_span(env)
    runs = []
    if span:
        threshold = span.floor + (span.peak - span.floor) * 0.35
        runs = [(max(start, span.start), min(end, span.end))
                for start, end in _runs(env, threshold)
                if end > span.start and start < span.end]
    runs = runs or [(0.0, len(env) * FRAME)]
    spoken, labels = _text_words(text)
    result = spread(spoken, runs)
    for item, label in zip(result, labels):
        item["w"] = label
    return result


def from_phonemes(timings, text: str, head_trim_s: float,
                  path: Path | None = None) -> list[dict]:
    """Group at spaces; mismatched counts need an envelope fallback at path.

    Without a processed path, a mismatch returns [] so a caller can estimate.
    """
    groups = []
    start = end = None
    for timing in timings:
        if timing.phoneme.isspace():
            if start is not None:
                groups.append((start, end))
                start = end = None
        else:
            if start is None:
                start = timing.start
            end = timing.end
    if start is not None:
        groups.append((start, end))
    spoken, labels = _text_words(text)
    if len(groups) != len(spoken):
        return estimate(path, text) if path is not None else []
    return [{"w": label, "start": round(max(0.0, start - head_trim_s), 3),
             "end": round(max(0.0, end - head_trim_s), 3), "src": "tts"}
            for label, (start, end) in zip(labels, groups)]


def head_trim(raw_path: Path, processed_path: Path) -> float:
    raw = audio.speech_span(audio._levels(raw_path))
    processed = audio.speech_span(audio._levels(processed_path))
    return raw.start - processed.start if raw and processed else 0.0

"""Bounded PCM energy measurements; no engine, model or audio writes."""
import array
import math
import sys
import wave

from .. import words


def voiced(path, start, end):
    """Read only the requested span of our mono 16-bit PCM extraction."""
    levels = []
    with wave.open(str(path), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError('Speech timing requires mono 16-bit PCM')
        rate = wav.getframerate()
        first = min(wav.getnframes(), max(0, int(start * rate)))
        remaining = max(0, min(wav.getnframes(), int(end * rate)) - first)
        wav.setpos(first)
        frame = max(1, round(rate * words.FRAME))
        while remaining:
            data = array.array('h', wav.readframes(min(frame, remaining)))
            if sys.byteorder != 'little':
                data.byteswap()
            if not data:
                break
            rms = math.sqrt(sum(x*x for x in data) / len(data)) / 32768
            levels.append(20 * math.log10(max(rms, 1e-6)))
            remaining -= len(data)
    if not levels or max(levels) < -55:
        return []
    threshold = max(-55, max(levels) - 30)
    return [(start + a, min(end, start + b))
            for a, b in words._runs(levels, threshold) if start + a < end]


def segment_words(segment, path):
    raw = segment.get('words')
    if raw:
        return [{**w, 'src': 'stt'} for w in raw]
    runs = voiced(path, segment['start'], segment['end'])
    return [{**w, 'src': 'stt-seg'} for w in words.spread(segment['text'].split(), runs)]


def mark_turns(items, path, previous=None):
    """A turn is a pause with low measured energy, never a speaker identity."""
    for word in items:
        if previous is not None and word['start'] - previous['end'] >= .8:
            pause_start = max(previous['end'], word['start'] - 2)
            runs = voiced(path, pause_start, word['start'])
            active = sum(b-a for a, b in runs)
            if word['start'] - pause_start - active >= .6:
                word['turn'] = True
        previous = word

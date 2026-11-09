"""Adapters receive cached mono WAV; bounded decoding keeps engine clocks local."""
import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def window(path, start, end):
    with wave.open(str(path), 'rb') as source, tempfile.TemporaryDirectory() as root:
        rate = source.getframerate()
        offset = max(0, (start or 0) - 2)
        stop = min(source.getnframes() / rate, end + 2) if end is not None else source.getnframes() / rate
        source.setpos(int(offset * rate))
        target = Path(root) / 'window.wav'
        with wave.open(str(target), 'wb') as out:
            out.setparams(source.getparams())
            remaining = int((stop - offset) * rate)
            while remaining > 0:
                count = min(remaining, rate * 60)
                out.writeframes(source.readframes(count))
                remaining -= count
        yield target, offset


def normalize(segments, offset, start, end, cancel, context=False):
    for segment in segments:
        cancel()
        segment = dict(segment)
        segment['start'] += offset
        segment['end'] += offset
        segment['words'] = [{**w, 'start': w['start'] + offset, 'end': w['end'] + offset}
                            for w in segment.get('words', [])]
        lo = max(0, (start or 0) - (2 if context else 0))
        hi = float('inf') if end is None else end + (2 if context else 0)
        if segment['end'] <= lo or segment['start'] >= hi:
            continue
        segment['start'], segment['end'] = max(lo, segment['start']), min(hi, segment['end'])
        had_words = bool(segment['words'])
        segment['words'] = [{**w, 'start': max(lo, w['start']), 'end': min(hi, w['end'])}
                            for w in segment['words'] if lo <= (w['start'] + w['end']) / 2 < hi]
        if had_words and not segment['words']:
            continue
        yield segment


def local_model(model):
    path = Path(model).expanduser()
    if not path.exists():
        raise ValueError('Choose a downloaded local model path; transcription never downloads models')
    return str(path)

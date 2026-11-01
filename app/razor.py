"""Prepare non-destructive paragraph splits; publishing is done under the lock."""
from copy import deepcopy
import math
from pathlib import Path
import re

from . import audio, ffutil, tts, words
from .schema import Slide
from .config import WORDS_PER_MINUTE


def timings(root, take, text):
    items = take.get('words') or words.estimate(root / take['path'], text)
    tokens = text.split()
    if len(items) != len(tokens):
        items = _group_spoken(items, tokens)
    if len(items) != len(tokens) or any(w.get('w') != t for w, t in zip(items, tokens)):
        raise ValueError('Word timings do not match the narration; cannot safely split.')
    for item in items:
        a, b = float(item['start']), float(item['end'])
        if not math.isfinite(a) or not math.isfinite(b) or a < 0 or b < a:
            raise ValueError('Invalid word timings.')
    return items


def _group_spoken(items, tokens):
    """Timings in spoken words ("2017" -> "twenty seventeen") back onto the
    narration's words. Returns the input unchanged when the counts disagree."""
    counts = [max(1, len(tts.spoken_form(t).split())) for t in tokens]
    if sum(counts) != len(items):
        return items
    grouped, i = [], 0
    for token, n in zip(tokens, counts):
        part = items[i:i + n]
        grouped.append({**part[0], 'w': token, 'end': part[-1]['end']})
        i += n
    return grouped


def _nearest_pause(env, target, window=1.5, min_s=0.1):
    """Centre of the pause nearest `target`: a gap of at least `min_s`
    between voiced runs, as `words.estimate` finds them."""
    span = audio.speech_span(env)
    if not span:
        return None
    threshold = span.floor + (span.peak - span.floor) * 0.35
    runs = words._runs(env, threshold, merge_s=min_s)
    pauses = [((a_end + b_start) / 2, b_start - a_end)
              for (_, a_end), (b_start, _) in zip(runs, runs[1:])
              if b_start - a_end >= min_s]
    near = [(abs(c - target), -length, c) for c, length in pauses if abs(c - target) <= window]
    return min(near)[2] if near else None


def gap(items, index):
    a, b = float(items[index - 1]['end']), float(items[index]['start'])
    if b < a:
        raise ValueError('The words overlap; no safe gap to split.')
    return a, b


def text_clock(count):
    step = max(2.5, count / WORDS_PER_MINUTE * 60) / max(1, count)
    return [{'start': i * step, 'end': (i + 1) * step} for i in range(count)]


def boundary(text, items, at):
    tokens = list(re.finditer(r'\S+', text))
    ends = [i for i in range(1, len(tokens)) if tokens[i - 1][0][-1] in '.?!']
    if at is None:
        if not ends:
            raise ValueError('Not enough sentences to split.')
        return ends[(len(ends) - 1) // 2], False
    at = float(at)
    if not math.isfinite(at) or at < 0:
        raise ValueError('Split time must be finite and nonnegative.')
    # Match the unrecorded timeline paragraph duration.
    items = items or text_clock(len(tokens))
    candidates = []
    for i in range(1, len(tokens)):
        try:
            a, b = gap(items, i)
        except ValueError:
            continue
        candidates.append((i, abs((a + b) / 2 - at)))
    nearby = [(i, d) for i, d in candidates if i in ends and d <= 1.5]
    choices = nearby or candidates
    if not choices:
        raise ValueError('No word gap is available to split.')
    return min(choices, key=lambda x: x[1])[0], not bool(nearby)


def prepare(project, slide, root: Path, temp: Path, at):
    original = slide.narration
    active = timings(root, slide.take, original) if slide.take else None
    index, approximate = boundary(original, active, at)
    tokens = list(re.finditer(r'\S+', original))
    offset = tokens[index].start()
    head_text, tail_text = original[:offset].rstrip(), original[offset:]
    tail = Slide(**{key: deepcopy(getattr(slide, key)) for key in
                   ('section', 'beat', 'visual_note', 'queries', 'prefer_kind',
                    'candidates', 'chosen_id', 'locked_media')},
                 narration=tail_text, picture_mode='hold', gap_override=slide.gap_override)
    prepared = []
    active_cut = text_clock(len(tokens))[index]['start']
    for track, take in slide.takes.items():
        # TODO T7.1: split camera picture and voice together when camera takes land.
        if take.get('video'):
            raise ValueError('Camera take splitting is not supported yet.')
        items = timings(root, take, original)
        a, b = gap(items, index)
        target = (a + b) / 2
        source = root / take['path']
        duration = ffutil.duration(source)
        env = audio._levels(source)
        frames = [(n * audio.FRAME + audio.FRAME / 2, level)
                  for n, level in enumerate(env)
                  if max(a, target - .15) <= n * audio.FRAME + audio.FRAME / 2
                  <= min(b, target + .15)]
        cut = min(frames, key=lambda f: (f[1], abs(f[0] - target)))[0] if frames else target
        if not take.get('words'):
            # Estimated word times drift by up to a second on real takes, so
            # snap to the nearest real pause rather than trusting the gap.
            cut = _nearest_pause(env, target) or cut
        if track == project.voice_track:
            active_cut = cut
        if not 0 < cut < duration:
            raise ValueError('No safe interior cut in the recording.')
        for side, start, end, subset, text in (
                ('head', 0., cut, items[:index], head_text),
                ('tail', cut, duration, items[index:], tail_text)):
            out = temp / f'{len(prepared)}.wav'
            ffutil.run(['-ss', str(start), '-i', str(source), '-t', str(end - start),
                        '-vn', '-c:a', 'pcm_s16le', str(out)])
            rebased = [{**w, 'start': round(w['start'] - start, 6),
                        'end': round(w['end'] - start, 6)} for w in subset]
            value = {**deepcopy(take), 'raw_path': '', 'duration': ffutil.duration(out),
                     'words': rebased, 'narration': text,
                     'split_from': {'path': take['path'], 'start': start, 'end': end}}
            prepared.append((track, side, out, value))
    for fmt, cues in slide.cues.items():
        head_cues, tail_cues = [], []
        # Match occurrences in the original so a repeated anchor on both sides
        # stays with the first occurrence, as cue placement does.
        for cue in cues:
            anchor = str(cue.get('on', '')).strip()
            pos = original.casefold().find(anchor.casefold()) if anchor else -1
            value = deepcopy(cue)
            if pos >= offset and 'at' in value:
                value['at'] = max(0.0, float(value['at']) - active_cut)
            (tail_cues if pos >= offset else head_cues).append(value)
        slide.cues[fmt], tail.cues[fmt] = head_cues, tail_cues
    slide.needs_cues = not any(slide.cues.values())
    tail.needs_cues = not any(tail.cues.values())
    # Retire originals with their original narration before changing the text.
    for track in list(slide.takes):
        project.set_take(slide, track, None, reason='split')
    slide.narration = head_text
    slide.gap_override = 0.0
    project.slides.insert(project.slides.index(slide) + 1, tail)
    return tail, prepared, approximate

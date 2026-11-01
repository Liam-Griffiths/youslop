"""Non-destructive source-clock cuts; one clock for sound, picture and words."""
import math


def cut_ranges(take, *, duration=None):
    duration = float((take or {}).get('duration') or 0) if duration is None else duration
    ranges = []
    for cut in (take or {}).get('cuts', []):
        a, b = max(0., float(cut['a'])), min(duration, float(cut['b']))
        if b > a:
            ranges.append((a, b))
    merged = []
    for a, b in sorted(ranges):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def kept_ranges(take):
    end, result = 0., []
    for a, b in cut_ranges(take):
        if a > end:
            result.append((end, a))
        end = b
    duration = float((take or {}).get('duration') or 0)
    if end < duration:
        result.append((end, duration))
    return result


def take_duration(take):
    return float(round(sum(b - a for a, b in kept_ranges(take)), 6))


def take_words(take):
    """Drop words touched by a cut, rebase survivors; never mutate originals."""
    if not (take or {}).get('cuts'):
        return [dict(w) for w in (take or {}).get('words', [])]
    ranges, words, elapsed = kept_ranges(take), [], 0.
    for a, b in ranges:
        for w in (take or {}).get('words', []):
            if a <= w['start'] < b and w['end'] <= b:
                words.append({**w, 'start': round(elapsed + w['start'] - a, 6),
                              'end': round(elapsed + w['end'] - a, 6)})
        elapsed += b - a
    return words


def validate_cuts(take, cuts):
    if not isinstance(cuts, list):
        raise ValueError('Camera cuts must be a list')
    clean = []
    duration = float(take['duration'])
    for c in cuts:
        if (not isinstance(c, dict) or c.get('by') not in ('hand', 'auto')
                or any(isinstance(c.get(k), bool) or not isinstance(c.get(k), (int, float))
                       or not math.isfinite(c[k]) for k in ('a', 'b'))
                or not 0 <= c['a'] < c['b'] <= duration):
            raise ValueError('Each cut needs 0 <= a < b <= duration and by: hand or auto')
        clean.append({k: c[k] for k in ('a', 'b', 'by')})
    if take_duration({**take, 'cuts': clean}) < .02:
        raise ValueError('Keep at least 20 ms of the camera take')
    return clean


def audio_pieces(take, index):
    """Return a graph and label. Half-crossfade source handles keep the clock."""
    ranges = kept_ranges(take)
    n = len(ranges)
    fades = [min(.01, 2 * (b - a), 2 * (d - c))
             for (a, b), (c, d) in zip(ranges, ranges[1:])]
    graph = [f'[{index}:a]asplit={n}' + ''.join(f'[cs{index}_{j}]' for j in range(n))]
    for j, (a, b) in enumerate(ranges):
        a -= fades[j - 1] / 2 if j else 0
        b += fades[j] / 2 if j < n - 1 else 0
        graph.append(f'[cs{index}_{j}]atrim=start={a:.6f}:end={b:.6f},'
                     f'asetpts=PTS-STARTPTS[cp{index}_{j}]')
    label = f'cp{index}_0'
    for j in range(1, n):
        out = f'cj{index}_{j}'
        graph.append(f'[{label}][cp{index}_{j}]acrossfade=d={fades[j-1]:.6f}:c1=tri:c2=tri[{out}]')
        label = out
    return graph, label

"""Align padded decodes before clipping. Words in a repeated phrase stay ordered.

A seam uses the nearest shared lexical anchor within the two-second context,
matched one-to-one in sequence order. Keep the left decode through that anchor
and the right decode afterwards. Timestamp proximity breaks repeated-word ties.
With no lexical agreement retain midpoint ownership; recognition disagreements
cannot be resolved from timestamps alone. Never collapse adjacent equal words.
"""
import math
import re


def clip(items, start, end):
    selected = [w for w in items if math.isfinite(w['start']) and math.isfinite(w['end'])
                and w['end'] > w['start'] and start <= (w['start']+w['end'])/2 < end]
    epsilon = min(.001, (end-start) / (2*len(selected))) if selected else .001
    result, cursor = [], start
    for w in selected:
        a = max(cursor, start, w['start'])
        b = max(w['end'], a + epsilon)
        result.append({**w, 'start': a, 'end': b})
        cursor = b
    # Work backwards at the outer range edge, rather than dropping a jittered
    # word whose forward correction would push it beyond the requested end.
    cursor = end
    for w in reversed(result):
        w['end'] = min(w['end'], cursor)
        w['start'] = min(w['start'], w['end'] - epsilon)
        cursor = w['start']
    return result


def join(left, right, boundary):
    """Splice on a shared word, retaining its left timing and metadata."""
    li = [i for i,w in enumerate(left) if abs((w['start']+w['end'])/2-boundary) < 2]
    ri = [i for i,w in enumerate(right) if abs((w['start']+w['end'])/2-boundary) < 2]
    key = lambda w: re.sub(r'\W+', '', w['w']).casefold()
    # Time-constrained LCS; minimum timestamp distance disambiguates repetitions.
    table = {}
    for a in range(len(li)-1, -1, -1):
        for b in range(len(ri)-1, -1, -1):
            candidates = [table.get((a+1,b), (0,0,[])), table.get((a,b+1), (0,0,[]))]
            x,y = left[li[a]], right[ri[b]]
            distance = abs((x['start']+x['end']-y['start']-y['end'])/2)
            if key(x) and key(x) == key(y) and distance <= 2:
                n,cost,pairs = table.get((a+1,b+1), (0,0,[]))
                candidates.append((n+1,cost-distance,[(li[a],ri[b])]+pairs))
            table[a,b] = max(candidates, key=lambda v: v[:2])
    pairs = table.get((0,0), (0,0,[]))[2]
    if pairs:
        i,j = min(pairs, key=lambda pair: abs((left[pair[0]]['start']+left[pair[0]]['end'])/2-boundary))
        return left[:i+1] + right[j+1:]
    return ([w for w in left if (w['start']+w['end'])/2 < boundary] +
            [w for w in right if (w['start']+w['end'])/2 >= boundary])

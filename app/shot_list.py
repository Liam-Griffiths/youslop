"""Deterministic filming checklist and provisional label-overlap coverage."""
import re

from .schema import PlannedShot

_STOP = set('a an the of at in on to from with and or by for into show shows showing '
            'shot shots view camera film filming capture static pan over across '
            'wide medium close up closeup insert detail'.split())


def terms(text):
    return set(re.findall(r"[^\W_]+", text.casefold())) - _STOP


def shot_size(note):
    for size, pattern in [('insert', r'\b(insert|detail)\b'),
                          ('close', r'\b(close(?:[ -]?up)?)\b'),
                          ('wide', r'\bwide\b')]:
        if re.search(pattern, note, re.I):
            return size
    return 'medium'


def build(project):
    """Merge adjacent notes at >= 50% shared terms, with identical framing.

    Compare to the preceding note, not an expanding bag of earlier subjects.
    A paragraph without a visual note breaks adjacency. Preserve checked shots
    only when their paragraph ids, notes and framing are unchanged.
    """
    shots, previous = [], set()
    for slide in project.slides:
        note = slide.visual_note.strip()
        if not note:
            previous = set()
            continue
        words, size = terms(note), shot_size(note)
        union = words | previous
        if (shots and previous and shots[-1].size == size and union
                and len(words & previous) / len(union) >= .5):
            shots[-1].paragraph_ids.append(slide.id)
            shots[-1].notes.append(note)
        else:
            shots.append(PlannedShot([slide.id], size, [note]))
        previous = words
    checked = {(tuple(s.paragraph_ids), s.size, tuple(s.notes))
               for s in project.shot_list if s.done}
    for shot in shots:
        shot.done = (tuple(shot.paragraph_ids), shot.size, tuple(shot.notes)) in checked
    return shots


def coverage(shot, shoot):
    """Covered: >= 60% of note terms in one clip; maybe: any overlap.

    Only subject/location/place suggestions and searchable labels participate.
    Framing alone cannot count as coverage. No clip or source is modified.
    """
    wanted = terms(' '.join(shot.notes))
    matches = []
    for clip in shoot.clips:
        labels = clip.labels + [clip.auto_labels.get(k, '')
                                for k in ('subject', 'location', 'place')]
        overlap = wanted & terms(' '.join(labels))
        if overlap:
            matches.append(dict(clip_id=clip.id, score=len(overlap) / len(wanted)))
    matches.sort(key=lambda m: (-m['score'], m['clip_id']))
    status = 'covered' if matches and matches[0]['score'] >= .6 else 'maybe' if matches else 'missing'
    return dict(status=status, matches=matches)

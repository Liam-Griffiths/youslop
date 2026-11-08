"""Offline clip matching and resolution; originals never enter project media/."""
from __future__ import annotations

import json
import math

from .. import footage
from ..schema import MediaCandidate
from .base import PROVIDER_WEIGHT, tokens


def _tokens(text):
    return {w[:-1] if w.endswith('s') and len(w) > 3 else w for w in tokens(text)}


def suggestions(text: str, limit: int = 20, *, rerank: bool = False):
    query = _tokens(text)
    found = []
    for shoot in footage.list_shoots():
        sources = {f.id: f for f in shoot.files}
        for clip in shoot.clips:
            if clip.rejected or clip.file not in sources or clip.out_s <= clip.in_s:
                continue
            source = sources[clip.file]
            labels = list(dict.fromkeys(clip.labels + [str(v) for k, v in clip.auto_labels.items()
                                                       if not k.startswith('_') and isinstance(v, str)]))
            description = ' '.join(labels + [clip.note])
            # Vocabulary expands a matching place name only; unrelated shoot-wide
            # vocabulary must not make every clip appear to match every place.
            vocabulary = [v for v in shoot.vocabulary if _tokens(v) & _tokens(description)]
            overlap = len(query & _tokens(description + ' ' + ' '.join(vocabulary)))
            rank = PROVIDER_WEIGHT['footage'] + overlap * 2
            rank += .3 * clip.starred + .2 * (clip.best_take == clip.id)
            rank -= 1 if clip.quality.get('usable') is False else 0
            root = f'/api/footage/shoots/{shoot.id}/media'
            found.append(cand := MediaCandidate(
                id=f'ft{shoot.id}_{clip.id}', provider='footage', kind='video',
                title=description or clip.id, url=f'{root}/proxies/{source.id}.mp4',
                thumb=(f'{root}/thumbs/{clip.thumbs[0]}' if clip.thumbs else
                       f'{root}/sprites/{source.id}.jpg'),
                shoot_id=shoot.id, clip_id=clip.id, in_s=clip.in_s, out_s=clip.out_s,
                duration=clip.out_s - clip.in_s, width=source.width, height=source.height,
                license='Your footage', author='you', score=rank, query=text,
                labels=labels))
            cand.matched = overlap  # Not saved; lets fill skip clips that share no words.
    found.sort(key=lambda c: c.score, reverse=True)
    if rerank and found:
        from .. import llm
        top = found[:20]
        ids = [c.id for c in top]
        order = llm.complete_json(
            'Rank these footage candidates for the paragraph; return an array of IDs. '
            + json.dumps({'paragraph': text, 'clips': [{'id': c.id, 'text': c.title} for c in top]}),
            retries=0, allow_search=False,
            require=lambda r: isinstance(r, list) and len(r) == len(ids)
            and all(isinstance(i, str) for i in r) and set(r) == set(ids))
        if (isinstance(order, list) and len(order) == len(ids)
                and all(isinstance(i, str) for i in order) and set(order) == set(ids)):
            by_id = {c.id: c for c in top}
            found = [by_id[i] for i in order] + found[20:]
    return found[:limit]


def fill(project, *, overwrite=False, rerank=False):
    used = {c['id'] for s in project.slides for c in s.candidates
            if c['id'] == s.chosen_id and c.get('provider') == 'footage'}
    count = 0
    for slide in project.slides:
        if slide.on_camera or (slide.chosen_id and not overwrite) or slide.locked_media:
            continue
        # Only clips that share a word with the paragraph: an unrelated clip is
        # worse than leaving the paragraph for archives or the user.
        options = [c for c in suggestions(slide.narration + ' ' + slide.visual_note,
                                          limit=100000, rerank=rerank) if c.matched]
        chosen = next((c for c in options if c.id not in used), options[0] if options else None)
        if chosen:
            slide.candidates = [chosen.to_dict()] + [c for c in slide.candidates if c['id'] != chosen.id]
            slide.chosen_id = chosen.id
            used.add(chosen.id)
            from ..overlay_plan import apply
            apply(project, slide)
            count += 1
    return count


def resolve(candidate, *, preview=False, progress=lambda m: None):
    """Resolve only manifest-owned IDs and validate the saved edit range."""
    try:
        shoot = footage.load(candidate.get('shoot_id', ''))
        clip = next(c for c in shoot.clips if c.id == candidate.get('clip_id'))
        source = next(f for f in shoot.files if f.id == clip.file)
        start, end = candidate.get('in_s'), candidate.get('out_s')
        if not (isinstance(start, (int, float)) and isinstance(end, (int, float))
                and math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= source.duration):
            return None
        if not preview:
            original = footage.source_path(shoot, source)
            if original.is_file():
                return original
            progress(f'Warning: footage original missing ({shoot.id}/{clip.id}); using proxy if available')
        return footage.media_path(shoot.id, 'proxies', source.id + '.mp4')
    except (OSError, ValueError, StopIteration):
        return None

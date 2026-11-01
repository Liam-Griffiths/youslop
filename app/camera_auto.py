"""Explicit, cached camera rough cuts. Slow work happens outside the store lock."""
from copy import deepcopy
import hashlib
import json
import re

from . import camera, check, llm, media, store
from .camera_overlays import validate
from .take_edits import take_duration, take_words, validate_cuts


def plan(project, slides):
    """Reviewable candidate/word proposals, batched like the existing cue planner."""
    result = {}
    for start in range(0, len(slides), 8):
        chunk = slides[start:start + 8]
        listing = [dict(id=s.id, narration=s.narration, queries=s.queries,
                        candidates=[dict(id=c['id'], title=c.get('title', '')) for c in s.candidates]) for s in chunk]
        proposals = llm.complete_json('Propose camera cutaways using the visual search queries and '
            'ONLY these candidate ids. Anchor on an exact narration word/phrase. Return a JSON '
            'list of {id, cutaways:[{on, candidate_id, dur}]} (dur in seconds). Use [] if no match.\n'
            + json.dumps(listing))
        for entry in proposals if isinstance(proposals, list) else []:
            if isinstance(entry, dict):
                items = entry.get('cutaways')
                result[entry.get('id')] = [v for v in items if isinstance(v, dict)][:32] if isinstance(items, list) else []
    return result


def edit(pid, payload, progress=lambda message: None):
    project = store.load(pid)
    slides = [s for s in project.slides if s.on_camera and s.takes.get('camera')
              and (not payload.get('sid') or s.id == payload['sid'])]
    undo, suggest = payload.get('undo', False), payload.get('suggest', False)
    signature = lambda s: hashlib.sha256(s.narration.encode()).hexdigest()
    pending = [s for s in slides if not s.takes['camera'].get('overlays')
               and s.takes['camera'].get('cutaway_cache', {}).get('text') != signature(s)]
    proposals = plan(project, pending) if pending and not undo else {}
    changed, review = [], {}
    for slide in slides:
        old = slide.takes['camera']
        pauses = [] if undo or suggest else camera.suggest_cuts({**old, 'path': str(store.project_dir(pid) / old['path'])})
        cache = old.get('cutaway_cache', {})
        if cache.get('text') != signature(slide):
            cache = {}
        if slide in pending and not undo:
            cache = dict(text=signature(slide), items=proposals.get(slide.id, []))
        downloaded = {}
        if not undo and not suggest:
            for item in cache.get('items', []):
                candidate = next((c for c in slide.candidates if c['id'] == item.get('candidate_id')), None)
                if candidate and not (store.project_dir(pid) / candidate.get('local_path', '')).is_file():
                    try:
                        name = media.download_to(media.upgrade(candidate), store.project_dir(pid) / 'media')
                        downloaded[candidate['id']] = 'media/' + name
                    except Exception:
                        progress('Skipped unavailable cutaway media')
        with store.lock_for(pid):
            fresh = store.load(pid)
            s = next((s for s in fresh.slides if s.id == slide.id), None)
            if not s or not s.on_camera or s.narration != slide.narration or s.takes.get('camera') != old:
                continue  # The creator edited while the planner/analysis was running.
            take = s.takes['camera']
            before = deepcopy(take)
            if suggest:
                take['cutaway_cache'] = cache
                review[s.id] = cache.get('items', [])
                fresh.set_take(s, 'camera', take)
                store.save(fresh)
                continue
            if undo:
                for key in ('cuts', 'overlays'):
                    if key in take:
                        take[key] = [r for r in take[key] if r.get('by', 'hand') != 'auto']
            else:
                cuts = list(take.get('cuts', []))
                for r in pauses:
                    if not any(r['a'] < c['b'] and r['b'] > c['a'] for c in cuts):
                        try:
                            proposed = validate_cuts(take, [*cuts, {**r, 'by': 'auto'}])
                            hand_end = max((o['at']+o['dur'] for o in take.get('overlays', []) if o.get('by', 'hand') == 'hand'), default=0)
                            if take_duration({**take, 'cuts': proposed}) >= hand_end:
                                cuts = proposed
                        except ValueError:
                            pass
                take['cuts'] = cuts
                take['cutaway_cache'] = cache
                for c in s.candidates:
                    if c['id'] in downloaded:
                        c['local_path'] = downloaded[c['id']]
                overlays = [v for o in take.get('overlays', [])
                            for v in ([o] if o.get('by', 'hand') == 'hand' else validate(take, [o]))]
                words = take_words(take)
                for item in cache.get('items', []):
                    tokens = lambda text: re.findall(r"[\w’']+", text.casefold())
                    anchor = tokens(str(item.get('on', '')))
                    at = next((w['start'] for i, w in enumerate(words) if anchor and
                               [token for v in words[i:i+len(anchor)] for token in tokens(v['w'])] == anchor), None)
                    c = next((c for c in s.candidates if c['id'] == item.get('candidate_id')), {})
                    if at is None or not c.get('local_path') or not (store.project_dir(pid) / c['local_path']).is_file():
                        continue
                    try:
                        proposed = validate(take, [*overlays, dict(at=at, dur=item.get('dur', 3),
                            kind='cutaway', source=dict(candidate_id=c['id']), by='auto')])
                        if len(proposed) > len(overlays):
                            overlays.append(proposed[-1])
                    except ValueError:
                        pass  # Only fill unoccupied spans; preserve hand edits exactly.
                take['overlays'] = overlays
            fresh.set_take(s, 'camera', take)
            if any(before.get(k, []) != take.get(k, []) for k in ('cuts', 'overlays')):
                changed.append(s.id)
            store.save(fresh)
    return dict(changed=changed, proposals=review, check=check.run(store.load(pid)))

"""Atomic main-track edits. Only project metadata moves; files stay put."""
from copy import deepcopy

from . import render
from .edits import EditError
from .schema import group_slides


def apply(project, payload):
    if project.kind == 'clip':
        raise EditError('Source-linked clips have no editable main track.')
    op, ids, to = (payload.get(k) for k in ('op', 'ids', 'to'))
    if op not in ('move', 'delete') or not isinstance(ids, list) or not ids or any(
            not isinstance(sid, str) for sid in ids) or len(set(ids)) != len(ids):
        raise EditError('Expected move or delete and unique main-track ids.')
    if type(payload.get('version')) not in (int, float):
        raise EditError('Expected the project version from selection time.')
    if payload['version'] != project.updated_at:
        raise EditError('Project changed; select the section again.', 409)
    order = [s.id for s in project.slides]
    if any(sid not in order for sid in ids):
        raise EditError('Main track changed; select the section again.', 409)
    start = order.index(ids[0])
    if order[start:start + len(ids)] != ids:
        raise EditError('Select a contiguous section in timeline order.')
    if op == 'move' and (not isinstance(to, str) or to and to not in order):
        raise EditError('Unknown destination boundary.')
    chosen = set(ids)
    remaining = [s for s in project.slides if s.id not in chosen]
    if op == 'move':
        if to in chosen or (order[start + len(ids):] or [''])[0] == to:
            return '', ''
        index = next((i for i, s in enumerate(remaining) if s.id == to), len(remaining))
        rows = remaining[:index] + project.slides[start:start + len(ids)] + remaining[index:]
        if sorted(s.id for s in rows) != sorted(order):
            raise EditError('Move must preserve every main-track row.')
    else:
        rows = remaining
    # Pin only time-based mid reads; pre/end retain their placement rules.
    placed = render._sponsor_placements(project, render._slide_durations(project, True))
    anchors = {slot.id: sid for sid, slots in placed.items() for slot in slots}
    for slot in project.sponsors:
        if not slot.enabled or slot.placement != 'mid' or slot.after_slide_id:
            continue
        anchor = anchors.get(slot.id)
        if anchor:
            slot.placement, slot.after_slide_id = 'mid', anchor
    if op == 'delete':
        project.sponsors = [s for s in project.sponsors
                            if s.placement != 'mid' or s.after_slide_id not in chosen]
    # Keep each original picture run, splitting only where rows were separated.
    runs = group_slides(project.slides, project.style.picture_every)
    source = {s.id: (run[0], n, i) for n, run in enumerate(runs) for i, s in enumerate(run)}
    previous, split = None, False
    for row in rows:
        lead, run, offset = source[row.id]
        continues = previous == (run, offset - 1)
        row.picture_mode = 'hold' if continues else 'new'
        if not continues and row.id != lead.id:
            split = True
            # A new fragment retains the picture that was on screen. Narration,
            # takes, titles, cues, overlays and chapter fields remain its own.
            for key in ('kind', 'prefer_kind', 'candidates', 'chosen_id', 'locked_media',
                        'map_place', 'map_lat', 'map_lon', 'map_zoom', 'map_kind',
                        'map_style', 'diagram', 'custom', 'custom_html', 'shot'):
                setattr(row, key, deepcopy(getattr(lead, key)))
        previous = (run, offset)
    project.slides = rows
    paragraphs = sum(not s.insert for run in runs for s in run if s.id in chosen)
    inserts = len(ids) - paragraphs
    counts = [f'{n} {name}{"s" if n != 1 else ""}' for n, name in
              ((paragraphs, 'paragraph'), (inserts, 'insert')) if n]
    label = ('Moved ' if op == 'move' else 'Deleted ') + ' and '.join(counts)
    return label, 'Picture group split; each fragment keeps its picture.' if split else ''

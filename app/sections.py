"""Atomic main-track edits. Only project metadata moves; files stay put."""
from copy import deepcopy

from . import render
from .edits import EditError
from .schema import Slide, SponsorSlot, _uid, group_slides


def _fragments(rows, runs):
    source = {s.id: (run[0], n, i) for n, run in enumerate(runs) for i, s in enumerate(run)}
    previous, split = None, False
    for row in rows:
        lead, run, offset = source[row.id]
        continues = previous == (run, offset - 1)
        row.picture_mode = 'hold' if continues else 'new'
        if not continues and row.id != lead.id:
            split = True
            for key in ('kind', 'prefer_kind', 'candidates', 'chosen_id', 'locked_media',
                        'map_place', 'map_lat', 'map_lon', 'map_zoom', 'map_kind',
                        'map_style', 'diagram', 'custom', 'custom_html', 'shot'):
                setattr(row, key, deepcopy(getattr(lead, key)))
        previous = (run, offset)
    return split


def _anchors(project):
    placed = render._sponsor_placements(project, render._slide_durations(project, True))
    anchors = {slot.id: sid for sid, slots in placed.items() for slot in slots}
    return {s.id: (s.after_slide_id if s.placement == 'mid' and s.after_slide_id
                   else anchors.get(s.id)) for s in project.sponsors}


def capture(project, ids):
    rows = deepcopy([s for s in project.slides if s.id in ids])
    _fragments(rows, group_slides(project.slides, project.style.picture_every))
    anchors = _anchors(project)
    slots = []
    for slot in project.sponsors:
        if anchors.get(slot.id) in ids:
            clone = deepcopy(slot)
            clone.placement, clone.after_slide_id = 'mid', anchors[slot.id]
            slots.append(clone.to_dict())
    return dict(project_id=project.id, slides=[s.to_dict() for s in rows], sponsors=slots)


def _copies(project, snapshot):
    # Clipboard paths are project-relative: never paste them into another root.
    if not isinstance(snapshot, dict) or snapshot.get('project_id') != project.id:
        raise EditError('Copy a section from this project first.')
    if not isinstance(snapshot.get('slides'), list) or not isinstance(snapshot.get('sponsors'), list):
        raise EditError('Invalid section clipboard.')
    try:
        rows = [Slide.from_dict(s) for s in deepcopy(snapshot['slides'])]
        slots = [SponsorSlot.from_dict(s) for s in deepcopy(snapshot['sponsors'])]
        ids = [s.id for s in rows]
        if not ids or any(not isinstance(sid, str) for sid in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid clipboard rows')
        mapping = {sid: _uid('s') for sid in ids}
        for row in rows:
            if row.narration and not row.insert:
                row.duplicate_of = row.duplicate_of or row.id
            row.id = mapping[row.id]
            for graphic in row.overlays:
                graphic['id'] = _uid('g')
        for slot in slots:
            slot.id = _uid('sponsor')
            slot.after_slide_id = mapping[slot.after_slide_id]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise EditError('Invalid section clipboard.') from exc
    return rows, slots


def apply(project, payload):
    if project.kind == 'clip':
        raise EditError('Source-linked clips have no editable main track.')
    op, ids, to = (payload.get(k) for k in ('op', 'ids', 'to'))
    if op not in ('move', 'delete', 'cut', 'copy', 'paste', 'duplicate', 'add'):
        raise EditError('Unknown section operation.')
    if op not in ('paste', 'add') and (not isinstance(ids, list) or not ids or any(
            not isinstance(sid, str) for sid in ids) or len(set(ids)) != len(ids)):
        raise EditError('Expected unique main-track ids.')
    if type(payload.get('version')) not in (int, float):
        raise EditError('Expected the project version from selection time.')
    if payload['version'] != project.updated_at:
        raise EditError('Project changed; select the section again.', 409)
    order = [s.id for s in project.slides]
    if op not in ('paste', 'add'):
        if any(sid not in order for sid in ids):
            raise EditError('Main track changed; select the section again.', 409)
        start = order.index(ids[0])
        if order[start:start + len(ids)] != ids:
            raise EditError('Select a contiguous section in timeline order.')
    if op == 'copy':
        return '', ''  # The route returns capture() without saving.
    if op in ('move', 'paste', 'add') and (not isinstance(to, str) or to and to not in order):
        raise EditError('Unknown destination boundary.')
    chapter = payload.get('chapter')
    if chapter is not None and (op not in ('move', 'add') or not isinstance(chapter, str)):
        raise EditError('Chapter must be text on a move or add.')
    if op == 'add' and chapter is None:
        raise EditError('New shot needs a chapter.')
    labels, label = {}, ''
    for row in project.slides:
        label = row.chapter or label
        labels[row.id] = label
    runs = group_slides(project.slides, project.style.picture_every)
    if op == 'add':
        new = Slide(picture_mode='new')
        index = order.index(to) if to else len(order)
        rows = project.slides[:index] + [new] + project.slides[index:]
        runs += [[new]]
        chosen = {new.id}
    elif op in ('paste', 'duplicate'):
        snapshot = capture(project, ids) if op == 'duplicate' else payload.get('clipboard')
        copies, slots = _copies(project, snapshot)
        if op == 'duplicate':
            to = (order[start + len(ids):] or [''])[0]
        index = order.index(to) if to else len(order)
        rows = project.slides[:index] + copies + project.slides[index:]
        runs += group_slides(copies, project.style.picture_every)
        chosen = {s.id for s in copies}
    else:
        chosen = set(ids)
    remaining = [s for s in project.slides if s.id not in chosen]
    if op == 'move':
        if to in chosen:
            if chapter is None:
                return '', ''
            to = (order[start + len(ids):] or [''])[0]
        if chapter is None and (order[start + len(ids):] or [''])[0] == to:
            return '', ''
        index = next((i for i, s in enumerate(remaining) if s.id == to), len(remaining))
        rows = remaining[:index] + project.slides[start:start + len(ids)] + remaining[index:]
        if sorted(s.id for s in rows) != sorted(order):
            raise EditError('Move must preserve every main-track row.')
    elif op in ('delete', 'cut'):
        rows = remaining
    # Pin only time-based mid reads; pre/end retain their placement rules.
    anchors = _anchors(project)
    for slot in project.sponsors:
        if not slot.enabled or slot.placement != 'mid' or slot.after_slide_id:
            continue
        anchor = anchors.get(slot.id)
        if anchor:
            slot.placement, slot.after_slide_id = 'mid', anchor
    if op == 'cut':
        project.sponsors = [s for s in project.sponsors if anchors.get(s.id) not in chosen]
    elif op == 'delete':
        project.sponsors = [s for s in project.sponsors
                            if s.placement != 'mid' or s.after_slide_id not in chosen]
    if op in ('paste', 'duplicate'):
        project.sponsors.extend(slots)
    if chapter is not None:
        previous = None
        for row in rows:
            current = chapter if row.id in chosen else labels[row.id]
            row.chapter = current if current != previous else ''
            previous = current
    split = _fragments(rows, runs)
    project.slides = rows
    paragraphs = sum(not s.insert for run in runs for s in run if s.id in chosen)
    inserts = len(chosen) - paragraphs
    counts = [f'{n} {name}{"s" if n != 1 else ""}' for n, name in
              ((paragraphs, 'paragraph'), (inserts, 'insert')) if n]
    verb = dict(add='Added', move='Moved', delete='Deleted', cut='Cut', paste='Pasted', duplicate='Duplicated')[op]
    label = verb + ' ' + ' and '.join(counts)
    return label, 'Picture group split; each fragment keeps its picture.' if split else ''

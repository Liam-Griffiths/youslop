"""Project track metadata derived from the existing, render-free timeline.

Derived tracks and resolved item references are views, never migrations. The
legacy role dictionary remains available to check and inspector consumers.
"""
from .schema import Layer, LAYER_ROLES


_COLORS = dict(zip(LAYER_ROLES, (
    'ink-2', 'cool', 'cool', 'accent', 'accent', 'ink',
    'good', 'warn', 'good', 'warn', 'dim')))


def note_items(total, findings, report):
    """The same check/review ticks used by the Edit API, including decisions."""
    from . import review
    notes = []
    for finding in findings:
        ident = finding.get('id') or review.note_id(finding)
        decision = next((n for n in report.get('notes', [])
                         if n.get('source') == 'check' and n.get('id') == ident), {})
        notes.append(dict(finding, id=ident, text=finding['msg'], severity=finding['level'],
                          source='check', state=finding.get('state', decision.get('state', 'open'))))
    notes += [n for n in report.get('notes', []) if n.get('source') != 'check']
    notes += report.get('warnings_kept', [])
    weakest = report.get('weakest')
    if weakest:
        notes.append(dict(weakest, id='weakest', problem=weakest['why'], severity='P2'))
    items = []
    for i, note in enumerate(notes):
        if note.get('state', 'open') not in ('open', 'kept'):
            continue
        t = max(0, float(note.get('t', 0)))
        items.append(dict(id=note.get('id', f'note:{i}'), sid=note.get('slide_id', ''),
            t0=t, t1=min(total, t + .8), kind='note', src=note.get('source', 'review'),
            text=note.get('text') or note.get('problem', ''), severity=note.get('severity', 'P2')))
    return items


def role_items(project, timeline=None):
    """Reuse actual spans: a populated schema field need not be a visible item.

    Supplying the completed API timeline reuses its check/review work. Without
    one, compute the same render-free spans and note decisions locally.
    """
    if timeline is None:
        from . import check, render, review
        timeline = render.timeline(project)
        timeline['layers']['notes'] = note_items(
            timeline['total'], check.run(project)['findings'], review.read_notes(project.id))
    items = {role: list(timeline.get('layers', {}).get(role, [])) for role in LAYER_ROLES}
    # Match tlLayerRows: essay captions currently share the titles contract.
    if project.style.format == 'essay':
        items['captions'], items['titles'] = items['titles'], []
    for seg in timeline['segments']:
        items['pictures'].append(dict(id=seg['ref'], sid=seg.get('lead', ''),
            t0=seg['start'], t1=seg['start'] + seg['duration'], kind='picture',
            text=seg.get('script') or seg.get('type', 'picture')))
        for paragraph in seg.get('paragraphs', []):
            items['voice'].append(dict(id=paragraph['id'], sid=paragraph['id'],
                t0=paragraph['start'], t1=paragraph['start'] + paragraph['duration'],
                kind='paragraph', text=paragraph['text']))
    return items


def _derived(items):
    return [Layer(id=role, name=role.capitalize(), role=role, color=_COLORS[role], order=i)
            for i, role in enumerate(LAYER_ROLES)
            if role in ('pictures', 'voice') or items.get(role)]


def effective(project, *, items=None):
    """Saved layers in stable order, or today's lanes with empty roles omitted.

    `items` is an optional role -> spans mapping from role_items, so callers
    which already planned the timeline do not repeat that work.
    """
    if project.layers:
        if len({layer.id for layer in project.layers}) != len(project.layers):
            raise ValueError('Layer ids must be unique')
        return sorted(project.layers, key=lambda layer: layer.order)
    return _derived(role_items(project) if items is None else items)


def resolve(layers, role, ident=''):
    """Unknown, missing or wrong-role ids fall back within the item's role."""
    candidates = [layer for layer in layers if layer.role == role]
    return next((layer for layer in candidates if layer.id == ident),
                candidates[0] if candidates else None)


def rows(project, timeline):
    """Additive API view; do not mutate stored items or the legacy dictionary."""
    items = role_items(project, timeline)
    layers = effective(project, items=items)
    # A partial saved configuration must not orphan existing content. These
    # fallback tracks, like old-project derivation, are never saved implicitly.
    roles = {layer.role for layer in layers}
    layers = list(layers)
    used = {layer.id for layer in layers}
    for layer in _derived(items):
        if layer.role in roles:
            continue
        while layer.id in used:
            layer.id = f'derived:{layer.id}'
        used.add(layer.id)
        layers.append(layer)
    result = [dict(layer.to_dict(), items=[]) for layer in layers]
    by_id = {row['id']: row for row in result}
    for role, spans in items.items():
        for item in spans:
            layer = resolve(layers, role, item.get('layer', ''))
            by_id[layer.id]['items'].append(dict(item, layer=layer.id))
    return result


def graphics_order(project, group):
    """Stable item permutation, bottom to top; later project tracks win.

    Preserve paragraph/list order within a track, including anchor resolution.
    Unknown references use the first graphics track without changing storage.
    This is also the cache dependency: names, colours and locks aren't pixels.
    """
    tracks = [layer for layer in effective(project, items={}) if layer.role == 'graphics']
    ranks = {layer.id: i for i, layer in enumerate(tracks)}
    items = [(i, j) for i, (slide, _) in enumerate(group) for j in range(len(slide.overlays))]
    def rank(pair):
        item = group[pair[0]][0].overlays[pair[1]]
        track = resolve(tracks, 'graphics', item.get('layer', ''))
        return ranks[track.id] if track else 0
    return sorted(items, key=rank)


def graphics_cache_order(project, group):
    """No extra cache data when composition still matches the legacy order."""
    order = graphics_order(project, group)
    original = [(i, j) for i, (slide, _) in enumerate(group) for j in range(len(slide.overlays))]
    return order if order != original else []

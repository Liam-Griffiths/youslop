"""Project track metadata derived from the existing, render-free timeline.

Derived tracks and resolved item references are views, never migrations. The
legacy role dictionary remains available to check and inspector consumers.
"""
from .schema import Layer, LAYER_ROLES, Slide


_COLORS = dict(zip(LAYER_ROLES, (
    'ink-2', 'cool', 'cool', 'accent', 'accent', 'ink',
    'good', 'warn', 'good', 'warn', 'dim')))


class LockedLayerError(RuntimeError):
    """Separate from validation errors so legacy ValueError handlers keep 409."""


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


def rows(project, timeline=None):
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
        layer.order = max((track.order for track in layers), default=-1) + 1
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


class Visibility(frozenset):
    """Resolved preview tracks. Bare ids win over legacy role aliases.

    `role:<name>` explicitly addresses a role when an id shadows its name.
    Cache tokens include resolution order; default renders keep an empty set.
    """
    def __new__(cls, project, requested=(), *, final=False):
        if isinstance(requested, cls):
            return requested
        tracks = list(effective(project, items={}))
        used = {t.id for t in tracks}
        for role in LAYER_ROLES:
            if any(t.role == role for t in tracks):
                continue
            ident = role
            while ident in used:
                ident = 'derived:' + ident
            used.add(ident)
            tracks.append(Layer(id=ident, role=role))
        ids = {t.id for t in tracks if t.hidden and (not final or project.hide_in_render)}
        for token in requested:
            if token in {t.id for t in project.layers} or token not in LAYER_ROLES and token in used:
                ids.add(token)
            else:
                role = token.removeprefix('role:')
                if role not in LAYER_ROLES:
                    raise ValueError('Unknown preview layer')
                roles = {role, 'captions'} if role == 'titles' else {role}
                ids.update(t.id for t in tracks if t.role in roles)
        tokens = {'id:' + ident for ident in ids}
        if ids:
            import hashlib, json
            tokens.add('resolve:' + hashlib.sha1(json.dumps(
                [(t.id, t.role) for t in tracks] + [project.music_layer]).encode()).hexdigest()[:12])
        obj = super().__new__(cls, tokens)
        obj.tracks, obj.ids = tracks, ids
        return obj

    def __reduce__(self):
        return (_restore_visibility, (tuple(self), self.tracks, self.ids))

    def item(self, role, ident=''):
        track = resolve(self.tracks, role, ident)
        return bool(track and track.id in self.ids)

    def __contains__(self, role):
        if role in {'cues', 'graphics'}:
            return all(t.id in self.ids for t in self.tracks if t.role == role)
        return self.item(role)


def _restore_visibility(tokens, tracks, ids):
    obj = frozenset.__new__(Visibility, tokens)
    obj.tracks, obj.ids = tracks, ids
    return obj


def visibility(project, requested=(), *, final=False):
    return Visibility(project, requested, final=final)


def visible_stings(project, stings, hide):
    hide = visibility(project, hide)
    return {role: entry for role, entry in stings.items() if not hide.item('stings',
        getattr(getattr(entry[1], '_spec', entry[1]),
                'music_layer' if role == 'intro' else 'sting_layer', ''))}


def patch_flags(project, ident, patch):
    """Materialize the drawing view only on an explicit layer edit."""
    from .edits import EditError
    if not patch or set(patch) - {'hidden', 'locked'} or any(type(v) is not bool for v in patch.values()):
        raise EditError('Layer hidden and locked settings must be booleans.')
    tracks = [Layer.from_dict(row) for row in rows(project)]
    target = next((layer for layer in tracks if layer.id == ident), None)
    if target is None:
        raise EditError('No such layer.', 404)
    for key, value in patch.items():
        setattr(target, key, value)
    project.layers = tracks


def _locked_message(layer):
    return f'{layer.role.capitalize()} layer “{layer.name}” is locked. Unlock it in Edit before editing.'


def require_unlocked(project, role, ident=''):
    """Preflight only the role(s) an operation changes, including external writes."""
    tracks = effective(project, items={})
    for kind in (role,) if isinstance(role, str) else role:
        track = resolve(tracks, kind, ident)
        if track and track.locked:
            raise LockedLayerError(_locked_message(track))


def assert_unlocked(before, after):
    """Check the complete proposed save, including both ends of item moves.

    The persistence boundary covers HTTP, tools and background jobs equally.
    No file or history entry is published until every locked track passes.
    Unlocking is a separate edit: a payload cannot unlock and edit its items.
    """
    locked = [layer for layer in before.layers if layer.locked]
    if not locked:
        return
    old, new = before.to_dict(), after.to_dict()
    for raw in (old, new):
        for slide in raw['slides']:
            for take in [slide['take'], *slide['takes'].values()]:
                if take:
                    take.pop('cutaway_cache', None)  # proposals aren't an applied edit
    old_tracks, new_tracks = effective(before, items={}), effective(after, items={})

    defaults = Slide().to_dict()
    original_sids = {slide.id for slide in before.slides}

    def contents(raw, tracks, layer):
        role, result = layer.role, []
        def belongs(ident=''):
            track = resolve(tracks, role, ident)
            return track and track.id == layer.id
        for slide in raw['slides']:
            sid = slide['id']
            if role == 'graphics':
                result += [(sid, item) for item in slide['overlays'] if belongs(item.get('layer', ''))]
            elif role == 'cues':
                for kind, cues in slide['cues'].items():
                    if kind not in {'blocks', 'inactive_blocks'}:
                        result += [(sid, kind, item) for item in cues if belongs(item.get('layer', ''))]
            elif role == 'titles' and belongs(slide['title_layer']):
                if slide['title'] or slide['title_at'] is not None or slide['title_hold'] is not None:
                    result.append((sid, [slide[k] for k in ('title', 'title_at', 'title_hold')]))
            elif belongs():
                fields = {
                    'pictures': ('kind', 'chosen_id', 'picture_mode', 'on_camera', 'insert',
                                 'prefer_kind', 'map_place', 'map_lat', 'map_lon', 'map_zoom',
                                 'map_kind', 'map_style', 'visual_note', 'diagram', 'custom',
                                 'custom_html', 'shot', 'board_template',
                                 'board_lead', 'board_points', 'board_note'),
                    'voice': ('narration', 'take', 'takes', 'on_camera', 'gap_override'),
                    'chapters': ('chapter', 'chapter_hold'),
                }.get(role, ())
                # Blank writing paragraphs have no authored picture/chapter to
                # lock. Captions and automatic cues derive from Voice's inputs.
                if fields and (role == 'voice' or any(
                        slide.get(k) != defaults.get(k) for k in fields
                        if not (k == 'picture_mode' and slide[k] == 'hold' and sid not in original_sids))):
                    result.append((sid, {k: slide.get(k) for k in fields}))
                if role == 'pictures':
                    blocks = {k: v for k, v in slide['cues'].items()
                              if k in {'blocks', 'inactive_blocks'}}
                    if blocks:
                        result.append((sid, blocks))
                    # Downloads may add local_path without changing the chosen source.
                    chosen = [{k: v for k, v in c.items() if k != 'local_path'}
                              for c in slide['candidates'] if c['id'] == slide['chosen_id']]
                    if chosen:
                        result.append((sid, chosen))
                    if slide['on_camera']:
                        result.append((sid, slide['take']))
        if role == 'music' and belongs(raw.get('music_layer', '')):
            result += [raw['music'], raw['style']['music_db']]
        if role == 'sponsors' and belongs():
            result += [raw['sponsors'], raw['style']['sponsor_music_db']]
        if role == 'stings':
            for spec, prefix, ref in ((raw['intro'], 'music', 'music_layer'),
                                      (raw['outro'], 'sting', 'sting_layer')):
                if belongs(spec.get(ref, '')):
                    result.append({k: v for k, v in spec.items() if k.startswith(prefix)})
        if role in {'pictures', 'captions', 'cues', 'titles', 'chapters'}:
            result += [{k: v for k, v in raw['style'].items()
                        if k not in {'music_db', 'sponsor_music_db'}}, raw['frame'], raw['cast']]
        if role == 'voice':
            result += [raw['voice'], raw['voice_track'], raw['narrator']]
        if role in {'pictures', 'voice'}:
            result += [raw['presenter'], raw['clip']]
        if role == 'pictures':
            result += [raw['intro'], raw['outro'], raw['title'], raw['subtitle'],
                       raw['channel_id'], raw['use_intro'], raw['use_outro']]
        return result

    for layer in locked:
        target = next((track for track in new_tracks if track.id == layer.id), None)
        if (target is None or target.role != layer.role or target.order != layer.order
                or contents(old, old_tracks, layer) != contents(new, new_tracks, layer)):
            raise LockedLayerError(_locked_message(layer))

"""Project track metadata derived from the existing, render-free timeline.

Derived tracks and resolved item references are views, never migrations. The
legacy role dictionary remains available to check and inspector consumers.
"""
from .schema import Layer, LAYER_ROLES, Slide
from .media_overlays import role as overlay_role


_COLORS = dict(zip(LAYER_ROLES, (
    'ink-2', 'cool', 'cool', 'accent', 'accent', 'ink',
    'good', 'warn', 'good', 'warn', 'dim', 'cool')))


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
            layer = resolve(layers, role, item.get('layer') or project.layer_defaults.get(role, ''))
            by_id[layer.id]['items'].append(dict(item, layer=layer.id))
    return result


def graphics_order(project, group):
    """Stable item permutation, bottom to top; later project tracks win.

    Preserve paragraph/list order within a track, including anchor resolution.
    Unknown references use the first track of the item's role without changing storage.
    This is also the cache dependency: names, colours and locks aren't pixels.
    """
    tracks = [layer for layer in effective(project, items={}) if layer.role in {'graphics', 'media'}]
    ranks = {layer.id: i for i, layer in enumerate(tracks)}
    items = [(i, j) for i, (slide, _) in enumerate(group) for j in range(len(slide.overlays))]
    def rank(pair):
        item = group[pair[0]][0].overlays[pair[1]]
        track = resolve(tracks, overlay_role(item), item.get('layer', ''))
        return ranks[track.id] if track else len(tracks) + (overlay_role(item) == 'media')
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
                [(t.id, t.role) for t in tracks] + [project.music_layer, project.layer_defaults]).encode()).hexdigest()[:12])
        obj = super().__new__(cls, tokens)
        obj.tracks, obj.ids, obj.defaults = tracks, ids, project.layer_defaults
        return obj

    def __reduce__(self):
        return (_restore_visibility, (tuple(self), self.tracks, self.ids, self.defaults))

    def item(self, role, ident=''):
        track = resolve(self.tracks, role, ident or self.defaults.get(role, ''))
        return bool(track and track.id in self.ids)

    def __contains__(self, role):
        if role in {'cues', 'graphics', 'media'}:
            return all(t.id in self.ids for t in self.tracks if t.role == role)
        return self.item(role)


def _restore_visibility(tokens, tracks, ids, defaults):
    obj = frozenset.__new__(Visibility, tokens)
    obj.tracks, obj.ids, obj.defaults = tracks, ids, defaults
    return obj


def visibility(project, requested=(), *, final=False):
    return Visibility(project, requested, final=final)


def visible_stings(project, stings, hide):
    hide = visibility(project, hide)
    return {role: entry for role, entry in stings.items()
            if not hide.item('stings', sting_layer(project, role, entry[1]))}


def sting_layer(project, role, spec):
    return project.layer_defaults.get('stings:' + role) or getattr(
        getattr(spec, '_spec', spec), 'music_layer' if role == 'intro' else 'sting_layer', '')


def patch_flags(project, ident, patch):
    """Materialize the drawing view only on an explicit layer edit."""
    from .edits import EditError
    if not patch or set(patch) - {'hidden', 'locked', 'name', 'color'}:
        raise EditError('Unknown layer setting.')
    tracks = [Layer.from_dict(row) for row in rows(project)]
    target = next((layer for layer in tracks if layer.id == ident), None)
    if target is None:
        raise EditError('No such layer.', 404)
    try:
        updated = Layer(**dict(target.to_dict(), **patch))
        if 'name' in patch and len(updated.name) > 24:
            raise ValueError('Layer names must be at most 24 characters.')
    except (TypeError, ValueError) as exc:
        raise EditError(str(exc)) from exc
    tracks[tracks.index(target)] = updated
    project.layers = tracks


def _bindings(project):
    """Stored references, including dormant items that aren't timeline spans."""
    items = role_items(project)
    for role in LAYER_ROLES:
        if items[role] or role in project.layer_defaults:
            yield role, project.layer_defaults, role
    for role in ('intro', 'outro'):
        if 'stings:' + role in project.layer_defaults:
            yield 'stings', project.layer_defaults, 'stings:' + role
    for slide in project.slides:
        for item in slide.overlays:
            yield overlay_role(item), item, 'layer'
        for kind, cues in slide.cues.items():
            if kind not in {'blocks', 'inactive_blocks'}:
                for cue in cues:
                    yield 'cues', cue, 'layer'
        if slide.title:
            yield 'titles', slide.__dict__, 'title_layer'
    if project.music:
        yield 'music', project.__dict__, 'music_layer'
    if project.intro.music:
        yield 'stings', project.intro.__dict__, 'music_layer'
    if project.outro.sting:
        yield 'stings', project.outro.__dict__, 'sting_layer'


def manage(project, payload):
    """One structural edit, persisted atomically by the caller with one undo."""
    from .edits import EditError
    if payload.get('op') in {'apply_proposal', 'dismiss_proposal'}:
        from .layer_proposals import decide
        return decide(project, payload)
    tracks = [Layer.from_dict(row) for row in rows(project)]
    op = payload.get('op')
    source = next((t for t in tracks if t.id == payload.get('id')), None)
    if op in {'duplicate', 'delete'} and source is None:
        raise EditError('No such layer.', 404)
    # Resolve legacy/default assignments before changing the first track.
    for row in rows(project):
        if row['role'] == 'stings':
            for item in row['items']:
                project.layer_defaults.setdefault('stings:' + item['id'], row['id'])
    bindings = [(owner, key, resolve(tracks, role, owner.get(key) or project.layer_defaults.get(role, '')))
                for role, owner, key in _bindings(project)]
    if op in {'add', 'duplicate'}:
        try:
            new = (Layer(name=source.name, role=source.role, color=source.color) if op == 'duplicate'
                   else Layer(name=payload.get('name'), role=payload.get('role')))
            if len(new.name) > 24:
                raise ValueError('Layer names must be at most 24 characters.')
            if new.role in {'pictures', 'voice'} and any(t.role == new.role for t in tracks):
                raise ValueError('Pictures and Voice each use one main track.')
        except (TypeError, ValueError) as exc:
            raise EditError(str(exc)) from exc
        new.order = max((t.order for t in tracks), default=-1) + 1
        tracks.append(new)
    elif op == 'move_item':
        target = next((t for t in tracks if t.id == payload.get('to')), None)
        role = payload.get('role', 'graphics')
        if not target or target.role != role or role in {'pictures', 'voice'}:
            raise EditError('Choose another layer of the same supported role.')
        candidates = [r for r in rows(project) if r['role'] == role]
        current = next((r for r in candidates if any(i['id'] == payload.get('item')
            and i.get('sid', '') == payload.get('sid', '') for i in r['items'])), None)
        if current is None:
            raise EditError('Item changed; select it again.', 409)
        require_unlocked(project, role, current['id'])
        require_unlocked(project, role, target.id)
        slide = next((s for s in project.slides if s.id == payload.get('sid')), None)
        if role in {'graphics', 'media'}:
            next(o for o in slide.overlays if o.get('id') == payload['item'])['layer'] = target.id
        elif role == 'titles':
            slide.title_layer = target.id
        elif role == 'cues':
            from . import cuts, kinds
            from copy import deepcopy
            fmt = kinds.kind_for(project, slide)
            cues = deepcopy(cuts.cues_for(cuts.BY_KEY[fmt], slide))
            index = next(i['cue'] for r in candidates for i in r['items'] if i['id'] == payload['item'])
            cues[index]['layer'] = target.id
            slide.cues[fmt] = cues  # Materialize automatic cues, preserving on/at.
        elif role == 'music':
            project.music_layer = target.id
        elif role == 'stings':
            project.layer_defaults['stings:' + payload['item']] = target.id
        else:
            # Captions, chapters, sponsors and notes have role-wide ownership.
            for row in candidates:
                if row['items']:
                    require_unlocked(project, role, row['id'])
            project.layer_defaults[role] = target.id
        bindings = []
    elif op == 'reorder':
        ids = payload.get('ids')
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or sorted(ids) != sorted(t.id for t in tracks):
            raise EditError('Reorder must include each layer exactly once.')
        tracks.sort(key=lambda t: ids.index(t.id))
        for i, track in enumerate(tracks):
            track.order = i
    elif op == 'delete':
        if source.role in {'pictures', 'voice'}:
            raise EditError('Pictures and Voice cannot be deleted.')
        if source.locked:
            raise LockedLayerError(_locked_message(source))
        target = next((t for t in tracks if t.id == payload.get('move_to') and
                       t.role == source.role and t.id != source.id), None)
        occupied = any(row['items'] for row in rows(project) if row['id'] == source.id)
        occupied |= any(track and track.id == source.id for owner, _, track in bindings
                        if owner is not project.layer_defaults)
        if occupied and target is None:
            raise EditError('Move items to another layer of the same role before deleting.')
        if occupied and target.locked:
            raise LockedLayerError(_locked_message(target))
        for owner, key, track in bindings:
            if track and track.id == source.id:
                if target:
                    owner[key] = target.id
                else:
                    owner.pop(key, None)  # An empty track's default is only metadata.
        tracks.remove(source)
    else:
        raise EditError('Unknown layer operation.')
    # Pin surviving movable items so reordering never silently moves them.
    for owner, key, track in bindings:
        if track and track in tracks and not track.locked:
            owner[key] = track.id
    project.layers = tracks


def _locked_message(layer):
    return f'{layer.role.capitalize()} layer “{layer.name}” is locked. Unlock it in Edit before editing.'


def require_unlocked(project, role, ident=''):
    """Preflight only the role(s) an operation changes, including external writes."""
    tracks = effective(project, items={})
    for kind in (role,) if isinstance(role, str) else role:
        track = resolve(tracks, kind, ident or project.layer_defaults.get(kind, ''))
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
            track = resolve(tracks, role, ident or raw.get('layer_defaults', {}).get(role, ''))
            return track and track.id == layer.id
        for slide in raw['slides']:
            sid = slide['id']
            if role in {'graphics', 'media'}:
                result += [(sid, item) for item in slide['overlays'] if overlay_role(item) == role and belongs(item.get('layer', ''))]
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

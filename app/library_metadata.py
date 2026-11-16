"""Library culling metadata. Index-only operations; originals are never opened."""
import json

from fastapi import Body, HTTPException

from . import library, store

COLORS = ('', 'red', 'yellow', 'green', 'blue', 'purple')


def read_extras():
    try:
        raw = json.loads(library._INDEX_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raw = {}
    return {k: raw.get(k, []) for k in ('collections', 'labels')}


def context():
    with library._LOCK:
        extra = read_extras()
        extra['labels'] = list(dict.fromkeys(extra['labels'] + [t for a in library._load_index() for t in a.tags]))
        return extra


def strings(value):
    if not isinstance(value, list) or any(not isinstance(s, str) or not s.strip() for s in value):
        raise ValueError('Expected a list of nonempty strings')
    return list(dict.fromkeys(s.strip() for s in value))


def mutate(payload, operation):
    with library._LOCK:
        assets, folders = library._load_both()
        extra = context()
        if operation == 'batch':
            ids = strings(payload.get('ids'))
            if not ids or set(ids) - {a.id for a in assets}:
                raise ValueError('Selection contains missing assets')
            rating, color = payload.get('rating'), payload.get('color')
            if rating is not None and (type(rating) is not int or not 0 <= rating <= 5):
                raise ValueError('Rating must be 0–5')
            if color is not None and color not in COLORS:
                raise ValueError('Unknown colour')
            add, remove = strings(payload.get('add', [])), strings(payload.get('remove', []))
            for a in assets:
                if a.id not in ids:
                    continue
                if rating is not None:
                    a.rating = rating
                if color is not None:
                    a.color = color
                if 'title' in payload:
                    if not isinstance(payload['title'], str):
                        raise ValueError('Title must be text')
                    a.title = payload['title'].strip()
                a.tags = list(dict.fromkeys([t for t in a.tags if t not in remove] + add))
            extra['labels'] = list(dict.fromkeys(extra['labels'] + add))
        elif operation == 'labels':
            old, action = payload.get('old'), payload.get('action')
            if action == 'reorder':
                labels = strings(payload.get('labels'))
                if set(labels) != set(extra['labels']):
                    raise ValueError('Reorder must contain every label')
                extra['labels'] = labels
            elif action in ('rename', 'delete') and old in extra['labels']:
                new = strings([payload.get('new')])[0] if action == 'rename' else ''
                def relabel(tags):
                    return list(dict.fromkeys(new if t == old else t for t in tags if t != old or new))
                extra['labels'] = relabel(extra['labels'])
                for a in assets:
                    a.tags = relabel(a.tags)
                for c in extra['collections']:
                    if c['kind'] == 'smart':
                        c['filters']['labels'] = relabel(c['filters'].get('labels', []))
            else:
                raise ValueError('Unknown label operation')
        elif operation == 'collections':
            ident = payload.get('id')
            if ident:
                c = next((c for c in extra['collections'] if c['id'] == ident), None)
                if c is None or c['kind'] != 'manual':
                    raise ValueError('Choose a manual collection')
                ids = strings(payload.get('ids'))
                if set(ids) - {a.id for a in assets}:
                    raise ValueError('Collection contains missing assets')
                c['ids'] = list(dict.fromkeys(c['ids'] + ids))
            else:
                name = strings([payload.get('name')])[0]
                kind = payload.get('kind')
                if kind not in ('manual', 'smart') or not isinstance(payload.get('filters', {}), dict):
                    raise ValueError('Invalid collection')
                extra['collections'].append(dict(id=library._uid(), name=name, kind=kind,
                    ids=[], filters=payload.get('filters', {})))
        # One atomic replacement includes assets, folders, vocabulary and collections.
        store.atomic_write(library._INDEX_FILE, json.dumps(dict(extra,
            assets=[a.to_dict() for a in assets], folders=[f.to_dict() for f in folders]), ensure_ascii=False, indent=2))
        return dict(extra, assets=[a.to_dict() for a in assets])


def used_in():
    """Read project references without store.load's schema migrations or writes."""
    assets = library.list_all()
    uses = {a['id']: [] for a in assets}
    def values(v):
        if isinstance(v, dict):
            return set().union(*(values(x) for x in v.values())) if v else set()
        if isinstance(v, list):
            return set().union(*(values(x) for x in v)) if v else set()
        return {v} if isinstance(v, str) else set()
    for path in store.PROJECTS_DIR.glob('*/project.json'):
        try:
            p = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        refs = values(p.get('bin', []))
        for s in p.get('slides', []):
            chosen = next((c for c in s.get('candidates', []) if c.get('id') == s.get('chosen_id')), {})
            refs |= values([chosen, s.get('insert', {}), s.get('overlays', []), s.get('custom', {}), s.get('cues', {})])
        for a in assets:
            ident = a['id']
            if refs & {ident, 'lib'+ident, 'library:'+ident, '/api/library/file/'+ident,
                       '/scene/{token}/library/'+ident}:
                uses[ident].append(dict(id=p.get('id', path.parent.name), title=p.get('title') or p.get('idea') or path.parent.name))
    return uses


def register(app):
    @app.get('/api/library/metadata/context')
    def get_context():
        return context()

    @app.get('/api/library/metadata/used')
    def get_used():
        return used_in()

    @app.post('/api/library/metadata/{operation}')
    def edit(operation: str, payload: dict = Body(...)):
        if operation not in ('batch', 'labels', 'collections'):
            raise HTTPException(404, 'Unknown Library operation')
        try:
            return mutate(payload, operation)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

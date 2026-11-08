"""Saved values only. Rendering never resolves a preset reference."""
from copy import deepcopy
import math
import uuid
from typing import Literal

from fastapi import Body, HTTPException
from . import blocks, channels, store


def provenance(item):
    if 'preset' not in item:
        return {}
    value = item['preset']
    if (not isinstance(value, dict) or not isinstance(value.get('id'), str)
            or not value['id'] or value.get('scope') not in ('project', 'channel')):
        raise ValueError('Preset needs a nonempty id and scope: project or channel')
    return {'preset': {'id': value['id'], 'scope': value['scope']}}


def validate(payload, previous=None):
    raw = {**(previous or {}), **payload}
    name, ref, values = raw.get('name'), raw.get('block'), raw.get('values', {})
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError('Preset name must be 1–120 characters')
    if not isinstance(ref, str) or not isinstance(values, dict):
        raise ValueError('Preset needs a block ref and values object')
    block = blocks.discover().get(ref)
    if block:
        values = blocks.validate_vars(block['meta'], values)
    elif not previous or ref != previous['block'] or values != previous['values']:
        raise ValueError(f'Block missing: {ref}. Saved values are kept until it returns.')
    result = dict(id=(previous or {}).get('id') or uuid.uuid4().hex, name=name.strip(),
                  block=ref, values=deepcopy(values))
    for key in ('seconds', 'aspect'):
        value = raw.get(key)
        if value is None:
            continue
        if key == 'seconds' and (isinstance(value, bool) or not isinstance(value, (int, float))
                                or not math.isfinite(value) or value <= 0):
            raise ValueError('Preset seconds must be positive and finite')
        if key == 'aspect' and (value not in ('16:9', '9:16') or block and value not in block['meta']['aspects']):
            raise ValueError('Unsupported preset aspect')
        result[key] = value
    return result


def backend(owner):
    return channels if owner == 'channels' else store


def load(owner, ident):
    try:
        return backend(owner).load(ident)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


def listing(owner, ident):
    found = blocks.discover()
    return [dict(deepcopy(p), missing=p['block'] not in found)
            for p in load(owner, ident).block_presets]


def create(owner, ident, payload):
    service = backend(owner)
    try:
        with service.lock_for(ident):
            obj = load(owner, ident)
            item = validate(payload)
            obj.block_presets.append(item)
            service.save(obj)
            return item
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def change(owner, ident, preset_id, payload=None):
    service = backend(owner)
    try:
        with service.lock_for(ident):
            obj = load(owner, ident)
            old = next((p for p in obj.block_presets if p['id'] == preset_id), None)
            if old is None:
                raise HTTPException(404, 'Preset not found')
            item = validate(payload, old) if payload is not None else None
            obj.block_presets = [item if p['id'] == preset_id else p for p in obj.block_presets
                                 if item is not None or p['id'] != preset_id]
            service.save(obj)
            return item or {'deleted': preset_id}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def register(app):
    # Plain routes preserve the app.routes introspection contract.
    @app.get('/api/{owner}/{ident}/block-presets')
    def get(owner: Literal['channels', 'projects'], ident: str):
        return listing(owner, ident)

    @app.post('/api/{owner}/{ident}/block-presets')
    def post(owner: Literal['channels', 'projects'], ident: str, payload: dict = Body(...)):
        return create(owner, ident, payload)

    @app.patch('/api/{owner}/{ident}/block-presets/{preset_id}')
    def patch(owner: Literal['channels', 'projects'], ident: str, preset_id: str, payload: dict = Body(...)):
        return change(owner, ident, preset_id, payload)

    @app.get('/api/{owner}/{ident}/block-presets/{preset_id}/slides')
    def count(owner: Literal['channels', 'projects'], ident: str, preset_id: str):
        return affected(owner, ident, preset_id)

    @app.post('/api/{owner}/{ident}/block-presets/{preset_id}/slides')
    def update(owner: Literal['channels', 'projects'], ident: str, preset_id: str):
        try:
            return affected(owner, ident, preset_id, apply=True)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete('/api/{owner}/{ident}/block-presets/{preset_id}')
    def delete(owner: Literal['channels', 'projects'], ident: str, preset_id: str):
        return change(owner, ident, preset_id)


def affected(owner, ident, preset_id, apply=False):
    """Count slides first; only an explicit second request changes copied vars."""
    preset = next((p for p in load(owner, ident).block_presets if p['id'] == preset_id), None)
    if preset is None:
        raise HTTPException(404, 'Preset not found')
    scope = 'project' if owner == 'projects' else 'channel'
    reference = dict(id=preset_id, scope=scope)
    ids = [ident] if scope == 'project' else [p['id'] for p in store.list_projects() if p.get('channel_id') == ident]
    count = 0
    for pid in ids:
        with store.lock_for(pid):
            project = store.load(pid)
            if scope == 'channel' and project.channel_id != ident:
                continue
            changed = False
            for slide in project.slides:
                cues = (slide.cues or {}).get('blocks', [])
                targets = [c for c in cues if c.get('preset') == reference and c['block'] == preset['block']]
                targets += [o for o in slide.overlays if o.get('preset') == reference and o['block_id'] == preset['block']]
                if not targets:
                    continue
                count += 1
                if apply:
                    # Validate before replacing any saved values, including missing blocks.
                    clean = validate(preset)
                    for target in targets:
                        target['vars'] = deepcopy(clean['values'])
                    changed = True
            if changed:
                store.save(project)
    return {'slides': count}

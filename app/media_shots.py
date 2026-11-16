"""Detached shot/cast snapshots. Only composition may invoke the 3D runner."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math

from . import composing_sources, models3d, shots, stage, store
from .schema import Slide


def validate(data):
    if (not isinstance(data, dict) or not isinstance(data.get('shot'), dict)
            or not isinstance(data.get('cast'), list) or not data['cast']
            or type(data.get('seconds')) not in (int, float)
            or not math.isfinite(data['seconds']) or data['seconds'] <= 0):
        raise ValueError('Invalid detached 3D shot')
    if (not isinstance(data['shot'].get('intent'), dict)
            or not isinstance(data['shot'].get('solved') or {}, dict)
            or any(not isinstance(s, dict) or any(not isinstance(s.get(k), str) or not s[k] for k in ('id', 'model')) for s in data['cast'])):
        raise ValueError('The shot needs its cast models')


def snapshot(project, data):
    row = Slide(insert=deepcopy(data))
    composing_sources.prepare(project, row, data)
    context = deepcopy(project)
    composing_sources.attach(context, row)
    subjects = row.shot['intent']['subjects']
    result = dict(shot=deepcopy(row.shot), seconds=data['seconds'],
                  cast=deepcopy([s for s in context.cast if s['id'] in subjects]))
    validate(result)
    return result


def resolve(project, data, *, size=None, fps=None, render=False):
    validate(data)
    context = replace(project, cast=deepcopy(data['cast']))
    intent = shots.clean_intent(data['shot']['intent'], context)
    if not intent or intent['subjects'] != data['shot']['intent']['subjects']:
        raise ValueError('The detached shot needs unavailable models')
    models = {s['model']: models3d.get(s['model']) for s in data['cast']}
    from .render import preview_size, PREVIEW_FPS
    size = size or preview_size(project)
    fps = fps or PREVIEW_FPS
    key = hashlib.sha256(json.dumps([data, size, fps,
        [shots._model_sig(m) | {'bytes': m.get('bytes'), 'tint': m.get('tint')} for m in models.values()]],
        sort_keys=True).encode()).hexdigest()[:24]
    root = store.project_dir(project.id) / 'stage' / 'media'
    path = root / (key+'.mp4')
    if render and not path.is_file():
        row = Slide(id=key, kind='stage', shot=deepcopy(data['shot']))
        if not (row.shot.get('solved') or {}).get('shot'):
            result = stage.solve([dict(id=key, entries=shots.entries(context, intent),
                intent=intent, secs=data['seconds'], prev_id=None, prev=None)], models)[key]
            if result.get('error'):
                raise ValueError(result['error'])
            row.shot['solved'] = result
        spec = shots._render_item(context, row, data['seconds'], size, fps)
        stage.render([{**spec, 'clip':key}], models, root)
        if not path.is_file():
            raise ValueError('The detached shot did not render')
    return path, 'video', 0., data['seconds']

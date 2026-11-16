"""Detached 3D shots and Create HTML snapshots; placement never renders."""
from copy import deepcopy
from dataclasses import replace
import hashlib

from . import cast, graphics, models3d, shots


def prepare(project, row, data, previous=None):
    kind = data['kind']
    if kind == 'graphic':
        ident = data.get('graphic_id')
        if not isinstance(ident, str) or not ident:
            raise ValueError('Choose a Create graphic')
        # Trimming an already placed version must survive edits/deletion in Create.
        if not (previous and previous.insert.get('graphic_id') == ident and row.custom_html):
            graphic = next((g for g in graphics.graphics_of(project) if g.get('id') == ident), None)
            if not graphic or not graphics.current_html(graphic):
                raise ValueError('Design the graphic in Create first')
            row.custom_html = graphics._clean(graphics.current_html(graphic))
        row.kind, row.custom = 'custom:graphic', {}
        return
    if bool(data.get('model_id')) == bool(data.get('source_slide')):
        raise ValueError('Choose one 3D model or existing shot')
    same = previous and all(data.get(k) == previous.insert.get(k) for k in ('model_id', 'source_slide'))
    if same and (row.shot or {}).get('intent'):
        return  # Keep hand edits and camera paths when changing only the length.
    if data.get('source_slide'):
        source = project.slide(data['source_slide'])
        if not source or not (source.shot or {}).get('intent') or not shots.is_3d(source):
            raise ValueError('That 3D shot is no longer available')
        intent = shots.clean_intent(source.shot['intent'], project)
        if not intent or intent['subjects'] != source.shot['intent'].get('subjects'):
            raise ValueError('The shot needs its cast models')
        row.shot, row.visual_note = deepcopy(source.shot), source.visual_note
        row.shot['intent'] = intent
    else:
        ident = data['model_id']
        if not isinstance(ident, str):
            raise ValueError('Choose a 3D model')
        model = models3d.get(ident)
        subject = next((s for s in project.cast if s.get('model') == ident
                        and s.get('mode', 'model') == 'model' and s.get('id')), None)
        subject = subject or dict(id='m' + hashlib.sha1(ident.encode()).hexdigest()[:10],
                                  subject=cast.model_name(model), model=ident, mode='model')
        context = replace(project, cast=[*project.cast, subject])
        intent = shots.clean_intent(dict(subjects=[subject['id']], move='static', framing='wide'), context)
        if not intent:
            raise ValueError('The shot needs an available model')
        row.shot = dict(intent=intent, solved=None, locked=False, by='hand')
        row.visual_note = f'3D: {subject["subject"]} — whole — static wide'
    row.kind = 'stage'


def attach(project, row):
    """Publish source bookkeeping together with the placed row in one undo state."""
    data = row.insert
    if data.get('kind') == 'stage' and data.get('model_id'):
        sid = row.shot['intent']['subjects'][0]
        if not any(s.get('id') == sid for s in project.cast):
            project.cast = [*project.cast, dict(id=sid, subject=cast.model_name(models3d.get(data['model_id'])),
                model=data['model_id'], mode='model', role='supporting', chapters=[], why='')]
    if data.get('kind') == 'graphic':
        graphic = next((g for g in graphics.graphics_of(project) if g.get('id') == data['graphic_id']), None)
        if graphic is not None and row.id not in graphic.setdefault('used_in', []):
            graphic['used_in'].append(row.id)

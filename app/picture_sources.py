"""Resolve composing sources by owned IDs, never client-supplied paths."""
from copy import deepcopy
import shutil
import uuid

from . import library, project_bin, store


def local_path(project, path):
    root = store.project_dir(project.id)
    if not path.is_relative_to(root):
        dest = root / 'media' / (uuid.uuid4().hex + path.suffix)
        dest.parent.mkdir(exist_ok=True)
        with path.open('rb') as source, dest.open('xb') as target:
            shutil.copyfileobj(source, target)
        path = dest
    return path.relative_to(root).as_posix()


def candidate(project, payload):
    if payload.get('candidate_id'):
        source = project.slide(payload.get('source_slide'))
        found = next((c for c in source.candidates if c['id'] == payload['candidate_id']), None) if source else None
        if not found:
            raise ValueError('Search result is no longer available; search again')
        return deepcopy(found)
    if payload.get('kind') == 'clip':
        from . import footage, inserts
        row, _ = inserts.prepare(project, payload)
        meta = row.insert
        shoot = footage.load(meta['shoot_id'])
        source = next(f for f in shoot.files if f.id == meta['source_id'])
        root = f'/api/footage/shoots/{shoot.id}/media'
        return dict(id='ft' + uuid.uuid4().hex, provider='footage', kind='video',
                    title=source.source_path.split('/')[-1] or source.id,
                    shoot_id=shoot.id, source_id=source.id, in_s=meta['in_s'], out_s=meta['out_s'],
                    duration=meta['seconds'], width=source.width, height=source.height,
                    url=f'{root}/proxies/{source.id}.mp4', thumb=f'{root}/sprites/{source.id}.jpg',
                    license='Your footage', author='you')
    if payload.get('bin_id'):
        item = project_bin.item_for(project, payload['bin_id'])
        if item.kind not in {'image', 'clip'}:
            raise ValueError('Choose a picture or clip from Materials')
        if item.source.startswith('footage:'):
            from .media.footage import suggestions
            shoot, clip = item.source.removeprefix('footage:').split('/')
            found = next((c.to_dict() for c in suggestions('', limit=100000)
                          if c.shoot_id == shoot and c.clip_id == clip), None)
            if not found:
                raise ValueError('Material footage is unavailable')
        else:
            path = project_bin.file_path(project.id, item)
            if not path or not path.is_file():
                raise ValueError('Material is unavailable')
            found = dict(id='bin'+item.id, provider='materials', title=item.title,
                         kind='video' if item.kind == 'clip' else 'image', local_path=local_path(project, path),
                         thumb=f'/api/projects/{project.id}/bin/{item.id}/thumb',
                         width=item.width, height=item.height, duration=item.duration)
        return dict(found, bin_id=item.id, license=item.licence, author=item.credit,
                    source_page=item.url, origin=item.origin, made=item.made, shows=item.shows)
    ident = payload.get('asset_id')
    if not isinstance(ident, str):
        raise ValueError('Choose a Library or Materials source')
    asset, path = library.get(ident), library.file_path(ident)
    if not asset or asset['kind'] not in {'image', 'video'} or not path or not path.is_file():
        raise ValueError('Library picture is unavailable')
    return dict(id='lib'+ident, provider='library', ref=ident, kind=asset['kind'],
                title=asset.get('title', ident), local_path=local_path(project, path),
                thumb=f'/api/library/thumb/{ident}', license=asset.get('license', ''),
                author=asset.get('author', ''), source_page=asset.get('source_page', ''),
                width=asset.get('width', 0), height=asset.get('height', 0), duration=asset.get('duration', 0))


def apply(project, sid, payload):
    from . import inserts
    slide = project.slide(sid)
    if not slide or slide.on_camera or project.kind == 'clip':
        raise ValueError('Choose a non-camera picture paragraph')
    if slide.insert:
        data = dict(payload, kind=payload.get('kind', 'picture'))
        if data['kind'] != 'clip':
            data['seconds'] = slide.insert['seconds']
        row, _ = inserts.prepare(project, data)
        slide.insert, slide.candidates, slide.chosen_id = row.insert, row.candidates, row.chosen_id
        slide.kind, slide.locked_media = row.kind, True
        slide.shot, slide.custom_html, slide.custom = row.shot, row.custom_html, row.custom
        if row.kind == 'stage':
            slide.visual_note = row.visual_note
        from .composing_sources import attach
        attach(project, slide)
        if slide.cues.get('blocks'):
            slide.cues = dict(slide.cues, inactive_blocks=slide.cues['blocks'], blocks=[])
        return
    lead = project.slide(next((r[0] for r in project.picture_runs() if sid in r), sid))
    if payload.get('kind') in {'stage', 'graphic'}:
        from .composing_sources import attach
        row, _ = inserts.prepare(project, dict(payload, seconds=4))
        lead.kind, lead.locked_media = row.kind, True
        lead.chosen_id = ''  # Keep candidates available without downloading an old choice.
        lead.shot, lead.custom_html, lead.custom = row.shot, row.custom_html, row.custom
        if row.kind == 'stage':
            lead.visual_note = row.visual_note
        if lead.cues.get('blocks'):
            lead.cues = dict(lead.cues, inactive_blocks=lead.cues['blocks'], blocks=[])
        row.id = lead.id
        attach(project, row)
        return
    if payload.get('kind') == 'block':
        row, _ = inserts.prepare(project, dict(payload, seconds=4))
        lead.kind, lead.locked_media = 'kenburns', True
        lead.cues = dict(lead.cues, blocks=[dict(block=row.insert['block'], vars=row.insert['vars'])])
        return
    found = candidate(project, payload)
    lead.candidates = [deepcopy(found)] + [c for c in lead.candidates if c['id'] != found['id']]
    lead.chosen_id, lead.locked_media, lead.kind = found['id'], True, 'kenburns'
    if lead.cues.get('blocks'):
        lead.cues = dict(lead.cues, inactive_blocks=lead.cues['blocks'], blocks=[])

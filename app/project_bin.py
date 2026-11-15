"""Project-local assets and references. Removed bytes remain available to undo."""
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from . import ffutil, footage, library, store
from .schema import BinItem


def load(pid):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', pid):
        raise HTTPException(400, 'Invalid project id')
    try:
        return store.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Project not found') from exc


def item_for(p, ident):
    item = next((i for i in p.bin if i.id == ident), None)
    if item is None:
        raise HTTPException(404, 'Bin item not found')
    return item


def owned(pid, rel):
    root = store.project_dir(pid).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root / 'bin') or path == root / 'bin':
        raise HTTPException(400, 'Invalid bin path')
    return path


def reference(source):
    """Resolve indexed references only; never accept an arbitrary external path."""
    if source.startswith('library:'):
        ident = source.removeprefix('library:')
        asset = library.get(ident)
        if asset:
            return dict(kind='clip' if asset['kind'] == 'video' else 'image',
                        title=asset['title'], width=asset['width'], height=asset['height'],
                        duration=asset['duration']), library.file_path(ident), library.thumb_path(ident)
    elif re.fullmatch(r'footage:[a-z0-9]+/[a-z0-9]+', source):
        sid, cid = source.removeprefix('footage:').split('/')
        try:
            shoot = footage.load(sid)
            clip = next(c for c in shoot.clips if c.id == cid)
            file = next(f for f in shoot.files if f.id == clip.file)
            thumb = footage.media_path(sid, 'thumbs', clip.thumbs[0]) if clip.thumbs else None
            return dict(kind='audio' if file.kind == 'audio' else 'clip', title=clip.title or cid,
                        duration=clip.out_s-clip.in_s, width=file.width, height=file.height), footage.source_path(shoot, file), thumb
        except (FileNotFoundError, StopIteration, ValueError):
            pass
    raise HTTPException(404, 'Referenced asset not found')


def file_path(pid, item, thumb=False):
    if item.source != 'dropped':
        return reference(item.source)[2 if thumb else 1]
    if not item.file:
        return None
    path = owned(pid, f'bin/thumbs/{item.id}.jpg' if thumb else item.file)
    if not thumb and not path.exists():
        path = owned(pid, f'bin/.removed/{path.name}')
    return path


def listing(p):
    def values(value):
        if isinstance(value, dict):
            return set().union(*(values(v) for v in value.values())) if value else set()
        if isinstance(value, list):
            return set().union(*(values(v) for v in value)) if value else set()
        return {value} if isinstance(value, str) and value else set()
    uses = [(s.id, values([next((c for c in s.candidates if c.get('id') == s.chosen_id), {}), s.insert, s.overlays])) for s in p.slides]
    rows = []
    for item in p.bin:
        keys = {item.id, item.file, item.source if item.source != 'dropped' else ''} - {''}
        if item.source.startswith('library:'):
            keys.add(item.source.removeprefix('library:'))
        footage_uses = set()
        if item.source.startswith('footage:'):
            sid, cid = item.source.removeprefix('footage:').split('/')
            keys.add(f'ft{sid}_{cid}')
            try:
                clip = next(c for c in footage.load(sid).clips if c.id == cid)
                footage_uses = {s.id for s in p.slides if s.insert.get('shoot_id') == sid
                    and s.insert.get('source_id') == clip.file
                    and s.insert.get('in_s', 0) < clip.out_s and s.insert.get('out_s', 0) > clip.in_s}
            except (FileNotFoundError, StopIteration, ValueError):
                pass
        path = file_path(p.id, item) if item.file else None
        rows.append(dict(item.to_dict(), used_in=[sid for sid, refs in uses if keys & refs or sid in footage_uses],
                         size=path.stat().st_size if path and path.is_file() else 0,
                         thumb=f'/api/projects/{p.id}/bin/{item.id}/thumb' if item.kind in {'image', 'clip'} else ''))
    return dict(items=rows, labels=p.labels)


def patch(item, payload, p):
    for key in ('title', 'note'):
        if key in payload:
            if not isinstance(payload[key], str):
                raise HTTPException(400, f'{key} must be text')
            setattr(item, key, payload[key])
    if 'labels' in payload:
        labels = payload['labels']
        if not isinstance(labels, list) or any(not isinstance(x, str) or not x.strip() for x in labels):
            raise HTTPException(400, 'Labels must be nonempty strings')
        item.labels = list(dict.fromkeys(x.strip() for x in labels))
        p.labels = list(dict.fromkeys(p.labels + item.labels))


def register(app):
    base = '/api/projects/{pid}/bin'

    @app.get(base)
    def get_bin(pid: str):
        with store.lock_for(pid):
            return listing(load(pid))

    @app.post(base)
    def upload(pid: str, files: list[UploadFile]):
        load(pid)
        extensions = {**dict.fromkeys(library._IMAGE_EXT, 'image'), **dict.fromkeys(footage._VIDEO_EXT, 'clip'), **dict.fromkeys(footage._AUDIO_EXT, 'audio')}
        if any(Path(f.filename or '').suffix.lower() not in extensions for f in files) or not files:
            raise HTTPException(400, 'Choose pictures, clips or audio files')
        items = []
        for file in files:
            suffix = Path(file.filename).suffix.lower()
            title = re.sub(r'[_-]+', ' ', Path(file.filename).stem).strip()
            item = BinItem(id=uuid.uuid4().hex, kind=extensions[suffix], title=title)
            item.file = f'bin/{item.id}{suffix}'
            dest = owned(pid, item.file)
            dest.parent.mkdir(exist_ok=True)
            with dest.open('xb') as out:
                shutil.copyfileobj(file.file, out, length=1024 * 1024)
            try:
                if item.kind == 'image':
                    with Image.open(dest) as image:
                        item.width, item.height = image.size
                else:
                    item.duration = ffutil.duration(dest)
                    if item.kind == 'clip':
                        item.width, item.height = ffutil.dimensions(dest)
            except Exception:
                pass  # Keep the original even if its metadata cannot be read.
            if item.kind in {'image', 'clip'}:
                thumbs = owned(pid, 'bin/thumbs')
                thumbs.mkdir(exist_ok=True)
                library._make_thumb(dest, 'video' if item.kind == 'clip' else 'image', item.id, directory=thumbs)
            items.append(item)
        with store.lock_for(pid):
            p = load(pid)
            p.bin.extend(items)
            store.save(p)
        return listing(p)

    @app.post(base + '/note')
    @app.post(base + '/link')
    def add(pid: str, payload: dict = Body(...)):
        with store.lock_for(pid):
            p = load(pid)
            source, url = payload.get('source', 'dropped'), payload.get('url', '')
            if not isinstance(source, str) or not isinstance(url, str):
                raise HTTPException(400, 'Source and URL must be text')
            try:
                if url and (urlsplit(url).scheme not in {'https', 'http'} or not urlsplit(url).netloc):
                    raise ValueError()
            except ValueError as exc:
                raise HTTPException(400, 'Use an http or https URL') from exc
            metadata = reference(source)[0] if source != 'dropped' else dict(kind='link' if url else 'note')
            item = BinItem(id=uuid.uuid4().hex, source=source, url=url, **metadata)
            patch(item, payload, p)
            item.title = item.title or url or 'Untitled note'
            p.bin.append(item)
            store.save(p)
            return listing(p)

    @app.patch(base + '/labels')
    def edit_labels(pid: str, payload: dict = Body(...)):
        with store.lock_for(pid):
            p = load(pid)
            action = payload.get('action', 'rename')
            old, new = payload.get('old'), payload.get('new')
            if action == 'reorder':
                order = payload.get('labels')
                if (not isinstance(order, list) or any(not isinstance(l, str) for l in order)
                        or len(order) != len(p.labels) or set(order) != set(p.labels)):
                    raise HTTPException(400, 'Supply every label exactly once')
                p.labels = order
            elif action == 'delete' and old in p.labels:
                p.labels.remove(old)
                for item in p.bin:
                    item.labels = [l for l in item.labels if l != old]
            elif action == 'rename' and old in p.labels and isinstance(new, str) and new.strip():
                new = new.strip()
                p.labels = list(dict.fromkeys(new if l == old else l for l in p.labels))
                for item in p.bin:
                    item.labels = list(dict.fromkeys(new if l == old else l for l in item.labels))
            else:
                raise HTTPException(400, 'Choose an existing label and a nonempty name')
            store.save(p)
            return listing(p)

    @app.patch(base + '/selection')
    def label_selection(pid: str, payload: dict = Body(...)):
        with store.lock_for(pid):
            p = load(pid)
            ids, label, action = payload.get('ids'), payload.get('label'), payload.get('action')
            if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids)
                    or not isinstance(label, str) or not label.strip()
                    or not isinstance(action, str) or action not in {'add', 'remove', 'toggle'}):
                raise HTTPException(400, 'Choose items, a nonempty label and add, remove or toggle')
            selected = [item_for(p, ident) for ident in dict.fromkeys(ids)]
            label = label.strip()
            if action == 'toggle':
                action = 'remove' if all(label in item.labels for item in selected) else 'add'
            for item in selected:
                patch(item, {'labels': list(dict.fromkeys(item.labels + [label])) if action == 'add'
                      else [l for l in item.labels if l != label]}, p)
            store.save(p)
            return listing(p)

    @app.patch(base + '/{ident}')
    def edit(pid: str, ident: str, payload: dict = Body(...)):
        with store.lock_for(pid):
            p = load(pid)
            patch(item_for(p, ident), payload, p)
            store.save(p)
            return listing(p)

    @app.delete(base + '/{ident}')
    def remove(pid: str, ident: str):
        with store.lock_for(pid):
            p = load(pid)
            item = item_for(p, ident)
            if item.file and item.source == 'dropped':
                path = owned(pid, item.file)
                if path.is_file():
                    dest = owned(pid, f'bin/.removed/{path.name}')
                    dest.parent.mkdir(exist_ok=True)
                    if dest.exists():
                        raise HTTPException(409, 'Removed file already exists')
                    path.rename(dest)
            p.bin.remove(item)
            store.save(p)
            return listing(p)

    @app.get(base + '/{ident}/{part}')
    def media(pid: str, ident: str, part: str):
        if part not in {'file', 'thumb'}:
            raise HTTPException(404, 'Unknown bin media')
        path = file_path(pid, item_for(load(pid), ident), thumb=part == 'thumb')
        if not path or not path.is_file():
            raise HTTPException(404, 'Bin media missing')
        return FileResponse(path)

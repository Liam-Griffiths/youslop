"""Thumbnail migration contracts; no browser, encoder or LLM required."""
import io
from copy import deepcopy

from PIL import Image
import pytest

from app import main, scenes, stage, store, thumbs
from app.schema import Project


def png():
    out = io.BytesIO()
    Image.new('RGB', (1280, 720), '#123456').save(out, 'PNG')
    return out.getvalue()


def test_template_keys():
    files = {p.stem for p in (scenes.SCENE_DIR / 'thumbs').glob('*.html')
             if not p.name.startswith('_')}
    assert files == set(thumbs.TEMPLATE_KEYS)
    p = Project.from_dict({'id': 'old', 'idea': '', 'style': {'unknown': 1}})
    assert p.style.thumb_engine == 'scene'
    p.style.thumb_engine = 'pillow'
    assert Project.from_dict(p.to_dict()).style.thumb_engine == 'pillow'


@pytest.mark.parametrize('key', thumbs.TEMPLATE_KEYS)
def test_templates_capture_and_cache(project, tmp_path, monkeypatch, key):
    project.thumb.template = key
    project.thumb.headline = '<A long & interesting headline>'
    project.thumb.image = 'portrait #1.png'
    Image.new('RGB', (400, 600), 'orange').save(tmp_path / project.thumb.image)
    calls = []

    def capture(items, directory, **roots):
        assert len(items) == 1
        item = items[0]
        assert (item['W'], item['H'], item['size'], item['t']) == (1280, 720, (1280, 720), 0)
        assert roots['project_root'] == str(tmp_path)
        html = next(directory.glob('*.html')).read_text()
        assert scenes.lint(html) == []
        assert '/project/thumb/bed-' in html
        assert 'data-var-text="headline"' in html
        assert r'\u003cA long \u0026 interesting headline\u003e'.upper() in html.upper()
        calls.append(item)
        return {item['clip']: png()}

    monkeypatch.setattr(stage, 'capture_stills', capture)
    for _ in range(2):
        result = thumbs.render_thumb(project, tmp_path, tmp_path / 'out.jpg')
        with Image.open(result) as image:
            assert image.size == (1280, 720)
            assert image.format == 'JPEG'
        assert result.stat().st_size < 2_000_000
    assert len(calls) == 1
    if key == 'sticker':
        assert len(list((tmp_path / 'thumb').glob('cutout-*.png'))) == 1


@pytest.mark.parametrize('mode', ['pillow', 'missing', 'failed'])
def test_fallback(project, tmp_path, monkeypatch, caplog, mode):
    calls = []
    def capture(*args, **kw):
        calls.append(1)
        raise stage.StageError('Chromium unavailable')
    monkeypatch.setattr(scenes, 'capture', capture)
    if mode == 'pillow':
        project.style.thumb_engine = 'pillow'
    elif mode == 'missing':
        monkeypatch.setattr(scenes, 'SCENE_DIR', tmp_path)
    out = thumbs.render_thumb(project, tmp_path, tmp_path / 'out.jpg')
    assert Image.open(out).size == (1280, 720)
    assert bool(calls) == (mode == 'failed')
    if mode == 'failed':
        assert 'using Pillow' in caplog.text


@pytest.mark.parametrize('route', ['render', 'pick', 'upload'])
def test_routes_render_unlocked_and_reload(project, monkeypatch, route):
    import asyncio
    import threading
    from fastapi import UploadFile

    root = store.project_dir(project.id)
    root.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (30, 30), 'red').save(root / 'source.png')
    store.save(project)
    calls = []
    def capture(snapshot, directory, out):
        # A second thread must acquire the lock while capture is in progress.
        def edit():
            with store.lock_for(project.id):
                current = store.load(project.id)
                current.title = 'Edited during capture'
                current.thumb.kicker = 'New kicker'
                store.save(current)
                calls.append(deepcopy(snapshot))
        worker = threading.Thread(target=edit)
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive(), 'capture held project lock'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b'jpeg')
        return out
    monkeypatch.setattr(thumbs, 'render_thumb', capture)
    if route == 'render':
        result = main.render_thumbnail(project.id)
    elif route == 'pick':
        result = main.thumb_pick(project.id, {'candidate': {'local_path': 'source.png'}})
    else:
        upload = UploadFile(filename='upload.png', file=io.BytesIO(png()))
        async def read():
            return png()
        monkeypatch.setattr(upload, 'read', read)
        result = asyncio.run(main.thumb_upload(project.id, upload))
    assert len(calls) == 1
    saved = store.load(project.id)
    assert saved.title == 'Edited during capture'
    assert result['thumb']['kicker'] == saved.thumb.kicker == 'New kicker'
    assert saved.thumb.rendered_at > 0
    if route != 'render':
        assert calls[0].thumb.image


def test_raster_cache_tracks_picture_and_controls(project, tmp_path):
    from urllib.parse import unquote

    project.thumb.template = 'banner'
    project.thumb.image = 'portrait #1.png'
    picture = tmp_path / project.thumb.image
    Image.new('RGB', (400, 600), 'orange').save(picture)
    def context():
        source = thumbs._Source(picture, project.thumb.focal, thumbs._accent(project))
        return thumbs.scene_context(project, tmp_path, source)['thumb']
    first = context()
    assert first['image'].endswith('portrait%20%231.png')
    assert context() == first
    # A replacement at the same path and a moved focal point invalidate rasters.
    Image.new('RGB', (400, 600), 'blue').save(picture)
    second = context()
    assert second['bed'] != first['bed']
    project.thumb.focal = [.2, .8]
    assert context()['bed'] != second['bed']
    for spec in (first, second, context()):
        rel = unquote(spec['bed'].split('/project/')[1])
        with Image.open(tmp_path / rel) as image:
            assert image.size == (1280, 720)

"""Browse/poster contracts. Never starts Chromium or a render."""
import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import block_library as library, blocks, channels, jobs, main, paths
from app.schema import Channel


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(library, '_POSTER_JOB', None)
    monkeypatch.delenv('CORKBORED_BLOCK_POSTERS', raising=False)
    meta = json.loads((blocks.BUILTIN_DIR / 'number_slam/block.json').read_text())
    root = tmp_path / 'block'
    root.mkdir()
    (root / 'block.json').write_text(json.dumps(meta))
    found = {'number_slam': dict(meta=meta, root=root)}
    monkeypatch.setattr(library, 'registry', lambda: found)
    return root, found


def test_metadata_shape_filters_and_legacy_id(isolated):
    channels.save(Channel(id='ctest', name='Test', blocks=['number_slam']))
    row = main.list_blocks(q='number', aspect='9:16', channel='ctest')[0]
    assert row['ref'] == row['id'] == 'number_slam'
    assert row['channels'] == ['ctest'] and row['source'] == 'built-in'
    assert {'description','category','tags','duration','licence','origin','check_status','variables','posters'} <= row.keys()
    for query in [dict(q='map'), dict(aspect='1:1'), dict(source='mine'), dict(category='unknown'), dict(data=True), dict(channel='absent')]:
        assert main.list_blocks(**query) == []
    assert row['posters'] == {}
    assert main.block_poster('number_slam').status_code == 204
    with pytest.raises(HTTPException) as error:
        main.block_poster('unknown')
    assert error.value.status_code == 400


def test_poster_signature_tracks_files_and_defaults(isolated):
    root, found = isolated
    first = library.poster_path('number_slam', '16:9')
    (root / 'asset.txt').write_text('new asset')
    second = library.poster_path('number_slam', '16:9')
    assert first != second
    meta = found['number_slam']['meta']
    meta['variables']['title']['default'] = 'New title'
    (root / 'block.json').write_text(json.dumps(meta))
    assert second != library.poster_path('number_slam', '16:9')
    path = library.poster_path('number_slam', '16:9')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'fixture png')
    assert main.block_poster('number_slam').path == path


def test_explicit_single_batch_and_snapshot_opt_out(isolated, monkeypatch):
    start = Mock(return_value='jposters')
    monkeypatch.setattr(jobs, 'start', start)
    monkeypatch.setattr(jobs, 'get', lambda jid: {'state':'running'})
    assert library.start_posters() == library.start_posters() == {'job':'jposters'}
    start.assert_called_once_with('block posters', '', library.make_posters, cancellable=True)
    monkeypatch.setenv('CORKBORED_BLOCK_POSTERS', 'off')
    assert library.start_posters() == {'job':None}


def test_batch_one_session_quarter_size_and_atomic_publish(isolated, monkeypatch, tmp_path):
    root, found = isolated
    monkeypatch.setattr(library.scenes, '_prepare', lambda owner, template, ctx, *a:
                        ('key', tmp_path / 'scenes/key.html', ctx))
    calls = []
    def capture(items, directory, **kw):
        calls.append(items)
        for item in items:
            assert item['size'] in ((480,270),(270,480)) and item['assets_root'] == str(root)
            kw['scene_probe'](None, None, item, item['t'])
            kw['on_still'](item['clip'], b'png fixture')
    monkeypatch.setattr(library.stage, 'capture_stills', capture)
    assert library.make_posters(lambda message: None) == {'posters':2}
    assert len(calls) == 1
    assert library.poster_path('number_slam','9:16').read_bytes() == b'png fixture'
    assert library.start_posters() == {'job':None}


def test_registry_reuses_scan_and_invalidates_on_file_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks, 'BUILTIN_DIR', tmp_path)
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'users')
    monkeypatch.setattr(library.packs, 'BUILTIN_DIR', tmp_path / 'builtin-packs')
    monkeypatch.setattr(library.packs, 'PACKS_DIR', tmp_path / 'packs')
    monkeypatch.setattr(library, '_REGISTRY', (None, {}))
    discover = Mock(return_value={})
    monkeypatch.setattr(blocks, 'discover', discover)
    library.registry(); library.registry()
    assert discover.call_count == 1
    (tmp_path / 'block.json').write_text('{}')
    library.registry()
    assert discover.call_count == 2


def test_trial_cache_validation_and_snapshot_switch(isolated, monkeypatch):
    monkeypatch.setattr(library, '_REQUESTS', {})
    capture = Mock(return_value=b'quarter png')
    monkeypatch.setattr(library.scenes, 'capture', capture)
    result = library.preview('number_slam', {}, '9:16', 'trial', 'session', 1)
    assert main.block_preview_file(result['url'].split('/')[-2], 'trial').path.read_bytes() == b'quarter png'
    assert capture.call_args.kwargs['size'] == (270, 480)
    assert library.preview('number_slam', {}, '9:16', 'trial', 'session', 2)['url'] == result['url']
    assert capture.call_count == 1
    with pytest.raises(ValueError, match='maxLength'):
        library.preview('number_slam', {'title':'W'*999}, '9:16', 'trial', 'session', 3)
    monkeypatch.setenv('CORKBORED_BLOCK_POSTERS', 'off')
    assert library.preview('number_slam', {}, '16:9', 'motion', 'session', 4) == {'disabled':True}
    assert capture.call_count == 1


def test_motion_serializes_with_trials_and_drops_stale(isolated, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    monkeypatch.setattr(library, '_REQUESTS', {})
    entered, release, queued = Event(), Event(), Event()
    clip = tmp_path / 'mock.mp4'
    clip.write_bytes(b'mock movie')
    def render(*args, **kw):
        assert kw['size'] == (480,270) and kw['max_seconds'] == 6
        entered.set()
        assert release.wait(2)
        return clip
    monkeypatch.setattr(blocks, 'render', render)
    capture = Mock(return_value=b'png')
    monkeypatch.setattr(library.scenes, 'capture', capture)
    # Signal when the newer request reaches the shared render gate.
    real_lock = library._RENDER_LOCK
    class Gate:
        def __enter__(self):
            if entered.is_set(): queued.set()
            real_lock.acquire()
        def __exit__(self, *args): real_lock.release()
    monkeypatch.setattr(library, '_RENDER_LOCK', Gate())
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(library.preview, 'number_slam', {}, '16:9', 'motion', 'same', 1)
        assert entered.wait(2)
        second = pool.submit(library.preview, 'number_slam', {}, '16:9', 'trial', 'same', 2)
        try:
            assert queued.wait(2)
            capture.assert_not_called()
        finally:
            release.set()
        assert first.result() == {'stale':True}
        assert second.result()['url'].endswith('/trial')
    assert library.preview('number_slam', {}, '16:9', 'motion', 'same', 1) == {'stale':True}


def test_apply_patch_reaches_segment_builder_without_rendering(tmp_path, monkeypatch):
    from app import render, scene_builder, store
    from app.schema import Project, Slide, group_slides
    project = Project(id='pblocks', title='Blocks', idea='', slides=[Slide(id='s1', narration='Forty two')])
    project.use_intro = project.use_outro = False
    slide = project.slides[0]
    slide.cues = {'ticker':[{'kind':'text','text':'Keep me'}]}
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    store.save(project)
    saved = main.patch_slide(project.id, slide.id, {'cues':{'blocks':[{'block':'number_slam','vars':{'title':'Trial title'}}]}, 'picture_mode':'new'})
    assert saved['cues']['ticker'] == slide.cues['ticker']
    project = store.load(project.id)
    slide = project.slides[0]
    after = Slide(id='s2', narration='Another', picture_mode='hold')
    assert len(group_slides([slide,after],8)) == 2
    builder = Mock()
    monkeypatch.setattr(scene_builder, 'render', builder)
    monkeypatch.setattr(render, '_chapter_tail', lambda p,out,*a: out)
    out = tmp_path / 'segment.webm'
    assert render._render_segment(project, [(slide,5)], 5,0,out,size=(480,270)) == out
    args, kw = builder.call_args
    assert args[1].startswith('_blocks/number_slam/')
    assert args[2]['vars']['title'] == 'Trial title'
    assert args[2]['duration'] == kw['seconds'] == 5
    assert kw['size'] == (480,270)


def test_motion_builder_receives_quarter_size_and_cap(tmp_path, monkeypatch):
    from app import scene_builder
    prepare = Mock(return_value=('fixture.html', {'width':1920,'height':1080,'duration':10}))
    monkeypatch.setattr(blocks, 'prepare', prepare)
    prepared = Mock(side_effect=lambda owner,template,ctx,seconds,size,*a:
                    ('key',tmp_path / 'clip.html',ctx))
    monkeypatch.setattr(blocks.scenes, '_prepare', prepared)
    builder = Mock()
    monkeypatch.setattr(scene_builder, 'render', builder)
    blocks.render('fixture',size=(480,270),max_seconds=6)
    assert prepared.call_args.args[3:5] == (6,(480,270))
    assert builder.call_args.kwargs['size'] == (480,270)
    assert builder.call_args.kwargs['seconds'] == 6

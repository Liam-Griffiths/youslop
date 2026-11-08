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
    def render(ref, values, aspect, ctx, out, size, ground):
        assert size == (480,270)
        assert ctx['duration'] == 6
        out.write_bytes(b'mock movie')
        entered.set()
        assert release.wait(2)
    monkeypatch.setattr(library, 'render_motion', render)
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


def test_preferences_persist_atomically_and_filter_pins(isolated, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    real_replace = library.os.replace
    replaced = []
    def replace(source, target):
        assert source.parent == target.parent and source != target
        replaced.append(target)
        real_replace(source, target)
    monkeypatch.setattr(library.os, 'replace', replace)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(library.preferences, 'number_slam', favourite=True)
        b = pool.submit(library.preferences, 'number_slam', used=True)
        a.result(); b.result()
    prefs = json.loads((tmp_path / 'blocks_prefs.json').read_text())
    assert prefs['favourites'] == ['number_slam'] and prefs['recent']['number_slam'] > 0
    assert len(replaced) == 2
    channels.CHANNELS_DIR.mkdir(exist_ok=True)
    row = library.browse()[0]
    assert row['favourite'] and row['recent'] == prefs['recent']['number_slam']
    library.preferences('number_slam', favourite=False)
    assert library.preferences()['favourites'] == []
    assert library.preferences()['recent'] == prefs['recent']
    assert main.favourite_block('number_slam', {'favourite':True})['favourites'] == ['number_slam']
    with pytest.raises(HTTPException):
        main.favourite_block('number_slam', {'favourite':'yes'})


@pytest.mark.parametrize('failure', [None, 'lint', 'browser', 'exception'])
def test_duplicate_checks_and_cleans_only_new_folder(tmp_path, monkeypatch, failure):
    from app import block_authoring as kit, scene_builder
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'mine')
    monkeypatch.setattr(blocks, 'BUILTIN_DIR', tmp_path / 'builtin')
    source = kit.new('source')
    reserved = blocks.USER_DIR / 'source-copy'
    reserved.mkdir()
    (reserved / 'keep.txt').write_text('existing work')
    if failure == 'lint':
        (source / 'block.html').write_text(kit.TEMPLATE.replace('{{ vars.title }}', '{{ forbidden() }}'))
    before = {p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    # Check's Jinja/sandbox/lint remain real; only its browser operations are mocked.
    inspect = Mock(return_value={})
    if failure == 'exception':
        inspect.side_effect = RuntimeError('browser unavailable')
    monkeypatch.setattr(scene_builder, 'inspect', inspect)
    def browser(job, progress, *, scene_probe):
        if failure == 'browser':
            raise ValueError('browser check failed')
    monkeypatch.setattr(kit.stage, '_run_cdp', browser)
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            library.duplicate('user/source')
        assert set(blocks.USER_DIR.iterdir()) == {source, reserved}
        if failure == 'lint': inspect.assert_not_called()
    else:
        first = library.duplicate('user/source')['id']
        second = library.duplicate('user/source')['id']
        assert first != second and first.startswith('user/source-')
        for ref in [first, second]:
            meta = blocks.discover()[ref]['meta']
            assert meta['origin']['forked_from'] == 'user/source'
            assert kit.lint(ref) == []
        assert inspect.call_count == 6
    assert (reserved / 'keep.txt').read_text() == 'existing work'
    assert before == {p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}


def test_recent_only_after_successful_apply(tmp_path, monkeypatch):
    from app import store
    from app.schema import Project, Slide
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    p = Project(id='precent', title='Recent', idea='', slides=[Slide(id='s1')])
    store.save(p)
    assert library.preferences()['recent'] == {}
    with pytest.raises(HTTPException):
        main.patch_slide(p.id, 's1', {'cues':{'blocks':[{'block':'missing'}]}})
    assert library.preferences()['recent'] == {}
    main.patch_slide(p.id, 's1', {'cues':{'blocks':[{'block':'number_slam','vars':{}}]}})
    used = library.preferences()['recent']['number_slam']
    main.patch_slide(p.id, 's1', {'title':'Other edit'})
    assert library.preferences()['recent']['number_slam'] == used
    monkeypatch.setattr(store, 'save', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        main.patch_slide(p.id, 's1', {'cues':{'blocks':[{'block':'number_slam','vars':{}}]}})
    assert library.preferences()['recent']['number_slam'] == used


def test_library_picker_reference_resolves_in_preview_and_segment(tmp_path, monkeypatch):
    from app import block_authoring as kit, library as media, render, scenes, scene_builder
    from app.schema import Project, Slide
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'blocks')
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    image = tmp_path / 'linked.png'
    image.write_bytes(b'image fixture')
    monkeypatch.setattr(media, 'file_path', lambda asset_id: image if asset_id == 'img1' else None)
    root = kit.new('picture')
    meta = json.loads((root / 'block.json').read_text())
    meta['variables']['picture'] = dict(type='image', default='')
    meta['duration'] = dict(mode='range', min=1, max=20)
    (root / 'block.json').write_text(json.dumps(meta))
    (root / 'block.html').write_text(kit.TEMPLATE.replace('{{ vars.title }}', '{{ vars.title }}<img src="{{ vars.picture }}">'))
    ref = '/scene/{token}/library/img1'
    values = dict(picture=ref)
    assert blocks.validate_vars(meta, values)['picture'] == ref
    for bad in ['/scene/{token}/library/../img1', '/scene/{token}/library/missing']:
        with pytest.raises(ValueError): blocks.validate_vars(meta, dict(picture=bad))
    seen = []
    def resolve(template, ctx):
        assert ctx['vars']['picture'] == ref
        assert ref in scenes.render_html(template, ctx)
        seen.append(scenes._local_file(ref, tmp_path, ctx['block_assets_root']))
    def capture(owner, template, ctx, **kw):
        resolve(template, ctx)
        return b'preview fixture'
    monkeypatch.setattr(library.scenes, 'capture', capture)
    monkeypatch.delenv('CORKBORED_BLOCK_POSTERS', raising=False)
    assert library.preview('user/picture', values, '16:9', 'trial', 'image-test', 1)['url']
    p = Project(id='pimage', title='Image', idea='', slides=[Slide(id='s1',cues={'blocks':[{'block':'user/picture','vars':values}]})])
    p.use_intro = p.use_outro = False
    monkeypatch.setattr(scene_builder, 'render', lambda owner,template,ctx,*a,**kw: resolve(template,ctx))
    monkeypatch.setattr(render, '_chapter_tail', lambda p,out,*a: out)
    render._render_segment(p, [(p.slides[0],5)],5,0,tmp_path/'segment.webm',size=(480,270))
    assert seen == [image.resolve(),image.resolve()]
    native = kit.TEMPLATE.replace('{{ vars.title }}', '<span data-media="{{ vars.picture }}"></span>')
    (root / 'block.html').write_text(native)
    template, ctx = blocks.prepare('user/picture', values)
    assert f'data-media="{image.resolve()}"' in scenes.render_html(template, ctx)


def test_motion_webm_sizes_duration_and_background_cache(isolated, monkeypatch):
    monkeypatch.setattr(library, '_REQUESTS', {})
    calls = []
    def render(ref, values, aspect, ctx, out, size, ground):
        calls.append((ctx['duration'], size, ground))
        out.write_bytes(b'webm fixture')
    monkeypatch.setattr(library, 'render_motion', render)
    first = library.preview('number_slam', {}, '16:9', 'motion', 'sizes', 1)
    key = first['url'].split('/')[-2]
    assert library.preview_file(key, 'motion').suffix == '.webm'
    assert main.block_preview_file(key, 'motion').media_type == 'video/webm'
    assert library.preview('number_slam', {}, '16:9', 'motion', 'sizes', 2)['url'] == first['url']
    half = main.block_preview('number_slam', dict(kind='motion', session='sizes', sequence=3, scale=2))
    assert half['url'] != first['url']
    assert calls == [(6, (480,270), None), (6, (960,540), None)]
    for scale in [True, 1, '2']:
        with pytest.raises(ValueError):
            library.preview('number_slam', {}, '16:9', 'motion', 'sizes', 4, scale=scale)


def test_preview_overlay_flattens_scratch_only(tmp_path, monkeypatch):
    from app import scene_builder
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    def render(owner, template, ctx, out, **kw):
        assert ctx['builder_alpha'] and kw['seconds'] == 5
        assert out.suffix == '.mov' and out.parent != tmp_path
        out.write_bytes(b'alpha fixture')
    def flatten(args):
        from PIL import Image
        with Image.open(args[3]) as image:
            assert image.getpixel((0,0)) != image.getpixel((20,0))
        assert 'libvpx-vp9' in args
        Path(args[-1]).write_bytes(b'flat webm')
    from pathlib import Path
    monkeypatch.setattr(scene_builder, 'render', render)
    monkeypatch.setattr(library.ffutil, 'run', flatten)
    _, ctx = blocks.prepare('lower_third_panel')
    out = tmp_path / 'preview.webm'
    library.render_motion('lower_third_panel', {}, '16:9', ctx, out, (480,270), None)
    assert out.read_bytes() == b'flat webm'


def test_preview_project_picture_is_local_and_uses_held_lead(tmp_path, monkeypatch):
    from app import store
    from app.schema import Project, Slide
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    lead = Slide(id='s1', chosen_id='pic', candidates=[dict(id='pic',local_path='media/pic.png')])
    p = Project(id='ppreview', title='', idea='', slides=[lead, Slide(id='s2', picture_mode='hold')])
    store.save(p)
    picture = store.project_dir(p.id) / 'media/pic.png'
    picture.write_bytes(b'picture')
    assert library.preview_background('project',p.id,'s2') == picture
    lead.candidates[0]['local_path'] = '../../outside.png'
    store.save(p)
    with pytest.raises(ValueError, match='no still picture'):
        library.preview_background('project',p.id,'s1')
    with pytest.raises(ValueError):
        library.preview_background('project','../escape','s1')


@pytest.mark.parametrize('duration,expected', [(5,5), (20,15)])
def test_motion_duration_default_and_cap(tmp_path, monkeypatch, duration, expected):
    from app import scene_builder
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    template, ctx = blocks.prepare('title_card')
    assert ctx['duration'] == 5
    ctx['duration'] = duration
    monkeypatch.setattr(blocks, 'prepare', lambda *a, **kw: (template, ctx))
    def render(owner, template, ctx, out, **kw):
        assert kw['seconds'] == expected and ctx['duration'] == expected
        assert out.suffix == '.webm' and not ctx.get('builder_alpha')
        out.write_bytes(b'webm')
    monkeypatch.setattr(scene_builder, 'render', render)
    library.render_motion('title_card', {}, '16:9', ctx, tmp_path/'preview.webm', (480,270), None)

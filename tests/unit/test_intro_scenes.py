"""Intro migration contracts without Chromium, sockets, encoders or LLMs."""
from pathlib import Path

import pytest

from app import scene_builder, channels, intro, main, render, scenes, stage
from app.schema import Channel


@pytest.mark.parametrize('kind', ['project', 'channel'])
def test_asset_paths(tmp_path, kind):
    root = tmp_path / kind
    root.mkdir()
    (root / 'portrait.png').write_bytes(b'portrait')
    (root / 'escape').symlink_to(tmp_path / 'private.png')
    run = stage._Run({'scene_root': str(tmp_path / 'scenes'),
                      kind + '_root': str(root)}, None)
    translate = object.__new__(stage._handler(run)).translate_path
    prefix = f'/scene/{run.token}/{kind}/'
    assert translate(prefix + 'portrait.png') == str(root / 'portrait.png')
    for rel in ('../private.png', '%2e%2e/private.png', 'sub/../portrait.png',
                'escape', '/private.png', '', 'odd..png'):
        assert translate(prefix + rel) == '/nonexistent'
    assert translate('/scene/wrong/' + kind + '/portrait.png') == '/nonexistent'
    assert translate(f'/scene/{run.token}/' + ('channel' if kind == 'project' else 'project') + '/portrait.png') == '/nonexistent'


@pytest.mark.parametrize('name', ['solo', 'dossier', 'folio', 'portrait'])
@pytest.mark.parametrize('duration,expected', [(1, 2.5), (6, 6), (30, 12)])
def test_intro_dispatch_and_duration(tmp_path, monkeypatch, name, duration, expected):
    ch = Channel(id='intro-test', name='A <series>', tagline='A kicker')
    ch.intro.template = 'scene:intro_' + name
    ch.intro.duration = duration
    root = channels.channel_dir(ch.id)
    (root / 'intro/face.png').write_bytes(b'portrait')
    ch.intro.images = ['intro/face.png']
    assert ch.intro.template in {t['key'] for t in main.intro_templates()}

    def ensure(owner, template, ctx, out, **kw):
        assert template == 'cards/intro_' + name + '.html'
        assert kw['seconds'] == expected
        assert ctx['vars']['title'] == 'Episode'
        assert ctx['portrait_url'] == '/scene/{token}/channel/intro/face.png'
        assert ctx['asset_roots']['channel_root'] == str(root)
        html = scenes.render_html(template, {**ctx, 'duration': expected})
        assert scenes.lint(html) == []
        assert r'A \u003cseries\u003e' in html
        assert 'data-motion="rise"' in html
        assert 'data-motion-exit=' in html
        return tmp_path / 'cache.mp4'

    monkeypatch.setattr(scene_builder, 'render', ensure)
    monkeypatch.setattr(scenes, '_encode', lambda *a, **kw: None)
    assert intro.render_intro(ch, 'Episode', tmp_path / 'preview.webm') == expected
    assert intro.SOLO_DEFAULT == 'signal'


def test_portrait_cache_and_guard(tmp_path):
    ch = Channel(id='portrait-cache', name='Series')
    root = channels.channel_dir(ch.id)
    portrait = root / 'intro/face.png'
    portrait.write_bytes(b'first')
    ch.intro.images = ['intro/face.png']
    first = scenes.intro_context(ch)
    portrait.write_bytes(b'second')
    assert scenes.intro_context(ch)['portrait_hash'] != first['portrait_hash']
    (root / 'escape').symlink_to(tmp_path / 'private')
    ch.intro.images = ['../private', 'escape', '/etc/passwd', 'missing']
    assert scenes.intro_context(ch)['portrait_url'] == ''


def test_preview_sting_and_timeline_dispatch(project, tmp_path, monkeypatch):
    ch = Channel(id='preview-intro', name='Series')
    ch.intro.template = 'scene:intro_portrait'
    ch.intro.images = ['intro/face.png']
    ch.intro.music = 'intro/sting.wav'
    (channels.channel_dir(ch.id) / ch.intro.music).write_bytes(b'sting')
    project.channel_id = ch.id
    project.use_intro = True
    calls = []
    monkeypatch.setattr(main, '_channel', lambda cid: ch)
    monkeypatch.setattr(channels, 'load_or_none', lambda cid: ch)
    monkeypatch.setattr(intro, 'preview_path', lambda c: tmp_path / 'preview.webm')

    def card(kind, name, channel, title, out, progress):
        calls.append((kind, name))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b'picture')
        return 5

    monkeypatch.setattr(scenes, 'render_card', card)
    monkeypatch.setattr(intro, 'mux_sting', lambda c, out, seconds, progress: calls.append(('sting', seconds)))
    monkeypatch.setattr(main.jobs, 'start', lambda kind, cid, fn: fn(lambda msg: None))
    assert main.preview_intro(ch.id, {}) == {'job': {'path': 'cache/intro_preview.webm'}}
    assert calls == [('intro', 'intro_portrait'), ('sting', 5)]
    assert render._has_slate(project)
    assert render._build_intro(project, lambda msg: None, tmp_path / 'timeline.webm')[1] == 5
    assert 'intro' in render._stings_for(project, True, False)


def test_roots_reach_capture_and_render(project, tmp_path, monkeypatch):
    ch = Channel(id='roots', name='Series')
    ctx = scenes.context_base(project, ch)
    calls = []

    def capture(*args, **kw):
        calls.append(kw)
        return b'png'

    def encode(items, directory):
        calls.append(items[0])
        out = directory / (items[0]['clip'] + '.mp4')
        out.write_bytes(b'clip')
        return {items[0]['clip']: out}

    monkeypatch.setattr(stage, 'capture_one', capture)
    monkeypatch.setattr(stage, 'render_scene', encode)
    scenes.capture(tmp_path, '_test/base.html', ctx, t=1, size=(480, 270))
    scenes.ensure_clip(tmp_path, '_test/base.html', ctx, seconds=5, size=(480, 270), fps=30)
    for call in calls:
        assert call['project_root'] == ctx['asset_roots']['project_root']
        assert call['channel_root'] == ctx['asset_roots']['channel_root']


def test_stage_job_asset_roots(tmp_path, monkeypatch):
    from types import SimpleNamespace

    jobs = []

    def cdp(job, *args, **kwargs):
        jobs.append(job)
        return SimpleNamespace(clips={}, thumbs={'snapshot': b'png'})

    monkeypatch.setattr(stage, '_run_cdp', cdp)
    roots = dict(project_root=str(tmp_path / 'project'), channel_root=str(tmp_path / 'channel'))
    stage.render_scene([dict(scene_root=str(tmp_path), **roots)], tmp_path)
    stage.capture_one('/static/test.html', 1920, 1080, 2, (480, 270), **roots)
    for job in jobs:
        for kind, root in roots.items():
            assert job[kind] == root

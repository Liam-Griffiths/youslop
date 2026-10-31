"""Render integration contracts, without Chromium, sockets or real rendering."""
from pathlib import Path

import pytest

from app import audio, cuts, ffutil, intro, outro, render, scenes
from app.config import HEAD_PAD, PARAGRAPH_GAP
from app.schema import Channel


@pytest.mark.parametrize('first', [True, False])
def test_scene_branch_matches_cut_timing(project, tmp_path, monkeypatch, first):
    project.style.format = 'flameboat'
    group = [(project.slides[0 if first else 1], 3.0)]
    out = tmp_path / 'out.webm'
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return out

    monkeypatch.setattr(scenes, 'handles', lambda fmt: fmt == 'flameboat')
    monkeypatch.setattr(scenes, 'render_segment', record)
    monkeypatch.setattr(cuts, 'render_segment', record)
    chapter = ('Next chapter', 'Subtitle')
    channel = Channel(id='ctest', name='Example')
    kwargs = dict(channel=channel, chapter=chapter, size=(480, 270), fps=15, crf=28)
    assert render._render_segment(project, group, 4, 0, out, **kwargs) == out
    monkeypatch.setattr(scenes, 'handles', lambda fmt: False)
    assert render._render_segment(project, group, 4, 0, out, **kwargs) == out
    scene, cut = calls
    assert scene[0] == cut[0] == (project, group, 4, out)
    for key in (*kwargs, 'lead_in', 'hold'):
        assert scene[1][key] == cut[1][key]
    assert scene[1]['lead_in'] == cuts.transition_for(project.style) / 2 + (HEAD_PAD if first else 0)
    assert scene[1]['hold'] == max(0.9, min(3.2, audio.gap_map(project).get(
        group[-1][0].id, PARAGRAPH_GAP) - 0.12))


@pytest.mark.parametrize('fmt', ['_test', 'flameboat'])
def test_scene_context_and_encoding(project, tmp_path, monkeypatch, fmt):
    project.style.format = fmt
    group = [(project.slides[0], 3.0)]
    captured = {}
    commands = []

    def ensure(owner, template, ctx, **kwargs):
        captured.update(owner=owner, template=template, ctx=ctx, **kwargs)
        return tmp_path / 'cached.mp4'

    monkeypatch.setattr(scenes, 'ensure_clip', ensure)
    monkeypatch.setattr(ffutil, 'run', lambda args: commands.append(args))
    out = tmp_path / 'proxy.webm'
    assert scenes.render_segment(project, group, 4, out, size=(480, 270), fps=15,
                                 chapter=('Next', ''), lead_in=0.6, hold=1) == out
    assert captured['size'] == (1920, 1080)
    assert captured['seconds'] == 4 and captured['fps'] == 15
    ctx = captured['ctx']
    assert ctx['narration'] == group[0][0].narration
    assert ctx['titles'] == [group[0][0].title]
    assert ctx['chapter'] == ('Next', '') and ctx['lead_in'] == 0.6
    assert ctx['cues'] == (cuts.timed_cues(project, group, 4, 0.6) if fmt == 'flameboat' else [])
    assert 'scale=480:270' in commands[0] and 'libvpx-vp9' in commands[0]
    if fmt == '_test':
        assert scenes.handles(fmt)
        assert scenes.lint(scenes.render_html(captured['template'], {**ctx, 'duration': 4})) == []


@pytest.mark.parametrize('kind', ['intro', 'outro'])
def test_card_dispatch_and_duration(tmp_path, monkeypatch, kind):
    channel = Channel(id='ctest', name='Example')
    getattr(channel, kind).template = 'scene:_test'
    getattr(channel, kind).duration = 100
    commands = []

    def ensure(owner, template, ctx, **kwargs):
        assert template == 'cards/_test.html'
        assert ctx['vars']['title'] == 'Episode'
        assert ctx['card']['template'] == 'scene:_test'
        assert scenes.lint(scenes.render_html(template, {**ctx, 'duration': kwargs['seconds']})) == []
        return tmp_path / 'cache.mp4'

    monkeypatch.setattr(scenes, 'ensure_clip', ensure)
    monkeypatch.setattr(ffutil, 'run', lambda args: commands.append(args))
    renderer = intro.render_intro if kind == 'intro' else outro.render_outro
    assert renderer(channel, 'Episode', tmp_path / 'preview.webm') == (12 if kind == 'intro' else 20)
    assert 'libvpx-vp9' in commands[0]
    assert not intro.needs_images('scene:_test')


@pytest.mark.parametrize('field', ['title', 'subtitle', 'frame', 'version'])
def test_proxy_key_scene_inputs(project, monkeypatch, field):
    groups = [[(project.slides[0], 3.0)]]
    before = render._proxy_key(project, groups, 0, None)
    if field == 'version':
        monkeypatch.setattr(scenes, 'SCENE_VERSION', scenes.SCENE_VERSION + 1)
    elif field == 'frame':
        project.frame.arrive_s += 0.1
    else:
        setattr(project, field, getattr(project, field) + ' changed')
    assert render._proxy_key(project, groups, 0, None) != before


def test_preview_routes_scene(project, monkeypatch):
    project.style.format = '_test'
    project.slides = project.slides[:1]
    calls = []

    def segment(*args, **kwargs):
        calls.append(kwargs)
        args[3].write_bytes(b'fake webm')
        return args[3]

    def no_voice(*args, **kwargs):
        raise ValueError('No take')

    monkeypatch.setattr(scenes, 'render_segment', segment)
    monkeypatch.setattr(render.media, 'download_chosen', lambda *a, **kw: False)
    monkeypatch.setattr(audio, 'build_slice', no_voice)
    result = render.preview_segment(project, project.slides[0].id)
    assert Path(result['path']).suffix == '.webm'
    assert calls[0]['size'] == render.preview_size()
    assert calls[0]['fps'] == render.PREVIEW_FPS


def test_solo_card_frame_and_cache(project, monkeypatch):
    project.channel_id = ''
    project.intro.template = 'scene:_test'
    before = render._slate_key(project, 'intro')
    project.frame.arrive_s += 0.1
    channel = render._slate_channel(project)
    assert channel.frame.to_dict() == project.frame.to_dict()
    assert channel.frame is not project.frame
    assert render._slate_key(project, 'intro') != before
    before = render._slate_key(project, 'intro')
    monkeypatch.setattr(scenes, 'SCENE_VERSION', scenes.SCENE_VERSION + 1)
    assert render._slate_key(project, 'intro') != before

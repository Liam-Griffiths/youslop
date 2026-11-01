"""Outro geometry and chapter dispatch contracts; no browser or real renders."""
from pathlib import Path

import pytest

from app import scene_builder, board, ffutil, outro, render, scenes
from app.schema import Channel


@pytest.mark.parametrize('key,slots,expected', [
    ('twoup', 0, []), ('twoup', 1, [(1388, 346, 400)]),
    ('twoup', 2, [(944, 346, 400), (1388, 346, 400)]),
    ('quiet', 1, [(795, 483, 330)]),
    ('quiet', 2, [(602, 483, 330), (988, 483, 330)]),
])
def test_plate_geometry_and_template(key, slots, expected):
    channel = Channel(id='ctest', name='A <channel>')
    channel.outro.template = 'scene:outro_' + key
    channel.outro.slots = slots
    ctx = scenes.context_base(channel=channel)
    ctx.update(scenes.outro_context(channel))
    assert [(p['x'], p['y'], p['width']) for p in ctx['plates']] == expected
    assert not outro.wants_backdrop(channel.outro.template)
    assert outro.max_slots(channel.outro.template) == 2
    html = scenes.render_html('cards/outro_' + key + '.html', ctx)
    assert scenes.lint(html) == []
    assert 'data-motion="rise"' in html and 'data-motion-exit=' not in html
    assert r'A \u003cchannel\u003e' in html


@pytest.mark.parametrize('fmt', ['board', 'custom:example'])
@pytest.mark.parametrize('chapter,seconds,wanted', [(('Next', 'Part two'), 6, True),
                                                  (None, 6, False),
                                                  (('Next', ''), .5, False)])
def test_chapter_after_render(project, tmp_path, monkeypatch, fmt, chapter, seconds, wanted):
    project.style.format = fmt
    out = tmp_path / 'out.webm'
    calls = []

    def picture(*args, **kwargs):
        calls.append('picture')
        return out

    def clip(owner, template, ctx, out, **kwargs):
        calls.append('chapter')
        assert template == 'cards/chapter.html'
        assert ctx['vars']['title'] == 'Next'
        assert scenes.lint(scenes.render_html(template, {**ctx, 'duration': kwargs['seconds']})) == []
        assert kwargs['size'] == (480, 270) and kwargs['fps'] == 15
        return tmp_path / 'card.mp4'

    def overlay(path, card, start, **kwargs):
        calls.append('overlay')
        assert path == out and 0 < start < seconds

    monkeypatch.setattr(board, 'render_segment', picture)
    monkeypatch.setattr(render, '_render_custom_style', picture)
    monkeypatch.setattr(scene_builder, 'render', clip)
    monkeypatch.setattr(render, '_overlay_tail', overlay)
    assert render._render_segment(project, [(project.slides[0], seconds)], seconds,
                                  0, out, chapter=chapter, size=(480, 270), fps=15) == out
    assert calls == (['picture', 'chapter', 'overlay'] if wanted else ['picture'])


@pytest.mark.parametrize('fail', [True, False])
def test_overlay_atomic_and_codec(tmp_path, monkeypatch, fail):
    out = tmp_path / 'segment.webm'
    out.write_bytes(b'original')

    def encode(args, **kwargs):
        assert '-an' in args and 'libvpx-vp9' in args
        assert args[args.index('-itsoffset') + 1] == '3.250000'
        assert "eof_action=pass" in args[args.index('-filter_complex') + 1]
        Path(args[-1]).write_bytes(b'replacement')
        if fail:
            raise RuntimeError('encoder failed')

    monkeypatch.setattr(ffutil, 'run', encode)
    if fail:
        with pytest.raises(RuntimeError, match='encoder failed'):
            render._overlay_tail(out, tmp_path / 'chapter.mp4', 3.25)
    else:
        render._overlay_tail(out, tmp_path / 'chapter.mp4', 3.25)
    assert out.read_bytes() == (b'original' if fail else b'replacement')
    assert not out.with_name('segment.chapter.webm').exists()


@pytest.mark.parametrize('name', ['outro_twoup', 'outro_quiet'])
def test_scene_outro_dispatch(tmp_path, monkeypatch, name):
    channel = Channel(id='ctest', name='Example')
    channel.outro.template = 'scene:' + name
    channel.outro.duration = 7

    def ensure(owner, template, ctx, out, **kwargs):
        assert template == 'cards/' + name + '.html'
        assert ctx['vars']['title'] == 'Episode'
        assert ctx['card']['duration'] == kwargs['seconds'] == 7
        assert ctx['plates'] == outro.plate_rects(channel.outro.template, 2)
        assert scenes.lint(scenes.render_html(template, {**ctx, 'duration': 7})) == []
        return tmp_path / 'cached.mp4'

    monkeypatch.setattr(scene_builder, 'render', ensure)
    monkeypatch.setattr(scenes, '_encode', lambda *a, **kw: None)
    assert outro.render_outro(channel, 'Episode', tmp_path / 'preview.webm') == 7

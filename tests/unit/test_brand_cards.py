"""New cards opt into scenes without changing saved channel looks."""
import pytest

from app import render, stage, themes
from app.schema import Channel, Style, new_channel, new_project


@pytest.mark.parametrize('browser', [None, '/usr/bin/chromium'])
def test_new_cards_and_legacy_defaults(monkeypatch, browser):
    monkeypatch.setattr(stage, 'browser', lambda: browser)
    channel = new_channel('New series')
    assert channel.intro.template == ('scene:intro_solo' if browser else 'signal')
    assert channel.outro.template == ('scene:outro_twoup' if browser else 'twoup')
    assert channel.style.chapter_engine == ('scene' if browser else 'pillow')
    assert Channel.from_dict(channel.to_dict()).to_dict() == channel.to_dict()
    assert new_project('Next episode', channel=channel).style.chapter_engine == channel.style.chapter_engine
    legacy = Channel.from_dict({'id': 'cold', 'name': 'Old series', 'future_key': True})
    assert legacy.intro.template == 'columns'
    assert legacy.outro.template == 'twoup'
    assert legacy.style.chapter_engine == 'pillow'
    assert Channel.from_dict(legacy.to_dict()).to_dict() == legacy.to_dict()


@pytest.mark.parametrize('browser', [None, '/usr/bin/chromium'])
def test_available_theme_cards_and_opt_out(monkeypatch, browser):
    monkeypatch.setattr(stage, 'browser', lambda: browser)
    assert themes.apply_to_style(Style(), 'archive')['outro'] == (
        'scene:outro_twoup' if browser else 'twoup')
    assert themes.apply_to_style(Style(), 'terminal')['intro'] == (
        'scene:intro_solo' if browser else 'signal')
    assert themes.apply_to_style(Style(), 'arcade')['intro'] == 'arcade'
    assert themes.apply_to_style(Style(), 'terminal', False) == {}


@pytest.mark.parametrize('engine,browser,scene', [
    ('pillow', '/usr/bin/chromium', False), ('scene', None, False),
    ('scene', '/usr/bin/chromium', True),
])
def test_photographic_chapter_dispatch(project, tmp_path, monkeypatch, engine, browser, scene):
    monkeypatch.setattr(stage, 'browser', lambda: browser)
    project.style.format = 'kenburns'
    project.style.chapter_engine = engine
    chapter = ('Next chapter', '')
    calls = []

    def graph(*args):
        calls.append(('graph', args[5]))
        return [], '[0:v]null[v]', '[v]'

    def tail(*args):
        calls.append(('tail', args[2]))
        return args[1]

    monkeypatch.setattr(render, '_segment_graph', graph)
    monkeypatch.setattr(render, '_chapter_tail', tail)
    monkeypatch.setattr(render.ffutil, 'run', lambda *a, **kw: None)
    out = tmp_path / 'chapter.mp4'
    assert render._render_segment(project, [(project.slides[0], 6)], 6, 0, out,
                                  chapter=chapter, size=(480, 270), fps=15) == out
    assert calls == ([('graph', None), ('tail', chapter)] if scene else [('graph', chapter)])

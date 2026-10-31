"""Scene orchestration tests: no browser, sockets, encoder or LLM."""
import json
import logging

import jinja2
import pytest

from app import cli, scenes, stage


def test_templates_and_context(project):
    ctx = scenes.context_base(project)
    assert ctx['frame'] == project.frame.to_dict()
    assert ctx['palette']['accent'].startswith('#')
    assert all(url.startswith('/fonts/') for url in ctx['fonts'].values())
    for template in ('_test/static.html', '_test/base.html'):
        assert scenes.lint(scenes.render_html(template, ctx)) == []
    ctx['vars']['title'] = '<script>alert(1)</script>'
    html = scenes.render_html('_test/base.html', ctx)
    assert '&lt;script&gt;' in html
    assert 'window.__vars = ' in html
    with pytest.raises(jinja2.UndefinedError):
        scenes.render_html('_test/base.html', {})


@pytest.mark.parametrize('code', [
    'Date.now()', 'Math.random()', 'setTimeout(fn, 1)', 'repeat: -1',
    'tl.play()', 'navigator.gpu', 'fetch("https://example.com/data")',
    '<script src="//example.com/a.js"></script>',
])
def test_lint_banned(code):
    html = scenes.render_html('_test/static.html', {})
    assert scenes.lint(html + code)
    assert not scenes.lint(html + '<!-- ' + code + ' -->')


def test_lint_contract():
    assert 'one composition root required' in scenes.lint('<html></html>')
    html = scenes.render_html('_test/static.html', {}).replace('data-start=', 'removed=')
    assert 'clip missing data-start' in scenes.lint(html)


def test_cache_and_dependencies(tmp_path, monkeypatch, caplog):
    scene = tmp_path / 'templates'
    scene.mkdir()
    (scene / 'segment.html').write_text('{% extends "base.html" %}')
    base = scene / 'base.html'
    base.write_text('<html data-composition-id="test" data-width="1920" '
                    'data-height="1080" data-duration="{{ duration }}">{{ text }}</html>')
    monkeypatch.setattr(scenes, 'env', jinja2.Environment(
        loader=jinja2.FileSystemLoader(scene), autoescape=True,
        undefined=jinja2.StrictUndefined))
    calls = []

    def render(items, directory):
        calls.append(items)
        path = directory / (items[0]['clip'] + '.mp4')
        path.write_bytes(b'fake mp4')
        return {items[0]['clip']: path}

    monkeypatch.setattr(stage, 'render_scene', render)
    ctx = dict(text='first', width=1920, height=1080)
    kwargs = dict(seconds=3, size=(480, 270), fps=30)
    with caplog.at_level(logging.INFO):
        first = scenes.ensure_clip(tmp_path, 'segment.html', ctx, **kwargs)
        assert scenes.ensure_clip(tmp_path, 'segment.html', dict(reversed(list(ctx.items()))), **kwargs) == first
    assert len(calls) == 1
    assert 'scene cache hit' in caplog.text
    assert scenes.ensure_clip(tmp_path, 'segment.html', {**ctx, 'text': 'second'}, **kwargs) != first
    base.write_text(base.read_text() + '<!-- changed shared template -->')
    assert scenes.ensure_clip(tmp_path, 'segment.html', ctx, **kwargs) != first
    monkeypatch.setattr(scenes, '_asset_hash', lambda: 'changed runtime')
    assert scenes.ensure_clip(tmp_path, 'segment.html', ctx, **kwargs) != first
    assert calls[0][0]['scene_root'] == str(tmp_path / 'scenes')


def test_capture_saved(tmp_path, monkeypatch):
    calls = []

    def capture(*args, **kwargs):
        calls.append(args)
        return b'fake png'

    monkeypatch.setattr(stage, 'capture_one', capture)
    for _ in range(2):
        assert scenes.capture(tmp_path, '_test/base.html', scenes.context_base(),
                              t=1.5, size=(480, 270)) == b'fake png'
    assert len(calls) == 1
    assert len(list((tmp_path / 'scenes').glob('*_1.5.png'))) == 1


def test_lint_mounted_files(tmp_path, monkeypatch):
    monkeypatch.setattr(scenes, 'SCENE_DIR', tmp_path)
    component = tmp_path / 'component.html'
    component.write_text('<template><script>Date.now()</script></template>')
    html = ('<html data-composition-id="x" data-width="1" data-height="1" data-duration="1">'
            '<div class="clip" data-start="0" data-duration="1" data-composition-src="component.html"></div></html>')
    assert 'Date.now() is forbidden' in scenes.lint(html)
    component.write_text('<template><!-- Date.now() --></template>')
    assert scenes.lint(html) == []
    assert scenes.lint(html.replace('component.html', '../outside.html'))


def test_preview_cli(tmp_path, monkeypatch):
    ctx = tmp_path / 'ctx.json'
    ctx.write_text(json.dumps({'vars': {'title': 'preview'}}))
    out = tmp_path / 'frame.png'
    monkeypatch.setattr(stage, 'capture_one', lambda *a, **kw: b'fake png')
    assert cli.main(['scene-preview', '_test/base.html', '--ctx', str(ctx), '--out', str(out)]) == 0
    assert out.read_bytes() == b'fake png'



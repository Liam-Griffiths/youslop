"""Sponsor template contract and timing checks, deliberately browser-free."""
import json
from pathlib import Path
import re

import pytest

from app import cli, scenes, sponsors, stage

TEMPLATES = ['house_short', 'short', 'long', 'short_vertical', 'long_vertical']


def context(**values):
    return {**scenes.context_base(), 'duration': 45, **values}


def test_word_beats_and_confidence():
    ctx = context(name='Acme Works', word_offset=.1, take={'words': [
        {'w': 'Acme', 'start': 1.2, 'src': 'tts'},
        {'w': 'Works,', 'start': 1.4, 'src': 'tts'},
        {'w': 'description.', 'start': 5.1, 'src': 'est'}]})
    resolved = sponsors.scene_context(ctx)
    assert resolved['beats']['brand'] == pytest.approx(1.3)
    assert resolved['beats']['link'] == pytest.approx(5.2)
    assert resolved['beat_sources']['brand'] == 'tts'
    assert resolved['beat_sources']['link'] == 'est'
    assert resolved['beat_sources']['learn'] == 'proportional'
    assert sponsors.scene_context(context())['beats']['brand'] == pytest.approx(11.4)
    assert sponsors.scene_context(context(beats={'brand': 2}))['beats']['brand'] == 2


@pytest.mark.parametrize('template', TEMPLATES)
@pytest.mark.parametrize('maximum', [False, True])
def test_contracts_and_maximum_copy(template, maximum):
    ctx = context()
    if maximum:
        ctx['vars'].update(name='N' * 64, url='example.test/' + 'x' * 107,
                           code='C' * 32, learn='D' * 120, made='M' * 64, link='L' * 64)
    html = scenes.render_html(f'sponsor/{template}.html', ctx)
    assert scenes.lint(html) == []
    assert '/static/vendor/gsap/gsap.min.js' in html
    assert "url('/fonts/" in html
    assert 'https://' not in html
    if maximum:
        assert 'N' * 64 in html and 'C' * 32 in html
    if template.endswith('vertical'):
        assert 'data-width="1080" data-height="1920"' in html


@pytest.mark.parametrize('template', TEMPLATES)
@pytest.mark.parametrize('maximum', [False, True])
def test_paper_ink_and_local_urls(template, maximum):
    """Render real fixtures without Chromium, including hostile palette colours."""
    ctx = context()
    if maximum:
        variant = 'long' if template.startswith('long') else 'short'
        fixture = Path('tests/fixtures') / f'sponsor_{variant}_max.json'
        values = json.loads(fixture.read_text())
        ctx['vars'].update(values.pop('vars'))
        ctx.update(values)
    ctx['vars'].update(ink='#FFFFFF', accent='#FFFFFF')
    html = scenes.render_html(f'sponsor/{template}.html', ctx)
    styles = '\n'.join(re.findall(r'<style>(.*?)</style>', html, re.S))
    rules = re.findall(r'([^{}]+)\{([^{}]*)\}',
                       re.sub(r'/\*.*?\*/', '', styles, flags=re.S))
    # Check each paper text rule, including inherited long-read copy colours.
    selectors = ['.made', '.brand', '.learn', '.card-copy']
    if template.startswith('long'):
        selectors += ['.product p', '.lower', '.end', '.end .address']
    for selector in selectors:
        declarations = [body for key, body in rules if key.strip() == selector]
        colours = [colour.upper() for body in declarations
                   for colour in re.findall(r'(?<![-\w])color:\s*(#[\da-fA-F]{6})', body)]
        assert colours and set(colours) == {'#1B1B1F'}, selector
    if not template.startswith('long'):
        assert re.search(r'\.link\s*\{[^}]*color:\s*#FF5A1F', styles)
        assert 'id="arrow"' not in html and 'class="arrow"' not in html
    assert not re.search(r'''https?://|["'(]\s*//''', html, re.I)


@pytest.mark.parametrize('values', [
    {'logo': 'https://example.test/logo.png'},
    {'logo': '//example.test/logo.png'},
    {'logo': '/static/../secret'},
    {'media': [{'src': 'https://example.test/photo.jpg'}] * 2},
    {'name': 'x' * 65}, {'url': 'x' * 121},
    {'accent': 'red; background:url(https://example.test)'},
    {'beats': {'brand': float('nan')}},
])
def test_invalid_vars(values):
    with pytest.raises(ValueError):
        scenes.render_html('sponsor/short.html', context(**values))


def test_local_media_and_escaping():
    ctx = context(name='<Acme>', logo='/static/brand/corkbored-icon.svg', media=[
        {'src': '/scene/{token}/project/library/product.jpg', 'caption': '<Product>'},
        {'src': '/scene/{token}/project/footage/demo.mp4', 'kind': 'video'}])
    html = scenes.render_html('sponsor/long.html', ctx)
    assert '&lt;Acme&gt;' in html and '&lt;Product&gt;' in html
    assert '<video src="/scene/{token}/project/footage/demo.mp4" muted' in html
    assert 'id="product-1"' in html and "'#product-1'" in html
    assert scenes.lint(html) == []


def test_check_cli_without_capture(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail('scene-check must not launch capture')
    monkeypatch.setattr(stage, 'capture_one', forbidden)
    monkeypatch.setattr(stage, 'render_scene', forbidden)
    assert cli.main(['scene-check', 'sponsor/short.html']) == 0
    assert 'lint OK' in capsys.readouterr().out
    ctx = tmp_path / 'ctx.json'
    ctx.write_text(json.dumps({'logo': 'https://example.test/logo.png'}))
    assert cli.main(['scene-check', 'sponsor/short.html', '--ctx', str(ctx)]) == 1
    assert 'local' in capsys.readouterr().err


def test_portrait_capture_geometry(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(stage, 'capture_one', lambda path, w, h, t, size, **kw:
                        seen.append((w, h, size)) or b'fake png')
    scenes.capture(tmp_path, 'sponsor/short_vertical.html', context(), t=2, size=(270, 480))
    assert seen == [(1080, 1920, (270, 480))]


def test_portrait_preview_cli(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(stage, 'capture_one', lambda path, w, h, t, size, **kw:
                        seen.append((w, h, size)) or b'fake png')
    assert cli.main(['scene-preview', 'sponsor/long_vertical.html', '--out',
                     str(tmp_path / 'portrait.png')]) == 0
    assert seen == [(1080, 1920, (270, 480))]


@pytest.mark.parametrize('template', TEMPLATES)
def test_max_fixture_cli(template):
    variant = 'long' if template.startswith('long') else 'short'
    assert cli.main(['scene-check', f'sponsor/{template}.html', '--ctx',
                     f'tests/fixtures/sponsor_{variant}_max.json']) == 0

"""Offline catalog fixtures; no upstream requests or browser launches."""
import json
from pathlib import Path

import httpx
import pytest

from app import catalog, cli, scenes, stage

SHA = 'a' * 40
HTML = '<template><div>Hello</div></template>'


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, 'CATALOG_DIR', tmp_path / 'catalog')
    items = [
        dict(name='lower-third', type='hyperframes:component'),
        dict(name='lower-third-gpu', type='hyperframes:block'),
    ]
    item = dict(**items[0], license='Apache-2.0 AND MIT',
                files=[dict(path='lower-third.html'), dict(path='lib/LICENSE-MIT')],
                tags=[])
    calls = []
    def respond(request):
        calls.append(str(request.url))
        path = request.url.path
        if path.endswith('/commits/main'):
            return httpx.Response(200, json={'sha': SHA})
        if path.endswith('/registry.json'):
            return httpx.Response(200, json={'items': items})
        if path.endswith('/registry-item.json'):
            value = {**item, 'tags': ['webgpu']} if 'gpu/' in path else item
            return httpx.Response(200, json=value)
        if path.endswith('/lower-third.html'):
            return httpx.Response(200, text=HTML)
        if path.endswith('/LICENSE') or path.endswith('/LICENSE-MIT'):
            return httpx.Response(200, text='fixture license')
        return httpx.Response(404)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(
        **kw, transport=httpx.MockTransport(respond)))
    return item, calls


def test_fetch_noop_modified(upstream):
    item, calls = upstream
    dest = catalog.fetch('lower-third')
    source = catalog.installed()[0]
    assert source['commit'] == SHA
    assert source['license'] == item['license']
    assert source['lint'] == []
    assert (dest / 'LICENSE.txt').read_text() == 'fixture license'
    assert (dest / 'lib/LICENSE-MIT').is_file()
    assert all('/' + SHA + '/' in url for url in calls[1:])
    count = len(calls)
    assert catalog.fetch('lower-third') == dest
    assert len(calls) == count
    (dest / 'lower-third.html').write_text('local edit')
    with pytest.raises(ValueError, match='modified local'):
        catalog.fetch('lower-third')
    assert (dest / 'lower-third.html').read_text() == 'local edit'


def test_search_cache_cli(upstream, capsys):
    assert cli.main(['catalog', 'search', 'lower third']) == 0
    output = capsys.readouterr()
    assert 'WebGPU items excluded' in output.err
    assert [i['name'] for i in json.loads(output.out)] == ['lower-third']
    count = len(upstream[1])
    assert len(catalog.search('lower third')) == 1
    assert len(upstream[1]) == count
    assert cli.main(['catalog', 'fetch', 'lower-third']) == 0
    assert cli.main(['catalog', 'list']) == 0


@pytest.mark.parametrize('name', ['../escape', '/absolute', '_index', 'a/b'])
def test_invalid_names(name, upstream):
    with pytest.raises(ValueError):
        catalog.fetch(name)
    assert not upstream[1]


def test_bad_file_path(upstream):
    upstream[0]['files'] = [dict(path='../escape')]
    with pytest.raises(ValueError, match='unsafe'):
        catalog.fetch('lower-third')
    assert not (catalog.CATALOG_DIR / 'lower-third').exists()


def test_mount_lint_and_cache(upstream):
    dest = catalog.fetch('lower-third')
    html = ('<div data-composition-id="test" data-width="1920" data-height="1080" '
            'data-duration="3"><div class="clip" data-start="0" data-duration="3" '
            'data-composition-src="/catalog/lower-third/lower-third.html"></div></div>')
    assert scenes.lint(html) == []
    first = scenes.lint_component(HTML + 'setTimeout(fn, 1)', dest)
    assert 'setTimeout() is forbidden' in first
    (dest / 'lower-third.html').write_text(HTML + 'setTimeout(fn, 1)')
    assert 'setTimeout() is forbidden' in scenes.lint(html)
    handler = object.__new__(stage._handler(stage._Run({}, None)))
    assert handler.translate_path('/catalog/lower-third/lower-third.html') == str(dest / 'lower-third.html')
    for url in ('/catalog/../escape', '/catalog/%2e%2e/escape', '/catalog/_index/registry.json'):
        assert handler.translate_path(url) == '/nonexistent'


def test_fetch_records_lint(upstream, monkeypatch):
    monkeypatch.setattr(scenes, 'lint_component', lambda *a: ['setTimeout() is forbidden'])
    dest = catalog.fetch('lower-third')
    assert 'setTimeout() is forbidden' in (dest / 'SOURCE.json').read_text()


def test_scene_preview_mount(upstream, tmp_path, monkeypatch):
    import jinja2

    catalog.fetch('lower-third')
    template = tmp_path / 'mounted.html'
    template.write_text(
        '<html data-composition-id="test" data-width="1920" data-height="1080" '
        'data-duration="3"><div class="clip" data-start="0" data-duration="3" '
        'data-composition-src="/catalog/lower-third/lower-third.html"></div></html>')
    monkeypatch.setattr(scenes, 'env', jinja2.Environment(
        loader=jinja2.FileSystemLoader(tmp_path)))
    captured = []
    def capture(path, width, height, t, size, **kwargs):
        assert scenes.lint(path.read_text()) == []
        captured.append(size)
        return b'fixture png'
    monkeypatch.setattr(stage, 'capture_one', capture)
    out = tmp_path / 'preview.png'
    assert cli.main(['scene-preview', 'mounted.html', '--out', str(out)]) == 0
    assert out.read_bytes() == b'fixture png'
    assert captured == [(480, 270)]


def test_recorded_lint_refuses_mount(upstream, monkeypatch):
    monkeypatch.setattr(scenes, 'lint_component', lambda *a: ['helper.js: setTimeout() is forbidden'])
    catalog.fetch('lower-third')
    html = ('<div data-composition-id="test" data-width="1" data-height="1" '
            'data-duration="1" data-composition-src="/catalog/lower-third/lower-third.html"></div>')
    assert any('Catalog lint:' in error and 'helper.js' in error
               for error in scenes.lint(html))


def test_missing_download_keeps_install_absent(upstream):
    upstream[0]['files'].append(dict(path='missing.js'))
    with pytest.raises(httpx.HTTPStatusError):
        catalog.fetch('lower-third')
    assert not (catalog.CATALOG_DIR / 'lower-third').exists()
    assert not list(catalog.CATALOG_DIR.glob('_fetch-*'))

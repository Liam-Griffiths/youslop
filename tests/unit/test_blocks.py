"""Block discovery, validation and scene dispatch without Chromium or LLMs."""
import json
import re

import pytest

from app import blocks, cli, scenes, stage


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'blocks')
    monkeypatch.setattr(blocks, 'PACKS_DIR', tmp_path / 'packs')
    return tmp_path


def add_block(root, **updates):
    root.mkdir(parents=True)
    meta = json.loads((blocks.BUILTIN_DIR / 'chapter/block.json').read_text())
    meta.update(id=root.name, **updates)
    (root / 'block.json').write_text(json.dumps(meta))
    (root / 'block.html').write_text('{% extends "_base.html" %}{% block body %}{{ vars.title }}{% endblock %}')
    return meta


def test_discovery_and_cli(library, capsys):
    add_block(blocks.USER_DIR / 'mine')
    pack = blocks.PACKS_DIR / 'demo-pack'
    add_block(pack / 'blocks/mine')
    (pack / 'pack.json').write_text('{"id":"demo-pack"}')
    found = blocks.discover()
    count = len(list(blocks.BUILTIN_DIR.glob('*/block.json'))) + 2
    assert len(found) == count and {'user/mine', 'demo-pack/mine'} <= found.keys()
    assert cli.main(['block', 'list']) == 0
    assert len(json.loads(capsys.readouterr().out)) == count
    assert cli.main(['block', 'show', 'chapter']) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'chapter'


@pytest.mark.parametrize('ref', ['_test', 'intro_solo', 'intro_dossier',
                                    'intro_folio', 'intro_portrait', 'outro_twoup',
                                    'outro_quiet', 'sponsor_house_read'])
def test_existing_html_identical(library, ref):
    template, ctx = blocks.prepare(ref)
    original = 'sponsor/house_short.html' if ref.startswith('sponsor') else f'cards/{ref}.html'
    html = scenes.render_html(template, ctx)
    assert scenes.lint(html, asset_root=ctx['block_assets_root']) == []
    without_base = lambda h: re.sub(r'<base href="[^"]*">', '', h).strip()
    assert without_base(html) == without_base(scenes.render_html(original, ctx))


@pytest.mark.parametrize('values,match', [({'title':'x'*241}, 'maxLength'),
                                         ({'title':42}, 'expected string'),
                                         ({'unknown':1}, 'unknown block variables')])
def test_refused_before_render(library, monkeypatch, values, match):
    monkeypatch.setattr(scenes, 'ensure_clip', lambda *a, **k: pytest.fail('render invoked'))
    with pytest.raises(ValueError, match=match):
        blocks.render('chapter', values)


@pytest.mark.parametrize('spec,bad', [
    (dict(type='number', default=1, min=0, max=2), True),
    (dict(type='number', default=1), float('nan')),
    (dict(type='colour', default='var(--accent)'), 'red'),
    (dict(type='image', default=''), 'https://remote/image.png'),
    (dict(type='clip', default=''), '/scene/%2e%2e/private'),
    (dict(type='table', default=[{'n':1}]), [[1,2]]),
    (dict(type='enum', default='a', choices=['a','b']), 'c'),
])
def test_variable_types(spec, bad):
    meta = {'variables': {'value':spec}}
    assert blocks.validate_vars(meta, {})['value'] == spec['default']
    with pytest.raises(ValueError):
        blocks.validate_vars(meta, {'value':bad})


def test_variants_duration_cache_and_assets(library, monkeypatch):
    root = blocks.USER_DIR / 'custom'
    add_block(root, aspects={'9:16':'block.html', '1:1':'block.html'},
              duration=dict(mode='from_words', min=1, max=10, variable='title', words_per_minute=60))
    (root / 'asset.txt').write_text('first')
    calls = []
    def render(items, directory):
        calls.extend(items)
        item = items[0]
        out = directory / (item['clip'] + '.mp4')
        out.write_bytes(b'fake')
        return {item['clip']:out}
    monkeypatch.setattr(stage, 'render_scene', render)
    kw = dict(aspect='9:16', project=library / 'cache')
    first = blocks.render('user/custom', {'title':'two words'}, **kw)
    assert blocks.render('user/custom', {'title':'two words'}, **kw) == first
    assert len(calls) == 1 and calls[0]['assets_root'] == str(root)
    assert (calls[0]['W'], calls[0]['H'], calls[0]['frames']) == (1080,1920,60)
    (root / 'asset.txt').write_text('changed')
    assert blocks.render('user/custom', {'title':'two words'}, **kw) != first
    for kwargs in [dict(aspect='16:9'), dict(aspect='1:1', seconds=11)]:
        with pytest.raises(ValueError):
            blocks.prepare('user/custom', **kwargs)
    assert blocks.prepare('user/custom', aspect='1:1')[1]['height'] == 1080


def test_bad_manifest_and_escape(library):
    root = blocks.USER_DIR / 'bad'
    add_block(root, version=3)
    with pytest.raises(ValueError, match='version'):
        blocks.discover()
    add = json.loads((root / 'block.json').read_text())
    add['version'] = '1.0.0'
    add['aspects']['16:9'] = '../private.html'
    (root / 'block.json').write_text(json.dumps(add))
    with pytest.raises(ValueError, match='invalid format'):
        blocks.discover()


def test_preview_and_lint(library, monkeypatch):
    monkeypatch.setattr(stage, 'render_scene', lambda *a, **k: pytest.fail('browser invoked'))
    root = blocks.USER_DIR / 'custom'
    add_block(root, aspects={'9:16':'block.html'})
    (root / 'block.html').write_text('{% extends "_base.html" %}{% block body %}<script>Date.now()</script>{% endblock %}')
    with pytest.raises(ValueError, match='Date.now'):
        blocks.render('user/custom', aspect='9:16', project=library / 'cache')
    (root / 'block.html').write_text('{% extends "_base.html" %}')
    def capture(*args, **kwargs):
        assert args[1:3] == (1080,1920) and args[4] == (270,480)
        assert kwargs['assets_root'] == str(root)
        return b'fake png'
    monkeypatch.setattr(stage, 'capture_one', capture)
    out = library / 'preview.png'
    assert cli.main(['block','preview','user/custom','--aspect','9:16','--t','1.5','--out',str(out)]) == 0
    assert out.read_bytes() == b'fake png'


def test_fixed_duration_beats_and_symlink(library):
    root = blocks.USER_DIR / 'timed'
    add_block(root, duration=dict(mode='fixed', seconds=5), beats={'hit':'land here'})
    context = scenes.context_base()
    context['take'] = {'words':[{'w':'Land', 'start':1.2, 'src':'est'},
                                {'w':'here', 'start':1.6, 'src':'est'}]}
    _, ctx = blocks.prepare('user/timed', context=context)
    assert ctx['beats'] == {'hit':1.2} and ctx['beat_sources'] == {'hit':'est'}
    assert ctx['safe_areas'] == {'title':.1, 'action':.05}
    with pytest.raises(ValueError, match='duration'):
        blocks.prepare('user/timed', seconds=6)
    (library / 'private.html').write_text('<template/>')
    (root / 'escape.html').symlink_to(library / 'private.html')
    with pytest.raises(ValueError, match='outside folder'):
        blocks.prepare('user/timed')


@pytest.mark.parametrize('resource', ['<style>@font-face{src:url(https://remote/font.ttf)}</style>',
                                     '<link href="//remote/style.css" rel="stylesheet">'])
def test_remote_resources_refused(library, monkeypatch, resource):
    root = blocks.USER_DIR / 'remote'
    add_block(root)
    (root / 'block.html').write_text('{% extends "_base.html" %}{% block head %}' + resource + '{% endblock %}')
    monkeypatch.setattr(stage, 'render_scene', lambda *a, **k: pytest.fail('browser invoked'))
    with pytest.raises(ValueError, match='remote block resource'):
        blocks.render('user/remote', project=library / 'cache')


def test_range_default_is_a_watchable_length():
    from app import blocks
    _, ctx = blocks.prepare('sponsor_house_read')
    assert ctx['duration'] == 8
    _, ctx = blocks.prepare('chapter')
    assert ctx['duration'] == 5.0


def test_authoring_scaffold_and_static_checks(library, monkeypatch, capsys):
    from app import block_authoring as kit
    monkeypatch.setattr(stage, '_run_cdp', lambda *a, **k: pytest.fail('browser invoked'))
    assert cli.main(['block', 'new', 'my-title']) == 0
    root = blocks.USER_DIR / 'my-title'
    assert kit.lint('user/my-title') == []
    assert cli.main(['block', 'check', 'user/my-title', '--static-only']) == 0
    assert 'browser checks skipped' in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        kit.new('my-title')
    with pytest.raises(ValueError):
        kit.new('../escape')
    assert kit.samples(blocks.discover()['user/my-title']['meta']) == {'title':'W'*80}
    (root / 'block.html').write_text(kit.TEMPLATE.replace('{% block body %}',
        '{% block body %}<script>Date.now()</script>'))
    assert any('Date.now' in error for error in kit.lint('user/my-title'))


def test_authoring_browser_measurements(library, monkeypatch):
    from app import block_authoring as kit
    kit.new('probe')
    visited = []
    class CDP:
        def send(self, method, params, session):
            if method == 'Page.captureScreenshot':
                import base64
                import io
                from PIL import Image
                out = io.BytesIO()
                Image.new('RGB', (2,2)).save(out, format='PNG')
                return {'data':base64.b64encode(out.getvalue()).decode()}
            expression = params['expression']
            return {'result':{'value':['title: text overflow'] if 'querySelectorAll' in expression else None}}
    def run(job, progress, **kwargs):
        item = job['items'][0]
        visited.append((item['W'], item['H']))
        kwargs['scene_probe'](CDP(), 'session', item, item['t'])
    monkeypatch.setattr(stage, '_run_cdp', run)
    errors = kit.check('user/probe')
    assert len(errors) == 3 and all('title: text overflow' in e for e in errors)
    assert visited == [(1920,1080), (1080,1920), (1080,1080)]


def test_authoring_preview_bundle(library, monkeypatch):
    from app import block_authoring as kit
    import io
    from PIL import Image
    kit.new('preview')
    out = io.BytesIO()
    Image.new('RGB', (480,270)).save(out, format='PNG')
    times = []
    def capture(*a, **kw):
        assert kw['size'] == (480,270)
        times.append(kw['t'])
        return out.getvalue()
    def clip(root, template, ctx, **kw):
        assert kw['size'] == (480,270) and kw['seconds'] == 3
        path = root / 'mock.mp4'
        path.write_bytes(b'mock mp4')
        return path
    monkeypatch.setattr(scenes, 'capture', capture)
    monkeypatch.setattr(scenes, 'ensure_clip', clip)
    target = library / 'preview-output'
    assert cli.main(['block','preview','user/preview','--out',str(target)]) == 0
    assert {p.name for p in target.iterdir()} == {'preview.png','sheet.png','preview.mp4'}
    assert times == [1.5, 0, .5, 1, 1.5, 2, 2.5]

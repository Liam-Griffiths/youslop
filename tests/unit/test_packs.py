"""Disposable pack fixtures; no real data, browser, network or LLM."""
import json
import shutil
import wave

import pytest

from app import blocks, block_authoring, packs, scenes, themes, render, models3d, stage
from app.schema import Style


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setattr(packs, 'PACKS_DIR', tmp_path / 'packs')
    monkeypatch.setattr(packs, 'BUILTIN_DIR', tmp_path / 'builtin-packs')
    root = packs.PACKS_DIR / 'demo-pack'
    root.mkdir(parents=True)
    (root / 'pack.json').write_text(json.dumps(dict(id='demo-pack', name='Demo pack',
        version='1.0.0', author='Fixture', licence='CC0')))
    (root / 'themes').mkdir()
    (root / 'themes/gold.json').write_text(json.dumps(themes.THEMES[0]))
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'blocks')
    authored = block_authoring.new('title')
    shutil.copytree(authored, root / 'blocks/title')
    meta = json.loads((root / 'blocks/title/block.json').read_text())
    meta['kind'] = 'intro'
    (root / 'blocks/title/block.json').write_text(json.dumps(meta))
    (root / 'music').mkdir()
    with wave.open(str(root / 'music/bed.wav'), 'wb') as track:
        track.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        track.writeframes(b'\0' * 32000)
    (root / 'music/credits.json').write_text(json.dumps({'bed.wav': dict(
        title='Quiet', artist='Fixture artist', licence='CC0', url='https://example.test/bed')}))
    (root / 'fonts').mkdir()
    (root / 'fonts/Demo.ttf').write_bytes(b'fixture font, never loaded by a browser')
    return root


def test_scan_refs_and_pick_unpick(demo, project, caplog, monkeypatch):
    from app import main
    pack, = packs.scan()
    assert pack.problems == [] and pack.item_problems == {}
    assert packs.scan()[0] is pack
    assert packs.resolve('demo-pack/gold')['accent'] == themes.THEMES[0]['accent']
    assert packs.resolve('demo-pack/bed.wav') == demo / 'music/bed.wav'
    assert packs.resolve('pack/demo-pack/title') == demo / 'blocks/title'
    style = Style()
    themes.apply_to_style(style, 'demo-pack/gold', take_templates=False)
    assert themes.palette(style).key == 'demo-pack/gold'
    assert main.list_themes()[-1]['pack'] == 'Demo pack'
    assert main.intro_templates()[-1]['key'] == 'scene:pack/demo-pack/title'
    assert main.music_list()[-1]['label'] == 'Quiet · Demo pack'
    project.music = 'demo-pack/bed.wav'
    assert render.pick_music(project) == demo / 'music/bed.wav'
    assert 'Music: Quiet by Fixture artist (CC0) https://example.test/bed' in render.credits_text(project)
    template, ctx = blocks.prepare('pack/demo-pack/title')
    assert 'user_fit.js' in scenes.render_html(template, ctx)
    assert block_authoring.check('pack/demo-pack/title', static_only=True) == []
    from app import scene_builder, learning
    from app.schema import Channel
    assert learning.validate_look('theme:demo-pack/gold') == 'theme:demo-pack/gold'
    calls = []
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw: calls.append((a, kw)))
    channel = Channel(id='fixture', name='Fixture channel', style=style)
    assert scenes.render_card('intro', 'pack/demo-pack/title', channel, 'Video title', demo.parent / 'preview.mp4') == 3
    assert calls[0][0][2]['vars']['title'] == 'Video title'
    assert calls[0][0][2]['palette']['key'] == 'demo-pack/gold'
    assert ctx['fonts']['pack:demo-pack/Demo.ttf'] == '/fonts/packs/demo-pack/Demo.ttf'
    first = ctx['block_version']
    manifest = json.loads((demo / 'pack.json').read_text())
    (demo / 'pack.json').write_text(json.dumps({**manifest, 'version': '1.0.1'}))
    assert blocks.prepare('pack/demo-pack/title')[1]['block_version'] != first
    # Simulate uninstall by moving the whole disposable folder, including its fixture audio.
    demo.rename(demo.parent.parent / 'removed')
    assert themes.palette(style).key == themes.DEFAULT and 'Missing theme' in caplog.text
    assert render.pick_music(project) is None
    assert packs.resolve('demo-pack/gold') is None
    assert main.rescan_packs() == []


@pytest.mark.parametrize('bad', ['{', '[]', '{"id":"wrong"}'])
def test_bad_manifest(demo, bad):
    (demo / 'pack.json').write_text(bad)
    assert packs.scan()[0].problems
    assert 'pack/demo-pack/title' not in blocks.discover()


@pytest.mark.parametrize('bad', ['plugin.py', 'plugin.js', 'link', 'executable'])
def test_forbidden_files(demo, bad):
    path = demo / bad
    if bad == 'link':
        path.symlink_to(demo / 'themes/gold.json')
    else:
        path.write_text('not allowed')
        if bad == 'executable':
            path.chmod(0o755)
    assert packs.scan()[0].problems and packs.resolve('demo-pack/gold') is None


def test_bad_block_isolated_and_assets_confined(demo):
    source = demo / 'blocks/title/block.html'
    source.write_text(block_authoring.TEMPLATE.replace('{% block body %}',
        '{% block body %}<script>Date.now()</script>'))
    pack, = packs.scan()
    assert not pack.problems and pack.item_problems['pack/demo-pack/title']
    assert packs.resolve('demo-pack/gold') and not pack.blocks()
    source.write_text(block_authoring.TEMPLATE)
    source.write_text(block_authoring.TEMPLATE.replace('{% block head %}',
        '''{% block head %}<style>@font-face{font-family:Demo;src:url('{{ fonts["pack:demo-pack/Demo.ttf"] }}')}</style>'''))
    assert packs.scan()[0].blocks()
    handler_type = stage._handler(stage._Run({}, None))
    handler = handler_type.__new__(handler_type)
    assert handler.translate_path('/fonts/packs/demo-pack/Demo.ttf') == str(demo / 'fonts/Demo.ttf')
    for url in ['/fonts/packs/demo-pack/../pack.json', '/fonts/packs/demo-pack/%2e%2e/pack.json']:
        assert handler.translate_path(url) == '/nonexistent'


def test_models_read_only_and_copy(demo, tmp_path, monkeypatch):
    root = demo / 'models/model'
    root.mkdir(parents=True)
    (root / 'model.glb').write_bytes(b'fixture, never rendered')
    (root / 'manifest.json').write_text(json.dumps(dict(id='model', title='Model', confirmed=True)))
    monkeypatch.setattr(models3d, 'MODELS_DIR', tmp_path / 'library')
    assert models3d.all_models()[0]['read_only']
    from app import main
    from starlette.routing import Match
    route = next(r for r in main.app.routes if r.matches(dict(type='http', method='GET',
        path='/api/models/demo-pack/model/model.glb'))[0] == Match.FULL)
    assert route.endpoint is main.model_file
    assert models3d.glb_path('demo-pack/model') == root / 'model.glb'
    for fn in [lambda: models3d.update('demo-pack/model', {'title':'oops'}),
               lambda: models3d.delete('demo-pack/model'),
               lambda: models3d.set_thumb('demo-pack/model', b'fake')]:
        with pytest.raises(models3d.ModelError, match='read-only'):
            fn()
    copied = models3d.copy_to_library('demo-pack/model')
    assert '/' not in copied['id'] and 'read_only' not in copied
    assert models3d.get(copied['id'])['title'] == 'Model · Demo pack'
    assert json.loads((root / 'manifest.json').read_text())['title'] == 'Model'

"""Pack authoring exercises real validation/install and mocks only browser capture."""
import json
import shutil
import zipfile

import pytest

from app import block_authoring, blocks, cli, packs, paths, scenes, themes


@pytest.fixture
def draft(tmp_path, monkeypatch):
    monkeypatch.setattr(packs, 'PACKS_DIR', tmp_path / 'installed')
    monkeypatch.setattr(packs, 'BUILTIN_DIR', tmp_path / 'builtins')
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'authored')
    root = tmp_path / 'demo-pack'
    root.mkdir()
    (root / 'pack.json').write_text(json.dumps(dict(id='demo-pack', name='Demo',
        author='Fixture', version='1.0.0', licence='GPL-3.0-or-later')))
    (root / 'themes').mkdir()
    (root / 'themes/demo.json').write_text(json.dumps(themes.THEMES[0]))
    shutil.copytree(block_authoring.new('title'), root / 'blocks/title')
    return root


def test_check_and_build_install(draft, monkeypatch, capsys):
    calls = []
    def capture(root, template, ctx, **kwargs):
        # Prove the uninstalled draft is renderable via the existing loader.
        assert 'A new perspective' in scenes.render_html(template, ctx)
        calls.append(kwargs['size'])
        return b'preview fixture'
    monkeypatch.setattr(scenes, 'capture', capture)
    assert cli.main(['pack', 'check', str(draft)]) == 0
    assert calls == [(480, 270), (270, 480), (270, 270)]
    assert len(list((draft / '.check').glob('*.png'))) == 3
    (draft / '.hidden').write_text('excluded')
    assert cli.main(['pack', 'build', str(draft)]) == 0
    archive = draft.parent / 'demo-pack-1.0.0.corkboredpack'
    with zipfile.ZipFile(archive) as zf:
        assert all(not any(part.startswith('.') for part in p.split('/')) for p in zf.namelist())
        assert 'demo-pack/blocks/title/block.html' in zf.namelist()
    result = packs.install(archive)
    assert result['items']['blocks'][0]['ref'] == 'pack/demo-pack/title'
    assert result['items']['themes'][0]['ref'] == 'demo-pack/demo'
    assert packs.STAGED.get() == ()
    assert cli.main(['pack', 'build', str(draft), '--static-only']) == 1
    assert 'File exists' in capsys.readouterr().err


@pytest.mark.parametrize('bad', ['plugin.py', 'blocks/title/block.html'])
def test_invalid_pack_fails(draft, bad, capsys):
    (draft / bad).write_text('<script>Date.now()</script>')
    assert cli.main(['pack', 'check', str(draft)]) == 1
    assert ('forbidden code' if bad.endswith('.py') else 'pack/demo-pack/title') in capsys.readouterr().err
    assert not (draft / '.check').exists()


def test_browser_failure_and_static_only(draft, monkeypatch, capsys):
    from app.stage import StageError
    def fail(*args, **kwargs):
        raise StageError('browser unavailable')
    monkeypatch.setattr(scenes, 'capture', fail)
    assert cli.main(['pack', 'check', str(draft)]) == 1
    assert 'preview failed: browser unavailable' in capsys.readouterr().err
    assert cli.main(['pack', 'check', str(draft), '--static-only']) == 0
    assert packs.STAGED.get() == ()


def test_starter_builtin_and_protected(tmp_path, monkeypatch):
    monkeypatch.setattr(packs, 'PACKS_DIR', tmp_path / 'packs')
    monkeypatch.setattr(packs, 'BUILTIN_DIR', paths.resource_root() / 'packs')
    pack, = packs.scan()
    assert pack.id == 'starter' and not pack.problems and not pack.item_problems
    assert len(pack.themes()) == 1 and len(pack.blocks()) == 3 and not pack.music()
    assert packs.summary(pack)['builtin']
    for item in pack.blocks():
        template, ctx = blocks.prepare(item['ref'])
        assert 'data-layer="title"' in scenes.render_html(template, ctx)
    with pytest.raises(packs.PackError, match='Built-in'):
        packs.remove('starter')
    # Even a newer archive cannot replace or shadow a built-in pack.
    archive = tmp_path / 'starter.corkboredpack'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('starter/pack.json', '{}')
    with pytest.raises(packs.PackError, match='Built-in'):
        packs.install(archive, replace=True)
    shadow = packs.PACKS_DIR / 'starter'
    shadow.mkdir(parents=True)
    (shadow / 'pack.json').write_text('{}')
    assert packs.scan()[0].path == pack.path


def test_local_draft_fonts_in_preview_thread(draft):
    from concurrent.futures import ThreadPoolExecutor
    from app import stage
    fonts = draft / 'fonts'
    fonts.mkdir()
    (fonts / 'Demo.ttf').write_bytes(b'fixture font')
    token = packs.STAGED.set((draft,))
    try:
        handler_type = stage._handler(stage._Run({}, None))
    finally:
        packs.STAGED.reset(token)
    handler = handler_type.__new__(handler_type)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(handler.translate_path, '/fonts/packs/demo-pack/Demo.ttf').result()
    assert result == str(fonts / 'Demo.ttf')
    assert handler.translate_path('/fonts/packs/demo-pack/../pack.json') == '/nonexistent'

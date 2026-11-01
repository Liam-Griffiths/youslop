"""Pack installation uses disposable archives and storage; no media rendering."""
import io
import json
import stat
import zipfile

import pytest
from fastapi import HTTPException, UploadFile

from app import config, main, packs, themes


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(packs, 'PACKS_DIR', tmp_path / 'packs')
    monkeypatch.setattr(packs, 'BUILTIN_DIR', tmp_path / 'builtin-packs')
    monkeypatch.setattr(main, 'CACHE_DIR', tmp_path / '.cache')
    main.CACHE_DIR.mkdir()
    monkeypatch.setattr(config, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(config, 'PROJECTS_DIR', tmp_path / 'projects')


def bundle(version='1.0.0', extra=(), theme=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as zf:
        zf.writestr('demo-pack/pack.json', json.dumps(dict(id='demo-pack', name='Demo',
            version=version, author='Fixture', licence='CC0')))
        zf.writestr('demo-pack/themes/gold.json', json.dumps(theme if theme is not None else themes.THEMES[0]))
        zf.writestr('demo-pack/preview.jpg', b'preview fixture')
        for name, content in extra:
            zf.writestr(name, content)
    out.seek(0)
    return out


def install_api(src, replace=False):
    return main.install_pack(UploadFile(src, filename='demo.corkboredpack'), replace=replace)


def test_install_upgrade_and_remove():
    installed = install_api(bundle())
    assert installed['author'] == 'Fixture' and installed['licence'] == 'CC0'
    assert installed['items']['themes'][0]['ref'] == 'demo-pack/gold'
    assert main.pack_preview('demo-pack').path == packs.PACKS_DIR / 'demo-pack/preview.jpg'
    assert main.list_packs()['packs'][0]['name'] == 'Demo'
    assert main.list_themes()[-1]['key'] == 'demo-pack/gold'
    with pytest.raises(HTTPException) as same:
        install_api(bundle())
    assert same.value.status_code == 400
    with pytest.raises(HTTPException) as newer:
        install_api(bundle('1.1.0'))
    assert newer.value.status_code == 409 and newer.value.detail['replace_required']
    assert not (packs.PACKS_DIR / '.old').exists()
    install_api(bundle('1.1.0'), replace=True)
    old = packs.PACKS_DIR / '.old/demo-pack-1.0.0'
    assert (old / 'pack.json').is_file()
    with pytest.raises(packs.PackError, match='same or older'):
        packs.install(bundle(), replace=True)
    assert len(packs.scan()) == 1
    removed = main.remove_pack('demo-pack')
    assert (packs.PACKS_DIR / '.old/demo-pack-1.1.0/pack.json').is_file()
    assert removed['id'] == 'demo-pack' and packs.scan() == []
    assert packs.missing_items({'music': 'demo-pack/track.wav', 'narration': 'demo-pack/prose'}) == ['demo-pack/track.wav']
    assert (old / 'pack.json').is_file()


@pytest.mark.parametrize('name', ['/absolute', '../outside', 'demo-pack/../outside',
    'demo-pack/sub/../../outside', 'C:/outside', 'demo-pack\\outside'])
def test_unsafe_paths(name, tmp_path):
    with pytest.raises(packs.PackError):
        packs.install(bundle(extra=[(name, b'bad')]))
    assert not packs.PACKS_DIR.exists() and not (tmp_path / 'outside').exists()
    assert list((tmp_path / '.cache').iterdir()) == []


@pytest.mark.parametrize('mode', [stat.S_IFLNK | 0o777, stat.S_IFCHR | 0o600,
    stat.S_IFBLK | 0o600, stat.S_IFIFO | 0o600, stat.S_IFREG | 0o755])
def test_links_devices_executables(mode):
    member = zipfile.ZipInfo('demo-pack/unsafe')
    member.create_system = 3
    member.external_attr = mode << 16
    with pytest.raises(packs.PackError):
        packs.install(bundle(extra=[(member, b'bad')]))
    assert not packs.PACKS_DIR.exists()


@pytest.mark.parametrize('limit,value', [('MAX_BYTES', 10), ('MAX_FILES', 1)])
def test_limits(limit, value, monkeypatch):
    monkeypatch.setattr(packs, limit, value)
    with pytest.raises(packs.PackError, match='limit'):
        packs.install(bundle())
    assert not packs.PACKS_DIR.exists()


@pytest.mark.parametrize('extra,theme', [([('demo-pack/plugin.py', b'bad')], None),
    ([], {'label': 'broken'}), ([('other/pack.json', b'{}')], None)])
def test_validation_before_replace(extra, theme):
    packs.install(bundle())
    with pytest.raises(packs.PackError):
        packs.install(bundle('2.0.0', extra, theme), replace=True)
    assert packs.scan()[0].version == '1.0.0'
    assert not (packs.PACKS_DIR / '.old').exists()


def test_uses_includes_nested_block_refs():
    packs.install(bundle())
    for root, name, data in [(config.CHANNELS_DIR, 'channel', dict(name='My channel',
        intro={'template': 'scene:pack/demo-pack/title'})),
        (config.PROJECTS_DIR, 'project', dict(title='My video', cast=[{'model': 'demo-pack/model'}]))]:
        folder = root / 'fixture'
        folder.mkdir(parents=True)
        (folder / f'{name}.json').write_text(json.dumps(data))
    uses = main.pack_uses('demo-pack')
    assert uses == dict(channels=[dict(id='fixture', name='My channel')],
                        projects=[dict(id='fixture', name='My video')])
    assert packs.references({'style': {'theme': 'demo-pack/gold'}}, 'demo-pack')
    assert not packs.references('other-pack/gold', 'demo-pack')
    for pid in ['../demo-pack', '.old', '/tmp/demo-pack']:
        with pytest.raises(packs.PackError):
            packs.remove(pid)


def test_bad_manifest_and_zip():
    for src in [io.BytesIO(b'not a zip'), bundle(extra=[('demo-pack/bad.js', b'code')])]:
        with pytest.raises(packs.PackError):
            packs.install(src)
    assert packs.scan() == []


def test_removed_item_check(project, monkeypatch):
    from app import check
    project.music = 'demo-pack/track.wav'
    monkeypatch.setattr(check, '_scene_text', lambda *a: None)
    result = check.run(project)
    warnings = [f for f in result['findings'] if f['code'] == 'missing_pack_item']
    assert len(warnings) == 1 and 'demo-pack/track.wav' in warnings[0]['msg']
    assert packs.missing_items({'template': 'sponsor/house_short.html'}) == []

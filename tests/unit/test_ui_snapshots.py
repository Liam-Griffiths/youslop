"""UI harness contracts, deliberately independent of Chromium and sockets."""
from pathlib import Path

import pytest

from scripts.ui_snapshots import FORMATS, PROJECT_STAGES, console_error, output_path, routes, seed


def test_routes_match_current_tabs_and_families():
    paths = routes()
    assert len(paths) == len(set(paths)) == 75
    assert paths[:5] == ['#/', '#/setup', '#/library', '#/settings', '#/guide']
    assert '#/footage/ssnapshot' in paths
    assert '#/c/csnapshot' in paths and '#/c/csnapshot/setup' in paths
    for fmt in FORMATS:
        expected = set(PROJECT_STAGES) | {'media', 'record', 'thumb', 'render',
            'visuals/media', 'publish/render', 'publish/thumb'}
        if fmt == 'stage':
            expected |= {'cast', 'stage', 'visuals/cast', 'visuals/stage'}
        assert {p.removeprefix(f'#/p/psnap{fmt}/') for p in paths
                if p.startswith(f'#/p/psnap{fmt}/')} == expected


def test_output_paths_are_unique_and_contained(tmp_path):
    paths = [output_path(tmp_path, route) for route in routes()]
    assert len(set(paths)) == 75
    assert paths[0] == tmp_path / 'home.png'
    assert output_path(tmp_path, '#/p/psnapstage/stage').name == 'p--psnapstage--stage.png'
    assert all(p.parent == tmp_path and p.suffix == '.png' for p in paths)


@pytest.mark.parametrize('route', ['../../escape', '#/../escape', '#//etc', '#/a-b', '#/a%2Fb', '#/a\\b'])
def test_reject_unsafe_output_routes(tmp_path, route):
    with pytest.raises(ValueError):
        output_path(tmp_path, route)


@pytest.mark.parametrize('event, expected', [
    ({'method': 'Runtime.consoleAPICalled', 'params': {'type': 'error', 'args': [
        {'value': 'probe'}, {'description': 'Error: broken'}, {'value': 42}]}},
     'console.error: probe Error: broken 42'),
    ({'method': 'Runtime.consoleAPICalled', 'params': {'type': 'error'}}, 'console.error: '),
    ({'method': 'Runtime.exceptionThrown', 'params': {'exceptionDetails': {
        'text': 'Uncaught', 'exception': {'description': 'ReferenceError: missing'},
        'url': 'core.js', 'lineNumber': 9}}}, 'exception: ReferenceError: missing (core.js:10)'),
    ({'method': 'Runtime.exceptionThrown', 'params': {'exceptionDetails': {'text': 'Uncaught'}}},
     'exception: Uncaught (:1)'),
    ({'method': 'Runtime.consoleAPICalled', 'params': {'type': 'warning'}}, None),
    ({'method': 'Network.loadingFinished'}, None),
])
def test_console_error_parsing(event, expected):
    assert console_error(event) == expected


def test_seed_uses_only_fixture_data(monkeypatch, tmp_path):
    from app import channels, config, library, settings, store, footage
    monkeypatch.setenv('CORKBORED_DATA', str(tmp_path))
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(config, 'WRITABLE_DIRS', (tmp_path / 'library',))
    monkeypatch.setattr(library, '_INDEX_FILE', tmp_path / 'library/library.json')
    monkeypatch.setattr(library, '_FILES', tmp_path / 'library')
    monkeypatch.setattr(library, '_THUMBS', tmp_path / 'library')
    monkeypatch.setattr(library, 'LIBRARY_DIR', tmp_path / 'library')
    seed()
    assert len(footage.load('ssnapshot').clips) == 2
    assert footage.status('ssnapshot')['ready'] == 1
    assert settings.load_file()['setup_complete'] == 'true'
    assert not settings.setup_needed()
    assert channels.load('csnapshot').name == 'Snapshot channel'
    assert channels.load('csnapshot').blocks == ['title_card']
    assert channels.load('csnapshot').block_presets[0]['name'] == 'Our chapter card'
    for fmt in FORMATS:
        p = store.load(f'psnap{fmt}')
        assert p.style.format == fmt
        assert p.channel_id == 'csnapshot'
        assert all(not slide.take for slide in p.slides)
        assert store.project_dir(p.id).joinpath('media/pic.jpg').is_file()
    mixed = store.load('psnapmixed')
    from app.kinds import kind_for
    assert [kind_for(mixed,s) for s in mixed.slides] == ['kenburns','board','casefile','block']
    assets = library.list_all()
    assert len(assets) == 1 and assets[0]['title'] == 'Fixture picture'

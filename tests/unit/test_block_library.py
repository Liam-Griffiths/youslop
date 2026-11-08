"""Browse/poster contracts. Never starts Chromium or a render."""
import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import block_library as library, blocks, channels, jobs, main, paths
from app.schema import Channel


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(library, '_POSTER_JOB', None)
    monkeypatch.delenv('CORKBORED_BLOCK_POSTERS', raising=False)
    meta = json.loads((blocks.BUILTIN_DIR / 'number_slam/block.json').read_text())
    root = tmp_path / 'block'
    root.mkdir()
    (root / 'block.json').write_text(json.dumps(meta))
    found = {'number_slam': dict(meta=meta, root=root)}
    monkeypatch.setattr(library, 'registry', lambda: found)
    return root, found


def test_metadata_shape_filters_and_legacy_id(isolated):
    channels.save(Channel(id='ctest', name='Test', blocks=['number_slam']))
    row = main.list_blocks(q='number', aspect='9:16', channel='ctest')[0]
    assert row['ref'] == row['id'] == 'number_slam'
    assert row['channels'] == ['ctest'] and row['source'] == 'built-in'
    assert {'description','category','tags','duration','licence','origin','check_status','variables','posters'} <= row.keys()
    for query in [dict(q='map'), dict(aspect='1:1'), dict(source='mine'), dict(category='unknown'), dict(data=True), dict(channel='absent')]:
        assert main.list_blocks(**query) == []
    assert row['posters'] == {}
    assert main.block_poster('number_slam').status_code == 204
    with pytest.raises(HTTPException) as error:
        main.block_poster('unknown')
    assert error.value.status_code == 400


def test_poster_signature_tracks_files_and_defaults(isolated):
    root, found = isolated
    first = library.poster_path('number_slam', '16:9')
    (root / 'asset.txt').write_text('new asset')
    second = library.poster_path('number_slam', '16:9')
    assert first != second
    meta = found['number_slam']['meta']
    meta['variables']['title']['default'] = 'New title'
    (root / 'block.json').write_text(json.dumps(meta))
    assert second != library.poster_path('number_slam', '16:9')
    path = library.poster_path('number_slam', '16:9')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'fixture png')
    assert main.block_poster('number_slam').path == path


def test_explicit_single_batch_and_snapshot_opt_out(isolated, monkeypatch):
    start = Mock(return_value='jposters')
    monkeypatch.setattr(jobs, 'start', start)
    monkeypatch.setattr(jobs, 'get', lambda jid: {'state':'running'})
    assert library.start_posters() == library.start_posters() == {'job':'jposters'}
    start.assert_called_once_with('block posters', '', library.make_posters, cancellable=True)
    monkeypatch.setenv('CORKBORED_BLOCK_POSTERS', 'off')
    assert library.start_posters() == {'job':None}


def test_batch_one_session_quarter_size_and_atomic_publish(isolated, monkeypatch, tmp_path):
    root, found = isolated
    monkeypatch.setattr(library.scenes, '_prepare', lambda owner, template, ctx, *a:
                        ('key', tmp_path / 'scenes/key.html', ctx))
    calls = []
    def capture(items, directory, **kw):
        calls.append(items)
        for item in items:
            assert item['size'] in ((480,270),(270,480)) and item['assets_root'] == str(root)
            kw['scene_probe'](None, None, item, item['t'])
            kw['on_still'](item['clip'], b'png fixture')
    monkeypatch.setattr(library.stage, 'capture_stills', capture)
    assert library.make_posters(lambda message: None) == {'posters':2}
    assert len(calls) == 1
    assert library.poster_path('number_slam','9:16').read_bytes() == b'png fixture'
    assert library.start_posters() == {'job':None}


def test_registry_reuses_scan_and_invalidates_on_file_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks, 'BUILTIN_DIR', tmp_path)
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'users')
    monkeypatch.setattr(library.packs, 'BUILTIN_DIR', tmp_path / 'builtin-packs')
    monkeypatch.setattr(library.packs, 'PACKS_DIR', tmp_path / 'packs')
    monkeypatch.setattr(library, '_REGISTRY', (None, {}))
    discover = Mock(return_value={})
    monkeypatch.setattr(blocks, 'discover', discover)
    library.registry(); library.registry()
    assert discover.call_count == 1
    (tmp_path / 'block.json').write_text('{}')
    library.registry()
    assert discover.call_count == 2

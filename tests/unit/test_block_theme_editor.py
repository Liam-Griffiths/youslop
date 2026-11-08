"""Theme editor contracts without Chromium, network, movies or model calls."""
from unittest.mock import Mock

import pytest

from app import block_library as library, blocks, channels, main, paths, store
from app.schema import Channel


@pytest.fixture
def owners(tmp_path, monkeypatch, project):
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.delenv('CORKBORED_BLOCK_POSTERS', raising=False)
    monkeypatch.setattr(library, '_REQUESTS', {})
    channel = Channel(id='ctheme', name='Theme')
    channel.style.block_theme = {'accent': '#3DFFDC'}
    channels.save(channel)
    project.channel_id = channel.id
    project.style.block_theme = {}
    store.save(project)
    return channel, project


def test_unsaved_save_inherit_override_reset_and_atomic_validation(owners):
    channel, project = owners
    context = library.theme_context('channel', channel.id, {'accent': '#FF3366'})
    assert context['theme']['accent'] == '#FF3366'
    assert channels.load(channel.id).style.block_theme['accent'] == '#3DFFDC'
    payload = dict(scope='project', id=project.id, overrides={'accent': '#FF3366'})
    result = main.save_block_theme(payload)
    assert result['tokens']['accent'] == dict(value='#FF3366', source='project', editable=True)
    assert store.load(project.id).style.block_theme['accent'] == '#FF3366'
    reset = main.save_block_theme({**payload, 'overrides': {'accent': None}})
    assert reset['tokens']['accent']['source'] == 'channel'
    assert reset['theme']['accent'] == '#3DFFDC'
    with pytest.raises(main.HTTPException):
        main.save_block_theme({**payload, 'overrides': {'accent': '#000000', 'pace': 5}})
    assert store.load(project.id).style.block_theme == {}
    saved = main.save_block_theme(dict(scope='channel', id=channel.id, overrides={'accent': '#FF3366'}))
    assert saved['tokens']['accent']['source'] == 'channel'
    assert library.theme_context('project', project.id)['theme']['accent'] == '#FF3366'
    assert main.get_block_theme('channel', channel.id)['fonts']['EB Garamond'].startswith('/fonts/')


def test_sheet_batch_midpoints_cache_theme_and_supersession(owners, monkeypatch):
    channel, _ = owners
    captures = []
    def capture(items, root, *, on_still):
        captures.append(items)
        for item in items:
            on_still(item['clip'], b'poster')
    monkeypatch.setattr(library.stage, 'capture_stills', capture)
    payload = dict(scope='channel', id=channel.id, session='sheet-test', sequence=0)
    first = main.block_theme_sheet(payload)
    assert [p['ref'] for p in first['posters']] == list(library.SHEET_BLOCKS)
    assert len(captures) == 1 and len(captures[0]) == 6
    for item in captures[0]:
        _, ctx = blocks.prepare(item['clip'])
        assert item['t'] == ctx['duration'] / 2
        assert item['size'] == (480, 270)
    second = main.block_theme_sheet({**payload, 'sequence': 1})
    assert second['posters'] == first['posters'] and len(captures) == 1
    changed = main.block_theme_sheet({**payload, 'sequence': 2, 'overrides': {'accent': '#FF3366'}})
    assert changed['posters'][0]['url'] != first['posters'][0]['url']
    assert len(captures) == 2
    assert main.block_theme_sheet({**payload, 'sequence': 1}) == {'stale': True}
    assert len(captures) == 2
    one = main.block_theme_sheet({**payload, 'sequence': 3, 'ref': 'title_card', 'aspect': '9:16'})
    assert len(one['posters']) == 1 and captures[-1][0]['size'] == (270, 480)
    monkeypatch.setenv('CORKBORED_BLOCK_POSTERS', 'off')
    cached = main.block_theme_sheet({**payload, 'sequence': 4})
    assert cached['disabled'] and cached['posters'] == first['posters']
    missing = main.block_theme_sheet({**payload, 'sequence': 5, 'overrides': {'accent': '#123456'}})
    assert missing['posters'] == [] and len(captures) == 3
    with pytest.raises(main.HTTPException):
        main.block_theme_sheet({**payload, 'sequence': 4, 'ref': '../bad'})


def test_all_preview_kinds_resolve_scope_and_scratch(owners, monkeypatch):
    channel, _ = owners
    preview = Mock(return_value={'url': 'fixture'})
    monkeypatch.setattr(library, 'preview', preview)
    for kind in ('trial', 'motion'):
        main.block_preview('title_card', dict(kind=kind, theme_context=dict(scope='channel', owner=channel.id, overrides={'accent':'#FF3366'})))
        assert preview.call_args.kwargs['theme']['accent'] == '#FF3366'
    assert channels.load(channel.id).style.block_theme['accent'] == '#3DFFDC'

"""Kits persist look/preferences without changing authored pictures or takes."""
import asyncio
from copy import deepcopy
import json

import httpx
import pytest
from fastapi import HTTPException

from app import channels, main, stages, store, style_kits as kits
from app.schema import Channel, Project, Slide, new_project
from tests.unit.test_picture_kinds import mixed


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(kits, 'INDEX', tmp_path / 'kits/index.json')
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(kits.slide_styles, '_INDEX_FILE', tmp_path / 'slide-styles.json')


def test_casefile_preview_and_apply_preserve_mixed_content(mixed):
    before = deepcopy(mixed.to_dict())
    slides = json.dumps(before['slides'], sort_keys=True)
    mixed.blocks = ['title_card']
    mixed.block_presets = [dict(id='mine', name='Mine', block='title_card', values={})]
    preview = kits.apply_kit(mixed, 'casefile', dry_run=True)
    assert preview['follows_default'] == 0 and preview['kept'] == 4
    assert preview['ready'] == 0 and preview['needs'] == 'cues on words'
    assert json.dumps(mixed.to_dict()['slides'], sort_keys=True) == slides
    assert mixed.style.to_dict() == before['style'] and mixed.style_kit == {}
    assert kits.apply_kit(mixed, 'casefile') == preview
    assert mixed.style.format == 'casefile'
    assert set(mixed.blocks) >= {'title_card', 'quote_card', 'date_timeline'}
    assert mixed.block_presets[0]['id'] == 'mine'
    assert json.dumps(mixed.to_dict()['slides'], sort_keys=True) == slides
    assert set(preview['changes']) <= {'style', 'blocks', 'block_presets', 'style_kit'}
    assert 'Blocks at most 50%' in stages.visual_rules(mixed)['rule']
    mixed.slides[0].kind = ''
    assert kits.apply_kit(mixed, 'board', dry_run=True)['follows_default'] == 1
    mixed.slides[0].on_camera = True
    assert kits.apply_kit(mixed, 'board', dry_run=True)['follows_default'] == 0


def test_save_inherited_look_roundtrip_and_independent_snapshot():
    channel = Channel(id='c', name='Series', blocks=['quote_card'])
    channel.style.block_theme = dict(radius=8, font_body='Inter')
    channel.block_presets = [dict(id='p', name='Title', block='title_card', values={'title':'Saved'})]
    channels.save(channel)
    source = new_project('Source', channel=channel)
    source.style.accent = '#123456'
    source.style.block_theme = dict(pace=1.2)
    source.style_kit = dict(rules=dict(block_share_max=.25))
    saved = kits.save_kit('My doc look', source)
    dest = Project(id='p', idea='New', blocks=['number_slam'])
    kits.apply_kit(dest, saved)
    assert dest.style.accent == '#123456'
    assert dest.style.block_theme['radius'] == 8 and dest.style.block_theme['pace'] == 1.2
    assert dest.blocks == ['number_slam', 'quote_card']
    assert dest.block_presets[0]['values']['title'] == 'Saved'
    kits.apply_kit(dest, saved)
    assert len(dest.block_presets) == 1
    clone = kits.import_bundle(kits.export_bundle(saved['id']))
    assert clone['id'] != saved['id']
    kits.change(saved['id'], 'Renamed')
    kits.change(saved['id'])
    assert dest.style_kit['name'] == 'My doc look'
    for cls, owner in [(Project, dest), (Channel, channel)]:
        kits.apply_kit(owner, clone)
        raw = owner.to_dict()
        raw['future'] = True
        restored = cls.from_dict(raw)
        assert restored.style_kit == owner.style_kit
        restored.style_kit['rules']['block_share_max'] = 1
        assert owner.style_kit['rules']['block_share_max'] == .25
        assert cls.from_dict({k:v for k,v in raw.items() if k != 'style_kit'}).style_kit == {}
    assert Project.from_dict(dest.to_dict()).blocks == dest.blocks


def test_legacy_formats_and_slide_styles_are_readonly_adapters():
    channel = Channel(id='c', name='Old')
    style = channel.style.to_dict()
    style.update(format='essay', music_db=-21, picture_every=2)
    channel.formats = [dict(name='Old look', style=style, frame=dict(move_max_s=.7),
                           look=dict(intro=dict(template='signal'), outro=dict(enabled=True)))]
    channels.save(channel)
    original = (channels.CHANNELS_DIR/'c/channel.json').read_bytes()
    kits.slide_styles._INDEX_FILE.write_text(json.dumps(dict(styles=[dict(id='ss1',name='Old slide')])))
    adapter = next(k for k in kits.list_kits() if k['id'].startswith('format:'))
    home = new_project('', channel=channel, format_name='Old look')
    target = Project(id='p', idea='Test', slides=[Slide(), Slide()])
    kits.apply_kit(target, adapter)
    for key in ('style', 'frame', 'intro', 'outro', 'format_look'):
        assert target.to_dict()[key] == home.to_dict()[key]
    assert len(target.picture_runs()) == 1  # Derived summary fields never replace methods.
    assert (channels.CHANNELS_DIR/'c/channel.json').read_bytes() == original
    kits.apply_kit(target, 'custom:ss1')
    assert target.style.format == 'custom:ss1'
    with pytest.raises(HTTPException):
        kits.change(adapter['id'], 'No migration')


def test_builtins_rules_and_invalid_import():
    from app import blocks
    found = blocks.discover()
    assert len(kits.builtin_kits()) == 9
    for kit in kits.builtin_kits():
        assert set(kit['blocks']['pins']) <= found.keys()
    p = Project(id='p', idea='Test')
    assert stages.visual_rules(p)['rules'] == {}
    assert stages.stages(p, {})[3]['rule'] == stages.visual_rules(p)['rule']
    for patch in [dict(default_kind='bogus'), dict(blocks=[]), dict(look=dict(vignette=True)),
                  dict(block_theme=dict(radius=99)), dict(rules=dict(block_share_max=2)), dict(name='')]:
        bundle = kits.export_bundle('kenburns')
        bundle['kit'].update(patch)
        with pytest.raises(ValueError):
            kits.import_bundle(bundle)
    assert not kits.INDEX.exists()


def test_http_lifecycle_and_dry_run(monkeypatch, mixed):
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    mixed.id = 'p'
    store.save(mixed)
    channels.save(Channel(id='c', name='Series'))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            assert len((await client.get('/api/style-kits')).json()) == 9
            for owner, ident, path in [('projects','p',store.PROJECTS_DIR/'p/project.json'),
                                       ('channels','c',channels.CHANNELS_DIR/'c/channel.json')]:
                url = f'/api/{owner}/{ident}/style-kit'
                before = path.read_bytes()
                preview = await client.post(url, json=dict(kit_id='casefile',dry_run=True))
                assert preview.status_code == 200 and path.read_bytes() == before
                result = await client.post(url, json=dict(kit_id='casefile'))
                assert result.status_code == 200 and result.json() == preview.json()
                assert json.loads(path.read_bytes()).get('slides') == json.loads(before).get('slides')
                assert (await client.post(url, json=dict(kit_id='casefile',dry_run='false'))).status_code == 400
            saved = (await client.post('/api/style-kits', json=dict(owner='projects',id='p',name='Saved'))).json()
            base = '/api/style-kits/' + saved['id']
            bundle = (await client.get(base+'/export')).json()
            assert (await client.post('/api/style-kits/import', json=bundle)).status_code == 200
            assert (await client.patch(base,json=dict(name='New'))).json()['name'] == 'New'
            assert (await client.delete(base)).status_code == 200
            assert (await client.get(base+'/export')).status_code == 404
            assert (await client.post('/api/projects/missing/style-kit',json=dict(kit_id='essay'))).status_code == 404
    asyncio.run(run())


def test_builtin_kit_keeps_user_settings():
    """A built-in kit brings colours and grade only: engines, cadence and knobs stay."""
    from app import style_kits
    from app.schema import Project
    p = Project(id='keep', idea='', title='t')
    p.style.picture_every, p.style.chapter_engine = 3, 'scene'
    p.style.vignette, p.style.board_hand, p.style.transition = .1, 'chalk', 1.2
    style_kits.apply_kit(p, 'loudmouth')
    assert p.style.format == 'loudmouth'
    assert (p.style.picture_every, p.style.chapter_engine, p.style.vignette,
            p.style.board_hand, p.style.transition) == (3, 'scene', .1, 'chalk', 1.2)
    assert not any(k.endswith('_engine') or k == 'picture_every' for k in style_kits.LOOK_FIELDS)

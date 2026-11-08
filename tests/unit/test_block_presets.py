"""Preset persistence and explicit application, without renders or model calls."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from app import block_presets as presets, blocks, channels, edits, main, render, store
from app.schema import Channel, Project, Slide


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    channels.save(Channel(id='c1', name='Series', blocks=['title_card']))
    store.save(Project(id='p1', idea='Test', channel_id='c1', slides=[Slide(id='s1')]))
    store.save(Project(id='p2', idea='Other', channel_id='c1', slides=[Slide(id='s2')]))
    return dict(name='Chapter card', block='title_card', values={'title':'Our chapter'})


@pytest.mark.parametrize('cls,raw', [(Channel, {'id':'c1','name':'Old'}), (Project, {'id':'p1','idea':'Old'})])
def test_old_and_nested_roundtrip(cls, raw):
    assert cls.from_dict(raw).block_presets == []
    raw['unknown_future'] = True
    raw['block_presets'] = [dict(id='preset', name='Saved', block='missing', values={'old':'kept'})]
    obj = cls.from_dict(raw)
    assert cls.from_dict(obj.to_dict()).block_presets == raw['block_presets']
    obj.block_presets[0]['values']['old'] = 'changed'
    assert raw['block_presets'][0]['values']['old'] == 'kept'


def test_crud_validation_and_missing_block(saved, monkeypatch):
    item = presets.create('channels', 'c1', saved)
    assert item['values']['title'] == 'Our chapter'
    assert presets.listing('projects', 'p1') == []
    assert not presets.listing('channels', 'c1')[0]['missing']
    updated = presets.change('channels', 'c1', item['id'], {'name':'Renamed'})
    assert updated['values'] == item['values']
    for patch in [{'values':{'unknown':'x'}}, {'seconds':True}, {'seconds':float('nan')}, {'aspect':'1:1'}, {'name':''}]:
        with pytest.raises(HTTPException) as error:
            presets.change('channels', 'c1', item['id'], patch)
        assert error.value.status_code == 400
    monkeypatch.setattr(blocks, 'discover', lambda: {})
    assert presets.listing('channels', 'c1')[0]['missing']
    assert presets.change('channels', 'c1', item['id'], {'name':'Still here'})['values'] == item['values']
    with pytest.raises(HTTPException):
        presets.change('channels', 'c1', item['id'], {'values':{'title':'Changed'}})
    presets.change('channels', 'c1', item['id'])
    assert presets.listing('channels', 'c1') == []


def test_explicit_update_counts_slides_and_retains_overlays(saved):
    item = presets.create('channels', 'c1', saved)
    ref = dict(id=item['id'], scope='channel')
    p = store.load('p1')
    edits.patch_slide_fields(p.slides[0], {'cues':{'blocks':[dict(block='title_card',vars={'title':'Per slide'},preset=ref)]}})
    # A provenance-matched graphic uses a real overlay block with its own preset.
    graphic = presets.create('channels', 'c1', dict(name='Name',block='lower_third_rule',values={}))
    overlay_ref = dict(id=graphic['id'],scope='channel')
    overlay = dict(id='o1',block_id='lower_third_rule',vars=graphic['values'],at=1,dur=2,
                   position='bottom-left',by='hand',preset=overlay_ref)
    from app import block_overlays
    # Use authored positions rather than assuming a block's allowed enum.
    overlay['position'] = blocks.discover()['lower_third_rule']['meta']['overlay']['position'][0]
    edits.patch_slide_fields(p.slides[0], {'overlays':[overlay]})
    assert p.slides[0].overlays[0]['preset'] == overlay_ref
    store.save(p)
    presets.change('channels', 'c1', item['id'], {'values':{'title':'New chapter'}})
    assert store.load('p1').slides[0].cues['blocks'][0]['vars']['title'] == 'Per slide'
    assert presets.affected('channels','c1',item['id']) == {'slides':1}
    assert presets.affected('channels','c1',item['id'],True) == {'slides':1}
    after = store.load('p1').slides[0]
    assert after.cues['blocks'][0]['vars']['title'] == 'New chapter'
    before = deepcopy(after.overlays[0])
    assert presets.affected('channels','c1',graphic['id'],True) == {'slides':1}
    assert store.load('p1').slides[0].overlays[0] == before
    assert not store.load('p2').slides[0].cues
    presets.change('channels','c1',item['id'])
    assert store.load('p1').slides[0].cues['blocks'][0]['vars']['title'] == 'New chapter'
    for bad in [{'id':1,'scope':'project'}, {'id':'x','scope':'all'}, None]:
        with pytest.raises(edits.EditError):
            edits.patch_slide_fields(after, {'cues':{'blocks':[dict(block='title_card',vars={},preset=bad)]}})
        with pytest.raises(ValueError, match='Preset needs'):
            block_overlays.validate(None,[dict(overlay,preset=bad)])


def test_missing_block_errors_keep_stored_values(saved, monkeypatch):
    p = store.load('p1')
    p.slides[0].cues = {'blocks':[dict(block='removed',vars={'title':'Keep me'})]}
    store.save(p)
    monkeypatch.setattr(blocks, 'discover', lambda: {})
    with pytest.raises(ValueError, match='Block missing: removed'):
        render._block_versions(p.slides[0])
    assert store.load('p1').slides[0].cues['blocks'][0]['vars'] == {'title':'Keep me'}


def test_http_routes_registered():
    routes = {(r.path,method) for r in main.app.routes for method in (getattr(r,'methods',None) or [])}
    base = '/api/{owner}/{ident}/block-presets'
    assert {(base,'GET'),(base,'POST'),(base+'/{preset_id}','PATCH'),(base+'/{preset_id}','DELETE'),
            (base+'/{preset_id}/slides','GET'),(base+'/{preset_id}/slides','POST')} <= routes


def test_http_crud_and_project_isolation(saved, monkeypatch):
    import asyncio
    import httpx

    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            url = '/api/projects/p1/block-presets'
            response = await client.post(url, json=saved)
            assert response.status_code == 200
            item = response.json()
            assert (await client.get(url)).json()[0]['id'] == item['id']
            assert (await client.get('/api/projects/p2/block-presets')).json() == []
            assert (await client.get('/api/channels/c1/block-presets')).json() == []
            assert (await client.patch(url+'/'+item['id'], json={'values':{'title':'x'*500}})).status_code == 400
            assert (await client.patch(url+'/'+item['id'], json={'name':'New name'})).json()['name'] == 'New name'
            assert (await client.get(url+'/'+item['id']+'/slides')).json() == {'slides':0}
            assert (await client.delete(url+'/'+item['id'])).status_code == 200
            assert (await client.get(url)).json() == []
            assert (await client.get('/api/projects/absent/block-presets')).status_code == 404
    asyncio.run(run())

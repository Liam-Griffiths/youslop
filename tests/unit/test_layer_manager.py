"""Layer edits preserve items and history without media work or model calls."""
import asyncio
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest

from app import layers, main, store, undo
from app.edits import EditError
from app.schema import Layer, Project, Slide


@pytest.fixture
def managed(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    item = dict(id='map', block_id='lower_third_panel', vars={}, at=0, dur=1, on='river')
    p = Project(id='pmanager', idea='Synthetic layers', slides=[Slide(id='a',
        narration='A river crosses the map.', overlays=[item], title='River')])
    p.style.format = 'kenburns'
    store.save(p)
    return p


def test_first_edit_metadata_duplicate_and_preserved_empty_layers(managed):
    p = managed
    assert not p.layers
    original = deepcopy(p.slides[0].overlays)
    layers.patch_flags(p, 'pictures', {'name':'Main picture', 'color':'good'})
    assert p.layers and p.layers[0].name == 'Main picture'
    layers.manage(p, {'op':'add', 'name':'Maps', 'role':'graphics'})
    maps = p.layers[-1]
    layers.manage(p, {'op':'duplicate', 'id':maps.id})
    assert p.layers[-1].id != maps.id and p.layers[-1].role == maps.role
    rows = {r['id']:r for r in layers.rows(p)}
    assert not rows[maps.id]['items'] and not rows[p.layers[-1].id]['items']
    assert p.slides[0].overlays == [{**original[0], 'layer':'graphics'}]
    store.save(p)
    assert store.load(p.id).layers == p.layers


@pytest.mark.parametrize('patch', [{'name':''}, {'name':'x'*25}, {'color':'#fff'},
                                  {'hidden':1}, {'locked':'yes'}, {'role':'voice'}])
def test_invalid_metadata_is_atomic(managed, patch):
    before = managed.to_dict()
    with pytest.raises(EditError):
        layers.patch_flags(managed, 'pictures', patch)
    assert managed.to_dict() == before


def test_old_long_name_can_still_be_hidden_and_unlocked(managed):
    managed.layers = [Layer(id='old', name='An existing descriptive layer name', locked=True)]
    layers.patch_flags(managed, 'old', {'hidden':True, 'locked':False})
    assert managed.layers[0].hidden and not managed.layers[0].locked


def test_reordering_preserves_fallback_assignments_and_stacks(managed):
    p = managed
    p.layers = [Layer(id='maps', name='Maps'), Layer(id='diagrams', name='Diagrams', order=1)]
    p.slides[0].overlays += [{**p.slides[0].overlays[0], 'id':'diagram', 'layer':'diagrams'}]
    ids = ['diagrams', 'maps'] + [r['id'] for r in layers.rows(p) if r['role'] != 'graphics']
    layers.manage(p, {'op':'reorder', 'ids':ids})
    assert p.slides[0].overlays[0]['layer'] == 'maps'
    assert layers.graphics_order(p, [(p.slides[0], 3)]) == [(0, 1), (0, 0)]
    with pytest.raises(EditError, match='exactly once'):
        layers.manage(p, {'op':'reorder', 'ids':['maps', 'maps']})


def test_delete_with_move_preserves_dormant_items_and_all_fields(managed):
    p = managed
    p.layers = [Layer(id='maps'), Layer(id='diagrams', order=1)]
    p.slides[0].on_camera = True  # Stored overlays have no timeline spans.
    item = deepcopy(p.slides[0].overlays[0])
    with pytest.raises(EditError, match='Move items'):
        layers.manage(p, {'op':'delete', 'id':'maps'})
    layers.manage(p, {'op':'delete', 'id':'maps', 'move_to':'diagrams'})
    assert p.slides[0].overlays == [{**item, 'layer':'diagrams'}]
    assert all(t.id != 'maps' for t in p.layers)
    layers.manage(p, {'op':'add', 'name':'Empty', 'role':'graphics'})
    layers.manage(p, {'op':'delete', 'id':p.layers[-1].id})
    for role in ('pictures', 'voice'):
        with pytest.raises(EditError, match='cannot be deleted'):
            layers.manage(p, {'op':'delete', 'id':role})


def test_delete_moves_automatic_cues_to_chosen_peer(managed):
    p = managed
    p.style.format = 'flameboat'
    p.layers = [Layer(id=key, role='cues', order=i) for i, key in enumerate(('old', 'other', 'chosen'))]
    assert next(r for r in layers.rows(p) if r['id'] == 'old')['items']
    layers.manage(p, {'op':'delete', 'id':'old', 'move_to':'chosen'})
    assert next(r for r in layers.rows(p) if r['id'] == 'chosen')['items']
    assert not next(r for r in layers.rows(p) if r['id'] == 'other')['items']


def test_http_moves_locks_deletes_and_one_step_undo(managed, monkeypatch):
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            path = f'/api/projects/{managed.id}'
            async def edit(body):
                return await c.post(path+'/layers', json=body, headers={'X-Edit-Label':body['op']+' layer'})
            response = await edit({'op':'add', 'name':'Maps', 'role':'graphics'})
            assert response.status_code == 200, response.text
            maps = response.json()['layers'][-1]['id']
            renamed = await c.patch(path+'/layers/pictures', json={'name':'Main picture', 'color':'good'},
                                    headers={'X-Edit-Label':'rename picture layer'})
            assert renamed.status_code == 200
            assert (await c.post(path+'/undo')).json()['edit_label'] == 'rename picture layer'
            assert store.load(managed.id).layers[0].name == 'Pictures'
            await c.post(path+'/redo')
            assert store.load(managed.id).layers[0].name == 'Main picture'
            order = [t.id for t in store.load(managed.id).layers]
            assert (await edit({'op':'reorder', 'ids':order[::-1]})).status_code == 200
            await c.post(path+'/undo')
            assert [t.id for t in store.load(managed.id).layers] == order
            await c.post(path+'/redo')
            assert [t.id for t in store.load(managed.id).layers] == order[::-1]
            before = deepcopy(store.load(managed.id).slides[0].overlays[0])
            history = undo.read(store.project_dir(managed.id))
            move = {'op':'move_item', 'sid':'a', 'item':'map', 'to':maps}
            assert (await edit(move)).status_code == 200
            assert store.load(managed.id).slides[0].overlays == [{**before, 'layer':maps}]
            assert len(undo.read(store.project_dir(managed.id))['states']) == len(history['states']) + 1
            assert (await c.post(path+'/undo')).status_code == 200
            assert store.load(managed.id).slides[0].overlays == [before]
            assert (await c.post(path+'/redo')).status_code == 200
            assert store.load(managed.id).slides[0].overlays[0]['layer'] == maps
            assert (await c.patch(path+'/layers/graphics', json={'locked':True})).status_code == 200
            for body in ({**move, 'to':'graphics'}, {'op':'delete', 'id':maps, 'move_to':'graphics'},
                         {**move, 'to':'voice'}, {'op':'duplicate', 'id':'pictures'}):
                saved = (store.project_dir(managed.id)/'project.json').read_bytes()
                history = deepcopy(undo.read(store.project_dir(managed.id)))
                result = await edit(body)
                assert result.status_code in (400, 409), result.text
                assert (store.project_dir(managed.id)/'project.json').read_bytes() == saved
                assert undo.read(store.project_dir(managed.id)) == history
            assert (await c.patch(path+'/layers/graphics', json={'locked':False})).status_code == 200
            assert (await edit({'op':'delete', 'id':maps, 'move_to':'graphics'})).status_code == 200
            assert store.load(managed.id).slides[0].overlays[0]['layer'] == 'graphics'
            await c.post(path+'/undo')
            assert store.load(managed.id).slides[0].overlays[0]['layer'] == maps
    asyncio.run(run())


def test_manager_js_queue_and_empty_locked_lane(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{name}.js').read_text()
                       for name in ('layers', 'layer_manager'))
    script = tmp_path/'manager.js'
    script.write_text(source + r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);}, esc=s=>String(s);
const rows=[{id:'maps',name:'Maps',role:'graphics',color:'cool',locked:true,items:[]}];
const TL={pid:'p',data:{project_layers:rows,layers:{graphics:[]}}}, state={project:{id:'p'}};
const html=tlLayerRows();
check(html.includes('data-track="maps"')&&html.includes('Maps'),'saved empty lane remains visible');
check(html.includes('locked')&&html.includes('fill="currentColor"'),'locked lane has filled padlock and tint class');
let tlInspectorQueue=Promise.resolve(), calls=[], refreshed=0, messages=[];
const api=async(url,opts)=>{calls.push({url,...opts});if(JSON.parse(opts.body).name==='fail')throw Error('Rejected');return {id:'p'};};
const tlRefresh=async()=>{refreshed++;},tlInspector=()=>{},tlMsg=m=>messages.push(m);
async function run(){
 const a=tlLayerRequest({name:'Maps'},'maps','rename layer');
 const b=tlLayerRequest({op:'reorder',ids:['maps']},'','reorder layers');
 check(calls.length===0,'edits wait for queue');
 check(await a&&await b&&calls.length===2&&refreshed===2,'each edit saves and refreshes once');
 check(calls[0].method==='PATCH'&&calls[1].method==='POST','metadata reuses PATCH route');
 check(calls[0].editLabel==='rename layer','undo label supplied');
 check(!await tlLayerRequest({name:'fail'},'maps')&&messages[0]==='Rejected','failure is visible');
 TL.pid='other';check(!await tlLayerRequest({name:'Old'},'maps')&&calls.length===3,'navigation prevents stale save');
 print('layer manager queue and lane states passed');
}
run().catch(e=>{printerr(e.stack);imports.system.exit(1);});
''')
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert 'layer manager queue and lane states passed' in result.stdout

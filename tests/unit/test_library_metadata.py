"""Index transactions and executable culling/filter contracts, without a browser."""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import library, library_metadata as metadata, main, store
from tests.unit.test_library_explorer import evaluate_js


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setattr(library, '_INDEX_FILE', tmp_path / 'library.json')
    monkeypatch.setattr(library, 'LIBRARY_DIR', tmp_path)
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    library._INDEX_FILE.write_text(json.dumps({'assets': [dict(id=k, kind='image', tags=[k, 'Shared'], future=True) for k in ('a', 'b')]}))
    return tmp_path


def test_old_index_batch_atomicity_and_collection_preservation(index, monkeypatch):
    assert library.get('a')['rating'] == 0 and library.get('a')['color'] == ''
    writes, original = [], store.atomic_write
    monkeypatch.setattr(store, 'atomic_write', lambda *args: (writes.append(args), original(*args)))
    metadata.mutate(dict(ids=['a', 'b'], rating=4, color='green', add=['New'], remove=['Shared']), 'batch')
    assert len(writes) == 1
    assert all(a['rating'] == 4 and a['color'] == 'green' for a in library.list_all())
    assert library.get('a')['tags'] == ['a', 'New'] and library.get('b')['tags'] == ['b', 'New']
    before = library._INDEX_FILE.read_bytes()
    for patch in (dict(ids=['a', 'missing'], rating=1), dict(ids=['a'], rating=6), dict(ids=['a'], color='orange')):
        with pytest.raises(ValueError):
            metadata.mutate(patch, 'batch')
        assert library._INDEX_FILE.read_bytes() == before
    metadata.mutate(dict(name='Picks', kind='manual'), 'collections')
    ident = metadata.context()['collections'][0]['id']
    metadata.mutate(dict(id=ident, ids=['a', 'b', 'a']), 'collections')
    metadata.mutate(dict(name='Green unused', kind='smart', filters=dict(rating=4, color='green', usage='unused')), 'collections')
    library.update('a', title='Retitled', rating=5, color='purple')
    library._save_both(library._load_index(), [library.LibraryFolder('f', '/unused')])
    data = metadata.context()
    assert data['collections'][0]['ids'] == ['a', 'b'] and len(data['collections']) == 2
    assert 'New' in data['labels'] and library.get('a')['rating'] == 5
    with pytest.raises(HTTPException) as exc:
        main.edit_library_asset('a', {'rating': -1})
    assert exc.value.status_code == 400


def test_vocabulary_merge_reorder_delete_and_usage(index):
    metadata.mutate(dict(action='rename', old='a', new='b'), 'labels')
    assert library.get('a')['tags'] == ['b', 'Shared']
    metadata.mutate(dict(action='reorder', labels=['Shared', 'b']), 'labels')
    metadata.mutate(dict(name='Label picks', kind='smart', filters=dict(labels=['Shared', 'b'])), 'collections')
    metadata.mutate(dict(action='delete', old='Shared'), 'labels')
    assert all(a['tags'] == ['b'] for a in library.list_all())
    assert metadata.context()['collections'][0]['filters']['labels'] == ['b']
    project = store.PROJECTS_DIR / 'p1'
    project.mkdir(parents=True)
    raw = dict(id='p1', title='Example', bin=[dict(source='library:a')], slides=[
        dict(chosen_id='other', candidates=[dict(id='libb'), dict(id='other')]),
        dict(custom={'vars': {'image': '/scene/{token}/library/a'}})])
    path = project / 'project.json'
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    assert metadata.used_in() == {'a': [dict(id='p1', title='Example')], 'b': []}
    assert path.read_bytes() == before
    raw['bin'] = []  # The custom block must retain a's reference independently.
    raw['slides'].append(dict(chosen_id='libb', candidates=[dict(id='libb', provider='library', ref='b')]))
    path.write_text(json.dumps(raw))
    assert metadata.used_in() == {k: [dict(id='p1', title='Example')] for k in ('a', 'b')}
    before = path.read_bytes()
    metadata.used_in()
    assert path.read_bytes() == before


def test_filters_collections_keys_and_per_node_memory():
    source = '\n'.join(Path('static/js/tabs/'+name+'.js').read_text() for name in ('library_metadata', 'library_explorer'))
    evaluate_js('''const document={addEventListener(){},querySelectorAll(){return []}},window={addEventListener(){}};
      const node={querySelectorAll(){return []}}, $=()=>node, esc=String;
      const state={library:{items:[],folders:[],q:'',kind:''}}, memory={};
      const localStorage={setItem(k,v){memory[k]=v},getItem(k){return memory[k]}};
      const assert=(ok,message)=>{if(!ok)throw Error(message)};
    ''' + source + '''
      const a={id:'a',kind:'image',title:'Station',tags:['Travel','Night'],rating:5,color:'green',width:1920,height:1080,added_at:1800000000};
      const b={...a,id:'b',rating:3,color:'red',width:400,height:800};
      LM.used={a:[],b:[{id:'p'}]};state.library.items=[a,b];
      const filters={rating:4,color:'green',usage:'unused',labels:['Travel','Night'],match:'all',orientation:'landscape',from:'2026-01-01',to:'2028-01-01'};
      assert(libMatches(a,filters)&&!libMatches(b,filters),'Combined filters');
      assert(libMatches(a,{labels:['Missing','Night'],match:'any'}),'Any labels');
      assert(!libMatches(a,{labels:['Missing','Night'],match:'all'}),'All labels');
      assert(!libMatches({...a,width:0,height:0},{orientation:'square'}),'Unknown orientation');
      LX.selected=new Set(['b','a']);libBindMetadata([a,b]);
      assert(node.innerHTML.includes('Used in:'),'Usage survives reverse selection order');
      LM.collections=[{id:'m',name:'Manual',kind:'manual',ids:['a']},{id:'s',name:'Smart',kind:'smart',filters}];
      libTree();LX.node='collection:s';assert(libVisible().map(a=>a.id).join()==='a','Smart collection');
      a.rating=2;assert(libVisible().length===0,'Smart collection updates live');
      LX.node='collection:m';assert(libVisible().length===1,'Manual membership');
      libFilterBar=()=>{};LX.node='all';LM.filters.all=filters;state.library.q='Station';state.library.kind='image';libRemember();
      LX.node='uploaded';libRestore();assert(!state.library.q&&!state.library.kind,'New node starts clear');
      LX.node='all';libRestore();assert(state.library.q==='Station'&&libFilters().rating===4,'Remember node filters');
      assert(JSON.parse(memory['library-filters']).all.usage==='unused','Persisted filters');
      const patches=[];libWrite=(op,p)=>{patches.push(p);return Promise.resolve()};
      LX.selected=new Set(['a','b']);const e={preventDefault(){},key:'4'};
      libRateKey(e);libRateKey({...e,key:'8'});libRateKey({...e,key:'`'});
      assert(patches.length===3&&patches.every(p=>p.ids.length===2),'One batch for each key');
      assert(patches[0].rating===4&&patches[1].color==='green'&&patches[2].color==='','Key mappings');
      assert(!libRateKey({...e,ctrlKey:true}),'Modified key is not a rating');
    ''')


def test_metadata_routes_use_one_transaction(index, monkeypatch):
    import asyncio
    import httpx
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            base = '/api/library/metadata/'
            assert (await client.get(base+'context')).json()['collections'] == []
            result = await client.post(base+'batch', json=dict(ids=['a', 'b'], rating=5, color='purple'))
            assert result.status_code == 200 and len(result.json()['assets']) == 2
            assert (await client.post(base+'batch', json=dict(ids=['a'], rating=6))).status_code == 400
            assert (await client.patch('/api/library/a', json=dict(color='blue'))).json()['color'] == 'blue'
            assert (await client.get(base+'used')).json() == {'a': [], 'b': []}
    asyncio.run(run())


def test_keyboard_writes_serialize_and_retain_grid_focus(tmp_path):
    import shutil
    import subprocess
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    setup = '''let calls=[],active=0,focused=0;const document={activeElement:{}};
      const grid={contains(){return true},focus(){focused++}}, $=()=>grid;
      const LX={selected:new Set(['a','b'])},state={library:{items:[{id:'a'},{id:'b'}]}};
      const libTree=()=>{},libPaint=()=>{},toast=e=>{throw Error(e)};
      async function api(url,options){active++;if(active!==1)throw Error('Concurrent writes');
        await Promise.resolve();calls.push(JSON.parse(options.body));active--;return {assets:state.library.items,labels:[],collections:[]};}
    '''
    checks = '''
      (async()=>{const e={preventDefault(){},key:'5'};libRateKey(e);libRateKey({...e,key:'9'});await LM.writes;
        if(calls.length!==2||calls[0].rating!==5||calls[1].color!=='blue'||focused!==2)throw Error('Lost key, selection or focus');
      })().catch(e=>{printerr(e.stack);imports.system.exit(1)});
    '''
    path = tmp_path / 'culling.js'
    path.write_text(setup + Path('static/js/tabs/library_metadata.js').read_text() + checks)
    result = subprocess.run([runtime, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

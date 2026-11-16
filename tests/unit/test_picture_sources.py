"""Local composing edits preserve recordings and publish one undo state."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest

from app import inserts, library, llm, main, render, store, undo
from app.schema import BinItem


@pytest.fixture
def sources(project, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: pytest.fail('LLM called'))
    project.style.format, project.style.picture_every = 'kenburns', 3
    project.slides[1].picture_mode = 'hold'
    root = store.project_dir(project.id)
    (root / 'bin').mkdir(parents=True)
    (root / 'bin/photo.jpg').write_bytes(b'original image')
    project.bin = [BinItem(id='photo', kind='image', title='Local photo',
                          file='bin/photo.jpg', licence='CC0', credit='Photographer')]
    store.save(project)
    return project


@pytest.mark.parametrize('payload', [{'bin_id':'photo'}, {'asset_id':'asset'}])
def test_replace_group_undo_and_render_source(sources, monkeypatch, payload):
    original = deepcopy(sources.slides[0].to_dict())
    root = store.project_dir(sources.id)
    monkeypatch.setattr(library, 'get', lambda ident: dict(kind='image', title='Library photo'))
    monkeypatch.setattr(library, 'file_path', lambda ident: root / 'bin/photo.jpg')
    changed = main.replace_picture_source(sources.id, sources.slides[1].id, payload)
    p = store.load(sources.id)
    lead = p.slides[0]
    assert changed['slides'][0]['locked_media'] and lead.chosen_id
    assert lead.kind == 'kenburns'
    assert lead.take == original['take'] and lead.history == original['history']
    assert render._chosen(p, lead)[:2] == (root / 'bin/photo.jpg', 'image')
    if 'bin_id' in payload:
        assert lead.candidates[0]['license'] == 'CC0'
        assert lead.candidates[0]['author'] == 'Photographer'
    assert undo.read(root)['states'][-1]['label'] == 'replace picture'
    main.undo_project(p.id)
    assert store.load(p.id).slides[0].to_dict() == original
    main.redo_project(p.id)
    assert store.load(p.id).slides[0].chosen_id == lead.chosen_id
    assert (root / 'bin/photo.jpg').read_bytes() == b'original image'


def test_material_insert_ripple_and_validation(sources):
    row, after = inserts.prepare(sources, dict(kind='picture', bin_id='photo', seconds=4, after='s1'))
    before = sources.est_seconds()
    inserts.place(sources, row, after)
    assert sources.est_seconds() == pytest.approx(before + 4)
    assert render._chosen(sources, row)[0] == store.project_dir(sources.id) / 'bin/photo.jpg'
    assert row.chosen_id == 'binphoto' and row.locked_media and not row.take
    changed, _ = inserts.prepare(sources, dict(seconds=2), row)
    assert changed.insert['seconds'] == 2
    for payload in ({'bin_id':'missing'}, {'asset_id':'missing'}, {'local_path':'/etc/passwd'}):
        path = store.project_dir(sources.id) / 'project.json'
        before = path.read_bytes()
        with pytest.raises(main.HTTPException):
            main.replace_picture_source(sources.id, 's1', payload)
        assert path.read_bytes() == before
    sources.slides[0].on_camera = True
    store.save(sources)
    with pytest.raises(main.HTTPException, match='Choose a non-camera'):
        main.replace_picture_source(sources.id, 's1', {'bin_id':'photo'})


def test_library_replacement_is_portable(sources, tmp_path, monkeypatch):
    original = tmp_path / 'library.jpg'
    original.write_bytes(b'external library picture')
    monkeypatch.setattr(library, 'get', lambda ident: dict(kind='image'))
    monkeypatch.setattr(library, 'file_path', lambda ident: original)
    main.replace_picture_source(sources.id, 's1', {'asset_id':'asset'})
    chosen = store.load(sources.id).slides[0].candidates[0]
    assert chosen['local_path'].startswith('media/')
    assert (store.project_dir(sources.id) / chosen['local_path']).read_bytes() == original.read_bytes()
    assert original.read_bytes() == b'external library picture'


def test_source_drop_targets_without_browser(tmp_path):
    if not (gjs := shutil.which('gjs')):
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{name}.js').read_text()
                       for name in ('inserts', 'source_panel'))
    harness = r'''
const check=(v,m)=>{if(!v) throw Error(m);};
const TL={pid:'p',zoom:10,cur:0}, state={project:{kind:'video'}}, calls=[];
const seg={type:'picture',ref:'a',start:0,duration:10};
const node={dataset:{seg:'0'},classList:{add(){}}};
const lane={querySelectorAll:()=>[],contains:()=>false};
const $=s=>s==='#tl-track .tl-pictures'?lane:{getBoundingClientRect:()=>({left:0})};
const document={querySelectorAll:()=>[]};
const tlSegs=()=>[seg], tlParas=()=>[{id:'a',start:0}], tlSectionEnd=()=>10;
const tlItems=()=>[{kind:'picture',id:'a',sid:'a'}];
let locked=false; const tlCanEdit=()=>!locked;
tlSourceUse=(p,s)=>calls.push(['replace',s.sid]);
tlInsertSave=(id,p)=>calls.push(['insert',p.after]);
tlInsertGhost=(p,s)=>{TL.insertDrop=p;};
const ev=x=>({clientX:x,dataTransfer:{},target:{closest:s=>s==='[data-seg]'?node:null},preventDefault(){},stopPropagation(){}});
const drag=()=>{TL.insertDrag={pid:'p',payload:{kind:'picture',bin_id:'photo',seconds:4}};};
tlWireInserts(); drag(); lane.ondragover(ev(154)); lane.ondrop(ev(154));
check(calls[0][0]==='replace' && calls[0][1]==='a','body replaces');
drag(); lane.ondragover(ev(204)); lane.ondrop(ev(204));
check(calls[1][0]==='insert' && calls[1][1]==='a','boundary inserts');
locked=true; drag(); lane.ondragover(ev(154)); lane.ondrop(ev(154));
check(calls.length===2,'locked layer rejects drop');
TL.insertDrag.pid='other'; lane.ondragover(ev(154)); lane.ondrop(ev(154));
check(calls.length===2,'cross-project drag rejected');
print('source drop targets passed');
'''
    script = tmp_path / 'sources.js'
    script.write_text(source + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

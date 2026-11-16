"""Picture tools: held leads, shot descriptions, serialized edits and undo."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest

from app import main, store, undo
from app.schema import Slide
from app.script_agent import shots


@pytest.mark.parametrize('mode,pictures,script_shots', [
    ('auto', 1, 1), ('hold', 1, 1), ('cut', 2, 1), ('new', 2, 2)])
def test_modes_preserve_takes_and_undo(project, tmp_path, monkeypatch, mode, pictures, script_shots):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    project.style.picture_every = 3
    project.slides = [Slide(id='a', visual_note='Station'), Slide(id='b', visual_note='Station')]
    root = store.project_dir(project.id)
    (root / 'takes').mkdir(parents=True, exist_ok=True)
    (root / 'takes/original.wav').write_bytes(b'recorded audio')
    project.set_take(project.slides[1], 'mic', {'path':'takes/original.wav', 'duration':3, 'words':[]})
    before = deepcopy(project.to_dict()['slides'])
    store.save(project)
    token = undo.edit_source.set(('change picture mode', 'one-gesture'))
    try:
        main.patch_slide(project.id, 'b', {'picture_mode':mode})
    finally:
        undo.edit_source.reset(token)
    p = store.load(project.id)
    assert len(p.picture_runs()) == pictures and len(shots(p)) == script_shots
    assert p.slides[1].takes == before[1]['takes']
    if mode != 'auto':
        main.undo_project(project.id)
        assert store.load(project.id).slides[1].picture_mode == 'auto'
        main.redo_project(project.id)
        assert store.load(project.id).slides[1].picture_mode == mode
    assert (root / 'takes/original.wav').read_bytes() == b'recorded audio'


def test_shot_description_and_candidate_undo(project, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    project.style.picture_every = 3
    project.slides = [Slide(id=sid, visual_note='Station', picture_mode=mode)
                      for sid, mode in [('a','auto'), ('b','hold'), ('c','cut')]]
    project.slides[0].candidates = [{'id':'one', 'local_path':'media/one.jpg'},
                                     {'id':'two', 'local_path':'media/two.jpg'}]
    project.slides[0].chosen_id = 'one'
    store.save(project)
    token = undo.edit_source.set(('edit shot description', 'description'))
    try:
        for slide in project.slides:
            main.patch_slide(project.id, slide.id, {'visual_note':'Morning platform'})
    finally:
        undo.edit_source.reset(token)
    assert {s.visual_note for s in store.load(project.id).slides} == {'Morning platform'}
    main.undo_project(project.id)
    assert {s.visual_note for s in store.load(project.id).slides} == {'Station'}
    token = undo.edit_source.set(('choose picture', 'candidate'))
    try:
        main.patch_slide(project.id, 'a', {'chosen_id':'two', 'locked_media':True})
    finally:
        undo.edit_source.reset(token)
    assert store.load(project.id).slides[0].locked_media
    main.undo_project(project.id)
    lead = store.load(project.id).slides[0]
    assert lead.chosen_id == 'one' and not lead.locked_media


def test_picture_tools_without_browser(tmp_path):
    if not (gjs := shutil.which('gjs')):
        pytest.skip('GJS unavailable')
    writing = Path('static/js/tabs/script-writing.js').read_text()
    source = writing[writing.index('function scriptRuns('):writing.index('// Paragraph panels')]
    source += Path('static/js/timeline/picture_inspector.js').read_text()
    harness = r'''
const check=(v,m)=>{if(!v) throw Error(m);};
const slides=['a','b','c'].map(id=>({id,visual_note:'Station',picture_mode:'auto',candidates:[]}));
slides[1].picture_mode='hold'; slides[2].picture_mode='cut';
slides[0].candidates=[{id:'one',title:'<Station>',provider:'local'},{id:'two',title:'Platform'}];
slides[0].chosen_id='one';
const state={project:{id:'p',slides,picture_runs:[['a','b'],['c']]}};
const sel={kind:'paragraph',id:'b',sid:'b'}, TL={pid:'p',selection:sel};
const esc=s=>String(s).replaceAll('<','&lt;'), pictureKind=()=> 'kenburns', isCut=()=>false;
const thumbUrl=c=>'/local/'+c.id;
const document={activeElement:null,getElementById:()=>null};
const calls=[], crypto={randomUUID:()=> 'gesture'}, tlMsg=m=>{throw Error(m);};
let locked=false, tlInspectorQueue=Promise.resolve();
const tlCanEdit=()=>!locked, tlRefresh=async()=>{}, tlItems=()=>[];
const tlInspector=()=>{if(document.activeElement) document.activeElement.closest=()=>null;};
const api=async()=>state.project;
const saveSlide=async(sid,patch,history)=>{
  calls.push({sid,patch,history}); Object.assign(slides.find(s=>s.id===sid),patch); return patch;
};
const ctx=tlPictureContext(sel);
check(ctx.lead.id==='a' && ctx.members.length===2,'held paragraph resolves lead');
check(ctx.shot.length===3,'cut stays in Script shot');
const html=tlPictureFields(ctx);
check(html.includes('&lt;Station>') && html.includes('data-candidate="two"'),'safe candidates');
check(html.includes('value="cut"') && html.includes('value="new"'),'four picture modes');
check(html.includes('data-picture-mode="b"'),'held paragraph can change mode');
check(tlPictureQueries(' first \n\nsecond\nthird\nfourth\nfifth').join('|')==='first|second|third|fourth','queries');
const nodes=new Map();
const node=k=>{if(!nodes.has(k)) nodes.set(k,{}); return nodes.get(k);};
const candidate=node('candidate'), mode=node('mode');
candidate.dataset={candidate:'two'}; mode.dataset={pictureMode:'b'}; mode.value='cut';
const body={querySelector:node,querySelectorAll:s=>s==='[data-candidate]'?[candidate]:[mode]};
tlPictureWire(sel,ctx,body);
node('#tl-picture-note').onchange({target:{value:'New description'}});
candidate.onclick(); mode.onchange();
tlInspectorQueue.then(async()=>{
 check(calls.slice(0,3).every(c=>c.patch.visual_note==='New description'),'whole Script shot description');
 check(new Set(calls.slice(0,3).map(c=>c.history.editGesture)).size===1,'one undo gesture');
 check(calls[3].sid==='a' && calls[3].patch.chosen_id==='two' && calls[3].patch.locked_media,'candidate saves to lead and locks');
 check(calls[4].sid==='b' && calls[4].patch.picture_mode==='cut','mode targets held paragraph');
 let restored=false;
 document.activeElement={id:'candidate',closest:()=>true};
 document.getElementById=()=>({focus:()=>{restored=true;}});
 await candidate.onclick(); check(restored && calls.length===6,'keyboard focus survives detached field');
 locked=true; await candidate.onclick(); check(calls.length===6,'layer lock');
 locked=false; const pending=candidate.onclick(); TL.pid='other'; await pending;
 check(calls.length===6,'stale project guard');
 print('picture inspector passed');
}).catch(e=>{printerr(e.stack); imports.system.exit(1);});
imports.mainloop.run('test');
'''
    # Exit the GJS loop after queued async handlers settle.
    harness = harness.replace("print('picture inspector passed');", "print('picture inspector passed'); imports.mainloop.quit('test');")
    script = tmp_path / 'picture-inspector.js'
    script.write_text(source + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

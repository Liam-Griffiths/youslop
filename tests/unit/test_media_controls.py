"""Owned placement, undo and detached dependencies; never render or use an LLM."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest

from app import footage, library, main, media_overlays as media, models3d, render, stage, store, undo


def test_media_placement_ranges_undo_and_missing(project, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path/'projects')
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path/'shoots')
    original = tmp_path/'original.mp4'
    original.write_bytes(b'owned original')
    footage._save(footage.Shoot('shoot', files=[footage.SourceFile('file', str(original), duration=20)]))
    monkeypatch.setattr(library, 'get', lambda _: dict(kind='video', duration=7))
    monkeypatch.setattr(library, 'file_path', lambda _: original)
    monkeypatch.setattr(render, '_render_segment', lambda *a, **k: pytest.fail('placement rendered'))
    project.style.format = 'kenburns'
    recording = store.project_dir(project.id)/'takes/keep.wav'
    recording.write_bytes(b'recorded audio')
    project.set_take(project.slides[0], 'mic', dict(path='takes/keep.wav', duration=8))
    store.save(project)
    before = deepcopy(store.load(project.id).to_dict())
    payload = dict(kind='clip', shoot_id='shoot', source_id='file', in_s=5, out_s=11)
    main.place_media_overlay(project.id, 's1', dict(source=payload, at=1))
    placed = store.load(project.id)
    item = placed.slide('s1').overlays[0]
    assert item['dur'] == 6 and item['in'] == item['volume'] == 0
    assert media.source(placed, item) == (original, 'video', 5, 6)
    item['in'], item['dur'] = 2, 3
    inputs, _, _ = media.compose(placed, item, [], 'null[v]', '[v]', (480,270), 15, 1, 'm')
    assert inputs[:4] == ['-ss','7.000000','-t','3.000000']
    assert undo.read(store.project_dir(project.id))['states'][-1]['label'] == 'place media'
    assert len(undo.read(store.project_dir(project.id))['states']) == 2
    main.undo_project(project.id)
    assert store.load(project.id).slides[0].to_dict() == before['slides'][0]
    main.redo_project(project.id)
    main.place_media_overlay(project.id, 's1', dict(source=dict(kind='picture', asset_id='lib', seconds=4)))
    assert store.load(project.id).slide('s1').overlays[-1]['dur'] == 7
    assert recording.read_bytes() == b'recorded audio' and original.read_bytes() == b'owned original'
    # Candidate references deliberately depend on the source paragraph remaining.
    missing = dict(item, source=dict(source_slide='gone', candidate_id='gone'))
    assert media.info(placed, missing)['unavailable']
    assert media.info(placed, dict(item,source={'bin_id':'gone'}))['unavailable']
    placed.slide('s1').overlays = [missing]
    assert render.timeline(placed)['layers']['media'][0]['unavailable']
    placed = store.load(project.id)
    lane = next(l for l in placed.layers if l.role == 'media')
    lane.locked = True
    store.save(placed)
    before = (store.project_dir(project.id)/'project.json').read_bytes()
    with pytest.raises(main.HTTPException, match='unlocked media'):
        main.place_media_overlay(project.id,'s1',dict(source=payload, layer=lane.id))
    assert (store.project_dir(project.id)/'project.json').read_bytes() == before


def test_detached_shot_survives_cast_and_slide_edits(project, tmp_path, monkeypatch):
    from app import composing_sources, media_shots
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    monkeypatch.setattr(models3d, 'get', lambda ident: dict(id=ident, kind='object', title='Model'))
    monkeypatch.setattr(stage, 'solve', lambda *a, **k: pytest.fail('implicit solver'))
    monkeypatch.setattr(stage, 'render', lambda *a, **k: pytest.fail('implicit render'))
    project.style.format = 'kenburns'
    row = project.slides[1]
    row.insert = dict(kind='stage', model_id='model', seconds=6)
    composing_sources.prepare(project,row,row.insert)
    composing_sources.attach(project,row)
    store.save(project)
    main.place_media_overlay(project.id,'s1',dict(source=dict(kind='stage',source_slide=row.id,seconds=6)))
    project = store.load(project.id)
    item = project.slides[0].overlays[0]
    project.cast.clear()
    project.slides.pop(1)
    assert media.source(project,item)[3] == 6
    snapshot = item['source']['shot']
    calls = []
    monkeypatch.setattr(stage, 'solve', lambda rows, models: {rows[0]['id']:dict(shot={'fov':42},checks={})})
    def fake_render(rows, models, root):
        calls.append(rows[0]); root.mkdir(parents=True,exist_ok=True)
        (root/(rows[0]['clip']+'.mp4')).write_bytes(b'preview')
    monkeypatch.setattr(stage,'render',fake_render)
    media_shots.resolve(project,snapshot,size=(480,270),fps=15,render=True)
    assert calls[0]['frames'] == 90 and calls[0]['W'] == 480
    media_shots.resolve(project,snapshot,size=(480,270),fps=15,render=True)
    assert len(calls) == 1  # cached; no actual browser or 3D run


def test_media_gestures_headless(tmp_path):
    if not (gjs := shutil.which('gjs')):
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{n}.js').read_text() for n in
                       ('edit','graphics','graphic_actions','graphic_gestures','media','ergonomics'))
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);}, structuredClone=v=>JSON.parse(JSON.stringify(v));
let serial=0, calls=[], refreshes=[], tlInspectorQueue=Promise.resolve();
const crypto={randomUUID:()=>String(++serial)}, state={project:{id:'p',slides:[{id:'s',overlays:[
 {id:'m',type:'media',source:{asset_id:'a'},at:1,dur:4,in:2,box:{x:.65,y:.05,w:.3,h:.3},volume:0}]}]}};
const TL={pid:'p',cur:2,zoom:100}, tlParas=()=>[{id:'s',start:0,duration:20}], tlFps=()=>30;
const tlItems=kind=>kind==='media'?state.project.slides[0].overlays.map(o=>({kind:'media',sid:'s',id:o.id,t0:o.at,t1:o.at+o.dur,source_kind:'video',source_length:10})):[];
const tlSelect=s=>{TL.selection=s;TL.selections=s?[s]:[];}, tlPause=()=>{}, tlDraw=()=>{}, tlCanEdit=()=>true;
const tlInspector=()=>{}, tlItemLayerSelect=()=>{}, esc=String;
const tlMsg=m=>{throw Error(m);}, tlRefresh=async(...args)=>refreshes.push(args), pictureKind=()=>'', isCut=()=>false;
const api=async(url,opts)=>{calls.push(JSON.parse(opts.body));for(const e of calls.at(-1).edits) Object.assign(state.project.slides[0],e.patch);return state.project;};
const node={style:{},setPointerCapture(){},hasPointerCapture(){return false;}};
let outline;
const document={createElement:()=>({style:{},dataset:{},setAttribute(){},setPointerCapture(){},hasPointerCapture(){return false;},remove(){outline=null;}}),addEventListener(){},removeEventListener(){}};
const player={querySelector:()=>outline,append:n=>{outline=n;},getBoundingClientRect:()=>({width:100,height:100})};
const $=s=>s==='#tl-stage'?player:{append(){},querySelectorAll:()=>[]}, tlTrackHint=()=>({show(){},remove(){}}), tlClock=String;
const ev=x=>({clientX:x,clientY:0,pointerId:1,altKey:true,preventDefault(){}});
async function gesture(edge,dx,cancel=false){const count=calls.length;tlGraphicPointer(ev(0),node,tlItems('media')[0],edge);node.onpointermove(ev(dx));
 check(TL.drag&&calls.length===count,'no save during gesture');if(cancel)node.onpointercancel();else node.onpointerup(ev(dx));await tlInspectorQueue;}
async function run(){
 await gesture('start',100);check(tlGraphic(TL.selection).in===3&&tlGraphic(TL.selection).dur===3,'left trim advances source');
 await gesture('end',100);check(tlGraphic(TL.selection).dur===4,'right trim');
 await gesture('slip',10000);check(tlGraphic(TL.selection).in===6,'slip clamped to owned range');
 const before=calls.length;await gesture('move',100,true);check(calls.length===before,'cancel saves nothing');
 await tlGraphicCommand('split',[TL.selection],4);check(state.project.slides[0].overlays[1].in===8,'split advances second offset');
 check(refreshes.every(a=>a[0]===false&&a[1]===true),'media refresh never renders');
 const box=tlMediaGeometry({x:.65,y:.05,w:.3,h:.3},'se',1,1);check(box.x+box.w===1&&box.y+box.h===1,'resize stays inside frame');
 const moved=tlMediaGeometry(box,'',-2,-2);check(moved.x===0&&moved.y===0,'move clamp');
 tlSelect(tlItems('media')[0]);TL.cur=3;tlMediaBox();
 const pointer=x=>({...ev(x),button:0,target:{dataset:{corner:'se'}},stopPropagation(){}});
 const count=calls.length, original=structuredClone(tlGraphic(TL.selection));
 outline.onpointerdown(pointer(0));outline.onpointermove(pointer(-10));check(calls.length===count,'box move never saves');
 outline.onpointercancel();check(calls.length===count,'box cancellation never saves');
 outline.onpointerdown(pointer(0));outline.onpointerup(pointer(-10));await tlInspectorQueue;
 check(calls.length===count+1&&Math.abs(tlGraphic(TL.selection).box.w-.2)<1e-6,'resize saves once on release');
 const updated=tlGraphic(TL.selection);check(updated.in===original.in&&updated.dur===original.dur&&updated.volume===original.volume,'box edit keeps source and timing');
 const fields={'#media-preset':{},'#media-fit':{},'[data-delete-media]':{},'#media-x':{dataset:{mediaField:'x'},value:'0.5',reportValidity:()=>true}};
 const body={querySelector:k=>fields[k],querySelectorAll:()=>[fields['#media-x']]};
 tlMediaInspector(TL.selection,body);fields['#media-x'].onchange();await tlInspectorQueue;
 check(calls.length===count+2&&tlGraphic(TL.selection).box.x===.5,'one inspector edit saves once');
 check(tlErgonomicsKey({key:'Delete'}),'global Delete reaches media');await tlInspectorQueue;
 check(state.project.slides[0].overlays.length===1,'keyboard deletes selected media only');
 print('media gestures passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path/'media.js'
    script.write_text(source+'\n'+harness)
    result = subprocess.run([gjs,str(script)],capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stdout+result.stderr


def test_placement_reuses_a_free_media_lane(project, monkeypatch):
    from app import media_overlays as media
    monkeypatch.setattr(media, 'source', lambda p, item: ('x', 'image', 0, 0))
    payload = dict(kind='picture', asset_id='lib', seconds=2)
    media.place(project, 's1', dict(source=payload, at=0))
    media.place(project, 's1', dict(source=payload, at=3))   # free on the same lane
    media.place(project, 's1', dict(source=payload, at=3.5))  # overlaps: needs a second lane
    lanes = [o['layer'] for o in project.slide('s1').overlays if o.get('type') == 'media']
    assert lanes[0] == lanes[1] != lanes[2]
    assert sum(l.role == 'media' for l in project.layers) == 2

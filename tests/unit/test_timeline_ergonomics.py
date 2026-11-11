"""Grouped edits and viewport gestures; synthetic data, GJS, no browser/render."""
import asyncio
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest


def test_group_save_is_atomic_and_one_undo(monkeypatch, tmp_path):
    from app import main, store, undo
    from app.schema import Project, Slide
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='pgroup', idea='Synthetic group edit', slides=[Slide(id=f's{i}', title=f'Title {i}',
        take={'path': f'takes/{i}.wav', 'duration': 5, 'words': []}) for i in range(3)])
    store.save(p)
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            path = '/api/projects/pgroup'
            entries = [{'sid': s.id, 'patch': {'title_at': 1}} for s in p.slides]
            r = await client.patch(path+'/slides-batch', json={'edits': entries},
                headers={'X-Edit-Label':'move 3 items', 'X-Edit-Gesture':'group-1'})
            assert r.status_code == 200
            assert all(s['title_at'] == 1 for s in r.json()['slides'])
            assert len(undo.read(store.project_dir(p.id))['states']) == 2
            r = await client.post(path+'/undo')
            assert r.json()['edit_label'] == 'move 3 items'
            assert all(s['title_at'] is None for s in r.json()['slides'])
            await client.post(path+'/redo')
            before = store.load(p.id).to_dict()
            entries[-1]['patch']['title_at'] = 'invalid'
            assert (await client.patch(path+'/slides-batch', json={'edits': entries})).status_code == 400
            assert store.load(p.id).to_dict() == before
            entries = [{'sid': s.id, 'patch': {'title': ''}} for s in p.slides]
            assert (await client.patch(path+'/slides-batch', json={'edits': entries})).status_code == 200
            assert [s.take for s in store.load(p.id).slides] == [s.take for s in p.slides]
            await client.post(path+'/undo')
            assert [s.title for s in store.load(p.id).slides] == [s.title for s in p.slides]
    asyncio.run(run())


def test_gestures_without_browser(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path('static/js/timeline/'+p+'.js').read_text() for p in ['core','inspect','edit','ergonomics'])
    harness = r'''
const check = (v,m) => {if (!v) throw Error(m);};
const near = (a,b) => Math.abs(a-b)<.00001;
const structuredClone = v => JSON.parse(JSON.stringify(v));
class El {
 constructor(dataset={}, left=0) {this.dataset=dataset;this.style={left:`${left}px`};this.handlers={};this.classList={toggle(){}};}
 append() {} remove() {} setPointerCapture() {} hasPointerCapture() {return false;}
 addEventListener(k,fn) {this.handlers[k]=fn;} removeEventListener(k) {delete this.handlers[k];}
 getBoundingClientRect() {const x=parseFloat(this.style.left);return {left:x,top:30,right:x+30,bottom:50,width:30,height:20};}
 closest() {return null;}
}
const titles=[0,1,2].map(i=>({kind:'title',sid:'s'+i,id:'s'+i,t0:1+i*5,t1:2+i*5}));
const nodes=titles.map((s,i)=>new El({layer:'titles',item:String(i)},s.t0*10));
const track=new El(), sc=new El(), slider={}, hover={};
sc.clientWidth=1280;sc.scrollWidth=2000;sc.scrollLeft=0;
track.querySelectorAll=()=>nodes; track.getBoundingClientRect=()=>({left:0,top:0});
sc.getBoundingClientRect=()=>({left:0});
const document={querySelectorAll:()=>nodes,createElement:()=>new El(),addEventListener(k,fn){this.key=fn;},removeEventListener(){this.key=null;}};
const $=s=>({'#tl-track':track,'#tl-scroll':sc,'#tl-zoom':slider,'#tl-hover':hover}[s]);
let stored={};const localStorage={getItem:k=>stored[k],setItem:(k,v)=>{stored[k]=v;}};
const state={project:{id:'p',slides:titles.map(s=>({id:s.sid,title:'Title',overlays:[]}))}};
const TL_LAYER_KINDS={titles:'title',cues:'cue',graphics:'overlay'};
TL.pid='p'; TL.zoom=10; TL.data={total:1200,fps:10,layers:{titles},segments:[{paragraphs:titles.map((s,i)=>({id:s.sid,start:i*5,duration:5,spoken:4}))}]};
tlInspector=()=>{};const tlDraw=()=>{},tlPause=()=>{};
function event(x,y=0) {return {clientX:x,clientY:y,pointerId:1,target:{closest:()=>null},preventDefault(){},stopImmediatePropagation(){},altKey:true};}
tlRestoreZoom();check(near(TL.zoom,.96),'20 minutes fitted');
TL.data.total=11;TL.zoomReady=false;tlRestoreZoom();check(TL.zoom>60,'11 seconds fitted');
for (const width of [1280,1600]) for (const total of [11,1200]) {
 sc.clientWidth=width;TL.data.total=total;tlFit();check(near(total*TL.zoom,width-128),'fit at both widths');
}
const saved=TL.zoom; TL.zoom=1;tlRestoreZoom();check(TL.zoom===saved,'per project zoom restored');
TL.pid='other';tlRestoreZoom();check(near(TL.zoom,(sc.clientWidth-128)/1200),'new project fits');
localStorage.getItem=()=>{throw Error('private');};tlRestoreZoom();
TL.zoom=10;sc.scrollLeft=100;tlWireZoom();const t=(100+600-104)/10;
sc.handlers.wheel({...event(600),ctrlKey:true,deltaY:-100,deltaMode:0});
check(near((sc.scrollLeft+600-104)/TL.zoom,t),'pointer time fixed');
let old=sc.scrollLeft;sc.handlers.wheel({...event(600),deltaX:0,deltaY:80,deltaMode:0});check(sc.scrollLeft===old+80,'plain wheel scrolls');
TL.zoom=10;TL.cur=20;old=104+TL.cur*10-sc.scrollLeft;tlZoomAt(20);check(near(104+TL.cur*20-sc.scrollLeft,old),'keyboard anchor');
tlSelect(titles[0]);tlSelect(titles[1],true);tlSelect(titles[2],true);check(TL.selections.length===3,'shift adds');
tlSelect(titles[1],true);check(TL.selections.length===2,'shift removes');
tlMarquee(event(0,25));track.handlers.pointermove(event(400,55));check(TL.selections.length===3,'marquee three titles');
track.handlers.pointerup(event(400,55));
TL.zoom=10;check(tlGroupDrag(event(10),nodes[0],titles[0]),'group drag starts');
nodes[0].onpointermove(event(20));check(nodes.every((n,i)=>parseFloat(n.style.left)===titles[i].t0*10+10),'all move equally');
document.key({key:'Escape',preventDefault(){},stopImmediatePropagation(){}});check(nodes[0].style.left==='10px','cancel restores');
check(tlGroupDelta(titles,-10)===-1 && tlGroupDelta(titles,10)===3,'shared clamp');
const patches=tlGroupPatches(titles,'move',1);check(patches.length===3 && patches.every(e=>e.patch.title_at===2),'relative patches');
check(tlGroupPatches(titles,'delete',0).every(e=>e.patch.title===''),'delete all titles');
const cues=[{kind:'cue',sid:'s0',id:'c0',cue:0},{kind:'cue',sid:'s0',id:'c2',cue:2}];
state.project.slides[0].cues={cut:[{text:'a'},{text:'b'},{text:'c'}]};
const pictureKind=()=> 'cut';
check(tlGroupPatches(cues,'delete',0)[0].patch.cues.cut[0].text==='b','cue indices delete descending');
let rejected=false;try {tlGroupPatches([0,1,2].map(cue=>({...cues[0],cue})), 'delete', 0);} catch {rejected=true;}
check(rejected,'deleting the last cue cannot silently regenerate defaults');
let calls=[]; const crypto={randomUUID:()=> 'unique-gesture'};
const api=async (url, opts)=>{calls.push({url,...opts});return state.project;};
let messages=[];
const tlMsg=m=>{messages.push(m);}; tlRefresh=async()=>{};
TL.pid=state.project.id;tlSelect(titles[0]);tlSelect(titles[1],true);tlSelect(titles[2],true);
tlGroupDrag(event(10),nodes[0],titles[0]);nodes[0].onpointermove(event(20));
check(calls.length===0,'no requests during drag');nodes[0].onpointerup(event(20));
tlInspectorQueue.then(async()=>{
 check(calls.length===1 && JSON.parse(calls[0].body).edits.length===3,'one batch on drop');
 check(calls[0].editLabel==='move 3 items' && calls[0].editGesture==='unique-gesture','undo opts');
 titles[2].t0=14; titles[2].text='Third title';
 tlGroupDrag(event(10),nodes[0],titles[0]);nodes[0].onpointerup(event(20));
 await tlInspectorQueue;
 check(calls.length===1,'zero-clamped drag does not save a no-op');
 check(messages.at(-1)==="Can't move further: ‘Third title’ is at the end of its paragraph.",'drag names limiting item');
 const graphics=titles.map((s,i)=>({...s,kind:'overlay',id:'g'+i,t0:1+i*5,t1:4+i*5,text:'Graphic '+i}));
 TL.data.layers.graphics=graphics;
 state.project.slides.forEach((s,i)=>{s.overlays=[{id:'g'+i,at:1,hold:3}];});
 graphics[2].t1=15;
 tlGroupSave(graphics,'move',.5);await tlInspectorQueue;
 check(calls.length===1 && messages.at(-1).includes('‘Graphic 2’ is at the end'),'blocked graphic move explains zero');
 graphics[2].t1=14.8;
 tlGroupSave(graphics,'move',.5);await tlInspectorQueue;
 check(calls.length===2 && JSON.parse(calls[1].body).edits.every(e=>near(e.patch.overlays[0].at,1.2)),'all graphics move by shared .20 clamp');
 check(messages.at(-1)==='Moved by 0.20 s; ‘Graphic 2’ reaches the end of its paragraph.','partial move names limit and actual delta');
 tlGroupSave(graphics,'move',-2);await tlInspectorQueue;
 check(messages.at(-1)==='Moved by -1.00 s; ‘Graphic 0’ reaches the start of its paragraph.','start clamp explains negative move');
 graphics[0].t0=0;
 tlGroupSave(graphics,'move',-.5);await tlInspectorQueue;
 check(calls.length===3 && messages.at(-1)==="Can't move further: ‘Graphic 0’ is at the start of its paragraph.",'start zero clamp skips save');
 print('ergonomics runtime passed');
}).catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'ergonomics.js'
    script.write_text(source+'\n'+harness)
    r = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert r.returncode == 0, r.stdout+r.stderr
    assert 'ergonomics runtime passed' in r.stdout

"""Timeline graphic gestures in GJS and atomic cross-paragraph undo; no browser."""
import asyncio
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest


def test_graphic_reattach_undo(monkeypatch, tmp_path):
    from app import main, store, undo
    from app.schema import Project, Slide
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    item = dict(id='g', block_id='lower_third_panel', vars={'title': 'Ada'},
                at=1.5, dur=2, position='bottom-left', by='hand')
    from app import blocks
    item['position'] = blocks.discover()['lower_third_panel']['meta']['overlay']['position'][0]
    p = Project(id='pgraphics', idea='Synthetic graphics', slides=[Slide(id='a', overlays=[item]), Slide(id='b')])
    store.save(p)
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            path = '/api/projects/pgraphics'
            batch = [{'sid': 'a', 'patch': {'overlays': []}},
                     {'sid': 'b', 'patch': {'overlays': [{**item, 'at': 1.5}]}}]
            r = await client.patch(path+'/slides-batch', json={'edits': batch},
                                   headers={'X-Edit-Label': 'move graphic', 'X-Edit-Gesture': 'g1'})
            assert r.status_code == 200
            assert not r.json()['slides'][0]['overlays']
            assert r.json()['slides'][1]['overlays'][0]['at'] == 1.5
            assert len(undo.read(store.project_dir(p.id))['states']) == 2
            assert (await client.post(path+'/undo')).json()['slides'][0]['overlays'][0]['id'] == 'g'
            assert not store.load(p.id).slides[1].overlays
            await client.post(path+'/redo')
            before = store.load(p.id).to_dict()
            batch[1]['patch']['overlays'][0]['dur'] = -1
            assert (await client.patch(path+'/slides-batch', json={'edits': batch})).status_code == 400
            assert store.load(p.id).to_dict() == before
    asyncio.run(run())


def test_graphic_commands_and_gestures(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{n}.js').read_text() for n in
                       ('edit', 'graphics', 'graphic_actions', 'graphic_gestures', 'sections'))
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);}, near=(a,b)=>Math.abs(a-b)<1e-6;
const structuredClone=v=>JSON.parse(JSON.stringify(v));
let serial=0;const crypto={randomUUID:()=>String(++serial)};
const block={ref:'lower',variables:{title:{type:'text',max_length:20}},overlay:{max_dur:10,position:['bottom']}};
tlGraphicBlocks=[block];
const state={project:{id:'p',slides:[{id:'a',overlays:[]},{id:'b',overlays:[]}]}};
const TL={pid:'p',zoom:20,cur:0,selections:[],host:{focus(){}}};
const tlParas=()=>[{id:'a',start:0,duration:5},{id:'b',start:5,duration:5}];
const tlItems=()=>state.project.slides.flatMap(s=>s.overlays.map(o=>({kind:'overlay',id:o.id,sid:s.id,
 t0:tlParas().find(q=>q.id===s.id).start+o.at,t1:Math.min(tlParas().find(q=>q.id===s.id).start+o.at+o.dur,s.id==='a'?5:10)})));
const pictureKind=()=> 'kenburns',isCut=()=>false,tlFps=()=>30,tlClock=t=>t.toFixed(2);
const tlPause=()=>{},tlRefresh=async()=>{},tlDraw=()=>{},tlMsg=m=>{messages.push(m);};
const saveSlide=async(sid,patch)=>{Object.assign(state.project.slides.find(s=>s.id===sid),patch);return true;};
const tlSeek=()=>{},openVisualEdit=()=>{};
let picker, renders=0;
const tlInsertAspect=()=> '16:9', renderBlocks=async(path,options)=>{picker=options;};
const blocksBrowser={items:[]},render=async()=>{renders++;};
let messages=[],calls=[],tlInspectorQueue=Promise.resolve();
const tlSameItem=(a,b)=>a?.id===b?.id&&a?.sid===b?.sid;
const tlItemForNode=()=>TL.selection;
const tlSelect=(s,add=false)=>{TL.selection=s;TL.selections=s?(add?[...TL.selections,s]:[s]):[];};
const api=async(url,opts)=>{calls.push({url,...opts});const next=structuredClone(state.project);
 for(const {sid,patch} of JSON.parse(opts.body).edits){if(patch.overlays.length>8)throw Error('At most 8 overlays');next.slides.find(s=>s.id===sid).overlays=patch.overlays;}return next;};
class El {
 constructor(){this.style={left:'20px',width:'38px'};this.children=[];this.offsetWidth=100;this.offsetHeight=20;this.offsetTop=22;this.handlers={};this.classList={contains:()=>false};}
 append(n){this.children.push(n);n.parent=this;} remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}
 setPointerCapture(){} hasPointerCapture(){return false;} addEventListener(k,f){this.handlers[k]=f;} removeEventListener(k){delete this.handlers[k];}
 setAttribute(){} querySelectorAll(){return this.buttons ||= [new El(),new El(),new El(),new El()];}
}
const track=new El(),sc=new El(),pic=new El();sc.clientWidth=500;sc.scrollLeft=0;
track.querySelectorAll=()=>[];
track.querySelector=()=>pic;
const $=s=>s==='#tl-scroll'?sc:track;
const document={createElement:()=>new El(),addEventListener(k,f){this.key=f;},removeEventListener(){this.key=null;}};
const hint=()=>track.children.find(n=>n.className==='tl-track-hint');
const event=x=>({clientX:x,button:0,pointerId:1,altKey:true,preventDefault(){},stopPropagation(){}});
let layerMoves=[];const tlLayerRequest=async payload=>{layerMoves.push(payload);};
const key=(k,extra={})=>({key:k,ctrlKey:true,target:{closest:()=>null},...extra});
async function run(){
 await tlGraphicDrop({block:'lower',vars:{title:'Ada'}},6.5,'names');
 check(state.project.slides[1].overlays[0].layer==='names','drop assigns destination project track');
 check(state.project.slides[1].overlays[0].at===1.5 && TL.selection.sid==='b','panel drop paragraph 2 +1.5 seconds');
 const g=TL.selection;await tlGraphicCommand('move',[g],{time:1});
 check(TL.selection.sid==='a' && state.project.slides[1].overlays.length===0,'cross paragraph reattachment');
 check(JSON.parse(calls.at(-1).body).edits.length===2 && calls.at(-1).editGesture,'one atomic undo gesture');
 state.project.slides[0].overlays[0].dur=1;tlSelect(tlItems()[0]);
 tlGraphicCommand('copy');state.project.slides[0].overlays[0].vars.title='Changed';
 await tlGraphicCommand('paste',[],6.5);
 check(tlGraphic(TL.selection).vars.title==='Ada' && tlGraphic(TL.selection).at===1.5,'detached clipboard and playhead paste');
 await tlGraphicCommand('duplicate');check(near(TL.selection.t0,7.5),'duplicate just after selection');
 const count=calls.length;TL.cur=7;
 check(tlGraphicClipboardKey(key('c')) && calls.length===count,'copy has no save');
 TL.section={};check(!tlGraphicClipboardKey(key('v')),'section wins clipboard routing');TL.section=null;
 check(!tlGraphicClipboardKey(key('d',{target:{closest:()=>({})}})),'fields ignore clipboard');
 tlSelect(tlItems()[0]);const at=TL.selection.t0;
 tlGraphicKey(key('ArrowRight',{ctrlKey:false,shiftKey:true}));await tlInspectorQueue;
 check(near(TL.selection.t0,at+10/30)&&tlGraphic(TL.selection).dur===1,'Shift arrow moves ten frames without resizing');
 const beforeResize={...TL.selection};TL.cur=TL.selection.t0+.2;
 tlGraphicKey(key('[',{ctrlKey:false}));await tlInspectorQueue;
 check(near(TL.selection.t0,TL.cur)&&near(tlGraphic(TL.selection).dur,.8),'start bracket resizes to playhead');
 TL.cur=TL.selection.t1-.2;tlGraphicKey(key(']',{ctrlKey:false}));await tlInspectorQueue;
 check(near(TL.selection.t1,TL.cur)&&near(tlGraphic(TL.selection).dur,.6),'end bracket resizes to playhead');
 tlGraphicKey(key('{',{ctrlKey:false,shiftKey:true}));await tlInspectorQueue;
 tlGraphicKey(key('}',{ctrlKey:false,shiftKey:true}));await tlInspectorQueue;
 check(near(tlGraphic(TL.selection).dur,.6+2/30),'Shift brackets expand by one frame per edge');
 await tlGraphicCommand('resize',[TL.selection],{time:beforeResize.t0,dur:1});
 tlGraphicCommand('copy',tlItems());await tlGraphicCommand('paste',[],0);
 check(TL.selections.length===3,'multi-graphic paste selects all copies');
 await tlGraphicCommand('delete');check(tlItems().length===3,'delete selected copies only');
 tlSelect(tlItems()[0]);const sel=TL.selection,node=new El(),n=calls.length;
 tlGraphicPointer(event(0),node,sel,'move');node.onpointermove(event(100));
 check(hint().textContent.includes('s ·')&&calls.length===n,'move readout on track without requests');
 node.onpointerup(event(100));await tlInspectorQueue;
 check(TL.selection.sid==='b'&&calls.length===n+1&&!hint(),'drag across paragraph saves once');
 const dest={dataset:{track:'maps'},getBoundingClientRect:()=>({top:80,bottom:110})};
 track.querySelectorAll=()=>[dest];node.closest=()=>({dataset:{track:'names'}});
 const moveLayer=y=>({...event(0),clientY:y});
 const anchorBefore=JSON.stringify(tlGraphic(TL.selection)), saveCount=calls.length;
 tlGraphicPointer(moveLayer(30),node,TL.selection,'move');node.onpointerup(moveLayer(90));
 check(layerMoves.length===1&&layerMoves[0].to==='maps'&&calls.length===saveCount,'vertical drag makes one layer move');
 check(JSON.stringify(tlGraphic(TL.selection))===anchorBefore,'vertical move preserves word anchor and timing');
 track.querySelectorAll=()=>[];
 const start=TL.selection.t0;
 tlGraphicPointer(event(0),node,TL.selection,'start');node.onpointerup(event(4));await tlInspectorQueue;
 check(near(TL.selection.t0,start+.2)&&near(tlGraphic(TL.selection).dur,.8),'left edge keeps end');
 tlGraphicPointer(event(0),node,TL.selection,'end');node.onpointerup(event(4));await tlInspectorQueue;
 check(near(tlGraphic(TL.selection).dur,1),'right edge length');
 const before=JSON.stringify(state.project),nc=calls.length;
 for(const cancel of ['escape','onpointercancel','onlostpointercapture']){
  tlGraphicPointer(event(0),node,TL.selection,'move');node.onpointermove(event(8));
  if(cancel==='escape')document.key({key:'Escape',preventDefault(){},stopImmediatePropagation(){}});else node[cancel]();
  check(!TL.drag&&!hint()&&calls.length===nc&&JSON.stringify(state.project)===before,'cancel cleans readout and never saves');
 }
 await tlGraphicCommand('split',[TL.selection],TL.selection.t0+.5);
 check(TL.selections.length===2&&TL.selections.every(s=>near(tlGraphic(s).dur,.5)),'razor splits timing only');
 const splitCount=calls.length;await tlGraphicCommand('split',[TL.selection],TL.selection.t0);
 check(calls.length===splitCount&&messages.at(-1).includes('inside'),'invalid split rejected before save');
 const next={variables:{title:{type:'text',max_length:10},wrong:{type:'number'},choice:{type:'enum',choices:['x']}}};
 const compatible=tlGraphicCompatible({variables:{title:{type:'text'},wrong:{type:'text'},choice:{type:'enum'}}},next,{title:'Keep',wrong:'text',choice:'y'});
 check(JSON.stringify(compatible)==='{"title":"Keep"}','replace carries only compatible values');
 const original=structuredClone(tlGraphic(TL.selection));
 tlGraphic(TL.selection).on='Ada';tlGraphic(TL.selection).preset={id:'old',scope:'project'};
 const replacement={...block,ref:'replacement',overlay:{max_dur:10,position:['top']}};
 blocksBrowser.items=[replacement];await tlGraphicReplace(TL.selection);
 check(picker.overlay&&picker.mode==='pick'&&picker.initialValues(replacement).title==='Changed','replacement uses shared picker and carries vars');
 await picker.onUse({block:'replacement',vars:{title:'Edited'}});
 const replaced=tlGraphic(TL.selection);
 check(replaced.at===original.at&&replaced.dur===original.dur&&replaced.on==='Ada'&&!replaced.preset&&replaced.position==='top'&&renders===1,'replace preserves timing and anchor, removes obsolete preset');
 const saved=calls.length;tlGraphicBlocks.push(replacement);replacement.overlay.max_dur=.1;
 await tlGraphicReplace(TL.selection);
 let refused=false;try{await picker.onUse({block:'replacement',vars:{title:'Edited'}});}catch{refused=true;}
 check(refused&&calls.length===saved,'replacement never shortens timing silently');
 const lane=new El();lane.offsetTop=180;
 lane.querySelectorAll=()=>[{}];
 track.querySelectorAll=s=>s.includes('data-role')?[lane]:[];
 track.querySelector=s=>s==='.tl-graphic-tools'?track.children.find(n=>n.className==='tl-graphic-tools')
  :s.includes('data-eye')?{closest:()=>lane}:pic;
 for(const scroll of [0,800]){
  sc.scrollLeft=scroll;tlGraphicTools();const tools=track.querySelector('.tl-graphic-tools');
  check(parseFloat(tools.style.top)===24&&parseFloat(tools.style.top)+tools.offsetHeight<86
    &&parseFloat(tools.style.left)>=scroll+108,'toolbar stays in reserved row above every lane and inside visible track');
 }
 TL.section={};tlGraphicTools();check(!track.querySelector('.tl-graphic-tools'),'section hides graphic toolbar');TL.section=null;
 state.project.slides[0].on_camera=true;
 const no=calls.length;await tlGraphicDrop({block:'lower',vars:{}},1);
 check(calls.length===no&&messages.at(-1).includes('picture paragraph'),'unsupported target rejected');

 // Historical overlay ids are unique only within a paragraph.
 const shared={id:'hand-lower-1.0',block_id:'lower',vars:{title:'First'},at:1,dur:2,position:'bottom',by:'hand'};
 const resetShared=()=>{
  state.project.slides=[{id:'a',overlays:[structuredClone(shared)]},
   {id:'b',overlays:[{...structuredClone(shared),vars:{title:'Second'}}]}];
  tlSelect(tlItems().find(s=>s.sid==='b'));
 };
 const firstUnchanged=()=>check(JSON.stringify(state.project.slides[0].overlays)==JSON.stringify([shared]),'other paragraph unchanged');
 resetShared();
 await tlGraphicCommand('duplicate');firstUnchanged();
 check(state.project.slides[1].overlays.length===2&&TL.selections.length===1&&TL.selection.sid==='b'
  &&TL.selection.t0===8&&tlGraphic(TL.selection).vars.title==='Second','shared id duplicates selected paragraph only');
 check(TL.selection.id.startsWith('graphic-'),'duplicate gets UUID');
 resetShared();
 await tlGraphicCommand('delete');firstUnchanged();
 check(!state.project.slides[1].overlays.length&&!TL.selections.length,'shared id deletes selected paragraph only');
 resetShared();
 await tlGraphicCommand('split',[TL.selection],7);firstUnchanged();
 check(state.project.slides[1].overlays.length===2&&TL.selections.length===2
  &&TL.selections.every(s=>s.sid==='b'&&tlGraphic(s).dur===1),'shared id split and re-selection stay in selected paragraph');
 resetShared();
 await tlGraphicCommand('move',[TL.selection],{time:7});firstUnchanged();
 check(TL.selections.length===1&&TL.selection.sid==='b'&&tlGraphic(TL.selection).at===2,'same paragraph move selects only its own graphic');
 resetShared();
 await tlGraphicCommand('move',[TL.selection],{time:2});
 check(!state.project.slides[1].overlays.length&&state.project.slides[0].overlays.length===2,'shared id move reattaches selected paragraph only');
 check(JSON.stringify(state.project.slides[0].overlays[0])===JSON.stringify(shared),'destination original remains unchanged');
 check(TL.selections.length===1&&TL.selection.sid==='a'&&TL.selection.t0===2
  &&TL.selection.id.startsWith('graphic-')&&tlGraphic(TL.selection).vars.title==='Second','reattachment resolves destination id collision and selects moved graphic');
 resetShared();
 await tlGraphicCommand('replace',[TL.selection],{block_id:'replacement',vars:{title:'Replaced'}});firstUnchanged();
 check(TL.selections.length===1&&TL.selection.sid==='b'&&tlGraphic(TL.selection).vars.title==='Replaced','shared id replacement stays in selected paragraph');
 // Inspector saves use the same paragraph-aware re-selection after refresh.
 tlGraphicSave(TL.selection,{dur:1});await tlInspectorQueue;firstUnchanged();
 check(TL.selection.sid==='b'&&tlGraphic(TL.selection).dur===1,'inspector save re-selects the same paragraph');
 TL.host.isConnected=true;
 openGraphicEdit('b',shared.id);
 check(TL.selection.sid==='b','direct graphic focus uses paragraph and id');
 TL.host.isConnected=false;
 openGraphicEdit('b',shared.id);
 check(state.graphicFocus.sid==='b'&&state.graphicFocus.id===shared.id,'deferred graphic focus retains paragraph');
 print('shared overlay id duplicate, delete, split, move, replace, save and focus passed');
 print('graphic commands, clipboard, reattachment, handles and cancellation passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'graphics.js'
    script.write_text(source+'\n'+harness)
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'graphic commands, clipboard' in result.stdout

"""Exercise section pointer/keyboard gestures in GJS, without a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_section_gestures(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{name}.js').read_text() for name in
        ('core', 'inspect', 'playback', 'ergonomics', 'layers', 'edit', 'sections'))
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);};
class El {
 constructor(dataset={}){this.dataset=dataset;this.style={left:'0px'};this.handlers={};this.classList={toggle(){},add(){}};}
 append(n){if(n?.className==='tl-section-ghost')this.ghost=n;} remove(){this.removed=true;}
 cloneNode(){const clone=new El();clone.labels=[new El(),new El()];this.clone=clone;return clone;}
 querySelectorAll(s){return s==='.tl-layer-label, em' ? this.labels||[] : [];}
 setPointerCapture(){} hasPointerCapture(){return false;} setAttribute(){}
 getBoundingClientRect(){return {left:-100};}
 addEventListener(k,f){this.handlers[k]=f;} removeEventListener(k){delete this.handlers[k];}
 closest(s){return s.includes('[data-para]')&&this.dataset.para ? this : null;}
}
const track=new El(), band=new El(), layer=new El({layer:'titles',item:'0'}), add=new El(), lane=new El();
track.querySelectorAll=s=>s.includes('[data')?[layer]:s==='.tl-lane'?[lane]:[];track.querySelector=()=>band;
const document={querySelectorAll:()=>[],createElement:()=>new El(),addEventListener(k,f){this.key=f;},removeEventListener(){this.key=null;}};
const $=s=>s==='#tl-track'?track:s==='#tl-add-sponsor'?add:null;
const state={project:{id:'p',updated_at:123,slides:[0,1,2,3].map(i=>({id:'s'+i}))}};
const crypto={randomUUID:()=> 'section-gesture'};
let calls=[];const api=async(url,opts)=>{calls.push({url,...opts});return {...state.project};};
tlPause=()=>{};tlSeek=()=>{};tlInspector=()=>{};tlSectionPaint=()=>{};tlRefresh=async()=>{};tlMsg=()=>{};
TL.pid='p';TL.zoom=10;TL.data={total:20,segments:state.project.slides.map((s,i)=>({ref:''+i,type:'picture',lead:s.id,start:i*5,duration:5,index:i,
 paragraphs:[{id:s.id,start:i*5,duration:5}]})),layers:{titles:[{kind:'title',id:'s0',sid:'s0',t0:1,t1:2}]}};
const event=(id,x,opts={})=>({button:0,pointerId:1,clientX:x+4,target:new El({para:id}),preventDefault(){},stopPropagation(){},...opts});
const finish=(x=0)=>track.handlers.pointerup(event('s1',x));
const cancel=()=>document.key({key:'Escape',preventDefault(){},stopImmediatePropagation(){}});
tlSelect(tlItems('paragraph')[0]);
tlSectionPointer(event('s2',100,{shiftKey:true}));finish(100);
check(TL.section.ids.join()==='s0,s1,s2','Shift extends clicked paragraph');
tlSectionPointer(event('s1',50));track.handlers.pointermove(event('s1',55));
check(!track.ghost&&calls.length===0,'six pixel threshold');
track.handlers.pointermove(event('s1',0));check(track.ghost,'whole-section ghost');
check(lane.clone.labels.every(n=>n.removed),'ghost strips lane headers and controls');cancel();
check(TL.section.ids.join()==='s0,s1,s2'&&calls.length===0&&!TL.drag,'Escape restores selection without save');
tlSectionSet('s1','s2');tlSectionPointer(event('s1',50));track.handlers.pointermove(event('s1',0));
check(calls.length===0,'drag never saves while moving');finish(0);
tlInspectorQueue.then(async()=>{
 check(calls.length===1&&JSON.parse(calls[0].body).to==='s0','one move on drop');
 check(JSON.parse(calls[0].body).version===123&&calls[0].editGesture==='section-gesture','version and undo gesture');
 tlSectionKey({key:'ArrowRight',altKey:true});await tlInspectorQueue;
 check(JSON.parse(calls.at(-1).body).to==='','Alt right moves one boundary');
 tlSectionKey({key:'a',metaKey:true});check(TL.section.ids.length===4,'Cmd A selects all');
 tlSectionKey({key:'Delete'});await tlInspectorQueue;
 check(JSON.parse(calls.at(-1).body).op==='delete','ripple delete');
 TL.cur=5;tlSectionKey({key:'i',target:new El()});TL.cur=15;tlSectionKey({key:'o',target:new El()});
 tlSectionKey({key:'x'});check(TL.section.ids.join()==='s1,s2','I/O snapped section');
 const ruler={closest:s=>s==='.tl-ruler'?{}:null};
 tlSectionPointer(event('',0,{target:ruler}));track.handlers.pointermove(event('',7,{target:ruler}));finish(7);
 check(TL.section.ids.join()==='s0','short ruler range stays valid');
 tlWireScrub();tlSelect(tlItems('paragraph')[0]);
 track.onpointerdown(event('s1',50,{ctrlKey:true}));track.onpointerup();
 check(TL.selections.length===2&&!TL.section,'Ctrl click adds single item');
 track.onpointerdown(event('s1',50,{metaKey:true}));track.onpointerup();
 check(TL.selections.length===1,'Cmd click removes single item');
 tlWireLayers();tlWireTiming();
 for(const modifier of ['ctrlKey','metaKey','shiftKey']){
  layer.onpointerdown(event('',0,{[modifier]:true}));check(!TL.drag,'modified lane click does not start drag');
  layer.onclick(event('',0,{[modifier]:true}));check(TL.selections.length===2,'modified title adds');
  layer.onclick(event('',0,{[modifier]:true}));check(TL.selections.length===1,'modified title removes');
 }
 print('section gestures passed');
}).catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'sections.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'section gestures passed' in result.stdout


def test_section_toolbar_scroll_clamping(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);};
class El {
 constructor(){this.style={};this.children=[];this.offsetWidth=320;}
 append(n){this.children.push(n);n.parent=this;}
 remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}
 setAttribute(){}
 querySelectorAll(s){return this.children.flatMap(n=>[...(s.includes('.'+n.className)?[n]:[]),...n.querySelectorAll(s)]);}
 querySelector(s){return s==='[data-section-delete]'?new El():this.querySelectorAll(s)[0];}
}
const track=new El(),ruler=new El(),sc={clientWidth:600,scrollLeft:0};
ruler.className='tl-ruler';track.append(ruler);
const $=s=>s==='#tl-track'?track:s==='#tl-scroll'?sc:null;
const document={createElement:()=>new El()};
const TL={zoom:10,section:{ids:['a']}};
const tlParas=()=>[{id:'a',start:80,duration:5},{id:'b',start:85,duration:5}];
tlSectionPaint();
const tools=ruler.querySelector('.tl-section-tools');
check(tools&&tools.parent===ruler,'toolbar belongs to ruler above all lanes');
const checkVisible=()=>{
 const left=104+parseFloat(tools.style.left)-sc.scrollLeft;
 check(left>=4&&left+tools.offsetWidth<=sc.clientWidth-4,'toolbar inside visible scroll area');
};
checkVisible();
sc.scrollLeft=800;sc.onscroll();checkVisible();
sc.scrollLeft=1600;sc.onscroll();checkVisible();
sc.scrollLeft=650;sc.onscroll();
check(parseFloat(tools.style.left)===800,'toolbar follows selection when it fits');
TL.section=null;tlSectionPaint();
check(!track.querySelector('.tl-section-tools'),'clearing selection removes toolbar');
print('section toolbar passed');
'''
    script = tmp_path / 'section_toolbar.js'
    script.write_text(Path('static/js/timeline/sections.js').read_text() + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'section toolbar passed' in result.stdout

"""Exercise the plain JS editor with GJS; no Node, browser, rendering or network."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_drag_runtime(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS is unavailable')
    source = Path('static/js/timeline/edit.js').read_text()
    source = Path('static/js/tabs/visuals.js').read_text().split('function pictureKindLabel')[0] + source
    harness = r'''
const structuredClone = (v) => JSON.parse(JSON.stringify(v)); // GJS lacks this browser global
function check(ok, msg) { if (!ok) throw new Error(msg); }
const near = (a,b) => Math.abs(a-b) < .00001;
check(near(tlSnap(1.24, [], 10, 6, 60, false).t, 1.2), 'frame snap');
check(tlSnap(1.24, [{start:1.3,end:1.8}], 30, 6, 60, false).t === 1.3, 'word preference');
check(tlSnap(1.24, [{start:1.3,end:1.8}], 30, 6, 60, true).t === 1.24, 'Alt');
check(tlSnap(1.24, [], 1, 6, 60, false).guide === null, 'outside tolerance');
class El {
 constructor(dataset={}, left=0, width=40) {
  this.dataset=dataset; this.style={left:`${left}px`,width:`${width}px`};
  this.classList={add(){}}; this.onclick=()=>{};
 }
 append() {} remove() {} setPointerCapture() {} hasPointerCapture() {return false;}
 getBoundingClientRect() {return {left:-100};} // scrolled track
}
const item = new El({layer:'titles',item:'0'}, 20, 40);
const later = new El({para:'b'}, 100, 40);
const gap = new El({gap:'a'}, 100, 0);
const track = new El();
track.querySelectorAll = (s) => s === '[data-layer], [data-gap]' ? [item,gap] : [item,later,gap];
const document = {createElement:()=>new El(), addEventListener(k,fn){this.key=fn;}, removeEventListener(){this.key=null;}};
const $ = () => track;
const q = {id:'a',index:0,start:0,duration:5,spoken:4,word_times:[],
 timing:{title_hold:{value:1},chapter_hold:{value:1},gap:{value:1}},effective_cues:[{kind:'title',text:'derived'}]};
const title={kind:'title',id:'a',sid:'a',t0:1,t1:3};
const TL={pid:'p',zoom:20,data:{total:10,title_exit:1,last_line_min_s:2,layers:{titles:[title]}}};
const state={project:{id:'p',style:{format:'flameboat'},slides:[{id:'a',cues:{}}]}};
let paras = [q,{id:'b'}];
const tlParas = () => paras;
const tlItems = (kind) => kind==='paragraph' ? [{kind,id:'a',sid:'a',t0:0,t1:5}] : [title];
const tlPause = () => {};
const tlSelect = (s) => {TL.selection=s;};
const tlFps = () => 10;
const tlDraw = () => {};
const tlMsg = (s) => {throw new Error(s);};
const tlRefresh = async () => {};
let saves=[];
const saveSlide = async (sid,patch) => {saves.push(patch);return {};};
let tlInspectorQueue = Promise.resolve();
function event(x, resize=false) {return {button:0,pointerId:1,clientX:x-100+104,altKey:true,
 stopPropagation(){},target:{closest:()=>resize?{}:null}};}
async function run() {
 tlWireTiming();
 item.onpointerdown(event(20)); item.onpointermove(event(28));
 check(saves.length===0,'no move save');
 item.onpointerup(event(28)); await tlInspectorQueue;
 check(saves.length===1 && near(saves[0].title_at,1.4),'one relative PATCH');
 item.onpointerdown(event(20)); item.onpointermove(event(60));
 document.key({key:'Escape',preventDefault(){},stopImmediatePropagation(){}});
 check(near(parseFloat(item.style.left),28) && saves.length===1,'Escape restores');
 item.onpointerdown(event(20,true)); item.onpointermove(event(-100,true)); item.onpointerup(event(-100,true));
 await tlInspectorQueue;
 check(saves.at(-1).title_hold===.5,'minimum hold');
 gap.onpointerdown(event(100)); gap.onpointermove(event(140));
 check(parseFloat(later.style.left)===140,'gap shifts following paragraph');
 check(saves.length===2,'gap preview is local');
 gap.onpointercancel();
 check(parseFloat(later.style.left)===100,'cancel restores gap');
 gap.onpointerdown(event(100)); gap.onpointermove(event(140)); gap.onpointerup(event(140));
 await tlInspectorQueue;
 check(saves.length===3 && saves.at(-1).gap_override===3,'gap drop');
 check(tlCuePatch({sid:'a',cue:0},.4).cues.flameboat[0].at===.4,'derived cue');
 state.project.slides[0].kind='casefile';
 check(tlCuePatch({sid:'a',cue:0},.4).cues.casefile[0].at===.4,'resolved cue kind');
 delete state.project.slides[0].kind;
 tlResetTiming(title); await tlInspectorQueue;
 check(saves.at(-1).title_at===null && saves.at(-1).title_hold===null,'reset');
 paras = [q]; // final title uses the frame spec minimum
 item.onpointerdown(event(20,true)); item.onpointerup(event(-100,true));
 await tlInspectorQueue;
 check(saves.at(-1).title_hold===2,'final title minimum');
 const chapter={kind:'chapter',id:'a',sid:'a',t0:3,t1:4};
 TL.data.layers.titles[0]=chapter;
 paras=[{id:'prev',timing:{gap:{value:3}}},q];
 tlWireTiming();
 item.onpointerdown(event(60,true)); item.onpointerup(event(40,true));
 await tlInspectorQueue;
 check(saves.at(-1).chapter_hold===2 && parseFloat(item.style.left)===40,'chapter left resize');
 print('drag runtime passed');
}
run().catch(e=>{printerr(String(e) + e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'drag.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'drag runtime passed' in result.stdout

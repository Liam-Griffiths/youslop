"""Exercise graphics pointer, keyboard and picker saves without a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_graphics_runtime(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = '\n'.join(Path(p).read_text() for p in [
        'static/js/timeline/edit.js', 'static/js/timeline/graphics.js'])
    harness = r'''
const assert = (v,m) => {if (!v) throw Error(m);};
const near = (a,b) => Math.abs(a-b) < .00001;
const hand = {id:'g1',block_id:'lower_third_panel',vars:{title:'Name'},at:1,dur:2,on:'Name',by:'auto'};
const other = {id:'g2',block_id:'lower_third_panel',at:7,dur:2,by:'hand'};
const state = {project:{id:'p',style:{format:'kenburns'},slides:[{id:'s',overlays:[hand,other]}]}};
const sel = {id:'g1',sid:'s',kind:'overlay',t0:11,t1:13};
const q = {id:'s',start:10,duration:8,spoken:7,word_times:[
  {start:12.12,end:12.12,src:'est'},{start:12.22,end:12.22,src:'tts'}],
  timing:{gap:{value:1},title_hold:{value:2},chapter_hold:{value:1}}};
const TL = {pid:'p',cur:12,zoom:100,data:{total:25,layers:{graphics:[sel]}},host:{focus(){}}};
const tlParas = () => [q], tlFps = () => 10, tlPause = () => {};
const tlSelect = s => {TL.selection=s;}, tlItems = () => [sel], tlDraw = () => {};
const tlMsg = message => {throw Error(message);};
const tlRefresh = async () => {};
let tlInspectorQueue = Promise.resolve(), calls=[];
const saveSlide = async (sid,patch) => {calls.push(patch); Object.assign(state.project.slides[0],patch);return {};};
class El {
 constructor(dataset={}) {this.dataset=dataset;this.style={left:'1100px',width:'198px'};this.classList={add(){}};this.onclick=()=>{};}
 append() {} remove() {} setPointerCapture() {} hasPointerCapture() {return false;}
 getBoundingClientRect() {return {left:0};}
}
const bar = new El({layer:'graphics',item:'0'}), track = new El();
track.querySelectorAll = () => [bar];
const $ = () => track;
const document = {createElement:() => new El(), addEventListener(k,fn){this.key=fn;},removeEventListener(){this.key=null;}};
function event(t,resize=false,alt=true) {return {button:0,pointerId:1,clientX:104+t*100,altKey:alt,
 stopPropagation(){},target:{closest:()=>resize?{}:null}};}
const isCut = () => false;
let focusSid;
const openVisualEdit = sid => {focusSid=sid;};
let options, rendered=0;
const render = async () => {rendered++;};
let blocksBrowser = {items:[{ref:'lower_third_panel',overlay:{position:['bottom_left'],max_dur:30}}]};
const renderBlocks = async (path,o) => {options=o;};
const crypto = {randomUUID:() => 'new'};
const api = async (url,opts) => {
 if (opts) {calls.push(JSON.parse(opts.body));return {};}
 return state.project;
};
async function run() {
 tlGraphicBlocks = [{ref:'lower_third_panel',overlay:{max_dur:30}}];
 tlWireTiming();
 bar.onpointerdown(event(11));bar.onpointermove(event(12));
 assert(calls.length === 0,'no PATCH during drag');
 bar.onpointerup(event(12));await tlInspectorQueue;
 assert(calls.length === 1 && near(calls[0].overlays[0].at,2),'paragraph-relative drop');
 assert(calls[0].overlays[0].on === '' && calls[0].overlays[0].by === 'hand','move clears anchor and becomes hand');
 assert(calls[0].overlays[1] === other,'other graphic preserved');
 bar.onpointerdown(event(11,true));bar.onpointerup(event(12,true));await tlInspectorQueue;
 assert(near(calls.at(-1).overlays[0].dur,3),'resize duration');
 const before = calls.length;
 bar.onpointerdown(event(11));bar.onpointermove(event(14));bar.onpointercancel();
 assert(calls.length === before,'cancel never saves');
 // Estimated word starts must not attract a graphic; precise starts do.
 bar.onpointerdown(event(11));bar.onpointerup(event(12.11,false,false));await tlInspectorQueue;
 assert(near(calls.at(-1).overlays[0].at,2.1),'estimated anchor skipped');
 bar.onpointerdown(event(11));bar.onpointerup(event(12.2,false,false));await tlInspectorQueue;
 assert(near(calls.at(-1).overlays[0].at,2.22),'precise anchor snaps');
 TL.selection = sel;
 assert(tlGraphicKey({key:'ArrowRight'}),'keyboard move handled');await tlInspectorQueue;
 assert(near(calls.at(-1).overlays[0].at,2.32),'keyboard paragraph-relative move');
 assert(tlGraphicKey({key:'ArrowRight',shiftKey:true}),'keyboard resize handled');await tlInspectorQueue;
 assert(near(calls.at(-1).overlays[0].dur,3.1),'keyboard resize duration');
 tlGraphicKey({key:'ArrowRight'}); tlGraphicKey({key:'ArrowRight'}); await tlInspectorQueue;
 assert(near(calls.at(-1).overlays[0].at,2.52),'rapid keys accumulate in save queue');
 assert(!tlGraphicKey({key:'j'}),'other shortcuts untouched');
 tlGraphicKey({key:'Delete'});await tlInspectorQueue;
 assert(state.project.slides[0].overlays.length === 1 && state.project.slides[0].overlays[0] === other,'Delete selected only');
 tlGraphicAdd();await Promise.resolve();
 assert(options.overlay && options.mode === 'pick','G uses filtered picker');
 await options.onUse({block:'lower_third_panel',vars:{title:'New'}});
 const added = calls.at(-1).overlays.at(-1);
 assert(added.at === 2 && added.by === 'hand' && added.vars.title === 'New','adds at playhead');
 assert(calls.at(-1).overlays[0].id === other.id && rendered === 1,'keeps existing and returns');
 openGraphicEdit('s','g2');
 assert(focusSid === 's' && state.graphicFocus.id === 'g2' && state.graphicFocus.pid === 'p','chip opens its graphic');
 print('graphics runtime passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'graphics.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'graphics runtime passed' in result.stdout


def test_graphic_inspector_form(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = '\n'.join(Path(p).read_text() for p in [
        'static/js/tabs/blocks_browser.js', 'static/js/timeline/graphics.js'])
    harness = r'''
const assert = (v,m) => {if (!v) throw Error(m);};
const item = {id:'g',block_id:'lower_third_panel',vars:{title:'Mine'},at:0,dur:4,position:'bottom_left',on:'Mine'};
const state = {project:{slides:[{id:'s',overlays:[item]}]}};
const sel = {id:'g',sid:'s',kind:'overlay',t0:11,t1:15};
const TL = {selection:sel,host:{focus(){}}};
const tlParas = () => [{id:'s',start:10}];
const esc = v => String(v ?? '');
let saved;
const tlSaveTiming = (s,fn) => {saved=fn();};
const nodes = {'#graphic-at':{value:'2.5'}, '#graphic-dur':{value:'5'},
 '#graphic-position':{value:'top_right'}, '#graphic-on':{value:'Mine'},
 '#graphic-delete':{}, '#graphic-status':{}, form:{}};
const body = {isConnected:true,innerHTML:'',querySelector:k => nodes[k],
 querySelectorAll:k => k === '[data-key]' ? [{dataset:{key:'title',type:'text'},value:'Edited'}] : []};
const api = async () => [{ref:'lower_third_panel',name:'Lower third',overlay:{max_dur:30,position:['bottom_left','top_right']},
 variables:{title:{type:'text',default:'Default',max_length:48}}}];
async function run() {
 await tlGraphicInspector(sel,body);
 assert(body.innerHTML.includes('Mine') && body.innerHTML.includes('Save graphic'),'existing vars and explicit save');
 nodes['#graphic-at'].oninput();
 assert(nodes['#graphic-on'].value === '', 'explicit start clears anchor');
 nodes.form.onsubmit({preventDefault(){}});
 const edited = saved.overlays[0];
 assert(edited.vars.title === 'Edited' && edited.at === 2.5 && edited.dur === 5,'typed form saves');
 assert(edited.position === 'top_right' && edited.by === 'hand' && edited.on === '', 'position and manual timing');
 nodes['#graphic-delete'].onclick();
 assert(saved.overlays.length === 0,'form deletes graphic');
 body.isConnected = false; body.innerHTML = 'detached';
 await tlGraphicInspector(sel,body);
 assert(body.innerHTML === 'detached','async load ignores removed inspector');
 print('graphics inspector passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'inspector.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'graphics inspector passed' in result.stdout

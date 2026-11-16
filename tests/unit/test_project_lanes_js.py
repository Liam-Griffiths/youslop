"""Project lane drawing and drops through GJS, without browser or render."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_project_lanes_and_drops(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{name}.js').read_text()
                       for name in ('layers', 'ergonomics', 'graphic_gestures'))
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);};
const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const item=(id,sid)=>({id,sid,kind:'overlay',text:'Name',t0:1,t1:3});
const a=item('shared','a'),b=item('shared','b');
const row=(id,role,items=[],name=id)=>({id,role,items,name,color:'cool'});
const TL={pid:'p',zoom:20,cur:6,hidden:{},collapsed:{},data:{layers:{graphics:[a,b],titles:[]},
 project_layers:[row('names','graphics',[b],'Names <quoted>'),row('voice','voice'),
 row('maps','graphics',[a]),row('base','pictures'),row('empty','titles')]}};
const state={project:{id:'p'}};
const tlClock=String,tlInsertButtons=()=>'<insert>',tlGapItems=()=>'<gaps>',tlCameraRows=()=>'<camera>';
let html=tlLayerRows('<pictures>','<voice>');
check(html.indexOf('data-track="names"')<html.indexOf('data-track="voice"')&&
 html.indexOf('data-track="voice"')<html.indexOf('data-track="maps"'),'ordered tracks across roles');
check(!html.includes('data-track="empty"'),'no empty saved role lane');
check(html.includes('Names &lt;quoted>')&&html.includes('--track-color:var(--cool)'),'escaped name and token swatch');
check(html.indexOf('data-item="1"')<html.indexOf('data-item="0"'),'shared ids keep paragraph-aware legacy indexes');
check(html.includes('<pictures><insert>')&&html.includes('<voice><gaps>')&&html.includes('<camera>'),'main-track and camera actions retained');
TL.data.project_layers=[row('captions','captions',[{id:'s:cap0',sid:'s',text:'Words',t0:0,t1:2}])];
TL.data.layers.titles=TL.data.project_layers[0].items;
html=tlLayerRows();check(html.includes('data-layer="titles" data-item="0"'),'caption inspector alias');
class El {
 constructor(dataset={}){this.dataset=dataset;this.children=[];this.style={};this.classList={add(){},toggle:(k,v)=>{this[k]=v;}};}
 append(n){this.children.push(n);} prepend(n){this.children.unshift(n);} setAttribute(k,v){this[k]=v;} querySelectorAll(){return [];}
 contains(){return false;}
 getBoundingClientRect(){return {left:0};}
}
const label=new El(),name={textContent:'Names'};
const lane=new El({track:'names',role:'graphics'});
lane.querySelector=s=>s==='.tl-layer-name'?name:label;
const addGraphic=new El(),addSponsor=new El(),track=new El(),pic=new El();
let lanes=[lane],nodes=[],selected,dropped;
track.querySelectorAll=s=>s==='.tl-lane'||s==='[data-role="graphics"]'?lanes:nodes;
track.querySelector=()=>pic;
const $=s=>({'#tl-track':track,'#tl-add-graphic':addGraphic,'#tl-add-sponsor':addSponsor}[s]);
const document={createElement:()=>new El()};
const tlPause=()=>{},tlGraphicAdd=()=>{},tlSponsorAdd=()=>{};
const tlSelect=s=>{selected=s;},tlSeek=()=>{};
tlWireLaneCollapse();
let collapse=label.children[0];collapse.onclick({stopPropagation(){}});
check(TL.collapsed.names&&lane.collapsed,'collapse stored by layer id');
name.textContent='Renamed';tlWireLaneCollapse();collapse=label.children[0];
check(lane.collapsed&&collapse['aria-label']==='Expand Renamed','renaming retains collapse state');
TL.data.layers.graphics=[a,b];
const node=new El({layer:'graphics',item:'1'});nodes=[node];
tlWireLayers();node.onclick({stopPropagation(){}});
check(selected===b,'named lane selects original role item');
check(typeof addSponsor.onclick==='function','Add sponsor wired without sponsor lane');
const tlInsertClearGhost=()=>{},tlGraphicTarget=t=>({sid:'s',at:t});
let tlGraphicBlocks=[{ref:'lower',overlay:{max_dur:10}}];
const tlGraphicDrop=(payload,t,layer)=>{dropped={payload,t,layer};};
const payload={kind:'block',block:'lower'};
const event={clientX:144,dataTransfer:{},preventDefault(){},stopPropagation(){}};
nodes=[];
TL.insertDrag={pid:'p',payload};tlWireGraphics();lane.ondragover(event);lane.ondrop(event);
check(dropped.layer==='names'&&dropped.t===2,'drop resolves track id and time by role');
lanes=[];TL.insertDrag={pid:'p',payload};tlWireGraphics();
addGraphic.ondragover(event);addGraphic.ondrop(event);
check(dropped.layer===''&&dropped.t===6,'missing Graphics lane retains drop at playhead');
check(pic.children.length===1,'fallback drop ghost uses main-track coordinates');
TL.insertDrag={pid:'other',payload};dropped=null;addGraphic.ondragover(event);addGraphic.ondrop(event);
check(!dropped,'other project drag rejected');
print('project lane order, selection, collapse, captions, actions and drops passed');
'''
    script = tmp_path / 'project-lanes.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'project lane order' in result.stdout

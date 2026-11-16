"""Narrow timeline targets and shared drag visibility; GJS, no browser/render."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def test_reserved_ruler_does_not_depend_on_selection():
    css = Path('static/styles.css').read_text()
    heights = re.findall(r'\.tl-ruler\s*\{[^}]*height:\s*(\d+)px', css)
    assert heights == ['56']  # ticks plus one command row are always reserved.
    assert '.tl-ruler:has(.tl-section-tools)' not in css
    assert re.search(r'\.tl-track\.dragging \.tl-insert-plus\s*\{[^}]*visibility: hidden;[^}]*pointer-events: none;', css)


def test_narrow_graphic_move_and_drag_visibility(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = Path('static/js/timeline/core.js').read_text().split('const tlFps')[0]
    source += '\n' + '\n'.join(Path(f'static/js/timeline/{name}.js').read_text()
                                for name in ('edit', 'sections', 'graphic_gestures'))
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);};
class El {
 constructor(width=null){this.style={left:'6.25px',width:width===null?'':`${width}px`};this.dataset={};this.children=[];
  this.classes=new Set();this.classList={add:k=>this.classes.add(k),toggle:(k,on)=>on?this.classes.add(k):this.classes.delete(k)};}
 append(n){this.children.push(n);n.parent=this;} remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}
 setPointerCapture(){} hasPointerCapture(){return false;}
 closest(s){return s==='[data-graphic-edge]'&&this.dataset.graphicEdge?this:null;}
 getBoundingClientRect(){return {top:100,bottom:160};}
 get offsetWidth(){return parseFloat(this.style.width)||100;}
}
const track=new El(),lane=new El(),node=new El(25),sc={scrollLeft:0,clientWidth:600,addEventListener(){},removeEventListener(){}};
track.querySelectorAll=s=>s.includes('[data-role=')?[lane]:[node];
const $=s=>s==='#tl-scroll'?sc:s==='#tl-track'?track:null;
const document={createElement:()=>new El(),addEventListener(){},removeEventListener(){}};
const state={project:{id:'p'}};
const sel={kind:'overlay',id:'g',sid:'s',t0:1,t1:5},item={dur:4};
const tlItemForNode=()=>sel,tlGroupDrag=()=>false,tlPause=()=>{},tlSelect=()=>{};
const tlGraphic=()=>item,tlGraphicTarget=()=>({sid:'s'}),tlFps=()=>30,tlClock=String;
const tlParas=()=>[{id:'s',start:0,duration:20,word_times:[]}];
let saves=[];
const tlGraphicCommand=(action,items,patch)=>saves.push({action,patch});
TL.pid='p';TL.zoom=6.25;
const event=x=>({clientX:x,clientY:0,button:0,pointerId:1,altKey:true,target:node,preventDefault(){},stopPropagation(){}});
for(const width of [40,39,25,16,15]){
 node.children=[];node.style.width=`${width}px`;tlWireGraphics();
 check(node.children.length===(width<16?0:2),`handles at ${width}px`);
 if(width>=16)check(node.children.every(h=>(h.style.width||'8px')===(width<40?'4px':'8px')),`handle width at ${width}px`);
 if(width===25){
  node.onpointerdown(event(0));node.onpointermove(event(6.25));
  check(TL.drag?.graphic&&track.classes.has('dragging')&&!saves.length,'middle starts move and hides plus buttons without saving');
  node.onpointerup(event(6.25));
  check(saves.length===1&&saves[0].action==='move'&&saves[0].patch.time===2&&item.dur===4,'middle moves 25px graphic without resizing');
  check(!TL.drag&&!track.classes.has('dragging'),'drop restores plus visibility');
 }
}
for(const drag of [{section:true},{trim:true},{marquee:true},{mediaBox:true}]){
 TL.drag=drag;check(track.classes.has('dragging'),'every drag hides plus buttons');
 TL.drag=null;check(!track.classes.has('dragging'),'clear drag restores buttons');
}
print('narrow targets and drag visibility passed');
'''
    script = tmp_path / 'polish.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'narrow targets and drag visibility passed' in result.stdout

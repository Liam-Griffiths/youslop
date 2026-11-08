"""Edit hosting and shortcut regressions; GJS, no browser/render/model calls."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_edit_lifecycle_and_shortcuts(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    scripts = ['static/js/palette.js', 'static/js/shell.js', 'static/js/timeline/draw.js', 'static/js/timeline/layers.js', 'static/js/timeline/graphics.js']
    source = '\n'.join(Path(p).read_text() for p in scripts)
    # Exercise the actual global keyboard dispatcher with all its suppression guards.
    boot = Path('static/js/boot.js').read_text().split('\n\nroute();')[0]
    harness = r'''
function check(ok, msg) { if (!ok) throw new Error(msg); }
const shell = {append(el){el.parent=this;}, classList:{remove(){}}};
const inspector = {replaceChildren(){this.empty=true;}};
const host = {isConnected:true,focus(){}};
let modal=null, focused={isConnected:true,focus(){restored++;}}, restored=0, dialog, button;
const handlers=[];
const document={
 activeElement:focused, documentElement:{dataset:{}},
 body:{contains:el=>el.isConnected, append(w){modal=w;}},
 querySelector:s=>s==='.modal'?modal:null,
 addEventListener:(kind,fn,capture)=>handlers.push({fn,capture}),
 removeEventListener:(kind,fn)=>handlers.splice(handlers.findIndex(h=>h.fn===fn),1),
 createElement:()=>{
  button={focus(){focused=this;}};
  dialog={querySelector:()=>button,remove(){modal=null;}};
  return dialog;
 }
};
const $=s=>s==='.app-shell'?shell:s==='#inspector'?inspector:null;
const window={addEventListener(){}};
const localStorage={getItem:()=>''};
const route=()=>{};
const TL={data:{total:100},host,cur:12,selection:null};
const state={tab:'edit',project:{}};
let pauses=0, seeks=[], splits=0, selection=1;
const tlPause=()=>pauses++;
const tlSeek=(t,opts)=>seeks.push({t,opts});
const tlSelect=s=>selection=s;
const tlSplitHere=()=>splits++;
const esc=s=>String(s);
const tlClock=t=>String(t);
'''
    checks = r'''
state.project.style={format:'essay'};
TL.hidden={}; TL.zoom=10;
TL.data.layers={titles:[{t0:1,t1:3,text:'Essay words',kind:'title'}]};
let lanes=tlLayerRows();
check(lanes.indexOf('>sponsors') < lanes.indexOf('</button>titles'),'sponsor lane before titles');
check(lanes.indexOf('Essay words') > lanes.indexOf('</button>captions'),'essay spans in captions lane');
check((lanes.match(/data-layer="titles"/g)||[]).length===1,'caption span is not duplicated');
state.project.style.format='kenburns'; lanes=tlLayerRows();
check(lanes.indexOf('Essay words') < lanes.indexOf('</button>captions'),'ordinary titles stay in titles lane');
restoreShellInspector();
check(inspector.parent===shell && inspector.empty,'shell slot survives repaint');
tlPreviewBit();
check(pauses===1 && seeks[0].t===12 && seeks[0].opts.ensure,'preview current segment explicitly');
TL.selection={t0:44}; tlPreviewBit();
check(seeks.length===2 && seeks[1].t===44,'preview selected span');
TL.host.isConnected=false; tlPreviewBit();
check(seeks.length===2,'detached edit cannot request preview'); TL.host.isConnected=true;
function key(k, target={tagName:'DIV'}, extra={}) {
 const e={key:k,target,preventDefault(){this.prevented=true;},stopPropagation(){},...extra};
 for(const h of [...handlers].reverse()) {if(h.capture) h.fn(e);}
 if(!e.prevented) for(const h of [...handlers]) {if(!h.capture) h.fn(e);}
 return e;
}
key('?',{tagName:'INPUT'}); check(!modal,'typing ? in input');
key('?',{tagName:'DIV',isContentEditable:true}); check(!modal,'typing ? in editable');
key('?',undefined,{ctrlKey:true}); check(!modal,'modified ?');
key('?'); check(modal,'? opens sheet');
check(modal.innerHTML.includes('I / O') && modal.innerHTML.includes('Shift + C'),'camera and chapter help');
key('s'); check(splits===0,'modal suppresses editing');
key('Tab'); check(focused===button,'sheet retains keyboard focus');
key('Escape'); check(!modal && restored===1 && selection===1,'Escape closes sheet without clearing selection');
key('s'); check(splits===1,'split shortcut retained');
key('s',{tagName:'TEXTAREA'}); check(splits===1,'typing s does not split');
key('Escape'); check(selection===null,'Escape still clears selection');
// Compile every classic script too: catches syntax errors without executing app startup.
'''
    checks += '\n'.join('new Function(' + __import__('json').dumps(p.read_text()) + ');'
                        for p in Path('static/js').rglob('*.js'))
    path = tmp_path / 'edit.js'
    path.write_text(harness + source + '\n' + boot + '\n' + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

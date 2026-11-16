"""Exercise source tiles and queued placement in GJS without network or a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_archive_and_footage_source_events(tmp_path):
    if not (gjs := shutil.which('gjs')):
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{name}.js').read_text()
                       for name in ('source_panel', 'insert_sources'))
    harness = r'''
const check=(v,m)=>{if(!v) throw Error(m);};
const structuredClone=v=>JSON.parse(JSON.stringify(v));
const TL={pid:'p',selection:{kind:'picture',sid:'held'},selections:[{}]};
const state={project:{id:'p',picture_runs:[['lead','held']],slides:[
  {id:'lead',candidates:[{id:'old',title:'Old archive',provider:'commons'}]}, {id:'held'},
  {id:'insert',insert:{kind:'card',seconds:4}}]}};
const esc=String, thumbUrl=c=>'/thumb/'+c.id, notices=[], calls=[];
const toast=m=>notices.push(m), tlPause=()=>{}, crypto={randomUUID:()=> 'gesture'};
const tlInsertClearGhost=()=>{};
let tlInspectorQueue=Promise.resolve(), locked=false, refreshed=0, inspected=0;
const tlCanEdit=()=>!locked, tlRefresh=async()=>{refreshed++;}, tlInspector=()=>{inspected++;};
const tools={querySelector:()=>({})}, status={}, use={};
let focused;
const grid={querySelectorAll(){
  const count=(this.innerHTML.match(/data-source=/g)||[]).length;
  if(this.buttons?.length!==count) this.buttons=Array.from({length:count},(_,i)=>({dataset:{source:String(i)},
    setAttribute(){},focus(){focused=i;}}));
  return this.buttons;
}};
const panel={querySelector:s=>({'[data-use]':use,'[data-source-tools]':tools,
  '[data-source-grid]':grid,'[data-source-status]':status})[s], querySelectorAll:()=>[]};
const $=s=>s==='#tl-sources'?panel:{focus(){focused='query';}};
const document={querySelectorAll:()=>[]};
let release;
const api=async(url,opts)=>{
  calls.push({url,...opts});
  if(url.endsWith('/search')) {
    if(release) await new Promise(r=>{release=r;});
    return {slide:{candidates:[{id:'new',title:'Station archive',provider:'commons',license:'CC0'}]},
      results:[{id:'new',title:'Station archive',provider:'commons',license:'CC0'}]};
  }
  return structuredClone(state.project);
};
async function run(){
  tlSourceView={pid:'p',tab:'Search',items:[],query:'station',choice:null};
  tlSourcesPaint();
  check(calls.length===0 && grid.buttons.length===1,'paint reads stored candidates without search');
  check(grid.buttons[0].draggable,'archive is draggable');
  await tlSourceSearch();
  check(calls.length===1 && calls[0].url.endsWith('/slides/lead/search'),'held selection searches lead');
  check(JSON.parse(calls[0].body).query==='station','editable query sent');
  check(grid.innerHTML.includes('Station archive') && grid.innerHTML.includes('CC0'),'embedded result and licence');
  check(grid.buttons[0].draggable && status.textContent.includes('1 results'),'results ready to drag');
  grid.buttons[0].onclick();
  check(tlSourceView.choice.candidate_id==='new' && tlSourceView.choice.source_slide==='lead','owned candidate payload');
  const transfer={setData(){}};
  grid.buttons[0].ondragstart({dataTransfer:transfer});
  check(TL.insertDrag.pid==='p' && TL.insertDrag.payload.candidate_id==='new','archive drag uses placement payload');
  await grid.buttons[0].ondblclick();
  check(calls.at(-1).url.endsWith('/held/picture-source') && calls.at(-1).editGesture==='gesture','double click undoable replacement');
  check(refreshed===1,'placement refreshes timeline without render');
  grid.buttons[0].ondragend();check(TL.insertDrag===null,'drag cleanup');
  const clip={kind:'clip',shoot_id:'shoot',source_id:'source',in_s:2,out_s:6};
  await tlSourceUse(clip,{kind:'picture',sid:'insert'});
  check(calls.at(-1).url.endsWith('/insert/picture-source') && JSON.parse(calls.at(-1).body).kind==='clip','footage replaces existing insert');
  let unblock;tlInspectorQueue=new Promise(r=>unblock=r);
  const count=calls.length, pending=tlSourceUse(clip); locked=true; unblock();await pending;
  check(calls.length===count,'lock rechecked after queued saves'); locked=false;
  tlSourceView.query='';await tlSourceSearch();
  check(calls.length===count && focused==='query','empty query never searches');
  tlSourceView.query='station';release=true;
  const search=tlSourceSearch();await Promise.resolve();await Promise.resolve();
  TL.pid='other';state.project={id:'other',slides:[]};release();await search;
  check(state.project.slides.length===0,'late search never changes another project');
  const buttons=Array.from({length:3},(_,i)=>({dataset:{source:String(i)},focus(){focused=i;}}));
  const box={querySelectorAll:()=>buttons};
  tlInsertSourceList(box,buttons.map((b,i)=>({label:String(i),payload:clip})),()=>{});
  buttons[0].onkeydown({key:'ArrowDown',preventDefault(){}});check(focused===2,'arrow grid navigation');
  buttons[2].onkeydown({key:'Home',preventDefault(){}});check(focused===0,'Home grid navigation');
  print('archive tiles, footage replacement, guards and keyboard passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    path = tmp_path / 'composing.js'
    path.write_text(source + '\n' + harness)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

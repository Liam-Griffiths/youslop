"""Migrated dialog lifecycle and explicit shot solving, without a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_dialog_routes_refresh_and_explicit_solve(tmp_path):
    if not (gjs := shutil.which('gjs')):
        pytest.skip('GJS unavailable')
    source = Path('static/js/tabs/picture_tools.js').read_text()
    stage = Path('static/js/tabs/stage.js').read_text()
    source += stage[stage.index('async function stageEdit('):stage.index('// The preview:')]
    harness = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);}, nodes={};
const $=s=>nodes[s] || null, esc=String;
const state={project:{id:'p',title:'Original'},stage:'edit',tab:'edit',subtab:'cast'};
let castPaints=0, stagePaints=0, solves=0, focused=0, renders=0;
const tlPause=()=>{}, toast=msg=>{throw Error(msg);}, stageSolve=()=>solves++;
const paintCast=async()=>{castPaints++;nodes['#edit-stage-tools'].innerHTML=state.project.title;};
const paintStage=async()=>{stagePaints++;nodes['#edit-stage-tools'].innerHTML='Shot checks';};
const render=async()=>{renders++;await editToolsRoute();};
const api=async(path,opts)=>{check(path.endsWith('/stage/s1') && opts.method==='PATCH','shot patch');return {...state.project,title:'Changed'};};
const document={activeElement:{isConnected:true,focus(){focused++;}},
  body:{appendChild(wrap){nodes['#edit-stage-tools']={closest:()=>wrap};}},
  createElement(){
    const button={focus(){}}, wrap={dataset:{},setAttribute(){},
      querySelector(){return button;},remove(){delete nodes['#edit-stage-tools'];}};
    return wrap;
  }};
async function run(){
  await editToolsRoute();
  check(castPaints===1 && nodes['#edit-stage-tools'].innerHTML==='Original','legacy Cast link opens in Edit');
  state.project={id:'p',title:'Updated'};await editToolsRoute();
  check(castPaints===2 && nodes['#edit-stage-tools'].innerHTML==='Updated','saved cast repaints its dialog');
  nodes['#edit-stage-tools'].closest().querySelector().onclick();
  check(!nodes['#edit-stage-tools'] && focused===1,'close restores focus');
  await editToolsRoute();check(!nodes['#edit-stage-tools'],'closed tools stay closed during repaint');
  state.subtab='stage';await editToolsRoute();
  check(stagePaints===1 && state.tab==='edit','legacy Stage link stays in Edit');
  await stageEdit('s1',{intent:{move:'static'}});
  check(renders===1 && solves===0 && stagePaints===2,'intent edit requires explicit Solve');
  state.tab='shots';state.stage='script';await editToolsRoute();
  check(!nodes['#edit-stage-tools'],'leaving Edit removes its tools');
  print('dialog routes, refresh, focus and explicit solving passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'edit-picture-tools.js'
    script.write_text(source + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

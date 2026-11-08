"""Command dispatch with GJS; no browser or production work."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_command_registry_and_shortcuts(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    setup = r'''
function check(ok, msg) { if (!ok) throw new Error(msg); }
let keyboard, route, previews=0, jobs=0, starts=0, focused=0;
const document={addEventListener:(name, fn)=>{keyboard=fn;}};
const state={project:null}, TL={data:{},host:{isConnected:true}};
const go=hash=>route=hash, openJobs=()=>jobs++, tlPreviewBit=()=>previews++;
const location={hash:'#/'}, $=()=>({focus:()=>focused++});
const homeStart=mode=>{check(mode==='idea','new project uses existing start'); starts++;};
'''
    source = '\n'.join(Path(p).read_text() for p in
                       ('static/js/palette.js', 'static/js/shell.js'))
    checks = r'''
const visible=()=>[...commands.values()].filter(c=>!c.when || c.when());
check(!visible().some(c=>c.group==='Project stages'),'project routes hidden on home');
for(const [id, hash] of [['home','#/'],['library','#/library'],['channels','#/channels'],['settings','#/settings']]) {
 commands.get('route-'+id).run(); check(route===hash,'screen route '+id);
}
state.project={id:'p-test'};
check(visible().filter(c=>c.group==='Project stages').length===6,'all six stages');
for(const [id] of STAGES) {commands.get('stage-'+id).run(); check(route==='#/p/p-test/'+id,'stage '+id);}
check(!visible().some(c=>c.id==='preview-section'),'preview hidden outside Edit');
state.stage='edit'; check(visible().some(c=>c.id==='preview-section'),'preview available in Edit');
commands.get('preview-section').run(); check(previews===1,'one existing section preview action');
TL.host.isConnected=false; check(!visible().some(c=>c.id==='preview-section'),'preview hidden for detached Edit');
commands.get('jobs').run(); check(jobs===1,'jobs action');
commands.get('new-project').run(); check(starts===1 && focused===1,'new project focuses start');
check(commandScore('Review & publish','rvpub')>=0,'subsequence matching');
check(commandScore('Home','xyz')===-1,'unmatched command excluded');
let opens=0;
openPalette=()=>opens++;
for(const modifier of ['ctrlKey','metaKey']) {
 let prevented=false, stopped=false;
 keyboard({key:'K',[modifier]:true,preventDefault(){prevented=true;},stopImmediatePropagation(){stopped=true;}});
 check(prevented && stopped,'shortcut consumed');
}
check(opens===2,'both command shortcuts');
'''
    path = tmp_path / 'palette.js'
    path.write_text(setup + source + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

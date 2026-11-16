"""Project shell actions, route changes and escaped full titles without a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_project_bar_actions_and_title(tmp_path):
    if not (gjs := shutil.which('gjs')):
        pytest.skip('GJS unavailable')
    setup = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const nodes={}, $=selector=>nodes[selector] ||= {innerHTML:''};
const document={addEventListener(){}}, registerCommand=()=>{};
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const FORMAT_INFO=[{key:'essay',label:'Essay'}];
const title='A long "title" <with markup> '+ 'many words '.repeat(30);
const state={project:{id:'p1',title,idea:'Idea',channel_id:'c1',style:{format:'essay'}},
 channels:[{id:'c1',name:'The "channel"'}],stageStates:{pid:'p1',items:[{id:'script',status:'todo'}]}};
'''
    checks = r'''
for(const [stage] of STAGES) {
 state.stage=stage;state.tab=stageTab(stage);paintProjectShell();
 const bar=nodes['#project-bar'].innerHTML, more=nodes['#project-more-actions'].innerHTML;
 check(bar.includes(`title="${esc(title)}"`) && bar.includes(`/ ${esc(title)}</span>`),'full escaped title and tooltip '+stage);
 check(bar.includes('title="The &quot;channel&quot; · Essay · 16:9"'),'metadata tooltip '+stage);
 for(const action of ['undo','redo']) check(bar.includes(`restoreProjectEdit('${action}')`),'history preserved '+stage);
 check(!bar.includes('openMicPanel') && !bar.includes('setNarrator'),'no duplicate Voice controls '+stage);
 check((bar.match(/class="btn primary"/g)||[]).length===(stage==='publish'?0:1),'one shell Next outside Publish '+stage);
 check(more.includes('tlPreviewBit()')===(stage==='edit'),'More clears between stages '+stage);
 if(stage==='edit') check(bar.includes('project-secondary') && more===bar.match(/<button[^>]*project-secondary[^>]*>.*?<\/button>/)[0],'same preview action in bar and More');
}
state.project.title='';state.project.idea=title;state.stage='voice';paintProjectShell();
check(nodes['#project-bar'].innerHTML.includes(`title="${esc(title)}"`),'fallback idea is full and escaped');
print('six stage bars: history, Next, More, Voice deduplication and title tooltips passed');
'''
    path = tmp_path / 'project-bar.js'
    path.write_text(setup + Path('static/js/shell.js').read_text() + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

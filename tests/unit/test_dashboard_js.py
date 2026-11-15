"""Dashboard action targets and legacy data defaults without a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_dashboard_content_and_actions(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = Path('static/js/tabs/dashboard.js').read_text()
    setup = r'''
const STAGES = [['dashboard','Dashboard'],['script','Script'],['voice','Voice'],['edit','Edit'],['publish','Publish']];
const state = {project:{id:'p',idea:'A fixture',style:{format:'essay'},slides:[]}};
const body = {}, $ = () => body, FORMAT_INFO = [], fmtTime = s => s+'s';
const esc = s => String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');
function check(ok, message) { if (!ok) throw Error(message); }
'''
    checks = r'''
paintDashboard();
check(!body.innerHTML.includes('Recent activity'),'hide empty activity');
check((body.innerHTML.match(/class="dashboard-card"/g) || []).length === 4,'four work stages');
check(!body.innerHTML.includes('View progress'),'no dashboard self card');
check(body.innerHTML.includes('disabled>Drop notes, pictures or clips here'),'bin disabled');
const p = state.project;
p.slides = [{narration:'<first>',take:{path:'take.wav'}},{narration:'Second'}];
p.outline = {hook:{first_line:'The hook'}};
p.log = Array.from({length:10}, (_, i)=>'Activity '+i);
state.stageStates = {pid:'p',items:[{id:'edit',reason:'1 of 3 pictures',pictures_done:1,pictures_total:3}]};
paintDashboard();
for (const [label, route] of [['Open script','script'],['Record 1 paragraph','voice'],['Fill 2 pictures','edit/pictures'],['Render','publish']]) {
 check(body.innerHTML.includes(`href="#/p/p/${route}">${label}</a>`),'action '+label);
}
check(body.innerHTML.includes('The hook') && body.innerHTML.includes('&lt;first&gt;'),'hook and escaped paragraph');
check(!body.innerHTML.includes('Activity 1</li>') && body.innerHTML.includes('Activity 2</li>'),'last eight activities');
p.outline.hook.first_line = '  <first>  ';
paintDashboard();
check(!body.innerHTML.includes('<h3>'),'omit repeated hook heading');
check((body.innerHTML.match(/&lt;first&gt;/g) || []).length === 1,'first paragraph appears once');
state.channels = [{id:'channel', name:'Under the Street'}];
p.channel_id = 'channel';
paintDashboard();
check(body.innerHTML.includes('Under the Street'),'channel name');
state.stageStates.pid = 'other';
paintDashboard();
check(!body.innerHTML.includes('Fill 2 pictures'),'ignore previous project readiness');
'''
    path = tmp_path / 'dashboard.js'
    path.write_text(setup + source + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_dashboard_direct_entry_loads_channel_and_next_stage(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    core = Path('static/js/core.js').read_text()
    loader = core.split('async function ensureChannelsLoaded() {', 1)[1].split('// ----------------------------------------------------------------- settings', 1)[0]
    project_route = core.split('} else if (proj) {', 1)[1].split('} else if (chan) {', 1)[0]
    setup = r'''
const state = {stage:'dashboard', thumbStyles:[], boardTemplates:[], cuts:[]};
const nodes = {}, $ = selector => nodes[selector] ||= {};
const document = {addEventListener(){}};
const registerCommand = () => {}, paintSidebar = () => {};
const esc = String, FORMAT_INFO = [], view = {}, loadingLine = () => 'Loading';
let stageFetches = 0;
const project = {id:'p', channel_id:'c', title:'Episode', idea:'Idea', style:{format:'essay'}, slides:[]};
const rows = ['dashboard','script','voice','edit','publish'].map(id => ({id,status:id==='publish'?'todo':'ready'}));
async function api(path) {
 if (path === '/api/channels') return [{id:'c',name:'Under the Street'}];
 if (path === '/api/projects/p') return project;
 if (path === '/openapi.json') return {paths:{'/api/projects/{pid}/stages':{}}};
 if (path === '/api/projects/p/stages') { stageFetches++; return rows; }
 throw Error('Unexpected API call '+path);
}
function check(ok, message) { if (!ok) throw Error(message); }
function paintDashboard() {}
async function render() { paintProjectShell(); }
'''
    checks = r'''
async function run() {
 await projectEntry(['','p','dashboard']);
 check(nodes['#project-bar'].innerHTML.includes('Under the Street'),'direct entry loads channel');
 check(nodes['#project-bar'].innerHTML.includes('href="#/p/p/publish">Next: Publish'),'first unfinished stage');
 rows[2].status = 'warn';
 await loadStageStates(project);
 check(nodes['#project-bar'].innerHTML.includes('href="#/p/p/voice">Next: Voice'),'refresh next action after readiness changes');
 rows.forEach(r => r.status = 'ready');
 await loadStageStates(project);
 check(!nodes['#project-bar'].innerHTML.includes('Next:'),'no unfinished stage');
 state.stageStates.pid = 'other';
 paintProjectShell();
 check(!nodes['#project-bar'].innerHTML.includes('Next:'),'ignore stale readiness');
 state.stage = 'script';
 paintProjectShell();
 check(nodes['#project-bar'].innerHTML.includes('Next: Voice'),'other stages keep sequential action');
 check(stageFetches === 3,'readiness fetched');
}
run().catch(e => { printerr(e.stack); imports.system.exit(1); });
'''
    source = Path('static/js/shell.js').read_text()
    path = tmp_path / 'dashboard-entry.js'
    path.write_text(setup + source + 'async function ensureChannelsLoaded() {' + loader
                    + 'async function projectEntry(proj) {' + project_route + '}' + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

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
function paintBin() {}
'''
    checks = r'''
paintDashboard();
check(!body.innerHTML.includes('Recent activity'),'hide empty activity');
check((body.innerHTML.match(/class="dashboard-card"/g) || []).length === 4,'four work stages');
check(!body.innerHTML.includes('View progress'),'no dashboard self card');
check(body.innerHTML.includes('id="project-bin"'),'bin region');
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


def test_bin_filters_labels_paste_and_drop(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    setup = r'''
const events={}, nodes={}, writes=[];
const document={addEventListener:(name, fn)=>events[name]=fn, querySelector:()=>null, getElementById:id=>nodes['#'+id]};
const $=id=>nodes[id] ||= {querySelectorAll:()=>[], setAttribute(){}, contains:()=>false, focus(){}};
const state={project:{id:'p'}, stage:'dashboard'}, esc=String, fmtTime=String;
const crypto={randomUUID:()=>String(writes.length)}, toast=message=>{throw Error(message)};
class FormData { constructor(){this.files=[];} append(key, file){this.files.push(file);} }
async function api(path, opts) {
 writes.push([path,opts]);
 const patch=opts.body instanceof FormData?{}:JSON.parse(opts.body || '{}');
 if (path.endsWith('/selection')) {
   if (patch.action==='toggle') patch.action=binView.items.filter(i=>patch.ids.includes(i.id)).every(i=>i.labels.includes(patch.label))?'remove':'add';
   return {items:binView.items.map(i=>patch.ids.includes(i.id)?{...i, labels:patch.action==='add'?[...new Set([...i.labels,patch.label])]:i.labels.filter(l=>l!==patch.label)}:i), labels:[...new Set([...binView.labels,patch.label])]};
 }
 return {items:binView.items, labels:binView.labels};
}
function check(ok, message){if(!ok) throw Error(message);}
'''
    checks = r'''
(async()=>{
 binView={...binInitial('p'),items:['n','b','c'].map(id=>({id,kind:'note',title:'Station '+id,note:'Research text',labels:[],used_in:[]})),labels:['Street'],selected:['n']};
 binShell();
 check(nodes['#bin-grid'].innerHTML.includes('Station'),'grid title');
 $('#bin-view-list').onclick();
 check(binView.list && nodes['#bin-grid'].className.includes('bin-list'),'switch to list');
 $('#bin-view-grid').onclick();
 check(!binView.list && nodes['#bin-grid'].className==='bin-grid','switch to grid');
 $('#bin-title').oninput({target:{value:'Draft title'}}); $('#bin-note').oninput({target:{value:'Edited note'}});
 await binToggleLabel(0);
 check(JSON.parse(writes[0][1].body).label==='Street','number label');
 check(binView.items[0].labels[0]==='Street','saved label');
 check(nodes['#bin-panel'].innerHTML.includes('Draft title') && nodes['#bin-panel'].innerHTML.includes('Edited note'),'draft survives label write');
 const visible=['n','b','c'];
 binSelect('n',{},visible); binSelect('c',{shiftKey:true},visible);
 check(binView.selected.length===3,'shift range');
 binSelect('b',{metaKey:true},visible);
 check(binView.selected.join(',')==='n,c','meta toggle');
 binSelect('b',{ctrlKey:true},visible);
 check(binView.selected.length===3,'ctrl toggle');
 binView.labelText='Typed'; await binTypedLabel('add');
 check(binView.items.every(i=>i.labels.includes('Typed')),'typed bulk add');
 await binTypedLabel('remove');
 check(binView.items.every(i=>!i.labels.includes('Typed')),'typed bulk remove');
 check(binView.items[0].title==='Station n','label writes do not save draft titles');
 const keyboard={target:{closest:()=>null},preventDefault(){}, key:'1'};
 events.keydown(keyboard); await binWrites;
 check(binView.items.every(i=>i.labels.includes('Street')),'number fills mixed selection');
 events.keydown(keyboard); await binWrites;
 check(binView.items.every(i=>!i.labels.includes('Street')),'number removes from all');
 events.keydown(keyboard); events.keydown(keyboard); await binWrites;
 check(binView.items.every(i=>!i.labels.includes('Street')),'queued rapid toggles use current labels');
 check(binView.selected.length===3,'write keeps selection');
 binView.query='hidden'; binGrid();
 check(binView.selected.length===3,'filter keeps hidden selection');
 binSelect('n',{},visible);
 check(nodes['#bin-panel'].innerHTML.includes('Edited note'),'draft survives multi-selection and filters');
 const count=writes.length;
 events.keydown({...keyboard,target:{closest:()=>({})}}); await binWrites;
 check(writes.length===count,'no number labels while typing');
 binView.query='no match'; binGrid();
 check(!nodes['#bin-grid'].innerHTML.includes('Station'),'search filters');
 binView.query=''; binView.kind='clip'; binGrid();
 check(!nodes['#bin-grid'].innerHTML.includes('Station'),'kind filters');
 let prevented=0;
 const event={target:{closest:()=>null},preventDefault:()=>prevented++};
 events.paste({...event,clipboardData:{getData:()=> 'https://example.test/source'}}); await binWrites;
 check(writes.at(-1)[0].endsWith('/link'),'URL paste');
 events.paste({...event,clipboardData:{getData:()=> 'Research pasted'}}); await binWrites;
 check(writes.at(-1)[0].endsWith('/note'),'text paste');
 const dashboard={classList:{toggle(){}}};
 events.drop({...event,target:{closest:()=>dashboard},dataTransfer:{types:['Files'],files:['a','b']}}); await binWrites;
 check(writes.at(-1)[1].body.files.length===2 && prevented===3,'batch drop');
})().catch(e=>{printerr(e.message+"\n"+e.stack);imports.system.exit(1);});
'''
    path = tmp_path/'bin.js'
    path.write_text(setup + Path('static/js/tabs/bin.js').read_text() + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_reusable_vocabulary_editor_actions_and_delete_confirmation(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    setup = r'''
const esc=String, dialogs=[], changes=[];
let labels=['Street','Morning'];
function check(ok,message){if(!ok) throw Error(message);}
function input(value) {return {value, dataset:{}, focus(){}};}
function makeRows() {
 const rows={forms:[],querySelectorAll(selector){return selector==='[data-row]'?this.forms:selector==='input'?this.forms.map(f=>f.input):[];},querySelector(){return this.forms[0]?.input;}};
 Object.defineProperty(rows,'innerHTML',{set(html){
  rows.forms=labels.map((l,n)=>({dataset:{row:String(n)},input:input(l),del:{},moves:[{dataset:{move:'-1'}},{dataset:{move:'1'}}],
   querySelector(s){return s==='input'?this.input:this.del;},querySelectorAll(){return this.moves;}}));
 }});
 return rows;
}
function studioDialog(kind,html) {
 const dialog={kind,html,nodes:{},closed:false,close(){this.closed=true;},setAttribute(){}};
 dialog.nodes['[data-label-rows]']=makeRows();
 dialogs.push(dialog); return dialog;
}
function $(selector,dialog) {return dialog.nodes[selector] ||= {focus(){}};}
async function change(p) {
 changes.push(p);
 if(p.action==='rename') labels=labels.map(l=>l===p.old?p.new:l);
 if(p.action==='reorder') labels=p.labels;
 if(p.action==='delete') labels=labels.filter(l=>l!==p.old);
 return true;
}
'''
    checks = r'''
(async()=>{
 const dialog=openLabelsEditor({getLabels:()=>labels,change});
 const rows=$('[data-label-rows]',dialog);
 rows.forms[0].input.value='Road';
 rows.forms[0].onsubmit({preventDefault(){}}); await Promise.resolve();
 check(labels.join(',')==='Road,Morning','keyboard form rename');
 await rows.forms[0].moves[1].onclick();
 check(labels.join(',')==='Morning,Road','reorder updates number order');
 const count=changes.length;
 rows.forms[0].del.onclick();
 let confirm=dialogs.at(-1);
 check(confirm.kind==='label-delete' && changes.length===count,'delete asks first');
 $('[data-cancel]',confirm).onclick();
 check(confirm.closed && changes.length===count,'cancel does not mutate');
 rows.forms[0].del.onclick(); confirm=dialogs.at(-1);
 await $('[data-confirm]',confirm).onclick();
 check(confirm.closed && labels.join(',')==='Road','confirmed deletion');
 $('[data-close]',dialog).onclick();
 check(dialog.closed,'close editor');
})().catch(e=>{printerr(e.stack);imports.system.exit(1);});
'''
    path = tmp_path / 'labels.js'
    path.write_text(setup + Path('static/ui/labels.js').read_text() + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

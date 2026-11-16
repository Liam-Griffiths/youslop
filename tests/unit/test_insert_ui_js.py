"""Insert gestures/transport in GJS; no browser, model, render or real media."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_insert_ui(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(f'static/js/timeline/{name}.js').read_text() for name in
                       ('inserts', 'insert_sources', 'insert_inspector'))
    source += '\n' + Path('static/js/tabs/script.js').read_text() + Path('static/js/tabs/script-writing.js').read_text()
    harness = r'''
const check = (v,m) => {if (!v) throw Error(m);};
const structuredClone = v => JSON.parse(JSON.stringify(v));
const state = {project:{id:'p', slides:[{id:'a'}, {id:'b'}]}};
const TL = {pid:'p',cur:5,zoom:10,selections:[],host:{focus(){}}};
let tlInspectorQueue = Promise.resolve(), calls=[], notices=[], renders=0, refreshed=0, selected;
const crypto = {randomUUID:() => String(calls.length)};
const toast = m => notices.push(m), esc = v => String(v), tlClock = t => String(t);
const tlPause = () => {}, tlSeek = () => {}, tlSelect = s => {selected=s;TL.selection=s;};
const tlParas = () => [{id:'a',start:2,duration:4},{id:'b',start:6,duration:4}];
const tlSegs = () => [{type:'intro',start:0,duration:2},{type:'picture',start:2,duration:8}];
const tlSectionEnd = () => 10;
const tlItems = () => state.project.slides.map(s=>({kind:'picture',sid:s.id,id:s.id,t0:2}));
const tlRefresh = async () => {refreshed++;};
const render = async () => {renders++;};
let menuPoint;
const renderBlocks = async (path,o) => {check(o.aspect==='16:9' && o.mode==='pick','shared aspect picker');
 await o.onUse({block:'title_card',vars:{title:'Custom'}});};
let reject=false;
const api = async (url,opts) => {
 if (!opts) {
   if (url==='/api/footage/shoots') return [{id:'shoot'}];
   if (url==='/api/footage/shoots/shoot') return {id:'shoot',files:[{id:'f',kind:'video',duration:9}],
     clips:[{id:'c',title:'Named range',file:'f',in_s:2,out_s:4}]};
   if (url==='/api/blocks') return [{ref:'title_card',name:'Title',aspects:['16:9'],variables:{title:{default:'Default'}}},
     {ref:'portrait',aspects:['9:16'],variables:{}}];
   if (url==='/api/library') return [{id:'asset',kind:'image',title:'Still'}];
 }
 calls.push({url,...opts});
 if (reject) throw Error('Invalid range');
 const project=structuredClone(state.project), patch=opts.body && JSON.parse(opts.body);
 if (opts.method==='POST') project.slides.splice(patch.after==='a'?1:0,0,{id:'new'+calls.length,insert:patch});
 if (opts.method==='PATCH') project.slides.find(s=>url.endsWith('/'+s.id)).insert.seconds=patch.seconds;
 if (opts.method==='DELETE') project.slides=project.slides.filter(s=>!url.endsWith('/'+s.id));
 return project;
};
const plus = {dataset:{insertPoint:'1'},setPointerCapture(){}};
const lane = {querySelectorAll:() => [plus],contains:() => false};
const track = {getBoundingClientRect:() => ({left:0})};
const scriptBody = {};
let $ = s => s==='#tabbody' ? scriptBody : s.includes('.tl-pictures') ? lane : track;
const pictureKind = () => 'image', thumbUrl = () => '/synthetic.jpg';
const isStage = () => false, fmtTime = t => String(t), presenterPanel = () => '', scriptLoadCheck = () => {};
const document = {querySelectorAll:() => []};
const blockTrialField = (key,spec) => key+':'+spec.default;
const readBlockTrial = () => ({title:'Edited vars'});
const event = (x=164,y=40) => ({clientX:x,clientY:y,button:0,pointerId:1,detail:1,stopPropagation(){},preventDefault(){}});
async function run() {
 check(tlInsertPoints().map(p=>p.t).join(',')==='2,6,10','intro and row boundaries');
 check(tlInsertNearest(8.1).after==='b','nearest final boundary');
 check(tlInsertNearest(2).after==='','opening after intro');
 const menu=tlInsertMenu; tlInsertMenu=p=>{menuPoint=p || tlInsertNearest();};
 tlWireInserts();
 plus.onpointerdown(event());plus.onpointerup(event());plus.onlostpointercapture();plus.onclick(event());
 check(menuPoint.after==='a','plus click uses its boundary');menuPoint=null;
 plus.onpointerdown(event());plus.onpointermove(event(180));plus.onpointerup(event(180));plus.onclick(event(180));
 check(menuPoint===null && !TL.scrubbing && !TL.drag,'drag starting on plus does nothing');
 plus.onpointerdown(event());plus.onpointercancel();plus.onclick(event());
 check(menuPoint===null,'cancel never opens');
 plus.onclick({...event(),detail:0});check(menuPoint.after==='a','keyboard button activation');
 const key=k=>({key:k,target:{closest:()=>null}});
 check(tlInsertKey(key('.')) && menuPoint.after==='a','period nearest playhead');
 check(tlInsertKey(key('Insert')),'Insert key');
 check(!tlInsertKey({...key('.'),target:{closest:()=>({})}}),'fields never insert');
 check(!tlInsertKey({...key('Insert'),ctrlKey:true}),'modifier never inserts');
 const sources=await tlInsertSources();
 check(sources.length===4 && sources[0].payload.in_s===2 && sources[0].payload.out_s===4,'named range and source');
 check(sources[2].payload.vars.title==='Default' && sources[3].payload.asset_id==='asset','aspect blocks and Library');
 const id=await tlInsertSave('',{...sources[0].payload,after:'a'});
 check(state.project.slides[1].id===id && selected.sid===id,'new insert selected after ripple');
 check(calls[0].editLabel==='add insert' && calls[0].editGesture && refreshed===1 && renders===0,'one undo gesture without render');
 await tlInsertSave(id,{seconds:3});check(state.project.slides[1].insert.seconds===3,'patch saves');
 TL.selection={kind:'picture',sid:id};TL.selections=[TL.selection];TL.section={ids:[id]};
 check(!tlInsertKey(key('Delete')),'section delete retains priority');TL.section=null;
 check(tlInsertKey(key('Backspace')),'selected insert delete');await tlInspectorQueue;
 check(!state.project.slides.some(s=>s.id===id) && selected===null,'deletion clears selection');
 const ghost=tlInsertGhost; let marker;
 tlInsertGhost=(point,seconds)=>{TL.insertDrop=point;marker={point,seconds};};
 TL.insertDrag={pid:'other',payload:sources[0].payload};const count=calls.length;
 lane.ondragover({...event(201),dataTransfer:{}});check(!marker,'foreign drag ignored');
 TL.insertDrag={pid:'p',payload:sources[0].payload};
 lane.ondragover({...event(201),dataTransfer:{}});
 check(marker.point.after==='b' && marker.seconds===2 && calls.length===count,'snap marker and ripple without save');
 lane.ondrop({...event(201),dataTransfer:{}});await tlInspectorQueue;
 check(calls.length===count+1 && JSON.parse(calls.at(-1).body).after==='b','one insert on drop');
 check(TL.insertDrag===null && TL.insertDrop===null,'drop clears ghost');tlInsertGhost=ghost;
 const before=JSON.stringify(state.project);reject=true;
 check(!await tlInsertSave('',{kind:'clip'}),'invalid mutation reports failure');
 check(JSON.stringify(state.project)===before && notices.at(-1)==='Invalid range','failure preserves local data');reject=false;
 await tlInsertBlock({after:'a',t:6});
 check(renders===1 && selected.sid===state.project.slides[1].id,'block picker returns to selected insert');
 const save=tlInsertSave;let edited;
 tlInsertSave=async (id,patch)=>{edited={id,patch};return id;};
 const nodes={'form':{querySelector:()=>submit},'[data-insert-vars]':{},'[data-insert-delete]':{},'[role=status]':{},
   '#insert-audio':{checked:true}};
 const submit={}, fields=[{dataset:{insertField:'in_s'},type:'number',value:'1'},
   {dataset:{insertField:'out_s'},type:'number',value:'3'}];
 const body={isConnected:true,querySelector:k=>nodes[k],querySelectorAll:k=>k==='[data-insert-field]'?fields:[]};
 const row={id:'inspect',insert:{kind:'clip',shoot_id:'shoot',source_id:'f',in_s:0,out_s:2,seconds:2}};
 state.project.slides.push(row);TL.selection={kind:'paragraph',sid:row.id};
 check(tlInsertInspector(TL.selection,body) && body.innerHTML.includes('Source out'),'clip inspector');
 await nodes.form.onsubmit({preventDefault(){}});
 check(edited.id===row.id && edited.patch.in_s===1 && edited.patch.out_s===3 && edited.patch.source_audio,'range and sound save together');
 nodes['[data-insert-delete]'].onclick();check(edited.patch===null,'inspector delete');
 row.insert={kind:'block',block:'title_card',seconds:4,vars:{title:'Existing'}};
 tlInsertInspector(TL.selection,body);await Promise.resolve();
 check(nodes['[data-insert-vars]'].innerHTML==='title:Existing' && !submit.disabled,'block typed form loads existing vars');
 fields.splice(0,2,{dataset:{insertField:'seconds'},type:'number',value:'5'});
 await nodes.form.onsubmit({preventDefault(){}});
 check(edited.patch.seconds===5 && edited.patch.vars.title==='Edited vars','block duration and vars save');
 check(!tlInsertInspector({kind:'chapter',sid:row.id},body),'attached layer inspector retained');
 tlInsertSave=save;
 state.project.style={format:'kenburns'};
 state.project.picture_runs=[['words','more'],['card']];
 state.project.slides=[{id:'words',narration:'Spoken',title:'',visual_note:'Shared shot',word_count:1,candidates:[{id:'pic'}],chosen_id:'pic'},
   {id:'more',narration:'More spoken words',word_count:3},
   {id:'card',chapter:'On an insert',insert:{kind:'card',text:'A card',seconds:4},word_count:0}];
 const workspace = {classList:{toggle(){}},style:{setProperty(){}}};
 const select = $; $ = s => s === '#script-toolbar' ? null : s === '.script-layout' ? workspace : select(s);
 scriptCurrent = () => {};
 paintScript();
 check(scriptBody.innerHTML.includes('Insert · card · 4.0 s') && !scriptBody.innerHTML.includes('Narration, paragraph 3'),'non-spoken Script label and count');
 check(!scriptBody.innerHTML.includes('Filter binder') && scriptBody.innerHTML.match(/data-script-shot=/g).length===2,'one page grouped by server picture runs');
 check(scriptBody.innerHTML.includes('SHOT 2') && scriptBody.innerHTML.includes('Shared shot') && scriptBody.innerHTML.includes('/synthetic.jpg'),'shot numbers and inline lead description');
 check(scriptSection('words','shot').join(',')==='words,more','whole-shot reorder preserves its paragraphs');
 const insertHtml=scriptBody.innerHTML.split('data-script-inspector="card"')[1];
 check(scriptBody.innerHTML.includes('On an insert') && insertHtml.includes('saveChapter') && !insertHtml.includes('textarea'),'insert chapters retained without narration fields');
 let focused=false;
 const insertCard={querySelector:()=>({focus(){focused=true;}})};
 insertCard.matches = () => true;
 scriptWorkspaceKey({key:'Enter',preventDefault(){},target:insertCard});
 check(focused,'Enter on an insert reaches Edit link');
 state.project.kind='clip';check(tlInsertPoints().length===0 && !tlInsertKey(key('.')),'clip projects excluded');
 tlInsertMenu=menu;
 print('insert UI gestures and transport passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'insert-ui.js'
    script.write_text('const window={addEventListener(){}};\n' + source + '\n' + harness)
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'insert UI gestures and transport passed' in result.stdout

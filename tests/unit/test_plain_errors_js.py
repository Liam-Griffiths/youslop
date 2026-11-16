"""Synthetic UX failure probes in GJS; no browser, model or media work."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_errors_actions_and_job_scope(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = Path('static/js/core.js').read_text()
    source += Path('static/js/jobs.js').read_text()
    render = Path('static/js/tabs/render.js').read_text()
    source += render[render.index('function paintPublishProgress()'):]
    source += Path('static/js/tabs/home-agent.js').read_text()
    source += Path('static/js/timeline/agent.js').read_text()
    harness = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
let timer, interval, payload, complete;
const setTimeout=fn=>{timer=fn;return 1;}, clearTimeout=()=>{};
const setInterval=fn=>{interval=fn;return 1;}, clearInterval=()=>{};
const location={hash:'#/p/p1/script'};
class FormData {}
const nodes={};
const node=()=>({innerHTML:'',className:'',buttons:[],dataset:{},children:[],
 set textContent(v){this.text=v;this.children=[];this.innerHTML='';for(const b of this.buttons)b.parentElement=null;this.buttons=[];},get textContent(){return this.text || '';},
 append(b){this.buttons.push(b);b.parentElement=this;},insertAdjacentHTML(_,html){this.innerHTML+=html;},
 insertBefore(child,next){const i=this.children.indexOf(next);this.children.splice(i<0?this.children.length:i,0,child);child.parent=this;},
 querySelector(s){return s==='article'?this.children.find(c=>c.className==='jobs-row'):this.detailsOpen?{}:null;},
 remove(){this.removed=true;if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}});
const document={activeElement:{dataset:{}},querySelector:s=>s==='dialog[open]'?null:nodes[s] ||= node(),createElement:node};
const drawerNodes={};
const studioDialog=()=>({open:true,querySelector:s=>drawerNodes[s] ||= node(),addEventListener(){}});
const fetch=async()=>({ok:true,text:async()=>JSON.stringify(payload)});
const paintJobsStrip=()=>{},scriptFlush=async()=>true;
const scriptPauseEditor=async fn=>fn();
'''
    checks = r'''
state.project={id:'p1'};
const model=friendlyError('LLMUnavailable: synthetic blocked');
check(model.message.includes("writing model didn't answer")&&model.action.label==='Open Settings','model guidance');
model.action.run();check(location.hash==='#/settings','settings action');
check(friendlyError({error:'unknown provider failure',reason:'model'}).message===model.message,'server reason takes precedence');
for(const name of ['NotAllowedError','NotFoundError']) {
 const f=friendlyError({name,message:'Permission denied'});
 check(f.message.includes(name==='NotAllowedError'?'microphone is blocked':'No microphone found'),'typed mic mapping');
 check(f.message.includes('draft voice')&&f.action.hash==='#/p/p1/voice','draft voice next step');
}
const missing="FFError: ffmpeg failed: [in#0 @ 0x123]\nError opening input file /tmp/data/projects/p1/takes/missing.wav.\nError opening input files: No such file or directory";
const file=friendlyError(missing);
check(file.message.includes('takes/missing.wav. Restore')&&!file.message.includes('/tmp/data'),'relative missing input');
check(file.action.hash==='#/p/p1/voice'&&file.details===missing,'recording recovery and raw report');
const fno=friendlyError("FileNotFoundError: [Errno 2] No such file or directory: '/home/user/projects/p1/raw/take.webm'");
check(fno.message.includes('raw/take.webm')&&!fno.message.includes('/home/user'),'Python missing input');
const stage=friendlyError('StageError: TypeError: window.__seek is not a function');
check(!stage.message.includes('__seek')&&stage.details.includes('__seek'),'stage diagnostics folded');
for(const render of [homeAgentMessage,editAgentMessage]) {
 const html=render({role:'agent',text:'The agent could not answer: provider offline',error:true},0);
 check(html.includes('writing model didn&#39;t answer')&&!html.split('<summary>Details</summary>')[0].includes('provider offline'),'agent errors folded');
}
check(friendlyError('ValueError: Too short. Private second sentence.').message==="That didn't work: Too short. Try again.",'first sentence fallback');
const markup=errorMarkup('LLMError: <script>unsafe</script>');
check(markup.includes('<summary>Details</summary><pre>LLMError: &lt;script&gt;')&&!markup.includes('<script>'),'selectable escaped raw details');
toast({name:'NotAllowedError',message:'Permission denied'},true);
const notice=nodes['#toast'];
check(notice.textContent.includes('microphone is blocked')&&notice.innerHTML.includes('Permission denied'),'toast friendly line plus details');
check(notice.buttons.at(-1).textContent==='Voice options','toast next step button');
let stopped=false;notice.onkeydown({stopPropagation(){stopped=true;}});
check(stopped&&markup.includes('onkeydown="event.stopPropagation()"'),'error controls keep Space and copy out of editor shortcuts');
notice.detailsOpen=true;timer();check(notice.className.includes('show'),'open details survive expiry');
notice.detailsOpen=false;timer();check(notice.className==='toast','closed toast expires');
toast({name:'NotAllowedError',message:'Permission denied'},true);
nodes['summary']=node();nodes['summary'].focus=()=>{};
await notice.buttons.at(-1).onclick();
check(state.rec.openDraft&&nodes['.voice-options'].open&&location.hash==='#/p/p1/voice','voice action opens existing draft options');
check(notice.className==='toast','completed navigation action clears its toast');
location.hash='#/p/p1/script';
payload={job:'synthetic'};await api('/api/projects/p1/script',{method:'POST'});
payload={id:'synthetic',project_id:'p1',writes:true,state:'running',log:[],log_total:0};
watchJob('synthetic','script',j=>complete=j);
for(let i=0;i<20;i++)await Promise.resolve();
check(jobPanel().includes('jobcard'),'origin stage card');
location.hash='#/p/p1/script/outline';check(jobPanel().includes('jobcard'),'same stage subtab keeps card');
location.hash='#/p/p1/voice';check(jobPanel()==='','other stage hides card');
location.hash='#/p/p2/script';check(jobPanel()==='','other project hides card');
location.hash='#/p/p1/dashboard';check(jobPanel().includes('jobcard'),'project dashboard shows writing job');
state.job.writes=false;check(jobPanel()==='','background jobs have no cards');
state.job.writes=true;state.job.origin='';check(jobPanel().includes('jobcard'),'resumed writer on dashboard');
location.hash='#/p/p1/script';check(jobPanel()==='','resumed writer does not guess origin');
state.project=null;
payload={...payload,state:'error',error:'LLMError: synthetic blocked',reason:'model'};
await interval();
check(complete.reason==='model'&&state.job.done==='error','failed job is retained and callback runs');
check(notice.textContent.includes("writing model didn't answer"),'failed job toast mapped');
state.project={id:'p1'};state.job.origin=location.hash;
const card=jobPanel();
check(card.includes('<strong>Script</strong>'),'sentence case job card');
paintJob(); check(nodes['#jobstate'].textContent==='failed','plain failed state');
state.job.done='done'; paintJob(); check(nodes['#jobstate'].textContent==='done','done state');
state.job.done='error';
check(card.includes('Dismiss')&&card.includes('Details')&&!card.split('<summary>Details</summary>')[0].includes('LLMError:'),'job diagnostic behind fold');
check(!card.includes('synthetic</'),'no visible job id');
check(friendlyError({last_log_line:'FAILED: legacy failure'}).message.includes('legacy failure'),'old summary without reason');
check(jobLabel({kind:'timeline sound'})==='Mixing the sound','plain sound label');
check(jobProgress({kind:'timeline sound',writes:false,last_log_line:'Measuring normalization'})==='Mixing the sound','quiet sound progress');
// Exercise the real microphone catch, retaining the DOMException name.
ensureMic=async()=>{throw {name:'NotAllowedError',message:'Permission denied'};};
await openMic();check(notice.textContent.includes('microphone is blocked'),'mic denied probe');
payload=[{id:'j-private-id',project_id:'p1',project_title:'Example',kind:'script',state:'error',
 error:'LLMError: synthetic blocked',reason:'model',elapsed:3,writes:true}];
openJobs();
for(let i=0;i<20;i++)await Promise.resolve();
const list=drawerNodes['[data-jobs-list]'], row=list.children[0];
check(row.innerHTML.includes('Details')&&row.innerHTML.includes("writing model didn&#39;t answer"),'drawer maps failure');
check(!row.innerHTML.includes('j-private-id'),'drawer hides job id');
row.detailsOpen=true;const content=row.innerHTML;
await timer();check(list.children[0]===row&&row.detailsOpen&&row.innerHTML===content,'completed details survive drawer refresh');
state.job={project_id:'p1',kind:'render',done:'error',error:missing,lines:['FAILED: '+missing]};
paintPublishProgress();
const publish=nodes['#publish-progress'].innerHTML;
check(publish.includes('takes/missing.wav')&&!publish.split('<summary>Details</summary>')[0].includes('FFError'),'Publish failure has friendly copy and Details');
print('plain errors, details, actions, mic denial and job scope passed');
'''
    # Only the recording function is needed; it calls the real shared toast.
    record = Path('static/js/tabs/record.js').read_text()
    record = record[record.index('async function openMic()'):record.index('async function chooseMic(')]
    script = tmp_path / 'plain-errors.mjs'
    script.write_text(harness + source + '\nlet ensureMic;\n' + record + checks)
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'job scope passed' in result.stdout

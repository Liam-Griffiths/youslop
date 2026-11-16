"""Shared dialog contracts and channel theme transactions; GJS, no browser."""
from pathlib import Path
import shutil
import subprocess
import re

import pytest


def test_no_native_dialog_calls():
    root = Path(__file__).resolve().parents[2] / 'static/js'
    calls = re.compile(r'\b(?:prompt|confirm|alert)\s*\(')
    found = [f'{path.relative_to(root)}:{number}: {line.strip()}'
             for path in sorted(root.rglob('*.js')) if path != root / 'ui/dialog.js'
             for number, line in enumerate(path.read_text().splitlines(), 1)
             if calls.search(line)]
    assert not found, 'Use shared app dialogs:\n' + '\n'.join(found)


def run_gjs(tmp_path, source):
    if not (gjs := shutil.which('gjs')):
        pytest.skip('GJS unavailable')
    script = tmp_path / 'dialogs.js'
    script.write_text(source)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


DOM = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nodes=[];
class Element {
 constructor(){this.listeners={};this.attrs={};this.dataset={};this.isConnected=true;}
 focus(){document.activeElement=this;}
 select(){this.selected=true;}
 getClientRects(){return this.hidden?[]:[{}];}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
 emit(k,e={}){for(const fn of this.listeners[k]||[])fn(e);}
 set innerHTML(html){
  this.html=html; this.parts=[];
  for(const match of html.matchAll(/<(h2|input|textarea|button|form|p)\b([^>]*)>/g)){
   const el=new Element();el.tag=match[1];el.markup=match[2];
   el.value=el.markup.match(/value="([^"]*)"/)?.[1]||'';
   if(el.tag==='textarea')el.value=html.slice(match.index+match[0].length).split('</textarea>')[0];
   el.id=el.markup.match(/id="([^"]*)"/)?.[1]||'';
   const choice=el.markup.match(/data-choice="([^"]*)"/);
   if(choice)el.dataset.choice=choice[1];
   this.parts.push(el);
  }
 }
 get innerHTML(){return this.html;}
 querySelectorAll(s){return this.parts.filter(el=>s.includes(',')?s.split(',').map(v=>v.trim()).includes(el.tag):
  s.startsWith('[')?el.markup.includes(s.slice(1,-1)):el.tag===s);}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}
 contains(el){return this===el||this.parts?.includes(el);}
 showModal(){this.open=true;}
 close(){this.open=false;this.emit('close');}
 remove(){this.isConnected=false;}
 matches(){return this.isConnected&&(this.legacy||this.open);}
}
const opener=new Element();
const document={activeElement:opener,createElement:()=>new Element(),
 body:{append:el=>nodes.push(el),contains:el=>el.isConnected},
 querySelectorAll:()=>nodes.filter(el=>el.matches())};
const last=()=>nodes.at(-1);
const key=(wrap,k,shiftKey=false)=>{
 const e={key:k,shiftKey,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
 wrap.emit('keydown',e);return e;
};
'''


def test_dialog_values_focus_and_legacy_adapters(tmp_path):
    source = Path('static/js/ui/dialog.js').read_text()
    picture = Path('static/js/tabs/picture_tools.js').read_text()
    library = Path('static/js/tabs/library_explorer.js').read_text()
    source += picture[picture.index('function pictureDialog('):]
    source += library[library.index('function libConfirm('):library.index('async function renderLibrary(')]
    checks = r'''
async function run(){
 let promise=appConfirm({title:'Delete?',body:'<unsafe>',danger:true});
 let dialog=last();
 check(dialog.attrs['aria-labelledby']===dialog.querySelector('h2').id,'labelled dialog');
 check(dialog.attrs['aria-describedby']===dialog.querySelector('p').id,'body description');
 check(dialog.html.includes('&lt;unsafe&gt;')&&!dialog.html.includes('<unsafe>'),'plain text body');
 check((dialog.html.match(/btn primary/g)||[]).length===1 && dialog.html.includes('danger'),'one primary, danger token class');
 const buttons=dialog.querySelectorAll('button');
 buttons.at(-1).focus();
 check(key(dialog,'Tab').prevented&&document.activeElement===buttons[0],'Tab wraps');
 check(key(dialog,'Tab',true).prevented&&document.activeElement===buttons.at(-1),'Shift Tab wraps');
 check(key(dialog,'Escape').prevented,'Escape consumed');
 check(await promise===false&&document.activeElement===opener&&!dialog.isConnected,'Escape cancels and returns focus');
 promise=appConfirm({title:'Continue?'});last().querySelector('[data-choice]').onclick();
 check(await promise===true,'confirm resolves true');
 promise=appChoose({title:'Choose',choices:[{id:'a',label:'Alpha',primary:true},{id:'b',label:'Beta',primary:true}]});
 check((last().html.match(/btn primary/g)||[]).length===1,'at most one primary');
 last().querySelectorAll('[data-choice]')[1].onclick();check(await promise==='b','choice id');
 promise=appChoose({title:'Choose',choices:[]});last().emit('cancel',{preventDefault(){}});
 check(await promise===null,'platform cancel resolves null');
 promise=appPrompt({title:'Name',label:'Style name',value:'Old'});dialog=last();
 const input=dialog.querySelector('input');
 check(dialog.html.includes(`for="${input.id}"`)&&input.selected,'explicit input label and selected text');
 check(document.activeElement===input&&input.value==='Old','prompt starts in input');
 input.value='  Exact text  ';dialog.querySelector('form').onsubmit({preventDefault(){}});
 check(await promise==='  Exact text  ','prompt preserves text');
 promise=appPrompt({title:'Name',label:'Name'});last().querySelector('[data-cancel]').onclick();
 check(await promise===null,'prompt Cancel');
 promise=appPrompt({title:'Rules',label:'One per line',value:'First\nSecond',multiline:true});dialog=last();
 const textarea=dialog.querySelector('textarea');
 check(textarea.value==='First\nSecond'&&document.activeElement===textarea,'multiline value and initial focus');
 check(dialog.html.includes(`for="${textarea.id}"`),'textarea labelled');
 const enter=key(dialog,'Enter');check(!enter.prevented&&dialog.open,'Enter remains available for newlines');
 dialog.querySelectorAll('button').at(-1).focus();key(dialog,'Tab');
 check(document.activeElement===textarea,'Tab wraps back to textarea');
 textarea.value=' First\n\n Second ';dialog.querySelector('form').onsubmit({preventDefault(){}});
 check(await promise===' First\n\n Second ','multiline text preserved exactly');
 promise=appPrompt({title:'Rules',label:'Rules',value:'</textarea><script>bad</script>',multiline:true});
 check(last().html.includes('&lt;/textarea&gt;')&&!last().html.includes('<script>'),'textarea value escaped');
 key(last(),'Escape');check(await promise===null,'textarea Escape cancels');
 promise=appPrompt({title:'Channel',fields:[{name:'name',label:'Name',value:'Old'},
  {name:'concept',label:'Concept'}]});dialog=last();
 const fields=dialog.querySelectorAll('input');
 check(fields.length===2&&fields[0].selected&&document.activeElement===fields[0],'two fields, first selected');
 check(fields.every(el=>dialog.html.includes(`for="${el.id}"`))&&fields[0].id!==fields[1].id,'unique field labels');
 fields[0].value='Channel';fields[1].value='';dialog.querySelector('form').onsubmit({preventDefault(){}});
 check(JSON.stringify(await promise)===JSON.stringify({name:'Channel',concept:''}),'named fields preserve blank concept');
 promise=appPrompt({title:'Channel',fields:[{name:'name',label:'Name'},{name:'concept',label:'Concept'}]});
 key(last(),'Escape');check(await promise===null&&document.activeElement===opener,'multi-field Escape cancels and returns focus');
 promise=pictureDialog('Name style','Old');last().querySelector('input').value='  Style  ';
 last().querySelector('form').onsubmit({preventDefault(){}});check(await promise==='Style','picture adapter trims');
 promise=pictureDialog('Change?');key(last(),'Escape');check(await promise===null,'picture adapter retains null Cancel');
 promise=libConfirm('Remove?');last().querySelector('[data-choice]').onclick();check(await promise===true,'library adapter');
 const legacy=studioDialog('editor','<h2 id="studio-dialog-title">Editor</h2><button>Close</button>');
 check(legacy.attrs['aria-labelledby']==='studio-dialog-title','existing title ids retained for content replacement');
 legacy.querySelector('button').focus();const previous=document.activeElement;
 promise=appConfirm({title:'Nested'});key(last(),'Escape');await promise;
 check(document.activeElement===previous&&legacy.open,'nested confirmation returns focus to editor');
 editToolKey({key:'Escape',preventDefault(){},stopPropagation(){}},legacy,()=>legacy.close());
 check(!legacy.isConnected&&document.activeElement===opener,'legacy key adapter');
 print('dialog values, keyboard, focus and adapters passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    run_gjs(tmp_path, DOM + source + checks)


def test_converted_flows_wait_for_dialog_and_preserve_payloads(tmp_path):
    source = Path('static/js/ui/dialog.js').read_text()
    for filename, start, end in [
        ('tabs/home.js', 'async function newChannel(', 'async function delProject('),
        ('tabs/script.js', 'async function delSlide(', 'async function reimport('),
        ('tabs/script-check.js', 'async function scriptEditRules(', 'async function runFactcheck('),
        ('tabs/settings.js', 'async function removePack(', 'async function checkSpeechEngines('),
        ('timeline/inspect.js', 'async function tlMakeRule(', 'async function tlRejectLook('),
        ('timeline/draw.js', 'async function tlDrawAll(', '// Preview only'),
    ]:
        text = (Path('static/js') / filename).read_text()
        source += text[text.index(start):text.index(end)]
    checks = r'''
const state={project:{id:'p1',frame:{rules:['First','Second']}}},TL={pid:'p1',data:{width:480,height:270}};
let calls=[],checks=0,refreshes=0,draws=0;
const api=async(path,options={})=>{
 calls.push({path,...options});
 if(path.endsWith('/uses'))return {channels:[],projects:[]};
 if(path==='/api/channels')return {id:'c1'};
 if(path==='/api/channels/c1')return {id:'c1',frame:{rules:['Channel rule']}};
 return {id:'p1',updated_at:7};
};
const go=()=>{},route=async()=>{},render=async()=>{},toast=(msg,bad)=>{if(bad)throw Error(msg);};
const scriptFlush=async()=>true,scriptPauseEditor=async fn=>fn(),scriptLoadCheck=()=>checks++;
const refreshPackPickers=async()=>refreshes++,renderPacks=async()=>{};
const tlSegs=()=>[{ref:'pic',ready:false}],tlEnsure=refs=>{check(refs[0]==='pic','drawing refs');draws++;};
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
const writes=()=>calls.filter(c=>c.method&&c.method!=='GET');
const submit=()=>last().querySelector('form').onsubmit({preventDefault(){}});
const choose=()=>last().querySelector('[data-choice]').onclick();
async function run(){
 let pending=newChannel();check(writes().length===0,'channel waits');
 key(last(),'Escape');await pending;check(writes().length===0,'channel cancel writes nothing');
 pending=newChannel();let fields=last().querySelectorAll('input');fields[0].value='Name';fields[1].value='Concept';
 submit();await pending;
 check(JSON.stringify(JSON.parse(writes()[0].body))===JSON.stringify({name:'Name',concept:'Concept'}),'single channel creation with both fields');
 calls=[];pending=delSlide('s1');await tick();
 check(last().html.includes('danger')&&writes().length===0,'delete waits with danger');
 key(last(),'Escape');await pending;check(writes().length===0,'paragraph cancel writes nothing');
 pending=delSlide('s1');await tick();choose();await pending;
 check(writes().length===1&&writes()[0].method==='DELETE'&&writes()[0].path.endsWith('/slides/s1'),'paragraph deletes once after approval');
 calls=[];state.project={id:'p1',frame:{rules:['First','Second']}};
 pending=scriptEditRules();check(last().querySelector('textarea').value==='First\nSecond','writing rules use textarea');
 key(last(),'Escape');await pending;check(writes().length===0,'rules cancel writes nothing');
 pending=scriptEditRules();last().querySelector('textarea').value=' New first\n\nNew second ';submit();await pending;
 check(JSON.parse(writes()[0].body).frame.rules.join('|')==='New first|New second','line splitting and trimming unchanged');
 check(state.project.updated_at===7&&checks===1,'project version and checks refresh');
 calls=[];state.project.channel_id='c1';pending=scriptEditRules();await tick();
 check(last().querySelector('textarea').value==='Channel rule','channel rules loaded from full channel');
 last().querySelector('textarea').value='';submit();await pending;
 check(writes()[0].path==='/api/channels/c1'&&JSON.parse(writes()[0].body).frame.rules.length===0,'channel rules can be cleared');
 calls=[];pending=removePack('test/pack');await tick();
 check(writes().length===0&&last().html.includes('danger'),'pack waits with danger');
 key(last(),'Escape');await pending;check(writes().length===0&&refreshes===0,'pack cancel preserves state');
 pending=removePack('test/pack');await tick();choose();await pending;
 check(writes().length===1&&writes()[0].path==='/api/packs/test%2Fpack'&&refreshes===1,'pack removal endpoint and refresh unchanged');
 calls=[];pending=tlMakeRule('Suggested');key(last(),'Escape');await pending;
 check(writes().length===0,'rule text cancel');
 pending=tlMakeRule('Suggested');submit();await tick();
 check(!last().querySelector('input')&&last().querySelectorAll('[data-choice]').length===2,'scope is a fixed choice');
 key(last(),'Escape');await pending;check(writes().length===0,'scope cancel writes nothing');
 for(const scope of ['project','channel']){
  pending=tlMakeRule('Suggested');submit();await tick();
  last().querySelectorAll('[data-choice]').find(b=>b.dataset.choice===scope).onclick();await pending;
  check(JSON.stringify(JSON.parse(writes().at(-1).body))===JSON.stringify({text:'Suggested',scope}),'rule scope payload');
 }
 pending=tlDrawAll();check(draws===0,'draw waits');key(last(),'Escape');await pending;check(draws===0,'draw cancel');
 pending=tlDrawAll();choose();await pending;check(draws===1,'draw starts once after confirmation');
 print('converted dialog cancellation, waits and payloads passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    run_gjs(tmp_path, DOM + source + checks)


def test_theme_cancel_apply_undo_and_errors(tmp_path):
    source = Path('static/js/tabs/channel_theme.js').read_text()
    checks = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const clone=x=>JSON.parse(JSON.stringify(x));
const original={id:'c1',style:{theme:'archive',accent:'custom1',accent2:'custom2',grade:'mono',other:7},
 frame:{transition_types:['fade'],rules:['Keep']},intro:{template:'columns'},thumb_template:'banner',
 outro:{template:'twoup',slots:2},videos:['v'],has_preview:true,has_outro_preview:true};
const state={channel:clone(original),themes:[{key:'arcade',label:'Arcade'}]};
let server=clone(original), choice=null, calls=[], action, fail=false, paints=0, errors=0;
const appChoose=async options=>{check(options.cancel==='Cancel'&&options.choices.length===2,'three choices with Cancel');return choice;};
const api=async(path,options)=>{
 calls.push({path,...options});if(fail)throw Error('Offline');
 const patch=JSON.parse(options.body);server.style={...server.style,theme:patch.key,accent:'new',accent2:'new2',grade:'cool'};
 server.frame.transition_types=['cut'];
 if(patch.templates){server.intro.template='arcade';server.thumb_template='sticker';server.outro={template:'arcade',slots:0};}
 return clone(server);
};
const applyChannel=fresh=>{state.channel=clone(fresh);paints++;};
const saveChannel=async(patch,options)=>{
 check(options.id==='c1'&&options.quiet,'Undo targets original channel');calls.push(patch);
 server.style={...server.style,...patch.style};server.frame=patch.frame;
 server.intro={...server.intro,...patch.intro};server.outro={...server.outro,...patch.outro};
 server.thumb_template=patch.thumb_template;return clone(server);
};
const toast=(msg,bad,a)=>{action=a;if(bad)errors++;};
async function run(){
 const bytes=JSON.stringify(state.channel);await pickTheme('arcade');
 check(JSON.stringify(state.channel)===bytes&&calls.length===0&&paints===0&&!action,'Cancel is byte-identical and sends nothing');
 for(const value of ['templates','colours']){
  choice=value;state.channel=clone(original);server=clone(original);calls=[];
  await pickTheme('arcade');
  check(calls[0].path==='/api/channels/c1/theme'&&JSON.parse(calls[0].body).templates===(value==='templates'),'correct apply path');
  check(action.label==='Undo'&&state.channel.style.accent==='new','applied and Undo offered');
  if(value==='colours')check(state.channel.intro.template==='columns'&&state.channel.outro.slots===2,'colours keep templates');
  const undo=action;await undo.run();
  check(JSON.stringify(state.channel)===bytes&&JSON.stringify(server)===bytes,'Undo restores colours, grade, frame, templates and slots');
 }
 choice='templates';fail=true;calls=[];await pickTheme('arcade');
 check(errors===1&&!action&&JSON.stringify(state.channel)===bytes,'failed apply preserves state and reports error');
 fail=false;await pickTheme('arcade');const undo=action;state.channel={id:'c2'};await undo.run();
 check(state.channel.id==='c2'&&server.style.accent===original.style.accent,'Undo after navigation targets original without repainting another channel');
 print('theme Cancel, both apply modes, Undo and failure paths passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    run_gjs(tmp_path, source + checks)


def test_timeline_refreshes_after_both_dialog_types(tmp_path):
    source = Path('static/js/timeline/inspect.js').read_text()
    source = source[source.index('async function tlModal('):source.index('async function tlRefreshProject(')]
    checks = r'''
let observer, refreshes=0;
const tlPause=()=>{},tlRefreshProject=()=>refreshes++;
class MutationObserver {
 constructor(fn){this.fn=fn;observer=this;}
 observe(body,options){check(options.subtree&&options.attributes,'watch nested editors and dialog open state');}
 disconnect(){this.done=true;}
}
async function run(){
 for(const legacy of [true,false]){
  const wrap=new Element();wrap.legacy=legacy;
  await tlModal(()=>{nodes.push(wrap);wrap.open=true;});
  observer.fn();check(!observer.done,'wait while editor remains open');
  if(legacy)wrap.remove();else wrap.open=false;
  observer.fn();check(observer.done,'disconnect after editor closes');
 }
 check(refreshes===2,'both dialog types refresh');
 await tlModal(async()=>{});check(refreshes===3,'already-awaited dialog refreshes immediately');
 print('timeline dialog refresh passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    run_gjs(tmp_path, DOM + source + checks)


def test_undo_toast_action_and_keyboard_lifetime(tmp_path):
    source = Path('static/js/core.js').read_text()
    source = source[source.index('function friendlyError('):source.index('function fmtTime(')]
    checks = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
let timer, delay, runs=0, cleared=0;
const setTimeout=(fn,ms)=>{timer=fn;delay=ms;return 1;},clearTimeout=()=>cleared++;
const state={},el={append(button){this.button=button;},insertAdjacentHTML(){},querySelector(){return null;},
 set textContent(v){this.message=v;this.button=null;}};
const $=()=>el,document={createElement:()=>({})};
async function run(){
 toast('Applied',false,{label:'Undo',run:async()=>{runs++;toast('Undone');}});
 check(el.button.textContent==='Undo'&&delay===15000,'Undo is a real button with time to act');
 const previous=cleared;el.onfocusin();check(cleared>previous,'keyboard focus pauses expiry');
 el.onfocusout();check(delay===15000,'expiry resumes after focus leaves');
 const button=el.button;await button.onclick();
 check(runs===1&&button.disabled&&el.message==='Undone'&&!el.button,'action runs once and new toast clears button');
 toast('Applied',false,{label:'Undo',run:async()=>{throw Error('Offline');}});
 await el.button.onclick();check(el.message.includes('Offline')&&el.className==='toast show bad','failed undo reports friendly error');
 timer();check(el.className==='toast'&&!el.button,'expiry removes hidden tab target');
 print('Undo toast action, focus lifetime and errors passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    run_gjs(tmp_path, source + checks)

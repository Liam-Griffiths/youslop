"""Shared dialog contracts and channel theme transactions; GJS, no browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


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
  for(const match of html.matchAll(/<(h2|input|button|form|p)\b([^>]*)>/g)){
   const el=new Element();el.tag=match[1];el.markup=match[2];
   el.value=el.markup.match(/value="([^"]*)"/)?.[1]||'';
   el.id=el.markup.match(/id="([^"]*)"/)?.[1]||'';
   const choice=el.markup.match(/data-choice="([^"]*)"/);
   if(choice)el.dataset.choice=choice[1];
   this.parts.push(el);
  }
 }
 get innerHTML(){return this.html;}
 querySelectorAll(s){return this.parts.filter(el=>s.includes(',')?['button','input'].includes(el.tag):
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
    source = source[source.index('let toastTimer;'):source.index('const esc =')]
    checks = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
let timer, delay, runs=0, cleared=0;
const setTimeout=(fn,ms)=>{timer=fn;delay=ms;return 1;},clearTimeout=()=>cleared++;
const el={append(button){this.button=button;},set textContent(v){this.message=v;this.button=null;}};
const $=()=>el,document={createElement:()=>({})};
async function run(){
 toast('Applied',false,{label:'Undo',run:async()=>{runs++;toast('Undone');}});
 check(el.button.textContent==='Undo'&&delay===15000,'Undo is a real button with time to act');
 const previous=cleared;el.onfocusin();check(cleared>previous,'keyboard focus pauses expiry');
 el.onfocusout();check(delay===15000,'expiry resumes after focus leaves');
 const button=el.button;await button.onclick();
 check(runs===1&&button.disabled&&el.message==='Undone'&&!el.button,'action runs once and new toast clears button');
 toast('Applied',false,{label:'Undo',run:async()=>{throw Error('Offline');}});
 await el.button.onclick();check(el.message==='Offline'&&el.className==='toast show bad','failed undo reports error');
 timer();check(el.className==='toast'&&!el.button,'expiry removes hidden tab target');
 print('Undo toast action, focus lifetime and errors passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    run_gjs(tmp_path, source + checks)

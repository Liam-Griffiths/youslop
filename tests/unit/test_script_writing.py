"""Writing gestures use synthetic metadata and GJS; no browser, audio or model work."""
import asyncio
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest

from app import main, store, undo
from app.schema import Project, Slide


def test_append_blank_and_undo_preserve_recordings(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    p = Project(id='writing', idea='Synthetic writing', slides=[Slide(id='one', narration='Only one sentence.',
        chapter='Opening', take={'path': 'takes/original.wav', 'duration': 3}),
        Slide(id='two', narration='The next paragraph.')])
    store.save(p)
    recording = store.project_dir(p.id) / 'takes/original.wav'
    recording.write_bytes(b'Untouched recording')
    before = deepcopy(store.load(p.id).to_dict())
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            path = '/api/projects/writing'
            response = await client.post(path + '/slides/one/split', json={'append': True})
            assert response.status_code == 200, response.text
            rows = response.json()['slides']
            assert [rows[0]['id'], rows[2]['id']] == ['one', 'two']
            assert rows[1]['narration'] == '' and rows[1]['chapter'] == '' and not rows[1]['take']
            assert rows[0] == before['slides'][0]
            assert len(undo.read(store.project_dir(p.id))['states']) == 2
            await client.post(path + '/undo')
            assert store.load(p.id).to_dict() == before
            await client.patch(path + '/slides/one', json={'narration': 'Changed words.'})
            assert store.load(p.id).slides[0].take == before['slides'][0]['take']
            await client.post(path + '/undo')
            assert store.load(p.id).to_dict() == before
            response = await client.patch(path + '/slides/one', json={'title': 'Updated title'})
            version = response.json()['project_version']
            assert version == store.load(p.id).updated_at
            response = await client.post(path + '/sections', json={
                'op': 'move', 'ids': ['two'], 'to': 'one', 'version': version})
            assert response.status_code == 200, response.text
            assert [s.id for s in store.load(p.id).slides] == ['two', 'one']
            await client.post(path + '/undo')
            assert [s.id for s in store.load(p.id).slides] == ['one', 'two']
            assert store.load(p.id).slides[0].title == 'Updated title'
            await client.delete(path + '/slides/one')
            assert store.load(p.id).retired_takes
            assert recording.read_bytes() == b'Untouched recording'
    asyncio.run(run())


def test_writing_save_queue(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    harness = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const status={textContent:''}, calls=[];
const $=()=>status, toast=()=>{}, document={querySelectorAll:()=>[],querySelector:()=>null};
const localStorage={getItem(){throw Error('disabled');},setItem(){throw Error('disabled');}};
const state={project:{id:'p',updated_at:42,slides:[
 {id:'a',narration:'A',chapter:'First'},{id:'b',narration:'B'},
 {id:'c',narration:'C',chapter:'Second'},{id:'d',narration:'D'}]}};
const projectRows=state.project.slides;
let fail=false, hold, version=42;
const api=async(path,options)=>{
 calls.push({path,...JSON.parse(options.body)});
 if(fail)throw Error('Offline');
 if(hold){const pending=hold;hold=null;await pending;}
 return path.endsWith('/sections')?state.project:{project_version:++version,...(path.includes('/p/')?projectRows:state.project.slides).find(s=>path.endsWith('/'+s.id)),...JSON.parse(options.body)};
};
scriptStats=()=>{};scriptLoadCheck=()=>{};paintScript=()=>{};scriptLocate=()=>{};
const loop=new imports.gi.GLib.MainLoop(null,false);
(async()=>{
 check(scriptPreference('agent',340)===340,'storage fallback'); scriptRemember('agent',300);
 scriptDrafts.set('a',{pid:'p',text:'New A'});scriptDrafts.set('b',{pid:'p',text:'New B'});
 check(await scriptFlush(),'flush succeeds');
 check(state.project.slides[0].narration==='New A'&&state.project.slides[1].narration==='New B','correct paragraph saves');
 check(calls.length===2&&!scriptDrafts.size,'one write per dirty paragraph');
 const saving=scriptSave('a',{narration:'Newest A'}), next=scriptSave('a',{title:'Title'});
 await Promise.all([saving,next]);
 check(state.project.slides[0].narration==='Newest A'&&state.project.slides[0].title==='Title','serial responses');
 fail=true;scriptDrafts.set('a',{pid:'p',text:'Retry me'});
 check(!await scriptFlush()&&scriptDrafts.has('a'),'failed save retains draft');
 fail=false;check(await scriptFlush()&&!scriptDrafts.size,'retry saves');
 scriptNotes.set('a',{pid:'p',text:'Private draft'}); fail=true;
 check(!await scriptFlush()&&scriptNotes.has('a'),'failed note save retains draft');
 fail=false;check(await scriptFlush()&&!scriptNotes.size,'retry note saves');
 check(state.project.slides[0].note==='Private draft'&&state.project.slides[0].narration==='Retry me','note stays separate from narration');
 await scriptMoveChapter(['a','b'],'');
 const move=calls.at(-1);
 check(move.path.endsWith('/sections')&&move.op==='move'&&move.ids.join(',')==='a,b'&&move.to===''&&move.version===state.project.updated_at,'atomic versioned section reorder');
 let release;
 hold=new Promise(r=>release=r);
 scriptDrafts.set('a',{pid:'p',text:'First revision'});
 const beforeSlow=calls.length, slow=scriptFlush(), also=scriptFlush();
 check(slow===also,'concurrent flush shares one drain');
 while(calls.length===beforeSlow)await Promise.resolve();
 scriptDrafts.set('a',{pid:'p',text:'Typed while saving'});
 release();check(await slow,'drain newer typing');
 check(calls.length===beforeSlow+2&&state.project.slides[0].narration==='Typed while saving'&&!scriptDrafts.size,'newer draft never discarded');
 scriptComposing=true;scriptDrafts.set('a',{pid:'p',text:'Composed text'});
 check(!await scriptFlush()&&scriptDrafts.has('a'),'no save or navigation during composition');
 scriptComposing=false;check(await scriptFlush(),'composition saves after completion');
 const previousProject=state.project;
 const bound=scriptSave('a',{title:'Captured project'});
 state.project={id:'another',slides:[]};
 await bound;
 check(calls.at(-1).path==='/api/projects/p/slides/a','queued write stays with its project');
 state.project=previousProject;
 let prevented=false;
 const composing={key:'Enter',isComposing:true,preventDefault(){prevented=true;}};
 await scriptEditorKey(composing,'a');check(!prevented,'IME ignored');
 check(scriptVoice({take:{narration:'Old'}}).includes('out of date'),'recording text warning');
 print('writing save queue passed');
})().catch(e=>{printerr(e.stack);imports.system.exit(1);}).finally(()=>loop.quit());loop.run();
'''
    source = '\n'.join(Path('static/js/tabs/' + name).read_text() for name in ('script.js', 'script-writing.js'))
    script = tmp_path / 'writing.js'
    script.write_text('const window={addEventListener(){}};\n' + source + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'writing save queue passed' in result.stdout


def test_writing_snapshot_fixtures(tmp_path, monkeypatch):
    from scripts.ui_snapshots import seed_writing, routes
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    seed_writing()
    short, long = (store.load('psnapwrite' + size) for size in ('short', 'long'))
    assert len(short.slides) == 2 and len(long.slides) == 32
    assert sum(bool(s.chapter) for s in long.slides) == 4
    assert all(len(run) == 1 for run in short.picture_runs())
    assert any(len(run) > 1 for run in long.picture_runs())
    assert long.slides[0].take and long.research['facts'] and long.research['flags']
    assert '#/p/psnapwritelong/script' in routes()


def test_page_shots_toolbar_and_caret(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path('static/js/tabs/' + name).read_text() for name in
                       ('script.js', 'script-writing.js', 'script-check.js', 'script-agent.js'))
    harness = r"""
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const esc=s=>String(s||''), fmtTime=String, isStage=()=>false, thumbUrl=()=>'/t.jpg';
const pictureKind=()=> 'image', pictureKindLabel=()=>'Photo', presenterPanel=()=>'';
const localStorage={getItem:()=>null,setItem(){}};
const state={project:{id:'p',style:{format:'kenburns'},target_minutes:8,
 picture_runs:[['a'],['b'],['c'],['d'],['insert']],slides:[
 {id:'a',narration:'Single paragraph',word_count:2,chapter:'Opening',visual_note:'Carrier',take:{duration:2,narration:'Single paragraph'}},
 {id:'b',narration:'Shared lead',word_count:2,visual_note:'Engraving'},
 {id:'c',narration:'Shared tail',word_count:2,visual_note:'Engraving'},
 {id:'d',narration:'Forced break',word_count:2,visual_note:'Engraving',picture_mode:'new'},
 {id:'insert',narration:'',word_count:0,insert:{kind:'card',seconds:4,text:'Title'}}]}};
const body={}, tools={}, toolbar={children:[],replaceChildren(el){this.children=[el];}};
const layout={classList:{toggle(){}},style:{setProperty(){}}};
const stub={checked:false,hidden:true,setAttribute(){},classList:{toggle(){}},style:{setProperty(){}}};
const $=s=>s==='#tabbody'?body:s==='#script-toolbar'?toolbar:s==='#tabbody .script-tools'?tools:s==='.script-layout'?layout:stub;
scriptCurrent=sid=>{scriptActive=sid;};scriptLoadCheck=()=>{};
paintScript();paintScript();
check(toolbar.children.length===1&&toolbar.children[0]===tools,'repaint replaces shared toolbar controls');
const html=body.innerHTML;
check(!html.includes('script-binder')&&!html.includes('Filter binder'),'no binder');
check(scriptRuns(state.project).map(r=>r.map(s=>s.id).join('+')).join(',')==='a,b+c,d,insert','shots follow description, forced breaks and inserts');
check((html.match(/data-script-shot=/g)||[]).length===4&&html.includes('SHOT 2')&&html.includes('Engraving'),'one section per shot with its description');
check(html.includes('Merge with shot above')&&html.includes('id="script-pane-agent"')&&html.includes('id="script-pane-check"'),'merge control and agent/check panel');
check(html.includes('data-panel="desc:b"')&&html.includes('data-panel="facts:b"')&&html.includes('data-panel="para:c"'),'description, facts and paragraph panels');
for(const sid of ['a','b','c','d'])check(html.includes(`data-para="${sid}" contenteditable="plaintext-only"`),'stable editable selector '+sid);
check(!html.includes('data-para="insert"')&&html.split('data-sid="insert"')[1].includes('saveChapter'),'insert stays non-editable and keeps its chapter');
check(!/\bprompt\(|\bconfirm\(/.test(Function.prototype.toString.call(scriptAgentSend)+scriptAgentApply+scriptNewShot+scriptMergeShot),'agent and shot gestures use no native dialogs');
let focused, caret, scrolled;
const selection={removeAllRanges(){caret=null;},addRange(range){caret=range;}};
window.getSelection=()=>selection;
const cards=state.project.slides.map(s=>{
 const text=s.insert?null:{sid:s.id,focus(){focused=this;}};
 const link={sid:s.id,focus(){focused=this;}};
 return {dataset:{sid:s.id},text,link,unit:{hidden:true},shot:{hidden:true},
  closest(sel){return sel==='.script-unit'?this.unit:this.shot;},
  querySelector(sel){return sel==='[data-para][contenteditable]'?text:sel==='a'?link:null;},
  scrollIntoView(){scrolled=s.id;}};
});
const document={querySelectorAll:sel=>sel==='.script-card'?cards:[],createRange:()=>({
 selectNodeContents(node){this.node=node;},collapse(start){this.start=start;}})};
const head=html.split('data-script-shot="b"')[1].match(/class="script-shot-select" onclick="([^"]+)"/)[1];
eval(head);
check(focused===cards[1].text&&caret.node===focused&&caret.start&&scriptActive==='b','shot header puts the caret in its first paragraph');
check(!cards[1].unit.hidden&&!cards[1].shot.hidden&&scrolled==='b','header reveals and scrolls paragraph');
scriptWorkspaceKey({key:'ArrowDown',ctrlKey:true,preventDefault(){}});
check(focused===cards[2].text&&scriptActive==='c','next shortcut sets caret');
scriptWorkspaceKey({key:'ArrowUp',metaKey:true,preventDefault(){}});
check(focused===cards[1].text,'previous shortcut sets caret');
scriptLocate('insert');check(focused===cards[4].link,'insert navigation keeps Edit link reachable');
print('page shots, toolbar and caret passed');
"""
    script = tmp_path / 'page-writing.js'
    script.write_text('const window={addEventListener(){}};\n' + source + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'page shots, toolbar and caret passed' in result.stdout

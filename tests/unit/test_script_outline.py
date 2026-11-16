"""Synthetic corkboard gestures; no browser, models, renders or user media."""
import shutil
import subprocess
from pathlib import Path

import pytest

from app import main, store, undo
from app.schema import Project, Slide


def test_shot_move_rechapters_atomically_and_add(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='corkboard', idea='Synthetic shots', slides=[
        Slide(id='a', chapter='First', narration='A', picture_mode='new'),
        Slide(id='b', narration='B', picture_mode='hold', take={'path':'takes/b.wav'}),
        Slide(id='c', chapter='Second', narration='C', picture_mode='new')])
    store.save(p)
    before = store.load(p.id).to_dict()
    result = main.edit_section(p.id, dict(op='move', ids=['a','b'], to='', chapter='Second', version=p.updated_at))
    moved = store.load(p.id)
    assert [s.id for s in moved.slides] == ['c','a','b']
    assert [s.chapter for s in moved.slides] == ['Second','','']
    assert moved.picture_runs() == [['c'],['a','b']]
    assert moved.slide('b').take == before['slides'][1]['take']
    assert len(undo.read(store.project_dir(p.id))['states']) == 2
    main.undo_project(p.id)
    assert store.load(p.id).to_dict() == before
    result = main.edit_section(p.id, dict(op='add', to='c', chapter='First', version=store.load(p.id).updated_at))
    assert len(result['slides']) == 4
    added = result['slides'][2]
    assert not added['narration'] and not added['take']
    assert result['picture_runs'] == [['a','b'],[added['id']],['c']]


def test_corkboard_cards_and_keyboard(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = Path('static/js/tabs/script_outline.js').read_text()
    harness = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const state={project:{id:'p',updated_at:1,slides:[
 {id:'a',chapter:'One',narration:'First line\nMore',word_count:4,visual_note:'A door'},
 {id:'b',narration:'Shared shot',word_count:2,take:{narration:'Shared shot'}},
 {id:'c',chapter:'Two',narration:'Third',word_count:1}]}};
const scriptRuns=()=>[[state.project.slides[0],state.project.slides[1]],[state.project.slides[2]]];
const scriptVoice=s=>s.take?'Recorded':'Not voiced', pictureKind=()=> 'archive', esc=s=>String(s||'');
const scriptPreference=(k,d)=>d, scriptShotFit=()=>{};
const body={}, $=()=>body, document={querySelectorAll:()=>[]};
planOutline={chapters:['One','Two','Empty'],sections:[{id:'beat',heading:'Unwritten',chapter:'Empty',words:100}]};
planDraw();
check(body.innerHTML.includes('2 paragraphs · 6 words'),'shared shot count');
check((body.innerHTML.match(/class="plan-beat outline-shot"/g)||[]).length===2,'one card per server picture run');
check(body.innerHTML.includes('outline-unwritten')&&body.innerHTML.includes('Unwritten'),'unwritten beat stays dashed');
check(body.innerHTML.indexOf('class="plan-hook"')<body.innerHTML.indexOf('class="plan-columns"'),'hook above columns');
check(body.innerHTML.includes('Works muted: needs an image'),'muted check');
check(body.innerHTML.includes('class="plan-premise" >'),'scripted premise collapsed');
check(body.innerHTML.includes('class="btn" onclick="planWrite()" >Rewrite changed beats</button>'),'scripted rewrite secondary');
let route; const go=value=>{route=value;}; outlineOpen(0);
check(state.focusSlide==='a'&&route==='#/p/p/script','Write caret target');
let move; outlineMove=(...args)=>{move=args;};
const event={target:body,currentTarget:body,key:'ArrowRight',altKey:true,preventDefault(){}};
outlineKey(event,0,0);
check(move[0].join(',')==='a,b'&&move[1]===1,'Alt right moves whole shot');
event.key='ArrowDown';outlineKey(event,0,0);
check(move[1]===1,'last shot in chapter cannot move down');
planOutline={sections:[{id:'x',heading:'Only beat',chapter:'Start',words:100}]};
state.project.slides=[];planDraw();
check(body.innerHTML.includes('Only beat')&&!body.innerHTML.includes('outline-shot"'),'outline-only beats');
check(body.innerHTML.includes('class="plan-premise" open>'),'outline-only premise open');
check(body.innerHTML.includes('class="btn" onclick="planWrite()" >Write the script</button>'),'first write secondary beside shell Next');
print('corkboard passed');
'''
    script = tmp_path / 'outline.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_beat_only_corkboard_columns(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    harness = r'''
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
const state={project:{slides:[
 {id:'a',beat:'Opening'}, {id:'b',beat:'Opening'},
 {id:'c',beat:'Ending'}, {id:'d',chapter:'Override',beat:'Opening'},
 {id:'e',beat:'Missing'}, {id:'f'}]}};
const scriptRuns=()=>state.project.slides.map(s=>[s]);
planOutline={chapters:['One','Two','Empty'],sections:[
 {heading:'Opening',chapter:'One'}, {heading:'Ending',chapter:'Two'}]};
const cols=outlineColumns(), shots=name=>cols.find(c=>c.name===name).shots.join(',');
check(shots('One')==='0,1','all shots with matching beat share column');
check(shots('Two')==='2','second beat maps to its chapter');
check(shots('Override')==='3','explicit chapter overrides beat');
check(shots('')==='4,5','only unmatched shots are unchaptered; no inherited chapter');
check(shots('Empty')==='','empty outline chapters retained');
check(state.project.slides.every(s=>s.chapter!=='One'),'display does not mutate slides');
'''
    script = tmp_path / 'beat_columns.js'
    script.write_text(Path('static/js/tabs/script_outline.js').read_text() + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_board_writing_keeps_chapter_columns(tmp_path, monkeypatch):
    monkeypatch.setattr('app.llm.complete_json', lambda *a, **kw: [])
    from app import plan_board, script_gen
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    from scripts.ui_snapshots import seed_outline
    seed_outline()
    monkeypatch.setattr(script_gen, '_write_section', lambda p, outline, i: [
        dict(kind='main', beat=outline['sections'][i]['heading'], text='Synthetic words', visual='A station')])
    plan_board.write('psnapoutline', lambda _: None)
    p = store.load('psnapoutline')
    assert [s.chapter for s in p.slides] == [f'Chapter {i+1}' for i in range(6)]
    assert len(p.picture_runs()) == 6

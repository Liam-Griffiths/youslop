"""Private notes and deterministic inspector gestures; synthetic data only."""
import asyncio
import json
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest

from app import main, store, script_gen, shot_list
from app.schema import Project, Slide


def test_note_roundtrip_patch_and_output(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    assert Slide.from_dict({'narration': 'Old project', 'future': True}).note == ''
    p = Project(id='private', idea='Synthetic', slides=[Slide(id='one', narration='Spoken words.',
        visual_note='Station platform', take={'path': 'takes/kept.wav', 'duration': 2})])
    store.save(p)
    private = 'PRIVATE NEVER SPEAK THIS'
    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            path = '/api/projects/private/slides/one'
            assert (await c.patch(path, json={'note': private})).status_code == 200
            assert (await c.patch(path, json={'note': []})).status_code == 400
    asyncio.run(run())
    fresh = store.load(p.id)
    s = fresh.slides[0]
    assert s.note == private
    assert Project.from_dict(fresh.to_dict()).slides[0].note == private
    assert s.narration == 'Spoken words.' and s.take == {'path': 'takes/kept.wav', 'duration': 2, 'words': []}
    assert private not in json.dumps([shot.__dict__ for shot in shot_list.build(fresh)])
    prompts = []
    def complete(prompt, **kw):
        prompts.append(prompt)
        return {'text': 'Rewritten words.'}
    monkeypatch.setattr(script_gen, 'complete_json', complete)
    script_gen.rewrite_slide(fresh, s, 'Tighten')
    assert prompts and all(private not in prompt for prompt in prompts)


def test_fact_matching_and_caret(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = Path('static/js/tabs/script-writing.js').read_text()
    harness = r'''
const check=(x,m)=>{if(!x)throw Error(m);};
const s={id:'a',beat:'Opening',narration:'Station platform clock'};
const state={project:{id:'p',slides:[s],research:{facts:[
 {claim:'Ocean currents'}, {claim:'Station clock',source:'Archive',date:'1920'},
 {claim:'Unrelated',beat:'Opening'}, {claim:'Unrelated',slide_id:'a'},
 {claim:'Station platform',slide_id:'b'}]}}};
check(scriptFactRows(state.project,s).map(r=>r.index).join(',')==='3,2,1,0,4','explicit then beat then overlap, stable ties');
check(scriptFactRows(state.project,s,'ARCHIVE 1920').length===1,'source/date search');
check(scriptFactRows(state.project,s,'missing').length===0,'unmatched search');
scriptDrafts.set('a',{text:'Ocean currents'});
check(scriptFactRank({claim:'Ocean currents'},s)===2,'match unsaved narration');scriptDrafts.clear();
let range={startContainer:'text',endContainer:'text',cloneRange(){return {...this};}};
let selected=range, focused=false, inserted, drafted;
const el={contains:n=>n==='text',focus(){focused=true;},innerText:'Station platform clock'};
window.getSelection=()=>({rangeCount:1,getRangeAt:()=>selected,removeAllRanges(){},addRange(r){selected=r;}});
const document={querySelector:()=>el,execCommand(cmd,ui,text){inserted={cmd,text,range:selected};}};
scriptInput=(node,sid)=>{drafted=sid;};
scriptActive='a';scriptSaveCaret(el,'a');selected={startContainer:'inspector'};
scriptInsertFact(1);
check(focused&&inserted.cmd==='insertText'&&inserted.text==='Station clock'&&inserted.range.startContainer==='text'&&drafted==='a','restore saved narration caret and queue edit');
print('inspector matching and caret passed');
'''
    path = tmp_path / 'inspector.js'
    path.write_text('const window={addEventListener(){}};\n' + source + harness)
    r = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert r.returncode == 0, r.stdout + r.stderr


def test_notes_do_not_invalidate_picture_caches(tmp_path, monkeypatch):
    from app import render, stages
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='notecache', idea='Synthetic', slides=[Slide(id='a', narration='Station clock.')])
    groups = [[(p.slides[0], 3.0)]]
    before = render._proxy_key(p, groups, 0, None)
    signature = stages.render_signature(p)
    p.slides[0].note = 'Private note changed'
    assert render._proxy_key(p, groups, 0, None) == before
    assert stages.render_signature(p) == signature

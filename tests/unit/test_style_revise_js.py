"""Exercise proposal review in GJS with a tiny DOM; no browser or Node."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_proposal_review(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = Path('static/js/tabs/script.js').read_text()
    script = tmp_path / 'style.mjs'
    script.write_text('''
const check = (ok, msg) => { if (!ok) throw Error(msg); };
const esc = s => String(s).replaceAll('<','&lt;');
let calls = [], messages = [], pending, result, refreshes = 0, watched;
const watchJob = (id, kind, done) => { watched = {id,kind,done}; };
const api = async (url, opts) => {
  calls.push([url,JSON.parse(opts.body)]);
  if (pending) { await pending; pending = null; }
  return result;
};
const state = {project:{id:'p',slides:[{id:'one',word_count:5},{id:'two',word_count:5}]},tab:'script'};
const summary = {};
const $ = () => summary;
const fmtTime = n => String(n);
const toast = msg => messages.push(msg);
function host(sid) {
  const fields = Object.fromEntries(['textarea','.script-word-count','.script-voice'].map(k => [k,{style:{}}]));
  return {dataset:{styleProposal:sid},innerHTML:'', buttons:[{},{}],
    querySelectorAll(){return this.buttons;},
    closest(){return {querySelector:k => fields[k]};},
    replaceChildren(){this.innerHTML='';}};
}
const hosts = [host('one'),host('two')];
const document = {querySelectorAll:() => hosts};
''' + source + '''
scriptLoadCheck = () => { refreshes++; };
const proposals = ['one','two'].map(slide_id => ({slide_id,before:'<old>',after:'<new>',reasons:['Reason']}));
const button = {textContent:'Smooth flagged lines'};
result = {job:'j1'};
await smoothFlaggedLines(null,button);
check(watched.id === 'j1' && watched.kind === 'smooth flagged lines','job watched');
check(hosts.every(h => !h.innerHTML),'no proposals before completion');
watched.done({state:'done',result:proposals});
check(calls.length === 1 && calls[0][1].slides === undefined,'all paragraphs request');
check(!button.disabled && button.textContent === 'Smooth flagged lines','button restored');
check(hosts.every(h => h.innerHTML.includes('<del>&lt;old>') && h.innerHTML.includes('<ins>&lt;new>')),'escaped before/after');
hosts[1].buttons[1].onclick();
check(!hosts[1].innerHTML && calls.length === 1,'reject does not save');
hosts[1].innerHTML = 'Another pending proposal';
result = {id:'one',narration:'New words',word_count:2,take:{narration:'Old words'}};
await hosts[0].buttons[0].onclick();
check(calls[1][0].endsWith('/style/apply') && calls[1][1].before === '<old>','apply sends proposal');
check(state.project.slides[0].narration === 'New words' && refreshes === 1,'applied and checked');
check(!hosts[0].innerHTML && hosts[1].innerHTML === 'Another pending proposal','other proposal preserved');
result = {job:'j2'};
await smoothFlaggedLines('two',button);
watched.done({state:'done',result:[]});
check(calls.at(-1)[1].slides[0] === 'two' && !hosts[1].innerHTML,'paragraph request and old proposal cleared');
check(messages.at(-1) === 'No safe changes proposed.','empty feedback');
await smoothFlaggedLines(null,button);
const late = watched;
state.project = {id:'another'};
late.done({state:'done',result:proposals});
check(hosts.every(h => !h.innerHTML),'navigation ignores late job result');
state.project = {id:'p'};
let release;
pending = new Promise(r => release = r);
const request = smoothFlaggedLines(null,button);
state.project = {id:'another'};
result = proposals;
release(); await request;
check(hosts.every(h => !h.innerHTML),'navigation ignores late result');
''')
    run = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert run.returncode == 0, run.stderr


def test_style_actions_refresh_with_findings(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = Path('static/js/tabs/script.js').read_text()
    script = tmp_path / 'findings.mjs'
    script.write_text('''
const check = (ok, msg) => { if (!ok) throw Error(msg); };
const state = {project:{id:'p',slides:[{id:'one'},{id:'two'}]},tab:'script'};
const esc = String;
let findings = [];
const api = async () => ({findings,counts:{},rules:[]});
const all = {}, results = {};
const $ = selector => selector === '[data-style-all]' ? all : results;
const actions = ['one','two'].map(styleSlide => ({dataset:{styleSlide},hidden:true}));
const document = {querySelectorAll: selector => selector === '[data-style-slide]' ? actions : []};
''' + source + '''
await scriptLoadCheck();
check(all.disabled && all.title.includes('No style findings'),'clean script disables all with reason');
check(actions.every(b => b.hidden),'clean cards hide action');
findings = [{code:'script.style',slide_id:'two',level:'P3',msg:'Rhythm'},
            {code:'script.empty',slide_id:'one',level:'P0',msg:'Empty'}];
await scriptLoadCheck();
check(!all.disabled && !all.title,'style findings enable all');
check(actions[0].hidden && !actions[1].hidden,'only style findings show paragraph action');
findings = [];
await scriptLoadCheck();
check(all.disabled && actions.every(b => b.hidden),'refresh removes resolved or dismissed actions');
''')
    run = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert run.returncode == 0, run.stderr

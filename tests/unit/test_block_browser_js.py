"""Browser queue and slide application contracts using GJS, without Chromium."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_preview_queue_and_application(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = Path('static/js/tabs/blocks_browser.js').read_text()
    script = tmp_path / 'blocks.mjs'
    script.write_text('''
const esc = s => String(s ?? '');
let calls = [], resolve;
const api = (url,options) => {
  calls.push([url,JSON.parse(options.body)]);
  return new Promise(r => { resolve = r; });
};
const document = {querySelectorAll:() => []};
const target = {isConnected:true, querySelector:() => null,
  matches:() => true, classList:{contains:() => false}};
const assert = (ok,msg) => { if (!ok) throw Error(msg); };
''' + source + '''
const b = {ref:'number_slam'};
const first = requestBlockPreview(b,'16:9','trial',{},target);
await requestBlockPreview(b,'16:9','motion',{},target);
await requestBlockPreview(b,'9:16','trial',{title:'Newest'},target);
assert(calls.length === 1,'one in flight');
resolve({stale:true});
await Promise.resolve(); await Promise.resolve();
assert(calls.length === 2,'one pending request replaces older pending');
assert(calls[1][1].aspect === '9:16' && calls[1][1].values.title === 'Newest','newest wins');
resolve({disabled:true}); await first;
assert(!blockPreviewBusy,'gate released');
const selection = {block:'number_slam',vars:{title:'Mine'}};
const apply = applyBlockToSlide('p1','s1',selection);
assert(calls.at(-1)[0] === '/api/projects/p1/slides/s1','existing PATCH path');
assert(calls.at(-1)[1].cues.blocks[0] === selection ||
       calls.at(-1)[1].cues.blocks[0].vars.title === 'Mine','scratch applied');
assert(Object.keys(calls.at(-1)[1].cues).join() === 'blocks','other cue keys absent');
resolve({}); await apply;
assert(blockTrialField('title',{type:'text',default:'sample',max_length:20},0).includes('type="text"'),'typed input');
assert(blockTrialField('data',{type:'table',default:[]},0).includes('Paste CSV'),'table entry');
''')
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

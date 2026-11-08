"""Exercise preset form actions offline with the system JS runtime."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_save_both_update_count_and_promote(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = Path('static/js/tabs/blocks_browser.js').read_text()
    script = tmp_path / 'preset-flow.mjs'
    script.write_text('''
const nodes = {};
const $ = key => nodes[key] ||= {value:'',checked:false,textContent:'',innerHTML:''};
const esc = s => String(s ?? '');
const assert = (ok,msg) => { if (!ok) throw Error(msg); };
const calls = [], saved = {'projects/p1':[], 'channels/c1':[]};
let serial = 0;
const api = async (url,options={}) => {
  const body = JSON.parse(options.body || '{}'); calls.push([url,options.method || 'GET',body]);
  if (url === '/api/projects') return [{id:'p1',title:'Project'}];
  if (url.endsWith('/slides')) return {slides:2};
  if (url.endsWith('/promote')) return {id:'channel-copy'};
  const owner = url.includes('/projects/') ? 'projects/p1' : 'channels/c1';
  if (options.method === 'POST') { const item = {...body,id:'pr'+(++serial)}; saved[owner].push(item); return item; }
  if (options.method === 'PATCH') return body;
  return saved[owner];
};
''' + source + '''
paintBlocksGrid = () => {};
const b = {ref:'title_card',name:'Title',aspects:['16:9']};
blocksBrowser = {items:[b],presets:[],channels:[{id:'c1',name:'Series'}],options:{project:'p1',channel:'c1'}};
await blockPresetTarget(b,'16:9',() => ({title:'Our title'}));
$('#preset-name').value = 'Our card'; $('#preset-scope').value = 'both';
await $('#preset-create').onclick();
assert(saved['projects/p1'].length === 1 && saved['channels/c1'].length === 1,'save both scopes');
const projectPreset = blocksBrowser.presets.find(p => p.scope === 'project');
blocksBrowser.trial = {ref:b.ref,preset:{id:projectPreset.id,scope:'project'}};
await blockPresetTarget(b,'16:9',() => ({title:'Changed'}));
$('#preset-name').value = 'Changed card';
await $('#preset-update').onclick();
assert(calls.at(-2)[1] !== 'POST' && !calls.some(c => c[0].endsWith('/slides')),'edit never updates slides');
await $('#preset-count').onclick();
assert(calls.at(-1)[1] === 'GET' && $('#preset-affected').innerHTML.includes('Update 2 slides'),'count before update');
await $('#preset-apply-slides').onclick();
assert(calls.at(-1)[0].endsWith('/slides') && calls.at(-1)[1] === 'POST','explicit update');
await $('#preset-promote').onclick();
assert(calls.at(-1)[1] === 'GET' && $('#preset-promotion').innerHTML.includes('2 slides'),'promotion counted first');
assert(!$('#preset-move').checked && !$('#preset-repoint').checked,'copy keeps source and provenance by default');
$('#preset-move').checked = true; $('#preset-repoint').checked = true;
await $('#preset-promote-confirm').onclick();
const promote = calls.find(c => c[0].endsWith('/promote'));
assert(promote[2].move && promote[2].point_slides,'explicit move and repoint sent');
assert(blockPriority({ref:'a',channels:['c1'],channel_order:{c1:0}},[],'c1') >
       blockPriority({ref:'b',channels:['c1'],channel_order:{c1:1}},[],'c1'),'pin order ranks projects');
''')
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

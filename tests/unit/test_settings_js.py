"""Settings provider switches, section routing and saves without a browser or Node."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app import settings


def test_settings_providers_routes_and_unsaved_values(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    fields = [dict(key=f.key, group=f.group, options=[dict(value=v, label=l) for v, l in f.options],
                   value='', default=f.default, label=f.label,
                   secret=f.secret) for f in settings.FIELDS if f.group != 'Internal']
    core = Path('static/js/core.js').read_text()
    # Exercise the real routing fast path; falling through would replace the form.
    route_start = core.split('async function routeView() {', 1)[1].split('  resetShell();', 1)[0]
    harness = r'''
const loop = new imports.gi.GLib.MainLoop(null, false);
const assert = (ok, message) => {if (!ok) throw Error(message);};
const settingsDirty = new Set(), nodes = {}, controls = [], rows = [], diagnostics = [];
const location = {hash:'#/settings/writing'}, canonicalHash = h => h;
const esc = s => String(s ?? ''), loadingLine = () => 'Loading';
const view = {innerHTML:''}, themeModes = ['system','light','dark'], themeMode = () => 'dark';
const document = {documentElement:{dataset:{}}, querySelector:s => $(s), querySelectorAll:s => {
  if (s === '.settings-nav a') return links;
  if (s === '[data-stt-engine]') return diagnostics;
  if (s.startsWith('[data-setting-key=')) return controls.filter(c => s.includes('"'+c.dataset.settingKey+'"'));
  if (s.startsWith('[data-settings-provider=')) return rows.filter(r => s.includes('"'+r.section+'"'));
  throw Error('Unexpected selector '+s);
}};
const $ = s => s.startsWith('[data-setting-key=') ? document.querySelectorAll(s)[0] : nodes[s];
function container() {return {children:[], append(row) {
  if (row.parent) row.parent.children = row.parent.children.filter(r => r !== row);
  this.children.push(row); row.parent=this;
}};}
function control(key, value='', original=value) {
  const el = {value, dataset:{settingKey:key, originalValue:original}};
  controls.push(el); nodes['#set_'+key] ||= el; return el;
}
const writes = [], notices = [];
async function api(url, options) {
  assert(url==='/api/settings','Only settings API allowed');
  if (!options) return {fields, data_dir:'/tmp/synthetic'};
  writes.push(JSON.parse(options.body)); return {};
}
const toast = message => notices.push(message);
let focused='', scrolled='', renders=0, links=[];
'''
    checks = r'''
links = SETTINGS_SECTIONS.map(([id]) => ({hash:'#/settings/'+id,
  setAttribute(name, value){this[name]=value;}, removeAttribute(name){delete this[name];}}));
nodes['#settings-screen'] = {};
nodes['#settings-state'] = {};
nodes['#settings-section-select'] = {};
for (const [id] of SETTINGS_SECTIONS) nodes['#settings-'+id+'-heading'] = {
  focus(){focused=id;}, scrollIntoView(){scrolled=id;}
};
for (const section of ['writing','speech']) {
  nodes['#settings-'+section+'-selected'] = container();
  nodes['#settings-'+section+'-alternatives'] = container();
  nodes['#settings-'+section+'-other'] = {open:false};
}
nodes['#settings-local-check'] = {};
for (const f of fields) {
  const el = control(f.key, f.key==='llm_backend'?'lmstudio':f.key==='stt_engine'?'whisper.cpp':'');
  const section = f.group==='Writing model'?'writing':f.group==='Speech-to-text'?'speech':null;
  if (section && settingsFieldBackends(f.key)) rows.push({section, el,
    dataset:{backends:settingsFieldBackends(f.key).join(' '), order:rows.length}});
}
for (const engine of ['whisper.cpp','faster-whisper','openai-whisper','mlx-whisper'])
  diagnostics.push({dataset:{sttEngine:engine}});
settingsUpdateProviders();
const selected = section => nodes['#settings-'+section+'-selected'].children.map(r=>r.el.dataset.settingKey);
assert(selected('writing').includes('lmstudio_url') && selected('writing').includes('ollama_context'),'LM Studio fields');
for (const key of ['openai_api_key','deepseek_api_key','xai_api_key','anthropic_api_key','llm_ollama_url'])
  assert(!selected('writing').includes(key),'Unselected provider exposed: '+key);
assert(selected('speech').join(',')==='stt_folder,stt_executable','whisper.cpp fields');
assert(diagnostics.filter(r=>!r.hidden).length===1,'Only selected engine diagnostics');
nodes['#settings-speech-other'].open = true; settingsUpdateSpeechStatus();
assert(diagnostics.every(r=>!r.hidden),'Other engine diagnostics available');
const secret = nodes['#set_openai_api_key']; secret.value='synthetic-key'; settingsFieldChanged(secret);
assert(controls.filter(c=>c.dataset.settingKey==='openai_api_key').every(c=>c.value==='synthetic-key'),'Voice key synchronized');
const backend = nodes['#set_llm_backend']; backend.value='openai'; settingsFieldChanged(backend);
assert(selected('writing').join(',')==='openai_api_key','OpenAI fields');
backend.value='lmstudio'; settingsFieldChanged(backend);
assert(secret.value==='synthetic-key' && !settingsDirty.has('llm_backend'),'Switch preserves edits; reverted selection clean');
const engine = nodes['#set_stt_engine']; engine.value='faster-whisper'; settingsFieldChanged(engine);
assert(selected('speech').join(',')==='stt_hub_cache,stt_device','faster-whisper fields');
location.hash='#/settings/speech';
await routeView();
assert(focused==='speech' && scrolled==='speech','Section heading focuses and scrolls');
assert(links.find(l=>l.hash===location.hash)['aria-current']==='location','Active nav link');
assert(nodes['#settings-section-select'].value==='speech','Narrow selector synchronized');
assert(settingsDirty.has('openai_api_key') && secret.value==='synthetic-key','Routing keeps unsaved hidden secrets');
assert(nodes['#settings-state'].textContent==='Unsaved changes','Dirty status');
const realRender = renderSettings;
renderSettings = async () => {renders++;};
await saveSettingsForm();
assert(writes.length===1 && writes[0].openai_api_key==='synthetic-key' &&
  writes[0].stt_engine==='faster-whisper' && Object.keys(writes[0]).length===2,'Save changed keys including hidden provider');
assert(renders===1,'Refresh saved settings');
// Render with the real metadata to check section order and unique control IDs.
renderSettings=realRender; settingsUpdateProviders=()=>{}; settingsSelectSection=()=>{};
renderPacks=async()=>{}; checkSpeechEngines=async()=>{};
await renderSettings();
const ids=[...view.innerHTML.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
assert(new Set(ids).size===ids.length,'Unique IDs including the shared voice key');
assert(SETTINGS_SECTIONS.every(([id],i,all)=>!i ||
  view.innerHTML.indexOf('id="settings-'+all[i-1][0]+'-heading"') <
  view.innerHTML.indexOf('id="settings-'+id+'-heading"')),'Sections in ticket order');
assert(!view.innerHTML.includes('New-channel cards:'),'Developer copy removed');
'''
    script = tmp_path / 'settings.js'
    script.write_text(harness + '\nconst fields=' + json.dumps(fields) + ';\n' +
                      Path('static/js/tabs/settings.js').read_text() +
                      '\nasync function routeView() {' + route_start +
                      "throw Error('Section navigation replaced the form');}\n" +
                      '(async()=>{' + checks +
                      '})().catch(e=>{printerr(e.stack);imports.system.exit(1);}).finally(()=>loop.quit());\nloop.run();')
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

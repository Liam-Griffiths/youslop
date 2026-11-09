"""Wizard navigation and saved-field behavior, without a browser or Node."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_wizard_navigation_and_saving(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    harness = r'''
const loop = new imports.gi.GLib.MainLoop(null, false);
const check = (value, message) => { if (!value) throw Error(message); };
const view = {innerHTML:''}, location = {hash:'#/setup'}, navigator = {};
const settingsDirty = new Set(), writes = [];
const esc = value => String(value), toast = message => { throw Error(message); };
const go = hash => {location.hash=hash;};
const $ = selector => ({focus(){}, value:'changed-key', innerHTML:''});
const settingsFieldRow = field => `<input id="set_${field.key}">`;
const localModelCheckRow = () => '';
const data = {paths:{data:'/tmp/synthetic'}, llm:{resolved:'cli',cli_found:false},
 tts:{ready:false,weights:false,detail:'Missing files',model_path:'/tmp/model',voices_path:'/tmp/voices'},
 ffmpeg:{ready:true,detail:'ffmpeg fixture'}, chromium:{ready:false,detail:'Install Chromium'},
 system:{available_ram_mb:null}, youtube:{connected:false}};
async function api(url, options) {
 if(options) { writes.push(JSON.parse(options.body)); return {}; }
 if(url==='/api/setup') return data;
 if(url==='/api/settings') return {fields:[{key:'anthropic_api_key',group:'Writing model'}]};
 throw Error('Unexpected request '+url);
}
'''
    checks = r'''
(async () => {
 await renderSetup();
 check(view.innerHTML.includes('Finish later') && view.innerHTML.includes('Skip'),'ways out');
 await setupAdvance(1);
 settingsDirty.add('anthropic_api_key');
 await setupAdvance(2);
 check(writes.length===1 && writes[0].anthropic_api_key==='changed-key','save touched key');
 check(view.innerHTML.includes('Download voice model'),'download only offered as link');
 check(!view.innerHTML.includes('<audio'),'no voice playback on load');
 await setupAdvance(3,false);
 check(writes.length===1,'skip does not write settings');
 await setupAdvance(4);
 await setupAdvance(5,false);
 check(writes.length===2 && writes[1].setup_complete==='true','finish persists flag');
 check(location.hash==='#/','finish leaves');
 location.hash='#/setup';
 await renderSetup();
 check(view.innerHTML.includes('Where projects live'),'explicit route reopens completed wizard');
})().catch(e => {printerr(e.stack); imports.system.exit(1);}).finally(()=>loop.quit());
loop.run();
'''
    script = tmp_path / 'setup.js'
    script.write_text(harness + Path('static/js/tabs/setup.js').read_text() + checks)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('needed', [False, True])
def test_boot_redirects_only_once(tmp_path, needed):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    harness = r'''
const loop = new imports.gi.GLib.MainLoop(null, false);
const handlers={}, document={documentElement:{dataset:{}},addEventListener(){}};
const localStorage={getItem:()=>null}, window={addEventListener:(name,fn)=>handlers[name]=fn};
let routes=0, requests=0, replacements=0;
const route=()=>routes++;
const location={hash:'#/library',replace(hash){this.hash=hash;replacements++;}};
const toast=message=>{throw Error(message);};
async function api(){requests++; return {setup_needed:NEEDED};}
'''.replace('NEEDED', str(needed).lower())
    checks = r'''
imports.gi.GLib.idle_add(imports.gi.GLib.PRIORITY_DEFAULT_IDLE,()=>{
 try {
  if(requests!==1 || replacements!==EXPECTED) throw Error('one boot decision');
  if(EXPECTED && location.hash!=='#/setup') throw Error('fresh root redirected');
  location.hash='#/'; handlers.hashchange();
  if(requests!==1 || location.hash!=='#/') throw Error('leaving setup must not redirect');
 } catch(e) {printerr(e.stack); imports.system.exit(1);}
 loop.quit(); return false;
});
loop.run();
'''.replace('EXPECTED', str(int(needed)))
    script = tmp_path / 'boot.js'
    script.write_text(harness + Path('static/js/boot.js').read_text() + checks)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

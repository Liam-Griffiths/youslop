"""Kit creation, confirmation and preview caching without model/browser calls."""
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app import ops, paths, store, style_kits as kits, style_previews as previews


def test_home_kit_applied_before_initialization(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    p, _ = ops.prepare_create(dict(idea='How a city moves', kit_id='casefile'))
    saved = store.load(p.id)
    assert saved.style.format == 'casefile' and saved.style_kit['id'] == 'casefile'
    assert all(getattr(saved.style, k) == v for k, v in kits.get('casefile')['look'].items())
    assert 'quote_card' in saved.blocks and saved.slides == []


def test_posters_cache_and_keep_scratch_outside_projects(tmp_path, monkeypatch):
    monkeypatch.delenv('CORKBORED_BLOCK_POSTERS', raising=False)
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    calls = []
    def draw(p, group, *args, **kwargs):
        calls.append(p)
        assert Path(p.id).is_relative_to(tmp_path / '.cache/style-previews')
        return [], '[0:v]null[out]', '[out]'
    def encode(args, **kwargs):
        assert args[args.index('-frames:v')+1] == '1'
        Image.new('RGB',(480,270)).save(args[-1])
    monkeypatch.setattr(previews.render, '_segment_graph', draw)
    monkeypatch.setattr(previews, 'run_graph', encode)
    first = previews.preview('kenburns','poster').path
    assert previews.preview('kenburns','poster').path == first and len(calls) == 1
    assert not (tmp_path / 'projects').exists()
    monkeypatch.setenv('CORKBORED_BLOCK_POSTERS','off')
    assert previews.preview('board','poster').path == previews.SAMPLE
    assert previews.preview('board','motion').status_code == 204


def test_confirmation_cancel_is_read_only(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    harness = r'''
const loop=new imports.gi.GLib.MainLoop(null,false);
const esc=s=>String(s??''), pictureKindLabel=k=>k, toast=e=>{throw Error(e);};
const state={stylePickerContext:'project',styleKits:[{id:'casefile',name:'Casefile'}],project:{id:'p'}};
const nodes={'[data-close]':{},'[data-apply]':{focus(){}},'[role=status]':{}};
const dialog={innerHTML:'',querySelector:s=>nodes[s],close(){this.closed=true;}};
const document={querySelector:()=>dialog};
let calls=[];
const api=async(path,opts)=>{calls.push(JSON.parse(opts.body));return {message:'2 paragraphs follow the default',changes:{}};};
async function run(){
 await chooseStyleKit('casefile');
 if(calls.length!==1 || calls[0].dry_run!==true || !dialog.innerHTML.includes('Apply Casefile?')) throw Error('Missing dry run');
 nodes['[data-close]'].onclick();
 if(!dialog.closed || calls.length!==1) throw Error('Cancel wrote data');
 print('Style confirmation: dry-run only; Cancel unchanged');
}
'''
    script = tmp_path / 'picker.js'
    script.write_text(harness + Path('static/js/tabs/style_picker.js').read_text()
                      + '\nrun().catch(e=>{printerr(e.stack);imports.system.exit(1);}).finally(()=>loop.quit());loop.run();')
    result = subprocess.run([runtime,str(script)],capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

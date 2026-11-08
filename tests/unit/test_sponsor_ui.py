"""Sponsor editor persistence and one-segment builder preview; no browser/LLM."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from app import main, render, store
from app.schema import Project, Slide, SponsorSlot


@pytest.fixture
def sponsor_project():
    p = Project(id='sponsor-ui', idea='Synthetic', use_intro=False, use_outro=False)
    p.slides = [Slide(id=f's{i}', narration='A paragraph.', take={'duration': 10}) for i in range(3)]
    store.save(p)
    return p


def test_editor_persists_and_preserves_takes(sponsor_project):
    pid = sponsor_project.id
    result = main.add_sponsor(pid, {'vars': {'name': 'Example', 'learn': 'Useful tools'},
                                  'script': 'Sponsored by Example.', 'after_slide_id': 's0'})
    ident = result['sponsors'][0]['id']
    p = store.load(pid)
    p.sponsors[0].set_take({'path': 'takes/kept.wav', 'duration': 7})
    p.sponsors[0].history = [{'path': 'takes/older.wav'}]
    store.save(p)
    before = deepcopy(p.sponsors[0].to_dict())
    for patch in ({'variant': 'long'}, {'placement': 'mid', 'after_slide_id': 's1'},
                  {'script': 'New read copy.', 'vars': {'name': 'New name'}}, {'enabled': False}):
        main.patch_sponsor(pid, ident, {**patch, 'take': None, 'history': []})
    p = store.load(pid)
    slot = p.sponsors[0]
    assert slot.take == before['take'] and slot.history == before['history']
    assert slot.variant == 'long' and slot.template == 'sponsor/long.html'
    assert slot.vars['name'] == 'New name'
    assert slot.vars['learn'] == 'Useful tools' and slot.script == 'New read copy.'
    assert not any(s['type'] == 'sponsor' for s in render.timeline(p)['segments'])
    main.patch_sponsor(pid, ident, {'enabled': True})
    tl = render.timeline(store.load(pid))
    read = next(s for s in tl['segments'] if s['type'] == 'sponsor')
    assert tl['segments'][read['index'] - 1]['paragraphs'][-1]['id'] == 's1'
    assert read['duration'] == 7


@pytest.mark.parametrize('patch', [{'variant': 'other'}, {'placement': 'other'},
    {'after_slide_id': 'missing'}, {'vars': {'name': 'x' * 65}}, {'vars': {'logo': 'https://x'}},
    {'script': 3}, {'enabled': 'false'}])
def test_bad_fields_do_not_persist(sponsor_project, patch):
    before = store.load(sponsor_project.id).to_dict()
    with pytest.raises(HTTPException) as error:
        main.add_sponsor(sponsor_project.id, patch)
    assert error.value.status_code == 400
    assert store.load(sponsor_project.id).to_dict() == before


@pytest.mark.parametrize('variant,recorded', [('short', True), ('long', True), ('short', False)])
def test_one_quarter_size_proxy_and_cache(sponsor_project, monkeypatch, variant, recorded):
    p = sponsor_project
    p.sponsors = [SponsorSlot(id='read', variant=variant, script='A short read.', after_slide_id='s0',
                             vars={'name': 'Example'}, take={'path': 'takes/kept.wav', 'duration': 7})]
    if not recorded:
        p.sponsors[0].take = None
    calls = []
    def fake_builder(project, template, ctx, out, **kwargs):
        calls.append((template, ctx, kwargs))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b'fake video')
    monkeypatch.setattr('app.scene_builder.render', fake_builder)
    out = render.proxy_ref(p, 'sponsor:read')
    assert len(calls) == 1
    template, ctx, options = calls[0]
    assert template == f'_blocks/sponsor_{variant}/block.html'
    assert options['size'] == (480, 270) and options['seconds'] == (7 if recorded else 2.5)
    assert ctx['sponsor']['name'] == 'Example'
    assert render.proxy_ref(p, 'sponsor:read') == out
    read = next(s for s in render.timeline(p)['segments'] if s['type'] == 'sponsor')
    assert read['ready'] and read['path'] == out['path']
    p.sponsors[0].vars['name'] = 'Changed'
    assert not next(s for s in render.timeline(p)['segments'] if s['type'] == 'sponsor')['ready']
    assert len(calls) == 1  # Reading timeline state never renders.


def test_preview_job_only_requests_one_read(sponsor_project, monkeypatch):
    p = sponsor_project
    p.sponsors = [SponsorSlot(id='read', enabled=False)]
    store.save(p)
    calls = []
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: fn(lambda m: None))
    monkeypatch.setattr(render, 'sponsor_proxy', lambda project, ident, progress, **kw:
                        calls.append((ident, kw)) or {'path': 'cache/preview.mp4'})
    assert main.preview_sponsor(p.id, 'read')['job']['path'] == 'cache/preview.mp4'
    assert calls == [('read', {'audible': True})]


def test_sponsor_drag_runtime(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    harness = r'''
function check(ok, msg) { if (!ok) throw new Error(msg); }
const item = {dataset:{item:'0'}, style:{left:'100px'}, classList:{add(){}},
 onclick(){}, setPointerCapture(){}};
const track = {querySelectorAll:()=>[item]};
const $ = ()=>track;
const sel = {id:'read',kind:'sponsor',t0:10};
const TL = {zoom:10,data:{layers:{sponsors:[sel]}}};
const state = {project:{slides:[{id:'a'},{id:'b'}]}};
const tlParas = ()=>[{id:'a',start:0,duration:10},{id:'b',start:17,duration:10}];
const tlPause = ()=>{};
const tlSelect = ()=>{};
let saves=[];
tlSponsorSave = (id,patch)=>saves.push({id,patch});
const event = (x)=>({button:0,pointerId:1,clientX:x,stopPropagation(){}});
tlWireSponsorDrag();
item.onpointerdown(event(100)); item.onpointermove(event(250));
check(saves.length===0 && item.style.left==='270px','drag is local and snaps');
item.onpointerup();
check(saves.length===1 && saves[0].patch.after_slide_id==='b','drop persists id');
check(saves[0].patch.placement==='mid' && !('at_s' in saves[0].patch),'no sponsored time saved');
item.onpointerdown(event(100)); item.onpointermove(event(250)); item.onpointercancel();
check(saves.length===1 && item.style.left==='100px','cancel restores');
print('sponsor drag passed');
'''
    path = tmp_path / 'sponsor.js'
    path.write_text(Path('static/js/timeline/sponsors.js').read_text() + '\n' + harness)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_audible_preview_only_muxes_existing_take(sponsor_project, monkeypatch):
    p = sponsor_project
    p.sponsors = [SponsorSlot(id='read', take={'path': 'takes/kept.wav', 'duration': 7})]
    before = deepcopy(p.to_dict())
    template, ctx, out = render._sponsor_preview(p, p.sponsors[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b'existing silent proxy')
    commands = []
    def fake_mux(args):
        commands.append(args)
        Path(args[-1]).write_bytes(b'voiced proxy')
    monkeypatch.setattr(render.ffutil, 'run', fake_mux)
    result = render.sponsor_proxy(p, 'read', audible=True)
    assert len(commands) == 1
    args = commands[0]
    assert args[args.index('-c:v') + 1] == 'copy'
    assert str(store.project_dir(p.id) / 'takes/kept.wav') in args
    assert result['path'].endswith('_voice.mp4') and p.to_dict() == before


def test_timeline_proxy_accepts_sponsor_ref(sponsor_project, monkeypatch):
    p = sponsor_project
    p.sponsors = [SponsorSlot(id='read', after_slide_id='s0')]
    store.save(p)
    calls = []
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn, *, cancellable: fn(lambda m: None))
    monkeypatch.setattr(render, 'proxy_ref', lambda project, ref, progress, **kw:
                        calls.append(ref) or {'ref': ref})
    result = main.timeline_proxy(p.id, {'refs': ['sponsor:read']})
    assert calls == ['sponsor:read'] and result['job']['segments'] == [{'ref': 'sponsor:read'}]
    with pytest.raises(HTTPException):
        main.timeline_proxy(p.id, {'refs': ['sponsor:missing']})

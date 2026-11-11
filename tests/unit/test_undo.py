"""Undo uses synthetic projects and recordings; no renders, browser or model."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import httpx
import pytest

from app import edits, jobs, main, store, undo
from app.schema import Project, Slide, SponsorSlot


@pytest.fixture
def saved(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='pundo', idea='Synthetic', slides=[Slide(id='sundo', narration='Hello.')])
    store.save(p)
    return p


def edit(p, patch, gesture='', label='edit'):
    token = undo.edit_source.set((label, gesture))
    try:
        edits.patch_slide_fields(p.slides[0], patch)
        store.save(p)
    finally:
        undo.edit_source.reset(token)


def test_ten_mixed_edits_exact_files_and_branch(saved):
    root = store.project_dir(saved.id)
    versions = [(root / 'project.json').read_bytes()]
    for patch in [{'title_at': .5}, {'title_hold': 2}, {'gap_override': 1},
                  {'chapter': 'Part one'}, {'chapter_hold': 1}, {'title': 'Hello'},
                  {'picture_mode': 'new'}, {'visual_note': 'Door'},
                  {'gap_override': 2}, {'title_at': 1}]:
        edit(saved, patch)
        versions.append((root / 'project.json').read_bytes())
    for expected in reversed(versions[:-1]):
        main.undo_project(saved.id)
        assert (root / 'project.json').read_bytes() == expected
    for expected in versions[1:]:
        main.redo_project(saved.id)
        assert (root / 'project.json').read_bytes() == expected
    main.undo_project(saved.id)
    edit(store.load(saved.id), {'title': 'Branch'})
    with pytest.raises(main.HTTPException, match='Nothing to redo'):
        main.redo_project(saved.id)


def test_coalesce_noops_and_limits(saved, monkeypatch):
    root = store.project_dir(saved.id)
    monkeypatch.setattr(undo.time, 'time', lambda: 42)
    edit(saved, {'title': 'a'}, 'typing')
    edit(saved, {'title': 'ab'}, 'typing')
    edit(saved, {'title': 'ab'}, 'typing')
    assert len(undo.read(root)['states']) == 2
    edit(saved, {'title_hold': 1}, 'other')
    assert len(undo.read(root)['states']) == 3
    main.undo_project(saved.id)
    main.undo_project(saved.id)
    assert store.load(saved.id).slides[0].title == ''
    monkeypatch.setattr(undo, 'MAX_ENTRIES', 3)
    for i in range(6):
        edit(store.load(saved.id), {'title': str(i)})
    assert len(undo.read(root)['states']) == 4
    monkeypatch.setattr(undo, 'MAX_BYTES', 100)
    edit(store.load(saved.id), {'title': 'Oversize'})
    assert (root / 'history/index.json').stat().st_size < 100
    assert store.load(saved.id).slides[0].title == 'Oversize'


def test_audio_survives_older_take_empty_project_branch_and_eviction(saved, monkeypatch):
    root = store.project_dir(saved.id)
    s = saved.slides[0]
    for name in ('old.wav', 'new.wav', 'old.webm', 'new.webm'):
        (root / 'raw' / name).write_bytes(name.encode())
    saved.set_take(s, 'mic', dict(path='raw/old.wav', raw_path='raw/old.webm'))
    store.save(saved)
    token = undo.edit_source.set(('record take', ''))
    saved.set_take(s, 'mic', dict(path='raw/new.wav', raw_path='raw/new.webm'))
    store.save(saved)
    undo.edit_source.reset(token)
    main.undo_project(saved.id)
    p = store.load(saved.id)
    assert p.slides[0].take['path'] == 'raw/old.wav'
    assert p.slides[0].history[0]['path'] == 'raw/new.wav'
    assert p.slides[0].history[0]['reason'] == 'undo'
    assert main.take_history(p.id, s.id)['history'][0]['url'].endswith('raw/new.wav')
    main.redo_project(saved.id)
    assert store.load(saved.id).slides[0].take['path'] == 'raw/new.wav'
    main.undo_project(saved.id)
    token = undo.edit_source.set(('remove paragraph', ''))
    p = store.load(saved.id)
    p.slides = []
    store.save(p)
    undo.edit_source.reset(token)
    assert {t['path'] for t in store.load(p.id).retired_takes} == {'raw/old.wav', 'raw/new.wav'}
    monkeypatch.setattr(undo, 'MAX_ENTRIES', 1)
    for i in range(3):
        p = store.load(p.id)
        p.title = str(i)
        store.save(p)
    assert len(store.load(p.id).retired_takes) == 2
    for name in ('old.wav', 'new.wav', 'old.webm', 'new.webm'):
        assert (root / 'raw' / name).read_bytes() == name.encode()


def test_sponsor_and_camera_take_retention(saved):
    saved.slides[0].on_camera = True
    saved.set_take(saved.slides[0], 'camera', dict(path='takes/camera.wav', video_path='raw/camera.webm'))
    saved.sponsors = [SponsorSlot(id='sponsor', take=dict(path='takes/sponsor.wav'))]
    store.save(saved)
    token = undo.edit_source.set(('remove takes', ''))
    saved.slides = []
    saved.sponsors = []
    store.save(saved)
    undo.edit_source.reset(token)
    assert {t['path'] for t in store.load(saved.id).retired_takes} == {'takes/camera.wav', 'takes/sponsor.wav'}
    main.undo_project(saved.id)
    assert store.load(saved.id).slides[0].take['path'] == 'takes/camera.wav'


def test_job_writes_not_undoable_and_running_jobs_refused(saved):
    edit(saved, {'title': 'User title'})
    ready, finish = threading.Event(), threading.Event()
    def work(progress):
        ready.set()
        assert finish.wait(2)
        with store.lock_for(saved.id):
            p = store.load(saved.id)
            p.render = {'output': 'synthetic.mp4'}
            p.research = {'facts': ['synthetic']}
            p.slides[0].visual_note = 'Job result'
            p.slides.insert(0, Slide(id='job-slide'))
            store.save(p)
    token = undo.edit_source.set(('must not enter job history', ''))
    jid = jobs.start('synthetic', saved.id, work)
    undo.edit_source.reset(token)
    try:
        assert ready.wait(2)
        for restore in (main.undo_project, main.redo_project):
            with pytest.raises(main.HTTPException) as err:
                restore(saved.id)
            assert err.value.status_code == 409
    finally:
        finish.set()
        thread = next(t for t in threading.enumerate() if t.name == 'job-synthetic')
        thread.join(2)
    assert jobs.get(jid)['state'] == 'done'
    main.undo_project(saved.id)
    p = store.load(saved.id)
    assert p.slide('sundo').title == '' and p.slide('sundo').visual_note == 'Job result'
    assert [s.id for s in p.slides] == ['job-slide', 'sundo']
    assert p.render == {'output': 'synthetic.mp4'} and p.research['facts'] == ['synthetic']
    main.redo_project(saved.id)
    assert store.load(saved.id).render == p.render


@pytest.mark.parametrize('writes', [False, True])
def test_restore_only_refuses_writing_jobs(saved, writes):
    edit(saved, {'title': 'User title'})
    ready, finish = threading.Event(), threading.Event()

    def work(progress):
        ready.set()
        assert finish.wait(2)

    jid = jobs.start('undo-guard', saved.id, work, writes=writes)
    try:
        assert ready.wait(2)
        assert jid in {j['id'] for j in jobs.active_for(saved.id)}
        assert (jid in {j['id'] for j in jobs.active_for(saved.id, writing=True)}) == writes
        for restore, title in ((main.undo_project, ''), (main.redo_project, 'User title')):
            if writes:
                with pytest.raises(main.HTTPException) as err:
                    restore(saved.id)
                assert err.value.status_code == 409
            else:
                assert restore(saved.id)['slides'][0]['title'] == title
            assert jobs.get(jid)['state'] == 'running'
    finally:
        thread = next(t for t in threading.enumerate() if t.name == 'job-undo-guard')
        finish.set()
        thread.join(2)
    assert jobs.get(jid)['state'] == 'done'


def test_timeline_proxy_allows_undo_without_overwriting_edit(saved, monkeypatch):
    edit(saved, {'title': 'User title'})
    ready, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(main.render, '_groups_for_preview', lambda p: [[(p.slides[0], 1)]])

    def download(p, progress, only):
        p.slides[0].candidates = [{'id': 'synthetic', 'local_path': 'media/test.jpg'}]
        return []

    def proxy(p, ref, progress, **kwargs):
        ready.set()
        assert finish.wait(2)
        return {'ref': ref}

    monkeypatch.setattr(main.render.media, 'download_chosen', download)
    monkeypatch.setattr(main.render, 'proxy_ref', proxy)
    jid = main.timeline_proxy(saved.id, {'refs': ['0']}, hide='')['job']
    try:
        assert ready.wait(2)
        assert jobs.get(jid)['writes'] is False
        main.undo_project(saved.id)
        p = store.load(saved.id)
        assert p.slides[0].title == ''
        assert p.slides[0].candidates[0]['local_path'] == 'media/test.jpg'
    finally:
        thread = next(t for t in threading.enumerate() if t.name == 'job-timeline proxy')
        finish.set()
        thread.join(2)
    assert jobs.get(jid)['state'] == 'done'
    assert store.load(saved.id).slides[0].title == ''


def test_job_save_leaves_snapshots_untouched(saved, monkeypatch):
    edit(saved, {'title': 'a'}, 'typing')
    edit(saved, {'title_hold': 2}, 'drag')
    root = store.project_dir(saved.id)
    paths = list((root / 'history').glob('*.json.gz'))
    original = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in paths}
    def forbidden(*args):
        pytest.fail('Job save read a compressed snapshot')
    monkeypatch.setattr(undo, 'snapshot', forbidden)
    saved.log.append('Job completed')
    saved.render = {'output': 'synthetic.mp4'}
    store.save(saved)
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in paths} == original
    assert len(undo.read(root)['states']) == 3
    index = root / 'history/index.json'
    unchanged = index.stat().st_mtime_ns
    saved.log.append('Another job')
    store.save(saved)
    assert index.stat().st_mtime_ns == unchanged


def test_jobs_survive_multiple_undos_later_edits_and_restart(saved):
    edit(saved, {'title': 'a'})
    edit(saved, {'title_hold': 2})
    saved.render = {'output': 'synthetic.mp4'}
    saved.slides[0].visual_note = 'First job'
    store.save(saved)
    edit(saved, {'title': 'b'})
    saved.research = {'facts': ['Second job']}
    store.save(saved)
    root = store.project_dir(saved.id)
    # All state is persisted; exercise the restore API without a Project cache.
    for _ in range(2):
        for direction in ('undo', 'redo'):
            for _ in range(3):
                undo.restore(root, direction)
                p = store.load(saved.id)
                assert p.render == {'output': 'synthetic.mp4'}
                assert p.slides[0].visual_note == 'First job'
                assert p.research == {'facts': ['Second job']}
    undo.restore(root, 'undo')
    edit(store.load(saved.id), {'chapter': 'Branch'})
    for _ in range(3):
        undo.restore(root, 'undo')
    assert store.load(saved.id).render == {'output': 'synthetic.mp4'}


def test_snapshot_files_branch_compression_limits_and_legacy_migration(saved, monkeypatch):
    root = store.project_dir(saved.id)
    edit(saved, {'title': 'a'}, 'typing')
    first_paths = set((root / 'history').glob('*.json.gz'))
    edit(saved, {'title': 'ab'}, 'typing')
    assert set((root / 'history').glob('*.json.gz')) == first_paths
    history = undo.read(root)
    latest = undo.snapshot(root, history['states'][history['cursor']])
    assert json.loads(latest['payload'])['slides'][0]['title'] == 'ab'
    edit(saved, {'title': 'b'})
    history = undo.read(root)
    assert all(set(s) == {'seq', 'label', 'gesture', 'time', 'bytes'} for s in history['states'])
    def assert_files():
        history = undo.read(root)
        paths = {undo.snapshot_path(root, s) for s in history['states']}
        assert set((root / 'history').glob('*.json.gz')) == paths
        assert sum(s['bytes'] for s in history['states']) == sum(p.stat().st_size for p in paths)
        return paths
    assert_files()
    undo.restore(root, 'undo')
    edit(store.load(saved.id), {'title': 'Branch'})
    assert_files()
    monkeypatch.setattr(undo, 'MAX_ENTRIES', 2)
    for i in range(5):
        edit(store.load(saved.id), {'title': str(i)})
    assert len(assert_files()) == 3
    # Measure the actual compressed size; the uncompressed project is larger.
    monkeypatch.setattr(undo, 'MAX_BYTES', 2 * max(p.stat().st_size for p in assert_files()))
    edit(store.load(saved.id), {'title': 'Trim bytes'})
    assert sum(p.stat().st_size for p in assert_files()) <= undo.MAX_BYTES
    # Discarding the never-shipped format leaves the live project intact.
    live = (root / 'project.json').read_bytes()
    (root / 'history/index.json').write_text(json.dumps({'cursor': 0, 'states': [
        {'payload': live.decode(), 'label': '', 'gesture': '', 'time': 0}]}))
    assert undo.read(root) == {'states': [], 'cursor': 0}
    assert (root / 'history/index.json').stat().st_size < 100
    assert (root / 'project.json').read_bytes() == live


@pytest.mark.skipif(os.environ.get('YS_SLOW') != '1', reason='Set YS_SLOW=1 for undo storage timing')
def test_large_project_history_timing(saved):
    saved.slides = [Slide(id=f's{i}', narration=f'Paragraph {i}.', candidates=[
        {'id': f'c{j}', 'caption': f'Archive candidate {i}/{j}',
         'url': f'https://example.invalid/{i}/{j}', 'width': 1920, 'height': 1080}
        for j in range(45)]) for i in range(37)]
    payload = undo.encode(saved.to_dict())
    saved.description = 'x' * max(0, 512_000 - len(payload.encode()))
    store.save(saved)
    root = store.project_dir(saved.id)
    assert 500_000 <= (root / 'project.json').stat().st_size <= 600_000
    durations = []
    token = undo.edit_source.set(('edit title', ''))
    try:
        for i in range(110):
            p = store.load(saved.id)
            p.slides[i % 37].title = f't{i}'
            start = time.perf_counter()
            store.save(p)
            durations.append(time.perf_counter() - start)
    finally:
        undo.edit_source.reset(token)
    assert len(undo.read(root)['states']) == 101
    start = time.perf_counter()
    undo.restore(root, 'undo')
    restore_ms = (time.perf_counter() - start) * 1000
    save_ms = sum(durations[-10:]) * 100
    print(f'500 KB / 100 edits: user save {save_ms:.1f} ms; undo {restore_ms:.1f} ms')
    assert save_ms < 60
    assert restore_ms < 150


def test_http_history_context_and_labels(saved, monkeypatch):
    # Match other HTTP tests: this sandbox can stall threadpool wakeups.
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            path = f'/api/projects/{saved.id}'
            response = await client.patch(path + '/slides/sundo', json={'title_at': 1},
                                          headers={'X-Edit-Label': 'move title'})
            assert response.status_code == 200
            response = await client.post(path + '/undo')
            assert response.status_code == 200 and response.json()['edit_label'] == 'move title'
            assert response.json()['slides'][0]['title_at'] is None
            assert (await client.post(path + '/redo')).json()['slides'][0]['title_at'] == 1
            assert (await client.post('/api/projects/missing/undo')).status_code == 404
    asyncio.run(run())
    assert undo.edit_source.get() is None


def test_shortcuts_and_request_labels_without_browser(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS is unavailable')
    source = Path('static/js/core.js').read_text().split('const studioWrites')[1].split('let toastTimer')[0]
    shell = Path('static/js/shell.js').read_text().split('let projectHistoryBusy')[1].split('function paintStageBar')[0]
    harness = r'''
const FormData = class {};
const state = {project:{id:'p'},stage:'edit',rec:{recording:false}};
const TL = {};
let key, calls=[], refreshed=0, message='';
const document = {addEventListener(type,fn){key=fn;}};
const fetch = async (path,opts) => {
 calls.push({path,...opts});
 return {ok:true,text:async()=>JSON.stringify({id:'p',edit_label:'move title'})};
};
let tlInspectorQueue = Promise.resolve();
const tlPause = () => {};
const tlRefreshProject = async () => {refreshed++;};
const paintProjectShell = () => {};
const loadStageStates = () => {};
const toast = text => {message=text;};
function check(ok,msg) {if(!ok)throw new Error(msg);}
function event(editable=false,shift=false) {
 return {key:'z',ctrlKey:true,shiftKey:shift,target:{closest:()=>editable?{}:null},
 preventDefault(){this.prevented=true;}};
}
async function run() {
 await api('/api/projects/p/slides/s',{method:'PATCH',body:'{"title":"a"}'});
 check(calls[0].headers['X-Edit-Label']==='edit title','field label');
 check(calls[0].headers['X-Edit-Gesture'].includes('/slides/s'),'coalesce target');
 let e=event(true); key(e); check(!e.prevented && calls.length===1,'native text undo');
 e=event(); key(e);
 for(let i=0;i<50 && projectHistoryBusy;i++) await Promise.resolve();
 check(e.prevented && calls.at(-1).path.endsWith('/undo'),'Ctrl Z');
 check(refreshed===1 && message==='Undid: move title','refresh and toast');
 e=event(false,true); key(e);
 for(let i=0;i<50 && projectHistoryBusy;i++) await Promise.resolve();
 check(calls.at(-1).path.endsWith('/redo') && message==='Redid: move title','redo');
 state.rec.recording=true;
 const count=calls.length;
 await restoreProjectEdit('undo'); check(calls.length===count,'recording guard');
 print('undo UI runtime passed');
}
run().catch(e=>{printerr(String(e)+e.stack);imports.system.exit(1);});
'''
    script = tmp_path / 'undo.js'
    script.write_text(harness.split('async function run()')[0] + '\nconst studioWrites' + source
                      + '\nlet projectHistoryBusy' + shell + '\nasync function run()' + harness.split('async function run()')[1])
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'undo UI runtime passed' in result.stdout

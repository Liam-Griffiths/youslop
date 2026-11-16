"""Lock enforcement at the save boundary; no browser, media work or models."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest

from app import camera_auto, jobs, layers, main, razor, render, review, stages, store, undo
from app.schema import LAYER_ROLES, Layer, Project, Slide, SponsorSlot


@pytest.fixture
def locked_project(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='plocks', idea='Locks', slides=[Slide(id='a', title='A',
        narration='First sentence. Second sentence.', take={'path':'takes/a.wav', 'duration':5}),
        Slide(id='b', title='B', narration='Next sentence.', take={'path':'takes/b.wav', 'duration':5})])
    p.layers = [Layer(id='open', name='Open'), Layer(id='names', name='Names', order=1, locked=True)]
    p.slides[0].overlays = [dict(id='same', block_id='lower_third_panel', vars={}, at=0, dur=1, layer='open')]
    p.slides[1].overlays = [dict(p.slides[0].overlays[0], layer='names')]
    store.save(p)
    return p


@pytest.mark.parametrize('change', ['resize', 'replace', 'delete', 'source', 'destination', 'paragraph', 'unlock', 'fallback'])
def test_locked_graphic_moves_are_atomic(locked_project, change):
    p = locked_project
    root = store.project_dir(p.id)
    original = (root/'project.json').read_bytes()
    history = undo.read(root)
    p.slides[0].title = 'Unrelated batch change'
    if change == 'resize':
        p.slides[1].overlays[0]['dur'] = 2
    elif change == 'replace':
        p.slides[1].overlays[0]['block_id'] = 'stat_card'
    elif change == 'delete':
        p.slides[1].overlays.clear()
    elif change == 'source':
        p.slides[1].overlays[0]['layer'] = 'open'
    elif change == 'destination':
        p.slides[0].overlays[0]['layer'] = 'names'
    elif change == 'paragraph':
        p.slides[0].overlays.append(p.slides[1].overlays.pop())
    elif change == 'unlock':
        p.layers[1].locked = False
        p.slides[1].overlays.clear()
    elif change == 'fallback':
        p.layers.pop(0)  # missing/unknown assignments now land on the locked track
    with pytest.raises(layers.LockedLayerError, match='Names.*locked'):
        store.save(p)
    assert (root/'project.json').read_bytes() == original
    assert undo.read(root) == history


def test_unrelated_edits_downloads_and_unlock_still_work(locked_project):
    p = locked_project
    p.slides[0].overlays[0]['dur'] = 2
    p.slides[0].title = 'Unrelated title'
    p.music = 'other.wav'
    store.save(p)
    p.layers[1].locked = False
    store.save(p)
    p.slides[1].overlays.clear()
    store.save(p)
    assert not store.load(p.id).slides[1].overlays


@pytest.mark.parametrize('role,change', [
    ('pictures', lambda p: setattr(p.slides[0], 'chosen_id', 'replacement')),
    ('pictures', lambda p: setattr(p.slides[0], 'picture_mode', 'hold')),
    ('voice', lambda p: setattr(p.slides[0], 'narration', 'Replacement words')),
    ('voice', lambda p: setattr(p.slides[0], 'gap_override', 3)),
    ('titles', lambda p: setattr(p.slides[0], 'title_hold', 2)),
    ('captions', lambda p: setattr(p.frame, 'arrive_s', p.frame.arrive_s + .1)),
    ('cues', lambda p: p.slides[0].cues.update(flameboat=[{'kind':'title','text':'New'}])),
    ('chapters', lambda p: setattr(p.slides[0], 'chapter_hold', 1)),
    ('music', lambda p: setattr(p, 'music', 'new.wav')),
    ('stings', lambda p: setattr(p.intro, 'music', 'new.wav')),
    ('sponsors', lambda p: p.sponsors.append(SponsorSlot(id='new', script='Read this'))),
])
def test_all_item_roles_reject_changed_content(locked_project, role, change):
    p = locked_project
    p.layers = [Layer(id=role, role=role, locked=True)]
    # Set up a new baseline without replacing an existing locked graphic.
    p.id = 'role-' + role
    store.save(p)
    change(p)
    with pytest.raises(layers.LockedLayerError):
        store.save(p)


@pytest.mark.parametrize('change', [lambda p: p.slides.reverse(), lambda p: p.slides.pop(0),
    lambda p: setattr(p.slides[0], 'gap_override', 3),
    lambda p: p.slides.append(Slide(narration='Insert a paragraph.')),
    lambda p: p.slides[0].take.update(duration=8)])
def test_upstream_ripple_keeps_locked_items_with_their_paragraph(locked_project, change):
    p = locked_project
    item = p.slides[1].overlays[0].copy()
    change(p)
    store.save(p)
    assert store.load(p.id).slide('b').overlays == [item]


def test_split_rejected_before_touching_audio(locked_project, tmp_path, monkeypatch):
    locked_project.layers.append(Layer(id='voice', role='voice', locked=True))
    store.save(locked_project)
    monkeypatch.setattr(razor, 'timings', lambda *a: pytest.fail('Split read audio before checking locks'))
    with pytest.raises(layers.LockedLayerError):
        razor.prepare(locked_project, locked_project.slides[0], tmp_path, tmp_path, 1)


def test_direct_camera_batch_checks_before_any_work(locked_project, monkeypatch):
    locked_project.layers.append(Layer(id='voice', role='voice', locked=True))
    store.save(locked_project)
    monkeypatch.setattr(camera_auto, 'plan', lambda *a: pytest.fail('Locked batch called a model'))
    with pytest.raises(layers.LockedLayerError):
        camera_auto.edit(locked_project.id, {})


def test_direct_camera_batch_allows_other_locked_roles(locked_project):
    p = locked_project
    p.id = 'camera-notes'
    p.layers = [Layer(id='notes', role='notes', locked=True)]
    p.slides[0].on_camera = True
    p.set_take(p.slides[0], 'camera', {'path':'takes/camera.wav', 'video':'takes/camera.mp4',
        'duration':5, 'cuts':[{'a':1, 'b':2, 'by':'auto'}]})
    store.save(p)
    assert camera_auto.edit(p.id, {'undo':True})['changed'] == ['a']
    assert store.load(p.id).slides[0].takes['camera']['cuts'] == []


def test_metadata_flags_preserve_default_render_signatures(locked_project):
    p = locked_project
    groups = render._groups_for_preview(p)
    before = render._proxy_key(p, groups, 0, None), stages.render_signature(p)
    for track in p.layers:
        track.hidden, track.locked = True, not track.locked
    assert (render._proxy_key(p, groups, 0, None), stages.render_signature(p)) == before


def test_materialized_fallback_ids_and_order_survive_reload(locked_project):
    p = locked_project
    p.id = 'pcollision'
    p.layers = [Layer(id='pictures'), Layer(id='derived:pictures', order=1)]
    rows = layers.rows(p)
    ident = next(row['id'] for row in rows if row['role'] == 'pictures')
    assert ident == 'derived:derived:pictures'
    layers.patch_flags(p, ident, {'locked':True, 'hidden':True})
    store.save(p)
    after = layers.rows(store.load(p.id))
    assert [row['id'] for row in rows] == [row['id'] for row in after]
    assert next(row for row in after if row['id'] == ident)['locked']
    assert next(row for row in after if row['id'] == ident)['hidden']


def test_notes_lock_covers_separate_report_file(locked_project):
    p = locked_project
    p.layers.append(Layer(id='notes', role='notes', locked=True, order=2))
    store.save(p)
    with pytest.raises(layers.LockedLayerError):
        review._write_notes(p.id, {'notes': []})
    with pytest.raises(layers.LockedLayerError):
        review.act(p.id, 'note', 'apply')
    assert not (store.project_dir(p.id)/'review/notes.json').exists()


def test_derived_notes_can_be_locked(locked_project):
    p = locked_project
    review._write_notes(p.id, {'notes':[{'id':'review', 't':1, 'problem':'A note', 'severity':'P2'}]})
    layers.patch_flags(p, 'notes', {'locked':True})
    store.save(p)
    assert next(layer for layer in store.load(p.id).layers if layer.role == 'notes').locked


def test_camera_and_clip_edits_respect_locks(locked_project):
    p = locked_project
    p.id = 'pcamera'
    p.slides[0].on_camera = True
    p.set_take(p.slides[0], 'camera', {'path':'takes/camera.wav', 'video':'takes/camera.mp4',
                                    'duration':5, 'cuts':[]})
    p.layers = [Layer(id='picture', role='pictures', locked=True)]
    store.save(p)
    p.slides[0].takes['camera']['punch'] = True
    with pytest.raises(layers.LockedLayerError):
        store.save(p)
    p = store.load(p.id)
    p.slides[0].takes['camera']['cutaway_cache'] = {'items':[]}
    store.save(p)  # cached suggestions have no effect until applied
    p.id, p.kind = 'pclip', 'clip'
    p.clip = {'in_s':0, 'out_s':10, 'cuts':[], 'reframes':{}}
    store.save(p)
    p.clip['cuts'] = [[1, 2]]
    with pytest.raises(layers.LockedLayerError):
        store.save(p)


@pytest.fixture
def api_request(monkeypatch):
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    def call(pid, method, suffix, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                        base_url='http://127.0.0.1') as client:
                return await client.request(method, f'/api/projects/{pid}{suffix}', **kwargs)
        return asyncio.run(run())
    return call


@pytest.mark.parametrize('role', LAYER_ROLES)
def test_script_writing_and_blank_paragraphs_only_require_voice_unlocked(locked_project, api_request, role):
    p = locked_project
    p.id = 'script-' + role
    p.layers = [Layer(id=role, role=role, name='Custom track', locked=True)]
    for slide in p.slides:
        slide.take, slide.takes = None, {}
    store.save(p)
    root = store.project_dir(p.id)
    before = (root/'project.json').read_bytes()
    history = undo.read(root)
    seconds = render._slide_durations(p, True)[0][1]
    text = ' '.join(['Longer narration.'] * 20)
    edited = api_request(p.id, 'PATCH', '/slides/a', json={'narration':text})
    appended = api_request(p.id, 'POST', '/slides/a/split', json={'append':True})
    if role == 'voice':
        for response in (edited, appended):
            assert response.status_code == 409
            assert response.json()['detail'] == (
                'Voice layer “Custom track” is locked. Unlock it in Edit before editing.')
        assert (root/'project.json').read_bytes() == before
        assert undo.read(root) == history
    else:
        assert edited.status_code == appended.status_code == 200, (edited.text, appended.text)
        saved = store.load(p.id)
        assert saved.slide('a').narration == text and len(saved.slides) == 3
        assert render._slide_durations(saved, True)[0][1] > seconds


RECORDING_ACTIONS = [
    ('/slides/a/take', True, ('voice',)),
    ('/slides/a/camera', True, ('pictures', 'voice')),
    ('/camera-paragraph', True, ('pictures', 'voice')),
    ('/presenter', True, ('pictures', 'voice')),
    ('/voice-over', False, ('voice',)),
    ('/slides/a/voice-over', False, ('voice',)),
    ('/takes/reprocess', False, ('voice',)),
    ('/sponsors/ad/voice', False, ('sponsors',)),
    ('/sponsors/ad/take', True, ('sponsors',)),
    ('/camera-auto-edit', False, ('pictures', 'voice')),
]


@pytest.mark.parametrize('action', RECORDING_ACTIONS, ids=lambda action: action[0])
@pytest.mark.parametrize('role', ['notes', 'titles', 'captions'])
def test_recording_endpoints_allow_unrelated_locked_roles(locked_project, api_request, monkeypatch, action, role):
    p = locked_project
    p.id = 'recording-' + role
    p.layers = [Layer(id=role, role=role, locked=True)]
    p.sponsors = [SponsorSlot(id='ad', script='Read this sponsor.')]
    p.slides[0].take['raw_path'] = 'raw/stub.webm'
    store.save(p)
    monkeypatch.setattr(main, '_engine_ready', lambda *a: None)
    monkeypatch.setattr(main, '_voice_one', lambda *a: {'path':'takes/stub.wav', 'duration':6})
    monkeypatch.setattr(main.audio_mod, 'process_take', lambda *a: {'duration':6})
    monkeypatch.setattr(main.words_mod, 'estimate', lambda *a: [])
    def camera_take(raw, wav, mp4, voice):
        wav.write_bytes(b'audio stub')
        mp4.write_bytes(b'video stub')
        return {'duration':6, 'av_offset':0, 'sync_warning':False}
    monkeypatch.setattr(main.camera, 'process_camera_take', camera_take)
    monkeypatch.setattr(main.ffutil, 'duration', lambda *a: 6)
    monkeypatch.setattr(main.ffutil, 'dimensions', lambda *a: (640, 360))
    monkeypatch.setattr(main.ffutil, 'has_audio', lambda *a: True)
    def run_job(kind, pid, fn, **kwargs):
        fn(lambda message: None)
        return 'stub-job'
    monkeypatch.setattr(main.jobs, 'start', run_job)
    suffix, upload, _ = action
    kwargs = {'files':{'file':('stub.webm', b'x'*4096, 'video/webm')}} if upload else {'json':{'undo':True}}
    response = api_request(p.id, 'POST', suffix, **kwargs)
    assert response.status_code == 200, response.text
    assert store.load(p.id).layers[0].locked


@pytest.mark.parametrize('action,role', [(action, role) for action in RECORDING_ACTIONS for role in action[2]])
def test_recording_endpoints_preflight_each_changed_role(locked_project, api_request, monkeypatch, action, role):
    p = locked_project
    p.id = 'blocked-' + role
    p.layers = [Layer(id=role, role=role, name='Custom track', locked=True)]
    store.save(p)
    monkeypatch.setattr(main.jobs, 'start', lambda *a, **k: pytest.fail('Locked endpoint started work'))
    suffix, upload, _ = action
    kwargs = {'files':{'file':('stub.webm', b'x'*4096, 'video/webm')}} if upload else {'json':{}}
    before = (store.project_dir(p.id)/'project.json').read_bytes()
    response = api_request(p.id, 'POST', suffix, **kwargs)
    assert response.status_code == 409, response.text
    assert role.capitalize() + ' layer “Custom track” is locked.' in response.json()['detail']
    assert (store.project_dir(p.id)/'project.json').read_bytes() == before
    assert not list((store.project_dir(p.id)/'raw').iterdir())


def test_job_save_after_lock_reports_error_without_project_or_history_writes(locked_project, monkeypatch, capsys):
    p = locked_project
    ready, release = threading.Event(), threading.Event()
    workers = []
    real_thread = threading.Thread
    def thread(**kwargs):
        worker = real_thread(**kwargs)
        workers.append(worker)
        return worker
    monkeypatch.setattr(jobs, 'threading', SimpleNamespace(Thread=thread))
    monkeypatch.setattr(jobs, '_JOBS', {})
    def work(progress):
        stale = store.load(p.id)
        stale.slides[0].title = 'Must not be partially saved'
        stale.slides[0].overlays[0]['dur'] = 2
        ready.set()
        assert release.wait(2)
        store.save(stale)
    jid = jobs.start('synthetic edit', p.id, work)
    try:
        assert ready.wait(1)
        token = undo.edit_source.set(('lock Open', ''))
        try:
            main.patch_layer_flags(p.id, 'open', {'locked':True})
        finally:
            undo.edit_source.reset(token)
        root = store.project_dir(p.id)
        before = (root/'project.json').read_bytes()
        history = {f.name:f.read_bytes() for f in (root/'history').iterdir()}
    finally:
        release.set()
        workers[0].join(2)
    assert not workers[0].is_alive()
    job = jobs.get(jid)
    assert job['state'] == 'error' and job['result'] is None
    assert 'Graphics layer “Open” is locked. Unlock it in Edit' in job['error']
    assert job['log'][-1]['m'].startswith('FAILED: Graphics layer')
    assert (root/'project.json').read_bytes() == before
    assert {f.name:f.read_bytes() for f in (root/'history').iterdir()} == history
    assert 'LockedLayerError' in capsys.readouterr().err


def test_http_persistence_history_and_atomic_409s(locked_project, monkeypatch):
    p = locked_project
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    monkeypatch.setattr(main.jobs, 'start', lambda *a, **kw: pytest.fail('Locked edit started a job'))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            path = '/api/projects/' + p.id
            r = await c.patch(path+'/layers/names', json={'locked':False}, headers={'X-Edit-Label':'unlock Names'})
            assert r.status_code == 200
            assert not store.load(p.id).layers[1].locked
            assert (await c.post(path+'/undo')).json()['edit_label'] == 'unlock Names'
            assert store.load(p.id).layers[1].locked
            assert (await c.post(path+'/redo')).status_code == 200
            assert not store.load(p.id).layers[1].locked
            assert (await c.patch(path+'/layers/names', json={'hidden':True})).status_code == 200
            assert store.load(p.id).layers[1].hidden
            assert (await c.post(path+'/undo')).status_code == 200
            assert not store.load(p.id).layers[1].hidden
            assert (await c.post(path+'/redo')).status_code == 200
            assert store.load(p.id).layers[1].hidden
            # A derived fallback row must persist once, preserving lane order.
            r = await c.patch(path+'/layers/pictures', json={'locked':True})
            assert r.status_code == 200
            assert len({row['id'] for row in r.json()['layers']}) == len(r.json()['layers'])
            assert (await c.patch(path+'/layers/names', json={'locked':True})).status_code == 200
            assert (await c.patch(path+'/layers/voice', json={'locked':True})).status_code == 200
            before = store.load(p.id).to_dict()
            version = before['updated_at']
            for method, suffix, body in [
                ('PATCH', '/slides-batch', {'edits':[{'sid':'a','patch':{'title':'Changed'}},
                    {'sid':'b','patch':{'overlays':[]}}]}),
                ('DELETE', '/slides/b', None),
                ('POST', '/slides/a/split', {'append':True}),
                ('PATCH', '/trim', {'sid':'a','edge':'end','delta':1,'version':version}),
                ('POST', '/sections', {'op':'delete','ids':['a'],'version':version}),
                ('POST', '/camera-auto-edit', {}),
            ]:
                r = await c.request(method, path+suffix, json=body)
                assert r.status_code == 409, (suffix, r.text)
                assert 'locked' in r.json()['detail']
                assert store.load(p.id).to_dict() == before
            for suffix in ['/slides/a/take', '/slides/a/camera', '/presenter', '/camera-paragraph']:
                r = await c.post(path+suffix, files={'file':('test.webm', b'placeholder', 'video/webm')})
                assert r.status_code == 409, (suffix, r.text)
            assert not list((store.project_dir(p.id)/'raw').iterdir())
            assert (await c.post(path+'/voice-over')).status_code == 409
            assert (await c.post(path+'/slides/a/voice-over')).status_code == 409
            assert (await c.patch(path+'/layers/pictures', json={'locked':'yes'})).status_code == 400
    asyncio.run(run())

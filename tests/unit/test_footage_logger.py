"""Logger edits use synthetic manifests only; models and exports are mocked."""
import threading
import asyncio
from types import SimpleNamespace

import pytest
import httpx

from app import footage, footage_labels, jobs
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    footage._save(footage.Shoot('s1', files=[footage.SourceFile('f1', duration=10)],
        clips=[footage.Clip('c1', 'f1', 1, 9), footage.Clip('c2', 'f1', 2, 8)]))
    # Existing HTTP tests bypass a sandbox threadpool wakeup stall.
    async def direct(fn, *args, **kwargs):
        kwargs.pop('limiter', None)
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    monkeypatch.setattr('starlette.responses.anyio.to_thread.run_sync', direct)
    monkeypatch.setattr(jobs, '_JOBS', {})
    def request(method, path, **kwargs):
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url='http://127.0.0.1') as c:
                return await c.request(method, path, **kwargs)
        return asyncio.run(call())
    yield SimpleNamespace(get=lambda p, **kw: request('GET', p, **kw),
                          post=lambda p, **kw: request('POST', p, **kw),
                          patch=lambda p, **kw: request('PATCH', p, **kw))


BASE = '/api/footage/shoots/s1'


def test_patch_clamps_and_persists(client):
    result = client.patch(BASE + '/clips/c1', json={'in_s': -2, 'out_s': 99,
        'labels': [' Lobby ', 'Lobby'], 'starred': True, 'rejected': True, 'note': 'Door'})
    assert result.status_code == 200
    clip = footage.load('s1').clips[0]
    assert (clip.in_s, clip.out_s, clip.labels, clip.starred, clip.rejected, clip.note) == (0, 10, ['Lobby'], True, True, 'Door')
    assert client.get(BASE).json()['vocabulary'] == []


@pytest.mark.parametrize('payload', [{'in_s': 9}, {'out_s': 1}, {'in_s': '2'},
    {'starred': 1}, {'rejected': 'yes'}, {'note': []}, {'labels': 'Lobby'},
    {'labels': ['']}, {'source_path': '/tmp/no'}])
def test_patch_invalid_is_atomic(client, payload):
    before = footage.load('s1').to_dict()
    assert client.patch(BASE + '/clips/c1', json=payload).status_code == 400
    assert footage.load('s1').to_dict() == before


def test_bulk_relabel_and_unknown_clip(client):
    assert client.post(BASE + '/relabel', json={'clip_ids': ['c1', 'c2'], 'add': ['Lobby']}).status_code == 200
    client.post(BASE + '/relabel', json={'clip_ids': ['c1'], 'add': ['Street'], 'remove': ['Lobby']})
    assert [c.labels for c in footage.load('s1').clips] == [['Street'], ['Lobby']]
    assert client.post(BASE + '/relabel', json={'clip_ids': ['c1', 'unknown'], 'add': ['bad']}).status_code == 400
    assert footage.load('s1').clips[0].labels == ['Street']


def test_running_job_blocks_all_mutations(client):
    entered, release = threading.Event(), threading.Event()
    def worker(pr):
        entered.set()
        release.wait(2)
    jid = jobs.start('footage', 's1', worker)
    entered.wait(1)
    try:
        assert client.get(BASE).json()['processing'] is True
        assert client.patch(BASE + '/clips/c1', json={'note': 'Lost'}).status_code == 409
        for action, payload in [('relabel', {'clip_ids': ['c1'], 'add': ['x']}),
                                ('vocabulary', {'labels': ['x']}), ('labels', {'confirm': True}),
                                ('export', {'clip_ids': ['c1'], 'output': '/tmp/no'})]:
            assert client.post(BASE + '/' + action, json=payload).status_code == 409
    finally:
        release.set()
    assert footage.load('s1').clips[0].note == ''


def test_old_manifest_defaults_and_finite_times(client):
    old = footage.Clip.from_dict({'id': 'old', 'file': 'f1', 'future': True})
    assert (old.starred, old.rejected, old.note) == (False, False, '')
    with pytest.raises(ValueError):
        footage.edit_clips('s1', ['c1'], {'in_s': float('nan')})


def test_only_safe_viewing_media_served(client, tmp_path):
    root = footage.shoot_dir('s1')
    (root / 'proxies').mkdir()
    (root / 'originals').mkdir()
    (root / 'originals/f1.mp4').write_bytes(b'ORIGINAL')
    (root / 'proxies/f1.mp4').write_bytes(b'PROXY')
    assert client.get(BASE + '/media/proxies/f1.mp4').content == b'PROXY'
    partial = client.get(BASE + '/media/proxies/f1.mp4', headers={'Range': 'bytes=1-3'})
    assert partial.status_code == 206 and partial.content == b'ROX'
    for path in ['originals/f1.mp4', 'proxies/..%2Foriginals%2Ff1.mp4', 'proxies/shoot.json']:
        assert client.get(BASE + '/media/' + path).status_code == 404
    (root / 'proxies/f1.mp4').unlink()
    (root / 'proxies/f1.mp4').symlink_to(root / 'originals/f1.mp4')
    assert client.get(BASE + '/media/proxies/f1.mp4').status_code == 404


def test_label_confirmation_and_job_identity(client, monkeypatch):
    budget = {'input_tokens': 10, 'output_tokens': 20}
    monkeypatch.setattr(footage_labels, 'estimate', lambda sid: budget)
    calls = []
    monkeypatch.setattr(footage_labels, 'run', lambda sid, **kw: calls.append(kw['confirm'](budget)))
    assert client.get(BASE + '/labels/estimate').json() == budget
    assert not calls
    assert client.post(BASE + '/labels', json={'confirm': True}).status_code == 400
    def start(kind, sid, worker):
        assert sid == 's1'
        worker(lambda m: None)
        return 'mockjob'
    monkeypatch.setattr(jobs, 'start', start)
    assert client.post(BASE + '/labels', json={'confirm': True, 'estimate': budget}).json() == {'job': 'mockjob'}
    assert calls == [True]


def test_import_starts_processing_and_export_is_a_job(client, monkeypatch):
    from app import footage_export
    calls = []
    def imported(path, *, copy):
        assert path == '/synthetic' and copy is True
        return footage.load('s1')
    monkeypatch.setattr(footage, 'import_shoot', imported)
    monkeypatch.setattr(footage, 'start_processing', lambda sid: 'proxyjob')
    assert client.post('/api/footage/import', json={'path': '/synthetic', 'copy': True}).json() == {'id': 's1', 'job': 'proxyjob'}
    def start(kind, sid, worker):
        assert sid == 's1' and kind == 'footage export'
        worker(lambda m: None)
        return 'exportjob'
    monkeypatch.setattr(jobs, 'start', start)
    monkeypatch.setattr(footage_export, 'export_clips', lambda *a, **kw: calls.append((a, kw)))
    assert client.post(BASE + '/export', json={'clip_ids': ['c1'], 'output': '/synthetic/out'}).json() == {'job': 'exportjob'}
    assert calls[0][0] == ('s1', ['c1'], '/synthetic/out')

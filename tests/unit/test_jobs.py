"""Synthetic jobs only: no media, renderers or model requests."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest

from app import jobs, store
from app.main import app
from app.schema import Project


@pytest.fixture
def workers(monkeypatch):
    monkeypatch.setattr(jobs, '_JOBS', {})
    threads = []
    real_thread = threading.Thread

    def thread(*args, **kwargs):
        worker = real_thread(*args, **kwargs)
        threads.append(worker)
        return worker

    monkeypatch.setattr(jobs, 'threading', SimpleNamespace(Thread=thread))
    # Match the existing HTTP tests: avoid the sandbox's threadpool wakeup stall.
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    yield threads
    for worker in threads:
        worker.join(timeout=1)
        assert not worker.is_alive()


def request(method, path):
    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://127.0.0.1') as client:
            return await client.request(method, path)
    return asyncio.run(call())


def test_list_all_projects_and_recent_without_log_bodies(workers):
    for pid in ('jobs-one', 'jobs-two'):
        store.save(Project(id=pid, title=f'Title {pid}', idea='Synthetic'))
    release = threading.Event()

    def work(progress):
        progress('Latest progress')
        assert release.wait(1)
        return {'private_result': True}

    first = jobs.start('research', 'jobs-one', work, cancellable=True)
    second = jobs.start('render', 'jobs-two', work)
    try:
        response = request('GET', '/api/jobs')
        assert response.status_code == 200
        rows = {row['id']: row for row in response.json()}
        assert set(rows) == {first, second}
        for jid, pid in ((first, 'jobs-one'), (second, 'jobs-two')):
            assert rows[jid]['project_id'] == pid
            assert rows[jid]['project_title'] == f'Title {pid}'
            assert rows[jid]['state'] == 'running'
            assert rows[jid]['last_log_line'] == 'Latest progress'
            assert rows[jid]['elapsed'] >= 0
            assert not {'log', 'result', 'error'} & rows[jid].keys()
        assert rows[first]['cancellable'] is True
        assert rows[second]['cancellable'] is False
    finally:
        release.set()
        for worker in workers:
            worker.join(1)
    assert all(row['state'] == 'done' for row in request('GET', '/api/jobs').json())


def test_cancel_at_next_progress_without_error_or_traceback(workers, capsys):
    ready, release = threading.Event(), threading.Event()
    reached = []

    def work(progress):
        progress('Before cancellation')
        ready.set()
        assert release.wait(1)
        progress('Next checkpoint')
        reached.append('should not reach')

    jid = jobs.start('research', '', work, cancellable=True)
    try:
        assert ready.wait(1)
        assert request('POST', f'/api/jobs/{jid}/cancel').status_code == 200
        assert jobs.get(jid)['state'] == 'running'
    finally:
        release.set()
        workers[0].join(1)
    job = request('GET', f'/api/jobs/{jid}').json()
    assert job['state'] == 'cancelled'
    assert job['error'] == '' and job['result'] is None
    assert job['log_total'] == 1 and not reached
    assert jobs.get(jid)['finished_at'] > 0
    assert not capsys.readouterr().err
    assert request('POST', f'/api/jobs/{jid}/cancel').status_code == 409


def test_default_cannot_cancel_and_missing_is_404(workers):
    release = threading.Event()
    jid = jobs.start('voice-over', '', lambda progress: release.wait(1))
    try:
        assert request('POST', f'/api/jobs/{jid}/cancel').status_code == 409
        assert not jobs.get(jid)['cancel_requested']
        assert request('POST', '/api/jobs/missing/cancel').status_code == 404
    finally:
        release.set()

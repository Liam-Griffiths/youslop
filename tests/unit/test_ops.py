"""Shared operations and socket-free HTTP routing; all slow work is mocked."""
import json
import os

import httpx
import pytest

from app import cli, main, ops, research, script_gen, store


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, 'CACHE_DIR', tmp_path)
    def forbidden(*a, **kw):
        pytest.fail('Unexpected LLM call')
    monkeypatch.setattr(script_gen, 'complete_json', forbidden)
    monkeypatch.setattr(research, 'complete_json', forbidden)
    monkeypatch.setattr(ops.reviews.llm, 'complete_json', forbidden)


def test_closed_loop(monkeypatch, capsys, project):
    def generate(p, progress, checkpoint, **kw):
        assert p.test and p.target_minutes == 1 and p.research_mode == 'quick'
        p.slides = project.slides
        p.status = 'scripted'
        checkpoint()
    monkeypatch.setattr(script_gen, 'generate', generate)
    monkeypatch.setattr(ops.media, 'gather', lambda *a, **kw: None)
    assert cli.main(['new', 'A minute about clocks', '--test']) == 0
    pid = capsys.readouterr().out.strip()
    assert store.load(pid).slides
    assert cli.main(['plan', pid]) == 0
    capsys.readouterr()
    expected = ops.check(pid, {}, lambda msg: None)
    assert cli.main(['check', pid, '--json']) == int(bool(expected['counts']['P0']))
    assert json.loads(capsys.readouterr().out) == expected
    assert main.get_check(pid) == expected


def test_create_validation_and_http_shape(monkeypatch):
    queued = []
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: queued.append((kind, pid, fn)) or 'j1')
    with pytest.raises(main.HTTPException) as error:
        main.create_project({'idea': 'short'})
    assert error.value.status_code == 400
    result = main.create_project({'idea': 'A minute about clocks', 'test': True})
    assert set(result) == {'project', 'job'} and result['job'] == 'j1'
    assert result['project']['test']
    assert queued[0][:2] == ('script', result['project']['id'])
    monkeypatch.setattr(ops, 'initialize', lambda pid, payload, pr: {'slides': 3})
    assert queued[0][2](lambda msg: None) == {'slides': 3}
    with pytest.raises(main.HTTPException) as error:
        main.review_action(result['project']['id'], 'n1', {})
    assert error.value.status_code == 400


def test_research_preserves_concurrent_edits(project, monkeypatch):
    store.save(project)
    def gather(*a, **kw):
        fresh = store.load(project.id)
        fresh.subtitle = 'Edited during research'
        store.save(fresh)
        return {'facts': [{'claim': 'Clocks tell time'}]}
    monkeypatch.setattr(research, 'gather', gather)
    result = ops.research(project.id, {}, lambda msg: None)
    fresh = store.load(project.id)
    assert fresh.research == result['research']
    assert fresh.subtitle == 'Edited during research'
    assert fresh.slides[0].take == project.slides[0].take


@pytest.mark.parametrize('command,path', [
    (['new', 'A minute about clocks', '--test'], '/api/projects'),
    (['plan', 'p1'], '/api/projects/p1/script'),
    (['research', 'p1'], '/api/projects/p1/research'),
    (['snapshot', 'p1'], '/api/projects/p1/review/snapshots'),
    (['review', 'p1'], '/api/projects/p1/review'),
    (['fix', 'p1', 'n1'], '/api/projects/p1/review/n1'),
    (['check', 'p1'], '/api/projects/p1/check'),
])
def test_open_loop(monkeypatch, capsys, command, path):
    (cli.CACHE_DIR / 'server.json').write_text(json.dumps({'pid': os.getpid(), 'port': 8420, 'token': 'secret'}))
    requests = []
    def handle(request):
        assert request.headers['x-vb-token'] == 'secret'
        requests.append(request)
        if request.url.path == '/api/health':
            return httpx.Response(200, json=main.health())
        result = {'notes': [], 'manifest': 'review/snaps.json', 'sheet': 'review/sheet.png',
                  'counts': {'P0': 0, 'P1': 0, 'P2': 0}, 'findings': []}
        if request.url.path == path:
            assert request.method == ('GET' if command[0] == 'check' else 'POST')
            if command[0] in ('check', 'fix'):
                return httpx.Response(200, json=result)
            return httpx.Response(200, json={'job': 'j1', 'project': {'id': 'p1'}})
        assert request.url.path == '/api/jobs/j1'
        done = request.url.params['since'] == '1'
        return httpx.Response(200, json={'state': 'done' if done else 'running',
            'log': [] if done else [{'m': 'Working'}], 'log_total': 1, 'result': result})
    factory = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: factory(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(cli.time, 'sleep', lambda s: None)
    monkeypatch.setattr(store, 'load', lambda pid: pytest.fail('Local operation while app is open'))
    assert cli.main(command) == 0
    output = capsys.readouterr()
    if command[0] not in ('check', 'fix'):
        assert output.err.count('Working') == 1
        assert len(requests) == 4
    if command[0] == 'new':
        assert output.out.strip() == 'p1'


@pytest.mark.parametrize('failure', ['unreachable', 'identity', 'job'])
def test_no_local_fallback(monkeypatch, capsys, failure):
    (cli.CACHE_DIR / 'server.json').write_text(json.dumps({'pid': os.getpid(), 'port': 8420}))
    def handle(request):
        if failure == 'unreachable':
            raise httpx.ConnectError('Unavailable', request=request)
        if request.url.path == '/api/health':
            return httpx.Response(200, json={'ok': True, 'pid': -1} if failure == 'identity' else main.health())
        if request.url.path.endswith('/script'):
            return httpx.Response(200, json={'job': 'j1'})
        return httpx.Response(200, json={'state': 'error', 'error': 'mock failure', 'log': [], 'log_total': 0})
    factory = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: factory(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(ops, 'plan', lambda *a: pytest.fail('Unsafe local fallback'))
    assert cli.main(['plan', 'p1']) == 1
    assert capsys.readouterr().err

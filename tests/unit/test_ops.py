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
            if command[0] == 'publish':
                body = json.loads(request.content)
                assert body['channel_id'] == 'c1' and body['privacy'] == 'unlisted'
            if command[0] == 'render':
                assert json.loads(request.content)['section'] == ('s1' if '--section' in command else None)
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


@pytest.mark.parametrize('command,path', [
    (['render', 'p1', '--section', 's1'], '/api/projects/p1/slides/s1/preview'),
    (['render', 'p1', '--full', '--yes'], '/api/projects/p1/render'),
    (['publish', 'p1', '--channel', 'c1', '--privacy', 'unlisted'],
     '/api/projects/p1/youtube/upload'),
])
def test_open_render_publish(monkeypatch, capsys, command, path):
    test_open_loop(monkeypatch, capsys, command, path)


@pytest.mark.parametrize('flags', [[], ['--full'], ['--yes'], ['--force']])
def test_full_refused_before_work(monkeypatch, capsys, flags):
    monkeypatch.setattr(cli, '_operation', lambda *a: pytest.fail('Work started'))
    assert cli.main(['render', 'p1', *flags]) == 1
    assert '--full --yes' in capsys.readouterr().err


def test_shared_render(project, monkeypatch, capsys):
    store.save(project)
    sid = project.slides[0].id
    calls = []
    def preview(p, section, progress):
        calls.append((p.id, section))
        return {'path': 'cache/preview.webm'}
    monkeypatch.setattr(ops.renderer, 'preview_segment', preview)
    assert cli.main(['render', project.id, '--section', sid]) == 0
    assert json.loads(capsys.readouterr().out) == {'path': 'cache/preview.webm'}
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: fn(lambda m: None))
    assert main.preview_segment(project.id, sid) == {'job': {'path': 'cache/preview.webm'}}
    assert calls == [(project.id, sid)] * 2
    with pytest.raises(main.HTTPException) as error:
        main.preview_segment(project.id, 'missing')
    assert error.value.status_code == 404
    assert cli.main(['render', project.id, '--section', 'missing']) == 1
    monkeypatch.setattr(ops.checks, 'run', lambda p, **kw: {'ok': False, 'counts': {'P0': 1}})
    monkeypatch.setattr(ops.renderer, 'render', lambda *a, **kw: pytest.fail('Blocked render'))
    assert cli.main(['render', project.id, '--full', '--yes']) == 1
    assert 'Render blocked by P0' in capsys.readouterr().out
    calls.clear()
    def full(p, progress, **kw):
        calls.append(kw)
        return {'output': 'output.mp4'}
    monkeypatch.setattr(ops.renderer, 'render', full)
    assert cli.main(['render', project.id, '--full', '--yes', '--force']) == 0
    assert 'heavy on this machine' in capsys.readouterr().err
    assert calls == [{'preview': False}]
    assert main.start_render(project.id, {'force': True, 'preview': True}) == {
        'job': {'output': 'output.mp4'}}
    assert calls[-1] == {'preview': True}


def test_shared_publish(project, monkeypatch, capsys):
    project.channel_id = 'c1'
    project.render = {'output': 'output.mp4'}
    store.save(project)
    monkeypatch.setattr(ops.youtube_mod, 'status', lambda cid: {'connected': True})
    calls = []
    def upload(p, cid, **kw):
        calls.append((cid, {k: v for k, v in kw.items() if k != 'progress'}))
        # Simulate an edit during upload; saving the URL must retain it.
        fresh = store.load(p.id)
        fresh.subtitle = 'Edited during upload'
        store.save(fresh)
        return {'url': 'https://example.invalid/video'}
    monkeypatch.setattr(ops.youtube_mod, 'upload_video', upload)
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: fn(lambda m: None))
    assert cli.main(['publish', project.id, '--channel', 'c1']) == 0
    cli_result = json.loads(capsys.readouterr().out)
    fresh = store.load(project.id)
    assert fresh.subtitle == 'Edited during upload'
    fresh.subtitle = ''
    store.save(fresh)
    assert main.youtube_upload(project.id, {}) == {'job': cli_result}
    assert calls[0] == calls[1]
    assert calls[0][1]['privacy'] == 'private'
    assert store.load(project.id).subtitle == 'Edited during upload'
    assert store.load(project.id).render['youtube_url'] == cli_result['url']
    assert cli.main(['publish', project.id, '--channel', 'wrong']) == 1
    assert len(calls) == 2


@pytest.mark.parametrize('channel,connected,output,message', [
    ('', False, '', "isn't on a channel"),
    ('c1', False, '', "isn't connected"),
    ('c1', True, '', 'Nothing rendered'),
])
def test_publish_early_validation(project, monkeypatch, capsys, channel, connected, output, message):
    project.channel_id = channel
    project.render = {'output': output}
    store.save(project)
    monkeypatch.setattr(ops.youtube_mod, 'status', lambda cid: {'connected': connected})
    monkeypatch.setattr(main.jobs, 'start', lambda *a: pytest.fail('Job queued'))
    monkeypatch.setattr(ops.youtube_mod, 'upload_video', lambda *a, **kw: pytest.fail('Upload started'))
    with pytest.raises(main.HTTPException) as error:
        main.youtube_upload(project.id, {})
    assert error.value.status_code == 400 and message in error.value.detail
    assert cli.main(['publish', project.id]) == 1
    assert message in capsys.readouterr().err

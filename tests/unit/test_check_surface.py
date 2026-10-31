"""Check surfaces refuse before starting work and preserve force semantics."""
import json

from app import check, cli, main, render, store


def test_endpoints_and_gate(project, monkeypatch):
    monkeypatch.setattr(main, '_load', lambda pid: project)
    finding = dict(code='empty_first_frame', level='P0', t=2, slide_id='s1',
                   msg='Missing opening picture', fix={'kind': 'picture'})
    result = dict(ok=False, counts={'P0': 1, 'P1': 0, 'P2': 0}, findings=[finding])
    monkeypatch.setattr(check, 'run', lambda p: result)
    monkeypatch.setattr(render, 'timeline', lambda p: {
        'segments': [dict(start=0, duration=2), dict(start=2, duration=3)]})
    started = []
    monkeypatch.setattr(main.jobs, 'start', lambda *args: started.append(args) or 'job1')
    assert main.get_check(project.id) == result
    tl = main.get_timeline(project.id)
    assert tl['segments'][0]['findings'] == []
    assert tl['segments'][1]['findings'] == [finding]
    assert main.start_render(project.id, {})['check'] == result
    assert not started
    assert main.start_render(project.id, {'force': True}) == {'job': 'job1'}
    result.update(ok=True, counts={'P0': 0, 'P1': 0, 'P2': 0}, findings=[])
    assert main.start_render(project.id, {}) == {'job': 'job1'}


def test_cli_check(project, monkeypatch, capsys):
    monkeypatch.setattr(store, 'load', lambda pid: project)
    result = dict(ok=False, counts={'P0': 1, 'P1': 0, 'P2': 0}, findings=[
        dict(level='P0', t=0, msg='Missing opening picture')])
    monkeypatch.setattr(check, 'run', lambda p: result)
    assert cli.main(['check', project.id]) == 1
    assert 'P0 (1)\n  0.000s  Missing opening picture' in capsys.readouterr().out
    assert cli.main(['check', project.id, '--json']) == 1
    assert json.loads(capsys.readouterr().out) == result
    result.update(ok=True, counts={'P0': 0, 'P1': 0, 'P2': 0}, findings=[])
    assert cli.main(['check', project.id]) == 0

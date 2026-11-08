"""Stable storyboard contract, shared validation, and CLI write safety."""
import json
import os

import pytest

from app import cli, cuts, edits, render, store, storyboard
from tests._fixtures import ROOT


def test_golden(project, request):
    actual = json.dumps(storyboard.build(project), sort_keys=True)
    actual = actual.replace(os.environ['CORKBORED_DATA'], '<DATA>').replace(str(ROOT), '<REPO>')
    golden = ROOT / 'tests/golden/storyboard_min.json'
    if request.config.getoption('--update-goldens'):
        golden.write_text(actual + '\n')
    assert actual + '\n' == golden.read_text()
    # Empty block overrides stay absent from the serialized legacy contract.
    assert storyboard.build(project)['style'] == project.style.to_dict()


def test_apply(project):
    before = project.to_dict()
    patch = {'paragraphs': {'s1': {'narration': ' New narration ', 'title': 'x' * 50,
                                  'chapter': ' Start ', 'picture_mode': 'hold',
                                  'cues': {'loudmouth': [{'kind': 'shout', 'text': 'Hello'}]}}}}
    assert storyboard.apply(project, patch) == ['narration', 'title', 'chapter', 'picture_mode', 'cues']
    expected = before['slides'][0] | {'narration': 'New narration', 'title': 'x' * 40,
                                    'chapter': 'Start', 'picture_mode': 'hold',
                                    'cues': project.slides[0].cues, 'word_count': 2}
    assert project.slides[0].to_dict() == expected
    assert project.to_dict()['slides'][1:] == before['slides'][1:]
    assert storyboard.apply(project, patch) == []


@pytest.mark.parametrize('payload', [{'unknown': 1}, {'picture_mode': 'bad'},
                                     {'cues': {'bad': []}}])
def test_reject_atomic(project, payload):
    before = project.to_dict()
    with pytest.raises(edits.EditError):
        storyboard.apply(project, {'paragraphs': {'s1': {'title': 'changed'}, 's2': payload}})
    assert project.to_dict() == before


def test_cut_times(project, monkeypatch):
    project.style.format = 'loudmouth'
    project.style.picture_every = 2
    groups = render._picture_groups(project, render._slide_durations(project, True))
    seg = next(s for s in render.timeline(project)['segments'] if s['type'] == 'picture')
    _dur, transition, length = render._segment_timing(project, groups, 0)
    lead = transition / 2 + cuts.head_pad_for(project, groups[0][0][0])
    # Independent copy of the original render loop, without drawing anything.
    spent, expected = 0.0, []
    for n, (slide, dur) in enumerate(groups[0]):
        offset = spent
        pad = lead if n == 0 else 0
        span = length - spent if n == len(groups[0]) - 1 else min(dur + pad, length - spent)
        spent += span
        cues = cuts.cues_for(cuts.BY_KEY['loudmouth'], slide)
        times = cuts.kit.place(slide.narration, cues, cuts.spoken_of(slide, dur), span,
                               lead=pad, min_hold=cuts.loudmouth.MIN_HOLD)
        expected.append((slide.id, cues, [(offset + a, offset + b) for a, b in times]))
    assert cuts.timed_cues(project, groups[0], length, lead) == expected
    monkeypatch.setattr(cuts, 'load_picture', lambda *a: pytest.fail('Downloaded a picture'))
    paras = {p['id']: p for p in storyboard.build(project)['paragraphs']}
    for sid, cues, times in expected:
        assert [(c['start'], c['end']) for c in paras[sid]['cues']] == [
            (round(seg['start'] - transition / 2 + a, 3),
             round(seg['start'] - transition / 2 + b, 3)) for a, b in times]


def test_api(project):
    from app import main
    store.save(project)
    assert main.project_storyboard(project.id) == storyboard.build(project)
    result = main.patch_slide(project.id, 's1', {'title': ' x ', 'focal': [2, -1]})
    assert result['title'] == 'x'
    assert result['candidates'][0]['focal'] == [1.0, 0.0]
    with pytest.raises(main.HTTPException) as exc:
        main.patch_slide(project.id, 's1', {'picture_mode': 'bad'})
    assert (exc.value.status_code, exc.value.detail) == (400, 'picture_mode is auto, hold or new')


def test_cli(project, tmp_path, monkeypatch, capsys):
    store.save(project)
    patch = tmp_path / 'patch.json'
    patch.write_text(json.dumps({'paragraphs': {'s1': {'title': 'CLI title'}}}))
    marker = cli.CACHE_DIR / 'server.json'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'pid': os.getpid()}))
    assert cli.main(['storyboard', project.id, '--json']) == 0
    assert json.loads(capsys.readouterr().out)['version'] == 1
    assert cli.main(['apply', project.id, str(patch)]) == 1
    assert 'the app is open; close it or use the UI' in capsys.readouterr().err
    assert store.load(project.id).slides[0].title != 'CLI title'
    monkeypatch.setattr(cli, '_alive', lambda pid: False)
    assert cli.main(['apply', project.id, str(patch)]) == 0
    assert not marker.exists()
    assert store.load(project.id).slides[0].title == 'CLI title'


def test_server_marker(monkeypatch):
    import uvicorn
    from app import __main__ as server
    marker = cli.CACHE_DIR / 'server.json'
    def run(self):
        assert json.loads(marker.read_text())['pid'] == os.getpid()
        assert json.loads(marker.read_text())['port'] == 8420
        raise RuntimeError('server stopped')
    monkeypatch.setattr(uvicorn.Server, 'run', run)
    with pytest.raises(RuntimeError, match='server stopped'):
        server.serve(8420)
    assert not marker.exists()

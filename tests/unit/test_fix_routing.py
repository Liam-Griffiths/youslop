"""Fixes use synthetic projects and mocked planners; no rendering or network."""
from copy import deepcopy

import pytest

from app import cli, main, review, script_gen, store
from tests.unit.test_review import setup_review  # shared synthetic snapshots/model


@pytest.fixture
def saved(project, tmp_path):
    project.id = 'pfix_' + tmp_path.name
    store.save(project)
    return project


@pytest.mark.parametrize('kind', review.ROUTES)
def test_routing_table(saved, monkeypatch, kind):
    calls = []
    monkeypatch.setitem(review.ROUTES, kind, lambda p, f: calls.append(f) or {'test': kind})
    result = review.route_fix(saved, dict(kind=kind, slide_id='s1', hint='Fix it'))
    assert result == dict(proposal={'test': kind}, applied=False)
    assert calls[0]['kind'] == kind


def test_text_proposal_apply_and_history(saved, monkeypatch):
    slide = saved.slides[0]
    slide.take = {'path': 'takes/old.wav', 'duration': 2}
    slide.takes = {saved.voice_track: slide.take}
    store.save(saved)
    original = store.load(saved.id)
    calls = []
    def rewrite(p, s, hint):
        calls.append(hint)
        current = store.load(p.id)
        current.subtitle = 'Concurrent edit'
        store.save(current)
        return 'Proposed narration'
    monkeypatch.setattr(script_gen, 'rewrite_slide', rewrite)
    fix = dict(kind='words', slide_id=slide.id, instruction='shorten')
    proposal = review.route_fix(original, fix)
    assert proposal['proposal']['old'] == slide.narration
    assert store.load(saved.id).slides[0].narration == slide.narration
    result = review.route_fix(original, fix, apply=True, proposal=proposal['proposal'])
    current = store.load(saved.id)
    assert result['applied'] and calls == ['shorten']
    assert current.subtitle == 'Concurrent edit'
    assert current.slides[0].narration == 'Proposed narration'
    assert current.slides[0].take is None and current.slides[0].takes == {}
    assert current.slides[0].history[0]['path'] == 'takes/old.wav'
    with pytest.raises(ValueError, match='changed'):
        review.route_fix(original, fix, apply=True, proposal=proposal['proposal'])


def test_single_cue_prompt_and_failure(saved, monkeypatch):
    saved.style.format = 'loudmouth'
    a, b = saved.slides[:2]
    a.cues = {'loudmouth': [{'kind': 'shout', 'text': 'Old'}], 'ticker': []}
    b.cues = deepcopy(a.cues)
    store.save(saved)
    prompts = []
    def fake(prompt, **kwargs):
        prompts.append(prompt)
        return [{'n': 1, 'cues': [{'kind': 'shout', 'text': 'New', 'on': 'opening'}]}]
    monkeypatch.setattr(script_gen, 'complete_json', fake)
    fix = dict(kind='cues', slide_id=a.id, hint='Make it bigger')
    result = review.route_fix(saved, fix, apply=True)
    current = store.load(saved.id)
    assert result['applied'] and 'Make it bigger' in prompts[0]
    assert current.slides[0].cues['loudmouth'][0]['text'] == 'New'
    assert current.slides[1].cues == b.cues
    assert saved.slides[0].cues == a.cues  # proposal works on a copy
    before = current.to_dict()
    monkeypatch.setattr(script_gen, 'complete_json', lambda *a, **k: (_ for _ in ()).throw(ValueError('offline')))
    with pytest.raises(ValueError, match='offline'):
        review.route_fix(current, fix, apply=True)
    assert store.load(saved.id).to_dict() == before


def test_other_routes(saved):
    sid = saved.slides[0].id
    title = review.route_fix(saved, dict(kind='title', slide_id=sid, hint='  New title  '), apply=True)
    assert title['applied'] and store.load(saved.id).slides[0].title == 'New title'
    look = review.route_fix(saved, dict(kind='style', hint='No gradients'), apply=True)
    assert look['applied'] and store.load(saved.id).frame.rejected_looks == ['No gradients']
    picture = review.route_fix(saved, dict(kind='picture', slide_id=sid, hint='archive ship'))
    assert picture['proposal'] == dict(search='archive ship', slide_id=sid)
    assert review.route_fix(saved, dict(kind='timing'))['unsupported'] == 'timing'
    assert review.route_fix(saved, dict(kind='none'))['unsupported'] == 'none'


def test_dismiss_and_keep_survive_review(setup_review):
    project, root, snaps, calls = setup_review
    result = review.run(project)
    nid = result['notes'][0]['id']
    main.review_action(project.id, nid, dict(action='dismiss'))
    result = review.run(project)
    assert not [n for n in result['notes'] if n.get('state') == 'open']
    assert result['warnings_kept'] == []
    main.review_action(project.id, nid, dict(action='keep'))
    result = review.run(project)
    assert result['warnings_kept'][0]['state'] == 'kept'


def test_api_cli_exact_proposal(saved, monkeypatch, capsys):
    note = dict(t=1, severity='P1', see='Text', problem='Long',
                fix=dict(kind='text', slide_id=saved.slides[0].id, hint='shorten'))
    note.update(id=review.note_id(note), state='open')
    review._write_notes(saved.id, {'notes': [note]})
    calls = []
    monkeypatch.setattr(script_gen, 'rewrite_slide', lambda *args: calls.append(1) or 'New narration')
    monkeypatch.setattr(cli, '_guard_write', lambda: None)
    assert cli.main(['fix', saved.id, note['id']]) == 0
    assert store.load(saved.id).slides[0].narration != 'New narration'
    result = main.review_action(saved.id, note['id'], {'action': 'apply'})
    assert result['applied'] and calls == [1]
    assert review.read_notes(saved.id)['notes'][0]['state'] == 'fixed'
    # --apply also prepares once and applies the exact printed proposal.
    assert cli.main(['fix', saved.id, note['id'], '--apply']) == 0
    assert calls == [1, 1]
    assert 'New narration' in capsys.readouterr().out
    with pytest.raises(main.HTTPException):
        main.review_action(saved.id, note['id'], {'action': 'unknown'})


def test_check_decisions(saved, monkeypatch):
    finding = dict(t=2, level='P1', code='long', msg='Shorten', slide_id=saved.slides[0].id,
                   fix=dict(kind='words', slide_id=saved.slides[0].id, instruction='shorten'))
    monkeypatch.setattr(review.check, 'run', lambda p: {'findings': [finding]})
    nid = review.note_id(finding)
    main.review_action(saved.id, nid, dict(action='dismiss', finding=True))
    assert main.get_timeline(saved.id)['check']['findings'][0]['state'] == 'dismissed'


def test_cue_route_isolated_reload(saved, monkeypatch):
    saved.style.format = 'loudmouth'
    for s in saved.slides:
        s.cues = {'loudmouth': [{'kind': 'shout', 'text': 'Old'}]}
    store.save(saved)
    sid = saved.slides[0].id
    started = []
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: started.append(fn) or 'job')
    def planner(p, slides, progress, instruction):
        assert [s.id for s in slides] == [sid]
        assert not slides[0].cues and instruction == 'Bigger'
        current = store.load(p.id)
        current.subtitle = 'Concurrent save'
        store.save(current)
        slides[0].cues = {'loudmouth': [{'kind': 'shout', 'text': 'New'}]}
    monkeypatch.setattr(script_gen, 'plan_cues', planner)
    main.plan_cues(saved.id, dict(slide_ids=[sid], redo=True, instruction='Bigger'))
    started[0](lambda msg: None)
    current = store.load(saved.id)
    assert current.subtitle == 'Concurrent save'
    assert current.slides[0].cues['loudmouth'][0]['text'] == 'New'
    assert current.slides[1].cues['loudmouth'][0]['text'] == 'Old'


def test_dismiss_time_tolerance_and_cli_status(setup_review, monkeypatch, capsys):
    project, root, snaps, calls = setup_review
    result = review.run(project)
    note = result['notes'][0]
    review.act(project.id, note['id'], 'dismiss')
    # The next model note uses an actual snapshot within half a second.
    monkeypatch.setattr(review, 'select', lambda *args: [dict(snaps[0], t=.4)])
    monkeypatch.setattr(review.llm, 'complete_json', lambda *a, **k: dict(
        notes=[dict(note, t=.4)], weakest=dict(t=.4, why='Same shot')))
    monkeypatch.setattr(cli, '_guard_write', lambda: None)
    assert cli.main(['review', project.id, '--json']) == 0
    assert not [n for n in review.read_notes(project.id)['notes'] if n['state'] == 'open']
    capsys.readouterr()
    monkeypatch.setattr(review, 'select', lambda *args: [dict(snaps[0], t=.6)])
    monkeypatch.setattr(review.llm, 'complete_json', lambda *a, **k: dict(
        notes=[dict(note, t=.6)], weakest=dict(t=.6, why='Different moment')))
    assert review.run(project)['notes'][0]['state'] == 'open'

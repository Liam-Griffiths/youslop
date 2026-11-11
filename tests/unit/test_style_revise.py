"""Smoothing uses synthetic scripts and model replies; no audio or live model."""
from copy import deepcopy
import json

import pytest
from fastapi import HTTPException

from app import main, script_gen as sg, store, style_lint
from app.schema import Project, Slide

TEXT = ('In 1891, Ada built a machine in London while her brother kept detailed '
        'notes about every test they performed together. He had no idea! '
        'The machine remained in the workshop because the investors wanted '
        'another demonstration before they agreed to fund production.')
REPLACEMENT = 'He did not know.'
RHYTHM = ('The workers arrived before dawn. They opened the heavy gates. '
          'They checked the old equipment. They started the morning shift.')
JOINED = ('The workers arrived before dawn and opened the heavy gates, '
          'then checked the old equipment before they started the morning shift.')


def reply(sid='p0', indices=None, text=REPLACEMENT):
    return {'slide_id': sid, 'replacements': [
        {'sentence_indices': [1] if indices is None else indices, 'text': text}]}


@pytest.fixture
def episode(monkeypatch):
    monkeypatch.setattr(sg, 'complete_json', lambda *a, **kw: pytest.fail('Unexpected model call'))
    return Project(id='style-revise', idea='Synthetic', slides=[Slide(id=f'p{i}', narration=TEXT) for i in range(3)])


def test_batched_proposals_only_change_flagged_text(episode, monkeypatch):
    calls = []
    before = deepcopy(episode.to_dict())
    def complete(prompt, **kw):
        calls.append(prompt)
        assert kw['system'] == sg.NARRATOR_SYSTEM
        assert kw['require']([]) and not kw['require']({})
        batch = json.loads(prompt.split('\n\n', 1)[1])
        assert len(batch) == 3
        assert all(b['replacements'] == [{'sentence_indices': [1]}] for b in batch)
        return [reply(f'p{i}') for i in range(3)]
    monkeypatch.setattr(sg, 'complete_json', complete)
    proposals = sg.revise_style(episode)
    assert len(calls) == 1 and len(proposals) == 3
    assert all(p['after'] == TEXT.replace('He had no idea!', REPLACEMENT) for p in proposals)
    assert episode.to_dict() == before  # reject/dismiss needs no write


def test_rhythm_join_and_rate(episode, monkeypatch):
    episode.slides = [Slide(id='p0', narration=RHYTHM)]
    def complete(prompt, **kw):
        assert 'joining/extending' in prompt and 'not single-sentence swaps' in prompt
        assert 'short_rhythm' in prompt and 'low_spread' in prompt
        return [reply(indices=[0, 1, 2, 3], text=JOINED)]
    monkeypatch.setattr(sg, 'complete_json', complete)
    proposal = sg.revise_style(episode)[0]
    assert proposal['after'] == JOINED
    assert style_lint.rate([JOINED]) < style_lint.rate([RHYTHM])


@pytest.mark.parametrize('replacement', [
    'He paid 500 dollars.', 'He visited Paris.', 'He visited London in 1900.',
    'He waited twelve years.', 'He arrived in May.', '', None])
def test_fact_guard_rejects_inventions(episode, monkeypatch, replacement):
    monkeypatch.setattr(sg, 'complete_json', lambda *a, **kw: [reply(text=replacement)])
    assert sg.revise_style(episode) == []


@pytest.mark.parametrize('original,replacement', [
    ('Ada paid 20 dollars!', 'Ada paid dollars.'),
    ('Ada arrived in May!', 'She arrived.'),
    ('Ada paid twelve dollars!', 'Ada paid dollars.')])
def test_fact_guard_keeps_existing_facts(original, replacement):
    assert sg.style_revision(original, reply(indices=[0], text=replacement)['replacements'])[0] == original


def test_no_hits_selection_and_faithful_skip(episode, monkeypatch):
    episode.slides[0].narration = 'A single deliberate short sentence.'
    assert sg.revise_style(episode, ['p0']) == []
    assert sg.revise_style(episode, []) == []
    episode.has_source = True
    assert sg.revise_style(episode) == []
    episode.fidelity = 'adapted'
    monkeypatch.setattr(sg, 'complete_json', lambda *a, **kw: [reply('p1')])
    assert [p['slide_id'] for p in sg.revise_style(episode, ['p1'])] == ['p1']


def test_invalid_spans_and_whitespace(episode):
    for indices in ([0], [True], [1, 1], [-1], [99], '1'):
        assert sg.style_revision(TEXT, reply(indices=indices)['replacements'])[0] == TEXT
    text = TEXT.replace(' He had', '\n\nHe had').replace(' The machine', '  The machine')
    after, _ = sg.style_revision(text, reply()['replacements'])
    assert after == text.replace('He had no idea!', REPLACEMENT)


def test_batch_limit_and_malformed_reply(episode, monkeypatch):
    episode.slides = [Slide(id=f'p{i}', narration=TEXT) for i in range(13)]
    calls = []
    monkeypatch.setattr(sg, 'complete_json', lambda prompt, **kw: calls.append(prompt) or [
        None, {}, {'slide_id': []}, reply('unknown'), {'slide_id': 'p0', 'replacements': {}}])
    assert sg.revise_style(episode) == [] and len(calls) == 2


def test_manual_preview_and_apply_preserve_recording_and_other_edits(episode, monkeypatch):
    episode.set_take(episode.slides[0], 'mic', {'path': 'takes/kept.wav', 'duration': 3})
    episode.slides[0].history = [{'path': 'takes/older.wav'}]
    store.save(episode)
    before = store.load(episode.id).to_dict()
    def complete(*args, **kwargs):
        fresh = store.load(episode.id)
        fresh.subtitle = 'Edited during model call'
        store.save(fresh)
        return [reply()]
    monkeypatch.setattr(sg, 'complete_json', complete)
    workers = []
    def start(kind, pid, work):
        assert kind == 'smooth flagged lines' and pid == episode.id
        workers.append(work)
        return 'synthetic-job'
    monkeypatch.setattr(main.jobs, 'start', start)
    assert main.propose_style_revision(episode.id, {'slides': ['p0']}) == {'job': 'synthetic-job'}
    assert store.load(episode.id).subtitle == episode.subtitle  # model has not run in request
    messages = []
    # A different thread must be able to take the lock during the model work.
    from concurrent.futures import ThreadPoolExecutor
    original = sg.complete_json
    def unlocked_complete(*args, **kwargs):
        def acquire():
            lock = store.lock_for(episode.id)
            acquired = lock.acquire(timeout=1)
            if acquired:
                lock.release()
            return acquired
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(acquire).result(timeout=2)
        return original(*args, **kwargs)
    monkeypatch.setattr(sg, 'complete_json', unlocked_complete)
    proposal = workers[0](messages.append)[0]
    assert any('Smoothing flagged lines' in m for m in messages)
    assert store.load(episode.id).slides[0].narration == TEXT
    saved = main.apply_style_revision(episode.id, proposal)
    assert saved['narration'] != saved['take']['narration']
    for field in ('take', 'takes', 'history'):
        assert saved[field] == before['slides'][0][field]
    fresh = store.load(episode.id)
    assert fresh.subtitle == 'Edited during model call'
    assert fresh.slides[1].narration == TEXT
    with pytest.raises(HTTPException, match='409'):
        main.apply_style_revision(episode.id, proposal)
    fresh.has_source = True
    store.save(fresh)
    with pytest.raises(HTTPException, match='400'):
        main.apply_style_revision(episode.id, proposal)


@pytest.mark.parametrize('faithful,fail', [(False, False), (False, True), (True, False)])
def test_generation_order_threshold_and_nonfatal_failure(episode, monkeypatch, faithful, fail):
    episode.has_source = faithful
    monkeypatch.setattr(sg, 'brief', lambda *a: {})
    monkeypatch.setattr(sg, 'write_script', lambda *a: episode.slides)
    for name in ('plan_visuals', 'plan_boards', 'plan_cues', '_plan_style_slides'):
        monkeypatch.setattr(sg, name, lambda *a: None)
    calls, messages = [], []
    monkeypatch.setattr(sg, 'consistency_check', lambda *a: calls.append('consistency') or [])
    def revise(*args, **kw):
        calls.append('style')
        if fail:
            raise sg.LLMError('Synthetic outage')
        return [{'slide_id': 'p0', 'after': TEXT.replace('He had no idea!', REPLACEMENT)}]
    monkeypatch.setattr(sg, 'revise_style', revise)
    sg.generate(episode, messages.append)
    assert calls == (['consistency'] if faithful else ['consistency', 'style'])
    assert (episode.slides[0].narration == TEXT) == (faithful or fail)
    assert any('Style smoothing skipped' in m for m in messages) == fail
    calls.clear()
    episode.slides = [Slide(narration='A quiet deliberate sentence.')]
    sg.generate(episode)
    assert calls == ['consistency']

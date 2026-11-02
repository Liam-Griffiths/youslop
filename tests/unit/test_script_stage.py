"""Script checks and chapter moves use synthetic data and never draw or call a model."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from app import channels, check, llm, main, review, store
from app.schema import Channel, Project, Slide


@pytest.fixture
def episode(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Script must not render, measure, or call a model')
    monkeypatch.setattr(llm, 'complete_json', forbidden)
    monkeypatch.setattr(llm, 'complete', forbidden)
    monkeypatch.setattr(check, 'run', forbidden)
    monkeypatch.setattr(check.storyboard, 'build', forbidden)
    p = Project(id='script-fixture', idea='Synthetic', slides=[
        Slide(id='one', narration='', chapter='Opening'),
        Slide(id='two', narration='The street before dawn.')])
    p.slides[0].history = [{'path': 'takes/retired.wav'}]
    p.set_take(p.slides[0], 'mic', {'path': 'takes/recorded.wav', 'duration': 4})
    p.research = {'flags': [{'slide_id': 'two', 'severity': 'high',
                            'claim': 'The street', 'issue': 'Verify the date'}]}
    store.save(p)
    return store.load(p.id)


def test_words_only_counts_and_effective_rules(episode):
    channel = Channel(id='script-channel', name='Synthetic')
    channel.frame.rules = ['British spelling']
    channels.save(channel)
    episode.channel_id = channel.id
    episode.frame.rules = ['Use concrete nouns']
    result = check.script(episode)
    assert result['counts'] == {'P0': 1, 'P1': 1, 'P2': 0}
    assert result['rules'] == ['British spelling', 'Use concrete nouns']
    assert [f['slide_id'] for f in result['findings']] == ['one', 'two']
    episode.outline = {'hook': {'open_loops': [{'question': 'Why?', 'payoff_beat': 'Missing'}]}}
    assert len(check.script(episode)['findings']) == 3


def test_dismiss_persists_and_changed_finding_reappears(episode):
    result = main.script_check(episode.id)
    fid = result['findings'][1]['id']
    review._write_notes(episode.id, {'notes': [{'id': 'unrelated', 'state': 'kept'}]})
    assert main.dismiss_script_finding(episode.id, fid) == {'state': 'dismissed'}
    assert main.script_check(episode.id)['counts']['P1'] == 0
    episode.research['flags'][0]['issue'] = 'Verify the number'
    store.save(episode)
    assert main.script_check(episode.id)['counts']['P1'] == 1
    assert review.read_notes(episode.id)['notes'][0]['id'] == 'unrelated'
    with pytest.raises(HTTPException) as exc:
        main.dismiss_script_finding(episode.id, fid)
    assert exc.value.status_code == 404


def test_move_chapter_preserves_every_other_field(episode):
    before = deepcopy(episode.to_dict()['slides'])
    main.move_chapter(episode.id, {'source': 'one', 'target': 'two'})
    after = store.load(episode.id).to_dict()['slides']
    assert [s['chapter'] for s in after] == ['', 'Opening']
    for s in before + after:
        s.pop('chapter')
    assert before == after


def test_chapter_conflict_is_atomic(episode):
    episode.slides[1].chapter = 'Second'
    store.save(episode)
    before = store.load(episode.id).to_dict()
    with pytest.raises(HTTPException) as exc:
        main.move_chapter(episode.id, {'source': 'one', 'target': 'two'})
    assert exc.value.status_code == 409
    assert store.load(episode.id).to_dict() == before


def test_edit_keeps_take_and_history(episode):
    take, history = deepcopy(episode.slides[0].take), deepcopy(episode.slides[0].history)
    main.patch_slide(episode.id, 'one', {'narration': 'A new line', 'visual_note': 'Archive', 'title': 'Street'})
    saved = store.load(episode.id).slides[0]
    assert saved.take == take and saved.history == history
    assert main.script_check(episode.id)['counts']['P0'] == 0

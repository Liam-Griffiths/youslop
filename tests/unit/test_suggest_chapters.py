"""Instant chapter proposals and additive, selected application."""
import copy

import pytest

from app import llm, render, script_gen
from app.schema import Project, Slide


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Chapter suggestions must not call an LLM')
    monkeypatch.setattr(llm, 'complete_json', forbidden)
    monkeypatch.setattr(script_gen, 'complete_json', forbidden)


def synthetic(monkeypatch, starts, end=180):
    project = Project(id='ptest', idea='Test', slides=[Slide(id=f's{i}', section='intro' if i == 0 else 'main',
                                   beat=f'beat {i}', narration='one two three four five six seven')
                              for i in range(len(starts))])
    paragraphs = [{'id': s.id, 'start': t,
                   'duration': (starts[i+1] if i+1 < len(starts) else end) - t}
                  for i, (s, t) in enumerate(zip(project.slides, starts))]
    monkeypatch.setattr(render, 'timeline', lambda p: {
        'segments': [{'paragraphs': paragraphs}, {'paragraphs': []}], 'total': end + 30})
    return project


def test_spacing_and_first_main(monkeypatch):
    project = synthetic(monkeypatch, [0, 10, 40, 55, 80, 100, 145])
    before = copy.deepcopy(project.to_dict())
    proposals = script_gen.suggest_chapters(project)
    assert [p['t'] for p in proposals] == [10, 55, 100, 145]
    assert proposals[0] == {'sid': 's1', 'text': 'Beat 1', 't': 10}
    assert project.to_dict() == before


def test_never_in_last_twenty_seconds(monkeypatch):
    project = synthetic(monkeypatch, [0, 20, 65, 110, 155, 175], end=175)
    assert [p['t'] for p in script_gen.suggest_chapters(project)] == [20, 65, 110, 155]
    project = synthetic(monkeypatch, [0, 156], end=175)
    assert script_gen.suggest_chapters(project) == []


def test_beat_changes_titles_and_existing_chapters(monkeypatch):
    project = synthetic(monkeypatch, [0, 10, 55, 100, 145], end=200)
    project.slides[1].beat = 'a long heading with more than six words here'
    project.slides[2].beat = project.slides[1].beat
    project.slides[3].beat = ''
    project.slides[4].chapter = 'Keep this'
    proposals = script_gen.suggest_chapters(project)
    assert [p['sid'] for p in proposals] == ['s1', 's3']
    assert proposals[0]['text'] == 'A Long Heading With More Than'
    assert proposals[1]['text'] == 'one two three four five six'


def test_empty_project():
    assert script_gen.suggest_chapters(Project(id='pempty', idea='Test')) == []


def test_route_preview_and_selected_apply(monkeypatch):
    from app import main, store
    project = synthetic(monkeypatch, [0, 10, 60, 110], end=180)
    project.slides[3].chapter = 'Owner chapter'
    monkeypatch.setattr(main, '_load', lambda pid: project)
    saved = []
    monkeypatch.setattr(store, 'save', lambda p: saved.append(copy.deepcopy(p.to_dict())))
    proposals = main.suggest_chapters(project.id, {})
    assert len(proposals) == 2
    assert saved == []
    main.suggest_chapters(project.id, {'apply': True, 'sids': ['s2']})
    assert [s.chapter for s in project.slides] == ['', '', 'Beat 2', 'Owner chapter']
    assert len(saved) == 1


def test_real_timeline_estimates_without_rendering():
    project = Project(id='ptest', idea='Test', slides=[Slide(section='intro', narration='word ' * 80),
                              Slide(beat='the main point', narration='word ' * 160),
                              Slide(beat='the next point', narration='word ' * 160)])
    before = copy.deepcopy(project.to_dict())
    starts = {p['id']: p['start'] for seg in render.timeline(project)['segments']
              for p in seg['paragraphs']}
    proposals = script_gen.suggest_chapters(project)
    assert proposals
    assert all(p['t'] == starts[p['sid']] for p in proposals)
    assert project.to_dict() == before


def test_beat_titles_keep_apostrophes():
    import string
    assert string.capwords("the system's shadow") == "The System's Shadow"

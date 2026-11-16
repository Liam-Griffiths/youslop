"""Moving paragraphs between Script page shots keeps shots, chapters and pictures intact."""
import asyncio

import httpx
import pytest

from app import main, script_shots, store
from app.schema import Project, Slide
from app.script_agent import shots


def _project():
    return Project(id='move', idea='Synthetic', slides=[
        Slide(id='a', narration='One.', chapter='Opening', visual_note='Carrier', chosen_id='m1'),
        Slide(id='b', narration='Two.', visual_note='Carrier'),
        Slide(id='c', narration='Three.', visual_note='Engraving', chosen_id='m2', take={'path': 'takes/c.wav', 'duration': 2}),
        Slide(id='d', narration='Four.', visual_note='Engraving'),
        Slide(id='i', insert={'kind': 'card', 'seconds': 4, 'text': 'Card'}),
        Slide(id='e', narration='Five.', chapter='Later', visual_note='Map'),
    ])


def ids(p):
    return [[s.id for s in run] for run in shots(p)]


def test_move_to_end_of_shot_above_takes_its_description():
    p = _project()
    assert script_shots.move(p, 'c', 'a')
    assert ids(p) == [['a', 'b', 'c'], ['d'], ['i'], ['e']]
    c, d = (next(s for s in p.slides if s.id == k) for k in 'cd')
    assert c.visual_note == 'Carrier' and c.take['path'] == 'takes/c.wav'
    assert d.chosen_id == 'm2' and d.visual_note == 'Engraving'  # the shot keeps its picture


def test_move_to_start_of_shot_below_and_within_a_shot():
    p = _project()
    assert script_shots.move(p, 'b', 'c', before='c')
    assert ids(p) == [['a'], ['b', 'c', 'd'], ['i'], ['e']]
    assert script_shots.move(p, 'd', 'b', before='b')
    assert ids(p) == [['a'], ['d', 'b', 'c'], ['i'], ['e']]
    assert not script_shots.move(p, 'd', 'd', before='d')


def test_chapter_stays_with_the_shot_that_leads_it():
    p = _project()
    assert not script_shots.move(p, 'a', 'a', before='b')  # already there
    assert script_shots.move(p, 'a', 'a')
    assert ids(p)[0] == ['b', 'a'] and p.slides[0].chapter == 'Opening' and not p.slides[1].chapter
    p = _project()
    p.slides.append(Slide(id='f', narration='Six.', visual_note='Map'))
    assert script_shots.move(p, 'e', 'c')  # a chapter's first paragraph leaves; the heading stays
    assert [s.chapter for s in p.slides if s.id in ('e', 'f')] == ['', 'Later']
    assert ids(p)[-1] == ['f']


def test_undescribed_paragraphs_stay_grouped():
    p = Project(id='plain', idea='x', slides=[Slide(id=k, narration=k) for k in 'abcd'])
    p.style.picture_every = 2
    before = ids(p)
    assert script_shots.move(p, 'c', before[0][0])
    assert ids(p)[0] == before[0] + ['c']


def test_rejects_inserts_and_unknown_shots():
    p = _project()
    with pytest.raises(script_shots.MoveError):
        script_shots.move(p, 'i', 'a')
    with pytest.raises(script_shots.MoveError):
        script_shots.move(p, 'a', 'i')
    with pytest.raises(script_shots.MoveError):
        script_shots.move(p, 'a', 'c', before='b')


def test_route_saves_one_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())
    version = store.load('move').updated_at

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            path = '/api/projects/move/script/move'
            assert (await c.post(path, json={'id': 'c', 'shot': 'a', 'version': version - 1})).status_code == 409
            r = await c.post(path, json={'id': 'c', 'shot': 'a', 'version': version})
            assert r.status_code == 200, r.text
            return r.json()
    out = asyncio.run(run())
    assert [s['id'] for s in out['slides']][:3] == ['a', 'b', 'c']
    assert ids(store.load('move'))[0] == ['a', 'b', 'c']

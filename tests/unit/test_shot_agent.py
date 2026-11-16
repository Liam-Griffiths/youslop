"""Shot design: the cut picture mode and the shot agent. No real LLM."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from app import llm, main, shot_agent, store
from app.schema import BinItem, Project, Slide, group_slides
from app.script_agent import shots


def _project():
    return Project(id='shotdesign', idea='Synthetic', cast=[{'subject': 'Brass carrier'}],
                   bin=[BinItem(id='b1', kind='image', title='Network map, 1934')], slides=[
        Slide(id='a', narration='Opening line.', visual_note='Carrier', chapter='One'),
        Slide(id='b', narration='It was not small.', visual_note='Network'),
        Slide(id='c', narration='Four hundred kilometres.', visual_note='Network', picture_mode='hold'),
        Slide(id='d', narration='A hundred and thirty offices.', visual_note='Network', picture_mode='hold',
              note='PRIVATE'),
    ])


def test_cut_starts_a_picture_but_not_a_shot():
    p = _project()
    assert [[s.id for s in run] for run in shots(p)] == [['a'], ['b', 'c', 'd']]
    p.slides[2].picture_mode = 'cut'
    # b keeps a's picture (auto grouping ignores descriptions); cut starts c's own.
    assert [[s.id for s in run] for run in group_slides(p.slides, 2)] == [['a', 'b'], ['c', 'd']]
    assert [[s.id for s in run] for run in shots(p)] == [['a'], ['b', 'c', 'd']]


def test_patch_accepts_cut_and_rejects_nonsense(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            ok = await c.patch('/api/projects/shotdesign/slides/c', json={'picture_mode': 'cut'})
            bad = await c.patch('/api/projects/shotdesign/slides/c', json={'picture_mode': 'sideways'})
            return ok, bad
    ok, bad = asyncio.run(run())
    assert ok.status_code == 200, ok.text
    assert bad.status_code >= 400
    assert store.load('shotdesign').picture_runs()[-1] == ['c', 'd']


def test_agent_validates_a_plan_and_never_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())
    before = deepcopy(store.load('shotdesign').to_dict())
    prompts = []

    def fake(prompt, **kw):
        prompts.append(prompt)
        assert kw['require']({'reply': 'x'})
        return {'reply': 'Open on a photo, then a map.', 'description': 'The network spreading under Paris.',
                'visuals': [{'from': 'c', 'kind': 'Diagram', 'query': '427 km lines', 'why': 'A number'},
                            {'from': 'c', 'kind': 'photo', 'query': 'duplicate'},
                            {'from': 'a', 'kind': 'photo', 'query': 'other shot'},
                            {'from': 'd', 'kind': 'hologram', 'query': 'bad kind'},
                            {'from': 'd', 'kind': 'map', 'query': 'Paris'}, 'junk']}
    monkeypatch.setattr(llm, 'complete_json', fake)

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            path = '/api/projects/shotdesign/script/shot-agent'
            assert (await c.post(path, json={'message': '', 'shot': 'b'})).status_code == 400
            assert (await c.post(path, json={'message': 'Plan it', 'shot': 'zzz'})).status_code == 404
            r = await c.post(path, json={'message': 'Plan it', 'shot': 'b', 'history': [{'role': 'user', 'text': 'Earlier'}]})
            assert r.status_code == 200, r.text
            return r.json()
    out = asyncio.run(run())
    # The first visual always starts on the shot's first paragraph.
    assert [(v['start'], v['kind']) for v in out['visuals']] == [('b', 'diagram'), ('d', 'map')]
    assert out['visuals'][0]['paragraph'] == 1 and out['description'].startswith('The network')
    prompt = prompts[0]
    assert '[b] It was not small.  <- visual starts here: photo' in prompt
    assert 'Brass carrier' in prompt and 'Network map, 1934' in prompt and 'PRIVATE' not in prompt
    assert 'Writer: Earlier' in prompt
    assert store.load('shotdesign').to_dict() == before


def test_agent_reports_model_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: (_ for _ in ()).throw(llm.LLMError('offline')))
    with pytest.raises(Exception) as err:
        shot_agent.ask(store.load('shotdesign'), 'b', 'Hello')
    assert 'offline' in str(err.value)

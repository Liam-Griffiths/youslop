"""Script agent: proposes only, validates ids, keeps private notes out. No real LLM."""
import asyncio
from copy import deepcopy

import httpx

from app import llm, main, script_agent, store
from app.schema import Project, Slide


def _project():
    return Project(id='agent', idea='Synthetic', slides=[
        Slide(id='a', narration='Paris stopped in 1984.', chapter='Opening', visual_note='Carrier',
              note='PRIVATE NOTE NEVER SEND', take={'path': 'takes/a.wav', 'duration': 3}),
        Slide(id='b', narration='Four hundred kilometres of tube.', visual_note='Engraving'),
        Slide(id='c', narration='Berlin had its own.', visual_note='Engraving'),
        Slide(id='d', narration='A forced break.', visual_note='Engraving', picture_mode='new'),
        Slide(id='i', insert={'kind': 'card', 'seconds': 4, 'text': 'Card'}),
        Slide(id='e', narration='Undescribed but continuing.'),
    ], research={'facts': [{'claim': 'Berlin had nearly 400 km of tubes around 1940.', 'source': 'Archive',
                            'date': '1940', 'confidence': 'medium'}]})


def test_shots_match_the_page_grouping():
    p = _project()
    assert [[s.id for s in run] for run in script_agent.shots(p)] == [['a'], ['b', 'c'], ['d'], ['i'], ['e']]
    p.slides.pop(4)
    p.slides[4].picture_mode = 'hold'  # undescribed, continuing d's picture: stays in d's shot
    assert [s.id for s in script_agent.shots(p)[-1]] == ['d', 'e']


def test_agent_validates_proposals_and_never_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())
    before = deepcopy(store.load('agent').to_dict())
    prompts = []

    def fake(prompt, **kw):
        prompts.append(prompt)
        assert kw['require']({'reply': 'x'})
        return {'reply': 'Paragraph 2 has no source for Paris.',
                'edits': [{'id': 'c', 'text': 'Berlin ran its own.', 'why': 'Shorter'},
                          {'id': 'c', 'text': 'A duplicate edit.'},
                          {'id': 'b', 'text': 'Four hundred kilometres of tube.'},
                          {'id': 'i', 'text': 'Inserts are not spoken.'},
                          {'id': 'missing', 'text': 'No such paragraph.'}, 'junk'],
                'flags': [{'id': 'b', 'quote': 'Four hundred kilometres', 'problem': 'F1 is about Berlin.'},
                          {'id': 'nope', 'problem': 'Unknown id'}]}
    monkeypatch.setattr(llm, 'complete_json', fake)

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            path = '/api/projects/agent/script/agent'
            assert (await c.post(path, json={'message': '  '})).status_code == 400
            r = await c.post(path, json={'message': 'Tighten shot 2', 'shot': 'b',
                                         'history': [{'role': 'user', 'text': 'Earlier question'}, 'junk']})
            assert r.status_code == 200, r.text
            return r.json()
    out = asyncio.run(run())
    assert out['reply'].startswith('Paragraph 2')
    assert out['edits'] == [dict(id='c', paragraph=3, before='Berlin had its own.', after='Berlin ran its own.', why='Shorter')]
    assert out['flags'] == [dict(id='b', paragraph=2, quote='Four hundred kilometres', problem='F1 is about Berlin.')]
    prompt = prompts[0]
    assert 'PRIVATE NOTE' not in prompt
    assert '### Shot 2  <- the writer is looking at this shot' in prompt
    assert '[b] ¶2: Four hundred kilometres of tube.' in prompt and 'F1. Berlin had nearly 400 km' in prompt
    assert 'Writer: Earlier question' in prompt and '[insert card, not spoken]' in prompt
    assert store.load('agent').to_dict() == before


def test_agent_reports_model_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())

    def broken(prompt, **kw):
        raise llm.LLMError('offline')
    monkeypatch.setattr(llm, 'complete_json', broken)

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            return await c.post('/api/projects/agent/script/agent', json={'message': 'Hello'})
    r = asyncio.run(run())
    assert r.status_code == 502 and 'offline' in r.json()['detail']

"""Edit's agent: find a place, propose graphics, titles and chapters. No real LLM."""
import asyncio
from copy import deepcopy

import httpx

from app import edit_agent, llm, main, store
from app.schema import Project, Slide


def _project():
    return Project(id='editagent', idea='Tube mail', slides=[
        Slide(id='a', narration='Paris decided to build in 1865.', chapter='Paris'),
        Slide(id='b', narration='Berlin built first, on 18 November 1865.', overlays=[
            dict(id='g1', block_id='lower_third_panel', vars={'title': 'Old', 'subtitle': '', 'picture': ''},
                 at=0.0, dur=4.0, position='bottom_left', by='hand')]),
        Slide(id='cam', narration='I think that matters.', on_camera=True),
    ])


def test_agent_checks_every_card_and_never_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())
    before = deepcopy(store.load('editagent').to_dict())
    prompts = []

    def fake(prompt, **kw):
        prompts.append(prompt)
        assert kw['require']({'reply': 'x'}) and not kw['require']([])
        return {'reply': 'Berlin is paragraph 2.', 'goto': 'b', 'actions': [
            {'type': 'graphic', 'paragraph': 'b', 'block': 'lower_third_panel', 'text': {'title': 'Berlin, 1865'},
             'position': 'top_right', 'on': 'berlin built first', 'seconds': 500, 'why': 'Names the place'},
            {'type': 'graphic', 'paragraph': 'b', 'block': 'lower_third_panel', 'text': {'title': 'X'},
             'on': 'words that are not spoken', 'position': 'sideways', 'seconds': 'long'},
            {'type': 'graphic', 'paragraph': 'b', 'block': 'lower_third_panel', 'text': {}},
            {'type': 'graphic', 'paragraph': 'b', 'block': 'no_such_block', 'text': {'title': 'X'}},
            {'type': 'graphic', 'paragraph': 'cam', 'block': 'lower_third_panel', 'text': {'title': 'X'}},
            {'type': 'graphic', 'paragraph': 'b', 'block': 'place_pin', 'text': {'title': 'Berlin'}},
            {'type': 'title', 'paragraph': 'a', 'text': 'T' * 80},
            {'type': 'chapter', 'paragraph': 'a', 'text': 'Paris'},
            {'type': 'chapter', 'paragraph': 'b', 'text': 'Berlin'},
            {'type': 'remove', 'paragraph': 'b', 'graphic': 'g1'},
            {'type': 'remove', 'paragraph': 'b', 'graphic': 'missing'},
            {'type': 'title', 'paragraph': 'gone', 'text': 'X'}, 'junk']}
    monkeypatch.setattr(llm, 'complete_json', fake)

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            good = await c.post('/api/projects/editagent/edit/agent', json={
                'message': 'Where is Berlin? Add a title.', 'focus': 'a', 'starts': {'a': 0, 'b': 61.5, 'zz': 9, 'cam': 'x'},
                'history': [{'role': 'user', 'text': 'Earlier question'}]})
            return good, await c.post('/api/projects/editagent/edit/agent', json={'message': '  '})
    good, empty = asyncio.run(run())
    assert good.status_code == 200, good.text
    assert empty.status_code == 400
    out = good.json()
    assert out['goto'] == 'b' and out['goto_paragraph'] == 2
    cards = out['actions']
    assert [c['type'] for c in cards] == ['graphic', 'graphic', 'title', 'chapter', 'remove']
    first, second = cards[0], cards[1]
    # Sample words never reach the screen; lengths and positions are clamped to the block's own.
    assert first['vars'] == {'title': 'Berlin, 1865', 'subtitle': '', 'picture': ''}
    assert first['dur'] == 30 and first['position'] == 'top_right' and first['on'] == 'berlin built first'
    assert second['dur'] == 4 and second['position'] == 'bottom_left' and second['on'] == ''
    assert cards[2]['text'] == 'T' * 40 and cards[3] == dict(type='chapter', text='Berlin', was='', sid='b', paragraph=2, why='')
    assert cards[4]['graphic'] == 'g1'
    prompt = prompts[0]
    assert '[b] ¶2 1:01' in prompt and '<- PLAYHEAD' in prompt.split('[a]')[1].split('\n')[0]
    assert 'graphic g1 (lower_third_panel: Old)' in prompt and 'chapter card "Paris"' in prompt
    assert 'lower_third_panel' in prompt and 'place_pin' not in prompt and 'Earlier question' in prompt
    assert store.load('editagent').to_dict() == before


def test_a_card_applies_through_the_ordinary_slide_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    store.save(_project())
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: {'reply': 'ok', 'actions': [
        {'type': 'graphic', 'paragraph': 'a', 'block': 'lower_third_panel', 'text': {'title': 'Paris, 1865'}}]})
    card = edit_agent.ask(store.load('editagent'), 'Add a title')['actions'][0]

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            return await c.patch('/api/projects/editagent/slides/a', json={'overlays': [dict(
                id='graphic-1', block_id=card['block'], vars=card['vars'], at=0, dur=card['dur'],
                position=card['position'], by='hand')]})
    assert asyncio.run(run()).status_code == 200
    saved = store.load('editagent').slide('a').overlays[0]
    assert saved['vars']['title'] == 'Paris, 1865' and saved['vars']['subtitle'] == ''

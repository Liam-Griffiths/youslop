"""Create: graphics made with an agent, versioned, previewed and placed. No real LLM or Chromium."""
import asyncio
import time

import httpx
import pytest

from app import custom_scenes, graphics, jobs, llm, main, scenes, store
from app.schema import Project, Slide

GOOD = ('<section class="cb-slide cb-center"><p class="cb-label" data-layer="when" data-start="0" data-motion="fade">By 1934</p>'
        '<h1 class="cb-number cb-accent" data-layer="number" data-start="0.8" data-motion="pop">427 km</h1></section>')


def _call(method, path, **kw):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            return await c.request(method, path, **kw)
    return asyncio.run(run())


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)

    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    store.save(Project(id='gfx', idea='Tube mail', slides=[Slide(id='a', narration='It reached 427 km.', visual_note='Size')],
                       research={'facts': [{'claim': 'About 427 km of tube by 1934.'}]}))


def _make():
    r = _call('POST', '/api/projects/gfx/graphics', json={'brief': 'The network length landing as a big number. Brass.'})
    assert r.status_code == 200, r.text
    return r.json()['graphic']


def test_create_agent_versions_and_hand_edits(project, monkeypatch):
    g = _make()
    assert g['title'] == 'The network length landing as a big number' and g['versions'] == [] and g['current'] == -1
    prompts, replies = [], [
        {'reply': 'A number that lands.', 'html': GOOD, 'title': 'Network length'},
        {'reply': 'Bigger.', 'html': '<section class="cb-slide" style="color:red"><h1>x</h1></section>'},
        {'reply': 'Fixed.', 'html': GOOD.replace('By 1934', 'In 1934')}]

    def fake(prompt, **kw):
        prompts.append(prompt)
        return replies.pop(0)
    monkeypatch.setattr(llm, 'complete_json', fake)
    r = _call('POST', f"/api/projects/gfx/graphics/{g['id']}/agent", json={'message': 'Make this graphic'})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out['changed'] and out['graphic']['title'] == 'Network length' and out['graphic']['current'] == 0
    assert 'F1. About 427 km of tube by 1934.' in prompts[0] and 'cb-number' in prompts[0] and 'LENGTH: 6.0 seconds' in prompts[0]
    # A fragment outside the vocabulary is retried once with the error, never saved.
    r = _call('POST', f"/api/projects/gfx/graphics/{g['id']}/agent", json={'message': 'Make it red', 'history': [{'role': 'user', 'text': 'Make this graphic'}]})
    assert r.status_code == 200, r.text
    saved = store.load('gfx').graphics[0]
    assert len(saved['versions']) == 2 and 'In 1934' in saved['versions'][1]['html'] and 'style' not in saved['versions'][1]['html']
    assert saved['title'] == 'Network length'  # renamed only on the first version
    assert 'rejected' in prompts[2]
    # Versions, length and hand edits.
    assert _call('PATCH', f"/api/projects/gfx/graphics/{g['id']}", json={'current': 0, 'seconds': 40}).status_code == 200
    saved = store.load('gfx').graphics[0]
    assert saved['current'] == 0 and saved['seconds'] == graphics.MAX_SECONDS
    assert _call('PATCH', f"/api/projects/gfx/graphics/{g['id']}", json={'html': '<script>alert(1)</script>'}).status_code == 400
    assert _call('PATCH', f"/api/projects/gfx/graphics/{g['id']}", json={'current': 9}).status_code == 400
    assert _call('PATCH', f"/api/projects/gfx/graphics/{g['id']}", json={'html': GOOD}).json()['graphic']['current'] == 2


def test_still_and_place(project, monkeypatch):
    g = _make()
    assert _call('GET', f"/api/projects/gfx/graphics/{g['id']}/still").status_code == 404
    monkeypatch.setattr(llm, 'complete_json', lambda prompt, **kw: {'reply': 'ok', 'html': GOOD})
    _call('POST', f"/api/projects/gfx/graphics/{g['id']}/agent", json={'message': 'Make it'})
    shots = []
    monkeypatch.setattr(scenes, 'capture', lambda root, template, ctx, *, t, size: shots.append((template, t, size)) or b'\x89PNG')
    r = _call('GET', f"/api/projects/gfx/graphics/{g['id']}/still", params={'t': 99})
    assert r.status_code == 200 and r.content == b'\x89PNG'
    assert shots == [('slides/custom.html', 6.0, (480, 270))]  # clamped to the length, quarter size
    assert _call('POST', f"/api/projects/gfx/graphics/{g['id']}/place", json={'slide': 'nope'}).status_code == 404

    def candidate(fragment, dest, spec, *, motion, seconds, project):
        assert motion == 'reveal' and seconds == 6.0 and 'cb-number' in fragment
        return dict(id='custom_x', provider='custom', kind='video', local_path='media/custom_x.mp4', custom_html=fragment, custom={})
    monkeypatch.setattr(custom_scenes, 'html_candidate', candidate)
    job = _call('POST', f"/api/projects/gfx/graphics/{g['id']}/place", json={'slide': 'a'}).json()['job']
    for _ in range(100):
        if jobs.get(job)['state'] != 'running':
            break
        time.sleep(.02)
    assert jobs.get(job)['state'] == 'done', jobs.get(job)
    p = store.load('gfx')
    s = p.slides[0]
    assert s.chosen_id == 'custom_x' and s.candidates[0]['graphic_id'] == g['id'] and s.locked_media
    assert p.graphics[0]['used_in'] == ['a']


def test_remove_keeps_placed_renders(project):
    g = _make()
    p = store.load('gfx')
    p.slides[0].candidates.append({'id': 'custom_y', 'graphic_id': g['id']})
    store.save(p)
    assert _call('DELETE', f"/api/projects/gfx/graphics/{g['id']}").json()['graphics'] == []
    assert store.load('gfx').slides[0].candidates[0]['id'] == 'custom_y'

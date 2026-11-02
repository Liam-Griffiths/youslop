"""Board persistence and selective writing, without research, models or renders."""
from copy import deepcopy

import pytest

from app import plan_board, script_gen, store
from app.schema import Project, Slide


def fixture():
    sections = [{'heading': name, 'summary': name, 'words': 100, 'kind': 'main'}
                for name in ('Door', 'Street')]
    return Project(id='plan-fixture', idea='Synthetic plan', outline={'sections': sections},
                   slides=[Slide(id=f's{i}', beat=s['heading'], narration=s['heading'])
                           for i, s in enumerate(sections)])


def test_reorder_citations_reload_and_only_changed_writer(monkeypatch):
    p = fixture()
    p.set_take(p.slides[0], 'mic', {'path': 'takes/door.wav', 'duration': 3})
    outline = plan_board.outline_for(p)
    outline['sections'].reverse()
    outline['sections'][0]['sources'] = ['https://example.test/archive']
    outline['sections'][0]['summary'] = 'Changed street'
    outline['sections'][0]['chapter'] = 'Door'
    plan_board.save(p, outline)
    store.save(p)
    calls = []
    def writer(project, board, i):
        calls.append(board['sections'][i]['heading'])
        return [{'kind': 'main', 'beat': 'Street', 'text': 'New street', 'visual': 'Street image'}]
    monkeypatch.setattr(script_gen, '_write_section', writer)
    plan_board.write(p.id, lambda _: None)
    fresh = store.load(p.id)
    assert calls == ['Street']
    assert [s.narration for s in fresh.slides] == ['New street', 'Door']
    assert fresh.slides[1].id == 's0'
    assert fresh.slides[1].takes['mic']['path'] == 'takes/door.wav'
    assert fresh.outline['sections'][0]['sources'] == ['https://example.test/archive']
    plan_board.write(p.id, lambda _: None)
    assert calls == ['Street']  # a second write is free


def test_changed_beat_retires_all_recordings(monkeypatch):
    p = fixture()
    p.set_take(p.slides[0], 'mic', {'path': 'takes/original.wav'})
    p.set_take(p.slides[0], 'camera', {'path': 'raw/camera.webm'})
    p.slides[0].history = [{'path': 'takes/older.wav'}]
    outline = plan_board.outline_for(p)
    outline['sections'][0]['summary'] = 'Changed'
    plan_board.save(p, outline)
    store.save(p)
    monkeypatch.setattr(script_gen, '_write_section', lambda *args: [
        {'kind': 'main', 'beat': 'Door', 'text': 'Replacement', 'visual': ''}])
    plan_board.write(p.id, lambda _: None)
    fresh = store.load(p.id)
    assert len(fresh.slides) == 2
    assert {t['path'] for t in fresh.slides[0].history} == {
        'takes/original.wav', 'raw/camera.webm', 'takes/older.wav'}


def test_draft_bank_follows_beats_and_invalidates_changed():
    p = fixture()
    p.slides = []
    p.draft = {'outline': p.outline, 'sections': {'0': ['door'], '1': ['street']}}
    p.outline = {}
    outline = plan_board.outline_for(p)
    outline['sections'].reverse()
    outline['sections'][1]['summary'] = 'Changed'
    plan_board.save(p, outline)
    assert p.draft['sections'] == {'0': ['street']}
    assert p.draft['outline'] == p.outline


def test_bad_payloads_and_beat_removal_leave_project_intact():
    p = fixture()
    before = deepcopy(p)
    for outline in ({}, {'sections': [None]}, {'sections': []}):
        with pytest.raises(ValueError):
            plan_board.save(p, outline)
        assert p == before


def test_concurrent_edit_not_overwritten(monkeypatch):
    p = fixture()
    p.slides = []
    store.save(p)
    def writer(project, outline, i):
        fresh = store.load(p.id)
        fresh.title = 'Edited during generation'
        store.save(fresh)
        return [{'kind': 'main', 'beat': outline['sections'][i]['heading'], 'text': 'New', 'visual': ''}]
    monkeypatch.setattr(script_gen, '_write_section', writer)
    with pytest.raises(ValueError, match='Project changed'):
        plan_board.write(p.id, lambda _: None)
    assert store.load(p.id).title == 'Edited during generation'


def test_reorder_only_and_http_contract(monkeypatch):
    import asyncio
    import httpx
    from app import main
    p = fixture()
    store.save(p)
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    monkeypatch.setattr(script_gen, '_write_section', lambda *args: pytest.fail('Reorder called a model'))
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://fixture') as client:
            url = f'/api/projects/{p.id}/plan'
            outline = (await client.get(url)).json()
            outline['sections'].reverse()
            response = await client.patch(url, json=outline)
            assert response.status_code == 200
            assert (await client.patch(url, json={'sections': []})).status_code == 400
            assert (await client.get('/api/projects/missing/plan')).status_code == 404
    asyncio.run(exercise())
    plan_board.write(p.id, lambda _: None)
    assert [s.id for s in store.load(p.id).slides] == ['s1', 's0']


def test_new_beat_with_existing_heading_is_written(monkeypatch):
    p = fixture()
    outline = plan_board.outline_for(p)
    outline['sections'].append({**outline['sections'][0], 'id': 'new-beat'})
    plan_board.save(p, outline)
    store.save(p)
    calls = []
    def writer(project, board, i):
        calls.append(i)
        return [{'kind': 'main', 'beat': 'Door', 'text': 'A new beat', 'visual': ''}]
    monkeypatch.setattr(script_gen, '_write_section', writer)
    plan_board.write(p.id, lambda _: None)
    assert calls == [2]
    assert [s.narration for s in store.load(p.id).slides] == ['Door', 'Street', 'A new beat']

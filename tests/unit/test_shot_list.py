"""Synthetic script/shoot only; PDF CDP and all model calls stay mocked."""
import asyncio
import base64

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app import footage, shot_list, shot_list_ui as ui, stage, store
from app.schema import PlannedShot, Project, Slide


@pytest.fixture
def episode(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    monkeypatch.setattr(stage, 'browser', lambda: '/fake/chromium')
    monkeypatch.setattr('app.llm.complete_json', lambda *a, **kw: pytest.fail('Model called'))
    project = Project('pshots', 'Building', title='<Building>', slides=[
        Slide(id='s1', visual_note='Wide exterior brick building'),
        Slide(id='s2', visual_note='Medium interior lobby reception'),
        Slide(id='s3', visual_note='Close-up rooftop chimney')])
    store.save(project)
    shoot = footage.Shoot('sfixture', path='<Fake shoot>', clips=[
        footage.Clip('c1', 'f1', labels=['exterior', 'brick building']),
        footage.Clip('c2', 'f1', auto_labels={'location': 'interior', 'subject': 'stairs'}),
        footage.Clip('c3', 'f1', labels=['close-up', 'wide'])])
    footage._save(shoot)
    return project, shoot


def test_grouping_adjacency_sizes_notes_and_checks(episode):
    project, _ = episode
    project.slides = [Slide(id='s1', visual_note='Wide exterior brick building'),
                      Slide(id='s2', visual_note='Wide brick building exterior'),
                      Slide(id='s3', visual_note='Insert brick building exterior')]
    shots = shot_list.build(project)
    assert [s.paragraph_ids for s in shots] == [['s1', 's2'], ['s3']]
    assert [s.size for s in shots] == ['wide', 'insert']
    assert len(shots[0].notes) == 2
    shots[0].done = True
    project.shot_list = shots
    assert shot_list.build(project)[0].done
    project.slides[1].visual_note += ' windows'
    assert not shot_list.build(project)[0].done
    project.slides.insert(1, Slide(id='gap'))
    assert len(shot_list.build(project)) == 3
    project.slides = [Slide(id='s1', visual_note='Wide street market'),
                      Slide(id='s2', visual_note='Wide interior lobby')]
    assert len(shot_list.build(project)) == 2


def test_fixture_coverage_and_schema_roundtrip(episode):
    project, shoot = episode
    project.shot_list = shot_list.build(project)
    assert [s.size for s in project.shot_list] == ['wide', 'medium', 'close']
    results = [shot_list.coverage(s, shoot) for s in project.shot_list]
    assert [r['status'] for r in results] == ['covered', 'maybe', 'missing']
    assert results[0]['matches'][0]['clip_id'] == 'c1'
    assert shoot.clips[-1].labels == ['close-up', 'wide']
    raw = project.to_dict()
    raw['future'] = 42
    raw['shot_list'][0]['future'] = 42
    saved = Project.from_dict(raw)
    assert saved.shot_list == project.shot_list
    assert Project.from_dict({'id': 'old', 'idea': ''}).shot_list == []
    assert shot_list.coverage(PlannedShot(notes=['Wide shot']), shoot)['status'] == 'missing'


def test_page_build_save_pdf_availability_and_escaping(episode, monkeypatch):
    project, shoot = episode
    assert b'No shots saved' in ui.page(project.id).body
    assert ui.build(project.id).status_code == 303
    page = ui.page(project.id, shoot.id).body.decode()
    assert all(text in page for text in ('covered', 'maybe', 'missing', 'c1', 'c2'))
    assert '&lt;Building&gt;' in page and '&lt;Fake shoot&gt;' in page
    assert 'type="checkbox"' in page and 'name="viewport"' in page
    assert 'Download PDF' in page
    assert ui.save_checks(project.id, shoot.id, [0]).status_code == 303
    assert store.load(project.id).shot_list[0].done
    ui.build(project.id)
    assert store.load(project.id).shot_list[0].done
    ui.save_checks(project.id, done=[])
    assert not any(s.done for s in store.load(project.id).shot_list)
    monkeypatch.setattr(stage, 'browser', lambda: None)
    assert 'Download PDF' not in ui.page(project.id).body.decode()


def test_page_errors_and_pdf_response(episode, monkeypatch):
    project, shoot = episode
    for call, status in [(lambda: ui.page('../bad'), 400),
                         (lambda: ui.page('missing'), 404),
                         (lambda: ui.page(project.id, 'missing'), 404),
                         (lambda: ui.save_checks(project.id, done=[-1]), 400)]:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == status
    ui.build(project.id)
    def print_pdf(html):
        assert '<Building>' not in html and 'Download PDF' not in html
        assert 'covered' in html and 'Save checkboxes' not in html
        return b'%PDF-fixture'
    monkeypatch.setattr(stage, 'print_pdf', print_pdf)
    response = ui.pdf(project.id, shoot.id)
    assert response.body == b'%PDF-fixture'
    assert response.media_type == 'application/pdf'
    monkeypatch.setattr(stage, 'print_pdf', lambda html: (_ for _ in ()).throw(stage.StageError('No Chromium')))
    with pytest.raises(HTTPException) as exc:
        ui.pdf(project.id)
    assert exc.value.status_code == 503


def test_pdf_one_navigation_one_print_no_capture(monkeypatch):
    calls = []
    class Cdp:
        def clear_events(self):
            pass
        def wait_event(self, method):
            assert method == 'Page.loadEventFired'
        def send(self, method, params=None, session=None):
            calls.append((method, params))
            if method == 'Page.printToPDF':
                return {'data': base64.b64encode(b'%PDF-fixture').decode()}
            return {}
    monkeypatch.setattr(stage, '_evaluate', lambda *a: None)
    monkeypatch.setattr(stage, '_run_cdp', lambda job, progress, **kw:
                        kw['session_action'](Cdp(), 'session', None))
    assert stage.print_pdf('<html>fixture</html>') == b'%PDF-fixture'
    assert [method for method, params in calls] == ['Page.navigate', 'Page.printToPDF']
    assert calls[0][1]['url'].startswith('data:text/html;base64,')


def test_http_forms_and_token_cookie_without_sockets(episode, monkeypatch):
    from app import main
    project, shoot = episode
    monkeypatch.setattr(main, 'ACCESS_TOKEN', 'fixture-token')
    # Keep endpoint dispatch on this test's event loop as well: sandboxed
    # thread-to-loop wakeup sockets are unavailable on some runners.
    async def direct(func, **kwargs):
        return func(**kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def exercise():
        transport = httpx.ASGITransport(app=main.app, client=('192.0.2.1', 1234))
        async with httpx.AsyncClient(transport=transport, base_url='http://fixture') as client:
            url = f'/projects/{project.id}/shot-list'
            assert (await client.get(url)).status_code == 401
            assert (await client.get(url + '?t=fixture-token')).status_code == 200
            assert (await client.post(url + '/build')).status_code == 303
            assert (await client.post(url, data={'done': '1'})).status_code == 303
            assert store.load(project.id).shot_list[1].done
            assert (await client.post(url, data={'done': 'bad'})).status_code == 422
            assert (await client.post(url)).status_code == 303
            assert not any(s.done for s in store.load(project.id).shot_list)
            page = await client.get(url, params={'shoot': shoot.id})
            assert page.status_code == 200 and 'covered' in page.text
    asyncio.run(exercise())


@pytest.mark.parametrize('path,method', [('/projects/pshots/shot-list', 'GET'),
    ('/projects/pshots/shot-list', 'POST'), ('/projects/pshots/shot-list/build', 'POST'),
    ('/projects/pshots/shot-list/pdf', 'GET')])
def test_remote_routes_require_existing_token(episode, monkeypatch, path, method):
    from app import main
    monkeypatch.setattr(main, 'ACCESS_TOKEN', 'fixture-token')
    assert any(r.path == path.replace('pshots', '{pid}') and method in r.methods
               for r in main.app.routes)
    async def check(query, host):
        request = Request(dict(type='http', method=method, path=path,
                               query_string=query, headers=[], client=(host, 1234)))
        async def next_handler(request):
            return Response('allowed')
        return await main._require_token(request, next_handler)
    assert asyncio.run(check(b'', '192.0.2.1')).status_code == 401
    allowed = asyncio.run(check(b't=fixture-token', '192.0.2.1'))
    assert allowed.status_code == 200 and 'vb_token' in allowed.headers['set-cookie']
    assert asyncio.run(check(b'', '127.0.0.1')).status_code == 200

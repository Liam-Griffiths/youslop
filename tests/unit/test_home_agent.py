"""Home agent: proposes only; applying a note or question writes; a search reads pages into documents. No real LLM."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from app import home_agent, llm, main, research, research_docs, store
from app.schema import BinItem, Project, Slide


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
    store.save(Project(id='home', idea='Paris tube mail', bin=[BinItem(id='m', kind='image', title='Map', shows='The 1934 network')],
                       slides=[Slide(id='a', narration='Paris stopped in 1984.', visual_note='Carrier', note='PRIVATE')],
                       research={'facts': [{'claim': 'Service ended 30 March 1984.', 'source': 'Web'}],
                                 'open_questions': ['Who ran it after 1945?'],
                                 'documents': [{'id': 'd1', 'title': 'Thesis', 'kind': 'pdf', 'pages': 212}]}))


def test_agent_proposes_and_never_writes(project, monkeypatch):
    before = deepcopy(store.load('home').to_dict())
    prompts = []

    def fake(prompt, **kw):
        prompts.append(prompt)
        assert kw['require']({'reply': 'x'})
        return {'reply': 'F1 covers the end date.', 'actions': [
            {'type': 'search', 'text': 'Paris pneumatic post 1945 PTT', 'why': 'Open question'},
            {'type': 'Search', 'text': 'paris pneumatic post 1945 ptt'},
            {'type': 'question', 'text': 'How long was the network?'},
            {'type': 'note', 'text': 'Ask the museum for audio.'},
            {'type': 'delete', 'text': 'everything'}, {'type': 'note', 'text': ''}, 'junk']}
    monkeypatch.setattr(llm, 'complete_json', fake)
    monkeypatch.setattr(research, 'available', lambda: True)
    assert _call('POST', '/api/projects/home/home/agent', json={'message': ' '}).status_code == 400
    r = _call('POST', '/api/projects/home/home/agent', json={'message': "What's missing?", 'history': [{'role': 'user', 'text': 'Earlier'}]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [a['type'] for a in out['actions']] == ['search', 'question', 'note'] and out['can_search'] is True
    prompt = prompts[0]
    assert 'F1. Service ended 30 March 1984. (Web)' in prompt and '- Thesis (pdf, 212 pages)' in prompt
    assert 'Who ran it after 1945?' in prompt and 'image: Map (shows The 1934 network)' in prompt and '1. Carrier' in prompt
    assert 'PRIVATE' not in prompt and 'Writer: Earlier' in prompt
    assert store.load('home').to_dict() == before


def test_apply_note_and_question(project):
    r = _call('POST', '/api/projects/home/home/apply', json={'type': 'note', 'text': 'Ask the museum for audio.\nThey may have a recording.'})
    assert r.status_code == 200, r.text
    p = store.load('home')
    assert p.bin[-1].kind == 'note' and p.bin[-1].title == 'Ask the museum for audio.' and 'recording' in p.bin[-1].note
    assert _call('POST', '/api/projects/home/home/apply', json={'type': 'question', 'text': 'How long was it?'}).status_code == 200
    _call('POST', '/api/projects/home/home/apply', json={'type': 'question', 'text': 'How long was it?'})
    assert store.load('home').research['open_questions'] == ['Who ran it after 1945?', 'How long was it?']
    assert _call('POST', '/api/projects/home/home/apply', json={'type': 'delete', 'text': 'x'}).status_code == 400


def test_search_without_a_backend_is_refused(project, monkeypatch):
    monkeypatch.setattr(research, 'available', lambda: False)
    r = _call('POST', '/api/projects/home/home/apply', json={'type': 'search', 'text': 'Paris tubes'})
    assert r.status_code == 409


def test_search_saves_pages_as_documents_and_reads_them(project, monkeypatch):
    monkeypatch.setattr(research, 'search', lambda q, n: [{'url': 'https://a.test/1', 'title': 'Page one'},
                                                          {'url': 'https://b.test/2', 'title': 'Broken'}, {'title': 'no url'}])

    def fetch(pid, url, title=''):
        if 'b.test' in url:
            raise research_docs.HTTPException(502, 'Could not fetch')
        doc = research_docs._new('web', title, url=url)
        return research_docs._store(pid, doc, ['The network reached 427 km in 1934.'])
    monkeypatch.setattr(research_docs, 'fetch_document', fetch)
    monkeypatch.setattr(llm, 'complete_json', lambda prompt, **kw: {'facts': [
        {'claim': 'The network reached 427 km in 1934.', 'page': 1, 'quote': '427 km in 1934'}]})
    logs = []
    out = home_agent.search_into_documents('home', 'Paris network length', logs.append)
    assert out == {'documents': 1, 'added': 1}
    p = store.load('home')
    doc = p.research['documents'][-1]
    assert doc['title'] == 'Page one' and doc['found_by'] == 'Paris network length' and doc['read_at']
    assert p.research['facts'][-1]['doc_id'] == doc['id'] and p.research['facts'][-1]['quote'] == '427 km in 1934'
    assert any('Skipped' in m for m in logs)

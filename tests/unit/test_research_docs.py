"""Research documents: add, paginate, read for facts with checked quotes. No real LLM."""
import asyncio
import shutil

import httpx
import pytest

from app import llm, main, research, research_docs, store
from app.schema import Project, Slide


def _client():
    async def direct(fn, *a, **kw):
        return fn(*a, **kw)
    return direct


def _call(method, path, **kw):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as c:
            return await c.request(method, path, **kw)
    return asyncio.run(run())


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', _client())
    store.save(Project(id='docs', idea='Tubes', slides=[Slide(id='a', narration='One.')],
                       research={'facts': [{'claim': 'Service ended 30 March 1984.', 'source': 'Web'}]}))
    return tmp_path


def test_paste_pages_and_listing(project):
    text = '\n\n'.join(f'Paragraph {i}. ' + 'word ' * 120 for i in range(20))
    r = _call('POST', '/api/projects/docs/documents/text', json={'title': 'Museum notes', 'text': text})
    assert r.status_code == 200, r.text
    doc = r.json()['documents'][0]
    assert doc['kind'] == 'text' and doc['title'] == 'Museum notes' and doc['pages'] > 1 and doc['facts'] == 0
    shown = _call('GET', f"/api/projects/docs/documents/{doc['id']}").json()
    assert len(shown['pages']) == doc['pages'] and shown['pages'][0].startswith('Paragraph 0.')
    assert _call('POST', '/api/projects/docs/documents/text', json={'text': '  '}).status_code == 400
    # The project file keeps the index; text lives beside it.
    assert store.load('docs').research['documents'][0]['id'] == doc['id']
    assert (project / 'docs' / 'docs' / f"{doc['id']}.txt").is_file()


def test_link_saves_a_readable_copy(project, monkeypatch):
    class Fake:
        headers = {'content-type': 'text/html; charset=utf-8'}
        text = ('<html><head><title>Paris pneumatic post</title></head><body><nav>Menu</nav>'
                '<p>The network peaked at about 427 km of tube in 1934, linking 130 offices.</p></body></html>')
        def raise_for_status(self):
            pass
    monkeypatch.setattr(research, '_client_for_web', lambda: type('C', (), {'get': lambda self, url: Fake()})())
    r = _call('POST', '/api/projects/docs/documents/link', json={'url': 'https://example.test/post'})
    assert r.status_code == 200, r.text
    doc = r.json()['documents'][0]
    assert doc['kind'] == 'web' and doc['title'] == 'Paris pneumatic post' and doc['url'] == 'https://example.test/post'
    page = _call('GET', f"/api/projects/docs/documents/{doc['id']}").json()['pages'][0]
    assert '427 km' in page and 'Menu' not in page
    assert _call('POST', '/api/projects/docs/documents/link', json={'url': 'file:///etc/passwd'}).status_code == 400


def test_upload_rejects_unknown_files(project):
    r = _call('POST', '/api/projects/docs/documents', files={'files': ('virus.exe', b'MZ', 'application/octet-stream')})
    assert r.status_code == 400


@pytest.mark.skipif(not shutil.which('pdftotext'), reason='pdftotext unavailable')
def test_pdf_pages(project, tmp_path):
    pdf = (b'%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
           b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
           b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R'
           b'/Resources<</Font<</F1 5 0 R>>>>>>endobj\n'
           b'4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (Tube mail 1866) Tj ET\nendstream endobj\n'
           b'5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF')
    r = _call('POST', '/api/projects/docs/documents', files={'files': ('thesis_1934.pdf', pdf, 'application/pdf')})
    assert r.status_code == 200, r.text
    doc = r.json()['documents'][0]
    assert doc['kind'] == 'pdf' and doc['title'] == 'thesis 1934' and doc['file'].endswith('.pdf')
    assert 'Tube mail 1866' in _call('GET', f"/api/projects/docs/documents/{doc['id']}").json()['pages'][0]
    assert _call('GET', f"/api/projects/docs/documents/{doc['id']}/file").status_code == 200


def test_read_keeps_real_quotes_and_dedupes(project, monkeypatch):
    pages = ['The network reached 427 km in 1934.', 'It linked 130 offices across Paris.']
    calls = []

    def fake(prompt, **kw):
        calls.append(prompt)
        assert '[PAGE 2]' in prompt and kw['require']({'facts': []})
        return {'facts': [
            {'claim': 'The network reached 427 km in 1934.', 'page': 1, 'quote': 'reached 427 km in 1934', 'confidence': 'high'},
            {'claim': '130 offices.', 'page': 2, 'quote': 'an invented quote'},
            {'claim': 'Out of range.', 'page': 9, 'quote': ''},
            {'claim': 'service ended 30 march 1984.', 'page': 1},
            {'claim': ''}, 'junk']}
    monkeypatch.setattr(llm, 'complete_json', fake)
    found = research_docs.read_facts(pages, 'Thesis')
    assert [(f['claim'], f['page'], f['quote']) for f in found] == [
        ('The network reached 427 km in 1934.', 1, 'reached 427 km in 1934'),
        ('130 offices.', 0, ''), ('Out of range.', 0, ''), ('service ended 30 march 1984.', 1, '')]
    p = store.load('docs')
    doc = {'id': 'd1', 'title': 'Thesis', 'kind': 'pdf'}
    p.research['documents'] = [doc]
    assert research_docs.apply_facts(p, doc, found) == 3  # the 1984 claim was already known
    added = [f for f in p.research['facts'] if f.get('doc_id') == 'd1']
    assert added[0]['source'] == 'Thesis, p. 1' and added[0]['quote'] and p.research['documents'][0]['read_at']


def test_remove_keeps_files_and_facts(project):
    doc = _call('POST', '/api/projects/docs/documents/text', json={'title': 'Notes', 'text': 'Some text.'}).json()['documents'][0]
    p = store.load('docs')
    p.research['facts'].append({'claim': 'From notes', 'doc_id': doc['id']})
    store.save(p)
    r = _call('DELETE', f"/api/projects/docs/documents/{doc['id']}")
    assert r.status_code == 200 and r.json()['documents'] == []
    assert (project / 'docs' / 'docs' / '.removed' / f"{doc['id']}.txt").is_file()
    assert any(f.get('claim') == 'From notes' for f in store.load('docs').research['facts'])

"""Research documents: PDFs, pasted text, saved web pages and scans.

A document is kept as its original file (when there is one) plus its text,
split into pages, under the project's docs/ folder. The list lives in
project.research["documents"]. Reading a document asks the model for facts
with page numbers and exact quotes; quotes are checked against the page text
and facts land in research["facts"] with doc_id, page and quote, beside the
facts the web research found. Removed documents move to docs/.removed.
"""
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import jobs, llm, research, store

MAX_BYTES = 80 * 1024 * 1024
MAX_PAGES = 600
PAGE_CHARS = 3000            # pasted text and web pages are cut into pages this long
CHUNK_CHARS = 14000          # one model read
MAX_CHUNKS = 12
TEXT_EXT = {'.txt', '.md', '.markdown', '.csv'}
HTML_EXT = {'.html', '.htm'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp'}

SYSTEM = ("You extract checkable facts from a research document for a documentary "
          "script. Use only what the text says. Reply with JSON only.")


def _load(pid):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', pid):
        raise HTTPException(400, 'Invalid project id')
    try:
        return store.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Project not found') from exc


def _docs_dir(pid):
    d = store.project_dir(pid) / 'docs'
    d.mkdir(exist_ok=True)
    return d


def documents(project):
    docs = (project.research or {}).get('documents')
    return docs if isinstance(docs, list) else []


def _find(project, ident):
    doc = next((d for d in documents(project) if isinstance(d, dict) and d.get('id') == ident), None)
    if doc is None:
        raise HTTPException(404, 'Document not found')
    return doc


# ------------------------------------------------------------------ extraction
def _paginate(text, size=PAGE_CHARS):
    text = re.sub(r'\r\n?', '\n', text).strip()
    pages, block = [], ''
    for para in re.split(r'\n\s*\n', text):
        if block and len(block) + len(para) > size:
            pages.append(block.strip())
            block = ''
        block += para + '\n\n'
        while len(block) > size * 1.5:
            pages.append(block[:size].strip())
            block = block[size:]
    if block.strip():
        pages.append(block.strip())
    return pages[:MAX_PAGES]


def pdf_pages(path):
    """Text per page: poppler's pdftotext when installed, else pypdf."""
    if shutil.which('pdftotext'):
        try:
            out = subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', str(path), '-'],
                                 capture_output=True, timeout=180, check=True).stdout.decode('utf-8', 'replace')
            pages = [re.sub(r'[ \t]+', ' ', p).strip() for p in out.split('\f')]
            while pages and not pages[-1]:
                pages.pop()
            return pages[:MAX_PAGES]
        except (subprocess.SubprocessError, OSError) as exc:
            raise HTTPException(422, f'Could not read that PDF: {exc}') from exc
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise HTTPException(422, 'Reading PDFs needs poppler (pdftotext) or the pypdf package installed') from exc
    try:
        return [(page.extract_text() or '').strip() for page in PdfReader(str(path)).pages[:MAX_PAGES]]
    except Exception as exc:  # pypdf raises many types for damaged files
        raise HTTPException(422, f'Could not read that PDF: {exc}') from exc


def image_pages(path):
    if not shutil.which('tesseract'):
        raise HTTPException(422, 'Reading scans needs tesseract installed')
    try:
        out = subprocess.run(['tesseract', str(path), '-'], capture_output=True, timeout=180, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(422, f'Could not read that scan: {exc}') from exc
    return _paginate(out.stdout.decode('utf-8', 'replace')) or ['']


def _store(pid, doc, pages):
    if not any(p.strip() for p in pages):
        raise HTTPException(422, 'No readable text in that document')
    (_docs_dir(pid) / f"{doc['id']}.txt").write_text('\f'.join(pages), encoding='utf-8')
    doc.update(pages=len(pages), chars=sum(len(p) for p in pages))
    return doc


def _new(kind, title, **extra):
    return dict(id=uuid.uuid4().hex[:12], kind=kind, title=title.strip()[:200] or 'Untitled document',
                added_at=time.time(), read_at=0, **extra)


def pages_of(pid, doc):
    path = _docs_dir(pid) / f"{doc['id']}.txt"
    return path.read_text(encoding='utf-8').split('\f') if path.is_file() else []


def _add(pid, doc):
    with store.lock_for(pid):
        p = _load(pid)
        p.research = dict(p.research or {})
        p.research['documents'] = documents(p) + [doc]
        store.save(p)
        return listing(p)


def listing(project):
    facts = (project.research or {}).get('facts') or []
    rows = []
    for d in documents(project):
        if isinstance(d, dict):
            rows.append(dict(d, facts=sum(1 for f in facts if isinstance(f, dict) and f.get('doc_id') == d.get('id'))))
    return dict(documents=rows)


# ------------------------------------------------------------------- reading
def _norm(text):
    return re.sub(r'\s+', ' ', text or '').strip().lower()


def read_facts(pages, title):
    """Ask the model for facts, chunk by chunk; keep quotes that are really there."""
    chunks, block, first = [], '', 1
    for n, page in enumerate(pages, 1):
        piece = f'\n[PAGE {n}]\n{page}'
        if block and len(block) + len(piece) > CHUNK_CHARS:
            chunks.append(block)
            block = ''
        block += piece
    if block:
        chunks.append(block)
    found = []
    for chunk in chunks[:MAX_CHUNKS]:
        out = llm.complete_json(f"""DOCUMENT: {title}
Pages are marked [PAGE n].
{chunk}

List the concrete, checkable facts a documentary script could use: names, dates,
numbers, places, firsts and lasts, direct quotes. One fact per item, plainly stated.
Return JSON: {{"facts": [{{"claim": "the fact", "page": n, "quote": "the exact words from the page that support it",
"date": "" or the date it concerns, "confidence": "high" | "medium" | "low"}}]}}""",
            system=SYSTEM, model=llm.MODEL_SCRIPT, timeout=300,
            require=lambda v: isinstance(v, dict) and isinstance(v.get('facts'), list),
            require_hint='The object needs a "facts" array.')
        for f in out.get('facts') or []:
            if not isinstance(f, dict) or not str(f.get('claim') or '').strip():
                continue
            try:
                page = int(f.get('page'))
            except (TypeError, ValueError):
                page = 0
            quote = str(f.get('quote') or '').strip()
            if not (1 <= page <= len(pages)) or (quote and _norm(quote) not in _norm(pages[page - 1])):
                # A page or quote the text does not contain: keep the claim, say less.
                page = page if 1 <= page <= len(pages) and not quote else 0
                quote = ''
            found.append(dict(claim=str(f['claim']).strip()[:600], page=page, quote=quote[:600],
                              date=str(f.get('date') or '')[:40],
                              confidence=f.get('confidence') if f.get('confidence') in ('high', 'medium', 'low') else 'medium'))
    return found


def apply_facts(project, doc, found):
    facts = list((project.research or {}).get('facts') or [])
    known = {_norm(f.get('claim')) for f in facts if isinstance(f, dict)}
    added = 0
    for f in found:
        if _norm(f['claim']) in known:
            continue
        known.add(_norm(f['claim']))
        facts.append(dict(f, source=doc['title'] + (f", p. {f['page']}" if f['page'] else ''),
                          url=doc.get('url', ''), doc_id=doc['id']))
        added += 1
    project.research = dict(project.research or {}, facts=facts)
    for d in documents(project):
        if d.get('id') == doc['id']:
            d['read_at'] = time.time()
    return added


def fetch_document(pid, url, title=''):
    """Save a readable copy of a web page or PDF link as a document (not yet listed)."""
    if not isinstance(url, str) or urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).netloc:
        raise HTTPException(400, 'Use an http or https link')
    try:
        r = research._client_for_web().get(url)
        r.raise_for_status()
    except Exception as exc:
        raise HTTPException(502, f'Could not fetch that page: {exc}') from exc
    ctype = r.headers.get('content-type', '')
    if 'pdf' in ctype:
        doc = _new('pdf', title or Path(urlsplit(url).path).stem or urlsplit(url).netloc, url=url)
        doc['file'] = f"docs/{doc['id']}.pdf"
        dest = store.project_dir(pid) / doc['file']
        _docs_dir(pid)
        dest.write_bytes(r.content[:MAX_BYTES])
        return _store(pid, doc, pdf_pages(dest))
    if 'html' in ctype or 'text' in ctype:
        found = re.search(r'<title[^>]*>(.*?)</title>', r.text, re.I | re.S)
        doc = _new('web', title or (re.sub(r'\s+', ' ', found.group(1)).strip() if found else urlsplit(url).netloc), url=url)
        return _store(pid, doc, _paginate(research._html_to_text(r.text) if 'html' in ctype else r.text))
    raise HTTPException(415, 'That link is not a web page or a PDF')


def read_into(pid, doc_id, progress=lambda m: None):
    """Read one listed document for facts and add them. Slow work outside the lock."""
    with store.lock_for(pid):
        doc = dict(_find(store.load(pid), doc_id))
    found = read_facts(pages_of(pid, doc), doc['title'])
    with store.lock_for(pid):
        p = store.load(pid)
        current = next((d for d in documents(p) if d.get('id') == doc_id), None)
        if current is None:
            return 0
        added = apply_facts(p, current, found)
        store.save(p)
    progress(f'{added} new fact(s) from {doc["title"]}')
    return added


# -------------------------------------------------------------------- routes
def register(app):
    base = '/api/projects/{pid}/documents'

    @app.get(base)
    def list_documents(pid: str):
        with store.lock_for(pid):
            return listing(_load(pid))

    @app.post(base)
    def upload(pid: str, files: list[UploadFile]):
        _load(pid)
        out = None
        for file in files or []:
            suffix = Path(file.filename or '').suffix.lower()
            if suffix not in {'.pdf'} | TEXT_EXT | HTML_EXT | IMAGE_EXT:
                raise HTTPException(400, 'Choose PDFs, text, web pages or scanned images')
            doc = _new('pdf' if suffix == '.pdf' else 'scan' if suffix in IMAGE_EXT else 'text',
                       re.sub(r'[_-]+', ' ', Path(file.filename).stem))
            doc['file'] = f"docs/{doc['id']}{suffix}"
            dest = store.project_dir(pid) / doc['file']
            _docs_dir(pid)
            size = 0
            with dest.open('xb') as fh:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        fh.close()
                        dest.unlink(missing_ok=True)
                        raise HTTPException(413, 'That document is over 80 MB')
                    fh.write(chunk)
            try:
                if suffix == '.pdf':
                    pages = pdf_pages(dest)
                elif suffix in IMAGE_EXT:
                    pages = image_pages(dest)
                else:
                    raw = dest.read_text(encoding='utf-8', errors='replace')
                    pages = _paginate(research._html_to_text(raw) if suffix in HTML_EXT else raw)
                _store(pid, doc, pages)
            except HTTPException:
                dest.unlink(missing_ok=True)
                raise
            out = _add(pid, doc)
        if out is None:
            raise HTTPException(400, 'Choose a document')
        return out

    @app.post(base + '/text')
    def paste(pid: str, payload: dict = Body(...)):
        text, title = payload.get('text'), payload.get('title') or ''
        if not isinstance(text, str) or not text.strip() or not isinstance(title, str):
            raise HTTPException(400, 'Paste some text')
        _load(pid)
        doc = _new('text', title or text.strip().split('\n')[0][:80])
        _store(pid, doc, _paginate(text[:2_000_000]))
        return _add(pid, doc)

    @app.post(base + '/link')
    def link(pid: str, payload: dict = Body(...)):
        url = payload.get('url')
        _load(pid)
        return _add(pid, fetch_document(pid, url))

    @app.get(base + '/{ident}')
    def show(pid: str, ident: str):
        with store.lock_for(pid):
            p = _load(pid)
            doc = _find(p, ident)
            facts = [dict(f, index=i) for i, f in enumerate((p.research or {}).get('facts') or [])
                     if isinstance(f, dict) and f.get('doc_id') == ident]
        return dict(document=doc, pages=pages_of(pid, doc), facts=facts)

    @app.get(base + '/{ident}/file')
    def original(pid: str, ident: str):
        doc = _find(_load(pid), ident)
        path = (store.project_dir(pid) / doc.get('file', '')).resolve() if doc.get('file') else None
        if not path or not path.is_relative_to(_docs_dir(pid).resolve()) or not path.is_file():
            raise HTTPException(404, 'This document has no original file')
        return FileResponse(path)

    @app.patch(base + '/{ident}')
    def rename(pid: str, ident: str, payload: dict = Body(...)):
        title = payload.get('title')
        if not isinstance(title, str) or not title.strip():
            raise HTTPException(400, 'Give the document a title')
        with store.lock_for(pid):
            p = _load(pid)
            _find(p, ident)['title'] = title.strip()[:200]
            store.save(p)
            return listing(p)

    @app.delete(base + '/{ident}')
    def remove(pid: str, ident: str):
        with store.lock_for(pid):
            p = _load(pid)
            doc = _find(p, ident)
            removed = _docs_dir(pid) / '.removed'
            removed.mkdir(exist_ok=True)
            for rel in filter(None, [doc.get('file'), f"docs/{ident}.txt"]):
                path = store.project_dir(pid) / rel
                if path.is_file():
                    path.rename(removed / path.name)
            p.research = dict(p.research or {}, documents=[d for d in documents(p) if d is not doc])
            store.save(p)  # facts drawn from it stay: they are research now
            return listing(p)

    @app.post(base + '/{ident}/read')
    def read(pid: str, ident: str):
        with store.lock_for(pid):
            doc = dict(_find(_load(pid), ident))

        def work(progress):
            progress(f'Reading {doc["title"]}…')
            return {'added': read_into(pid, ident, progress)}
        return {'job': jobs.start('read-document', pid, work)}

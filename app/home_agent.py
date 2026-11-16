"""Home's agent: research and planning beside the materials and documents.

It answers from the project's facts, documents, materials and script, and may
propose three actions the writer applies: a note for Materials, an open
question, or a web search. Applying a search is a job that saves the top pages
as research documents and reads them for facts (app/research_docs.py), so every
fact it brings keeps its page and quote. The agent itself never writes.
"""
import uuid

from fastapi import Body, HTTPException

from . import jobs, llm, research, research_docs, store
from .schema import BinItem
from .script_agent import _history_text, _load, shots

MAX_MESSAGE = 4000
MAX_FACTS = 80
MAX_ACTIONS = 5
PAGES_PER_SEARCH = 3

SYSTEM = (
    "You are a researcher and producer working with the writer of a narrated "
    "documentary video, on the project's home page. Answer briefly and concretely "
    "from the FACTS and DOCUMENTS you are given; say so when they do not cover "
    "something. Never invent facts or sources. You may propose actions: a note to "
    "keep, an open question to track, or a web search worth running. Reply with JSON only."
)


def build_prompt(project, message, history=None):
    r = project.research or {}
    facts = [f for f in (r.get('facts') or []) if isinstance(f, dict) and f.get('claim')][:MAX_FACTS]
    fact_lines = '\n'.join(f"F{i}. {f['claim']}" + (f" ({f.get('source')})" if f.get('source') else '')
                           for i, f in enumerate(facts, 1)) or '(none yet)'
    docs = '\n'.join(f"- {d.get('title')} ({d.get('kind')}, {d.get('pages', 0)} pages)"
                     for d in research_docs.documents(project) if isinstance(d, dict)) or '(none)'
    questions = '\n'.join(f'- {q if isinstance(q, str) else q.get("question", "")}'
                          for q in (r.get('open_questions') or [])) or '(none)'
    materials = '\n'.join(f'- {b.kind}: {b.title}' + (f' (shows {b.shows})' if b.shows else '')
                          for b in project.bin[:40]) or '(none)'
    outline = project.outline or {}
    shot_lines = '\n'.join(f'{n}. {run[0].visual_note or (run[0].narration or "")[:80]}'
                           for n, run in enumerate(shots(project), 1) if run and not run[0].insert)
    past = _history_text(history)
    return f"""VIDEO: {project.title or outline.get('title', '')}
IDEA: {project.idea}
THESIS: {outline.get('thesis', '')}
TARGET LENGTH: {project.target_minutes} minutes

SHOTS SO FAR:
{shot_lines or '(no script yet)'}

FACTS:
{fact_lines}

DOCUMENTS:
{docs}

OPEN QUESTIONS:
{questions}

MATERIALS:
{materials}

{('CONVERSATION SO FAR:' + chr(10) + past + chr(10)) if past else ''}WRITER: {message}

Return JSON:
{{"reply": "your answer, under 150 words, citing F-numbers where you use facts",
  "actions": [{{"type": "note" | "question" | "search", "text": "the note, question or search query", "why": "one short reason"}}]}}
Propose at most {MAX_ACTIONS} actions, only when they help. Searches are plain web queries."""


def _shape(out):
    return isinstance(out, dict) and isinstance(out.get('reply', ''), str)


def ask(project, message, history=None):
    out = llm.complete_json(build_prompt(project, message, history), system=SYSTEM,
                            model=llm.MODEL_SCRIPT, timeout=300, require=_shape,
                            require_hint='an object with reply and actions')
    actions, seen = [], set()
    for a in out.get('actions') or []:
        if not isinstance(a, dict):
            continue
        kind, text = str(a.get('type') or '').lower(), str(a.get('text') or '').strip()
        if kind in ('note', 'question', 'search') and text and (kind, text.lower()) not in seen:
            seen.add((kind, text.lower()))
            actions.append(dict(type=kind, text=text[:1000], why=str(a.get('why') or '')[:300]))
    return dict(reply=str(out.get('reply') or '').strip() or 'Done.', actions=actions[:MAX_ACTIONS],
                can_search=research.available())


def search_into_documents(pid, query, progress=lambda m: None):
    """Search, save the top pages as documents, read each for facts."""
    progress(f'Searching: {query}')
    hits = [h for h in research.search(query, PAGES_PER_SEARCH + 3) if h.get('url')][:PAGES_PER_SEARCH]
    saved = added = 0
    for hit in hits:
        try:
            doc = research_docs.fetch_document(pid, hit['url'], hit.get('title') or '')
        except HTTPException as exc:
            progress(f'Skipped {hit["url"]}: {exc.detail}')
            continue
        doc['found_by'] = query
        with store.lock_for(pid):
            p = store.load(pid)
            p.research = dict(p.research or {}, documents=research_docs.documents(p) + [doc])
            store.save(p)
        saved += 1
        added += research_docs.read_into(pid, doc['id'], progress)
    return {'documents': saved, 'added': added}


def register(app):
    @app.post('/api/projects/{pid}/home/agent')
    def home_agent(pid: str, payload: dict = Body(...)):
        message = str(payload.get('message') or '').strip()
        if not message:
            raise HTTPException(400, 'Write a message for the agent')
        if len(message) > MAX_MESSAGE:
            raise HTTPException(400, 'Message is too long')
        with store.lock_for(pid):
            project = _load(pid)
        try:
            return ask(project, message, payload.get('history'))
        except llm.LLMError as exc:
            raise HTTPException(502, f'The agent could not answer: {exc}') from exc

    @app.post('/api/projects/{pid}/home/apply')
    def home_apply(pid: str, payload: dict = Body(...)):
        kind, text = payload.get('type'), str(payload.get('text') or '').strip()
        if kind not in ('note', 'question', 'search') or not text or len(text) > 1000:
            raise HTTPException(400, 'Choose a note, question or search')
        if kind == 'search':
            if not research.available():
                raise HTTPException(409, 'No web search is set up. Add one in Settings.')
            _load(pid)
            return {'job': jobs.start('research', pid, lambda progress: search_into_documents(pid, text, progress))}
        with store.lock_for(pid):
            p = _load(pid)
            if kind == 'note':
                p.bin.append(BinItem(id=uuid.uuid4().hex, kind='note', title=text.split('\n')[0][:100], note=text,
                                     source='dropped'))
            else:
                questions = list((p.research or {}).get('open_questions') or [])
                if text not in questions:
                    questions.append(text)
                p.research = dict(p.research or {}, open_questions=questions)
            store.save(p)
            return p.to_dict()

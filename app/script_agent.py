"""The Script page's agent: talk about the script, get proposed edits back.

The agent only proposes. Edits come back as before/after pairs that the page
applies through the ordinary slide PATCH, so they are undoable like typing and
never touch recorded takes (an edited paragraph's take is simply out of date).
"""
import re

from fastapi import Body, HTTPException

from . import llm, store

MAX_MESSAGE = 4000
MAX_HISTORY = 8
MAX_FACTS = 80

SYSTEM = (
    "You are a script editor working beside the writer of a narrated documentary "
    "video. You answer briefly and concretely. You may propose edits to narration "
    "paragraphs, but only as full replacement text for a paragraph id you were "
    "given. Never invent facts: a claim is supported only if the FACTS list says "
    "it. When narration states something the facts do not support, flag it. "
    "Reply with JSON only."
)


def _load(pid):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', pid):
        raise HTTPException(400, 'Invalid project id')
    try:
        return store.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Project not found') from exc


def shots(project):
    """Paragraphs grouped as the Script page shows them (scriptRuns).

    A shot is the paragraphs sharing one shot description; "new" picture mode,
    chapters and inserts always break. An undescribed paragraph stays with the
    picture it continues.
    """
    leads = {run[0] for run in project.picture_runs() if run}
    runs, prev = [], None
    for s in project.slides:
        note = (s.visual_note or '').strip()
        if (prev is None or s.insert or prev.insert or (s.chapter or '').strip()
                or s.picture_mode == 'new'
                or (note != (prev.visual_note or '').strip() if note else s.id in leads)):
            runs.append([])
        runs[-1].append(s)
        prev = s
    return runs


def _script_text(project, focus_ids):
    lines, n = [], 0
    for number, run in enumerate(shots(project), 1):
        lead = run[0]
        if lead.chapter:
            lines.append(f'\n## Chapter: {lead.chapter}')
        mark = '  <- the writer is looking at this shot' if lead.id in focus_ids else ''
        lines.append(f'### Shot {number}{mark}')
        if lead.visual_note:
            lines.append(f'(picture: {lead.visual_note})')
        for s in run:
            if s.insert:
                lines.append(f'[insert {s.insert.get("kind", "")}, not spoken]')
                continue
            n += 1
            lines.append(f'[{s.id}] ¶{n}: {s.narration}')
    return '\n'.join(lines)


def _facts_text(project):
    facts = (project.research or {}).get('facts') or []
    rows = []
    for i, f in enumerate(facts[:MAX_FACTS], 1):
        if not isinstance(f, dict) or not f.get('claim'):
            continue
        meta = ', '.join(x for x in (f.get('date'), f.get('source'), f.get('confidence')) if x)
        rows.append(f'F{i}. {f["claim"]}' + (f' ({meta})' if meta else ''))
    return '\n'.join(rows) or '(no researched facts)'


def _history_text(history):
    rows = []
    for turn in (history or [])[-MAX_HISTORY:]:
        if not isinstance(turn, dict):
            continue
        who = 'Writer' if turn.get('role') == 'user' else 'You'
        text = str(turn.get('text') or '')[:1500].strip()
        if text:
            rows.append(f'{who}: {text}')
    return '\n'.join(rows)


def build_prompt(project, message, shot_id='', history=None):
    focus = next((run for run in shots(project) if shot_id and any(s.id == shot_id for s in run)), [])
    focus_ids = {s.id for s in focus}
    outline = project.outline or {}
    past = _history_text(history)
    return f"""VIDEO: {project.title or outline.get('title', '')}
THESIS: {outline.get('thesis', '') or project.idea}
TARGET LENGTH: {project.target_minutes} minutes

SCRIPT (paragraph ids in brackets):
{_script_text(project, focus_ids)}

FACTS (the only supported claims):
{_facts_text(project)}

{('CONVERSATION SO FAR:' + chr(10) + past + chr(10)) if past else ''}
WRITER: {message}

Return JSON:
{{"reply": "your answer to the writer, under 120 words",
  "edits": [{{"id": "a paragraph id from the script", "text": "the whole new paragraph", "why": "one short reason"}}],
  "flags": [{{"id": "a paragraph id", "quote": "the exact words at issue", "problem": "what is unsupported or wrong, citing F-numbers"}}]}}
Propose at most 4 edits, only when the writer asks for changes or one is clearly needed.
Keep each edited paragraph speakable and in the same voice. Use [] when there is nothing."""


def _shape(out):
    return isinstance(out, dict) and isinstance(out.get('reply', ''), str)


def ask(project, message, shot_id='', history=None):
    out = llm.complete_json(build_prompt(project, message, shot_id, history), system=SYSTEM,
                            model=llm.MODEL_SCRIPT, timeout=300, require=_shape,
                            require_hint='an object with reply, edits and flags')
    spoken = {s.id: s for s in project.slides if not s.insert}
    number = {s.id: i for i, s in enumerate(spoken.values(), 1)}
    edits, seen = [], set()
    for e in out.get('edits') or []:
        if not isinstance(e, dict):
            continue
        sid, text = str(e.get('id') or ''), str(e.get('text') or '').strip()
        if sid in spoken and text and text != spoken[sid].narration.strip() and sid not in seen:
            seen.add(sid)
            edits.append(dict(id=sid, paragraph=number[sid], before=spoken[sid].narration,
                              after=text, why=str(e.get('why') or '')[:300]))
    flags = []
    for f in out.get('flags') or []:
        if isinstance(f, dict) and str(f.get('id') or '') in spoken and f.get('problem'):
            sid = str(f['id'])
            flags.append(dict(id=sid, paragraph=number[sid], quote=str(f.get('quote') or '')[:400],
                              problem=str(f['problem'])[:600]))
    return dict(reply=str(out.get('reply') or '').strip() or 'Done.', edits=edits[:4], flags=flags[:6])


def register(app):
    @app.post('/api/projects/{pid}/script/agent')
    def script_agent(pid: str, payload: dict = Body(...)):
        message = str(payload.get('message') or '').strip()
        if not message:
            raise HTTPException(400, 'Write a message for the agent')
        if len(message) > MAX_MESSAGE:
            raise HTTPException(400, 'Message is too long')
        # A snapshot is enough: the agent only proposes, and each edit is
        # applied later through the normal PATCH against the current text.
        with store.lock_for(pid):
            project = _load(pid)
        if not any(not s.insert for s in project.slides):
            raise HTTPException(400, 'Write or generate a script first')
        try:
            return ask(project, message, str(payload.get('shot') or ''), payload.get('history'))
        except llm.LLMError as exc:
            raise HTTPException(502, f'The agent could not answer: {exc}') from exc

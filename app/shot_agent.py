"""The Shots view's agent: help describe and design one shot's visuals.

It only proposes: a shot description and a plan of visuals against the
paragraphs (which paragraph each visual starts on, what kind it is, what to
search for). The page applies a plan through ordinary slide PATCHes, so it is
undoable like any edit and never touches recorded takes or media files.
"""
from fastapi import Body, HTTPException

from . import llm, store
from .script_agent import _history_text, _load, shots

MAX_MESSAGE = 4000
MAX_VISUALS = 4
KINDS = ('photo', 'clip', 'map', '3d', 'diagram', 'scene')

SYSTEM = (
    "You are a picture editor for a narrated documentary video, working with the "
    "writer on one shot at a time. A shot is a run of narration paragraphs under one "
    "description; it can hold several visuals, each starting on a paragraph. You pick "
    "what the viewer sees: an archive photo, a film clip, a map, a 3D model, an "
    "animated diagram, or a designed scene (title card, chart, number). Prefer the "
    "visual that shows what the words claim: a size or number suits a diagram or "
    "scene, a place suits a map, a thing suits a photo or 3D model. Never invent facts. "
    "Reply with JSON only."
)


def _shot(project, lead):
    run = next((run for run in shots(project) if run and run[0].id == lead), None)
    if run is None or run[0].insert:
        raise HTTPException(404, 'That shot is no longer in the script')
    return run


def _visual_kind(slide):
    if slide.kind == 'stage':
        return '3d'
    chosen = next((c for c in slide.candidates if c.get('id') == slide.chosen_id), {})
    provider = chosen.get('provider')
    if (slide.cues or {}).get('blocks') or provider == 'custom':
        return 'scene'
    if provider == 'diagram':
        return 'diagram'
    if provider == 'maps' or slide.prefer_kind == 'map':
        return 'map'
    return 'clip' if chosen.get('kind') == 'video' or slide.prefer_kind == 'video' else 'photo'


def build_prompt(project, run, message, history=None):
    leads = {r[0] for r in project.picture_runs() if r}
    spoken = [s for s in run if not s.insert]
    lines = []
    for s in spoken:
        visual = f'  <- visual starts here: {_visual_kind(s)}' if s.id in leads else ''
        lines.append(f'[{s.id}] {s.narration}{visual}')
    cast = ', '.join(str(c.get('subject') or '') for c in project.cast if isinstance(c, dict)) or 'none'
    materials = '; '.join(f'{b.kind}: {b.title}' for b in project.bin[:30] if b.title) or 'none'
    past = _history_text(history)
    return f"""VIDEO: {project.title or (project.outline or {}).get('title', '') or project.idea}
SHOT DESCRIPTION: {run[0].visual_note or '(none yet)'}

PARAGRAPHS IN THIS SHOT (ids in brackets, current visuals marked):
{chr(10).join(lines)}

3D MODELS AVAILABLE: {cast}
WRITER'S MATERIALS: {materials}

{('CONVERSATION SO FAR:' + chr(10) + past + chr(10)) if past else ''}WRITER: {message}

Return JSON:
{{"reply": "your answer, under 100 words",
  "description": "a better shot description (what we see and feel), or empty to keep it",
  "visuals": [{{"from": "the paragraph id this visual starts on", "kind": "one of {', '.join(KINDS)}",
               "query": "what to search for or draw", "why": "one short reason"}}]}}
Give visuals only when the writer asks for ideas or a plan; at most {MAX_VISUALS}; the first starts on {spoken[0].id}."""


def _shape(out):
    return isinstance(out, dict) and isinstance(out.get('reply', ''), str)


def ask(project, lead, message, history=None):
    run = _shot(project, lead)
    spoken = [s for s in run if not s.insert]
    out = llm.complete_json(build_prompt(project, run, message, history), system=SYSTEM,
                            model=llm.MODEL_SCRIPT, timeout=300, require=_shape,
                            require_hint='an object with reply, description and visuals')
    order = {s.id: i for i, s in enumerate(spoken)}
    visuals, seen = [], set()
    for v in out.get('visuals') or []:
        if not isinstance(v, dict):
            continue
        sid, kind = str(v.get('from') or ''), str(v.get('kind') or '').lower()
        if sid in order and kind in KINDS and sid not in seen:
            seen.add(sid)
            visuals.append(dict(start=sid, paragraph=order[sid] + 1, kind=kind,
                                query=str(v.get('query') or '')[:200], why=str(v.get('why') or '')[:300]))
    visuals.sort(key=lambda v: order[v['start']])
    visuals = visuals[:MAX_VISUALS]
    if visuals and visuals[0]['start'] != spoken[0].id:
        # A shot's first paragraph always has a visual: the plan starts there.
        visuals[0] = {**visuals[0], 'start': spoken[0].id, 'paragraph': 1}
    description = str(out.get('description') or '').strip()[:600]
    return dict(reply=str(out.get('reply') or '').strip() or 'Done.',
                description='' if description == (run[0].visual_note or '').strip() else description,
                visuals=visuals)


def register(app):
    @app.post('/api/projects/{pid}/script/shot-agent')
    def shot_agent(pid: str, payload: dict = Body(...)):
        message = str(payload.get('message') or '').strip()
        lead = str(payload.get('shot') or '')
        if not message:
            raise HTTPException(400, 'Write a message for the agent')
        if len(message) > MAX_MESSAGE:
            raise HTTPException(400, 'Message is too long')
        with store.lock_for(pid):
            project = _load(pid)
        try:
            return ask(project, lead, message, payload.get('history'))
        except llm.LLMError as exc:
            raise HTTPException(502, f'The agent could not answer: {exc}') from exc

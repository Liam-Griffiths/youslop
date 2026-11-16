"""The Edit view's agent: find a place in the video and propose edits there.

It only proposes. A reply can point at one paragraph (the page moves the
playhead) and carry cards: an overlay graphic, an on-screen title, a chapter
card, or the removal of a graphic. The page applies a card through the
ordinary slide PATCH, so it is undoable like any edit and never touches
recorded takes or media files.
"""
import math

from fastapi import Body, HTTPException

from . import block_overlays, blocks, llm, store
from .script_agent import _history_text, _load

MAX_MESSAGE = 4000
MAX_ACTIONS = 6
MAX_BLOCKS = 40

SYSTEM = (
    "You are an assistant editor for a narrated video, working beside the person "
    "editing it on a timeline. You help them find a place in the video and you "
    "propose small edits there: an overlay graphic (a lower third, caption or "
    "label drawn over the picture), a short on-screen title, or a chapter card. "
    "You only propose; the editor applies what they like. Use only the paragraph "
    "ids and graphic blocks you were given. Text you put on screen must come from "
    "the narration or the editor's request: never invent names, dates or numbers. "
    "Reply with JSON only."
)


def _aspect(project):
    return {'portrait': '9:16', 'square': '1:1'}.get(project.aspect, '16:9')


def catalogue(project):
    """Overlay blocks that fit this video's shape, as the prompt and the checks need them."""
    aspect, found = _aspect(project), {}
    for ref, block in blocks.discover().items():
        meta = block['meta']
        # Sample tables and pictures would reach the screen as if they were the
        # editor's own; offer only blocks the agent can fill completely with words.
        plain = all(spec.get('type') == 'text' or (spec.get('type') == 'image' and not spec.get('default'))
                    for spec in meta['variables'].values())
        if meta.get('overlay') and aspect in meta.get('aspects', {}) and plain:
            found[ref] = meta
    return dict(list(found.items())[:MAX_BLOCKS])


def _block_line(ref, meta):
    fields = ', '.join(f"{key} ({spec.get('max_length', 80)} chars)" for key, spec in meta['variables'].items()
                       if spec.get('type') == 'text')
    spec = meta['overlay']
    return (f"- {ref}: {meta.get('name', ref)}. {meta.get('description', '')} Text fields: {fields or 'none'}. "
            f"Positions: {', '.join(spec['position'])}. At most {spec['max_dur']:g} s.")


def _clock(seconds):
    return f'{int(seconds // 60)}:{int(seconds % 60):02d}'


def _starts(project, starts):
    """Paragraph start times as the page's timeline has them; unknown ones are left out."""
    ids, clean = {s.id for s in project.slides}, {}
    for sid, value in (starts.items() if isinstance(starts, dict) else []):
        if sid in ids and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            clean[sid] = max(0.0, float(value))
    return clean


def build_prompt(project, library, message, history=None, focus='', starts=None):
    starts, lines, number = starts or {}, [], 0
    for s in project.slides:
        if s.insert:
            continue
        number += 1
        marks = [f'chapter card "{s.chapter}"' if s.chapter else '', f'title "{s.title}"' if s.title else '']
        marks += [f"graphic {o['id']} ({o.get('block_id', 'media')}: "
                  f"{'; '.join(str(v) for v in (o.get('vars') or {}).values() if isinstance(v, str) and v)[:80]})"
                  for o in s.overlays if o.get('type') != 'media']
        marks = ' | '.join(m for m in marks if m)
        when = f' {_clock(starts[s.id])}' if s.id in starts else ''
        here = '  <- PLAYHEAD' if s.id == focus else ''
        camera = ' (on camera: no graphics)' if s.on_camera else ''
        lines.append(f'[{s.id}] ¶{number}{when}{camera}{here} {s.narration}' + (f'\n      has: {marks}' if marks else ''))
    past = _history_text(history)
    return f"""VIDEO: {project.title or (project.outline or {}).get('title', '') or project.idea}

PARAGRAPHS IN ORDER (id in brackets, then number and start time):
{chr(10).join(lines)}

OVERLAY GRAPHIC BLOCKS YOU MAY USE:
{chr(10).join(_block_line(ref, meta) for ref, meta in library.items()) or '(none)'}

{('CONVERSATION SO FAR:' + chr(10) + past + chr(10)) if past else ''}EDITOR: {message}

Return JSON:
{{"reply": "your answer, under 80 words",
  "goto": "the paragraph id to move the playhead to, or empty",
  "actions": [
    {{"type": "graphic", "paragraph": "id", "block": "a block ref from the list",
      "text": {{"field name": "words for that field"}}, "position": "one of the block's positions",
      "on": "the exact words in that paragraph's narration where it should appear, or empty for the start",
      "seconds": 4, "why": "one short reason"}},
    {{"type": "title", "paragraph": "id", "text": "up to 40 characters", "why": "..."}},
    {{"type": "chapter", "paragraph": "id", "text": "up to 60 characters", "why": "..."}},
    {{"type": "remove", "paragraph": "id", "graphic": "an existing graphic id", "why": "..."}}]}}
Give actions only when the editor asks for a change or for suggestions; at most {MAX_ACTIONS}.
"Here" and "this" mean the PLAYHEAD paragraph. When the editor asks where something is, set goto and say which paragraph."""


def _shape(out):
    return isinstance(out, dict) and isinstance(out.get('reply', ''), str)


def _graphic(slide, action, library):
    ref = str(action.get('block') or '')
    meta = library.get(ref)
    if not meta or slide.on_camera:
        return None
    spec = meta['overlay']
    text = action.get('text') if isinstance(action.get('text'), dict) else {}
    # A field the agent left out stays empty: a block's sample words never go on screen.
    values = {key: str(text.get(key) or '').strip()[:var.get('max_length', 200)] if isinstance(text.get(key), str) else ''
              for key, var in meta['variables'].items() if var.get('type') == 'text'}
    if not any(values.values()):
        return None
    position = action.get('position') if action.get('position') in spec['position'] else spec['position'][0]
    seconds = action.get('seconds')
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        seconds = 4
    item = dict(id='check', block_id=ref, vars=values, at=0.0, dur=float(min(seconds, spec['max_dur'])),
                position=position, by='hand')
    on = str(action.get('on') or '').strip()
    if on and on.lower() in slide.narration.lower():
        item['on'] = on[:120]
    try:
        clean = block_overlays.validate(slide.take, [item])[0]
    except ValueError:
        return None
    return dict(type='graphic', block=ref, block_name=meta.get('name', ref), vars=clean['vars'],
                dur=clean['dur'], position=clean['position'], on=clean.get('on', ''))


def ask(project, message, history=None, focus='', starts=None):
    library = catalogue(project)
    spoken = [s for s in project.slides if not s.insert]
    by_id = {s.id: (i + 1, s) for i, s in enumerate(spoken)}
    focus = focus if focus in by_id else ''
    out = llm.complete_json(build_prompt(project, library, message, history, focus, _starts(project, starts)),
                            system=SYSTEM, model=llm.MODEL_SCRIPT, timeout=300, require=_shape,
                            require_hint='an object with reply, goto and actions')
    actions = []
    for raw in out.get('actions') or []:
        if not isinstance(raw, dict) or str(raw.get('paragraph') or '') not in by_id:
            continue
        number, slide = by_id[str(raw['paragraph'])]
        kind, text = str(raw.get('type') or ''), str(raw.get('text') or '').strip() if isinstance(raw.get('text'), str) else ''
        if kind == 'graphic':
            card = _graphic(slide, raw, library)
        elif kind == 'title' and text and text[:40] != slide.title:
            card = dict(type='title', text=text[:40], was=slide.title)
        elif kind == 'chapter' and text and text[:60] != slide.chapter:
            card = dict(type='chapter', text=text[:60], was=slide.chapter)
        elif kind == 'remove':
            found = next((o for o in slide.overlays if o['id'] == raw.get('graphic') and o.get('type') != 'media'), None)
            card = found and dict(type='remove', graphic=found['id'], block_name=library.get(
                found.get('block_id'), {}).get('name', found.get('block_id', 'graphic')))
        else:
            card = None
        if card:
            actions.append(dict(card, sid=slide.id, paragraph=number, why=str(raw.get('why') or '')[:300]))
    goto = str(out.get('goto') or '')
    if goto not in by_id:
        goto = actions[0]['sid'] if actions else ''
    return dict(reply=str(out.get('reply') or '').strip() or 'Done.', goto=goto,
                goto_paragraph=by_id[goto][0] if goto else 0, actions=actions[:MAX_ACTIONS])


def register(app):
    @app.post('/api/projects/{pid}/edit/agent')
    def edit_agent(pid: str, payload: dict = Body(...)):
        message = str(payload.get('message') or '').strip()
        if not message:
            raise HTTPException(400, 'Write a message for the agent')
        if len(message) > MAX_MESSAGE:
            raise HTTPException(400, 'Message is too long')
        with store.lock_for(pid):
            project = _load(pid)
        try:
            return ask(project, message, payload.get('history'), str(payload.get('focus') or ''), payload.get('starts'))
        except llm.LLMError as exc:
            raise HTTPException(502, f'The agent could not answer: {exc}') from exc

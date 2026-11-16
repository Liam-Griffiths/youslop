"""Create: custom HTML graphics made with an agent, then placed in shots.

A graphic is a constrained HTML fragment (app/sanitise.py: a small set of tags
and classes, per-element timing and motions, no CSS or scripts) with a brief,
a length and numbered versions. Each agent revision is a new version, so going
back is choosing an earlier one. Previews are single Chromium captures at a
few moments, at quarter size. Placing a graphic renders it through the same
path as a custom HTML slide (custom_scenes.html_candidate) and chooses it on
the shot's paragraph. Graphics live in project.graphics.
"""
import threading
import time
import uuid

from fastapi import Body, HTTPException
from fastapi.responses import Response

from . import custom_scenes, jobs, llm, sanitise, scenes, store
from .script_agent import _history_text, _load, shots

MAX_MESSAGE = 4000
MAX_VERSIONS = 30
MIN_SECONDS, MAX_SECONDS = 2.0, 20.0
# The page asks for several moments at once; Chromium captures race when run
# side by side (a page seeked before it loaded). One at a time; each is cached.
_CAPTURE = threading.Lock()

SYSTEM = (
    "You design animated on-screen graphics for a narrated documentary video: title "
    "cards, big numbers, comparisons, lists, timelines and quotes. You write a small "
    "HTML fragment in a fixed vocabulary; the channel's fonts and colours are applied "
    "for you. Use only facts you are given. Reply with JSON only."
)

VOCABULARY = f"""HTML VOCABULARY (anything else is rejected):
Tags: {' '.join(sorted(sanitise.TAGS - {'img'}))}.
Classes: cb-slide (the outer section, required), cb-row (columns), cb-stack (rows),
cb-card (a padded bordered panel), cb-title and cb-number (large display type),
cb-label (small mono caption), cb-accent (channel accent colour), cb-muted, cb-center.
Attributes: class; data-start="seconds" (when the element appears);
data-motion one of {', '.join(sorted(sanitise.MOTIONS))}; data-duration="seconds";
data-text (inert note). An element with data-motion or data-duration also needs
data-layer="a-unique-lowercase-id", and layered elements must not sit inside
another layered element. No style, CSS, scripts, links, images or other attributes.
Example: <section class="cb-slide cb-center"><p class="cb-label" data-layer="when" data-start="0" data-motion="fade">By 1934</p>
<h1 class="cb-number cb-accent" data-layer="number" data-start="0.8" data-motion="pop">427 km</h1>
<p class="cb-muted" data-layer="what" data-start="2" data-motion="rise">of tube under Paris</p></section>"""


def graphics_of(project):
    return [g for g in (project.graphics or []) if isinstance(g, dict)]


def _find(project, ident):
    g = next((g for g in graphics_of(project) if g.get('id') == ident), None)
    if g is None:
        raise HTTPException(404, 'Graphic not found')
    return g


def current_html(g):
    versions = g.get('versions') or []
    i = g.get('current', len(versions) - 1)
    return versions[i]['html'] if versions and 0 <= i < len(versions) else ''


def _clean(html):
    try:
        return sanitise.clean(html, [])
    except sanitise.UnsafeHTML as exc:
        raise ValueError(str(exc)) from exc


def build_prompt(project, g, message, history=None):
    r = project.research or {}
    facts = '\n'.join(f"F{i}. {f['claim']}" for i, f in enumerate(
        [f for f in (r.get('facts') or []) if isinstance(f, dict) and f.get('claim')][:60], 1)) or '(none)'
    placed = {sid for sid in g.get('used_in') or []}
    words = ' '.join(s.narration for run in shots(project) for s in run if s.id in placed and not s.insert)
    past = _history_text(history)
    return f"""VIDEO: {project.title or project.idea}
GRAPHIC: {g.get('title')}
BRIEF: {g.get('brief') or '(none)'}
LENGTH: {g.get('seconds', 6)} seconds
{f'NARRATION IT PLAYS UNDER: {words}' if words else ''}
CURRENT VERSION:
{current_html(g) or '(nothing yet)'}

FACTS:
{facts}

{VOCABULARY}

{('CONVERSATION SO FAR:' + chr(10) + past + chr(10)) if past else ''}WRITER: {message}

Return JSON: {{"reply": "what you made or changed, under 60 words",
"html": "the whole new fragment, or empty if you only answered a question",
"title": "a short name for the graphic, or empty to keep it"}}
Time the reveals within {g.get('seconds', 6)} seconds. Keep words few and large."""


def ask(project, g, message, history=None):
    out = llm.complete_json(build_prompt(project, g, message, history), system=SYSTEM,
                            model=llm.MODEL_SCRIPT, timeout=300,
                            require=lambda v: isinstance(v, dict) and isinstance(v.get('reply', ''), str),
                            require_hint='an object with reply, html and title')
    html = str(out.get('html') or '').strip()
    if html:
        try:
            html = _clean(html)
        except ValueError:
            # One retry with the error: the vocabulary is strict on purpose.
            retry = llm.complete_json(build_prompt(project, g, message, history)
                                      + '\n\nYour last fragment was rejected. Use only the vocabulary above.',
                                      system=SYSTEM, model=llm.MODEL_SCRIPT, timeout=300,
                                      require=lambda v: isinstance(v, dict), require_hint='an object')
            html = _clean(str(retry.get('html') or ''))
    return dict(reply=str(out.get('reply') or '').strip() or 'Done.', html=html,
                title=str(out.get('title') or '').strip()[:80])


def _context(pid, project, html, seconds):
    return custom_scenes.html_context(store.project_dir(pid) / 'media', html, {}, seconds, project)


def register(app):
    base = '/api/projects/{pid}/graphics'

    @app.get(base)
    def list_graphics(pid: str):
        with store.lock_for(pid):
            return {'graphics': graphics_of(_load(pid))}

    @app.post(base)
    def create(pid: str, payload: dict = Body(...)):
        title, brief = str(payload.get('title') or '').strip(), str(payload.get('brief') or '').strip()
        if not title and not brief:
            raise HTTPException(400, 'Name the graphic or describe it')
        g = dict(id='g' + uuid.uuid4().hex[:10], title=(title or brief.split('.')[0])[:80], brief=brief[:2000],
                 seconds=6.0, versions=[], current=-1, used_in=[], created_at=time.time())
        with store.lock_for(pid):
            p = _load(pid)
            p.graphics = graphics_of(p) + [g]
            store.save(p)
            return {'graphics': graphics_of(p), 'graphic': g}

    @app.patch(base + '/{ident}')
    def edit(pid: str, ident: str, payload: dict = Body(...)):
        with store.lock_for(pid):
            p = _load(pid)
            g = _find(p, ident)
            if 'title' in payload:
                if not isinstance(payload['title'], str) or not payload['title'].strip():
                    raise HTTPException(400, 'Give the graphic a name')
                g['title'] = payload['title'].strip()[:80]
            if 'brief' in payload:
                g['brief'] = str(payload['brief'] or '')[:2000]
            if 'seconds' in payload:
                try:
                    g['seconds'] = max(MIN_SECONDS, min(MAX_SECONDS, float(payload['seconds'])))
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, 'Length must be seconds') from exc
            if 'current' in payload:
                if not isinstance(payload['current'], int) or not 0 <= payload['current'] < len(g.get('versions') or []):
                    raise HTTPException(400, 'No such version')
                g['current'] = payload['current']
            if 'html' in payload:  # a hand edit becomes a version like any other
                try:
                    html = _clean(str(payload['html']))
                except ValueError as exc:
                    raise HTTPException(400, f'That HTML is not allowed: {exc}') from exc
                g['versions'] = (g.get('versions') or []) + [dict(html=html, note='Edited by hand', at=time.time())]
                g['versions'] = g['versions'][-MAX_VERSIONS:]
                g['current'] = len(g['versions']) - 1
            store.save(p)
            return {'graphics': graphics_of(p), 'graphic': g}

    @app.delete(base + '/{ident}')
    def remove(pid: str, ident: str):
        with store.lock_for(pid):
            p = _load(pid)
            g = _find(p, ident)
            p.graphics = [x for x in graphics_of(p) if x is not g]  # placed renders stay on their shots
            store.save(p)
            return {'graphics': graphics_of(p)}

    @app.post(base + '/{ident}/agent')
    def agent(pid: str, ident: str, payload: dict = Body(...)):
        message = str(payload.get('message') or '').strip()
        if not message or len(message) > MAX_MESSAGE:
            raise HTTPException(400, 'Write a message for the agent')
        with store.lock_for(pid):
            p = _load(pid)
            g = dict(_find(p, ident))
        try:
            out = ask(p, g, message, payload.get('history'))
        except llm.LLMError as exc:
            raise HTTPException(502, f'The agent could not answer: {exc}') from exc
        except ValueError as exc:
            raise HTTPException(502, f'The agent made a graphic outside the allowed HTML: {exc}') from exc
        with store.lock_for(pid):
            p = _load(pid)
            current = _find(p, ident)
            if out['html']:
                current['versions'] = ((current.get('versions') or []) + [dict(html=out['html'], note=message[:200], at=time.time())])[-MAX_VERSIONS:]
                current['current'] = len(current['versions']) - 1
            if out['title'] and not current.get('versions', [])[:-1]:
                current['title'] = out['title']  # name a new graphic once; later renames are the writer's
            store.save(p)
            return {'reply': out['reply'], 'graphic': current, 'changed': bool(out['html'])}

    @app.get(base + '/{ident}/still')
    def still(pid: str, ident: str, t: float = 0.0, v: int = -1):
        with store.lock_for(pid):
            p = _load(pid)
            g = _find(p, ident)
        versions = g.get('versions') or []
        i = v if 0 <= v < len(versions) else g.get('current', len(versions) - 1)
        if not versions or not 0 <= i < len(versions):
            raise HTTPException(404, 'Nothing designed yet')
        seconds = float(g.get('seconds') or 6)
        ctx = _context(pid, p, versions[i]['html'], seconds)
        with _CAPTURE:
            png = scenes.capture(store.project_dir(pid) / 'media', 'slides/custom.html', ctx,
                                 t=max(0.0, min(seconds, float(t))), size=(480, 270))
        return Response(png, media_type='image/png', headers={'Cache-Control': 'max-age=3600'})

    @app.post(base + '/{ident}/place')
    def place(pid: str, ident: str, payload: dict = Body(...)):
        sid = str(payload.get('slide') or '')
        with store.lock_for(pid):
            p = _load(pid)
            g = dict(_find(p, ident))
            slide = next((s for s in p.slides if s.id == sid and not s.insert), None)
            if slide is None:
                raise HTTPException(404, 'Choose a paragraph to place it on')
        html, seconds = current_html(g), float(g.get('seconds') or 6)
        if not html:
            raise HTTPException(400, 'Design the graphic first')

        def work(progress):
            progress(f'Rendering {g["title"]}')
            cand = custom_scenes.html_candidate(html, store.project_dir(pid) / 'media', {},
                                                motion='reveal', seconds=seconds, project=p)
            cand.update(title=g['title'], graphic_id=ident)
            with store.lock_for(pid):
                q = _load(pid)
                s = next((x for x in q.slides if x.id == sid), None)
                if s is None:
                    raise RuntimeError('That paragraph is no longer in the script')
                s.candidates.insert(0, cand)
                s.chosen_id, s.custom_html, s.prefer_kind, s.locked_media = cand['id'], cand['custom_html'], 'custom', True
                current = next((x for x in graphics_of(q) if x.get('id') == ident), None)
                if current is not None and sid not in current.setdefault('used_in', []):
                    current['used_in'].append(sid)
                store.save(q)
            progress('Placed')
            return {'slide': sid}
        return {'job': jobs.start('graphic', pid, work)}

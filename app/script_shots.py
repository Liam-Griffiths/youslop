"""Move a paragraph between shots on the Script page, as one undoable edit.

A shot is the run of paragraphs the page groups under one description
(script_agent.shots). Moving a paragraph reorders the main track, gives the
paragraph its new shot's description, and keeps both shots' boundaries and
chapter headings where the writer sees them. Takes and media files are never
touched; a moved paragraph keeps its own recording.
"""
import uuid
from copy import deepcopy

from fastapi import Body, HTTPException

from . import jobs, store, undo
from .script_agent import shots

# Picture choice belongs to the paragraph that starts a picture. When a shot's
# first paragraph leaves, the next one inherits it so the shot keeps its picture.
MEDIA_KEYS = ('kind', 'prefer_kind', 'candidates', 'chosen_id', 'locked_media', 'map_place',
              'map_lat', 'map_lon', 'map_zoom', 'map_kind', 'map_style', 'diagram', 'custom',
              'custom_html', 'shot')


class MoveError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _ids(project):
    return [[s.id for s in run] for run in shots(project)]


def move(project, sid, shot, before=''):
    """Move paragraph `sid` into the shot led by `shot`, before `before` or at its end."""
    runs = shots(project)
    by_id = {s.id: s for s in project.slides}
    para = by_id.get(sid)
    if not para or para.insert:
        raise MoveError('Only spoken paragraphs can move between shots.', 404 if not para else 400)
    source = next(run for run in runs if para in run)
    target = next((run for run in runs if run[0].id == shot), None)
    if target is None or target[0].insert:
        raise MoveError('That shot is no longer on the page.', 409)
    if before == sid:
        return False
    if before and before not in {s.id for s in target}:
        raise MoveError('Drop the paragraph inside the shot.', 409)
    note = (target[0].visual_note or '')
    chapters = {id(run): run[0].chapter or '' for run in runs}
    lead_mode = {id(run): run[0].picture_mode for run in runs}
    was_lead = source[0] is para

    # The intended shots, by id, once the paragraph has moved.
    desired = [list(run) for run in runs]
    src = next(r for r in desired if r and r[0] is source[0])
    dst = next(r for r in desired if r and r[0] is target[0])
    src.remove(para)
    index = len(dst) if not before else next(i for i, s in enumerate(dst) if s.id == before)
    dst.insert(index, para)
    new_order = [s for run in desired for s in run]
    if [[s.id for s in run] for run in desired if run] == [[s.id for s in run] for run in runs]:
        return False

    if was_lead and src and not any(getattr(src[0], k) for k in ('chosen_id', 'candidates', 'locked_media')):
        for key in MEDIA_KEYS:
            setattr(src[0], key, deepcopy(getattr(para, key)))
    para.visual_note = note
    # Each touched shot's chapter heading and break stay with whichever
    # paragraph now leads it.
    for original, run in ((source, src), (target, dst)):
        for k, s in enumerate(run):
            if k == 0:
                s.chapter = chapters[id(original)]
                if lead_mode[id(original)] == 'new':
                    s.picture_mode = 'new'
            else:
                s.chapter = ''
                if s.picture_mode == 'new':
                    s.picture_mode = 'auto'
    if not src and chapters[id(source)]:
        # The shot that left was a chapter's only one: the heading stays put.
        after = next((r for r in desired[desired.index(src) + 1:] if r), None)
        if after and not (after[0].chapter or '').strip():
            after[0].chapter = chapters[id(source)]
            after[0].picture_mode = 'new' if after[0].picture_mode == 'auto' else after[0].picture_mode
    project.slides = new_order
    want = [[s.id for s in run] for run in desired if run]
    for _ in range(3):
        got = _ids(project)
        if got == want:
            return True
        # Fill the breaks the grouping did not find on its own, and hold
        # undescribed paragraphs inside their shot.
        for run in desired:
            for k, s in enumerate(run):
                if k == 0 and s.picture_mode != 'new' and not any(g[0] == s.id for g in got):
                    s.picture_mode = 'new'
                elif k and any(g[0] == s.id for g in got):
                    s.picture_mode = 'hold'
    if _ids(project) != want:
        raise MoveError('Could not keep the shots apart here; try merging the shots instead.', 409)
    return True


def register(app):
    @app.post('/api/projects/{pid}/script/move')
    def script_move(pid: str, payload: dict = Body(...)):
        sid, shot, before = (str(payload.get(k) or '') for k in ('id', 'shot', 'before'))
        if not sid or not shot:
            raise HTTPException(400, 'Name the paragraph and the shot.')
        with store.lock_for(pid):
            try:
                p = store.load(pid)
            except FileNotFoundError as exc:
                raise HTTPException(404, 'Project not found') from exc
            if jobs.active_for(pid, writing=True):
                raise HTTPException(409, 'Wait for jobs that update this project before moving paragraphs.')
            version = payload.get('version')
            if type(version) in (int, float) and version != p.updated_at:
                raise HTTPException(409, 'The script changed; try the move again.')
            try:
                changed = move(p, sid, shot, before)
            except MoveError as exc:
                raise HTTPException(exc.status, str(exc)) from exc
            if changed:
                source = undo.edit_source.get()
                token = undo.edit_source.set(('Move paragraph', source[1] if source else uuid.uuid4().hex))
                try:
                    store.save(p)
                finally:
                    undo.edit_source.reset(token)
            return p.to_dict()

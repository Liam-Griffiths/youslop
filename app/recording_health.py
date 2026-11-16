"""Read-only availability of current recordings; retired takes stay untouched."""
import logging

from . import store
from .schema import take_track

log = logging.getLogger(__name__)


def take_missing(root, take):
    return bool(take) and not (take.get('path') and (root / take['path']).is_file())


def insert_source(meta):
    from . import inserts
    try:
        return inserts.source(meta)
    except (OSError, ValueError, StopIteration):
        return None


def missing(project):
    """Current tracks, enabled reads and audible inserts, never history."""
    root = store.project_dir(project.id)
    result = []

    def add(owner, ident, label, track, take, active):
        if take_missing(root, take):
            result.append(dict(owner=owner, id=ident, label=label, track=track,
                path=take.get('path', ''), active=active,
                reprocess=bool(take.get('raw_path') and (root / take['raw_path']).is_file())))

    for n, slide in enumerate(project.slides, 1):
        label = f'¶{n}'
        if slide.insert:
            if slide.insert.get('source_audio') and insert_source(slide.insert) is None:
                result.append(dict(owner='inserts', id=slide.id, label=label, track='',
                    path=f"{slide.insert['shoot_id']}/{slide.insert['source_id']}",
                    active=True, reprocess=False))
            continue
        takes = slide.takes or ({take_track(slide.take): slide.take} if slide.take else {})
        active = 'camera' if slide.on_camera else project.voice_track
        for track, take in takes.items():
            add('slides', slide.id, label, track, take, track == active or not slide.takes)
    from . import render
    placed = {slot.id for slots in render._sponsor_placements(
        project, render._slide_durations(project, True)).values() for slot in slots}
    for slot in project.sponsors:
        if slot.id in placed:
            add('sponsors', slot.id, f'Sponsor {slot.vars.get("name") or slot.id}', '', slot.take, True)
    return result


def warn(label):
    log.warning('Sound mixed without %s: its recording is missing.', label)


def reprocess(pid, payload):
    """Explicit recovery to a fresh path, preserving the missing reference."""
    from . import audio
    from .layers import require_unlocked
    from .audio_files import next_take_path
    from uuid import uuid4
    def find(project):
        item = next((r for r in missing(project) if all(r.get(k) == payload.get(k)
                    for k in ('owner', 'id', 'track', 'path'))), None)
        if not item or not item['reprocess']:
            raise ValueError('This recording changed or its raw file is unavailable. Refresh Voice.')
        sponsor = item['owner'] == 'sponsors'
        require_unlocked(project, 'sponsors' if sponsor else 'voice')
        owner = next(s for s in (project.sponsors if sponsor else project.slides) if s.id == item['id'])
        return item, sponsor, owner, owner.take if sponsor else owner.takes[item['track']]

    root = store.project_dir(pid)
    with store.lock_for(pid):
        project = store.load(pid)
        item, sponsor, owner, take = find(project)
        out = next_take_path(root, item['track'] or 'sponsor', owner.id + '.reprocessed-' + uuid4().hex)
    # Cleaning is slow; do it outside the lock, then re-check before applying.
    meta = audio.process_take(root / take['raw_path'], out, project.voice)
    with store.lock_for(pid):
        project = store.load(pid)
        item, sponsor, owner, current = find(project)
        if current.get('raw_path') != take.get('raw_path'):
            raise ValueError('This recording changed while it was cleaned. Refresh Voice.')
        replacement = {**current, **meta, 'path': out.relative_to(root).as_posix()}
        if sponsor:
            owner.set_take(replacement)
        else:
            project.set_take(owner, item['track'], replacement, reason='reprocess')
        store.save(project)

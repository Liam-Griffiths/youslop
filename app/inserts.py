"""Non-spoken main-track rows. Validate a detached row before changing order."""
from copy import deepcopy
import math

from .schema import Slide

FIELDS = {
    'clip': {'shoot_id', 'source_id', 'in_s', 'out_s', 'source_audio'},
    'block': {'block', 'vars'},
    'picture': {'asset_id', 'bin_id', 'source_slide', 'candidate_id'},
    'card': {'text'},
    'stage': {'model_id', 'source_slide'},
    'graphic': {'graphic_id'},
}


def _text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 400:
        raise ValueError(f'{key} must be non-empty text (at most 400 characters)')
    return value


def prepare(project, payload, slide=None):
    """Return a validated copy and its requested position, without any writes."""
    if project.kind == 'clip':
        raise ValueError('Inserts belong to video projects, not source-linked clip projects')
    row = deepcopy(slide) if slide else Slide(kind='kenburns', picture_mode='new', locked_media=True)
    data = {**row.insert, **payload}
    kind = data.get('kind')
    if not isinstance(kind, str) or kind not in FIELDS:
        raise ValueError('Insert kind must be clip, block, picture, card, stage or graphic')
    if slide and kind != slide.insert['kind']:
        raise ValueError('Insert kind cannot be changed; add a new insert')
    if payload.keys() - (FIELDS[kind] | {'kind', 'seconds', 'after'}):
        raise ValueError('Unknown insert field')
    after = data.pop('after', None)
    if 'after' in payload:
        if not isinstance(after, str) or (after not in {'', 'intro'} and
                not any(s.id == after and s.id != row.id for s in project.slides)):
            raise ValueError('Unknown main-track boundary')
    elif slide is None:
        after = ''
    if kind == 'clip':
        from . import footage, transcripts
        sid, fid = _text(data, 'shoot_id'), _text(data, 'source_id')
        # Require explicit endpoints; source_range also checks manifest ownership,
        # finite numbers, source bounds and the original's availability.
        if any(type(data.get(key)) not in (int, float) for key in ('in_s', 'out_s')):
            raise ValueError('A clip needs in_s and out_s')
        a, b = transcripts.source_range(sid, fid, data['in_s'], data['out_s'])
        source = next(s for s in footage.load(sid).files if s.id == fid)
        if source.kind != 'video':
            raise ValueError('A clip insert needs a video source')
        sound = data.get('source_audio', False)
        if not isinstance(sound, bool) or (sound and not source.audio):
            raise ValueError('source_audio must be boolean and the source must have audio')
        data.update(in_s=a, out_s=b, source_audio=sound, seconds=b-a)
        if 'seconds' in payload and (type(payload['seconds']) not in (int, float)
                or payload['seconds'] != b-a):
            raise ValueError('Clip seconds must equal out_s minus in_s')
    else:
        seconds = data.get('seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('seconds must be finite and greater than zero')
        if kind in {'stage', 'graphic'}:
            from . import composing_sources
            composing_sources.prepare(project, row, data, slide)
        elif kind == 'picture':
            if data.get('bin_id') or data.get('candidate_id'):
                from .picture_sources import candidate
                # The placed candidate is independent of its search paragraph.
                # Duration edits still work after that paragraph is removed.
                same = slide and data.get('candidate_id') and all(
                    data.get(k) == slide.insert.get(k) for k in ('candidate_id', 'source_slide'))
                found = next((deepcopy(c) for c in row.candidates if c['id'] == row.chosen_id), None) if same else None
                found = found or candidate(project, data)
                row.candidates, row.chosen_id = [found], found['id']
                row.insert = deepcopy(data)
                row.narration = ''
                return row, after
            from . import library
            ident = _text(data, 'asset_id')
            asset, path = library.get(ident), library.file_path(ident)
            if not asset or asset['kind'] not in {'image', 'video'} or not path or not path.is_file():
                raise ValueError('Library picture is unavailable')
        elif kind == 'block':
            from . import blocks
            block = blocks.discover().get(_text(data, 'block'))
            aspect = {'portrait': '9:16', 'square': '1:1'}.get(project.aspect, '16:9')
            if not block or aspect not in block['meta']['aspects']:
                raise ValueError('Choose a block that supports the project aspect')
            data['vars'] = blocks.validate_vars(block['meta'], data.get('vars', {}))
        else:
            data['text'] = _text(data, 'text')
    row.insert = deepcopy(data)
    row.narration = ''
    return row, after


def place(project, row, after):
    """Apply only after prepare succeeds; None preserves a patched row's order."""
    from .composing_sources import attach
    attach(project, row)
    if after is None:
        project.slides[project.slides.index(project.slide(row.id))] = row
        return
    rows = [s for s in project.slides if s.id != row.id]
    index = 0 if after in {'', 'intro'} else next(i+1 for i, s in enumerate(rows) if s.id == after)
    rows.insert(index, row)
    project.slides = rows


def source(meta, *, preview=False):
    """Resolve a manifest-owned range, including sources without named clips.

    Proxies retain the original clock and audio. Never copy or modify originals.
    """
    from . import footage
    shoot = footage.load(meta['shoot_id'])
    file = next((f for f in shoot.files if f.id == meta['source_id']), None)
    if (file is None or file.kind != 'video' or
            not 0 <= meta['in_s'] < meta['out_s'] <= file.duration):
        raise ValueError('Insert source range is unavailable')
    original = footage.source_path(shoot, file)
    proxy = footage.shoot_dir(shoot.id) / 'proxies' / (file.id + '.mp4')
    paths = (proxy, original) if preview else (original, proxy)
    path = next((p for p in paths if p.is_file()), None)
    if path is None:
        raise FileNotFoundError('Insert original and proxy are unavailable')
    if meta.get('source_audio') and not file.audio:
        raise ValueError('Insert source has no audio')
    return path


def source_state(meta):
    """Both resolutions matter to cached previews and their source sound."""
    from .render import _stat
    result = []
    for preview in (False, True):
        try:
            path = source(meta, preview=preview)
            result.append([str(path), _stat(path)])
        except (OSError, ValueError):
            result.append(None)
    return result


def chapter_hold(project, slide):
    """An insert's opening card consumes its own explicit time budget."""
    from .schema import chapter_title
    title = chapter_title(project, slide)
    frame = project.frame
    default = frame.arrive_s + frame.title_hold_base_s + frame.title_hold_per_word_s * len(title.split())
    return min(slide.insert['seconds'], max(0, slide.chapter_hold
               if slide.chapter_hold is not None else default)) if title else 0


def replace_script(project, slides):
    """Keep insert boundaries by spoken ordinal, clamped to the new end.

    Opening rows stay first; terminal rows follow the new last paragraph.
    Collapsed boundaries retain their original order. Retire replaced takes
    even when no undo session exists (including unsaved in-memory recordings).
    """
    from . import undo
    old = project.to_dict()
    count = sum(not s.insert for s in project.slides)
    boundaries = {}
    ordinal = 0
    for row in project.slides:
        if row.insert:
            boundary = (len(slides) if ordinal and ordinal == count
                        else min(ordinal, len(slides)))
            boundaries.setdefault(boundary, []).append(row)
        else:
            ordinal += 1
    rows = list(boundaries.get(0, []))
    for index, slide in enumerate(slides, 1):
        rows.append(slide)
        rows.extend(boundaries.get(index, []))
    target = dict(old, slides=[s.to_dict() for s in rows])
    if undo.retain_recordings(target, old):
        project.retired_takes = target.get('retired_takes', [])
        for row, data in zip(rows, target['slides']):
            row.history = data.get('history', [])
    project.slides = rows

"""Persistent feedback and the shared vocabulary used by look selectors."""
from copy import deepcopy
import logging

from . import channels, store
from .schema import FrameSpec


def _tokens():
    from . import cuts, render, themes
    return {
        'camera': set(render.CAMERA_OPS),
        'join': set(render.JOIN_XFADE) | set(render.NAMED_XFADES),
        'theme': set(themes.theme_keys()),
        'cut': set(cuts.BY_KEY),
    }


LOOK_TOKENS = _tokens()


def validate_look(token):
    if not isinstance(token, str) or ':' not in token:
        raise ValueError('Look must be a namespaced token, e.g. camera:punch')
    kind, name = token.split(':', 1)
    if name not in _tokens().get(kind, set()):
        raise ValueError(f'Unknown look token: {token}')
    return token


def choose(kind, candidates, frame):
    candidates = list(dict.fromkeys(candidates))
    for name in candidates:
        if f'{kind}:{name}' not in frame.rejected_looks:
            return name
    logging.getLogger(__name__).warning('All %s candidates rejected; using %s', kind, candidates[0])
    return candidates[0]


def effective_frame(project):
    channel = channels.load_or_none(project.channel_id)
    frame = FrameSpec.from_dict(deepcopy(project.frame.to_dict()))
    if channel:
        for key in ('rules', 'rejected_looks'):
            setattr(frame, key, list(dict.fromkeys(getattr(channel.frame, key) + getattr(frame, key))))
    return frame


def resolve_choices(project):
    """Resolve existing choices too, so late channel feedback reaches old videos."""
    from . import cuts, themes
    frame = effective_frame(project)
    key = choose('theme', [project.style.theme, *themes.theme_keys()], frame)
    if key != project.style.theme:
        themes.apply_to_style(project.style, key, False)
    if project.style.format in cuts.BY_KEY:
        project.style.format = choose('cut', [project.style.format, *cuts.KEYS], frame)


def add(pid, value, *, kind='rules', scope='project'):
    if scope not in ('project', 'channel'):
        raise ValueError('Scope must be project or channel')
    if kind == 'rejected_looks':
        value = validate_look(value)
    else:
        if not isinstance(value, str):
            raise ValueError('Rule must be text')
        value = ' '.join(value.split())[:200]
        if not value:
            raise ValueError('Rule cannot be empty')
    project = store.load(pid)
    if scope == 'channel':
        if not project.channel_id:
            raise ValueError('Project has no channel')
        persistence, ident = channels, project.channel_id
    else:
        persistence, ident = store, pid
    with persistence.lock_for(ident):
        obj = persistence.load(ident)
        items = getattr(obj.frame, kind)
        if value not in items:
            items.append(value)
        persistence.save(obj)
        return obj.frame.to_dict()


def save_format(cid, pid, name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
        raise ValueError('Format name must be 1 to 200 characters')
    project = store.load(pid)
    if project.channel_id != cid:
        raise ValueError('Project must belong to this channel')
    channel = channels.load(cid)
    look = project.format_look or dict(intro=channel.intro.to_dict(), outro=channel.outro.to_dict())
    saved = dict(name=name.strip(), style=deepcopy(project.style.to_dict()),
                 frame=effective_frame(project).to_dict(),
                 look=dict(theme=project.style.theme, cut=project.style.format,
                           intro=deepcopy(look['intro']), outro=deepcopy(look['outro'])))
    with channels.lock_for(cid):
        channel = channels.load(cid)
        if any(f['name'] == saved['name'] for f in channel.formats):
            raise ValueError('Format name already exists')
        channel.formats.append(saved)
        channels.save(channel)
    return saved

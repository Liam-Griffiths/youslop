"""Timeline variables mapped directly onto existing schema fields.

Styles and frames are snapshots, not sparse overrides. Sources are inferred by
comparison; resetting restores the current channel/theme/default value.
Block tokens use sparse overrides and explicit ownership instead.
"""
from dataclasses import fields
import math
import re

from . import channels, themes
from .schema import FrameSpec, Style

COPY = {'channel_name': ('name',), 'tagline': ('tagline',),
        'handle': ('outro', 'handle'), 'subscribe': ('outro', 'cta')}


def _get(obj, path):
    for key in path:
        obj = getattr(obj, key)
    return obj


def variables(project=None, channel=None):
    if channel is None and project and project.channel_id:
        channel = channels.load_or_none(project.channel_id)
    style = project.style if project else channel.style if channel else Style()
    frame = project.frame if project else channel.frame if channel else FrameSpec()
    theme = themes.theme(style.theme)
    result = dict(colors={}, copy={}, frame={})
    for key, token in [('accent', 'accent'), ('accent2', 'accent2'), ('bg', 'ground'), ('ink', 'ink')]:
        editable = key in ('accent', 'accent2')
        value = (getattr(style, key) or theme[token]) if editable else theme[token]
        source = 'theme'
        if editable and value.lower() != theme[token].lower():
            source = 'channel' if channel and getattr(channel.style, key) == value else 'project' if project else 'default'
        result['colors'][key] = dict(value=value, source=source, editable=editable)
    for key, path in COPY.items():
        owner = channel or project
        # A standalone project's title/subtitle fill the channel name/tagline.
        solo_path = ('title',) if key == 'channel_name' else ('subtitle',) if key == 'tagline' else path
        value = _get(owner, path if channel else solo_path) if owner else ''
        result['copy'][key] = dict(value=value, source='channel' if channel else 'project' if project else 'default')
    for f in fields(FrameSpec):
        value = getattr(frame, f.name)
        if type(value) not in (int, float):
            continue
        source = 'default'
        if value != getattr(FrameSpec(), f.name):
            source = 'channel' if channel and value == getattr(channel.frame, f.name) else 'project' if project else 'channel'
        if value == theme.get('frame', {}).get(f.name):
            source = 'theme'
        unit = 's' if f.name.endswith('_s') else '%' if '_pct_' in f.name else 'dB' if f.name.endswith('_db') else 'LUFS' if f.name.endswith('_lufs') else ''
        result['frame'][f.name] = dict(value=value, source=source, unit=unit)
    from .block_theme import resolve
    result["block"] = resolve(project, channel)
    return result


def apply(project, channel, scope, key, value):
    """Validate one exposed field; None resets to the current inherited value."""
    if scope not in ('project', 'channel') or (scope == 'channel' and channel is None):
        raise ValueError('Choose an available project or channel scope')
    obj = channel if scope == 'channel' else project
    if key.startswith('block.'):
        from .block_theme import validate
        token = key.removeprefix('block.')
        if value is None:
            from .block_theme import BLOCK_TOKENS
            if token not in BLOCK_TOKENS:
                raise ValueError('Unknown block token')
            obj.style.block_theme.pop(token, None)
        else:
            obj.style.block_theme = {**obj.style.block_theme, token: validate(token, value)}
    elif key in ('accent', 'accent2'):
        if value is None:
            value = getattr(channel.style, key) if scope == 'project' and channel else themes.theme(obj.style.theme)[key]
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError('Use a six-digit hex colour')
        setattr(obj.style, key, value)
    elif key in COPY:
        if scope != ('channel' if channel else 'project'):
            raise ValueError('Channel copy must be edited on the channel')
        path = COPY[key]
        if not channel and key in ('channel_name', 'tagline'):
            path = ('title',) if key == 'channel_name' else ('subtitle',)
        if not isinstance(value, str):
            raise ValueError('Copy must be text')
        setattr(_get(obj, path[:-1]), path[-1], value)
    elif key in variables(project, channel)['frame']:
        if value is None:
            value = getattr(channel.frame if scope == 'project' and channel else FrameSpec(), key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Enter a finite number')
        if type(getattr(obj.frame, key)) is int and value != int(value):
            raise ValueError('Enter a whole number')
        obj.frame = obj.frame.merge({key: value})
    else:
        raise ValueError('Unknown or read-only variable')

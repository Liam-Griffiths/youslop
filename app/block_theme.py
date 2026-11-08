"""Sparse block overrides, shared by project renders and standalone previews."""
import math
import re

from . import channels, themes

COLORS = ('bg', 'ink', 'accent', 'accent2', 'panel', 'line', 'dim')
# Empty faces/weight retain each family's existing typography.
BLOCK_TOKENS = dict(bg='#0E0F11', ink='#F2F2F2', accent='#FF5A1F', accent2='#6FB7FF',
                    panel='', line='', dim='', font_display='', font_body='',
                    radius=0, weight='', pace=1.)
WEIGHTS = dict(regular=400, bold=700, heavy=800)


def fonts(include_packs=True):
    from . import packs
    installed = {f'pack:{item["ref"]}': f'/fonts/packs/{item["ref"]}'
                 for pack in packs.scan() for item in pack.fonts()} if include_packs else {}
    return {**installed, 'Inter': '/fonts/Inter-Medium.ttf',
            'Archivo': '/fonts/ArchivoNarrow-Bold.ttf',
            'EB Garamond': '/fonts/EBGaramond-Regular.ttf',
            'JetBrains Mono': '/fonts/JetBrainsMono-Regular.ttf'}


def validate(key, value, faces=None):
    if key not in BLOCK_TOKENS:
        raise ValueError('Unknown block token')
    if key in COLORS:
        valid = isinstance(value, str) and (value == '' and key in ('panel', 'line', 'dim') or
                                          re.fullmatch(r'#[0-9a-fA-F]{6}', value))
    elif key.startswith('font_'):
        valid = isinstance(value, str) and (not value or value in (fonts() if faces is None else faces))
    elif key == 'weight':
        valid = isinstance(value, str) and value in ('', *WEIGHTS)
    else:
        lo, hi = (0, 32) if key == 'radius' else (.7, 1.4)
        valid = type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi
    if not valid:
        raise ValueError(f'Invalid block token: {key}')
    return value


def resolve(project=None, channel=None, *, defaults=None, faces=None):
    if channel is None and project and project.channel_id:
        channel = channels.load_or_none(project.channel_id)
    result = {k: dict(value=v, source='default', editable=True) for k, v in BLOCK_TOKENS.items()}
    def merge(values, source):
        for key, value in values.items():
            if key in result:  # Forward-compatible stored overrides.
                result[key].update(value=validate(key, value, faces), source=source)
    merge(defaults or {}, 'default')
    if project or channel:
        style = project.style if project else channel.style
        entry = themes.theme(style.theme)
        merge({k: entry['ground' if k == 'bg' else k] for k in COLORS[:4]}, 'theme')
        # Existing style accents predate sparse block overrides and keep working.
        for key in ('accent', 'accent2'):
            value = getattr(style, key) or entry[key]
            if value.lower() != entry[key].lower():
                merge({key: value}, 'channel' if channel and getattr(channel.style, key) == value else
                      'project' if project else 'channel')
        if channel:
            merge(channel.style.block_theme, 'channel')
        if project:
            merge(project.style.block_theme, 'project')
    for key, warning in warnings({k: v['value'] for k, v in result.items()}).items():
        result[key]['warning'] = warning
    return result


def values(project=None, channel=None):
    return {k: v['value'] for k, v in resolve(project, channel).items()}


def warnings(tokens):
    def rgb(key):
        return [int(tokens[key][i:i+2], 16) for i in (1, 3, 5)]
    def lum(color):
        c = [v / 255 for v in color]
        return sum((v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4)*w
                   for v, w in zip(c, (.2126, .7152, .0722)))
    bg, ink = rgb('bg'), rgb('ink')
    panel = rgb('panel') if tokens['panel'] else [a*.95+b*.05 for a, b in zip(bg, ink)]
    result = {}
    for fg, background, label, minimum in [('ink', bg, 'bg', 4.5), ('ink', panel, 'panel', 4.5),
                                            ('accent', bg, 'bg', 3)]:
        a, b = sorted((lum(rgb(fg)), lum(background)))
        ratio = (b+.05)/(a+.05)
        if ratio < minimum:
            message = f'{fg} on {label}: {ratio:.2f}:1 (needs {minimum}:1)'
            result[fg] = '; '.join(filter(None, (result.get(fg), message)))
    return result


def cache_owner(owner):
    """Exclude block-only knobs from the common picture cache dependencies."""
    from dataclasses import asdict, is_dataclass
    if not is_dataclass(owner):
        return None
    data = asdict(owner)
    (data.get('style', data)).pop('block_theme', None)
    return data

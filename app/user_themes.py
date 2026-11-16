"""Themes the creator built in the app, kept beside the built-in and pack themes.

A theme is small: four colours, a pattern, the icons the pattern is tiled from,
a grade and three template picks. Each one is a JSON file under the data
folder's `themes/`, so it can be copied into a pack by hand later. Keys start
with `_mine/`, which no pack id can match.
"""
from __future__ import annotations

import io
import json
import re
import uuid

from PIL import Image, ImageDraw

from . import block_theme, config, motifs, themes, titles

PREFIX = '_mine/'
PATTERNS = ('icons', 'stripes', 'words', 'halftone')
GRADES = ('warm', 'neutral', 'cool', 'mono')
MAX_ICONS = 6
# How graphics over the picture are drawn; applied to the channel's block theme.
BLOCK_FIELDS = ('radius', 'panel_opacity', 'border', 'font_display', 'weight')
_SLUG = r'[a-z0-9]{8,32}'
_HEX = r'#[0-9a-fA-F]{6}'


def folder():
    return config.DATA / 'themes'


def _light(ground: str) -> bool:
    r, g, b = titles._hex(ground)[:3]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.55


def clean(data: dict) -> dict:
    """Check a theme from the page and return exactly the fields a theme holds."""
    from . import intro, outro, thumbs

    if not isinstance(data, dict):
        raise ValueError('A theme must be an object')
    label = ' '.join(str(data.get('label') or '').split())[:40]
    if not label:
        raise ValueError('Give the theme a name')
    out = dict(label=label, blurb=' '.join(str(data.get('blurb') or '').split())[:200])
    out['for'] = ' '.join(str(data.get('for') or '').split())[:60]
    for name in ('accent', 'accent2', 'ground', 'ink'):
        value = str(data.get(name) or '')
        if not re.fullmatch(_HEX, value):
            raise ValueError(f'{name} must be a colour like #AABBCC')
        out[name] = value.upper()
    out['grade'] = data.get('grade') if data.get('grade') in GRADES else 'neutral'
    out['pattern'] = data.get('pattern') if data.get('pattern') in PATTERNS else 'icons'
    icons = [k for k in (data.get('icons') if isinstance(data.get('icons'), list) else []) if k in motifs.ICONS]
    out['icons'] = list(dict.fromkeys(icons))[:MAX_ICONS] or ['star4']
    out['blocks'] = {}
    for name, value in (data.get('blocks') if isinstance(data.get('blocks'), dict) else {}).items():
        if name in BLOCK_FIELDS:
            try:
                out['blocks'][name] = block_theme.validate(name, value)
            except ValueError:
                pass
    out['light'] = _light(out['ground'])
    out['frame'] = {}
    base = themes.THEMES[0]
    picks = dict(intro={t['key'] for t in intro.all_templates()}, thumb={t['key'] for t in thumbs.TEMPLATES},
                 outro={t['key'] for t in outro.all_templates()})
    for name, known in picks.items():
        out[name] = data.get(name) if data.get(name) in known else base[name]
    return out


def _read(path) -> dict | None:
    try:
        value = clean(json.loads(path.read_text()))
    except (OSError, ValueError):
        return None
    return {**value, 'key': PREFIX + path.stem, 'mine': True}


def all_themes() -> list[dict]:
    if not folder().is_dir():
        return []
    found = [_read(p) for p in sorted(folder().glob('*.json')) if re.fullmatch(_SLUG, p.stem)]
    return sorted((t for t in found if t), key=lambda t: t['label'].lower())


def _slug(key: str) -> str:
    slug = str(key or '').removeprefix(PREFIX)
    if not re.fullmatch(_SLUG, slug):
        raise ValueError('No such theme')
    return slug


def save(data: dict, key: str = '') -> dict:
    """Create a theme, or replace the one called `key`."""
    value = clean(data)
    slug = _slug(key) if key else uuid.uuid4().hex[:12]
    path = folder() / f'{slug}.json'
    if key and not path.exists():
        raise ValueError('No such theme')
    folder().mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(path)
    return {**value, 'key': PREFIX + slug, 'mine': True}


def delete(key: str) -> None:
    path = folder() / f'{_slug(key)}.json'
    if not path.exists():
        raise ValueError('No such theme')
    path.unlink()


# ------------------------------------------------------------------ pictures
W, H = 640, 360


def _field(theme: dict, name: str) -> Image.Image:
    ground, duo = theme['ground'], [theme['accent'], theme['accent2']]
    base = motifs.gradient((W, H), [motifs.shade(ground, 1.25 if not theme['light'] else 1.02), ground,
                                    motifs.mix(ground, theme['accent'], 0.16)], 120).convert('RGBA')
    kind = theme['pattern']
    if kind == 'stripes':
        bands = motifs.stripes((W, H), [motifs._c(theme['accent'], 46), (0, 0, 0, 0), motifs._c(theme['accent2'], 30),
                                        (0, 0, 0, 0)], width=34)
        return Image.alpha_composite(base, bands)
    if kind == 'words':
        return Image.alpha_composite(base, motifs.word_field((W, H), name, titles.CONDENSED_STACK, duo, rows=6, alpha=60))
    if kind == 'halftone':
        return Image.alpha_composite(base, motifs.halftone((W, H), motifs._c(theme['accent'], 90), cell=14,
                                                           radius=0.34, fade=(0.0, 1.0)))
    return Image.alpha_composite(base, motifs.icon_field((W, H), theme['icons'], duo + [theme['ink']],
                                                         cell=62, alpha=70, angle=-14))


def sample(data: dict, name: str = '') -> bytes:
    """A small picture of a theme: its ground and pattern, with type and both colours on it."""
    theme = clean({**data, 'label': data.get('label') or 'Theme'})
    name = ' '.join(str(name or '').split())[:40] or theme['label']
    out = _field(theme, name)
    ink, pad = titles._hex(theme['ink']), 36
    # The panel a lower third or caption sits on, with this theme's corners, opacity and border.
    look = theme['blocks']
    box = [pad - 18, 132, W - 150, 318]
    panel = motifs.mix(theme['ground'], theme['ink'], 0.05)[:3] + (round(255 * look.get('panel_opacity', 1)),)
    layer = Image.new('RGBA', out.size, (0, 0, 0, 0))
    border = round(look.get('border', 0) * 1.2)
    ImageDraw.Draw(layer).rounded_rectangle(box, round(look.get('radius', 0) * 1.2), fill=panel,
                                            outline=motifs.mix(theme['ground'], theme['ink'], 0.55) if border else None,
                                            width=border)
    out = Image.alpha_composite(out, layer)
    d = ImageDraw.Draw(out)
    kicker = titles._load(titles.KICKER_STACK, 15)
    d.text((pad, 150), (theme['for'] or 'A new video').upper()[:44], font=kicker, fill=titles._hex(theme['accent']))
    size = 56
    title = titles._load(titles.CONDENSED_STACK, size)
    while size > 26 and d.textlength(name.upper(), font=title) > W - 150 - pad * 2:
        size -= 4
        title = titles._load(titles.CONDENSED_STACK, size)
    d.text((pad, 176), name.upper(), font=title, fill=ink)
    y = 176 + size + 22
    d.rounded_rectangle([pad, y, pad + 150, y + 10], 5, fill=titles._hex(theme['accent']))
    d.rounded_rectangle([pad + 162, y, pad + 262, y + 10], 5, fill=titles._hex(theme['accent2']))
    d.rounded_rectangle([pad, y + 24, pad + 330, y + 29], 3, fill=ink[:3] + (120,))
    buf = io.BytesIO()
    out.convert('RGB').save(buf, 'PNG')
    return buf.getvalue()


def icon_png(key: str, color: str = '#FFFFFF', size: int = 48) -> bytes:
    if key not in motifs.ICONS or not re.fullmatch(_HEX, color):
        raise ValueError('No such icon')
    buf = io.BytesIO()
    motifs.icon(key, size, color, pad=0.12).save(buf, 'PNG')
    return buf.getvalue()

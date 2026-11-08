"""Named starting kits. Applying one never edits paragraph content or recordings."""
from copy import deepcopy
import hashlib
import json
import math
import os
import tempfile
import threading
import uuid
from typing import Literal

from fastapi import Body, HTTPException

from . import block_presets, block_theme, channels, kinds, slide_styles, themes
from .config import DATA
from .schema import Channel, Project, Style, group_slides, new_project

INDEX = DATA / 'style_kits' / 'index.json'
_LOCK = threading.RLock()
# Look only: renderer engine switches keep old cuts on their engine, and
# picture cadence is editorial, so neither travels with a style.
LOOK_FIELDS = tuple(k for k in Style.__dataclass_fields__
                    if k not in {'format', 'block_theme', 'music_db', 'sponsor_music_db', 'paragraph_gap',
                                 'picture_every'} and not k.endswith('_engine'))
# A built-in kit brings its theme's colours and grade; it never resets the
# user's drift, crossfade, vignette, board or cut settings to defaults.
BUILTIN_LOOK = ('theme', 'accent', 'accent2', 'grade')
# Keys match FORMAT_INFO. Pins refer to the shared library, never copied code.
_BUILTINS = [
    ('kenburns', 'Documentary', 'Photos that drift across the frame.', 'photos per paragraph', 'archive',
     ['lower_third_rule', 'date_timeline', 'map_highlight', 'quote_card']),
    ('essay', 'Video essay', 'Framed pictures with captions.', 'photos per paragraph', 'archive',
     ['title_card', 'pull_quote_picture', 'quote_card']),
    ('board', 'Handwritten board', 'Marker on slate, written as you talk.', 'board text', 'archive',
     ['labelled_diagram', 'step_list', 'callout_arrow']),
    ('flameboat', 'Flameboat', 'Rapid-fire technology explainer.', 'cues on words', 'terminal',
     ['number_slam', 'step_list', 'split_comparison']),
    ('casefile', 'Casefile', 'A lamp-lit case board.', 'cues on words', 'archive',
     ['document_highlight', 'date_timeline', 'map_highlight', 'quote_card']),
    ('loudmouth', 'Loudmouth', 'Kinetic type on spoken words.', 'cues on words', 'amp',
     ['kinetic_caption_slam', 'kicker_headline', 'number_slam']),
    ('groupchat', 'Group Chat', 'A message thread with cutaways.', 'cues on words', 'broadcast',
     ['quote_card', 'lower_third_panel', 'split_comparison']),
    ('ticker', 'Ticker', 'A terminal of figures and charts.', 'cues on words', 'terminal',
     ['number_slam', 'bar_chart', 'line_chart', 'bar_race', 'stat_comparison', 'simple_table', 'percentage_ring']),
    ('stage', '3D explainer', 'Models, orbits and reveals.', '3D models', 'terminal',
     ['lower_third_rule', 'labelled_diagram', 'callout_arrow']),
]


def builtin_kits():
    result = []
    for key, name, blurb, needs, theme, pins in _BUILTINS:
        style = Style(format=key)
        themes.apply_to_style(style, theme, take_templates=False)
        result.append(dict(id=key, name=name, blurb=blurb, needs=needs, default_kind=key,
                           look={k: deepcopy(getattr(style, k)) for k in BUILTIN_LOOK},
                           block_theme={}, blocks=dict(pins=pins, presets=[]),
                           rules=dict(visual_change_s=5, block_share_max=.5), builtin=True))
    return result


def _read():
    return json.loads(INDEX.read_text()) if INDEX.exists() else []


def _write(items):
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=INDEX.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(items, stream, indent=2, ensure_ascii=False)
        os.replace(name, INDEX)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def list_kits():
    with _LOCK:
        result = builtin_kits() + deepcopy(_read())
    # Adapters are read-only and resolve against their original source on apply.
    for path in sorted(channels.CHANNELS_DIR.glob('*/channel.json')):
        channel = channels.load(path.parent.name)
        for index, saved in enumerate(channel.formats):
            raw = saved.get('style') or {}
            result.append(dict(id=f'format:{channel.id}:{index}', name=saved['name'],
                               blurb=f'Saved format from {channel.name}', needs='',
                               default_kind=raw.get('format', 'kenburns'), look=deepcopy(raw),
                               block_theme=deepcopy(raw.get('block_theme', {})),
                               blocks=dict(pins=[], presets=[]), rules={}, builtin=False, readonly=True))
    for saved in slide_styles.list_styles():
        result.append(dict(id=f'custom:{saved["id"]}', name=saved['name'], blurb='Saved slide design',
                           needs='slide text', default_kind=f'custom:{saved["id"]}', look={},
                           block_theme={}, blocks=dict(pins=[], presets=[]), rules={},
                           builtin=False, readonly=True))
    return result


def get(ident):
    kit = next((k for k in list_kits() if k['id'] == ident), None)
    if kit is None:
        raise HTTPException(404, 'Style kit not found')
    return kit


def _validate(raw):
    """Validate portable data, dropping future fields and untrusted identity flags."""
    kit = {k: deepcopy(raw.get(k, default)) for k, default in dict(
        name='', blurb='', needs='', default_kind='kenburns', look={}, block_theme={},
        blocks=dict(pins=[], presets=[]), rules={}).items()}
    for key in ('name', 'blurb', 'needs'):
        if not isinstance(kit[key], str):
            raise ValueError(f'{key} must be text')
    kit['name'] = kit['name'].strip()
    if not kit['name'] or len(kit['name']) > 120:
        raise ValueError('Name must be 1–120 characters')
    if not kinds.valid(kit['default_kind']) or not kit['default_kind']:
        raise ValueError('Invalid default kind')
    for key in ('look', 'block_theme', 'blocks', 'rules'):
        if not isinstance(kit[key], dict):
            raise ValueError(f'{key} must be an object')
    kit['look'] = {k: v for k, v in kit['look'].items() if k in LOOK_FIELDS}
    defaults = Style()
    for key, value in kit['look'].items():
        sample = getattr(defaults, key)
        if (isinstance(sample, float) and (type(value) not in (int, float) or not math.isfinite(value))
                or not isinstance(sample, float) and type(value) is not type(sample)):
            raise ValueError(f'Invalid look field: {key}')
    kit['block_theme'] = {k: block_theme.validate(k, v) for k, v in kit['block_theme'].items()
                          if k in block_theme.BLOCK_TOKENS}
    pins, presets = kit['blocks'].get('pins', []), kit['blocks'].get('presets', [])
    if not isinstance(pins, list) or any(not isinstance(p, str) or not p for p in pins):
        raise ValueError('Pins must be block references')
    if not isinstance(presets, list) or any(not isinstance(p, dict) for p in presets):
        raise ValueError('Presets must be objects')
    kit['blocks'] = dict(pins=list(dict.fromkeys(pins)),
                         presets=[block_presets.validate(p, p) for p in presets])
    kit['rules'] = {k: v for k, v in kit['rules'].items() if k in ('visual_change_s', 'block_share_max')}
    for key, value in kit['rules'].items():
        if (type(value) not in (float, int) or not math.isfinite(value)
                or value < 0 or key == 'visual_change_s' and value == 0
                or key == 'block_share_max' and value > 1):
            raise ValueError(f'Invalid rule: {key}')
    return kit


def save_kit(name, source):
    # Resolve inherited block tokens and channel pins/presets for standalone reuse.
    channel = channels.load_or_none(source.channel_id) if isinstance(source, Project) else None
    presets = deepcopy((channel.block_presets if channel else []) + source.block_presets)
    kit = _validate(dict(name=name, default_kind=source.style.format,
                         look={k: deepcopy(getattr(source.style, k)) for k in LOOK_FIELDS},
                         block_theme=block_theme.values(source if isinstance(source, Project) else None,
                                                        source if isinstance(source, Channel) else channel),
                         blocks=dict(pins=list(dict.fromkeys((channel.blocks if channel else []) + source.blocks)),
                                     presets=presets), rules=source.style_kit.get('rules', {})))
    kit.update(id='sk' + uuid.uuid4().hex, builtin=False)
    with _LOCK:
        _write(_read() + [kit])
    return deepcopy(kit)


def apply_kit(target, kit, *, dry_run=False):
    """Return the same preview on dry run and apply; paragraph data is read only."""
    if isinstance(kit, str):
        kit = get(kit)
    trial = deepcopy(target)
    legacy = kit['id'].startswith('format:')
    if legacy:
        _, cid, index = kit['id'].split(':')
        channel = channels.load(cid)
        saved = channel.formats[int(index)]
        # Use Home's implementation to retain its full style/frame/slate semantics.
        snapshot = new_project('', channel=channel, format_name=saved['name'])
        for key in ('style', 'frame', 'intro', 'outro'):
            setattr(trial, key, deepcopy(getattr(snapshot, key)))
        if isinstance(trial, Project):
            trial.format_look = deepcopy(snapshot.format_look)
    else:
        clean = _validate(kit)
        trial.style.format = clean['default_kind']
        for key, value in clean['look'].items():
            setattr(trial.style, key, deepcopy(value))
        trial.style.block_theme = deepcopy(clean['block_theme'])
        trial.blocks = list(dict.fromkeys(trial.blocks + clean['blocks']['pins']))
        for preset in clean['blocks']['presets']:
            content = {k: v for k, v in preset.items() if k != 'id'}
            if not any({k: v for k, v in p.items() if k != 'id'} == content for p in trial.block_presets):
                # A stable new id avoids collisions with existing preset provenance.
                ident = hashlib.sha256(json.dumps([kit['id'], preset['id']], sort_keys=True).encode()).hexdigest()
                trial.block_presets.append(dict(deepcopy(preset), id=ident))
    trial.style_kit = deepcopy(kit)
    slides = target.slides if isinstance(target, Project) else []
    following = [s for run in group_slides(slides, trial.style.picture_every)
                 if not run[0].kind and not run[0].on_camera and not (run[0].cues or {}).get('blocks')
                 for s in run]
    kind = trial.style.format
    ready = (sum(bool(s.board_lead or s.board_points) for s in following) if kind == 'board'
             else sum(bool((s.cues or {}).get(kind)) for s in following) if kind in kinds.CUTS
             else sum(bool(s.shot) for s in following) if kind == 'stage'
             else sum(bool(s.custom_html or s.custom.get('elements')) for s in following) if kind.startswith('custom:')
             else sum(bool(s.chosen_id) for s in following))
    before, after = target.to_dict(), trial.to_dict()
    summary = dict(kit_id=kit['id'], default_kind=kind, follows_default=len(following),
                   kept=len(slides)-len(following), needs=kit['needs'], ready=ready, total=len(following),
                   changes={k: dict(before=before.get(k), after=v) for k, v in after.items()
                            if k in target.__dataclass_fields__ and before.get(k) != v})
    def count(n, word):
        return f"{n} {word}{'' if n == 1 else 's'}"
    summary['message'] = (f"{count(len(following), 'paragraph')} {'follows' if len(following) == 1 else 'follow'} "
                          f"the default and will become {kit['name']}; "
                          f"{summary['kept']} set by hand or supplied by camera/blocks stay as they are; "
                          f"{kit['name']} needs {kit['needs'] or 'pictures'}: {ready} of {len(following)} ready")
    if not dry_run:
        for key in summary['changes']:
            setattr(target, key, deepcopy(getattr(trial, key)))
    return summary


def change(ident, name=None):
    with _LOCK:
        items = _read()
        kit = next((k for k in items if k['id'] == ident), None)
        if kit is None:
            raise HTTPException(404, 'Writable user kit not found')
        if name is None:
            items.remove(kit)
        else:
            if not isinstance(name, str) or not name.strip() or len(name) > 120:
                raise ValueError('Name must be 1–120 characters')
            kit['name'] = name.strip()
        _write(items)
        return deepcopy(kit)


def export_bundle(ident):
    kit = get(ident)
    if kit.get('readonly'):
        raise ValueError('Save an adapted style as a kit before exporting')
    return dict(corkbored_style_kit=1, kit={k: v for k, v in kit.items() if k not in ('id', 'builtin')})


def import_bundle(payload):
    if payload.get('corkbored_style_kit') != 1 or not isinstance(payload.get('kit'), dict):
        raise ValueError('Unsupported style kit bundle')
    kit = _validate(payload['kit'])
    kit.update(id='sk' + uuid.uuid4().hex, builtin=False)
    with _LOCK:
        _write(_read() + [kit])
    return kit


def register(app):
    def checked(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get('/api/style-kits')
    def listing():
        return list_kits()

    @app.get('/api/style-kits/{kit_id}/poster')
    def poster(kit_id: str):
        from .style_previews import preview
        return preview(kit_id, 'poster')

    @app.get('/api/style-kits/{kit_id}/motion')
    def motion(kit_id: str):
        from .style_previews import preview
        return preview(kit_id, 'motion')

    @app.post('/api/style-kits/import')
    def importing(payload: dict = Body(...)):
        return checked(import_bundle, payload)

    @app.post('/api/style-kits')
    def saving(payload: dict = Body(...)):
        if payload.get('owner') not in ('channels', 'projects'):
            raise HTTPException(400, 'Owner must be channels or projects')
        source = block_presets.load(payload['owner'], payload.get('id', ''))
        return checked(save_kit, payload.get('name'), source)

    @app.get('/api/style-kits/{kit_id}/export')
    def exporting(kit_id: str):
        return checked(export_bundle, kit_id)

    @app.patch('/api/style-kits/{kit_id}')
    def renaming(kit_id: str, payload: dict = Body(...)):
        if payload.get('name') is None:
            raise HTTPException(400, 'Name is required')
        return checked(change, kit_id, payload['name'])

    @app.delete('/api/style-kits/{kit_id}')
    def deleting(kit_id: str):
        return change(kit_id)

    @app.post('/api/{owner}/{ident}/style-kit')
    def applying(owner: Literal['channels', 'projects'], ident: str, payload: dict = Body(...)):
        if type(payload.get('dry_run', False)) is not bool:
            raise HTTPException(400, 'dry_run must be a boolean')
        kit = get(payload.get('kit_id'))
        service = block_presets.backend(owner)
        with service.lock_for(ident):
            target = block_presets.load(owner, ident)
            result = checked(apply_kit, target, kit, dry_run=payload.get('dry_run', False))
            if not payload.get('dry_run', False):
                service.save(target)
            return result

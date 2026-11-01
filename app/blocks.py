"""Local Corkbored blocks. Discovery and validation never start a browser."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote

import jinja2

from . import paths, scenes
from .config import STATIC_DIR

BUILTIN_DIR = STATIC_DIR / 'blocks'
USER_DIR = paths.data_root() / 'blocks'
PACKS_DIR = paths.data_root() / 'packs'
SCHEMA = paths.resource_root() / 'docs/blocks/block.schema.json'


def _check(value, rule, label):
    """Validate the JSON Schema vocabulary used by block.schema.json (no deps)."""
    types = {'object': dict, 'array': list, 'string': str, 'number': (int, float), 'integer': int}
    kind = rule.get('type')
    if kind and (not isinstance(value, types[kind]) or
                 kind in ('number', 'integer') and
                 (isinstance(value, bool) or not math.isfinite(value))):
        raise ValueError(f'{label}: expected {kind}')
    if 'enum' in rule and value not in rule['enum']:
        raise ValueError(f'{label}: expected one of {rule["enum"]}')
    for key, fails in [('minimum', lambda n: value < n), ('maximum', lambda n: value > n),
                       ('exclusiveMinimum', lambda n: value <= n),
                       ('minLength', lambda n: len(value) < n), ('maxLength', lambda n: len(value) > n),
                       ('minItems', lambda n: len(value) < n), ('minProperties', lambda n: len(value) < n)]:
        if key in rule and fails(rule[key]):
            raise ValueError(f'{label}: violates {key} {rule[key]}')
    if 'pattern' in rule and not re.search(rule['pattern'], value):
        raise ValueError(f'{label}: invalid format')
    if isinstance(value, dict):
        for key in rule.get('required', []):
            if key not in value:
                raise ValueError(f'{label}: missing {key}')
        for key, item in value.items():
            child = rule.get('properties', {}).get(key, rule.get('additionalProperties', {}))
            if child is False:
                raise ValueError(f'{label}: unknown {key}')
            _check(item, child, f'{label}.{key}')
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check(item, rule.get('items', {}), f'{label}[{i}]')


def _file(root, name):
    target = (root / name).resolve()
    if Path(name).is_absolute() or not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f'block file outside folder or missing: {name}')
    return target


def validate_vars(meta, values):
    _check(values, {'type': 'object'}, 'variables')
    unknown = values.keys() - meta['variables'].keys()
    if unknown:
        raise ValueError(f'unknown block variables: {sorted(unknown)}')
    result = {}
    for key, spec in meta['variables'].items():
        value = values.get(key, spec['default'])
        kind = spec['type']
        rule = {'type': 'number' if kind == 'number' else 'array' if kind == 'table' else 'string'}
        if kind == 'text':
            if 'max_length' not in spec:
                raise ValueError(f'{key}: text requires max_length')
            rule['maxLength'] = spec['max_length']
        if kind == 'number':
            rule.update({k: spec[s] for k, s in [('minimum', 'min'), ('maximum', 'max')] if s in spec})
        if kind == 'enum':
            if not spec.get('choices'):
                raise ValueError(f'{key}: enum requires choices')
            rule['enum'] = spec['choices']
        _check(value, rule, key)
        if kind == 'colour' and not re.fullmatch(r'#[0-9a-fA-F]{6}|var\(--[a-z][a-z0-9-]*\)', value):
            raise ValueError(f'{key}: expected hex colour or CSS colour token')
        if kind in ('image', 'clip') and value and (not value.startswith(('/static/', '/scene/')) or
                '..' in unquote(value) or '\\' in unquote(value)):
            raise ValueError(f'{key}: expected local /static/ or /scene/ reference')
        if kind == 'table' and any(not isinstance(row, dict) or any(
                not isinstance(v, (str, int, float, bool, type(None))) or
                isinstance(v, float) and not math.isfinite(v) for v in row.values()) for row in value):
            raise ValueError(f'{key}: expected rows of scalar cells')
        result[key] = value
    return result


def discover():
    """Fresh scan; namespaced ids cannot shadow built-ins. Invalid blocks fail closed."""
    candidates = [(p.parent, '') for p in sorted(BUILTIN_DIR.glob('*/block.json'))]
    candidates += [(p.parent, 'user/') for p in sorted(USER_DIR.glob('*/block.json'))]
    for manifest in sorted(PACKS_DIR.glob('*/pack.json')):
        pack = json.loads(manifest.read_text())
        if pack.get('id') != manifest.parent.name or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,47}', pack['id']):
            raise ValueError(f'invalid pack id: {manifest}')
        candidates += [(p.parent, pack['id'] + '/') for p in sorted((manifest.parent / 'blocks').glob('*/block.json'))]
    result = {}
    schema = json.loads(SCHEMA.read_text())
    for root, prefix in candidates:
        meta = json.loads((root / 'block.json').read_text())
        _check(meta, schema, str(root / 'block.json'))
        if meta['id'] != root.name:
            raise ValueError(f'block id must match folder: {root}')
        validate_vars(meta, {})
        rule = meta['duration']
        required = {'fixed': ['seconds'], 'range': ['min', 'max'], 'from_words': ['min', 'max', 'variable', 'words_per_minute']}[rule['mode']]
        if any(k not in rule for k in required) or rule.get('min', 0) > rule.get('max', math.inf):
            raise ValueError(f'{meta["id"]}: invalid duration rule')
        if rule['mode'] == 'from_words' and meta['variables'].get(rule['variable'], {}).get('type') != 'text':
            raise ValueError('from_words requires a text variable')
        for name in ['block.html', *meta['aspects'].values(), *meta['assets']]:
            _file(root, name)
        ref = prefix + meta['id']
        if ref in result:
            raise ValueError(f'duplicate block id: {ref}')
        result[ref] = dict(meta=meta, root=root)
    return result


class Loader(jinja2.BaseLoader):
    def get_source(self, environment, template):
        if not template.startswith('_blocks/'):
            raise jinja2.TemplateNotFound(template)
        # Variants and includes use the same block namespace; nested paths are
        # resolved by the longest matching registry id.
        for key, block in discover().items():
            prefix = '_blocks/' + key + '/'
            if template.startswith(prefix):
                path = _file(block['root'], template[len(prefix):])
                source = path.read_text()
                return source, str(path), lambda: False
        raise jinja2.TemplateNotFound(template)


def prepare(block_id, values=None, aspect='16:9', seconds=None, *, context=None):
    block = discover().get(block_id)
    if block is None:
        raise ValueError(f'unknown block: {block_id}')
    meta, root = block['meta'], block['root']
    values = validate_vars(meta, values or {})
    if aspect not in meta['aspects']:
        raise ValueError(f'{block_id}: unsupported aspect {aspect}')
    rule = meta['duration']
    # A range's minimum is a limit, not a sensible length to preview at.
    default = rule.get('seconds', rule.get('default', min(rule.get('max', math.inf), max(rule.get('min', 5), 5.0))))
    if rule['mode'] == 'from_words':
        default = max(rule['min'], min(rule['max'], len(values[rule['variable']].split()) * 60 / rule['words_per_minute']))
    seconds = default if seconds is None else seconds
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0 or (
            rule['mode'] == 'fixed' and seconds != rule['seconds']) or not rule.get('min', 0) <= seconds <= rule.get('max', math.inf):
        raise ValueError(f'{block_id}: duration violates {rule}')
    ctx = scenes.context_base() if context is None else dict(context)
    ctx['vars'] = {**ctx.get('vars', {}), **values}
    # Authored defaults apply to standalone discovery/preview only. A supplied
    # scene context carries the channel's resolved colours and takes priority.
    if context is None:
        ctx['vars'].update(meta.get('default_colors', {}))
    ctx['safe_areas'] = meta['safe_areas']
    ctx.update(width={'16:9':1920, '9:16':1080, '1:1':1080}[aspect],
               height={'16:9':1080, '9:16':1920, '1:1':1080}[aspect], duration=seconds,
               block_assets_root=str(root.resolve()))
    if meta['kind'] in ('intro', 'outro'):
        from dataclasses import asdict
        from .schema import Channel
        channel = Channel(id='', name=values.get('channel_name', 'Scene capture'))
        ctx.setdefault('card', asdict(getattr(channel, meta['kind'])))
        ctx.setdefault('portrait_url', '')
        ctx.setdefault('plates', [])
        ctx.setdefault('cta', 'Watch next')
    if meta['kind'] != 'sponsor':
        entries = [(token, word) for word in (ctx.get('take') or {}).get('words', [])
                   for token in re.findall(r'\w+', word.get('w', '').casefold())]
        ctx['beats'], ctx['beat_sources'] = {}, {}
        for name, phrase in meta['beats'].items():
            tokens = re.findall(r'\w+', phrase.casefold())
            for i in range(len(entries) - len(tokens) + 1):
                if tokens and [e[0] for e in entries[i:i + len(tokens)]] == tokens:
                    word = entries[i][1]
                    start = word.get('start')
                    if isinstance(start, (int, float)) and math.isfinite(start) and 0 <= start < seconds:
                        ctx['beats'][name] = start
                        ctx['beat_sources'][name] = word.get('src', 'est')
                    break
    if meta['kind'] == 'sponsor':
        from .sponsors import scene_context
        ctx.update(scene_context(ctx))
    template = f'_blocks/{block_id}/{meta["aspects"][aspect]}'
    # Hash local assets as well as templates; previews/clips invalidate on edits.
    fingerprint = hashlib.sha1()
    for path in sorted(root.rglob('*')):
        if path.is_file():
            _file(root, str(path.relative_to(root)))
            fingerprint.update(str(path.relative_to(root)).encode() + path.read_bytes())
    ctx['block_version'] = fingerprint.hexdigest()
    return template, ctx


def render(block_id, vars=None, aspect='16:9', seconds=None, *, project=None, context=None):
    template, ctx = prepare(block_id, vars, aspect, seconds, context=context)
    return scenes.ensure_clip(project if project is not None else paths.data_root() / '.cache/blocks',
                              template, ctx, seconds=ctx['duration'],
                              size=(ctx['width'], ctx['height']), fps=ctx.get('fps', 30))

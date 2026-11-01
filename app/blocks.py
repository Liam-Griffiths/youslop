"""Local Corkbored blocks. Discovery and validation never start a browser."""
from __future__ import annotations

import csv
from datetime import date
import hashlib
import io
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import jinja2

from . import core_channel_blocks, core_data_blocks, core_explainer_blocks, paths, scene_builder, scenes
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


def parse_csv(text, columns):
    """Header keys or labels map to declared columns; validation handles cells."""
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        header = next(reader)
        aliases = {name: c['key'] for c in columns for name in (c['key'], c.get('label', c['key']))}
        keys = [aliases.get(h.strip()) for h in header]
        if None in keys or len(set(keys)) != len(keys) or set(keys) != {c['key'] for c in columns}:
            raise ValueError('CSV: headers must name each column once (key or label)')
        rows = []
        for i, cells in enumerate(reader, 1):
            if not cells:
                continue
            if len(cells) != len(keys):
                raise ValueError(f'CSV row {i}: expected {len(keys)} columns')
            rows.append(dict(zip(keys, (c.strip() for c in cells))))
        return rows
    except (StopIteration, csv.Error) as exc:
        raise ValueError(f'CSV: invalid table: {exc}') from exc


def _table(value, spec, key, unit):
    columns = spec.get('columns', [])
    if len({c['key'] for c in columns}) != len(columns):
        raise ValueError(f'{key}: duplicate column keys')
    if isinstance(value, str) and columns:
        value = parse_csv(value, columns)
    _check(value, {'type': 'array'}, key)
    result = []
    for i, row in enumerate(value, 1):
        label = f'{key} row {i}'
        if not isinstance(row, dict):
            raise ValueError(f'{label}: expected rows of scalar cells')
        row = dict(row)
        for col in columns:
            name, kind = col['key'], col['type']
            cell = row.get(name)
            where = f'{label} column {name}'
            if kind == 'number' and isinstance(cell, str):
                cell = cell.strip()
                suffix = col.get('unit', unit)
                _check(suffix, {'type': 'string'}, f'{where} unit')
                if suffix and cell.casefold().endswith(suffix.casefold()):
                    cell = cell[:-len(suffix)].strip()
                cell = cell.removesuffix('%').strip().replace(',', '')
                try:
                    cell = float(cell)
                except ValueError as exc:
                    raise ValueError(f'{where}: expected number') from exc
            _check(cell, {'type': 'number' if kind == 'number' else 'string'}, where)
            if kind == 'date':
                try:
                    if not re.fullmatch(r'\d{4}', cell):
                        date.fromisoformat(cell)
                    elif not 1 <= int(cell) <= 9999:
                        raise ValueError()
                except ValueError as exc:
                    raise ValueError(f'{where}: expected ISO date or year') from exc
            row[name] = cell
        for name, cell in row.items():
            if not isinstance(cell, (str, int, float, bool, type(None))) or isinstance(cell, float) and not math.isfinite(cell):
                raise ValueError(f'{label} column {name}: expected scalar cell')
        result.append(row)
    return result


def validate_vars(meta, values):
    _check(values, {'type': 'object'}, 'variables')
    unknown = values.keys() - meta['variables'].keys()
    if unknown:
        raise ValueError(f'unknown block variables: {sorted(unknown)}')
    result = {}
    for key, spec in meta['variables'].items():
        value = values.get(key, spec['default'])
        kind = spec['type']
        if kind == 'table':
            value = _table(value, spec, key, values.get('unit', meta['variables'].get('unit', {}).get('default', '')))
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
        result[key] = value
    return result


def source_line(research, narration):
    """Research keeps sourced facts; use only an existing attribution."""
    facts = [f for f in research.get('facts', []) if f.get('source') or f.get('url')]
    if not facts:
        return ''
    cited = next((f for f in facts if any(str(f[k]) in narration for k in ('url', 'source') if f.get(k))), None)
    citation = re.search(r'\[(\d+)\]', narration)
    if cited is None and citation:
        original = research.get('facts', [])
        n = int(citation[1]) - 1
        if 0 <= n < len(original) and original[n] in facts:
            cited = original[n]
    fact = cited or facts[0]
    return 'Source: ' + (fact.get('source') or urlsplit(fact['url']).netloc)


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
    if block_id in core_data_blocks.IDS and not values.get('source') and context:
        values['source'] = source_line(context.get('research', {}), context.get('narration', ''))
        limit = meta['variables']['source']['max_length']
        if len(values['source']) > limit:
            values['source'] = values['source'][:limit-1] + '…'
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
    ctx['budget'] = meta.get('budget', 0.1)
    ctx.update(width={'16:9':1920, '9:16':1080, '1:1':1080}[aspect],
               height={'16:9':1080, '9:16':1920, '1:1':1080}[aspect], duration=seconds,
               block_assets_root=str(root.resolve()))
    if block_id in core_data_blocks.IDS:
        ctx['data'] = core_data_blocks.layout(block_id, values, ctx['width'], ctx['height'], seconds)
        # World-screen grounds use the palette; keep the block/channel token.
        ctx['palette'] = {**ctx['palette'], 'ground': ctx['vars']['bg']}
    if block_id in core_explainer_blocks.IDS:
        ctx['explain'] = core_explainer_blocks.layout(block_id, values, ctx)
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
    if block_id in core_channel_blocks.IDS:
        ctx['channel_block'] = core_channel_blocks.layout(block_id, values, ctx)
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
    if hasattr(project, 'research'):
        context = {**(scenes.context_base(project) if context is None else context), 'research': project.research}
        project = paths.data_root() / 'projects' / project.id
    template, ctx = prepare(block_id, vars, aspect, seconds, context=context)
    owner = project if project is not None else paths.data_root() / '.cache/blocks'
    size, fps = (ctx['width'], ctx['height']), ctx.get('fps', 30)
    _, html, ctx = scenes._prepare(owner, template, ctx, ctx['duration'], size, fps,
                                  ('block-builder-v1', scene_builder.MOTIONS))
    out = html.with_suffix('.mp4')
    if not out.exists():
        scene_builder.render(owner, template, ctx, out, seconds=ctx['duration'],
                             size=size, fps=fps, crf=18)
    return out

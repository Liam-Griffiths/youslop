"""Read-only browse metadata and explicitly requested local poster batches."""
import hashlib
import os
from pathlib import Path
import threading

from . import blocks, channels, jobs, packs, paths, scenes, stage

_LOCK = threading.RLock()
_REGISTRY = (None, {})
_POSTER_JOB = None
_SIGNATURES = {}


def registry():
    global _REGISTRY
    roots = (blocks.BUILTIN_DIR, blocks.USER_DIR, packs.BUILTIN_DIR, packs.PACKS_DIR)
    stamp = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size)
                  for root in roots for p in sorted(root.rglob('*')) if p.is_file())
    with _LOCK:
        if stamp != _REGISTRY[0]:
            _REGISTRY = (stamp, blocks.discover())
        return _REGISTRY[1]


def signature(item):
    digest = hashlib.sha256(b'block-posters-v1')
    # Include runtime/templates/fonts as well as authored defaults and assets.
    roots = [item['root'], scenes.SCENE_DIR, paths.resource_root() / 'resources/fonts']
    with _LOCK:
        for root in roots:
            files = [p for p in sorted(root.rglob('*')) if p.is_file()]
            stamp = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
            cached = _SIGNATURES.get(str(root))
            if not cached or cached[0] != stamp:
                content = hashlib.sha256()
                for path in files:
                    content.update(str(path.relative_to(root)).encode() + path.read_bytes())
                cached = (stamp, content.digest())
                _SIGNATURES[str(root)] = cached
            digest.update(cached[1])
    return digest.hexdigest()[:24]


def poster_path(ref, aspect, item=None):
    item = item or registry().get(ref)
    if item is None:
        raise ValueError('Unknown block')
    if aspect not in item['meta']['aspects']:
        raise ValueError('Unsupported aspect')
    return paths.data_root() / '.cache/blocks/posters' / ref / f'{signature(item)}-{aspect.replace(":", "x")}.png'


def browse(q='', category='', aspect='', source='', channel='', data=False):
    pinned = {}
    for row in channels.list_channels():
        for ref in channels.load(row['id']).blocks:
            pinned.setdefault(ref, []).append(row['id'])
    result = []
    for ref, item in registry().items():
        meta = item['meta']
        if meta['kind'] == 'test':  # Internal fixtures, not for creators.
            continue
        origin = 'mine' if ref.startswith('user/') else item.get('pack', 'built-in')
        row = dict(id=ref, ref=ref, name=meta['name'], description=meta.get('description', ''),
                   kind=meta['kind'], category=meta.get('category', meta['kind']),
                   tags=meta.get('tags', []), aspects=list(meta['aspects']), duration=meta['duration'],
                   source=origin, licence=meta['licence'], origin=meta.get('origin'),
                   check_status='Metadata valid; browser check not recorded',
                   channels=pinned.get(ref, []), variables=meta['variables'],
                   posters={a: f'/api/blocks/{ref}/poster?aspect={a}'
                            for a in meta['aspects'] if poster_path(ref, a, item).exists()},
                   works_with_data=any(v['type'] == 'table' for v in meta['variables'].values()))
        haystack = ' '.join([row['name'], row['description'], *row['tags'], *row['variables']]).casefold()
        if (q.casefold() not in haystack or category and category != row['category'] or
                aspect and aspect not in row['aspects'] or channel and channel not in row['channels'] or
                data and not row['works_with_data'] or source and
                not (source == origin or source == 'packs' and ref.startswith('pack/'))):
            continue
        result.append(row)
    return result


def make_posters(progress):
    items, outputs = [], {}
    owner = paths.data_root() / '.cache/blocks'
    for ref, block in registry().items():
        for aspect in block['meta']['aspects']:
            out = poster_path(ref, aspect, block)
            if out.exists():
                continue
            progress(f'Preparing {ref} · {aspect}')
            template, ctx = blocks.prepare(ref, aspect=aspect, _block=block)
            _, html, ctx = scenes._prepare(owner, template, ctx, ctx['duration'],
                                           (ctx['width'], ctx['height']), 30)
            clip = str(len(items))
            outputs[clip] = out
            items.append(dict(clip=clip, url_path=f'/scene/{{token}}/{html.name}',
                              W=ctx['width'], H=ctx['height'],
                              size=(ctx['width']//4, ctx['height']//4),
                              t=ctx['duration']/2 if block['meta']['kind'] == 'chapter' else max(0, ctx['duration'] - .1),
                              assets_root=str(block['root'])))

    def checkpoint(cdp, session, item, t):
        progress(f'Capturing {outputs[item["clip"]].parent.name}')

    def publish(clip, png):
        out = outputs[clip]
        out.parent.mkdir(parents=True, exist_ok=True)
        temporary = out.with_suffix('.part')
        temporary.write_bytes(png)
        os.replace(temporary, out)

    if items:
        # One browser/session for the entire batch, including pack/user assets.
        stage.capture_stills(items, owner / 'scenes', scene_probe=checkpoint, on_still=publish)
    return {'posters': len(items)}


def start_posters():
    global _POSTER_JOB
    with _LOCK:
        if os.environ.get('CORKBORED_BLOCK_POSTERS') == 'off':
            return {'job': None}
        current = jobs.get(_POSTER_JOB) if _POSTER_JOB else None
        if current and current['state'] == 'running':
            return {'job': _POSTER_JOB}
        if not any(not poster_path(ref, aspect, item).exists()
                   for ref, item in registry().items() for aspect in item['meta']['aspects']):
            return {'job': None}
        _POSTER_JOB = jobs.start('block posters', '', make_posters, cancellable=True)
        return {'job': _POSTER_JOB}

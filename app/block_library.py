"""Read-only browse metadata and explicitly requested local poster batches."""
import hashlib
import os
from pathlib import Path
import threading
import tempfile
import shutil
import uuid

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


def browse(q='', category='', aspect='', source='', channel='', data=False, overlay=False):
    prefs = preferences()
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
                   overlay=meta.get('overlay'), source=origin, licence=meta['licence'], origin=meta.get('origin'),
                   check_status='Metadata valid; browser check not recorded',
                   channels=pinned.get(ref, []), variables=meta['variables'],
                   favourite=ref in prefs['favourites'], recent=prefs['recent'].get(ref, 0),
                   posters={a: f'/api/blocks/{ref}/poster?aspect={a}'
                            for a in meta['aspects'] if poster_path(ref, a, item).exists()},
                   works_with_data=any(v['type'] == 'table' for v in meta['variables'].values()),
                   forkable=forkable(ref, item))
        haystack = ' '.join([row['name'], row['description'], *row['tags'], *row['variables']]).casefold()
        if (q.casefold() not in haystack or category and category != row['category'] or
                aspect and aspect not in row['aspects'] or channel and channel not in row['channels'] or
                data and not row['works_with_data'] or overlay and not row['overlay'] or source and
                not (source == origin or source == 'packs' and ref.startswith('pack/'))):
            continue
        result.append(row)
    return result


def preferences(ref=None, *, favourite=None, used=False):
    """App-wide preferences; serialize read/modify/replace within this process."""
    import json
    import time
    path = paths.data_root() / 'blocks_prefs.json'
    with _LOCK:
        prefs = json.loads(path.read_text()) if path.exists() else {}
        prefs = dict(favourites=prefs.get('favourites', []), recent=prefs.get('recent', {}))
        if ref is None:
            return prefs
        if ref not in registry():
            raise ValueError('Unknown block')
        if favourite is not None:
            if not isinstance(favourite, bool):
                raise ValueError('Favourite must be a boolean')
            prefs['favourites'] = sorted((set(prefs['favourites']) - {ref}) | ({ref} if favourite else set()))
        if used:
            prefs['recent'][ref] = time.time()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(prefs, stream)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return prefs


def duplicate(ref):
    """Copy only into a fresh user folder, and keep it only if check passes."""
    import json
    from . import block_authoring
    item = registry().get(ref)
    if item is None:
        raise ValueError('Unknown block')
    blocks.USER_DIR.mkdir(parents=True, exist_ok=True)
    target = blocks.USER_DIR / (item['meta']['id'] + '-' + uuid.uuid4().hex[:12])
    target.mkdir(exist_ok=False)
    try:
        # Reject escaping links before copying any source content.
        for path in item['root'].rglob('*'):
            if path.is_file() or path.is_symlink():
                blocks._file(item['root'], str(path.relative_to(item['root'])))
        shutil.copytree(item['root'], target, dirs_exist_ok=True)
        meta = json.loads((target / 'block.json').read_text())
        meta.update(id=target.name, origin={**(meta.get('origin') or {}), 'forked_from':ref})
        (target / 'block.json').write_text(json.dumps(meta, indent=2) + '\n')
        errors = block_authoring.check('user/' + target.name)
        if errors:
            raise ValueError('; '.join(errors))
        return {'id':'user/' + target.name}
    except Exception:
        shutil.rmtree(target)
        raise


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
        with _RENDER_LOCK:
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


# Motion and trial captures share a gate, including the poster batch.
_RENDER_LOCK = threading.Lock()
_REQUESTS = {}
_PREVIEW_RENDERS = 0


def preview(ref, values, aspect, kind, session, sequence):
    """Explicit scratch preview. Superseded queued requests never capture."""
    global _PREVIEW_RENDERS
    import json
    import re
    if kind not in ('motion', 'trial') or not isinstance(session, str) or not re.fullmatch(r'[\w-]{1,80}', session):
        raise ValueError('Invalid preview request')
    if type(sequence) is not int or sequence < 0:
        raise ValueError('Invalid preview sequence')
    item = registry().get(ref)
    if item is None:
        raise ValueError('Unknown block')
    values = blocks.validate_vars(item['meta'], values)
    template, ctx = blocks.prepare(ref, values, aspect, _block=item)
    if os.environ.get('CORKBORED_BLOCK_POSTERS') == 'off':
        return {'disabled': True}
    with _LOCK:
        if sequence <= _REQUESTS.get(session, -1):
            return {'stale': True}
        if len(_REQUESTS) >= 256 and session not in _REQUESTS:
            _REQUESTS.pop(next(iter(_REQUESTS)))
        _REQUESTS[session] = sequence
    key = hashlib.sha256(json.dumps([signature(item), ctx.get('block_version'), values, aspect, kind], sort_keys=True).encode()).hexdigest()
    out = preview_file(key, kind)
    with _RENDER_LOCK:
        if _REQUESTS.get(session) != sequence:
            return {'stale': True}
        if not out.exists():
            _PREVIEW_RENDERS += 1
            out.parent.mkdir(parents=True, exist_ok=True)
            size = (ctx['width']//4, ctx['height']//4)
            owner = paths.data_root() / '.cache/blocks'
            if kind == 'motion':
                clip = blocks.render(ref, values, aspect, size=size, max_seconds=6,
                                     context={**ctx, 'library_signature': signature(item)})
                data = clip.read_bytes()
            else:
                ctx['library_signature'] = signature(item)
                t = ctx['duration']/2 if item['meta']['kind'] == 'chapter' else max(0, ctx['duration']-.1)
                data = scenes.capture(owner, template, ctx, t=t, size=size)
            temporary = out.with_suffix('.part')
            temporary.write_bytes(data)
            os.replace(temporary, out)
        if _REQUESTS.get(session) != sequence:
            return {'stale': True}
    return {'url': f'/api/block-previews/{key}/{kind}', 'values': values}


def preview_file(key, kind):
    import re
    if not re.fullmatch(r'[a-f0-9]{64}', key) or kind not in ('motion', 'trial'):
        raise ValueError('Invalid preview file')
    return paths.data_root() / '.cache/blocks/previews' / (key + ('.mp4' if kind == 'motion' else '.png'))


_FORKABLE = {}


def forkable(ref, item):
    """Whether a copy would pass the user-block sandbox (cached per signature).

    Built-in blocks use trusted template features (other bases, extra blocks,
    macros), so their copies fail the sandbox that user and pack blocks render in.
    """
    from . import block_sandbox
    key = (ref, signature(item))
    if key not in _FORKABLE:
        try:
            for name in item['meta']['aspects'].values():
                block_sandbox.parse((item['root'] / name).read_text())
            _FORKABLE[key] = True
        except Exception:
            _FORKABLE[key] = False
    return _FORKABLE[key]

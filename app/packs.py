"""Read-only content packs. Manifest/security errors disable a pack; bad items stay isolated."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import stat
import shutil
import tempfile
import uuid
import zipfile
import threading

import jinja2

from . import paths

PACKS_DIR = paths.data_root() / 'packs'
BUILTIN_DIR = paths.resource_root() / 'packs'
STAGED = ContextVar('staged_packs', default=())
_CACHE = {}
_LOCK = threading.RLock()
_ID = r'[a-z0-9][a-z0-9-]{1,47}'
_SUFFIXES = {'themes': {'.json'}, 'music': {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'},
             'fonts': {'.woff2', '.ttf', '.otf'}}


def _json(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path.name}: expected object')
    return value


@dataclass
class Pack:
    id: str
    name: str = ''
    version: str = ''
    author: str = ''
    licence: str = ''
    licence_url: str = ''
    description: str = ''
    path: Path = Path('.')
    problems: list = field(default_factory=list)
    item_problems: dict = field(default_factory=dict)
    items: dict = field(default_factory=dict, repr=False)

    def themes(self): return self.items.get('themes', []) if not self.problems else []
    def blocks(self): return self.items.get('blocks', []) if not self.problems else []
    def music(self): return self.items.get('music', []) if not self.problems else []
    def models(self): return self.items.get('models', []) if not self.problems else []
    def fonts(self): return self.items.get('fonts', []) if not self.problems else []


def _validate(meta, root):
    problems = []
    if not re.fullmatch(_ID, str(meta.get('id', ''))) or meta.get('id') != root.name:
        problems.append('id must match the folder and pack id pattern')
    for key in ('name', 'version', 'author', 'licence'):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            problems.append(f'missing or invalid {key}')
    for key in ('licence_url', 'description', 'corkbored'):
        if key in meta and not isinstance(meta[key], str):
            problems.append(f'invalid {key}')
    for path in [root, *root.rglob('*')]:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            problems.append(f'forbidden link or special file: {path.name}')
        elif path.is_file() and (mode & 0o111 or path.suffix.lower() in
                                {'.py', '.pyc', '.js', '.mjs', '.cjs', '.exe', '.sh', '.dll', '.so'}):
            problems.append(f'forbidden code/executable: {path.name}')
    return problems


def _load(root):
    pack = Pack(id=root.name, path=root)
    try:
        meta = _json(root / 'pack.json')
        pack.problems = _validate(meta, root)
        for key in ('name', 'version', 'author', 'licence', 'licence_url', 'description'):
            setattr(pack, key, meta.get(key, ''))
        if pack.problems:
            return pack
        from . import blocks, scenes, block_sandbox, block_authoring, themes
        groups = {k: sorted((root / k).glob('*')) for k in (*_SUFFIXES, 'blocks', 'models')}
        credits = _json(root / 'music/credits.json') if (root / 'music/credits.json').exists() else {}
        for kind, entries in groups.items():
            for path in entries:
                if kind in _SUFFIXES and path.suffix.lower() not in _SUFFIXES[kind]:
                    continue
                if kind == 'music' and path.name == 'credits.json':
                    continue
                key = path.stem if kind == 'themes' else path.name
                ref = f'{pack.id}/{key}'
                item = dict(ref=ref, path=path, pack=pack.name, label=f'{key} · {pack.name}')
                try:
                    if kind in _SUFFIXES and not path.is_file():
                        raise ValueError('expected a file')
                    if kind == 'fonts' and not re.fullmatch(r'[\w-]+\.(?:ttf|otf|woff2)', key):
                        raise ValueError('invalid font filename')
                    if kind == 'themes':
                        data = _json(path)
                        base = themes.THEMES[0]
                        for name, default in base.items():
                            if name != 'key' and (name not in data or not isinstance(data[name], type(default))):
                                raise ValueError(f'theme: missing or invalid {name}')
                        for name in ('accent', 'accent2', 'ground', 'ink'):
                            if not re.fullmatch(r'#[0-9a-fA-F]{6}', data[name]):
                                raise ValueError(f'invalid colour: {name}')
                        item['value'] = {**data, 'key': ref, 'pack': pack.name,
                                         'label': f'{data["label"]} · {pack.name}'}
                    elif kind == 'blocks':
                        item['ref'] = f'pack/{ref}'
                        block = dict(meta=blocks.validate_folder(path), root=path, version=pack.version)
                        context = scenes.context_base(include_packs=False)
                        context['fonts'].update({f'pack:{pack.id}/{f.name}': f'/fonts/packs/{pack.id}/{f.name}'
                                                 for f in groups['fonts'] if f.is_file()})
                        for aspect in block['meta']['aspects']:
                            _, ctx = blocks.prepare(item['ref'], block_authoring.samples(block['meta']), aspect,
                                context=context, _block=block)
                            source = blocks._file(path, block['meta']['aspects'][aspect]).read_text()
                            html = block_sandbox.render(source, ctx)
                            errors = scenes.lint(html, asset_root=path)
                            if errors:
                                raise ValueError('; '.join(errors))
                        item['meta'] = {**block['meta'], 'name': f'{block["meta"]["name"]} · {pack.name}'}
                    elif kind == 'models':
                        data = _json(path / 'manifest.json')
                        if not data.get('confirmed') or not (path / 'model.glb').is_file():
                            raise ValueError('model requires confirmed manifest and model.glb')
                        item['value'] = {**data, 'id': ref, 'pack': pack.name, 'read_only': True,
                                         'title': f'{data.get("title", key)} · {pack.name}'}
                    elif kind == 'music':
                        credit = credits.get(path.name, {})
                        if not isinstance(credit, dict) or any(not isinstance(v, str) for v in credit.values()):
                            raise ValueError('invalid track credits')
                        item['credits'] = credit
                        item['label'] = f'{credit.get("title", key)} · {pack.name}'
                    pack.items.setdefault(kind, []).append(item)
                except (OSError, ValueError, KeyError, TypeError, jinja2.TemplateError) as exc:
                    pack.item_problems[item['ref']] = [str(exc)]
    except (OSError, ValueError, TypeError) as exc:
        pack.problems.append(str(exc))
    return pack


def scan(*, force=False):
    """Nested stat signatures catch in-place item edits as well as folder changes."""
    with _LOCK:
        result = []
        # Built-ins win id collisions; authoring contexts can inspect a local draft.
        roots = {p.name: p for directory in (PACKS_DIR, BUILTIN_DIR)
                 for p in sorted(directory.glob('*'))}
        roots.update({p.name: p for p in STAGED.get()})
        for root in sorted(roots.values(), key=lambda p: p.name):
            if root.name.startswith('.'):
                continue
            if not root.is_dir() and not root.is_symlink():
                continue
            try:
                signature = tuple((str(p.relative_to(root)), p.lstat().st_mtime_ns,
                                   p.lstat().st_size, p.lstat().st_mode)
                                  for p in [root, *sorted(root.rglob('*'))])
                cached = _CACHE.get(root)
                if force or cached is None or cached[0] != signature:
                    _CACHE[root] = (signature, _load(root))
                result.append(_CACHE[root][1])
            except OSError as exc:
                result.append(Pack(id=root.name, path=root, problems=[str(exc)]))
        return result


def resolve(ref, kind=None):
    for pack in scan():
        for group in ([kind] if kind else ('themes', 'blocks', 'music', 'models', 'fonts')):
            for item in pack.items.get(group, []) if not pack.problems else []:
                if item['ref'] == ref:
                    return item.get('value', item['path'])
    return None


def font_path(url):
    match = re.fullmatch(r'/fonts/packs/(' + _ID + r')/([\w-]+\.(?:ttf|otf|woff2))', url)
    return resolve('/'.join(match.groups()), 'fonts') if match else None


EXTENSION = '.corkboredpack'
MAX_BYTES = 2 * 1024**3
MAX_FILES = 10_000


class PackError(ValueError):
    pass


class ReplaceRequired(PackError):
    pass


def summary(pack):
    preview = pack.path / 'preview.jpg'
    return dict(id=pack.id, name=pack.name, version=pack.version, author=pack.author,
                licence=pack.licence, licence_url=pack.licence_url, description=pack.description,
                problems=pack.problems, item_problems=pack.item_problems,
                builtin=pack.path.parent.resolve() == BUILTIN_DIR.resolve(),
                preview=f'/api/packs/{pack.id}/preview' if preview.is_file() and not pack.problems else '',
                items={k: [dict(ref=i['ref'], label=i['label']) for i in v]
                       for k, v in pack.items.items()})


def _version(value):
    # Compare numeric releases, with prereleases before the corresponding release.
    match = re.fullmatch(r'(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?', value)
    if not match:
        raise PackError('Pack upgrades require numeric release versions (for example 1.2.0)')
    numbers = [int(n) for n in match[1].split('.')]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    pre = tuple((0, int(n)) if n.isdigit() else (1, n) for n in (match[2] or '').split('.'))
    return tuple(numbers), match[2] is None, pre


def _archive_old(root, version):
    old = PACKS_DIR / '.old'
    old.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[^a-zA-Z0-9._-]', '_', str(version))[:80] or 'unknown'
    target = old / f'{root.name}-{safe}'
    if target.exists():
        target = old / f'{root.name}-{safe}-{uuid.uuid4().hex[:8]}'
    root.rename(target)
    return target


def install(src, *, replace=False):
    from . import transfer
    cache = PACKS_DIR.parent / '.cache'
    cache.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='pack-', dir=cache) as temp, zipfile.ZipFile(src) as zf:
            entries = transfer.checked_members(zf, max_bytes=MAX_BYTES, max_files=MAX_FILES)
            roots = {i.filename.split('/')[0] for i in entries}
            if len(roots) != 1 or not re.fullmatch(_ID, next(iter(roots), '')):
                raise PackError('Pack archive must contain one folder named after its id')
            pid = roots.pop()
            if (BUILTIN_DIR / pid).exists():
                raise PackError("Built-in packs cannot be replaced")
            if f'{pid}/pack.json' not in zf.namelist():
                raise PackError('Pack archive has no pack.json')
            if any((i.external_attr >> 16) & 0o111 for i in entries if not i.is_dir()):
                raise PackError('Pack archive contains executable files')
            staged = Path(temp) / pid
            transfer._extract(zf, pid, staged)
            pack = _load(staged)  # includes _validate and validation of every item
            problems = pack.problems + [f'{ref}: {p}' for ref, ps in pack.item_problems.items() for p in ps]
            if problems:
                raise PackError('; '.join(problems))
            with _LOCK:
                PACKS_DIR.mkdir(parents=True, exist_ok=True)
                final = PACKS_DIR / pid
                previous = None
                if final.exists() or final.is_symlink():
                    current = _load(final)
                    if _version(pack.version) <= _version(current.version):
                        raise PackError(f'{pid} {current.version} is already installed; same or older version refused')
                    if not replace:
                        raise ReplaceRequired(f'Replace {pid} {current.version} with {pack.version}? The old pack will be kept.')
                    previous = _archive_old(final, current.version)
                try:
                    staged.rename(final)
                except OSError:
                    if previous:
                        previous.rename(final)
                    raise
                scan(force=True)
                return summary(_load(final))
    except (transfer.TransferError, zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        raise PackError(str(exc)) from exc


def _installed(pid):
    if not re.fullmatch(_ID, pid):
        raise PackError('Invalid pack id')
    if (BUILTIN_DIR / pid).exists():
        raise PackError('Built-in packs cannot be removed or changed')
    root = PACKS_DIR / pid
    if not root.exists() and not root.is_symlink():
        raise PackError('No such installed pack')
    return root


def references(value, pid):
    if isinstance(value, str):
        return value.startswith((pid + '/', 'pack/' + pid + '/', 'scene:pack/' + pid + '/', 'pack:' + pid + '/'))
    if isinstance(value, dict):
        return any(references(v, pid) for v in value.values())
    if isinstance(value, list):
        return any(references(v, pid) for v in value)
    return False


def uses(pid):
    from .config import CHANNELS_DIR, PROJECTS_DIR
    _installed(pid)
    result = dict(channels=[], projects=[])
    for kind, directory, filename in [('channels', CHANNELS_DIR, 'channel.json'),
                                       ('projects', PROJECTS_DIR, 'project.json')]:
        for path in sorted(directory.glob('*/' + filename)):
            try:
                data = _json(path)
                if references(data, pid):
                    result[kind].append(dict(id=path.parent.name,
                        name=data.get('name') or data.get('title') or data.get('idea') or path.parent.name))
            except (OSError, ValueError):
                continue
    return result


def remove(pid):
    with _LOCK:
        root = _installed(pid)
        target = _archive_old(root, _load(root).version)
        scan(force=True)
        return dict(id=pid, archived_to=str(target))


def missing_items(value):
    """Find missing pack references in persisted item fields, without inspecting prose."""
    missing = set()
    def walk(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str):
            ref = value.removeprefix('scene:').removeprefix('pack:')
            if (ref.startswith('pack/') or key in {'theme', 'music', 'model'}):
                pid = ref.removeprefix('pack/').split('/')[0]
                if '/' in ref and re.fullmatch(_ID, pid) and resolve(ref) is None:
                    missing.add(ref)
    walk(value)
    return sorted(missing)

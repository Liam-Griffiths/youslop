"""Commit-pinned, locally cached Hyperframes catalog downloads."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import time

import httpx

from .config import USER_AGENT
from .paths import data_root

CATALOG_DIR = data_root() / 'assets' / 'catalog'
RAW = 'https://raw.githubusercontent.com/heygen-com/hyperframes/'
COMMITS = 'https://api.github.com/repos/heygen-com/hyperframes/commits/main'
FOLDERS = {'hyperframes:block': 'blocks', 'hyperframes:component': 'components',
           'hyperframes:example': 'examples'}


def _name(name):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', name):
        raise ValueError('invalid catalog name')
    return name


def _get(client, url):
    response = client.get(url)
    response.raise_for_status()
    return response


def _cached(client, key, url):
    path = CATALOG_DIR / '_index' / (key + '.json')
    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text())
    value = _get(client, url).json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return value


def search(query: str) -> list[dict]:
    """Search names first; inspect matching items only. Exclude WebGPU items."""
    with httpx.Client(timeout=20, headers={'User-Agent': USER_AGENT}) as client:
        index = _cached(client, 'registry', RAW + 'main/registry/registry.json')
        words = query.lower().replace('-', ' ').split()
        result = []
        for entry in index['items']:
            name = _name(entry['name'])
            folder = FOLDERS.get(entry['type'])
            if not folder or not all(w in name.lower().replace('-', ' ') for w in words):
                continue
            item = _cached(client, name, RAW + f'main/registry/{folder}/{name}/registry-item.json')
            if 'webgpu' not in [t.lower() for t in item.get('tags', [])]:
                result.append(item)
        return result


def installed() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(CATALOG_DIR.glob('*/SOURCE.json'))]


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(name: str) -> Path:
    name = _name(name)
    dest = CATALOG_DIR / name
    if dest.exists():
        source = json.loads((dest / 'SOURCE.json').read_text())
        for rel, sha in source['sha256'].items():
            path = dest / rel
            if not path.is_file() or _hash(path) != sha:
                raise ValueError(f'modified local catalog file: {name}/{rel}')
        return dest
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=20, headers={'User-Agent': USER_AGENT}) as client:
        sha = _get(client, COMMITS).json()['sha']
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('invalid upstream commit sha')
        base = RAW + sha + '/'
        index = _get(client, base + 'registry/registry.json').json()
        entry = next((i for i in index['items'] if i['name'] == name), None)
        if entry is None or entry['type'] not in FOLDERS:
            raise ValueError(f'unknown catalog item: {name}')
        item_url = base + f"registry/{FOLDERS[entry['type']]}/{name}/"
        item = _get(client, item_url + 'registry-item.json').json()
        with tempfile.TemporaryDirectory(prefix='_fetch-', dir=CATALOG_DIR) as temporary:
            root = Path(temporary)
            for file in item['files']:
                rel = file['path']
                path = PurePosixPath(rel)
                if (not rel or path.is_absolute() or '..' in path.parts or '\\' in rel
                        or rel in ('SOURCE.json', 'LICENSE.txt')):
                    raise ValueError(f'unsafe catalog file path: {rel}')
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_get(client, item_url + rel).content)
            (root / 'LICENSE.txt').write_bytes(_get(client, base + 'LICENSE').content)
            (root / 'registry-item.json').write_text(json.dumps(item, indent=2))
            from . import scenes
            errors = []
            for path in sorted(root.rglob('*')):
                if path.suffix.lower() in ('.html', '.js', '.css'):
                    errors.extend(f'{path.relative_to(root)}: {e}' for e in
                                  scenes.lint_component(path.read_text(), path.parent))
            source = dict(name=name, commit=sha,
                          url=f'https://github.com/heygen-com/hyperframes/commit/{sha}',
                          date=datetime.now(timezone.utc).isoformat(),
                          license=item.get('license', ''), lint=errors,
                          sha256={str(p.relative_to(root)): _hash(p)
                                  for p in sorted(root.rglob('*')) if p.is_file()})
            (root / 'SOURCE.json').write_text(json.dumps(source, indent=2))
            root.rename(dest)
    return dest

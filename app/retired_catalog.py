"""Offline fallback for retired catalog mounts; never reads the old cache."""
from urllib.parse import unquote, urlsplit

from .config import STATIC_DIR


def placeholder(url):
    path = unquote(urlsplit(url).path)
    parts = path.removeprefix('/catalog/').split('/')
    if not path.startswith('/catalog/') or any(
            not part or part in {'.', '..'} or part.startswith('_') or '\\' in part
            for part in parts):
        raise ValueError(f'invalid retired catalog reference: {url}')
    return STATIC_DIR / 'scene/retired_catalog.html'


def references(value):
    """Find legacy URLs in saved slide fields without changing the project."""
    import re

    if isinstance(value, dict):
        return sorted({ref for item in value.values() for ref in references(item)})
    if isinstance(value, list):
        return sorted({ref for item in value for ref in references(item)})
    if isinstance(value, str):
        return sorted(set(re.findall(r'/catalog/[^\s\"\'<>]+', value)))
    return []

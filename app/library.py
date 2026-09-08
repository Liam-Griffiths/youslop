"""A shared library of hand-downloaded stock: your own royalty-free footage
and photos, tagged so they compete for a slide the same way an archive hit
does.

The per-slide upload (`/api/projects/{pid}/slides/{sid}/upload` in main.py)
is a dead end: the file goes straight into one slide with no metadata and no
way to find it again. This is the opposite — one shared store, searchable by
title and tags, that `media/providers.py` exposes as an ordinary provider so
it's tried first, before any archive, and never touches the network once an
asset is chosen.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import ffutil
from .config import LIBRARY_DIR
from .schema import MediaCandidate

_LOCK = threading.RLock()
_INDEX_FILE = LIBRARY_DIR / "library.json"
_FILES = LIBRARY_DIR / "files"
_THUMBS = LIBRARY_DIR / "thumbs"

_VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


@dataclass
class LibraryAsset:
    id: str
    kind: str                              # image | video
    filename: str                          # under files/
    thumb_filename: str = ""               # under thumbs/
    title: str = ""
    tags: list[str] = field(default_factory=list)
    author: str = ""
    license: str = ""
    source_page: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    added_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LibraryAsset":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ------------------------------------------------------------------- index
def _load_index() -> list[LibraryAsset]:
    if not _INDEX_FILE.exists():
        return []
    try:
        raw = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [LibraryAsset.from_dict(r) for r in raw.get("assets", [])]


def _save_index(assets: list[LibraryAsset]) -> None:
    payload = json.dumps({"assets": [a.to_dict() for a in assets]},
                         indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=LIBRARY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, _INDEX_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# -------------------------------------------------------------------- CRUD
def list_all(q: str = "", kind: str = "", tag: str = "") -> list[dict]:
    """Everything in the library, newest first. For the management page."""
    q = q.strip().lower()
    tag = tag.strip().lower()
    with _LOCK:
        assets = _load_index()
    out = []
    for a in assets:
        if kind and a.kind != kind:
            continue
        if tag and tag not in [t.lower() for t in a.tags]:
            continue
        if q and q not in (a.title or "").lower() \
                and not any(q in t.lower() for t in a.tags):
            continue
        out.append(a.to_dict())
    return sorted(out, key=lambda a: a["added_at"], reverse=True)


def get(asset_id: str) -> dict | None:
    with _LOCK:
        for a in _load_index():
            if a.id == asset_id:
                return a.to_dict()
    return None


def file_path(asset_id: str) -> Path | None:
    a = get(asset_id)
    return (_FILES / a["filename"]) if a else None


def thumb_path(asset_id: str) -> Path | None:
    a = get(asset_id)
    if not a:
        return None
    if a["thumb_filename"]:
        return _THUMBS / a["thumb_filename"]
    return _FILES / a["filename"] if a["kind"] == "image" else None


def _make_thumb(src: Path, kind: str, stem: str) -> str:
    """A small JPEG preview for the picker grid. Empty string on failure."""
    out = _THUMBS / f"{stem}.jpg"
    try:
        if kind == "video":
            dur = ffutil.duration(src)
            grab_at = min(1.0, max(0.0, dur * 0.1)) if dur else 0.0
            ffutil.run(["-ss", f"{grab_at:.2f}", "-i", str(src), "-frames:v", "1",
                       "-vf", "scale=480:-1", str(out)])
        else:
            from PIL import Image
            img = Image.open(src)
            img.thumbnail((480, 480), Image.LANCZOS)
            img.convert("RGB").save(out, "JPEG", quality=82)
        return out.name
    except Exception:
        return ""


def add(data: bytes, filename: str, title: str = "", tags: list[str] | None = None,
       author: str = "", license: str = "", source_page: str = "") -> dict:
    """Save an uploaded file into the library and index it."""
    suffix = Path(filename or "asset").suffix.lower()
    kind = "video" if suffix in _VIDEO_EXT else "image"
    asset_id = _uid()
    stem = f"lib_{asset_id}"
    dest = _FILES / f"{stem}{suffix or ('.mp4' if kind == 'video' else '.jpg')}"
    dest.write_bytes(data)

    width = height = 0
    duration = 0.0
    try:
        if kind == "video":
            width, height = ffutil.dimensions(dest)
            duration = ffutil.duration(dest)
        else:
            from PIL import Image
            with Image.open(dest) as img:
                width, height = img.size
    except Exception:
        pass

    thumb_name = _make_thumb(dest, kind, stem)
    clean_tags = sorted({t.strip() for t in (tags or []) if t.strip()})

    asset = LibraryAsset(
        id=asset_id, kind=kind, filename=dest.name, thumb_filename=thumb_name,
        title=title.strip() or filename, tags=clean_tags, author=author.strip(),
        license=license.strip(), source_page=source_page.strip(),
        width=width, height=height, duration=round(duration, 2),
        added_at=time.time(),
    )
    with _LOCK:
        assets = _load_index()
        assets.append(asset)
        _save_index(assets)
    return asset.to_dict()


_EDITABLE = {"title", "tags", "author", "license", "source_page"}


def update(asset_id: str, **fields: Any) -> dict:
    with _LOCK:
        assets = _load_index()
        for a in assets:
            if a.id != asset_id:
                continue
            for k, v in fields.items():
                if k not in _EDITABLE:
                    continue
                if k == "tags":
                    v = sorted({t.strip() for t in (v or []) if t.strip()})
                elif isinstance(v, str):
                    v = v.strip()
                setattr(a, k, v)
            _save_index(assets)
            return a.to_dict()
    raise FileNotFoundError(f"No library asset {asset_id}")


def remove(asset_id: str) -> bool:
    with _LOCK:
        assets = _load_index()
        keep, gone = [], None
        for a in assets:
            if a.id == asset_id:
                gone = a
            else:
                keep.append(a)
        if gone is None:
            return False
        (_FILES / gone.filename).unlink(missing_ok=True)
        if gone.thumb_filename:
            (_THUMBS / gone.thumb_filename).unlink(missing_ok=True)
        _save_index(keep)
        return True


# ------------------------------------------------------------------ search
def _url_for(asset_id: str) -> str:
    return f"/api/library/file/{asset_id}"


def _thumb_url_for(asset_id: str, a: LibraryAsset) -> str:
    return f"/api/library/thumb/{asset_id}" if a.thumb_filename or a.kind == "image" \
        else _url_for(asset_id)


def search(query: str, kind: str, limit: int = 12) -> list[MediaCandidate]:
    """Provider-facing search: your own stock, scored like an archive hit.

    Tags count toward relevance by routing scoring through the same
    `media.base.score` every archive uses, against a candidate whose title is
    stood in for "title + tags" — the resolution/aspect bonuses come along for
    free, and a bare provider-weight bump can't surface something irrelevant.
    """
    from .media.base import score as _score, tokens as _tokens

    q_tokens = _tokens(query or "")
    with _LOCK:
        assets = [a for a in _load_index() if a.kind == kind]

    out: list[MediaCandidate] = []
    for a in assets:
        corpus = " ".join([a.title, *a.tags])
        if q_tokens and not (_tokens(corpus) & q_tokens):
            continue
        cand = MediaCandidate(
            id=f"lib{a.id}", provider="library", kind=a.kind, title=a.title,
            url=_url_for(a.id), thumb=_thumb_url_for(a.id, a),
            source_page=a.source_page, author=a.author,
            license=a.license or "your library", width=a.width, height=a.height,
            duration=a.duration, query=query, ref=a.id,
        )
        cand.score = _score(replace(cand, title=corpus), query, kind)
        out.append(cand)

    out.sort(key=lambda c: c.score, reverse=True)
    return out[:limit]

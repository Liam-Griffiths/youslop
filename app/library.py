"""A shared library of your own stock: files you upload, and whole folders
you point the app at, tagged so they compete for a slide the same way an
archive hit does.

The per-slide upload (`/api/projects/{pid}/slides/{sid}/upload` in main.py)
is a dead end: the file goes straight into one slide with no metadata and no
way to find it again. This is the opposite — one shared store, searchable by
title and tags, that `media/providers.py` exposes as an ordinary provider so
it's tried first, before any archive, and never touches the network once an
asset is chosen.

Two ways an asset gets in here. **Uploaded**: the bytes are copied into
`files/`, same as always. **Folder-linked**: `add_folder()` remembers a path
on disk, and `scan_folder()` indexes whatever is already inside it in place —
a thumbnail is generated, but the original file is never copied or moved, so
pointing this at a personal photo archive costs disk space proportional to
the thumbnails, not the archive. A later scan picks up anything new and drops
anything that has since been deleted from disk; nothing here ever writes to
or deletes from the folder itself.
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
from typing import Any, Callable

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
    # Exactly one of these is set. `filename` is under files/, for something
    # uploaded through the form below. `source_path` is an absolute path
    # outside this app entirely, for something found by scanning a linked
    # folder — see LibraryFolder.
    filename: str = ""
    source_path: str = ""
    folder_id: str = ""                    # which LibraryFolder, if any, found this
    thumb_filename: str = ""               # under thumbs/ — always ours, never external
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


@dataclass
class LibraryFolder:
    id: str
    path: str                              # absolute, on this machine
    label: str = ""                        # "" = show the folder's own name
    added_at: float = 0.0
    last_scanned: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LibraryFolder":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ------------------------------------------------------------------- index
# One file holds both halves: the assets (uploaded or folder-linked) and the
# folders themselves. Kept together because every folder operation needs to
# touch both — adding a folder is cheap, but scanning it rewrites the asset
# list, and the two should never be able to drift out of sync by being saved
# separately.
def _load_both() -> tuple[list[LibraryAsset], list["LibraryFolder"]]:
    if not _INDEX_FILE.exists():
        return [], []
    try:
        raw = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], []
    assets = [LibraryAsset.from_dict(r) for r in raw.get("assets", [])]
    folders = [LibraryFolder.from_dict(r) for r in raw.get("folders", [])]
    return assets, folders


def _load_index() -> list[LibraryAsset]:
    return _load_both()[0]


def _load_folders() -> list[LibraryFolder]:
    return _load_both()[1]


def _save_both(assets: list[LibraryAsset], folders: list[LibraryFolder]) -> None:
    payload = json.dumps(
        {"assets": [a.to_dict() for a in assets],
         "folders": [f.to_dict() for f in folders]},
        indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=LIBRARY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, _INDEX_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _save_index(assets: list[LibraryAsset]) -> None:
    """Rewrite just the assets, keeping whatever folders are on disk right
    now — for the plain upload path below, which has no reason to touch
    folders and would otherwise need to thread them through for no purpose."""
    _save_both(assets, _load_folders())


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
    if not a:
        return None
    if a.get("source_path"):
        return Path(a["source_path"])
    return _FILES / a["filename"] if a["filename"] else None


def thumb_path(asset_id: str) -> Path | None:
    a = get(asset_id)
    if not a:
        return None
    if a["thumb_filename"]:
        return _THUMBS / a["thumb_filename"]
    # An external image with no generated thumbnail can still be served
    # directly — an uploaded one always has `filename` for this fallback;
    # a folder-linked one needs `file_path()` itself, which knows about
    # `source_path` too.
    if a["kind"] == "image":
        return file_path(asset_id)
    return None


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
        # Only ever delete what we created ourselves. A folder-linked asset's
        # `filename` is empty (see file_path()) — its real file belongs to
        # the user, on their own disk, and this never touches it.
        if gone.filename:
            (_FILES / gone.filename).unlink(missing_ok=True)
        if gone.thumb_filename:
            (_THUMBS / gone.thumb_filename).unlink(missing_ok=True)
        _save_index(keep)
        return True


# -------------------------------------------------------------- folders
# A scan is capped rather than unbounded: pointing this at the wrong folder
# (a whole Pictures library, a home directory) should come back with a
# partial result and a clear count, not hang for ten minutes or fill the
# index with thousands of thumbnails nobody will ever pick from.
_SCAN_CAP = 4000


def list_folders() -> list[dict]:
    """Every linked folder, with how many assets it currently contributes —
    for the Library page, so a folder nobody has rescanned in a while still
    shows what it last found."""
    with _LOCK:
        assets, folders = _load_both()
    counts: dict[str, int] = {}
    for a in assets:
        if a.folder_id:
            counts[a.folder_id] = counts.get(a.folder_id, 0) + 1
    out = []
    for f in sorted(folders, key=lambda f: f.added_at, reverse=True):
        d = f.to_dict()
        d["asset_count"] = counts.get(f.id, 0)
        d["exists"] = Path(f.path).is_dir()
        out.append(d)
    return out


def add_folder(path: str, label: str = "") -> dict:
    """Start tracking a folder. Does not scan it yet — that is its own step,
    so the UI can show progress on what might be a slow walk of a large
    folder instead of this call blocking on it."""
    p = Path(path).expanduser()
    if not p.is_dir():
        raise NotADirectoryError(f"Not a folder: {path}")
    resolved = str(p.resolve())
    with _LOCK:
        assets, folders = _load_both()
        for f in folders:
            if f.path == resolved:
                return f.to_dict()      # already linked; adding again is a no-op
        folder = LibraryFolder(id=_uid(), path=resolved, label=label.strip(),
                               added_at=time.time())
        folders.append(folder)
        _save_both(assets, folders)
    return folder.to_dict()


def remove_folder(folder_id: str) -> int:
    """Stop tracking a folder. Removes its assets from the index and their
    thumbnails — never the original files, which were never ours to delete.
    Returns how many assets were dropped."""
    with _LOCK:
        assets, folders = _load_both()
        folders = [f for f in folders if f.id != folder_id]
        keep, dropped = [], []
        for a in assets:
            (dropped if a.folder_id == folder_id else keep).append(a)
        for a in dropped:
            if a.thumb_filename:
                (_THUMBS / a.thumb_filename).unlink(missing_ok=True)
        _save_both(keep, folders)
    return len(dropped)


def scan_folder(folder_id: str, progress: Callable[[str], None] = lambda m: None
               ) -> dict:
    """(Re)index one linked folder: add what is new, drop what is gone.

    Runs synchronously — callers that want progress reported to a UI wrap
    this in a background job (see app/main.py), the same pattern `media.gather`
    already uses.
    """
    with _LOCK:
        assets, folders = _load_both()
        folder = next((f for f in folders if f.id == folder_id), None)
    if folder is None:
        raise FileNotFoundError(f"No such folder: {folder_id}")

    root = Path(folder.path)
    if not root.is_dir():
        raise NotADirectoryError(f"{folder.path} no longer exists")

    known_paths = {a.source_path for a in assets if a.folder_id == folder_id}
    found_paths: set[str] = set()
    added: list[LibraryAsset] = []
    scanned = 0

    progress(f"Scanning {root}…")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            kind = "video" if suffix in _VIDEO_EXT else (
                "image" if suffix in _IMAGE_EXT else None)
            if kind is None:
                continue
            scanned += 1
            if scanned > _SCAN_CAP:
                progress(f"Stopped at {_SCAN_CAP} files — the folder has more "
                        "than this will index in one pass.")
                break
            file_path_ = str((Path(dirpath) / name).resolve())
            found_paths.add(file_path_)
            if file_path_ in known_paths:
                continue

            asset_id = _uid()
            src = Path(file_path_)
            width = height = 0
            duration = 0.0
            try:
                if kind == "video":
                    width, height = ffutil.dimensions(src)
                    duration = ffutil.duration(src)
                else:
                    from PIL import Image
                    with Image.open(src) as img:
                        width, height = img.size
            except Exception:
                pass
            thumb_name = _make_thumb(src, kind, f"lib_{asset_id}")
            title = src.stem.replace("_", " ").replace("-", " ").strip() or src.name
            added.append(LibraryAsset(
                id=asset_id, kind=kind, source_path=file_path_, folder_id=folder_id,
                thumb_filename=thumb_name, title=title, width=width, height=height,
                duration=round(duration, 2), added_at=time.time(),
            ))
            if len(added) % 25 == 0:
                progress(f"  found {len(added)} new file(s) so far…")
        if scanned > _SCAN_CAP:
            break

    # Anything this folder indexed before that is no longer on disk — moved,
    # renamed, deleted outside the app — drops out rather than lingering as a
    # candidate that 404s the moment someone picks it.
    with _LOCK:
        assets, folders = _load_both()
        removed = 0
        keep: list[LibraryAsset] = []
        for a in assets:
            if a.folder_id == folder_id and a.source_path not in found_paths                     and a.source_path not in {x.source_path for x in added}:
                if a.thumb_filename:
                    (_THUMBS / a.thumb_filename).unlink(missing_ok=True)
                removed += 1
                continue
            keep.append(a)
        keep.extend(added)
        for f in folders:
            if f.id == folder_id:
                f.last_scanned = time.time()
        _save_both(keep, folders)

    progress(f"Done — {len(added)} added, {removed} removed, "
            f"{len(found_paths)} total in the folder.")
    return {"added": len(added), "removed": removed, "total": len(found_paths)}


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

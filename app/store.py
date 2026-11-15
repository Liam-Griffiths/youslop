"""Project persistence: one directory per project, project.json as the record."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from .config import PROJECTS_DIR
from .schema import Project

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def lock_for(pid: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(pid, threading.RLock())


def project_dir(pid: str) -> Path:
    d = PROJECTS_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("media", "takes", "raw", "titles", "segments", "out"):
        (d / sub).mkdir(exist_ok=True)
    return d


def atomic_write(path: Path, payload: str | bytes) -> None:
    """A crash mid-save cannot truncate an existing JSON file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        options = {} if isinstance(payload, bytes) else {'encoding': 'utf-8'}
        with os.fdopen(fd, 'wb' if isinstance(payload, bytes) else 'w', **options) as fh:
            fh.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(project: Project) -> Project:
    from . import undo
    with lock_for(project.id):
        d = project_dir(project.id)
        path = d / 'project.json'
        before = path.read_text(encoding='utf-8') if path.exists() else None
        previous = json.loads(before) if before else None
        project.sync_takes()
        data = project.to_dict()
        if previous and undo.retain_recordings(data, previous):
            project.retired_takes = data.get('retired_takes', [])
            for kind in ('slides', 'sponsors'):
                for owner, raw in zip(getattr(project, kind), data[kind]):
                    owner.history = raw.get('history', [])
        # Don't turn no-op autosaves into history entries or job deltas.
        if previous == data:
            return project
        project.updated_at = time.time()
        data['updated_at'] = project.updated_at
        payload = undo.encode(data)
        undo.remember(d, before, payload, undo.edit_source.get())
        atomic_write(path, payload)
    return project


def load(pid: str) -> Project:
    path = PROJECTS_DIR / pid / "project.json"
    if not path.exists():
        raise FileNotFoundError(f"No project {pid}")
    return Project.from_dict(json.loads(path.read_text(encoding="utf-8")))


def exists(pid: str) -> bool:
    return (PROJECTS_DIR / pid / "project.json").exists()


def delete(pid: str) -> None:
    import shutil
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)


def list_projects(*, include_stage: bool = False) -> list[dict]:
    from .stages import home_summary
    out = []
    for d in PROJECTS_DIR.iterdir():
        if not (d / "project.json").exists():
            continue
        try:
            raw = json.loads((d / "project.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(
            {
                "id": raw.get("id", d.name),
                "kind": raw.get("kind", "video"),
                "title": raw.get("title") or raw.get("idea", "")[:70],
                "idea": raw.get("idea", ""),
                "channel_id": raw.get("channel_id", ""),
                "status": raw.get("status", "new"),
                **({"stage": home_summary(Project.from_dict(raw))} if include_stage else {}),
                "updated_at": raw.get("updated_at", 0),
                "slides": len(raw.get("slides", [])),
                "recorded": sum(1 for s in raw.get("slides", []) if s.get("take")),
                "est_seconds": raw.get("est_seconds", 0),
                "has_output": bool(raw.get("render", {}).get("output")),
                "thumb_at": (raw.get("thumb") or {}).get("rendered_at", 0),
                "format": (raw.get("style") or {}).get("format", "kenburns"),
                "test": bool(raw.get("test")),
                "cast": [c.get("model") for c in raw.get("cast") or [] if isinstance(c, dict)],
            }
        )
    return sorted(out, key=lambda p: p["updated_at"], reverse=True)


def log(project: Project, message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    project.log.append(f"[{stamp}] {message}")

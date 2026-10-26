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


def save(project: Project) -> Project:
    project.updated_at = time.time()
    project.sync_takes()
    d = project_dir(project.id)
    payload = json.dumps(project.to_dict(), indent=2, ensure_ascii=False)
    # Atomic write so a crash mid-save can never truncate an existing project.
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, d / "project.json")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
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


def list_projects() -> list[dict]:
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
                "title": raw.get("title") or raw.get("idea", "")[:70],
                "idea": raw.get("idea", ""),
                "channel_id": raw.get("channel_id", ""),
                "status": raw.get("status", "new"),
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

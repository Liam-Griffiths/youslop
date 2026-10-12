"""Channel persistence: one directory per channel, channel.json as the record."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from .config import CHANNELS_DIR
from .schema import Channel

_LOCKS: dict[str, threading.RLock] = {}
_GUARD = threading.Lock()


def lock_for(cid: str) -> threading.RLock:
    with _GUARD:
        return _LOCKS.setdefault(cid, threading.RLock())


def channel_dir(cid: str) -> Path:
    d = CHANNELS_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("intro", "cache"):
        (d / sub).mkdir(exist_ok=True)
    return d


def save(channel: Channel) -> Channel:
    channel.updated_at = time.time()
    d = channel_dir(channel.id)
    payload = json.dumps(channel.to_dict(), indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, d / "channel.json")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return channel


def load(cid: str) -> Channel:
    path = CHANNELS_DIR / cid / "channel.json"
    if not path.exists():
        raise FileNotFoundError(f"No channel {cid}")
    return Channel.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_or_none(cid: str) -> Channel | None:
    if not cid:
        return None
    try:
        return load(cid)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def delete(cid: str) -> None:
    import shutil
    shutil.rmtree(CHANNELS_DIR / cid, ignore_errors=True)


def list_channels() -> list[dict]:
    from .intro import needs_images        # imported here: intro imports us
    from .store import list_projects

    counts: dict[str, int] = {}
    for p in list_projects():
        counts[p.get("channel_id") or ""] = counts.get(p.get("channel_id") or "", 0) + 1

    out = []
    for d in CHANNELS_DIR.iterdir():
        f = d / "channel.json"
        if not f.exists():
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        intro = raw.get("intro") or {}
        # A type-led slate is ready the moment it is chosen; only the cast-led
        # templates are waiting on portraits.
        cast_led = needs_images(intro.get("template") or "columns")
        out.append({
            "id": raw.get("id", d.name),
            "name": raw.get("name", "Untitled channel"),
            "tagline": raw.get("tagline", ""),
            "concept": raw.get("concept", ""),
            "accent": (raw.get("style") or {}).get("accent", "#E8C36A"),
            "format": (raw.get("style") or {}).get("format", "kenburns"),
            "picture_every": (raw.get("style") or {}).get("picture_every", 1),
            "videos": counts.get(raw.get("id", d.name), 0),
            "intro_ready": (len(intro.get("images") or []) >= 2) or not cast_led,
            "intro_images": len(intro.get("images") or []),
            "intro_template": intro.get("template") or "columns",
            "intro_cast_led": cast_led,
            "updated_at": raw.get("updated_at", 0),
        })
    return sorted(out, key=lambda c: c["updated_at"], reverse=True)

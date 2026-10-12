"""Where the two kinds of file live.

A checkout and an installed app disagree about this, and the disagreement is
the whole of what makes the tool portable. Two kinds of path:

**Resources** are read-only and ship with the program — the web UI in
`static/`, the bundled fonts, the bundled ffmpeg. Frozen, they sit in
PyInstaller's unpacked bundle; from a checkout, in the source tree.

**Data** is everything the creator makes and the program writes: projects,
channels, the stock library, the music, the model weights, caches, logs. In a
checkout that is the source tree, exactly as it has always been, so an existing
clone keeps its projects where it left them. Installed, it is the usual
per-user folder for the platform, because an application bundle in
`/Applications` or `Program Files` is read-only — and on macOS it is also
code-signed, so writing inside it would break the signature even where the
permissions allowed it.

`YOUSLOP_DATA` overrides the data root, which is how you keep two sets of
projects, or put them on another disk.

The layout under the data root is the same in both cases (`projects/`,
`channels/`, `assets/`, `.cache/`). One layout is worth more than a tidier
name for the installed case: it means a checkout and an install are the same
program reading the same shapes, and a folder can be moved between them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: True when running from a PyInstaller bundle rather than a source checkout.
FROZEN = bool(getattr(sys, "frozen", False))

# The source tree, whatever else is going on. Resources resolve against this
# when not frozen, and it is also the data root for a checkout.
SOURCE_ROOT = Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """Where the files that ship with the program are. Never written to."""
    if FROZEN:
        # PyInstaller unpacks `datas` here; one-dir builds point at the bundle.
        return Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
    return SOURCE_ROOT


def _platform_data_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Youslop"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "Youslop"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "youslop"


def data_root() -> Path:
    """Where everything the creator makes is kept.

    A checkout that already has projects in it keeps using itself, so nobody
    comes back from an upgrade to an empty library.
    """
    override = os.environ.get("YOUSLOP_DATA", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if not FROZEN and (SOURCE_ROOT / "projects").is_dir():
        return SOURCE_ROOT
    return _platform_data_root()


def describe() -> dict:
    """What the About box and the bug reports need to say."""
    return {
        "frozen": FROZEN,
        "resources": str(resource_root()),
        "data": str(data_root()),
        "overridden": bool(os.environ.get("YOUSLOP_DATA", "").strip()),
    }

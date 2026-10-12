"""Saved slide designs, reusable as a video's house style.

A design made in the slide editor is a one-off: it belongs to the paragraph it
was drawn for. Saving it here turns it into a *style* — a layout, a palette and
a set of entrances, with the words and pictures left as slots — which then
appears in the Video style picker beside Documentary, Video essay and
Handwritten board. Pick one and every paragraph is staged in that design, the
same way picking the board format stages every paragraph as a board.

The split that makes this work: a `custom_slide` spec is already two things
mixed together — *how it looks* (positions, colours, fonts, animation) and
*what it says* (the text, the image queries). A style keeps the first and
treats the second as placeholders, so filling it per paragraph is a matter of
swapping strings into an existing layout rather than designing a new one 30
times. See `script_gen.plan_custom_slides`.

Stored in the data dir rather than in a project, because the whole point is to
reuse one across videos — the same reason the stock library lives there.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import custom_slide
from .config import DATA

STYLES_DIR = DATA / "slide_styles"
_INDEX_FILE = STYLES_DIR / "index.json"


@dataclass
class SlideStyle:
    id: str
    name: str
    spec: dict = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SlideStyle":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def summary(self) -> dict:
        """What the picker needs: never the whole spec, only its shape."""
        els = self.spec.get("elements", [])
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "elements": len(els),
            "slots": sum(1 for e in els if e.get("type") in ("text", "image")),
        }


def _load() -> list[SlideStyle]:
    if not _INDEX_FILE.exists():
        return []
    try:
        raw = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [SlideStyle.from_dict(r) for r in raw.get("styles", [])]


def _save(styles: list[SlideStyle]) -> None:
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"styles": [s.to_dict() for s in styles]},
                         indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=STYLES_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, _INDEX_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def list_styles() -> list[dict]:
    return [s.summary() for s in sorted(_load(), key=lambda s: s.created_at)]


def get(style_id: str) -> SlideStyle | None:
    return next((s for s in _load() if s.id == style_id), None)


def thumb_path(style_id: str) -> Path:
    return STYLES_DIR / f"{style_id}.jpg"


def _strip_resolved_images(spec: dict) -> dict:
    """Drop a fetched photo's path from a spec before it becomes a style.

    A style saved from the slide editor ("save as a style…") may carry a
    `local_path` the editor already resolved for that one paragraph — a file
    inside that project's media folder, meaningless once the spec is reused
    on a different paragraph, exported, or opened on another machine. A style
    is a template; its image elements should only ever be a query.
    """
    spec = copy.deepcopy(spec)
    for el in spec.get("elements", []):
        if el.get("type") == "image":
            el["local_path"] = ""
            el.pop("source_page", None)
            el.pop("author", None)
    return spec


def save(name: str, spec: dict, hand: str = custom_slide.DEFAULT_HAND) -> dict:
    """Keep a design as a named style, and draw its picker thumbnail.

    The thumbnail is rendered from the spec as-is — placeholders and all —
    because what the picker is showing is the *shape* of the style, which is
    exactly what the placeholder text illustrates.
    """
    spec = _strip_resolved_images(custom_slide.normalise(spec))
    name = (name or "").strip()[:60] or "Untitled style"
    style = SlideStyle(id=f"ss{uuid.uuid4().hex[:8]}", name=name, spec=spec,
                       created_at=time.time())
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    shot = custom_slide.render_still(spec, hand=hand)
    shot.resize((480, 270)).save(thumb_path(style.id), quality=86)
    styles = _load()
    styles.append(style)
    _save(styles)
    return style.summary()


def rename(style_id: str, name: str) -> bool:
    styles = _load()
    for s in styles:
        if s.id == style_id:
            s.name = (name or "").strip()[:60] or s.name
            _save(styles)
            return True
    return False


def remove(style_id: str) -> bool:
    styles = _load()
    kept = [s for s in styles if s.id != style_id]
    if len(kept) == len(styles):
        return False
    _save(kept)
    thumb = thumb_path(style_id)
    if thumb.is_file():
        thumb.unlink()
    return True


# ------------------------------------------------------------ import/export
# A small, versioned, self-contained bundle — the style's name and its spec,
# nothing that only makes sense on this machine (no id, no local file path,
# no timestamp). Sharing a style someone else made real is the point: hand
# over this one file and it opens the same way a style made locally does.
BUNDLE_VERSION = 1


def export_bundle(style_id: str) -> dict | None:
    style = get(style_id)
    if not style:
        return None
    return {"youslop_slide_style": BUNDLE_VERSION, "name": style.name,
            "spec": _strip_resolved_images(style.spec)}


def import_bundle(data: dict, hand: str = custom_slide.DEFAULT_HAND) -> dict:
    """Read a bundle a person exported — here, or from someone else's copy.

    Forgiving about the wrapper the same way the spec itself is forgiving:
    accepts the real export shape, a bare `{"name", "spec"}`, or a bare spec
    on its own, so pasting just the `spec` object back in still works.
    """
    if not isinstance(data, dict):
        raise ValueError("That file isn't a slide style.")
    spec = data.get("spec") if isinstance(data.get("spec"), dict) else data
    name = str(data.get("name") or "Imported style")
    return save(name, spec, hand=hand)


# ---------------------------------------------------------------- the format
# A video in a saved style carries "custom:<id>" as its format, so one string
# still answers "how is this video staged" for every consumer that only ever
# compared it to "board" or "essay".
PREFIX = "custom:"


def format_for(style_id: str) -> str:
    return f"{PREFIX}{style_id}"


def id_from_format(fmt: str) -> str:
    return fmt[len(PREFIX):] if (fmt or "").startswith(PREFIX) else ""

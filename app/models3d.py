"""The 3D model library: every model a 3D explainer can put on stage.

Shared across projects, like the stock library and the music folder, because
the expensive part of a model is not the download but *understanding* it:
which way is the front, how big it really is, what its parts are. That is
done once, here, and every video that uses the model inherits it. See
docs/3d-explainer.md, step 3.

One folder per model under `assets/models/<id>/`:

    model.glb       the file as uploaded, never modified
    manifest.json   everything known about it (below)
    thumb.jpg       a three-quarter view, rendered by the browser

Only GLB is accepted: a single file with its textures inside, which three.js
loads natively. Its JSON chunk is read here, without a 3D library, for the
credit (Sketchfab and most exporters put title, author, licence and source in
`asset.extras`), the counts, and the named parts.

The manifest has two halves. What the file says (`source`, `stats`,
`parts`) is read on import and never edited. What a human confirmed
(`title`, `heading`, `scale`, `tint`, `regions`, `confirmed`) is written by
the intake screen. The browser does the measuring, because it is the thing
that applies the node transforms: `measured` is the model's size in file
units once stood up and centred, before `scale`.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import MODELS_DIR

_LOCK = threading.RLock()

MAX_BYTES = 400 * 1024 * 1024
_ID = re.compile(r"^m[0-9a-f]{8}$")


class ModelError(ValueError):
    pass


# --------------------------------------------------------------- reading GLB
def read_glb_json(path: Path) -> dict:
    """The JSON chunk of a binary glTF. Raises ModelError for anything else."""
    with open(path, "rb") as fh:
        head = fh.read(20)
        if len(head) < 20:
            raise ModelError("That file is too short to be a GLB model.")
        magic, version, _length = struct.unpack("<4sII", head[:12])
        chunk_len, chunk_type = struct.unpack("<I4s", head[12:20])
        if magic != b"glTF":
            raise ModelError("That is not a GLB file. Export or download the "
                             "model as .glb (binary glTF).")
        if version != 2:
            raise ModelError(f"GLB version {version} is not supported; only glTF 2.0.")
        if chunk_type != b"JSON" or chunk_len > 64 * 1024 * 1024:
            raise ModelError("That GLB file has no readable JSON chunk.")
        try:
            return json.loads(fh.read(chunk_len))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ModelError(f"That GLB file's JSON chunk is damaged: {exc}") from exc


# Names exporters give to wrappers and anonymous chunks rather than to parts.
_JUNK = re.compile(
    r"^(object_?\d+|rootnode|root|scene|sketchfab_model|collada visual scene group"
    r"|gltf_scenerootnode|.*-material|.*_material|mesh_?\d*|node_?\d*|group_?\d*"
    r"|polysurface\d+|p(cube|sphere|cylinder|plane)\d+|defaultmaterial|default"
    r"|.*\.(obj|fbx|dae|3ds|blend|max|gles)(\..*)?)$",
    re.I)


def _is_junk(name: str) -> bool:
    return not name or bool(_JUNK.match(name.strip()))


def _has_mesh(gltf: dict, idx: int, memo: dict) -> bool:
    if idx in memo:
        return memo[idx]
    node = gltf["nodes"][idx]
    memo[idx] = False                                   # cycles: assume no
    memo[idx] = "mesh" in node or any(_has_mesh(gltf, c, memo) for c in node.get("children", []))
    return memo[idx]


def _label(name: str, prefix: str) -> str:
    """'A380-800_wing_L' with prefix 'A380-800_' -> 'wing L'; exporter noise
    ('mesh', '001', a word said twice) dropped. Only a placeholder: the
    naming step replaces it with what the part actually is."""
    out = name[len(prefix):] if prefix and name.startswith(prefix) else name
    words, kept = re.sub(r"[_\-.]+", " ", out).split(), []
    for w in words:
        if w.lower() in ("mesh", "geo", "geometry", "obj") or w.isdigit():
            continue
        if kept and kept[-1].lower() == w.lower():
            continue
        kept.append(w)
    return " ".join(kept) or name


def _common_prefix(names: list[str]) -> str:
    """The longest prefix ending in a separator that at least half the names share."""
    best = ""
    for name in names:
        for m in re.finditer(r"[_\-. ]", name):
            cand = name[: m.end()]
            if len(cand) > len(best) and sum(n.startswith(cand) for n in names) * 2 >= len(names):
                best = cand
    return best


def find_parts(gltf: dict) -> list[dict]:
    """The model's named parts, or [] when it is an unsplit scan.

    Walks down from the scene roots through wrappers (junk names, or a node
    whose only meshy child holds everything) to the first level of nodes with
    real names. Those are the parts; nothing below them is looked at, so a
    wing's material sub-meshes stay part of the wing.
    """
    nodes = gltf.get("nodes") or []
    scenes = gltf.get("scenes") or []
    if not nodes or not scenes:
        return []
    memo: dict[int, bool] = {}
    roots = scenes[gltf.get("scene", 0) if isinstance(gltf.get("scene"), int) else 0].get("nodes", [])
    frontier = [r for r in roots if _has_mesh(gltf, r, memo)]
    parts: list[int] = []
    for _ in range(12):                                 # depth guard
        if not frontier:
            break
        nxt: list[int] = []
        for idx in frontier:
            node = nodes[idx]
            kids = [c for c in node.get("children", []) if _has_mesh(gltf, c, memo)]
            wrapper = _is_junk(node.get("name", "")) or (len(frontier) == 1 and len(kids) >= 1)
            if wrapper and kids:
                nxt.extend(kids)
            elif not _is_junk(node.get("name", "")):
                parts.append(idx)
        if parts:
            break
        frontier = nxt
    names = [nodes[i].get("name", "") for i in parts]
    # A common prefix like "A380-800_" says nothing; strip it from labels.
    prefix = _common_prefix(names) if len(names) > 1 else ""
    return [{"node": nodes[i].get("name", ""), "label": _label(nodes[i].get("name", ""), prefix)}
            for i in parts]


def _stats(gltf: dict) -> dict:
    tris = 0
    acc = gltf.get("accessors") or []
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            if "indices" in prim and prim["indices"] < len(acc):
                tris += acc[prim["indices"]].get("count", 0) // 3
            elif "POSITION" in (prim.get("attributes") or {}):
                tris += acc[prim["attributes"]["POSITION"]].get("count", 0) // 3
    return {
        "triangles": tris,
        "meshes": len(gltf.get("meshes") or []),
        "nodes": len(gltf.get("nodes") or []),
        "materials": len(gltf.get("materials") or []),
        "textures": len(gltf.get("textures") or []),
        "animations": len(gltf.get("animations") or []),
        "extensions": sorted(gltf.get("extensionsRequired") or []),
    }


def _split_credit(text: str) -> tuple[str, str]:
    """'JUSTGAME (https://sketchfab.com/x)' -> ('JUSTGAME', 'https://sketchfab.com/x')."""
    m = re.match(r"^\s*(.*?)\s*\((https?://[^)]+)\)\s*$", text or "")
    return (m.group(1), m.group(2)) if m else ((text or "").strip(), "")


def licence_terms(licence: str) -> dict:
    """What a licence string obliges. Conservative: unknown means ask."""
    s = (licence or "").upper().replace(" ", "")
    if not s:
        return {"kind": "unknown", "credit_required": True, "commercial_ok": None}
    if "CC0" in s or "PUBLICDOMAIN" in s:
        return {"kind": "CC0", "credit_required": False, "commercial_ok": True}
    if "CC-BY" in s or "CCBY" in s or "ATTRIBUTION" in s:
        nc = "-NC" in s or "NONCOMMERCIAL" in s
        return {"kind": "CC-BY-NC" if nc else "CC-BY", "credit_required": True,
                "commercial_ok": not nc}
    return {"kind": "other", "credit_required": True, "commercial_ok": None}


def _source(gltf: dict) -> dict:
    extras = (gltf.get("asset") or {}).get("extras") or {}
    author, author_url = _split_credit(str(extras.get("author") or ""))
    licence, licence_url = _split_credit(str(extras.get("license") or extras.get("licence") or ""))
    return {
        "title": str(extras.get("title") or "")[:200],
        "author": author[:200],
        "author_url": author_url,
        "licence": licence[:120],
        "licence_url": licence_url,
        "url": str(extras.get("source") or "")[:500],
        "generator": str((gltf.get("asset") or {}).get("generator") or "")[:120],
        **licence_terms(licence),
    }


# ------------------------------------------------------------------- storage
def _dir(mid: str) -> Path:
    if not _ID.match(mid or ""):
        raise ModelError("No such model.")
    return MODELS_DIR / mid


def _manifest_path(mid: str) -> Path:
    return _dir(mid) / "manifest.json"


def _write(manifest: dict) -> None:
    path = _manifest_path(manifest["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(path)


def get(mid: str) -> dict:
    with _LOCK:
        path = _manifest_path(mid)
        if not path.exists():
            raise ModelError("No such model.")
        return json.loads(path.read_text(encoding="utf-8"))


def glb_path(mid: str) -> Path:
    path = _dir(mid) / "model.glb"
    if not path.exists():
        raise ModelError("No such model.")
    return path


def thumb_path(mid: str) -> Path:
    return _dir(mid) / "thumb.jpg"


def all_models() -> list[dict]:
    out = []
    with _LOCK:
        if not MODELS_DIR.is_dir():
            return out
        for d in MODELS_DIR.iterdir():
            if _ID.match(d.name) and (d / "manifest.json").exists():
                try:
                    out.append(json.loads((d / "manifest.json").read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
    out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return out


def add(upload: Path, filename: str) -> dict:
    """Take an uploaded file into the library. `upload` is moved, not copied."""
    if upload.stat().st_size > MAX_BYTES:
        raise ModelError(f"That model is over {MAX_BYTES // (1024 * 1024)} MB.")
    gltf = read_glb_json(upload)
    src = _source(gltf)
    stem = Path(filename or "model").stem
    title = src["title"] or re.sub(r"[_\-]+", " ", stem).strip().title() or "Untitled model"
    mid = "m" + uuid.uuid4().hex[:8]
    with _LOCK:
        d = MODELS_DIR / mid
        d.mkdir(parents=True, exist_ok=False)
        shutil.move(str(upload), d / "model.glb")
        manifest: dict[str, Any] = {
            "id": mid,
            "title": title[:120],
            "filename": filename[:200],
            "bytes": (d / "model.glb").stat().st_size,
            "created_at": time.time(),
            "source": src,
            "stats": _stats(gltf),
            "parts": find_parts(gltf),
            # Confirmed by a human on the intake screen.
            "heading": 0,            # degrees about +y that turn the front to face +z
            "scale": 1.0,            # file units -> metres
            "size_axis": "width",    # which dimension `size_m` was entered for
            "measured": None,        # [x, y, z] in file units, upright, before scale/heading
            "tint": "",              # flat colour for untextured scans, "" = none
            "regions": [],           # [{label, box: [[x,y,z],[x,y,z]]}] in file units (the intake space)
            "confirmed": False,
        }
        _write(manifest)
    return manifest


_EDITABLE = {"title", "heading", "scale", "size_axis", "measured", "tint", "regions",
             "confirmed", "parts_labels", "analysis", "kind", "identity", "north"}

# The five kinds of model (docs/3d-explainer.md, step 3). The browser works one
# out on intake (`analysis.kind_auto`); `kind` is the creator's word, and wins.
KINDS = ("object", "interior", "aerial_site", "modelled_site", "set")


def kind_of(m: dict) -> str:
    return m.get("kind") or (m.get("analysis") or {}).get("kind_auto") or "object"


def update(mid: str, changes: dict) -> dict:
    with _LOCK:
        m = get(mid)
        for key, value in changes.items():
            if key not in _EDITABLE:
                continue
            if key == "title":
                m["title"] = str(value).strip()[:120] or m["title"]
            elif key == "heading":
                m["heading"] = int(round(float(value))) % 360
            elif key == "scale":
                v = float(value)
                if not 1e-6 < v < 1e6:
                    raise ModelError("That scale is out of range.")
                m["scale"] = v
            elif key == "size_axis":
                m["size_axis"] = value if value in ("width", "length", "height") else "width"
            elif key == "measured":
                if (isinstance(value, list) and len(value) == 3
                        and all(isinstance(x, (int, float)) and x >= 0 for x in value)):
                    m["measured"] = [round(float(x), 5) for x in value]
            elif key == "tint":
                v = str(value or "")
                m["tint"] = v if re.match(r"^(#[0-9a-fA-F]{6})?$", v) else m["tint"]
            elif key == "regions":
                m["regions"] = _clean_regions(value)
            elif key == "confirmed":
                m["confirmed"] = bool(value)
            elif key == "analysis":
                # Measured in the browser (static/stage/intake.js). Kept whole,
                # but bounded: it is a summary, never the probe's raw pixels.
                if isinstance(value, dict) and len(json.dumps(value)) < 200_000:
                    m["analysis"] = value
                    m["analysed_at"] = time.time()
            elif key == "kind":
                m["kind"] = value if value in KINDS else ""
            elif key == "identity":
                # Claude's suggestions (app/identify.py), applied only by the creator.
                if isinstance(value, dict) and len(json.dumps(value)) < 100_000:
                    m["identity"] = value
            elif key == "north":
                m["north"] = value if value in ("-z", "+z", "-x", "+x") else ""
            elif key == "parts_labels" and isinstance(value, dict):
                for part in m["parts"]:
                    if part["node"] in value:
                        part["label"] = str(value[part["node"]]).strip()[:60] or part["label"]
        _write(m)
        return m


def _clean_regions(value: Any) -> list[dict]:
    out = []
    for r in value if isinstance(value, list) else []:
        try:
            lo, hi = r["box"]
            lo = [float(x) for x in lo][:3]
            hi = [float(x) for x in hi][:3]
        except (KeyError, TypeError, ValueError):
            continue
        if len(lo) == 3 and len(hi) == 3 and all(a < b for a, b in zip(lo, hi)):
            out.append({"label": str(r.get("label") or "region")[:60], "box": [lo, hi]})
    return out[:40]


def set_thumb(mid: str, data: bytes) -> None:
    if not data.startswith(b"\xff\xd8"):
        raise ModelError("The thumbnail must be a JPEG.")
    with _LOCK:
        m = get(mid)
        thumb_path(mid).write_bytes(data[: 4 * 1024 * 1024])
        m["thumb_at"] = time.time()           # the cards' cache-buster
        _write(m)


def delete(mid: str) -> None:
    with _LOCK:
        d = _dir(mid)
        if d.is_dir():
            shutil.rmtree(d)


def credit_line(m: dict) -> str:
    """One line for the description's credits, or "" when none is owed."""
    src = m.get("source") or {}
    if not src.get("credit_required") and src.get("kind") == "CC0":
        return ""
    title = src.get("title") or m.get("title") or "3D model"
    bits = [f'"{title}"']
    if src.get("author"):
        bits.append(f"by {src['author']}")
    if src.get("licence"):
        bits.append(f"({src['licence']})")
    line = " ".join(bits)
    if src.get("url"):
        line += f" {src['url']}"
    return line

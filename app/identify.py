"""Claude says what a 3D model is, from pictures chosen for its kind.

The browser renders the pictures (static/stage/identify.js) — six labelled
views round an object, four from inside a room, a gridded top view of a
site — and this asks Claude, once, for what the confirm screen can offer as
one-click suggestions:

    name        what it is ("Airbus A380")
    front       which view looks at its front (objects)
    sizes       one or two real dimensions it knows, so the scale can be set
                and cross-checked — two that disagree are worth a warning
    subject     for a site: where the thing the video is about sits, as a box
                in the grid's coordinates, and which way is north
    parts       plain names for the file's named parts

Nothing here changes the model. The suggestions are stored on the manifest
as `identity` and applied only when the creator clicks them. See
docs/3d-explainer.md, step 3.
"""
from __future__ import annotations

import time
from typing import Any

from .llm import MODEL_UTILITY, complete_json

SYSTEM = (
    "You identify 3D models from rendered pictures for a video tool. Be "
    "concrete and honest: if you cannot tell what something is, say so in "
    "`name` and set confidence to low rather than guessing a famous name. "
    "Real-world dimensions must be ones you actually know (published figures "
    "for a named landmark or machine; typical figures for furniture and rooms) "
    "— say which in `how_sure`. Reply with one JSON object only."
)

_COMMON = """\
The file says: title {title!r}, author {author!r}, source {url!r}.
The model's own size in its file units is {size} (x × y × z; y is up).
Measured already, so do not contradict it: it is {facts}.
Named parts in the file: {named}.

Return:
{{
  "name": "what it is, as a viewer would call it",
  "what": "one sentence: what it is and anything notable about the model itself (stylised, scanned, low detail, cut away…)",
  "confidence": "high" | "medium" | "low",
{extra}
  "sizes": [ up to two real dimensions you know, each
    {{"feature": "e.g. wingspan, tower height, ceiling height", "metres": number,
      "measure": {measures}, "how_sure": "published" | "typical" | "guess"}} ]
}}"""

_PROMPTS = {
    "object": (
        "These are six views of one 3D model, labelled by the side of it the "
        "camera stands on.",
        '  "front_view": "the letter of the view (A–D only) that looks most directly at its front, or null if it has no front",\n'
        '  "parts": {{ "<node name>": "plain name", … }} for these named parts, only where you can tell: {parts},',
        '"width" (side to side, seen from the front) | "length" (front to back) | "height"',
    ),
    "interior": (
        "These are four views from the middle of a room, at about eye height, "
        "each looking a different way.",
        "",
        '"room_height" (floor to ceiling) — prefer it; judge it from doors, '
        "chairs, tables or windows in the pictures",
    ),
    "set": (
        "This is a room built as a stage set: the first four views are from "
        "inside it at about eye height, the last from outside. Some walls may "
        "be missing on purpose.",
        "",
        '"room_height" (floor to ceiling) — judge it from the furniture: chairs, '
        "sofas and tables have well-known sizes",
    ),
    "site": (
        "This is a 3D scan or model of a patch of the world. View A looks "
        "straight down and carries a grid labelled in the model's own units: x "
        "grows to the right, z grows downward, the top of the picture is -z. "
        "View B is an oblique view of the same.",
        '  "subject": {{"name": "the landmark this model is about — if a named part above is a landmark, it is that one; otherwise the most notable", '
        '"box": [x_min, z_min, x_max, z_max] in the grid\'s units, tight around it}} or null,\n'
        '  "north": "-z" | "+z" | "-x" | "+x" | "unknown" — which grid direction is north, '
        "judged from what you recognise (a river, a famous layout, shadows at midday are no help),",
        '"subject_x" (the subject\'s extent along the grid\'s x) | "subject_z" (along z) | '
        '"subject_height" (its tallest point above the ground) — the measure must match the '
        "feature: a length runs along x or z, a height is subject_height",
    ),
}

_KIND_PROMPT = {"object": "object", "interior": "interior", "set": "set",
                "aerial_site": "site", "modelled_site": "site"}
_MEASURES = {"width", "length", "height", "room_height", "subject_x", "subject_z", "subject_height"}

_FACTS = {
    "object": "an object seen from outside", "interior": "an interior, a room you stand inside",
    "set": "a cutaway set built to be seen from one side",
    "aerial_site": "an aerial photogrammetry scan of a site, its light baked in",
    "modelled_site": "a built (modelled, not scanned) site with its own buildings and materials",
}


def prompt_for(manifest: dict, kind: str, captions: list[str], meta: dict) -> str:
    intro, extra, measures = _PROMPTS[_KIND_PROMPT.get(kind, "object")]
    src = manifest.get("source") or {}
    parts = ", ".join(p["node"] for p in (manifest.get("parts") or [])[:30]) or "(none)"
    size = " × ".join(f"{v:g}" for v in (meta.get("size_units") or manifest.get("measured") or []))
    named = ", ".join(p["node"] for p in (manifest.get("parts") or [])[:30]) or "(none)"
    body = _COMMON.format(title=src.get("title") or manifest.get("title", ""), author=src.get("author", ""),
                          url=src.get("url", ""), size=size or "unknown",
                          facts=_FACTS.get(kind, "a 3D model"), named=named,
                          extra=extra.format(parts=parts), measures=measures)
    pictures = "\n".join(f"Picture {i + 1}: {c}" for i, c in enumerate(captions))
    return f"{intro}\n\n{pictures}\n\n{body}"


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) < 1e9 else None


def clean(reply: Any, kind: str, manifest: dict) -> dict:
    """Keep only well-formed suggestions; anything odd is dropped, not trusted."""
    r = reply if isinstance(reply, dict) else {}
    out: dict[str, Any] = {
        "name": str(r.get("name") or "")[:120],
        "what": str(r.get("what") or "")[:400],
        "confidence": r.get("confidence") if r.get("confidence") in ("high", "medium", "low") else "low",
        "sizes": [],
    }
    for s in (r.get("sizes") or [])[:2]:
        if not isinstance(s, dict):
            continue
        metres = _num(s.get("metres"))
        if metres and metres > 0 and s.get("measure") in _MEASURES:
            out["sizes"].append({"feature": str(s.get("feature") or "")[:60], "metres": metres,
                                 "measure": s["measure"],
                                 "how_sure": s.get("how_sure") if s.get("how_sure") in ("published", "typical", "guess") else "guess"})
    if kind == "object":
        fv = r.get("front_view")
        out["front_view"] = fv if fv in ("A", "B", "C", "D") else None
        names = {p["node"] for p in manifest.get("parts") or []}
        parts = r.get("parts") if isinstance(r.get("parts"), dict) else {}
        out["parts"] = {k: str(v)[:40] for k, v in parts.items() if k in names and v}
    if _KIND_PROMPT.get(kind) == "site":
        sub = r.get("subject") if isinstance(r.get("subject"), dict) else None
        box = [_num(v) for v in (sub or {}).get("box") or []]
        if sub and len(box) == 4 and None not in box and box[0] < box[2] and box[1] < box[3]:
            out["subject"] = {"name": str(sub.get("name") or "")[:80], "box": box}
        out["north"] = r.get("north") if r.get("north") in ("-z", "+z", "-x", "+x") else "unknown"
    return out


def identify(manifest: dict, kind: str, images: list[bytes], captions: list[str], meta: dict) -> dict:
    reply = complete_json(prompt_for(manifest, kind, captions, meta), system=SYSTEM,
                          model=MODEL_UTILITY, timeout=240, images=images,
                          require=lambda v: isinstance(v, dict) and "name" in v,
                          require_hint="It must be one object with at least a `name` key.")
    out = clean(reply, kind, manifest)
    out.update({"kind": kind, "pictures": len(images), "at": time.time(), "meta": meta})
    return out


REFINE = """\
Here is a closer view, straight down, of the area where you said {name!r} is.
It carries a finer grid labelled in the same model units (x grows to the
right, z grows downward). Draw a tight box around {name!r} itself — the
building or landmark, not its grounds or neighbours.

Return {{"box": [x_min, z_min, x_max, z_max]}} in the grid's units, or
{{"box": null}} if it is not in this picture."""


def refine(manifest: dict, image: bytes, caption: str, grid: dict) -> list[float] | None:
    """The second, closer look (coarse-to-fine): a tight box for the subject.
    Kept only if it sits inside the zoomed picture."""
    sub = ((manifest.get("identity") or {}).get("subject")) or {}
    if not sub.get("name"):
        return None
    reply = complete_json(REFINE.format(name=sub["name"]) + f"\n\nPicture: {caption}", system=SYSTEM,
                          model=MODEL_UTILITY, timeout=200, images=[image],
                          require=lambda v: isinstance(v, dict) and "box" in v)
    box = [_num(v) for v in (reply.get("box") or [])]
    gx, gz = grid.get("x") or [], grid.get("z") or []
    if len(box) != 4 or None in box or not (box[0] < box[2] and box[1] < box[3]):
        return None
    if len(gx) == 2 and len(gz) == 2 and not (gx[0] - 1e-6 <= box[0] and box[2] <= gx[1] + 1e-6
                                                 and gz[0] - 1e-6 <= box[1] and box[3] <= gz[1] + 1e-6):
        return None
    return box

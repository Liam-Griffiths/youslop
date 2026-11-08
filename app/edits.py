"""Slide field edits shared by the HTTP API and storyboard tools."""
import copy
import json
import math

TIMING_FIELDS = {"gap_override", "title_at", "title_hold", "chapter_hold"}

from .take_edits import take_duration

from . import board as board_mod, cuts as cuts_mod, diagram as diagram_mod


class EditError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


EDITABLE = {"narration", "title", "visual_note", "chapter", "queries",
            "on_camera", "locked_media", "prefer_kind", "board_template", "board_lead", "board_note",
            "board_points", "diagram", "picture_mode", "cues", "overlays", "chosen_id", "focal"} | TIMING_FIELDS


def _focal(value) -> list[float]:
    """Normalise a focal point to [x, y] in 0..1. Anything else clears it."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return []
    try:
        return [min(1.0, max(0.0, float(value[0]))), min(1.0, max(0.0, float(value[1])))]
    except (TypeError, ValueError):
        return []


def patch_slide_fields(s, payload: dict) -> list[str]:
    """Apply API field validation in place; return the fields that changed."""
    before = {key: copy.deepcopy(getattr(s, key if key != "focal" else "candidates"))
              for key in payload if key in EDITABLE}
    for key in TIMING_FIELDS & payload.keys():
        value = payload[key]
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EditError(f"{key} must be finite seconds or null")
            value = max(0.0, float(value))
            if key == "gap_override":
                value = min(10.0, value)
            elif key == "title_at" and s.take:
                value = min(take_duration(s.take), value)
        setattr(s, key, value)
    if 'overlays' in payload:
        from .block_overlays import validate
        try:
            s.overlays = validate(s.take, payload['overlays'])
        except ValueError as exc:
            raise EditError(str(exc)) from exc
    if "locked_media" in payload:
        if not isinstance(payload["locked_media"], bool):
            raise EditError("locked_media must be a boolean")
        s.locked_media = payload["locked_media"]
    if "on_camera" in payload:
        if not isinstance(payload["on_camera"], bool):
            raise EditError("on_camera must be a boolean")
        s.on_camera = payload["on_camera"]
    if "narration" in payload:
        s.narration = str(payload["narration"]).strip()
    if "title" in payload:
        s.title = str(payload["title"]).strip()[:40]
    if "visual_note" in payload:
        s.visual_note = str(payload["visual_note"]).strip()[:400]
    if "chapter" in payload:
        # "" clears the mark; a chapter also forces its own picture, which
        # `schema.group_slides` applies on the way back out.
        s.chapter = str(payload["chapter"]).strip()[:60]
    if "queries" in payload:
        s.queries = [q for q in payload["queries"] if str(q).strip()][:4]
    if "prefer_kind" in payload:
        kind = str(payload["prefer_kind"])
        s.prefer_kind = (kind if kind in ("video", "map", "diagram", "custom")
                         else "image")
    if "board_template" in payload:
        key = str(payload["board_template"] or "auto")
        if key != "auto" and key not in board_mod.TEMPLATE_KEYS:
            raise EditError(f"No such board template: {key}")
        s.board_template = key
    for key in ("board_lead", "board_note"):
        if key in payload:
            setattr(s, key, str(payload[key]).strip()[:160])
    if "board_points" in payload:
        raw = payload["board_points"]
        if isinstance(raw, str):
            raw = raw.split("\n")
        s.board_points = [str(p).strip()[:120] for p in raw if str(p).strip()][:6]
    if "diagram" in payload:
        spec = payload["diagram"]
        if not spec:
            s.diagram = {}
        else:
            try:
                s.diagram = diagram_mod.normalise(spec)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise EditError(f"That diagram spec won't draw: {exc}")
    if "picture_mode" in payload:
        mode = str(payload["picture_mode"])
        if mode not in ("auto", "hold", "new"):
            raise EditError("picture_mode is auto, hold or new")
        s.picture_mode = mode
    if isinstance(payload.get("cues"), dict):
        # {"<cut key>": [cues]} — a list replaces that cut's cues, an
        # empty one clears them back to drawing from the narration.
        cues = dict(s.cues or {})
        for key, value in payload["cues"].items():
            if key == 'blocks':
                from . import blocks
                if not isinstance(value, list) or any(not isinstance(c, dict) for c in value):
                    raise EditError('Block cues are a list of objects.')
                library, clean = blocks.discover(), []
                for cue in value:
                    ref = cue.get('block')
                    if not isinstance(ref, str) or ref not in library:
                        raise EditError(f'No such block: {ref}')
                    try:
                        variables = blocks.validate_vars(library[ref]['meta'], cue.get('vars', {}))
                    except ValueError as exc:
                        raise EditError(str(exc)) from exc
                    clean.append(dict(block=ref, vars=variables))
                if clean:
                    cues[key] = clean
                else:
                    cues.pop(key, None)
                continue
            if key not in cuts_mod.BY_KEY:
                raise EditError(f"No such cut: {key}")
            if value and not isinstance(value, list):
                raise EditError("Cues are a list of objects.")
            for cue in value or []:
                at = cue.get("at") if isinstance(cue, dict) else None
                if at is not None and (isinstance(at, bool) or not isinstance(at, (int, float))
                                       or not math.isfinite(at)):
                    raise EditError("at must be finite seconds or null")
            clean = cuts_mod.normalise(cuts_mod.BY_KEY[key], value or [])
            if value and not clean:
                raise EditError("None of those cues are a kind this cut draws.")
            for cue in clean:
                if "at" in cue:
                    at = cue["at"]
                    if s.take:
                        cue["at"] = min(take_duration(s.take), at)
            if clean:
                cues[key] = clean
            else:
                cues.pop(key, None)
        s.cues = cues
    if "chosen_id" in payload:
        s.chosen_id = str(payload["chosen_id"])
        s.locked_media = True
    if "focal" in payload:
        # Lives on the candidate, not the slide, so each image keeps its own
        # point even after you switch pictures and switch back.
        cid = str(payload.get("focal_id") or s.chosen_id)
        cand = next((c for c in s.candidates if c["id"] == cid), None)
        if cand is None:
            raise EditError("No such image on this slide", 404)
        cand["focal"] = _focal(payload["focal"])
    return [key for key in before
            if before[key] != getattr(s, key if key != "focal" else "candidates")]


def add_overlay(slide, item):
    return patch_slide_fields(slide, {'overlays': [*slide.overlays, item]})


def update_overlay(slide, ident, patch):
    if not any(o['id'] == ident for o in slide.overlays):
        raise EditError(f'No such overlay: {ident}', 404)
    return patch_slide_fields(slide, {'overlays': [dict(o, **patch) if o['id'] == ident else o
                                                 for o in slide.overlays]})


def remove_overlay(slide, ident):
    if not any(o['id'] == ident for o in slide.overlays):
        raise EditError(f'No such overlay: {ident}', 404)
    return patch_slide_fields(slide, {'overlays': [o for o in slide.overlays if o['id'] != ident]})

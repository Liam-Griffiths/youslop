"""The cut's stable, render-free contract for editors and agent tools.

apply accepts {"paragraphs": {"slide_id": {field: value, ...}}} only.
Fields come from EDITABLE; cues maps cut keys to lists of cue objects.
Text fields are strings and picture_mode is auto, hold or new. Validation
is atomic and uses the same normalisation as the slide API.
"""
from copy import deepcopy
from dataclasses import asdict

from . import cuts, edits, render

EDITABLE = {"narration", "title", "chapter", "picture_mode", "cues"} | edits.TIMING_FIELDS


_UI_ONLY = {"spoken", "word_times", "effective_cues"}


def build(project) -> dict:
    timeline = render.timeline(project)
    segments = [{k: v for k, v in seg.items() if k not in {"stamp", "ready", "have"}}
                for seg in timeline["segments"]]
    # Drag-editing detail (per-word times etc.) is for the timeline UI only;
    # it would bloat the contract a model reads.
    for seg in segments:
        seg["paragraphs"] = [{k: v for k, v in q.items() if k not in _UI_ONLY}
                             for q in seg.get("paragraphs", [])]
    slides = {s.id: s for s in project.slides}
    paragraphs = []
    for seg in segments:
        for para in seg["paragraphs"]:
            slide = slides[para["id"]]
            path, _kind, _focal = render._chosen(project, slide)
            source = render._picture_source(project, slide)
            candidate = next((c for c in source.candidates
                              if c["id"] == source.chosen_id), {})
            take = slide.take or {}
            paragraphs.append({
                "id": slide.id, "index": para["index"], "start": para["start"],
                "end": round(para["start"] + para["duration"], 3),
                "narration": slide.narration, "title": slide.title,
                "on_camera": slide.on_camera,
                "chapter": slide.chapter, "timing": deepcopy(para["timing"]),
                "picture": {"provider": candidate.get("provider", ""),
                            "title": candidate.get("title", ""),
                            "path": str(path) if path else "",
                            "mode": slide.picture_mode},
                "take": {"path": take.get("path", ""),
                         "video": take.get("video", ""),
                         "duration": take.get("duration", 0.0),
                         "words": deepcopy(take.get("words", []))},
            })
            if slide.cues.get('blocks'):
                paragraphs[-1]['block_cues'] = deepcopy(slide.cues['blocks'])
    if cuts.is_cut(project.style.format):
        by_id = {p["id"]: p for p in paragraphs}
        groups = render._picture_groups(project, render._slide_durations(project, True))
        for seg in segments:
            if seg["type"] != "picture":
                continue
            group = groups[seg["group"]]
            _dur, transition, length = render._segment_timing(project, groups, seg["group"])
            lead = transition / 2 + cuts.head_pad_for(project, group[0][0])
            for sid, cues, times in cuts.timed_cues(project, group, length, lead):
                # Picture time skips the file's leading half-transition.
                offset = seg["start"] - transition / 2
                by_id[sid]["cues"] = [
                    {"i": i, "kind": cue.get("kind", ""), "on": cue.get("on", ""),
                     "text": cue.get("text", ""),
                     "start": round(offset + a, 3), "end": round(offset + b, 3)}
                    for i, (cue, (a, b)) in enumerate(zip(cues, times))]
    return {"version": 1,
            "project": {"id": project.id, "title": project.title,
                        "format": project.style.format, "duration": timeline["total"]},
            "sponsors": [slot.to_dict() for slot in project.sponsors],
            "style": asdict(project.style), "frame": project.frame.to_dict(),
            "segments": segments, "paragraphs": paragraphs}


def apply(project, patch) -> list[str]:
    """Validate the whole patch before editing; return unique changed fields."""
    if not isinstance(patch, dict) or set(patch) != {"paragraphs"}:
        raise edits.EditError('Patch must contain "paragraphs" only')
    if not isinstance(patch["paragraphs"], dict):
        raise edits.EditError("Paragraphs must be an object keyed by slide id")
    slides = {s.id: s for s in project.slides}
    pending, changed = [], []
    for sid, payload in patch["paragraphs"].items():
        if sid not in slides:
            raise edits.EditError(f"No such paragraph: {sid}", 404)
        if not isinstance(payload, dict) or set(payload) - EDITABLE:
            raise edits.EditError(f"Editable fields: {', '.join(sorted(EDITABLE))}")
        slide = deepcopy(slides[sid])
        for field in edits.patch_slide_fields(slide, payload):
            if field not in changed:
                changed.append(field)
        pending.append((slides[sid], slide, payload))
    for original, slide, payload in pending:
        for field in payload:
            setattr(original, field, getattr(slide, field))
    return changed

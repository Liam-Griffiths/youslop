"""Sponsor placement in the unsponsored cut, always at paragraph boundaries."""
from .config import HEAD_PAD, WORDS_PER_MINUTE


def duration(slot):
    return round(float((slot.take or {}).get("duration") or
                       max(2.5, len(slot.script.split()) / WORDS_PER_MINUTE * 60)), 3)


def placements(project, plan, pre=0.0):
    """Map paragraph ids to reads following them, preserving slot order.

    Time requests use original picture time (including the opening slate),
    rounded forward to the next paragraph boundary. Other sponsors never move
    that anchor. An explicit paragraph id takes precedence over at_s.
    """
    if not plan:
        return {}
    boundaries, t = [], pre + HEAD_PAD
    for slide, seconds in plan:
        t += seconds
        boundaries.append((slide.id, t))
    result = {}
    for slot in project.sponsors:
        if not slot.enabled:
            continue
        if slot.placement == "end":
            sid = plan[-1][0].id
        elif slot.placement == "mid" and slot.after_slide_id:
            sid = slot.after_slide_id
            if sid not in {s.id for s, _ in plan}:
                continue
        elif slot.placement in {"pre", "mid"}:
            target = pre + project.frame.hook_s if slot.placement == "pre" else slot.at_s
            if target is None:
                continue
            sid = next((sid for sid, end in boundaries if end >= target), boundaries[-1][0])
        else:
            continue
        result.setdefault(sid, []).append(slot)
    return result


def pads(placements):
    return {sid: sum(duration(slot) for slot in slots) for sid, slots in placements.items()}

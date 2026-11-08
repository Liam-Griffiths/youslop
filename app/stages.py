"""Cheap, render-free studio readiness computed only from project data."""
from dataclasses import asdict
import hashlib
import json

from . import kinds
from .schema import Project, group_slides


def render_signature(project: Project) -> str:
    """Project render inputs; saving or publishing alone must not stale a cut.

    External channel settings and asset file contents are not tracked here.
    """
    fields = ('title', 'subtitle', 'channel_id', 'use_intro', 'use_outro',
              'intro', 'outro', 'style', 'frame', 'presenter', 'narrator',
              'music', 'cast', 'sponsors', 'shot_list', 'format_look')
    data = {}
    for name in fields:
        value = getattr(project, name)
        if hasattr(value, '__dataclass_fields__'):
            value = asdict(value)
        elif isinstance(value, list):
            value = [asdict(v) if hasattr(v, '__dataclass_fields__') else v for v in value]
        data[name] = value
    data['slides'] = [{k: getattr(s, k) for k in s.__dataclass_fields__
                       if k not in {'takes', 'history', 'queries', 'locked_media'}}
                      for s in project.slides]
    for slide in data['slides']:
        if not slide['kind']:
            slide.pop('kind')
        if slide['take']:
            slide['take'] = {'words': [], **slide['take']}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _has_visual(project, run):
    lead = run[0]
    fmt = kinds.kind_for(project, lead)
    if lead.on_camera:
        return bool((lead.take or {}).get('video'))
    if fmt == 'block':
        return True
    if fmt == 'stage':
        from .cast import _split_visual
        kind, fields = _split_visual(lead.visual_note)
        if kind == '3d' and fields:
            return bool((lead.shot.get('solved') or {}).get('shot'))
    if fmt == 'board' or fmt in {'flameboat', 'casefile', 'loudmouth', 'groupchat', 'ticker'}:
        return all(s.narration.strip() for s in run)
    if fmt.startswith('custom:'):
        return bool(lead.custom_html or lead.custom.get('elements'))
    return any(c.get('id') == lead.chosen_id and c.get('local_path')
               for c in lead.candidates)


def readiness_check(project: Project) -> dict:
    """Only P0 checks: no storyboard, media probes, browser or model loading.

    Opening-picture detection includes generated layouts and camera shots,
    which the full check's path-only opening test cannot yet recognise.
    """
    from .check import camera_sync
    runs = group_slides(project.slides, project.style.picture_every)
    findings = []
    if runs and not _has_visual(project, runs[0]):
        findings.append({'code': 'empty_first_frame', 'level': 'P0'})
    sb = {'paragraphs': [dict(id=s.id, start=0, on_camera=s.on_camera,
                             take=s.take or {}) for s in project.slides]}
    findings.extend(f.to_dict() for f in camera_sync(sb, project.frame, None))
    return {'findings': findings}


def stages(project: Project, check_result: dict) -> list[dict]:
    """Return the six stage-bar states and short, actionable reasons.

    Uses active `slide.take` (including legacy takes), never retired or
    inactive voices. No filesystem access, mutation or expensive operations.
    """
    slides = project.slides
    total = len(slides)
    written = sum(bool(s.narration.strip()) for s in slides)
    voiced = sum(bool((s.take or {}).get('path')) for s in slides)
    drafts = sum(bool((s.take or {}).get('path') and s.take.get('synthetic')) for s in slides)
    runs = group_slides(slides, project.style.picture_every)
    pictured = sum(bool(_has_visual(project, run)) for run in runs)
    script_ok = bool(total and written == total)
    voice_ok = bool(total and voiced == total)
    visuals_ok = bool(runs and pictured == len(runs))
    p0 = check_result.get('counts', {}).get('P0', sum(
        f.get('level') == 'P0' for f in check_result.get('findings', [])))
    outline = project.outline or (project.draft or {}).get('outline') or {}
    beats = len(outline.get('sections') or [])

    def progress(done, count):
        return 'ready' if count and done == count else 'in_progress' if done else 'todo'

    def row(id, label, status, reason, action, onward):
        return dict(id=id, label=label, status=status, reason=reason,
                    next=onward if status == 'ready' else action)

    result = [
        row('plan', 'Plan', 'ready' if outline else 'todo',
            f'{beats} beat' + ('s' if beats != 1 else '') if beats
            else 'Outline ready' if outline else 'Needs a plan',
            'Plan the episode', 'Write the script'),
        row('script', 'Script', progress(written, total),
            f'{total} paragraphs' if script_ok else f'{written} of {total} written',
            'Finish the script', 'Read the script'),
        row('voice', 'Camera' if project.delivery == 'on_camera' else 'Voice',
            progress(voiced, total), f'{drafts} draft reads' if voice_ok and drafts
            else f'{voiced} of {total} read' + (' · draft' if drafts else ''),
            'Read the rest', 'Choose pictures'),
        row('visuals', 'Visuals', progress(pictured, len(runs)),
            f'{len(runs)} pictures' if visuals_ok else f'{len(runs) - pictured} need a picture',
            'Fill the pictures', 'Edit the cut'),
    ]
    if runs:
        result[-1]['kinds'] = {k: sum(kinds.kind_for(project, r[0]) == k for r in runs)
                               for k in sorted(kinds.kinds_in(project))}
    edit_ok = script_ok and voice_ok and visuals_ok and not p0
    result.append(row('edit', 'Edit', 'warn' if p0 else 'ready' if edit_ok
                      else 'in_progress' if total else 'todo',
                      f'{p0} P0' if p0 else 'No P0 findings' if edit_ok else 'Finish earlier stages',
                      'Fix P0 findings' if p0 else 'Finish earlier stages', 'Review the cut'))
    rendered = project.render or {}
    fresh = bool(rendered.get('output') and not rendered.get('preview')
                 and rendered.get('stage_signature') == render_signature(project))
    result.append(row('publish', 'Review & publish',
                      'ready' if fresh and edit_ok else 'warn' if rendered.get('output') else 'todo',
                      'Ready to publish' if fresh and edit_ok else 'Fix earlier stages' if fresh
                      else 'Render again' if rendered.get('output') else 'Not rendered',
                      'Fix earlier stages' if fresh else 'Render the cut', 'Publish the episode'))
    return result


def home_summary(project: Project) -> dict:
    """Next useful stage, using the same cheap readiness as the stage bar."""
    rows = stages(project, readiness_check(project))
    # Imported scripts can be complete without an outline.
    if project.render.get('output'):
        return rows[-1]
    candidates = rows[1:4] if project.slides else rows[:4]
    return next((r for r in candidates if r['status'] != 'ready'), rows[4])

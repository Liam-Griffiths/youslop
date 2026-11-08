"""Resolve picture groups without changing the project's default style."""
from dataclasses import replace

from .schema import group_slides

CUTS = {'flameboat', 'casefile', 'loudmouth', 'groupchat', 'ticker'}


def valid(kind):
    return isinstance(kind, str) and (kind in {'', 'kenburns', 'essay', 'board', 'stage'} | CUTS
                                     or kind.startswith('custom:') and bool(kind[7:].strip()))


def kind_for(project, slide) -> str:
    for group in group_slides(project.slides, project.style.picture_every):
        if any(s.id == slide.id for s in group):
            slide = group[0]
            break
    if slide.on_camera:
        return 'camera'
    if (slide.cues or {}).get('blocks'):
        return 'block'
    return slide.kind or project.style.format


def kinds_in(project) -> set:
    return {kind_for(project, g[0]) for g in group_slides(project.slides, project.style.picture_every)} or {project.style.format}


def transition_for(project, left, right) -> float:
    """Drawn cuts and 3D on either side cut; other kinds retain the style overlap."""
    from .cuts import HARD_CUT
    return (HARD_CUT if {left, right} & (CUTS | {'stage'})
            else max(0.0, float(project.style.transition)))


def run_project(project, slide):
    """Casefile boards and Groupchat threads restart after a different picture kind."""
    if not any(s.kind for s in project.slides):
        return project
    runs, run = [], []
    wanted = kind_for(project, slide)
    for member in project.slides:
        if kind_for(project, member) == wanted:
            run.append(member)
        else:
            if run:
                runs.append(run)
            run = []
    runs.append(run)
    return replace(project, slides=next(r for r in runs if any(s.id == slide.id for s in r)))

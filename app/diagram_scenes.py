"""SVG diagrams: capture short draw-on beats, let ffmpeg hold settled ink."""
from __future__ import annotations

from pathlib import Path
import tempfile

from . import board_scenes, diagram as dg, scenes
from .config import FPS, WIDTH, HEIGHT


def context(root, spec, accent, hand, seconds, grain=.5, *, box=None,
            ground_color=dg.GROUND):
    from .board import Sheet
    project_root = Path(root).resolve()
    geometry = dg.layout(spec, box=box, accent=accent, hand=hand, seconds=seconds)
    sheet = Sheet([dg.Mark(**m) for m in geometry['marks']])
    # The caller's root may be outside the configured project store.
    ctx = scenes.context_base()
    ctx['asset_roots']['project_root'] = str(project_root)
    directory = scenes._directory(project_root)
    ground = dg.ground(ground_color, grain)
    ctx.update(marks=board_scenes.svg_marks(sheet.marks, hand), photos=[],
               beats=geometry['beats'], seed=geometry['seed'],
               ground_url=scenes.ASSETS_URLS['project'] + 'scenes/' +
               board_scenes._asset(directory, ground).name,
               active_order=None, plate=False, settled=False, duration=seconds)
    ctx['fonts']['BoardHand'] = '/fonts/' + Path(dg.hand_stack(hand)[0][0]).name
    return ctx, ground


def still(spec, accent='#E8C36A', *, hand=dg.DEFAULT_HAND, grain=.5,
          box=None, ground_color=dg.GROUND):
    with tempfile.TemporaryDirectory(prefix='diagram-') as tmp:
        ctx, _ = context(Path(tmp), spec, accent, hand, dg.DEFAULT_SECONDS, grain,
                         box=box, ground_color=ground_color)
        ctx['settled'] = True
        return scenes.capture(Path(tmp), 'board/diagram.html', ctx, t=0, size=(WIDTH, HEIGHT))


def render(project, ctx, ground, out, *, crf=18, extra=()):
    return board_scenes.render(project, 'diagram', ctx, ground, out, crf=crf, extra=extra)

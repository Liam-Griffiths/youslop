"""SVG diagrams: capture short draw-on beats, let ffmpeg hold settled ink."""
from __future__ import annotations

import math
from pathlib import Path
import tempfile

from . import board_scenes, diagram as dg, ffutil, scenes, stage
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
    size = (WIDTH, HEIGHT)
    if '-vf' in extra:
        scale = extra[extra.index('-vf') + 1]
        if scale.startswith('scale='):
            size = tuple(map(int, scale[6:].split(':')))
    extra = board_scenes.without_scale(extra)
    inputs, graph, last = [], [], '0:v'
    directory = scenes._directory(project)
    bg = board_scenes._asset(directory, ground.resize(size))
    inputs += ['-loop', '1', '-framerate', str(FPS), '-i', str(bg)]
    items, clips = [], []
    for order, (start, arrival) in enumerate(ctx['beats']):
        # Include the fully settled endpoint, then clone it in ffmpeg.
        count = math.ceil(arrival * FPS) + 1
        motion = dict(ctx, plate=True, settled=False, active_order=order,
                      beats=[(0, arrival)] * len(ctx['beats']))
        key, html, prepared = scenes._prepare(project, 'board/diagram.html', motion,
                                              count / FPS, size, FPS, ('diagram-motion-v1',))
        clip = html.with_suffix('.mov')
        clips.append(clip)
        if not clip.exists() or not clip.stat().st_size:
            items.append(dict(clip=key, scene_root=str(directory),
                              **ctx['asset_roots'], url_path=f'/scene/{{token}}/{html.name}',
                              W=prepared['width'], H=prepared['height'], fps=FPS,
                              frames=count, size=size, alpha=True))
        i = order + 1
        inputs += ['-i', str(clip)]
        graph.append(f'[{i}:v]tpad=stop_mode=clone:stop_duration={ctx["duration"]},'
                     f'setpts=PTS+{start}/TB[b{i}]')
        graph.append(f'[{last}][b{i}]overlay=eof_action=pass:repeatlast=1:'
                     f"enable='gte(t,{start})'[v{i}]")
        last = f'v{i}'
    if items:
        stage.render_scene(items, directory)
    if any(not p.exists() or not p.stat().st_size for p in clips):
        raise stage.StageError('Diagram motion did not render')
    out.parent.mkdir(parents=True, exist_ok=True)
    ffutil.run([*inputs, '-filter_complex_threads', '1', '-filter_complex', ';'.join(graph),
                '-map', f'[{last}]', '-t', str(ctx['duration']),
                *ffutil.video_args(out, crf=crf), *extra, '-pix_fmt', 'yuv420p', '-an', str(out)])
    return out

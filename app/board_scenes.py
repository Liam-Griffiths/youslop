"""Board scene plates: one browser capture per beat, ffmpeg for motion/holds."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
from urllib.parse import quote

from PIL import Image

from . import diagram as dg, ffutil, scenes, stage, titles
from .config import FPS, HEIGHT, WIDTH


def handles(project, key):
    return (project.style.board_engine != 'pillow'
            and key in ('statement', 'bullets', 'steps', 'versus', 'code',
                        'stat', 'quote', 'taped', 'split', 'diagram')
            and (scenes.SCENE_DIR / 'board' / f'{key}.html').is_file())


def _asset(directory, image):
    data = io.BytesIO()
    image.save(data, format='PNG')
    raw = data.getvalue()
    path = directory / ('board-' + hashlib.sha1(raw).hexdigest() + '.png')
    if not path.exists():
        _write(path, raw)
    return path


def _write(path, data):
    # Parallel segment workers may discover the same content cache miss.
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.part', delete=False) as f:
        temporary = Path(f.name)
        f.write(data)
    temporary.replace(path)


def svg_marks(source, hand):
    marks = []
    for mark in source:
        item = asdict(mark)
        if mark.kind == 'text':
            font = dg.font_for(mark.font, mark.size, hand)
            # Preserve Pillow's anchor placement using the alphabetic baseline.
            anchored = font.getbbox(mark.text, anchor=mark.anchor)
            baseline = font.getbbox(mark.text, anchor='ls')
            item['x'] = mark.pts[0][0] + anchored[0] - baseline[0]
            item['y'] = mark.pts[0][1] + anchored[1] - baseline[1]
        marks.append(item)
    return marks


def context(project, slide, key, sheet, ground, hand, seconds, settle, channel=None):
    from . import board
    ctx = scenes.context_base(project, channel)
    directory = scenes._directory(project)
    root = Path(ctx['asset_roots']['project_root'])

    def url(path):
        return scenes.ASSETS_URLS['project'] + quote(path.relative_to(root).as_posix())

    marks = svg_marks(sheet.marks, hand)
    photos = [dict(order=p.order, x=p.xy[0], y=p.xy[1],
                   w=p.tile.width, h=p.tile.height, url=url(_asset(directory, p.tile)))
              for p in sheet.photos]
    ctx['fonts'].update(BoardHand='/fonts/' + Path(dg.hand_stack(hand)[0][0]).name,
                        BoardMono='/fonts/' + Path(titles.MONO_STACK[0][0]).name)
    ctx.update(board=board.content(slide), marks=marks, photos=photos,
               ground_url=url(_asset(directory, ground)) if ground is not None else '',
               margin=board.MARGIN, body=asdict(board.BODY),
               beats=board.reveal_plan(sheet, seconds, settle),
               active_order=None, plate=False, settled=False, duration=seconds,
               seed=sheet.seed)
    return ctx


def plates(project, key, ctx, size):
    """Capture and measure each beat once; cache only its occupied pixels."""
    paths, items = [], []
    for order in range(len(ctx['beats'])):
        plate_ctx = {**ctx, 'plate': True, 'settled': True, 'active_order': order}
        digest, html, prepared = scenes._prepare(
            project, f'board/{key}.html', plate_ctx, ctx['duration'], size, FPS,
            ('board-cropped-v1',))
        out = html.with_suffix('.png')
        paths.append(out)
        if not out.exists() or not out.stat().st_size or not out.with_suffix('.bounds.json').exists():
            items.append(dict(clip=digest, url_path=f'/scene/{{token}}/{html.name}',
                              W=prepared['width'], H=prepared['height'],
                              size=size, t=0, alpha=True))
    if items:
        bounds = {}

        def probe(cdp, session, item, t):
            # SVG roots cover the viewport. Measure their painted children,
            # including stroke caps, after fonts load and before this screenshot.
            result = stage._evaluate(cdp, session, """Array.from(
                document.querySelectorAll('.board svg > *'), el => {
                    const r = el.getBoundingClientRect();
                    const pad = parseFloat(getComputedStyle(el).strokeWidth) / 2 + 2;
                    return [r.left-pad, r.top-pad, r.right+pad, r.bottom+pad];
                })""")
            rects = result['result']['value']
            if not rects:
                raise stage.StageError('Board plate has no bounds')
            sx, sy = size[0] / item['W'], size[1] / item['H']
            bounds[item['clip']] = [
                max(0, math.floor(min(r[0] for r in rects) * sx)),
                max(0, math.floor(min(r[1] for r in rects) * sy)),
                min(size[0], math.ceil(max(r[2] for r in rects) * sx)),
                min(size[1], math.ceil(max(r[3] for r in rects) * sy))]

        made = stage.capture_stills(items, paths[0].parent, **ctx['asset_roots'], scene_probe=probe)
        for name, data in made.items():
            box = bounds.get(name)
            if box is None or box[2] <= box[0] or box[3] <= box[1]:
                raise stage.StageError('Board plate has invalid bounds')
            with Image.open(io.BytesIO(data)) as image:
                cropped = io.BytesIO()
                image.crop(box).save(cropped, format='PNG')
            out = paths[0].parent / f'{name}.png'
            _write(out, cropped.getvalue())
            _write(out.with_suffix('.bounds.json'), json.dumps(box).encode())
        if any(not p.exists() or not p.stat().st_size or
               not p.with_suffix('.bounds.json').exists() for p in paths):
            raise stage.StageError('Board plates did not render')
    return [(p, json.loads(p.with_suffix('.bounds.json').read_text())) for p in paths]


def without_scale(extra):
    """Drop a preview's `-vf scale=`: ffmpeg refuses -vf beside -filter_complex,
    and board scenes are already drawn at the preview size."""
    extra = list(extra)
    if '-vf' in extra and extra[extra.index('-vf') + 1].startswith('scale='):
        i = extra.index('-vf')
        del extra[i:i + 2]
    return extra


def render(project, key, ctx, ground, out, *, crf, extra):
    if key == 'diagram':
        from . import diagram_scenes
        return diagram_scenes.render(project, ctx, ground, out, crf=crf, extra=extra)
    # Capture at the actual preview size; composition coordinates stay at 1080p.
    size = (WIDTH, HEIGHT)
    if '-vf' in extra:
        scale = extra[extra.index('-vf') + 1]
        if scale.startswith('scale='):
            size = tuple(map(int, scale.removeprefix('scale=').split(':')))
            extra = without_scale(extra)
    paths = plates(project, key, ctx, size)
    bg = _asset(paths[0][0].parent, ground.resize(size))
    inputs = ['-loop', '1', '-framerate', str(FPS), '-i', str(bg)]
    graph, last = [], '0:v'
    for i, ((path, box), (start, duration)) in enumerate(zip(paths, ctx['beats']), 1):
        inputs += ['-loop', '1', '-framerate', str(FPS), '-i', str(path)]
        # Same quadratic ease-out as diagram.reveal_at(board.reveal_plan(...)).
        progress = f'(1-pow(1-clip((T-{start})/{duration},0,1),2))'
        ink = any(m['order'] == i - 1 and m['kind'] != 'wash' for m in ctx['marks'])
        photo = any(p['order'] == i - 1 for p in ctx['photos'])
        if ink and not photo:
            # Evaluate only the small cached crop, and only while arriving.
            # The soft nib and early opacity ramp echo Pillow's _draw_text.
            feather = max(1, max((m['size'] * .22 * size[0] / WIDTH
                                 for m in ctx['marks'] if m['order'] == i - 1
                                 and m['kind'] == 'text'), default=1))
            alpha = (f'alpha(X,Y)*clip({progress}/0.3,0,1)*'
                     f'clip((({box[2]-box[0]}+{2*feather})*{progress}-X)/{2*feather},0,1)')
            effect = (f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                      f"a='{alpha}':enable='between(t,{start},{start+duration})'")
        else:
            # Photos and washes already fade in Pillow; do not wipe the print.
            effect = f'fade=t=in:st={start}:d={duration}:alpha=1'
        graph.append(f'[{i}:v]format=rgba,{effect}[b{i}]')
        graph.append(f"[{last}][b{i}]overlay={box[0]}:{box[1]}:shortest=1:"
                     f"enable='gte(t,{start})'[v{i}]")
        last = f'v{i}'
    out.parent.mkdir(parents=True, exist_ok=True)
    ffutil.run([*inputs, '-filter_complex_threads', '1', '-filter_complex', ';'.join(graph),
                '-map', f'[{last}]', '-t', str(ctx['duration']),
                *ffutil.video_args(out, crf=crf), *extra,
                '-pix_fmt', 'yuv420p', '-an', str(out)])
    return out

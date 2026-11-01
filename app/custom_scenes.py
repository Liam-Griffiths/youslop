"""Positioned custom slides: capture each element once, animate with ffmpeg."""
from __future__ import annotations

import io
import math
from pathlib import Path
import tempfile
from urllib.parse import quote

from PIL import Image

from . import board_scenes, custom_slide as custom, diagram, ffutil, scenes, stage, titles
from .config import FPS, HEIGHT, WIDTH


def context(root, spec, seconds, hand=custom.DEFAULT_HAND, grain=.5):
    spec = custom.normalise(spec)
    root = Path(root).resolve()
    directory = scenes._directory(root)
    ctx = scenes.context_base()
    ctx['asset_roots']['project_root'] = str(root)

    def url(image):
        path = board_scenes._asset(directory, image)
        return scenes.ASSETS_URLS['project'] + quote(path.relative_to(root).as_posix())

    ground = diagram.ground(spec['background'] or diagram.GROUND, grain)
    orders = sorted({el['order'] for el in spec['elements'] if el['anim'] != 'none'})
    plan = diagram.schedule(len(orders), seconds, spec['reveal'])
    elements = []
    for el in custom._layout(spec):
        start, arrival = (0, 0) if el['anim'] == 'none' else plan[orders.index(el['order'])]
        item = dict(el, start=start, arrival=arrival, image_url='')
        if el['type'] == 'text':
            font, lines, line_h = custom._fit_text(
                el['text'], custom._stack(el['font'], hand), el['_w'], el['_h'],
                custom.SIZE_PX[el['size']])
            # Pillow uses anchor='?t': each line's ink starts at i * line_h.
            # SVG's alphabetic baseline avoids CSS line boxes/half-leading;
            # subtract the ink top relative to that baseline for each line.
            text_lines = [dict(text=line, baseline=i * line_h - font.getbbox(line, anchor='ls')[1])
                          for i, line in enumerate(lines)]
            item.update(lines=lines, text_lines=text_lines, font_size=font.size,
                        line_height=line_h,
                        text_x={'left': 0, 'center': 50, 'right': 100}[el['align']],
                        text_anchor={'left': 'start', 'center': 'middle', 'right': 'end'}[el['align']])
        if el['type'] == 'image' and el.get('local_path'):
            path = (root / el['local_path']).resolve()
            if path.is_relative_to(root) and path.is_file():
                try:
                    with Image.open(path) as image:
                        item['image_url'] = url(image.convert('RGB'))
                except OSError:
                    pass
        if 'color' in el:
            item['color'] = '#%02x%02x%02x' % titles._hex(el['color'])[:3]
        elements.append(item)
    for key in custom.FONT_KEYS:
        ctx['fonts']['Custom' + key] = '/fonts/' + Path(custom._stack(key, hand)[0][0]).name
    ctx.update(elements=elements, ground_url=url(ground), duration=seconds,
               settled=False, plate=False, active_index=None)
    return ctx, ground


def still(spec, hand=custom.DEFAULT_HAND, media_root=None, grain=.5):
    with tempfile.TemporaryDirectory(prefix='custom-') as tmp:
        root = Path(media_root) if media_root else Path(tmp)
        ctx, _ = context(root, spec, custom.DEFAULT_SECONDS, hand, grain)
        ctx['settled'] = True
        return scenes.capture(root, 'slides/custom.html', ctx, t=0, size=(WIDTH, HEIGHT))


def plates(root, ctx, size):
    paths, items, boxes = [], [], {}
    for index, el in enumerate(ctx['elements']):
        plate_ctx = dict(ctx, plate=True, settled=True, active_index=index)
        key, html, prepared = scenes._prepare(
            root, 'slides/custom.html', plate_ctx, ctx['duration'], size, FPS,
            ('custom-element-v1',))
        out = html.with_suffix('.png')
        # Crop in output pixels; the template keeps its 1080p composition.
        sx, sy = size[0] / WIDTH, size[1] / HEIGHT
        box = (math.floor(el['x'] * size[0]), math.floor(el['y'] * size[1]),
               math.ceil(el['x'] * size[0] + el['_w'] * sx),
               math.ceil(el['y'] * size[1] + el['_h'] * sy))
        paths.append((out, box))
        boxes[key] = box
        if not out.exists() or not out.stat().st_size:
            items.append(dict(clip=key, url_path=f'/scene/{{token}}/{html.name}',
                              W=prepared['width'], H=prepared['height'], size=size,
                              t=0, alpha=True))
    if items:
        directory = paths[0][0].parent
        made = stage.capture_stills(items, directory, **ctx['asset_roots'])
        for key, data in made.items():
            with Image.open(io.BytesIO(data)) as image:
                cropped = io.BytesIO()
                image.crop(boxes[key]).save(cropped, format='PNG')
            board_scenes._write(directory / f'{key}.png', cropped.getvalue())
        if any(not p.exists() or not p.stat().st_size for p, _ in paths):
            raise stage.StageError('Custom slide plates did not render')
    return paths


def render(root, ctx, ground, out, *, size=(WIDTH, HEIGHT), fps=FPS, crf=17):
    paths = plates(root, ctx, size)
    bg = board_scenes._asset(paths[0][0].parent, ground.resize(size))
    inputs = ['-loop', '1', '-framerate', str(fps), '-i', str(bg)]
    graph, last = [], '0:v'
    # Pillow paints static elements first, then settles live beats in order.
    indices = sorted(range(len(paths)), key=lambda i: (
        ctx['elements'][i]['anim'] != 'none',
        ctx['elements'][i]['order'] if ctx['elements'][i]['anim'] != 'none' else 0, i))
    for i, index in enumerate(indices, 1):
        path, box = paths[index]
        el = ctx['elements'][index]
        inputs += ['-loop', '1', '-framerate', str(fps), '-i', str(path)]
        x, y = str(box[0]), str(box[1])
        effect = 'format=rgba'
        if el['anim'] != 'none':
            start, arrival = el['start'], el['arrival']
            progress = f'(1-pow(1-clip((T-{start})/{arrival},0,1),2))'
            alpha = f'min(1,1.4*{progress})' if el['anim'] == 'pop' else progress
            effect += (f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*{alpha}':"
                       f"enable='between(t,{start},{start + arrival})'")
            remaining = f'pow(1-clip((t-{start})/{arrival},0,1),2)'
            if el['anim'] == 'rise':
                y += f'+{46 * size[1] / HEIGHT}*{remaining}'
            if el['anim'] in ('fly-left', 'fly-right'):
                dx = (-240 if el['anim'] == 'fly-left' else 240) * size[0] / WIDTH
                x += f'+({dx})*{remaining}'
        graph.append(f'[{i}:v]{effect}[b{i}]')
        graph.append(f"[{last}][b{i}]overlay=x='{x}':y='{y}':shortest=1:"
                     f"enable='gte(t,{el['start']})'[v{i}]")
        last = f'v{i}'
    out.parent.mkdir(parents=True, exist_ok=True)
    # Preview scaling is already applied to plates; never combine -vf with this graph.
    ffutil.run([*inputs, '-filter_complex_threads', '1', '-filter_complex', ';'.join(graph),
                '-map', f'[{last}]', '-t', str(ctx['duration']), '-r', str(fps),
                *ffutil.video_args(out, crf=crf), '-pix_fmt', 'yuv420p', '-an', str(out)])
    return out

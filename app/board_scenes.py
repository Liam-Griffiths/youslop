"""Board scene plates: one browser capture per beat, ffmpeg for motion/holds."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import io
from pathlib import Path
import tempfile
from urllib.parse import quote

from . import diagram as dg, ffutil, scenes, stage, titles
from .config import FPS, HEIGHT, WIDTH


def handles(project, key):
    return (project.style.board_engine != 'pillow' and key != 'diagram'
            and key in ('statement', 'bullets', 'steps', 'versus', 'code',
                        'stat', 'quote', 'taped', 'split')
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


def context(project, slide, key, sheet, ground, hand, seconds, settle, channel=None):
    from . import board
    ctx = scenes.context_base(project, channel)
    directory = scenes._directory(project)
    root = Path(ctx['asset_roots']['project_root'])

    def url(path):
        return scenes.ASSETS_URLS['project'] + quote(path.relative_to(root).as_posix())

    marks = []
    for mark in sheet.marks:
        item = asdict(mark)
        if mark.kind == 'text':
            font = dg.font_for(mark.font, mark.size, hand)
            # Preserve Pillow's anchor placement using the alphabetic baseline.
            anchored = font.getbbox(mark.text, anchor=mark.anchor)
            baseline = font.getbbox(mark.text, anchor='ls')
            item['x'] = mark.pts[0][0] + anchored[0] - baseline[0]
            item['y'] = mark.pts[0][1] + anchored[1] - baseline[1]
        marks.append(item)
    photos = [dict(order=p.order, x=p.xy[0], y=p.xy[1],
                   w=p.tile.width, h=p.tile.height, url=url(_asset(directory, p.tile)))
              for p in sheet.photos]
    ctx['fonts'].update(BoardHand='/fonts/' + Path(dg.hand_stack(hand)[0][0]).name,
                        BoardMono='/fonts/' + Path(titles.MONO_STACK[0][0]).name)
    ctx.update(board=board.content(slide), marks=marks, photos=photos,
               ground_url=url(_asset(directory, ground)),
               margin=board.MARGIN, body=asdict(board.BODY),
               beats=board.reveal_plan(sheet, seconds, settle),
               active_order=None, plate=False, settled=False, duration=seconds)
    return ctx


def plates(project, key, ctx, size):
    paths, items = [], []
    for order in range(len(ctx['beats'])):
        plate_ctx = {**ctx, 'plate': True, 'settled': True, 'active_order': order}
        digest, html, prepared = scenes._prepare(
            project, f'board/{key}.html', plate_ctx, ctx['duration'], size, FPS)
        out = html.with_suffix('.png')
        paths.append(out)
        if not out.exists() or not out.stat().st_size:
            items.append(dict(clip=digest, url_path=f'/scene/{{token}}/{html.name}',
                              W=prepared['width'], H=prepared['height'],
                              size=size, t=0, alpha=True))
    if items:
        made = stage.capture_stills(items, paths[0].parent, **ctx['asset_roots'])
        for name, data in made.items():
            _write(paths[0].parent / f'{name}.png', data)
        if any(not p.exists() or not p.stat().st_size for p in paths):
            raise stage.StageError('Board plates did not render')
    return paths


def without_scale(extra):
    """Drop a preview's `-vf scale=`: ffmpeg refuses -vf beside -filter_complex,
    and board scenes are already drawn at the preview size."""
    extra = list(extra)
    if '-vf' in extra and extra[extra.index('-vf') + 1].startswith('scale='):
        i = extra.index('-vf')
        del extra[i:i + 2]
    return extra


def render(project, key, ctx, ground, out, *, crf, extra):
    # Capture at the actual preview size; composition coordinates stay at 1080p.
    size = (WIDTH, HEIGHT)
    if '-vf' in extra:
        scale = extra[extra.index('-vf') + 1]
        if scale.startswith('scale='):
            size = tuple(map(int, scale.removeprefix('scale=').split(':')))
            extra = without_scale(extra)
    paths = plates(project, key, ctx, size)
    bg = _asset(paths[0].parent, ground.resize(size))
    inputs = ['-loop', '1', '-framerate', str(FPS), '-i', str(bg)]
    graph, last = [], '0:v'
    for i, (path, (start, duration)) in enumerate(zip(paths, ctx['beats']), 1):
        inputs += ['-loop', '1', '-framerate', str(FPS), '-i', str(path)]
        graph.append(f'[{i}:v]format=rgba,fade=t=in:st={start}:d={duration}:alpha=1[b{i}]')
        graph.append(f'[{last}][b{i}]overlay=0:0:shortest=1[v{i}]')
        last = f'v{i}'
    out.parent.mkdir(parents=True, exist_ok=True)
    ffutil.run([*inputs, '-filter_complex_threads', '1', '-filter_complex', ';'.join(graph),
                '-map', f'[{last}]', '-t', str(ctx['duration']),
                *ffutil.video_args(out, crf=crf), *extra,
                '-pix_fmt', 'yuv420p', '-an', str(out)])
    return out

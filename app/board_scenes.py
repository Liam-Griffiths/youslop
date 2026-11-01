"""Board scene plates: one browser capture per beat, ffmpeg for motion/holds."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import io
from pathlib import Path
import tempfile
from urllib.parse import quote

from PIL import Image

from . import diagram as dg, scene_builder, scenes, titles
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


def render(project, key, ctx, ground, out, *, crf, extra):
    return scene_builder.render(project, f'board/{key}.html', ctx, out,
                                seconds=ctx['duration'], size=(WIDTH, HEIGHT),
                                fps=FPS, crf=crf, extra=extra).path

"""Positioned custom slides: capture each element once, animate with ffmpeg."""
from __future__ import annotations

from pathlib import Path
import tempfile
from urllib.parse import quote
import uuid

from PIL import Image

from . import board_scenes, custom_slide as custom, diagram, scene_builder, scenes, titles
from .config import FPS, HEIGHT, WIDTH


def html_sources(root, spec):
    """Expose only resolved image elements, copied as inert PNG assets; never fetch."""
    root = Path(root).resolve()
    sources = []
    for el in (spec or {}).get('elements', []):
        if el.get('type') != 'image' or not el.get('local_path'):
            continue
        path = (root / el['local_path']).resolve()
        if path.is_relative_to(root) and path.is_file():
            try:
                with Image.open(path) as image:
                    asset = board_scenes._asset(scenes._directory(root), image.convert('RGB'))
                sources.append(scenes.ASSETS_URLS['project'] + asset.relative_to(root).as_posix())
            except OSError:
                pass
    return sources


def html_context(root, fragment, spec=None, seconds=custom.DEFAULT_SECONDS, project=None):
    from . import sanitise
    ctx = scenes.context_base(project)
    sources = html_sources(root, spec)
    ctx.update(custom_html=sanitise.clean(fragment, sources), html_sources=sources,
               duration=seconds, plate=False)
    ctx['asset_roots']['project_root'] = str(Path(root).resolve())
    return ctx


def html_candidate(fragment, dest, spec, *, motion='reveal', seconds=custom.DEFAULT_SECONDS, project=None):
    seconds = max(2., min(20., float(seconds)))
    ctx = html_context(dest, fragment, spec, seconds, project)
    stem = 'custom_' + uuid.uuid4().hex[:10]
    poster = dest / (stem + '.png')
    poster.write_bytes(scenes.capture(dest, 'slides/custom.html', ctx, t=0, size=(WIDTH, HEIGHT)))
    out = poster
    if motion != 'still':
        out = dest / (stem + '.mp4')
        render(dest, ctx, None, out)
    return dict(id=stem, provider='custom', title='Custom HTML slide',
                kind='image' if motion == 'still' else 'video',
                local_path='media/' + out.name, thumb='media/' + poster.name,
                width=WIDTH, height=HEIGHT, duration=0 if motion == 'still' else seconds,
                custom=spec, custom_html=ctx['custom_html'])


def context(root, spec, seconds, hand=custom.DEFAULT_HAND, grain=.5, *, measure_only=False):
    spec = custom.normalise(spec)
    root = Path(root).resolve()
    directory = scenes._directory(root)
    ctx = scenes.context_base()
    ctx['asset_roots']['project_root'] = str(root)

    def url(image):
        path = board_scenes._asset(directory, image)
        return scenes.ASSETS_URLS['project'] + quote(path.relative_to(root).as_posix())

    ground = None if measure_only else diagram.ground(spec['background'] or diagram.GROUND, grain)
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
    # Match Pillow's static-first, then reveal-order paint stack.
    elements.sort(key=lambda el: (el['anim'] != 'none', el['order'] if el['anim'] != 'none' else 0))
    for key in custom.FONT_KEYS:
        ctx['fonts']['Custom' + key] = '/fonts/' + Path(custom._stack(key, hand)[0][0]).name
    ctx.update(elements=elements, ground_url=url(ground) if ground is not None else '', duration=seconds,
               settled=False, plate=False, active_index=None)
    return ctx, ground


def still(spec, hand=custom.DEFAULT_HAND, media_root=None, grain=.5):
    with tempfile.TemporaryDirectory(prefix='custom-') as tmp:
        root = Path(media_root) if media_root else Path(tmp)
        ctx, _ = context(root, spec, custom.DEFAULT_SECONDS, hand, grain)
        ctx['settled'] = True
        return scenes.capture(root, 'slides/custom.html', ctx, t=0, size=(WIDTH, HEIGHT))


def render(root, ctx, ground, out, *, size=(WIDTH, HEIGHT), fps=FPS, crf=17):
    return scene_builder.render(root, 'slides/custom.html', ctx, out,
                                seconds=ctx['duration'], size=size, fps=fps, crf=crf).path

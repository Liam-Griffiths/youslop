"""Cheap, approximate graphics checks. Never draw a block or decode video."""
from copy import deepcopy
from PIL import Image, ImageColor

from . import kinds
from . import block_overlays, blocks, render, scenes, store


def _base_frame(project, lead, seconds, size, cache):
    """Read only a chosen local still or a manifest-owned clip thumbnail.

    seconds is relative to the held picture, not the overlay's paragraph.
    Clip thumbs are approximate samples; never use composited segment proxies.
    """
    lead = render._picture_source(project, lead)
    if lead.cues.get('blocks') or (kinds.kind_for(project, lead) == 'stage' and lead.shot):
        return None
    candidate = next((c for c in lead.candidates if c['id'] == lead.chosen_id), {})
    path, sample, unpad = None, 0., None
    if candidate.get('provider') == 'footage':
        from . import footage
        try:
            shoot = footage.load(candidate['shoot_id'])
            clip = next(c for c in shoot.clips if c.id == candidate['clip_id'])
            source = next(f for f in shoot.files if f.id == clip.file)
            a, b = candidate['in_s'], candidate['out_s']
            if not 0 <= a < b <= source.duration:
                return None
            target = min(b, a + max(0, seconds))
            times = (clip.in_s, (clip.in_s + clip.out_s)/2, max(clip.in_s, clip.out_s - 1/30))
            samples = [(abs(t-target), t, name) for t, name in zip(times, clip.thumbs) if a <= t < b]
            if not samples:
                return None
            _, sample, name = min(samples)
            path = footage.media_path(shoot.id, 'thumbs', name)
            unpad = (source.width, source.height)
        except (KeyError, OSError, ValueError, StopIteration):
            return None
    else:
        # Remote thumb URLs are deliberately ignored; no source downloads.
        for name in (candidate.get('local_path'), candidate.get('thumb')):
            if name and not str(name).startswith(('http:', 'https:', '/api/')):
                possible = store.project_dir(project.id) / name
                if possible.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'} and possible.is_file():
                    path = possible
                    break
    if path is None:
        return None
    focal = candidate.get('focal') or [.5, .5]
    key = (str(path), sample, tuple(focal), size)
    if key not in cache:
        try:
            with Image.open(path) as image:
                image = image.convert('RGB')
                if unpad and all(unpad):
                    scale = min(image.width/unpad[0], image.height/unpad[1])
                    w, h = round(unpad[0]*scale), round(unpad[1]*scale)
                    x, y = (image.width-w)//2, (image.height-h)//2
                    image = image.crop((x, y, x+w, y+h))
                scale = max(size[0]/image.width, size[1]/image.height)
                image = image.resize((max(size[0], round(image.width*scale)),
                                      max(size[1], round(image.height*scale))))
                fx, fy = focal if len(focal) == 2 else (.5, .5)
                x = round(min(max(fx*image.width-size[0]/2, 0), image.width-size[0]))
                y = round(min(max(fy*image.height-size[1]/2, 0), image.height-size[1]))
                cache[key] = image.crop((x, y, x+size[0], y+size[1]))
        except (OSError, ValueError):
            cache[key] = None
    return cache[key]


def _geometry(project, item, block, context):
    """Reuse scene text measurements, with no Chromium even on explicit Check."""
    block = deepcopy(block)
    block['meta']['duration'] = dict(mode='range', min=0)
    template, ctx = blocks.prepare(item['block_id'], item['vars'],
        '9:16' if project.aspect == 'portrait' else '16:9', item['dur'],
        context=context, _block=block, overlay=True, position=item['position'])
    rows = scenes.measure_many(project, [(template, ctx, 0)], render=False)[0]
    return [(r['x']/ctx['width'], r['y']/ctx['height'],
             (r['x']+r['width'])/ctx['width'], (r['y']+r['height'])/ctx['height'])
            for r in rows if r.get('width', 0) > 0 and r.get('height', 0) > 0]


def _region(position, portrait):
    """Position regions are estimates for sampling/collisions, never text bounds."""
    x0, x1 = (.12, .82 if portrait else .70) if position.endswith('left') else (
        (.18 if portrait else .30, .88) if position.endswith('right') else (.12, .82 if portrait else .88))
    y0, y1 = (.18, .45) if position.startswith('top') else (
        (.50 if portrait else .60, .76 if portrait else .87) if position.startswith('bottom') else (.30, .70))
    return x0, y0, x1, y1


def _intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _luma(rgb):
    return sum(weight * (v/255/12.92 if v/255 <= .04045 else ((v/255+.055)/1.055)**2.4)
               for weight, v in zip((.2126, .7152, .0722), rgb))


def _low_contrast(image, box, ink, panel):
    fg = _luma(ImageColor.getrgb(ink))
    if panel is not None:
        pixels = [panel]
    else:
        region = image.crop(tuple(round(v*s) for v, s in zip(box, image.size*2)))
        if region.width <= 0 or region.height <= 0:
            return False
        sample = region.resize((16, 16))
        pixels = [sample.getpixel((x, y)) for y in range(16) for x in range(16)]
    return sum((max(fg, bg)+.05)/(min(fg, bg)+.05) < 3
               for bg in map(_luma, pixels)) / len(pixels) > .1


def run(project, sb):
    from .check import _finding
    graphics = sb.get('layers', {}).get('graphics', [])
    if not graphics:
        return []
    out, cache = [], {}
    library, context = blocks.discover(), scenes.context_base(project)
    colors = context['vars']
    portrait = project.aspect == 'portrait'
    size = (270, 480) if portrait else (480, 270)
    paras = {p['id']: p for p in sb['paragraphs']}
    slides = {s.id: s for s in project.slides}
    for seg in sb['segments']:
        if seg['type'] != 'picture':
            continue
        lead = slides[seg['lead']]
        for q in seg['paragraphs']:
            p = paras[q['id']]
            rows = {r['id']: r for r in graphics if r['sid'] == p['id']}
            if not rows:
                continue
            for item in block_overlays.resolved(p['take'], p.get('overlays', []), q['duration']):
                span = rows.get(item['id'])
                if not span:
                    continue  # Camera and drawn-cut paths are not paragraph graphics.
                def finding(code, level, msg):
                    return _finding(code, level, span['t0'], p['id'], msg,
                                    overlay_id=item['id'])
                if item['src'] == 'est':
                    out.append(finding('overlay_anchor_estimated', 'P2',
                        'Graphic uses an estimated word anchor; verify its timing.'))
                block = library[item['block_id']]
                boxes = _geometry(project, item, block, context)
                region = _region(item['position'], portrait)
                # Without cached text bounds the position region stands in; the
                # overlap message says so rather than adding a note per graphic.
                inset = block['meta']['safe_areas']['title']
                safe = (inset, max(inset, .15) if portrait else inset,
                        min(1-inset, .85) if portrait else 1-inset,
                        min(1-inset, .8) if portrait else 1-inset)
                if any(b[0] < safe[0] or b[1] < safe[1] or b[2] > safe[2] or b[3] > safe[3] for b in boxes):
                    out.append(finding('overlay_safe_area', 'P1',
                        'Graphic text extends outside the block title safe area or portrait UI exclusions.'))
                for lane in ('titles', 'captions'):
                    for other in sb['layers'].get(lane, []):
                        if max(span['t0'], other['t0']) >= min(span['t1'], other['t1']):
                            continue
                        # Current title/caption band; use explicit normalised bounds when supplied.
                        band = other.get('bounds', (.1, .68, .9, .90))
                        if any(_intersects(b, band) for b in boxes or [region]):
                            out.append(finding('overlay_overlap', 'P1',
                                f'Graphic text overlaps {lane}: {other["text"].rstrip(".")}.'
                                + ('' if boxes else ' Placement is estimated from the position; text bounds were not measured.')))
                            break
                ink = colors.get('ink', block['meta'].get('default_colors', {}).get('ink', '#F2F2F2'))
                # Overlays that declare `overlay.panel` draw their text on an opaque
                # panel mixed from the resolved bg and ink (95%/5%): their contrast
                # is ink against the panel, whatever is underneath.
                panel = image = None
                if (block['meta'].get('overlay') or {}).get('panel'):
                    bg = ImageColor.getrgb(colors['bg'])
                    panel = tuple(round(.95*a+.05*b) for a, b in zip(bg, ImageColor.getrgb(ink)))
                else:
                    midpoint = (span['t0']+span['t1'])/2
                    image = _base_frame(project, lead, midpoint-seg['paragraphs'][0]['start'], size, cache)
                    if image is None:
                        out.append(finding('overlay_contrast_unmeasured', 'P2',
                            'Graphic contrast was not measured: no cheap base still or clip thumbnail is available.'))
                        continue
                if any(_low_contrast(image, b, ink, panel) for b in boxes or [region]):
                    out.append(finding('overlay_contrast', 'P1',
                        'Graphic text has low estimated contrast against its panel or sampled base picture (under 3:1).'))
    return out

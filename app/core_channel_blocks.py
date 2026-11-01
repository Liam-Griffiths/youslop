"""Core Channel layouts: bounded copy, local native pictures, sponsor beat timing."""
import math
from pathlib import Path

from .core_explainer_blocks import media_path

IDS = ('subscribe_card', 'next_video', 'sponsor_short', 'sponsor_long')


def layout(ref, v, ctx):
    portrait = ctx['height'] > ctx['width']
    d = dict(x=130 if portrait else 230, w=756 if portrait else 1460,
             top=300 if portrait else 120, media_versions={})

    def picture(key, url):
        path = media_path(url, ctx)
        stat = Path(path).stat()
        d['media_versions'][key] = [stat.st_mtime_ns, stat.st_size]
        return path

    if ref == 'subscribe_card':
        d['avatar'] = picture('avatar', v['avatar']) if v['avatar'] else ''
    if ref == 'next_video':
        d['picture'] = picture('picture', v['picture'])
    if ref.startswith('sponsor_'):
        s = ctx['sponsor']
        if s['logo']:
            picture('logo', s['logo'])  # Captured logo also invalidates on file changes.
        # Clamp all arrivals to leave at least a second of settled copy. Preserve
        # original beat/confidence metadata; only presentation times are bounded.
        d['beats'] = {key: min(max(0, t), ctx['duration']-1)
                      for key, t in ctx['beats'].items()}
        if ref == 'sponsor_long':
            d['slots'] = []
            intro = min(ctx['duration']*.25, max(1.5, d['beats']['learn']))
            end = min(ctx['duration']-1, max(intro+ctx['duration']*.3, d['beats']['link']))
            d['intro'] = intro
            for key, limit in (('made', intro*.3), ('brand', intro-.6), ('learn', intro*.6)):
                d['beats'][key] = min(d['beats'][key], limit)
            span = (end-intro)/len(s['media'])
            for i, item in enumerate(s['media']):
                if item['kind'] != 'image' or not item['src']:
                    raise ValueError('media: requires 2..4 local picture slots')
                original = ctx.get('media', v['media'])[i]
                focal = [original.get('focal_x', .5), original.get('focal_y', .5)]
                if any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in focal):
                    raise ValueError('media focal_x/y: requires fractions in 0..1')
                start = intro+i*span
                d['slots'].append(dict(src=item['src'], path=picture(str(i), item['src']),
                                       caption=item['caption'], focal=focal, start=start,
                                       duration=span if i < len(s['media'])-1 else ctx['duration']-start))
    return d

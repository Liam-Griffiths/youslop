"""Bounded, local-only layouts for the seven core explainer blocks."""
import math
from pathlib import Path
from urllib.parse import unquote

from . import paths

IDS = ('step_list', 'callout_arrow', 'document_highlight', 'map_highlight',
       'before_after_wipe', 'split_comparison', 'labelled_diagram')


def media_path(url, ctx):
    """Resolve declared scene/static images for native ffmpeg; never fetch."""
    if url.startswith('/static/'):
        root, rel = paths.resource_root() / 'static', url[len('/static/'):]
    else:
        parts = url.split('/', 4)
        kind = parts[3] if len(parts) == 5 else ''
        roots = dict(ctx.get('asset_roots', {}), assets_root=ctx['block_assets_root'])
        root = roots.get(kind + '_root')
        if kind not in ('project', 'channel', 'assets') or not root:
            raise ValueError('picture: requires a local static or scene asset URL with a configured root')
        root, rel = Path(root), parts[4]
    root = root.resolve()
    target = (root / unquote(rel)).resolve()
    if target == root or not target.is_relative_to(root) or not target.is_file():
        raise ValueError('picture: local image is missing or outside its asset root')
    return str(target)


def layout(ref, v, ctx):
    portrait = ctx['height'] > ctx['width']
    x, w, top, bottom = (130, 756, 600, 1400) if portrait else (230, 1460, 350, 860)
    d = dict(x=x, w=w, top=top, bottom=bottom, header=300 if portrait else 120,
             footer=1430 if portrait else 888, rows=[])
    rows = v.get('rows', [])
    if ref in ('step_list', 'labelled_diagram'):
        lo, hi = (2, 5) if ref == 'step_list' else (1, 3)
        if not lo <= len(rows) <= hi:
            raise ValueError(f'rows: {ref} requires {lo}..{hi} rows')
        for i, row in enumerate(rows):
            label = row.get('label')
            limit = 48 if ref == 'step_list' else 32
            if not isinstance(label, str) or not label.strip() or len(label) > limit:
                raise ValueError(f'rows[{i}].label: requires 1..{limit} characters')
            if ref == 'labelled_diagram':
                for key in ('x', 'y'):
                    n = row.get(key)
                    if type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1:
                        raise ValueError(f'rows[{i}].{key}: requires a fraction in 0..1')
        d['rows'] = rows
        d['gap'] = (bottom-top)/len(rows)
    if ref != 'step_list':
        d['media_versions'] = {}
        for key in ('picture', 'after'):
            if key in v:
                d[key] = media_path(v[key], ctx)
                stat = Path(d[key]).stat()
                d['media_versions'][key] = [stat.st_mtime_ns, stat.st_size]
        reserve = (290 if portrait else 0) if ref == 'labelled_diagram' else 90
        d['ph'] = bottom-top-reserve
        d['pw'] = w if portrait or ref != 'labelled_diagram' else 860
        if ref == 'labelled_diagram':
            d.update(label_x=x if portrait else x+900,
                     label_y=top+d['ph']+20 if portrait else top,
                     label_w=w if portrait else 560, label_gap=90 if portrait else 160)
        if ref in ('document_highlight', 'map_highlight') and (ref != 'map_highlight' or v['mode'] == 'region'):
            if v['w'] <= 0 or v['h'] <= 0 or v['x']+v['w'] > 1 or v['y']+v['h'] > 1:
                raise ValueError('region: positive w/h and x+w, y+h must fit within 1')
        d['inner_w'], d['inner_h'] = w-32, d['ph']-32
        if ref == 'callout_arrow':
            if (v['x'], v['y']) == (v['from_x'], v['from_y']):
                raise ValueError('arrow: target and tail must differ')
            d['angle'] = math.degrees(math.atan2((v['y']-v['from_y'])*d['inner_h'],
                                                (v['x']-v['from_x'])*d['inner_w']))
    if ref == 'split_comparison':
        d['panels'] = [dict(x=x, y=top, w=w if portrait else (w-32)/2,
                            h=(bottom-top-32)/2 if portrait else bottom-top),
                       dict(x=x if portrait else x+(w+32)/2,
                            y=top+(bottom-top+32)/2 if portrait else top,
                            w=w if portrait else (w-32)/2,
                            h=(bottom-top-32)/2 if portrait else bottom-top)]
    return d

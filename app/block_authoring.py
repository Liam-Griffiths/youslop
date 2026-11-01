"""Clean-room block authoring; lint and scaffolding do not need Chromium."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import re
import tempfile

from PIL import Image

from . import blocks, scene_builder, scenes, stage

TEMPLATE = '''{% extends "_base.html" %}
{% block head %}
<style>
/* Instrument tokens come from _base.html; keep text in the declared safe area. */
body { width: {{ width }}px; height: {{ height }}px; }
.copy { position:absolute; left:15%; right:22%; top:20%; height:55%;
 display:flex; align-items:center; }
h1 { font:700 64px/1.15 Inter,sans-serif; overflow-wrap:anywhere; width:100%; }
</style>
{% endblock %}
{% block body %}
<!-- One layer per panel or line; motion is compiled by the builder. -->
<div class="copy clip" data-start="0" data-duration="{{ duration }}"
 data-layer="copy" data-motion="rise"><h1 data-var-text="title">{{ vars.title }}</h1></div>
{% endblock %}
'''


def new(block_id):
    if not re.fullmatch(r'[a-z0-9_][a-z0-9_-]*', block_id):
        raise ValueError('invalid block id')
    root = blocks.USER_DIR / block_id
    # mkdir refuses existing blocks; never overwrite authored work.
    root.mkdir(parents=True, exist_ok=False)
    meta = dict(id=block_id, name=block_id.replace('_', ' ').replace('-', ' ').title(),
                kind='segment', version='1.0.0', licence='GPL-3.0-or-later',
                aspects={a: 'block.html' for a in ('16:9', '9:16', '1:1')},
                duration=dict(mode='fixed', seconds=3),
                variables=dict(title=dict(type='text', default='A new perspective', max_length=80)),
                fonts=['/fonts/Inter-Bold.ttf'], assets=[], beats={},
                safe_areas=dict(title=.1, action=.05))
    (root / 'block.json').write_text(json.dumps(meta, indent=2) + '\n')
    (root / 'block.html').write_text(TEMPLATE)
    return root


def samples(meta):
    """Wide glyphs also stress a single unbroken word at the declared limit."""
    return {key: 'W' * spec['max_length'] if spec['type'] == 'text' else spec['default']
            for key, spec in meta['variables'].items()}


def lint(block_id):
    block = blocks.discover().get(block_id)
    if block is None:
        raise ValueError(f'unknown block: {block_id}')
    meta = block['meta']
    errors = []
    for aspect in meta['aspects']:
        template, ctx = blocks.prepare(block_id, samples(meta), aspect)
        errors.extend(f'{aspect}: {e}' for e in scenes.lint(
            scenes.render_html(template, ctx), asset_root=ctx['block_assets_root']))
    return errors


# Run after fonts/__ready and seek. Use layout dimensions for overflow even when
# an entrance preset temporarily makes the text transparent or transforms it.
MEASURE = r'''(() => {
 const errors = [], W = document.documentElement.dataset.width * 1,
 H = document.documentElement.dataset.height * 1;
 const rgb = s => (s.match(/[\d.]+/g) || []).map(Number);
 const lum = c => c.slice(0,3).map(x => { x /= 255;
   return x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4;
 }).reduce((s,x,i) => s+x*[.2126,.7152,.0722][i],0);
 const elements = [...document.querySelectorAll('body *')].filter(el =>
   el.matches('[data-var-text]') || (!el.children.length && el.textContent.trim() &&
     !el.matches('script,style') && !el.closest('[data-var-text]')));
 for (const el of elements) {
   const key = el.dataset.varText || Object.keys(window.__vars).find(k =>
     String(window.__vars[k]) === el.textContent.trim()) || el.tagName,
   r = el.getBoundingClientRect(), p = el.parentElement,
   b = p.getBoundingClientRect(), css = getComputedStyle(el);
   if (el.scrollWidth > el.clientWidth+1 || el.scrollHeight > el.clientHeight+1 ||
       r.left < b.left-1 || r.right > b.right+1 || r.top < b.top-1 || r.bottom > b.bottom+1)
     errors.push(key+': text overflow');
   const inset = SAFE;
   if (r.left < W*inset-1 || r.right > W*(1-inset)+1 ||
       r.top < H*inset-1 || r.bottom > H*(1-inset)+1 ||
       (H > W && (r.top < H*.15 || r.bottom > H*.8 || r.right > W*.85)))
     errors.push(key+': outside title safe area / Shorts UI zones');
   let node = el, bg;
   while (node) {
     const c = rgb(getComputedStyle(node).backgroundColor);
     if (c.length === 3 || c[3] === 1) { bg = c; break; }
     node = node.parentElement;
   }
   const fg = rgb(css.color);
   if (!bg || fg.length < 3 || (fg.length > 3 && fg[3] !== 1))
     errors.push(key+': contrast needs an opaque foreground and background');
   else {
     const a = lum(fg), b = lum(bg), ratio = (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
     const large = parseFloat(css.fontSize) >= 24 ||
       (parseFloat(css.fontSize) >= 18.66 && parseInt(css.fontWeight) >= 700);
     if (ratio < (large ? 3 : 4.5)) errors.push(key+': insufficient contrast');
   }
 }
 return errors;
})()'''


def _pixels(encoded):
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as im:
        return im.convert('RGBA').tobytes()


def check(block_id, *, static_only=False, report=lambda aspect, stats: None):
    errors = lint(block_id)
    if errors or static_only:
        return errors
    meta = blocks.discover()[block_id]['meta']
    with tempfile.TemporaryDirectory(prefix='corkbored-check-') as directory:
        for aspect in meta['aspects']:
            template, ctx = blocks.prepare(block_id, samples(meta), aspect)
            try:
                stats = scene_builder.inspect(Path(directory), template, ctx, seconds=ctx['duration'],
                    size=(ctx['width']//4, ctx['height']//4), fps=ctx['fps'])
                report(aspect, stats)
            except ValueError as exc:
                errors.append(f'{aspect}: {exc}')
                continue
            html = Path(directory) / 'block.html'
            html.write_text(scenes.render_html(template, ctx))
            def probe(cdp, session, item, t):
                found = stage._evaluate(cdp, session, MEASURE.replace('SAFE', str(meta['safe_areas']['title'])))
                errors.extend(f'{aspect}: {e}' for e in found['result']['value'])
                def shot():
                    return _pixels(cdp.send('Page.captureScreenshot',
                        {'format':'png', 'fromSurface':True}, session)['data'])
                first = shot()
                stage._evaluate(cdp, session, 'window.__seek(0)')
                stage._evaluate(cdp, session, f'window.__seek({t})')
                if first != shot():
                    errors.append(f'{aspect}: seek is nondeterministic')
            stage._run_cdp(dict(scene_root=directory, assets_root=ctx['block_assets_root'],
                items=[dict(url_path='/scene/{token}/block.html', W=ctx['width'], H=ctx['height'],
                            t=ctx['duration']/2, size=(ctx['width']//4, ctx['height']//4))]),
                lambda m: None, scene_probe=probe)
    return errors


def preview(block_id, out, *, aspect='16:9', values=None, seconds=None, hero=None):
    """One short quarter-size clip, one poster and six labeled frames."""
    from .review import sheet
    template, ctx = blocks.prepare(block_id, values, aspect, seconds)
    duration = ctx['duration']
    hero = duration/2 if hero is None else hero
    if not 0 <= hero < duration:
        raise ValueError('hero time must be inside block duration')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    size = (ctx['width']//4, ctx['height']//4)
    with tempfile.TemporaryDirectory(prefix='corkbored-preview-') as directory:
        root = Path(directory)
        (out / 'preview.png').write_bytes(scenes.capture(root, template, ctx, t=hero, size=size))
        rows = []
        for i in range(6):
            t = duration * i/6
            path = root / f'frame-{i}.png'
            path.write_bytes(scenes.capture(root, template, ctx, t=t, size=size))
            rows.append(dict(path=path, t=t, why=block_id))
        sheet(rows, out / 'sheet.png', cols=3)
        scene_builder.render(root, template, ctx, out / 'preview.mp4',
                             seconds=duration, size=size, fps=ctx['fps'], crf=18)
    return out

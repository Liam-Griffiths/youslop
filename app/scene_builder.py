"""Layer plates captured once; bounded, script-file ffmpeg composition."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import io
import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile

from PIL import Image

from . import ffutil, scenes, stage

MOTIONS = json.loads((scenes.SCENE_DIR / 'motion.json').read_text())
log = logging.getLogger(__name__)


@dataclass
class Result:
    path: Path
    stats: dict = field(default_factory=dict)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        f.write(data)
    tmp.replace(path)


_PROBE = r"""(() => {
 const root = document.querySelector('[data-composition-id]');
 const layers = [...document.querySelectorAll('[data-layer]')];
 if (layers.some(e => e.parentElement.closest('[data-layer]'))) throw Error('Nested data-layer');
 const style = e => {const cs=getComputedStyle(e); return [...cs].filter(k=>k!=='visibility').map(k => [k,cs.getPropertyValue(k)]);};
 // Computed style follows from the stylesheet rules plus each element's own markup
 // and its ancestors' tags/classes/inline styles, so sign with those (cheap) unless
 // a rule depends on sibling position; then serialise every computed style (slow).
 const rules = [...document.styleSheets].map(sheet => {try {return [...sheet.cssRules].map(r=>r.cssText).join('\n');} catch (err) {return sheet.href || '';}});
 const positional = rules.some(t => /:(nth|first|last|only)-|[+~]\s*[^=\s]/.test(t.replace(/\{[^}]*\}/g,'{}')));
 const chain = e => {const out=[]; for (let n=e.parentElement; n; n=n.parentElement) out.push([n.tagName,n.className?.baseVal ?? n.className,n.getAttribute('style')||'']); return out;};
 const strip = h => h.replace(/ data-(layer|ground|steps|start|duration|motion[^ =]*)="[^"]*"/g,'').replace(/visibility:\s*(hidden|visible);?/g,'');
 const signature = e => positional ? [strip(e.outerHTML), [e,...e.querySelectorAll('*')].map(style)]
   : [strip(e.outerHTML), chain(e).map(c=>[c[0],c[1],strip(c[2])]), rules.length];
 const screens = [...document.querySelectorAll('[data-screen]')].map(e => ({
   id:e.dataset.screen, start:Number(e.dataset.start), duration:Number(e.dataset.duration),
   world:e.dataset.world === 'true', signature:[e.outerHTML,style(e)],
   media:[...e.querySelectorAll('[data-media]:not([data-layer])')].map(n=>{const r=n.getBoundingClientRect();return {
     path:n.dataset.media, video:n.dataset.video==='true', time:Number(n.dataset.mediaTime),
     dim:Number(n.dataset.mediaDim ?? .53), focal:JSON.parse(n.dataset.mediaFocal || '[0.5,0.5]'), blur:Number(n.dataset.mediaBlur || 0),
     wash:JSON.parse(n.dataset.mediaWash || 'null'), grayscale:n.dataset.mediaGrayscale==='true', box:[r.left,r.top,r.right,r.bottom]};}),
   camera:e.dataset.camera ? JSON.parse(e.dataset.camera) : undefined}));
 const row = (e,i,ground=false) => {
   let r=e.getBoundingClientRect();
   if (ground) {
     // Ground plates never move, so take in children painted outside the box
     // (e.g. an axis label hung off a 1px rule).
     const rects=[r,...[...e.querySelectorAll('*')].map(n=>n.getBoundingClientRect())].filter(b=>b.width>0&&b.height>0);
     if (rects.length) r={left:Math.min(...rects.map(b=>b.left)),top:Math.min(...rects.map(b=>b.top)),
       right:Math.max(...rects.map(b=>b.right)),bottom:Math.max(...rects.map(b=>b.bottom))};
   }
   const painted = e.dataset.bounds ? [...e.querySelectorAll(e.dataset.bounds)] :
     (e instanceof SVGElement ? [...e.querySelectorAll('text,path,rect,polyline,circle,image')] : []);
   if (painted.length) {
     const boxes=painted.map(n=>{ const b=n.getBoundingClientRect();
       const pad=n instanceof SVGElement ? parseFloat(getComputedStyle(n).strokeWidth)/2+2 : 0;
       return [b.left-pad,b.top-pad,b.right+pad,b.bottom+pad]; });
     r={left:Math.min(...boxes.map(b=>b[0])),top:Math.min(...boxes.map(b=>b[1])),
        right:Math.max(...boxes.map(b=>b[2])),bottom:Math.max(...boxes.map(b=>b[3]))};
   }
   return {id:e.dataset.layer, index:i, screen:e.closest('[data-screen]')?.dataset.screen || '',
     start:Number(e.dataset.start || 0), duration:Number(e.dataset.duration || root.dataset.duration),
     motion:e.dataset.motion || e.dataset.anim || 'none', arrival:Number(e.dataset.motionDuration || 0.6),
     ease:e.dataset.motionEase, y:e.dataset.motionY, feather:Number(e.dataset.motionFeather || 1),
     exit:Number(e.dataset.motionExit || 0), capture:e.dataset.capture,
     steps:JSON.parse(e.dataset.steps || '[]'),
     atlas:Number(e.dataset.atlas || 1), pathKeys:JSON.parse(e.dataset.path || '[]'),
     clip:JSON.parse(e.dataset.clip || 'null'), native:e.dataset.media || '',
     video:e.dataset.video==='true', time:Number(e.dataset.mediaTime || 0),
     dim:Number(e.dataset.mediaDim ?? 1), focal:JSON.parse(e.dataset.mediaFocal || '[0.5,0.5]'), blur:Number(e.dataset.mediaBlur || 0),
     wash:JSON.parse(e.dataset.mediaWash || 'null'), grayscale:e.dataset.mediaGrayscale==='true',
     box:[r.left,r.top,r.right,r.bottom], signature:signature(e)};
 };
 const rows = layers.map(row);
 const grounds = [...document.querySelectorAll('[data-ground]')].map((e,i)=>row(e,i,true));
 const clone = document.body.cloneNode(true);
 clone.querySelectorAll('[data-layer], [data-screen], script').forEach(e=>e.remove());
 return {layers:rows, grounds, screens, rules, ground:[clone.outerHTML,style(document.body)],
   camera:JSON.parse(root.dataset.camera || '[]'), budget:Number(root.dataset.budget || 0.1)};
})()"""


_PLACED = re.compile(r'(?<![\w-])(left|top)\s*:\s*-?[\d.]+px\s*;?\s*')


def _unplaced(signature):
    """The signature without the root element's own left/top (its position)."""
    if not isinstance(signature, list) or not signature or not isinstance(signature[0], str):
        return signature
    markup, *rest = signature
    head, sep, tail = markup.partition('>')
    return [_PLACED.sub('', head) + sep + tail, *rest]


def _value(cdp, session, js):
    return stage._evaluate(cdp, session, js)['result'].get('value')


def _world_bounds(keys, width, height, scale, density=None):
    """Conservative swept view, rasterised 1:1 at the closest camera zoom."""
    _camera(keys, 't', world=True)
    def bounds(axis, extent):
        edges = []
        for k in keys:
            edges.extend([k[axis]-extent/k['zoom']/2, k[axis]+extent/k['zoom']/2])
        for a,b in zip(keys,keys[1:]):
            delta, dz = b[axis]-a[axis], b['zoom']-a['zoom']
            for sign in (-1,1):
                if delta and dz and sign*extent*dz/(2*delta)>0:
                    zoom = math.sqrt(sign*extent*dz/(2*delta))
                    u = (zoom-a['zoom'])/dz
                    if 0<u<1:
                        edges.append(a[axis]+delta*u+sign*extent/zoom/2)
        return min(edges), max(edges)
    left,right = bounds('x',width)
    top,bottom = bounds('y',height)
    density = density if density is not None else scale*max(k['zoom'] for k in keys)
    # All screens share a pixel grid, so settled plates need no resampling.
    left, top = math.floor(left*density)/density, math.floor(top*density)/density
    w,h = right-left,bottom-top
    # Match output aspect exactly, so zoompan never distorts the world.
    divisor = math.gcd(width, height)
    aw, ah = width//divisor, height//divisor
    units = math.ceil(max(w*density/aw, h*density/ah))
    return left, top, density, aw*units, ah*units


def _plan(data, seconds, fps):
    if not math.isfinite(data['budget']) or not 0 <= data['budget'] <= 1:
        raise ValueError('capture budget must be between 0 and 1')
    screens = data['screens'] or [dict(id='', start=0, duration=seconds)]
    end = 0
    for screen in screens:
        a, d = screen['start'], screen['duration']
        if not all(math.isfinite(v) for v in (a, d)) or abs(a-end) > 1/fps/100 or d <= 0:
            raise ValueError('screens must partition the segment in time')
        end = a+d
    if abs(end-seconds) > 1/fps/100 or len({s['id'] for s in screens}) != len(screens):
        raise ValueError('screens must have unique ids and cover the segment')
    used, ids = 0, set()
    for layer in data['layers']:
        name = layer['id']
        if not name or name in ids or layer['motion'] not in MOTIONS:
            raise ValueError(f'invalid layer or motion: {name}')
        ids.add(name)
        screen = next((s for s in screens if s['id'] == layer['screen']), None)
        if screen is None and layer['screen'] == '':
            screen = dict(duration=seconds)
        if screen is None:
            raise ValueError(f'layer {name}: unknown screen')
        for key in ('start', 'duration', 'arrival'):
            if not math.isfinite(layer[key]) or layer[key] < 0:
                raise ValueError(f'layer {name}: invalid {key}')
        if layer['duration'] <= 0 or layer['arrival'] <= 0 or layer['start'] >= screen['duration']:
            raise ValueError(f'layer {name}: invalid timing')
        clip = layer.get('clip')
        if clip is not None and (len(clip) != 4 or not all(math.isfinite(v) for v in clip) or clip[2] <= clip[0] or clip[3] <= clip[1]):
            raise ValueError(f'layer {name}: invalid clip rectangle')
        if layer.get('capture') == 'frames':
            used += math.ceil(min(layer['arrival'], layer['duration']) * fps)
            if used > math.floor(seconds * fps * data['budget']):
                raise ValueError(f'layer {name}: capture window exceeds frame budget')
        if not isinstance(layer.get('atlas', 1), int) or not 1 <= layer.get('atlas', 1) <= 64:
            raise ValueError(f'layer {name}: atlas must have 1..64 rows')
    return screens


CAPTURE_GUTTER = 2
MAX_CAPTURE_SIDE = 8192
MAX_CAPTURE_PIXELS = 16_777_216


def _batches(plates, limit=MAX_CAPTURE_SIDE):
    """Greedily pack disjoint padded plates into bounded screenshot viewports."""
    def fits(bounds):
        w,h = bounds[2]-bounds[0], bounds[3]-bounds[1]
        return max(w,h) <= limit and w*h <= MAX_CAPTURE_PIXELS
    groups = []
    for plate in plates:
        x0,y0,x1,y1 = plate['box']
        box = [x0-CAPTURE_GUTTER,y0-CAPTURE_GUTTER,x1+CAPTURE_GUTTER,y1+CAPTURE_GUTTER]
        if not fits(box):
            raise ValueError('layer exceeds capture viewport limits')
        for group, bounds in groups:
            union = [min(bounds[0],box[0]),min(bounds[1],box[1]),
                     max(bounds[2],box[2]),max(bounds[3],box[3])]
            if fits(union) and all(box[2] <= p['box'][0]-CAPTURE_GUTTER or
                box[0] >= p['box'][2]+CAPTURE_GUTTER or box[3] <= p['box'][1]-CAPTURE_GUTTER or
                box[1] >= p['box'][3]+CAPTURE_GUTTER for p in group):
                group.append(plate)
                bounds[:] = union
                break
        else:
            groups.append(([plate], box))
    return groups


def _plates(project, template, ctx, seconds, size, fps, stats):
    key, html, ctx = scenes._prepare(project, template, ctx, seconds, size, fps,
                                    ('builder-v5', MOTIONS))
    stats.setdefault('screenshots', 0)
    manifest = html.with_suffix('.layers.json')
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if all(Path(p).is_file() for p in data['files']):
            stats['cache_hits'] += len(data['files'])
            return data

    def probe(cdp, session, item, t):
        # Builder timelines have no exit; measure the final layout once.
        _value(cdp, session, "window.__builderCapture=true; document.body.style.transform='none'; Object.values(window.__timelines).forEach(t=>t.progress(1))")
        _value(cdp, session, "document.querySelectorAll('[data-motion=atlas] .atlas-strip').forEach(e=>e.style.transform='none')")
        data = _value(cdp, session, _PROBE)
        _plan(data, seconds, fps)  # Budget and graph limits precede any screenshot.
        data['files'] = []
        isolation = """window.__isolate = document.createElement('style');
          document.head.appendChild(window.__isolate);"""
        _value(cdp, session, isolation)
        sx, sy = size[0]/ctx['width'], size[1]/ctx['height']

        # Every stylesheet rule in the page (inline <style> included) keys the plates.
        asset_hash = [scenes._asset_hash(), _hash(data.pop('rules', []))]

        def plate_path(signature):
            path = html.parent / ('layer-' + _hash(['v6', template, signature, size, asset_hash]) + '.png')
            data['files'].append(str(path))
            return path

        def screenshot(selector, time=None):
            _value(cdp, session, f'window.__seek({time})' if time is not None else
                   'Object.values(window.__timelines).forEach(t=>t.progress(1))')
            css = ('[data-layer], [data-layer] *, [data-screen], [data-screen] * {visibility:hidden!important}' if selector is None else
                   f'html,body {{background:transparent!important}} body * {{visibility:hidden!important}} {selector}, {selector} * {{visibility:visible!important}}')
            if selector and time is None:
                css += f' {selector} {{opacity:1!important}}'
                css += ' [data-motion="atlas"] .atlas-strip {transform:none!important}'
            _value(cdp, session, f'window.__isolate.textContent={json.dumps(css)}')
            raw = base64.b64decode(cdp.send('Page.captureScreenshot',
                                          dict(format='png', fromSurface=True), session)['data'])
            stats['screenshots'] += 1
            with Image.open(io.BytesIO(raw)) as image:
                return image.convert('RGBA')

        def save_crop(path, image, box):
            buf = io.BytesIO()
            image.crop(box).save(buf, format='PNG')
            _write(path, buf.getvalue())
            stats['captures'] += 1

        def capture(signature, box, selector, time=None):
            path = plate_path(signature)
            if path.exists():
                stats['cache_hits'] += 1
            else:
                save_crop(path, screenshot(selector, time), box)
            return str(path)

        world = any(s.get('world') for s in data['screens'])
        density = sx*max(k['zoom'] for s in data['screens'] for k in s['camera']) if world else sx
        if world:
            for screen in data['screens']:
                left, top, _, w, h = _world_bounds(screen['camera'], ctx['width'], ctx['height'], sx, density)
                screen['raster'] = dict(left=left, top=top, density=density, width=w, height=h)
        pending = {}
        # Ground clones use the same content signatures and world pixel grid as
        # their live rows, including rows only ever visible in a chapter ground.
        # An empty ground element (e.g. an omitted chart label) paints nothing; drop it.
        data['grounds'] = [g for g in data.get('grounds', []) if g['box'][2] > g['box'][0] and g['box'][3] > g['box'][1]]
        for attr, rows in [('data-layer', data['layers']), ('data-ground', data['grounds'])]:
            for layer in rows:
                x0,y0,x1,y1 = layer['box']
                dx,dy = (density,density) if world else (sx,sy)
                box = [math.floor(x0*dx),math.floor(y0*dy),math.ceil(x1*dx),math.ceil(y1*dy)]
                if box[2] <= box[0] or box[3] <= box[1]:
                    raise ValueError(f"layer {layer.get('id', 'ground')}: empty bounds")
                layer['box'] = box
                if layer.get('clip'):
                    layer['clip'] = [v*(dx if i%2==0 else dy) for i,v in enumerate(layer['clip'])]
                if layer.get('native'):
                    layer['path'] = layer['native']
                    data['files'].append(layer['path'])
                    continue
                # Pixels depend on content, size and sub-pixel phase, not on where the
                # plate sits: a chat bubble scrolled to a new place reuses its plate.
                phase = [round(x0*dx % 1, 3), round(y0*dy % 1, 3),
                         round((x1-x0)*dx, 3), round((y1-y0)*dy, 3)]
                path = plate_path([_unplaced(layer['signature']), phase, box[2]-box[0], box[3]-box[1], density])
                layer['path'] = str(path)
                if path.exists() or str(path) in pending:
                    stats['cache_hits'] += 1
                else:
                    pending[str(path)] = dict(layer, attr=attr)

        # Validate every batch before any screenshot. The CSS viewport also has
        # a limit, even when a tiny device scale makes its bitmap small.
        batches = _batches(pending.values(), min(MAX_CAPTURE_SIDE, int(32767*density)))
        if not world:
            data['ground_path'] = capture(data['ground'], (0, 0, *size), None)
        for group, bounds in batches:
            if world:
                x0,y0,x1,y1 = bounds
                cdp.send('Emulation.setDeviceMetricsOverride', dict(width=math.ceil((x1-x0)/density),
                    height=math.ceil((y1-y0)/density), deviceScaleFactor=density, mobile=False), session)
                _value(cdp, session, f"document.body.style.transformOrigin='0 0'; document.body.style.transform='translate({-x0/density}px,{-y0/density}px)'")
            else:
                x0,y0 = 0,0
            _value(cdp, session, ';'.join(f"document.querySelectorAll('[{p['attr']}]')[{p['index']}].setAttribute('data-builder-active','')" for p in group))
            image = screenshot('[data-builder-active]')
            for plate in group:
                box = [v-(x0 if i%2==0 else y0) for i,v in enumerate(plate['box'])]
                save_crop(Path(plate['path']), image, box)
            _value(cdp, session, "document.querySelectorAll('[data-builder-active]').forEach(e=>e.removeAttribute('data-builder-active'))")

        if world:
            for screen in data['screens']:
                left, top, w, h = (screen['raster'][k] for k in ('left','top','width','height'))
                origin = [round(left*density),round(top*density)]
                grounds = [g for g in data.get('grounds', []) if g['screen'] == screen['id']]
                path = html.parent / ('ground-' + _hash([screen['raster'], [(g['path'],g['box']) for g in grounds]]) + '.png')
                data['files'].append(str(path))
                if not path.exists():
                    ground = Image.new('RGBA', (w,h))
                    for row in grounds:
                        x0,y0,x1,y1 = [v-origin[i%2] for i,v in enumerate(row['box'])]
                        if x1 <= 0 or y1 <= 0 or x0 >= w or y0 >= h:
                            continue
                        with Image.open(row['path']) as plate:
                            ground.alpha_composite(plate, (x0,y0))
                    buf = io.BytesIO()
                    ground.save(buf, format='PNG')
                    _write(path, buf.getvalue())
                screen['ground_path'] = str(path)
                for layer in [l for l in data['layers'] if l['screen'] == screen['id']]:
                    layer['box'] = [v-origin[i%2] for i,v in enumerate(layer['box'])]
                    if layer.get('clip'):
                        layer['clip'] = [v-origin[i%2] for i,v in enumerate(layer['clip'])]
                    layer['steps'] = [(t, edge*density) for t,edge in layer.get('steps', [])]
                for media in screen.get('media', []):
                    media['box'] = [round(v*density)-origin[i%2] for i,v in enumerate(media['box'])]
            data['ground_color'] = ctx['palette']['ground']
        else:
            for layer in data['layers']:
                if layer.get('capture') != 'frames':
                    continue
                _value(cdp, session, f"document.querySelectorAll('[data-layer]')[{layer['index']}].setAttribute('data-builder-active','')")
                screen = next((s for s in data['screens'] if s['id'] == layer['screen']), dict(start=0))
                count = math.ceil(min(layer['arrival'], layer['duration'])*fps)
                layer['frames'] = [capture([key, layer['id'], i], layer['box'], '[data-builder-active]',
                    screen['start'] + layer['start'] + i/fps) for i in range(count)]
                stats['captured_frames'] += count
                _value(cdp, session, "document.querySelector('[data-builder-active]').removeAttribute('data-builder-active')")

        data['files'] = list(dict.fromkeys(data['files']))
        _write(manifest, json.dumps(data).encode())

    stage.capture_stills([dict(clip=key, url_path=f'/scene/{{token}}/{html.name}',
        W=ctx['width'], H=ctx['height'], size=size, t=0, alpha=True, measure_only=True)],
        html.parent, **ctx.get('asset_roots', {}), assets_root=ctx.get('block_assets_root'), scene_probe=probe)
    return json.loads(manifest.read_text())


def ease(name, p):
    if name == 'linear':
        return p
    if name in ('quad-out', 'cubic-out'):
        return f'(1-pow(1-({p}),{2 if name == "quad-out" else 3}))'
    if name == 'expo-out':
        return f'if(gte({p},1),1,1-pow(2,-10*({p})))'
    if name == 'cubic-in-out':
        return f'if(lt({p},0.5),4*pow({p},3),1-pow(-2*({p})+2,3)/2)'
    if name in ('back-out', 'back-out-1.9', 'back-out-2.4'):
        s = float(name.rsplit('-', 1)[1]) if name != 'back-out' else 1.70158
        return f'(1+{s+1}*pow(({p})-1,3)+{s}*pow(({p})-1,2))'
    raise ValueError(f'unsupported ease: {name}')


def _motion(layer, clock='t'):
    spec = MOTIONS[layer['motion']]
    p = ease(layer.get('ease') or spec['ease'], f"clip(({clock}-{layer['start']})/{layer['arrival']},0,1)")
    a, b = spec.get('renderFrom', spec['from']), spec.get('renderTo', spec['to'])
    def value(k, default):
        start = float(layer['y']) if k == 'y' and layer.get('y') is not None else a.get(k, default)
        if start == b.get(k, default):
            return str(start)
        return f'({start}+({b.get(k, default)}-{start})*({p}))'
    return {k: value(k, d) for k, d in [('opacity', 1), ('x', 0), ('y', 0), ('scale', 1), ('wipe', 1)]}


def _camera(keys, clock, world=False):
    if len(keys) > 48:
        raise ValueError('at most 48 camera keys per screen')
    keys = sorted(keys, key=lambda k: k['t'])
    for k in keys:
        if not all(math.isfinite(k.get(v, d)) for v, d in [('t', 0), ('x', 0), ('y', 0), ('zoom', 1)]) or k.get('zoom', 1) <= 0 or (not world and k.get('zoom', 1) < 1):
            raise ValueError('camera requires finite coordinates and zoom >= 1 (positive for worlds)')
    def expr(name, default):
        result = str(keys[-1].get(name, default)) if keys else str(default)
        for a, b in reversed(list(zip(keys, keys[1:]))):
            if b['t'] <= a['t']:
                raise ValueError('camera times must increase')
            p = ease(b.get('ease', 'linear'), f"clip(({clock}-{a['t']})/{b['t']-a['t']},0,1)")
            result = f"if(lt({clock},{b['t']}),{a.get(name,default)}+({b.get(name,default)-a.get(name,default)})*({p}),{result})"
        return result
    return [expr(k, d) for k, d in [('x', 0), ('y', 0), ('zoom', 1)]]


def _media_filter(media, w, h):
    dim = float(media.get('dim', .53))
    dim = '.53' if dim == .53 else f'{dim:g}'
    x, y = (max(0, min(1, float(v))) for v in media.get('focal', [.5, .5]))
    blur = float(media.get('blur') or 0)
    tint = ''
    wash = media.get('wash')
    if wash is not None:
        if len(wash) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 255 for v in wash):
            raise ValueError('media wash must contain four channels in 0..255')
        r,g,b,a = wash
        tint = 'format=rgb24,lutrgb=' + ':'.join(
            f"{ch}='val*{255-a:g}/255+{value*a:g}/255'" for ch,value in zip('rgb',(r,g,b))) + ','
    if media.get('grayscale'):
        # Pillow ImageOps.grayscale uses the BT.601 RGB luminance coefficients.
        tint += 'colorchannelmixer=' + ':'.join(
            f'{out}{src}={v}' for out in 'rgb' for src,v in zip('rgb',('.299','.587','.114'))) + ','
    # Soft background: shrink by `blur`, soften, scale back (cheap at the small size).
    soften = (f'scale={max(2, round(w/blur))}:{max(2, round(h/blur))}:flags=area,gblur=sigma=1.5,'
              f'scale={w}:{h}:flags=bicubic,' if blur > 1 else '')
    return (f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h}:(iw-ow)*{x}:(ih-oh)*{y},{tint}{soften}'
            f'colorchannelmixer=rr={dim}:gg={dim}:bb={dim}')


def _compile(data, screen, size, fps, directory):
    layers = []
    for source in data['layers']:
        if source['screen'] not in ('', screen['id']):
            continue
        layer = dict(source)
        if source['screen'] == '':
            layer['start'] -= screen['start']
        layer['start'] -= screen.get('offset', 0)
        layer['steps'] = [(t-screen.get('offset', 0), edge) for t,edge in layer.get('steps', [])]
        shift = screen.get('offset', 0)+(screen['start'] if source['screen'] == '' else 0)
        layer['pathKeys'] = [dict(k, t=k['t']-shift) for k in layer.get('pathKeys', [])]
        if layer.get('native') and layer.get('video'):
            layer['time'] += screen.get('offset', 0)
        if layer['start'] < screen['duration'] and layer['start']+layer['duration'] > 0:
            layers.append(layer)
    # Flatten the settled prefix in paint order. Foreground layers retain their order.
    world = screen.get('raster')
    with Image.open(screen.get('ground_path', data.get('ground_path'))) as image:
        ground = image.convert('RGBA')
    if world:
        text = ground
        ground = Image.new('RGBA', text.size, data['ground_color'])
        videos = []
        for media in screen.get('media', []):
            x0,y0,x1,y1 = media['box']
            if x1<=0 or y1<=0 or x0>=ground.width or y0>=ground.height:
                continue
            if media['video']:
                videos.append(dict(media, id='media', screen=screen['id'], start=0,
                    duration=screen['duration'], arrival=.001, motion='none',
                    time=media['time']+screen.get('offset', 0)))
                continue
            source = Path(media['path'])
            stamp = source.stat()
            vf = _media_filter(media, x1-x0, y1-y0)
            path = Path(screen['ground_path']).parent / ('media-'+_hash([str(source),stamp.st_mtime_ns,stamp.st_size,vf])+'.png')
            if not path.exists():
                with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.png', delete=False) as stream:
                    temporary = Path(stream.name)
                try:
                    ffutil.run(['-i', str(source), '-vf', vf, '-frames:v','1',str(temporary)])
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            with Image.open(path) as panel:
                ground.alpha_composite(panel.convert('RGBA'), (x0,y0))
        if videos:
            layers = videos+[dict(id='settled', screen=screen['id'], start=0, duration=screen['duration'],
                arrival=.001, motion='none', path=screen['ground_path'], box=[0,0,*text.size])]+layers
        else:
            ground.alpha_composite(text)
    while not world and layers and not layers[0].get('native') and not layers[0].get('clip') and layers[0]['motion'] != 'atlas' and not layers[0].get('pathKeys') and layers[0]['start'] <= 0 and (layers[0]['motion'] == 'none' or layers[0]['start']+layers[0]['arrival'] <= 0) and layers[0]['start']+layers[0]['duration'] >= screen['duration']:
        layer = layers.pop(0)
        with Image.open(layer['path']) as plate:
            ground.alpha_composite(plate.convert('RGBA'), tuple(layer['box'][:2]))
    if len(layers) > 48:
        raise ValueError(f"screen {screen['id']}: more than 48 live layers; add screen boundaries")
    ground_path = directory / 'ground.png'
    ground.save(ground_path)
    inputs, graph = ['-i', str(ground_path)], [f'[0:v]loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB),format=rgba[g]']
    last = 'g'
    for i, layer in enumerate(layers, 1):
        inputs += ['-i', layer['path']]
        m, alpha = _motion(layer), _motion(layer, 'T')
        w, h = layer['box'][2]-layer['box'][0], layer['box'][3]-layer['box'][1]
        # Soft nib stays in crop coordinates; never evaluate geq on the ground.
        wipe = f"lte(X/W,{alpha['wipe']})"
        if layer['motion'] == 'wipe':
            feather = max(1, layer.get('feather', 1) * size[0]/data['width'])
            wipe = (f"clip({alpha['wipe']}/0.3,0,1)*"
                    f"clip((({w}+{2*feather})*{alpha['wipe']}-X)/{2*feather},0,1)")
        if layer.get('steps'):
            edge = '0'
            for t, right in layer['steps']:
                edge = f'if(gte(T,{t}),{right},{edge})'
            wipe = f'lte(X,{edge})'
        # Scale/alpha/wipe evaluate only the small crop. Reuse decoded still pixels.
        effect = (f"loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB),format=rgba,"
                  f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*clip({alpha['opacity']},0,1)*{wipe}':enable='between(t,{layer['start']},{max([layer['start']+layer['arrival']]+[s[0]+.16 for s in layer.get('steps',[])])})',"
                  f"scale=w='max(1,iw*{m['scale']})':h='max(1,ih*{m['scale']})':eval=frame")
        if layer['motion'] == 'none':
            effect = f'loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB),format=rgba'
        if layer['motion'] == 'atlas':
            count = layer.get('atlas', 1)
            h = h/count
            index = f"floor(clip((t-{layer['start']})/{layer['arrival']},0,1)*{count-1})"
            effect = (f'loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB),format=rgba,'
                      f"crop=iw:ih/{count}:0:'({index})*ih/{count}'")
        if layer.get('video'):
            inputs[-2:] = ['-stream_loop','-1','-ss',str(layer['time']),'-i',layer['path']]
            effect = f'setpts=PTS-STARTPTS,{_media_filter(layer, w, h)},format=rgba'
        elif layer.get('native'):
            # Filter the still once, then repeat the finished pixels.
            effect = f'{_media_filter(layer,w,h)},format=rgba,loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB)'
        if layer.get('native') or layer.get('clip'):
            # Clip in screen coordinates after translation, on the small plate.
            sx, sy = (world['density'], world['density']) if world else (size[0]/data['width'],size[1]/data['height'])
            mx,my = _camera(layer['pathKeys'], 'T', world=True)[:2] if layer.get('pathKeys') else (alpha['x'],alpha['y'])
            mask = alpha['opacity'] if layer.get('native') else '1'
            if layer.get('clip'):
                x0,y0,x1,y1 = layer['clip']
                px,py = f"X+{layer['box'][0]}+{sx}*({mx})+({w}-W)/2",f"Y+{layer['box'][1]}+{sy}*({my})+({h}-H)/2"
                mask += f'*gte({px},{x0})*lt({px},{x1})*gte({py},{y0})*lt({py},{y1})'
            if layer.get('clip'):
                effect += f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({mask})'"
            elif not re.fullmatch(r'[\d.()]+', mask):
                # Opacity only animates during arrival; geq is per-pixel, so not after.
                effect += (f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({mask})'"
                           f":enable='between(t,{layer['start']},{layer['start']+layer['arrival']})'")
        exit_s = min(layer.get('exit', 0), layer['duration']/2)
        if exit_s > 0:
            effect += f",fade=t=out:st={layer['start']+layer['duration']-exit_s}:d={exit_s}:alpha=1"
        if layer.get('frames'):
            # A concat demuxer sequence is confined to the declared arrival, then holds its settled plate.
            sequence = directory / f'frames-{i}.txt'
            sequence.write_text(''.join(f"file '{p}'\nduration {1/fps}\n" for p in layer['frames']) + f"file '{layer['path']}'\n")
            inputs[-2:] = ['-r', str(fps), '-f', 'concat', '-safe', '0', '-i', str(sequence)]
            effect = f"setpts=PTS-STARTPTS+{layer['start']}/TB,tpad=stop_mode=clone:stop=-1,format=rgba"
        graph.append(f'[{i}:v]{effect}[l{i}]')
        sx, sy = (world['density'], world['density']) if world else (size[0]/data['width'], size[1]/data['height'])
        if layer.get('pathKeys'):
            m['x'], m['y'], _ = _camera(layer['pathKeys'], 't', world=True)
        x = f"{layer['box'][0]}+{sx}*{m['x']}+({w}-overlay_w)/2"
        y = f"{layer['box'][1]}+{sy}*{m['y']}+({h}-overlay_h)/2"
        if layer.get('frames'):
            x, y = str(layer['box'][0]), str(layer['box'][1])
        graph.append(f"[{last}][l{i}]overlay=x='{x}':y='{y}':enable='gte(t,{layer['start']})*lt(t,{layer['start']+layer['duration']})':eof_action=repeat:format=auto[v{i}]")
        last = f'v{i}'
    keys = screen.get('camera', data.get('camera', []))
    x, y, z = _camera(keys, f'(on/{fps}+{screen["start"]+screen.get("offset",0)})', world=bool(world))
    if world:
        x = f'(({x})-{data["width"]}/(2*({z}))-{world["left"]})*{world["density"]}'
        y = f'(({y})-{data["height"]}/(2*({z}))-{world["top"]})*{world["density"]}'
        z = f'({z})*{world["width"]/(data["width"]*world["density"])}'
    else:
        x, y = f'({x})*{size[0]/data["width"]}', f'({y})*{size[1]/data["height"]}'
    top = data.get('top_plate')
    output = 'camera' if top else 'out'
    if data.get('alpha'):
        graph.append(f'[{last}]format=rgba[{output}]')
    elif not keys:
        # No camera: zoompan is the costliest node at full size, so skip it.
        graph.append(f'[{last}]format={"rgba" if top else "yuv420p"}[{output}]')
    else:
        graph.append(f"[{last}]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={size[0]}x{size[1]}:fps={fps},format={'rgba' if top else 'yuv420p'}[{output}]")
    if top:
        # One static viewport plate, after the camera. Decode/scale once and
        # repeat the finished pixels; never send it through zoompan or geq.
        inputs += ['-i', str(top)]
        graph.append(f'[{len(layers)+1}:v]scale={size[0]}:{size[1]},format=rgba[top]')
        graph.append(f'[camera][top]overlay=eof_action=repeat:format=auto,format={"rgba" if data.get("alpha") else "yuv420p"}[out]')
    text = ';\n'.join(graph)
    if len(text.encode()) >= 65536:
        raise ValueError('screen graph exceeds 64 KB; add screen boundaries')
    return inputs, text


def inspect(project, template, ctx, *, seconds, size, fps):
    """Capture and compile an authoring check, returning stats without encoding."""
    stats = dict(captures=0, screenshots=0, cache_hits=0, layers=0, passes=0,
                 largest_graph_bytes=0, captured_frames=0)
    data = _plates(project, template, ctx, seconds, size, fps, stats)
    data.update(width=ctx['width'], height=ctx['height'], alpha=ctx.get('builder_alpha', False),
                top_plate=ctx.get('builder_top_plate'))
    with tempfile.TemporaryDirectory(prefix='builder-check-') as work:
        for screen in _plan(data, seconds, fps):
            _, graph = _compile(data, screen, size, fps, Path(work))
            stats['passes'] += 1
            stats['largest_graph_bytes'] = max(stats['largest_graph_bytes'], len(graph.encode()))
    stats['layers'] = len(data['layers'])
    # Include requested windows even when all their plates were cached.
    stats['captured_frames'] = sum(len(layer.get('frames', [])) for layer in data['layers'])
    return stats


PASS_WORKERS = 4


def render(project, template, ctx, out, *, seconds, size, fps, crf, extra=(), frames=None):
    extra = list(extra)
    if '-vf' in extra:
        i = extra.index('-vf')
        value = extra[i+1]
        if not value.startswith('scale='):
            raise ValueError('builder extra -vf must be a literal scale=W:H')
        size = tuple(map(int, value[6:].split(':')))
        del extra[i:i+2]
    stats = dict(captures=0, screenshots=0, cache_hits=0, layers=0, passes=0, largest_graph_bytes=0, captured_frames=0)
    data = _plates(project, template, ctx, seconds, size, fps, stats)
    data.update(width=ctx['width'], height=ctx['height'], alpha=ctx.get('builder_alpha', False),
                top_plate=ctx.get('builder_top_plate'))
    screens = _plan(data, seconds, fps)
    stats['layers'] = len(data['layers'])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix='builder-') as work:
        directory, jobs = Path(work), []
        for n, screen in enumerate(screens):
            first = math.ceil(screen['start']*fps-1e-6)
            stop = math.ceil((screen['start']+screen['duration'])*fps-1e-6)
            if frames:
                first, stop = max(first, frames[0]), min(stop, frames[1])
            if stop <= first:
                continue
            screen = dict(screen, offset=first/fps-screen['start'], duration=(stop-first)/fps)
            # Each screen gets its own folder so passes can run side by side.
            folder = directory / str(n)
            folder.mkdir()
            inputs, graph = _compile(data, screen, size, fps, folder)
            script = folder / 'graph.ffgraph'
            script.write_text(graph)
            part = directory / f'{n}{out.suffix}'
            jobs.append((inputs, script, part, stop-first))
            stats['passes'] += 1
            stats['largest_graph_bytes'] = max(stats['largest_graph_bytes'], len(graph.encode()))
        # Screens are independent: a few small ffmpeg passes at once, sharing the
        # usual thread cap between them rather than each taking all of it.
        workers = max(1, min(PASS_WORKERS, len(jobs)))
        threads = max(1, ffutil._default_threads() // workers)

        def encode(job):
            inputs, script, part, count = job
            args = ['-threads', str(threads), '-filter_threads', str(threads), *inputs,
                '-filter_complex_threads', str(threads), '-filter_complex_script', str(script),
                '-map', '[out]', '-frames:v', str(count), '-r', str(fps),
                *(['-c:v', 'png', '-pix_fmt', 'rgba'] if data.get('alpha') else ffutil.video_args(out, crf=crf)), *extra, '-an', str(part)]
            try:
                ffutil.run(args)
            except ffutil.FFError as exc:
                if "Unrecognized option 'filter_complex_script'" not in str(exc):
                    raise
                args[args.index('-filter_complex_script')] = '-/filter_complex'
                ffutil.run(args)
            return part

        if workers == 1:
            parts = [encode(job) for job in jobs]
        else:
            with ThreadPoolExecutor(workers) as pool:
                parts = list(pool.map(encode, jobs))
        if len(parts) == 1:
            parts[0].replace(out)
        else:
            listing = directory / 'concat.txt'
            listing.write_text(''.join(f"file '{p.name}'\n" for p in parts))
            ffutil.run(['-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', str(out)])
    log.debug('scene builder: %s', stats)
    return Result(out, stats)

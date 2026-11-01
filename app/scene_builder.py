"""Layer plates captured once; bounded, script-file ffmpeg composition."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import io
import json
import logging
import math
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
 const style = e => [...getComputedStyle(e)].filter(k=>k!=='visibility').map(k => [k,getComputedStyle(e).getPropertyValue(k)]);
 const signature = e => [e.outerHTML.replace(/ data-(start|duration|motion[^ =]*)="[^"]*"/g,'').replace(/visibility:\s*(hidden|visible);?/g,''),
     [e,...e.querySelectorAll('*')].map(style)];
 const screens = [...document.querySelectorAll('[data-screen]')].map(e => ({
   id:e.dataset.screen, start:Number(e.dataset.start), duration:Number(e.dataset.duration), camera:e.dataset.camera ? JSON.parse(e.dataset.camera) : undefined}));
 const rows = layers.map((e,i) => {
   let r=e.getBoundingClientRect();
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
     box:[r.left,r.top,r.right,r.bottom], signature:signature(e)};
 });
 const clone = document.body.cloneNode(true);
 clone.querySelectorAll('[data-layer], [data-screen], script').forEach(e=>e.remove());
 return {layers:rows, screens, ground:[clone.outerHTML,style(document.body)],
   camera:JSON.parse(root.dataset.camera || '[]'), budget:Number(root.dataset.budget || 0.1)};
})()"""


def _value(cdp, session, js):
    return stage._evaluate(cdp, session, js)['result'].get('value')


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
        if layer.get('capture') == 'frames':
            used += math.ceil(min(layer['arrival'], layer['duration']) * fps)
            if used > math.floor(seconds * fps * data['budget']):
                raise ValueError(f'layer {name}: capture window exceeds frame budget')
    return screens


def _plates(project, template, ctx, seconds, size, fps, stats):
    key, html, ctx = scenes._prepare(project, template, ctx, seconds, size, fps,
                                    ('builder-v2', MOTIONS))
    manifest = html.with_suffix('.layers.json')
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if all(Path(p).is_file() for p in data['files']):
            stats['cache_hits'] += len(data['files'])
            return data

    def probe(cdp, session, item, t):
        # Builder timelines have no exit; measure the final layout once.
        _value(cdp, session, "window.__builderCapture=true; document.body.style.transform='none'; Object.values(window.__timelines).forEach(t=>t.progress(1))")
        data = _value(cdp, session, _PROBE)
        _plan(data, seconds, fps)  # Budget and graph limits precede any screenshot.
        data['files'] = []
        isolation = """window.__isolate = document.createElement('style');
          document.head.appendChild(window.__isolate);"""
        _value(cdp, session, isolation)
        sx, sy = size[0]/ctx['width'], size[1]/ctx['height']

        def capture(signature, box, selector, time=None):
            path = html.parent / ('layer-' + _hash([template, signature, size, scenes._asset_hash()]) + '.png')
            data['files'].append(str(path))
            if path.exists():
                stats['cache_hits'] += 1
                return str(path)
            if time is not None:
                _value(cdp, session, f'window.__seek({time})')
            else:
                _value(cdp, session, 'Object.values(window.__timelines).forEach(t=>t.progress(1))')
            css = ('[data-layer], [data-layer] *, [data-screen], [data-screen] * {visibility:hidden!important}' if selector is None else
                   f'html,body {{background:transparent!important}} body * {{visibility:hidden!important}} {selector}, {selector} * {{visibility:visible!important}}')
            if selector and time is None and layer.get('exit', 0) > 0:
                css += f' {selector} {{opacity:1!important}}'
            _value(cdp, session, f'window.__isolate.textContent={json.dumps(css)}')
            raw = base64.b64decode(cdp.send('Page.captureScreenshot',
                                          dict(format='png', fromSurface=True), session)['data'])
            with Image.open(io.BytesIO(raw)) as image:
                buf = io.BytesIO()
                image.convert('RGBA').crop(box).save(buf, format='PNG')
            _write(path, buf.getvalue())
            stats['captures'] += 1
            return str(path)

        data['ground_path'] = capture(data['ground'], (0, 0, *size), None)
        for layer in data['layers']:
            box = [math.floor(layer['box'][0]*sx), math.floor(layer['box'][1]*sy),
                   math.ceil(layer['box'][2]*sx), math.ceil(layer['box'][3]*sy)]
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError(f"layer {layer['id']}: empty bounds")
            layer['box'] = box
            _value(cdp, session, f"document.querySelectorAll('[data-layer]')[{layer['index']}].setAttribute('data-builder-active','')")
            selector = '[data-builder-active]'
            layer['path'] = capture([layer['signature'], box], box, selector)
            if layer.get('capture') == 'frames':
                screen = next((s for s in _plan(data, seconds, fps) if s['id'] == layer['screen']), dict(start=0))
                count = math.ceil(min(layer['arrival'], layer['duration'])*fps)
                layer['frames'] = [capture([key, layer['id'], i], box, selector,
                    screen['start'] + layer['start'] + i/fps) for i in range(count)]
                stats['captured_frames'] += count
            _value(cdp, session, "document.querySelector('[data-builder-active]').removeAttribute('data-builder-active')")
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
    if name == 'back-out':
        return f'(1+2.70158*pow(({p})-1,3)+1.70158*pow(({p})-1,2))'
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


def _camera(keys, clock):
    if len(keys) > 48:
        raise ValueError('at most 48 camera keys per screen')
    keys = sorted(keys, key=lambda k: k['t'])
    for k in keys:
        if not all(math.isfinite(k.get(v, d)) for v, d in [('t', 0), ('x', 0), ('y', 0), ('zoom', 1)]) or k.get('zoom', 1) < 1:
            raise ValueError('camera requires finite coordinates and zoom >= 1')
    def expr(name, default):
        result = str(keys[-1].get(name, default)) if keys else str(default)
        for a, b in reversed(list(zip(keys, keys[1:]))):
            if b['t'] <= a['t']:
                raise ValueError('camera times must increase')
            p = ease(b.get('ease', 'linear'), f"clip(({clock}-{a['t']})/{b['t']-a['t']},0,1)")
            result = f"if(lt({clock},{b['t']}),{a.get(name,default)}+({b.get(name,default)-a.get(name,default)})*({p}),{result})"
        return result
    return [expr(k, d) for k, d in [('x', 0), ('y', 0), ('zoom', 1)]]


def _compile(data, screen, size, fps, directory):
    layers = []
    for source in data['layers']:
        if source['screen'] not in ('', screen['id']):
            continue
        layer = dict(source)
        if source['screen'] == '':
            layer['start'] -= screen['start']
        if layer['start'] < screen['duration'] and layer['start']+layer['duration'] > 0:
            layers.append(layer)
    # Flatten the settled prefix in paint order. Foreground layers retain their order.
    with Image.open(data['ground_path']) as image:
        ground = image.convert('RGBA')
    while layers and layers[0]['start'] <= 0 and (layers[0]['motion'] == 'none' or layers[0]['start']+layers[0]['arrival'] <= 0) and layers[0]['start']+layers[0]['duration'] >= screen['duration']:
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
        # Scale/alpha/wipe evaluate only the small crop. Reuse decoded still pixels.
        effect = (f"loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB),format=rgba,"
                  f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*clip({alpha['opacity']},0,1)*{wipe}':enable='between(t,{layer['start']},{layer['start']+layer['arrival']})',"
                  f"scale=w='max(1,iw*{m['scale']})':h='max(1,ih*{m['scale']})':eval=frame")
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
        sx, sy = size[0]/data['width'], size[1]/data['height']
        x = f"{layer['box'][0]}+{sx}*{m['x']}+({w}-overlay_w)/2"
        y = f"{layer['box'][1]}+{sy}*{m['y']}+({h}-overlay_h)/2"
        if layer.get('frames'):
            x, y = str(layer['box'][0]), str(layer['box'][1])
        graph.append(f"[{last}][l{i}]overlay=x='{x}':y='{y}':enable='gte(t,{layer['start']})*lt(t,{layer['start']+layer['duration']})':eof_action=repeat:format=auto[v{i}]")
        last = f'v{i}'
    keys = screen.get('camera', data.get('camera', []))
    x, y, z = _camera(keys, f'(on/{fps}+{screen["start"]})')
    x, y = f'({x})*{size[0]/data["width"]}', f'({y})*{size[1]/data["height"]}'
    if data.get('alpha'):
        graph.append(f'[{last}]format=rgba[out]')
    elif not keys:
        # No camera: zoompan is the costliest node at full size, so skip it.
        graph.append(f'[{last}]format=yuv420p[out]')
    else:
        graph.append(f"[{last}]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={size[0]}x{size[1]}:fps={fps},format=yuv420p[out]")
    text = ';\n'.join(graph)
    if len(text.encode()) >= 65536:
        raise ValueError('screen graph exceeds 64 KB; add screen boundaries')
    return inputs, text


def inspect(project, template, ctx, *, seconds, size, fps):
    """Capture and compile an authoring check, returning stats without encoding."""
    stats = dict(captures=0, cache_hits=0, layers=0, passes=0,
                 largest_graph_bytes=0, captured_frames=0)
    data = _plates(project, template, ctx, seconds, size, fps, stats)
    data.update(width=ctx['width'], height=ctx['height'], alpha=ctx.get('builder_alpha', False))
    with tempfile.TemporaryDirectory(prefix='builder-check-') as work:
        for screen in _plan(data, seconds, fps):
            _, graph = _compile(data, screen, size, fps, Path(work))
            stats['passes'] += 1
            stats['largest_graph_bytes'] = max(stats['largest_graph_bytes'], len(graph.encode()))
    stats['layers'] = len(data['layers'])
    # Include requested windows even when all their plates were cached.
    stats['captured_frames'] = sum(len(layer.get('frames', [])) for layer in data['layers'])
    return stats


def render(project, template, ctx, out, *, seconds, size, fps, crf, extra=()):
    extra = list(extra)
    if '-vf' in extra:
        i = extra.index('-vf')
        value = extra[i+1]
        if not value.startswith('scale='):
            raise ValueError('builder extra -vf must be a literal scale=W:H')
        size = tuple(map(int, value[6:].split(':')))
        del extra[i:i+2]
    stats = dict(captures=0, cache_hits=0, layers=0, passes=0, largest_graph_bytes=0, captured_frames=0)
    data = _plates(project, template, ctx, seconds, size, fps, stats)
    data.update(width=ctx['width'], height=ctx['height'], alpha=ctx.get('builder_alpha', False))
    screens = _plan(data, seconds, fps)
    stats['layers'] = len(data['layers'])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix='builder-') as work:
        directory, parts = Path(work), []
        for n, screen in enumerate(screens):
            inputs, graph = _compile(data, screen, size, fps, directory)
            script = directory / f'{n}.ffgraph'
            script.write_text(graph)
            part = directory / f'{n}{out.suffix}'
            count = round((screen['start']+screen['duration'])*fps)-round(screen['start']*fps)
            args = [*inputs, '-filter_complex_threads', str(ffutil._default_threads()), '-filter_complex_script', str(script),
                '-map', '[out]', '-frames:v', str(count), '-r', str(fps),
                *(['-c:v', 'png', '-pix_fmt', 'rgba'] if data.get('alpha') else ffutil.video_args(out, crf=crf)), *extra, '-an', str(part)]
            try:
                ffutil.run(args)
            except ffutil.FFError as exc:
                if "Unrecognized option 'filter_complex_script'" not in str(exc):
                    raise
                args[args.index('-filter_complex_script')] = '-/filter_complex'
                ffutil.run(args)
            parts.append(part)
            stats['passes'] += 1
            stats['largest_graph_bytes'] = max(stats['largest_graph_bytes'], len(graph.encode()))
        if len(parts) == 1:
            parts[0].replace(out)
        else:
            listing = directory / 'concat.txt'
            listing.write_text(''.join(f"file '{p.name}'\n" for p in parts))
            ffutil.run(['-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', str(out)])
    log.debug('scene builder: %s', stats)
    return Result(out, stats)

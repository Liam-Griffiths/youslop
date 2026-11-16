"""Owned media placement and composition; no downloads or source-file edits."""
import math

from . import ffutil, store


def role(item):
    return 'media' if item.get('type') == 'media' else 'graphics'


def validate(item):
    def number(key, default, low=0, high=float('inf')):
        value = item.get(key, default)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not low <= value <= high):
            raise ValueError(f'Media {key} must be finite and within {low}..{high}')
        return float(value)
    source = item.get('source')
    if not isinstance(source, dict):
        raise ValueError('Media source needs an owned source id')
    keys = set(source)
    if keys == {'shot'}:
        from .media_shots import validate as validate_shot
        validate_shot(source['shot'])
    elif keys not in ({'bin_id'}, {'asset_id'}, {'source_slide', 'candidate_id'}, {'clip'}) or any(
            not isinstance(v, str) or not v.strip() for v in source.values() if keys != {'clip'}):
        raise ValueError('Choose Materials, Library or a cached candidate')
    if keys == {'clip'}:
        meta = source['clip']
        if (not isinstance(meta, dict) or any(not isinstance(meta.get(k), str) for k in ('shoot_id', 'source_id'))
                or any(type(meta.get(k)) not in (int, float) or not math.isfinite(meta[k]) for k in ('in_s', 'out_s', 'seconds'))
                or not 0 <= meta['in_s'] < meta['out_s'] or meta['seconds'] != meta['out_s']-meta['in_s']):
            raise ValueError('Invalid owned clip range')
    box = item.get('box', dict(x=.65, y=.05, w=.3, h=.3))
    if not isinstance(box, dict) or set(box) != set('xywh') or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            or not 0 <= v <= 1 for v in box.values()):
        raise ValueError('Media box needs x/y/w/h in 0..1')
    if min(box['w'], box['h']) <= 0 or box['x']+box['w'] > 1 or box['y']+box['h'] > 1:
        raise ValueError('Media box must fit inside the frame')
    if item.get('fit', 'cover') not in {'cover', 'contain'}:
        raise ValueError('Media fit must be cover or contain')
    return dict(id=item['id'], type='media', source=dict(source), at=float(item['at']),
                dur=float(item['dur']), box=dict(box), fit=item.get('fit', 'cover'),
                **{'in': number('in', 0)}, fade_in=number('fade_in', .14),
                fade_out=number('fade_out', .14), volume=number('volume', 0, high=1),
                by=item.get('by', 'hand'), **{k: item[k] for k in ('layer', 'on') if k in item})


def source(project, item):
    """Return path, kind, range start and range length, resolving IDs only."""
    from . import library, project_bin
    ref, offset = item['source'], 0.
    if 'shot' in ref:
        from .media_shots import resolve
        result = resolve(project, ref['shot'])
        if item['in'] >= result[3]:
            raise ValueError('Media source offset is outside the clip')
        return result
    if 'clip' in ref:
        from .inserts import source as clip_source
        meta = ref['clip']
        path, kind, offset, length = clip_source(meta), 'video', meta['in_s'], meta['seconds']
    elif 'bin_id' in ref:
        entry = next((i for i in project.bin if i.id == ref['bin_id']), None)
        if entry is None:
            raise ValueError('Media material is no longer available')
        path, kind, length = project_bin.file_path(project.id, entry), entry.kind, entry.duration
        if entry.source.startswith('footage:'):
            from . import footage
            sid, cid = entry.source.removeprefix('footage:').split('/')
            clip = next(c for c in footage.load(sid).clips if c.id == cid)
            offset, length = clip.in_s, clip.out_s-clip.in_s
    elif 'asset_id' in ref:
        entry = library.get(ref['asset_id']) or {}
        path, kind, length = library.file_path(ref['asset_id']), entry.get('kind'), entry.get('duration', 0)
    else:
        slide = project.slide(ref['source_slide'])
        entry = next((c for c in slide.candidates if c['id'] == ref['candidate_id']), {}) if slide else {}
        kind, length = entry.get('kind'), entry.get('duration', 0)
        if entry.get('provider') == 'footage':
            from .media.footage import resolve
            path = resolve(entry)
            offset, length = entry['in_s'], entry['out_s']-entry['in_s']
        else:
            root = store.project_dir(project.id).resolve()
            path = (root / entry.get('local_path', '')).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Media candidate must be cached inside the project')
    if kind not in {'image', 'video', 'clip'} or not path or not path.is_file():
        raise ValueError('Media source is unavailable; cache it before placement')
    video = kind in {'video', 'clip'}
    length = length or (ffutil.duration(path) if video else 0)
    if video and item['in'] >= length:
        raise ValueError('Media source offset is outside the clip')
    return path, 'video' if video else 'image', offset, length


def info(project, item):
    try:
        _, kind, _, length = source(project, item)
        return dict(source_kind=kind, source_length=length, unavailable='')
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        return dict(source_kind='', source_length=0, unavailable=str(exc))


def place(project, sid, payload):
    """Owned placement and an optional new lane in the same undo snapshot."""
    import uuid
    from . import block_overlays, cuts, inserts, kinds, layers
    slide = project.slide(sid)
    if not slide or slide.on_camera or cuts.is_cut(kinds.kind_for(project, slide)) or project.kind == 'clip':
        raise ValueError('Place media inside a picture paragraph')
    data = payload.get('source')
    if not isinstance(data, dict):
        raise ValueError('Choose a media source')
    if data.get('kind') == 'stage':
        from .media_shots import snapshot
        ref = dict(shot=snapshot(project, data))
    elif data.get('kind') == 'clip':
        row, _ = inserts.prepare(project, data)
        ref = dict(clip=row.insert)
    else:
        ref = {k: data[k] for k in ('bin_id', 'asset_id', 'source_slide', 'candidate_id') if k in data}
    item = validate(dict(id='media-'+uuid.uuid4().hex, type='media', source=ref,
                         at=payload.get('at', 0), dur=data.get('seconds', 4)))
    _, kind, _, length = source(project, item)
    if kind == 'video':
        item['dur'] = length
    layer = payload.get('layer', '')
    if layer:
        if not any(r['id'] == layer and r['role'] == 'media' and not r['locked'] for r in layers.rows(project)):
            raise ValueError('Choose an unlocked media layer')
    else:
        # Reuse the top unlocked media lane that is free here; add a lane only when none is.
        def free(lane):
            return not any(role(o) == 'media' and o.get('layer') == lane
                           and o['at'] < item['at'] + item['dur'] and item['at'] < o['at'] + o['dur']
                           for o in slide.overlays)
        lanes = [r['id'] for r in layers.rows(project)
                 if r['role'] == 'media' and not r['locked'] and not str(r['id']).startswith('derived:')]
        layer = next((lane for lane in reversed(lanes) if free(lane)), '')
        if not layer:
            layers.manage(project, dict(op='add', role='media', name='Media'))
            layer = project.layers[-1].id
    slide.overlays = block_overlays.validate(slide.take, [*slide.overlays, dict(item, layer=layer)])


def cache_state(project, slide):
    from .render import _stat
    result = []
    for o in slide.overlays:
        if role(o) != 'media':
            continue
        try:
            path, kind, offset, length = source(project, validate(o))
            result.append([o, str(path), kind, offset, length, _stat(path)])
        except (ValueError, OSError, KeyError, StopIteration) as exc:
            if 'cached inside the project' in str(exc):
                raise
            result.append([o, 'unavailable', str(exc)])
    return result


def compose(project, item, inputs, graph, last, size, fps, at, tag, *, prepare_only=False):
    from . import render
    if 'shot' in item['source']:
        from .media_shots import resolve
        path, kind, offset, length = resolve(project, item['source']['shot'],
                                           size=size, fps=fps, render=not prepare_only)
    else:
        path, kind, offset, length = source(project, item)
    duration = min(item['dur'], length-item['in']) if kind == 'video' else item['dur']
    index = inputs.count('-i')
    x, y, w, h = (item['box'][k] for k in 'xywh')
    w, h = max(2, round(w*size[0]/2)*2), max(2, round(h*size[1]/2)*2)
    if kind == 'video':
        inputs += ['-ss', f"{offset+item['in']:.6f}", '-t', f'{duration:.6f}', '-i', str(path)]
    else:
        inputs += render._still_input(path, fps)
    mode = 'increase' if item['fit'] == 'cover' else 'decrease'
    fit = f'scale={w}:{h}:force_original_aspect_ratio={mode},format=rgba,'
    fit += (f'crop={w}:{h}' if mode == 'increase' else f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0')
    # Decode and scale stills once, then repeat the small RGBA plate in memory.
    fit += ',' + (render.HOLD_STILL if kind == 'image' else f'fps={fps}')
    chain = f'{fit},setsar=1,trim=duration={duration:.6f},setpts=PTS-STARTPTS'
    for direction, fade, start in [('in', item['fade_in'], 0),
                                   ('out', item['fade_out'], max(0, duration-min(duration, item['fade_out'])))]:
        if fade:
            chain += f',fade=t={direction}:st={start:.6f}:d={min(fade,duration):.6f}:alpha=1'
    graph += (f';[{index}:v]{chain},setpts=PTS+{at:.6f}/TB[{tag}s]'
              f';{last}[{tag}s]overlay={round(x*size[0])}:{round(y*size[1])}:'
              f"enable='gte(t,{at:.6f})*lt(t,{at+duration:.6f})':"
              f'eof_action=pass:repeatlast=0:format=auto[{tag}]')
    return inputs, graph, f'[{tag}]'


def mix_audio(project, takes, inputs, filters, gaps, head, hide, fill):
    """Mix on the paragraph clock before concatenation, under the voice bus."""
    from . import block_overlays
    from .layers import visibility
    hide = visibility(project, hide, final=True)
    active = any(role(o) == 'media' and o.get('volume') and not hide.item('media', o.get('layer', ''))
                 for slide, _ in takes for o in slide.overlays)
    if not active:
        return False
    if 'voice' in hide:
        for i in range(len(takes)):
            base = next(j for j, chain in enumerate(filters) if chain.endswith(f'[a{i}]'))
            filters[base] = filters[base].replace(f'[a{i}]', f',volume=0[a{i}]')
    for i, (slide, take) in enumerate(takes):
        if slide.on_camera:
            continue
        from . import cuts, kinds
        if cuts.is_cut(kinds.kind_for(project, slide)):
            continue
        from .take_edits import take_duration
        length = slide.insert.get('seconds') or (take_duration(take) if take else fill.get(slide.id, 0))
        length += gaps.get(slide.id, 0)
        labels = []
        for item in block_overlays.resolved(slide.take, slide.overlays, length):
            if role(item) != 'media' or not item['volume'] or hide.item('media', item.get('layer', '')):
                continue
            path, kind, offset, end = source(project, item)
            if kind != 'video' or not ffutil.has_audio(path):
                continue
            index, tag = inputs.count('-i'), f'ma{i}_{len(labels)}'
            duration = min(item['dur'], end-item['in'])
            inputs += ['-ss', f"{offset+item['in']:.6f}", '-t', f'{duration:.6f}', '-i', str(path)]
            delay = round((item['at'] + (head if i == 0 else 0))*1000)
            fades = ''
            for direction, fade, start in [('in', item['fade_in'], 0),
                    ('out', item['fade_out'], max(0, duration-item['fade_out']))]:
                if fade:
                    fades += f'afade=t={direction}:st={start:.6f}:d={min(fade,duration):.6f},'
            filters.append(f'[{index}:a]aresample=48000,aformat=channel_layouts=mono,'
                           f'atrim=duration={duration:.6f},asetpts=PTS-STARTPTS,'
                           f"volume={item['volume']:.6f},volume={project.style.music_db:.1f}dB,"
                           f'{fades}adelay={delay}|{delay}[{tag}]')
            labels.append(f'[{tag}]')
        if labels:
            base = next(j for j, chain in enumerate(filters) if chain.endswith(f'[a{i}]'))
            filters[base] = filters[base].replace(f'[a{i}]', f'[nar{i}]')
            filters.append(f'[nar{i}]'+''.join(labels)+f'amix=inputs={len(labels)+1}:duration=first:normalize=0[a{i}]')
    return True

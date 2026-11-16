"""Owned local pictures and clips on paragraph layers; no downloads or writes."""
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
    if keys not in ({'bin_id'}, {'asset_id'}, {'source_slide', 'candidate_id'}) or any(
            not isinstance(v, str) or not v.strip() for v in source.values()):
        raise ValueError('Choose Materials, Library or a cached candidate')
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
    if 'bin_id' in ref:
        entry = project_bin.item_for(project, ref['bin_id'])
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


def cache_state(project, slide):
    from .render import _stat
    return [[o, str(path), kind, offset, length, _stat(path)]
            for o in slide.overlays if role(o) == 'media'
            for path, kind, offset, length in [source(project, validate(o))]]


def compose(project, item, inputs, graph, last, size, fps, at, tag):
    from . import render
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

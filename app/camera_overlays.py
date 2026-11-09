"""Silent pictures on the edited camera clock; recordings are never rewritten."""
import math
from pathlib import Path

from .take_edits import take_duration


def validate(take, overlays):
    if not isinstance(overlays, list) or len(overlays) > 32:
        raise ValueError('Use a list of at most 32 camera overlays')
    clean, end = [], take_duration(take)
    for item in overlays:
        if (not isinstance(item, dict) or item.get('kind') not in ('cutaway', 'pip', 'split')
                or item.get('by', 'hand') not in ('hand', 'auto')
                or any(isinstance(item.get(k), bool) or not isinstance(item.get(k), (int, float))
                       or not math.isfinite(item[k]) for k in ('at', 'dur'))
                or item['dur'] <= 0):
            raise ValueError('Overlay needs finite at/dur, positive dur, kind and by: hand or auto')
        source = item.get('source')
        if (not isinstance(source, dict) or not (isinstance(source.get('candidate_id'), str)
                or isinstance(source.get('template'), str))):
            raise ValueError('Overlay source needs candidate_id or scene template')
        if source.get('template') and ('..' in source['template'] or source['template'].startswith('/')):
            raise ValueError('Use a local scene template')
        if item.get('position', 'bottom_right') not in ('bottom_left', 'bottom_right', 'top_left', 'top_right'):
            raise ValueError('Unknown PIP corner')
        a, b = max(0., item['at']), min(end, item['at'] + item['dur'])
        if b > a:
            clean.append({**item, 'at': a, 'dur': b - a, 'by': item.get('by', 'hand')})
    ordered = sorted(clean, key=lambda x: x['at'])
    if any(a['at'] + a['dur'] > b['at'] + 1e-6 for a, b in zip(ordered, ordered[1:])):
        raise ValueError('Camera overlays must not overlap')
    return clean


def compose(project, slide, inputs, graph, last, size, fps, *, prepare_only=False, preview=False):
    """The camera keeps running under hard, enabled overlays, including punches."""
    from . import blocks, cuts, render, scenes, scene_builder
    take = project.active_take(slide) or {}
    w, h = size
    lead = cuts.transition_for(project.style) / 2 + cuts.head_pad_for(project, slide)
    for j, item in enumerate(validate(take, take.get('overlays', []))):
        seconds, source = item['dur'], item['source']
        index, tag = inputs.count('-i'), f'co{j}'
        if source.get('template'):
            ctx = scenes.context_base(project)
            ctx.update(source.get('context') or {}, duration=seconds)
            source_size = blocks.source_size(f"{ctx['width']}:{ctx['height']}", size) if project.aspect in {'portrait', 'square'} else size
            _, html, ctx = scenes._prepare(project, source['template'], ctx, seconds, source_size, fps,
                                           ('camera-builder-v1', scene_builder.MOTIONS))
            path = html.with_suffix('.mp4')
            if not prepare_only and not path.exists():
                scene_builder.render(project, source['template'], ctx, path,
                                     seconds=seconds, size=source_size, fps=fps, crf=18)
            kind, focal = 'video', []
        else:
            candidate = next((c for c in slide.candidates if c['id'] == source.get('candidate_id')), {})
            if candidate.get('provider') == 'footage':
                from .media.footage import resolve
                path = resolve(candidate, preview=preview)
            else:
                path = render.project_dir(project.id) / candidate.get('local_path', '')
            if not path or not path.is_file():
                continue
            kind, focal = candidate.get('kind', 'image'), candidate.get('focal')
        crop, point = ((render._fit_filter(size), None) if source.get('template') else
                       render._cover_crop(path, w * 2 if kind != 'video' else w,
                                          h * 2 if kind != 'video' else h, focal))
        if kind == 'video':
            inputs += ['-stream_loop', '-1', '-i', str(path)]
            chain = crop + f',fps={fps}'
        else:
            inputs += render._still_input(path, fps)
            chain = crop + ',' + render._kenburns('creep_in', max(2, round(seconds * fps)),
                render._camera_amount(project, 'creep_in', j), point, size, fps)
        a, b = lead + item['at'], lead + item['at'] + seconds
        graph += (f';[{index}:v]{chain},setsar=1,trim=duration={seconds:.6f},'
                  f'setpts=PTS-STARTPTS+{a:.6f}/TB[{tag}s]')
        enabled = f"enable='gte(t,{a:.6f})*lt(t,{b:.6f})':eof_action=pass:repeatlast=0"
        if item['kind'] == 'cutaway':
            graph += f';{last}[{tag}s]overlay=0:0:{enabled}[{tag}]'
        else:
            graph += f';{last}split[{tag}base][{tag}cam]'
            if item['kind'] == 'split':
                half = w // 4 * 2
                fit = f'scale={w}:{h},crop={half}:{h},setsar=1'
                media_fit = render._fit_filter((half, h)) if source.get('template') and project.aspect in {'portrait', 'square'} else fit
                graph += (f';[{tag}cam]{fit}[{tag}c];[{tag}s]{media_fit}[{tag}m];'
                          f'[{tag}c][{tag}m]hstack=shortest=1[{tag}layout]')
            else:
                bw, bh = w // 6 * 2, h // 6 * 2
                # The rounded-corner mask is drawn once with geq, then looped.
                radius = max(2, round(h * .025))
                mask = f"if(lte(hypot(max(abs(X-W/2)-(W/2-{radius}),0),max(abs(Y-H/2)-(H/2-{radius}),0)),{radius}),255,0)"
                graph += (f';color=c=black:s={bw}x{bh}:r={fps},format=gray,'
                          f"geq=lum='{mask}',trim=end_frame=1,loop=loop=-1:size=1[{tag}k]"
                          f';[{tag}cam]scale={bw}:{bh},format=rgba[{tag}r]'
                          f';[{tag}r][{tag}k]alphamerge[{tag}c]')
                pos, margin = item.get('position', 'bottom_right'), max(2, round(h * .035))
                x = str(margin) if pos.endswith('left') else f'W-w-{margin}'
                y = str(margin) if pos.startswith('top') else f'H-h-{margin}'
                graph += f';[{tag}s][{tag}c]overlay={x}:{y}:shortest=1[{tag}layout]'
            graph += f';[{tag}base][{tag}layout]overlay=0:0:{enabled}[{tag}]'
        last = f'[{tag}]'
    return inputs, graph, last

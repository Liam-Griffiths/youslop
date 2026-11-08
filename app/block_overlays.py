"""Paragraph graphics, independent of full-frame block cues and camera edits."""
from copy import deepcopy
import math
import re
import tempfile

from . import blocks, cuts, scenes, scene_builder
from .take_edits import take_duration


def validate(take, overlays):
    if not isinstance(overlays, list) or len(overlays) > 8:
        raise ValueError('Use a list of at most 8 block overlays')
    # Stored as written: clipping to a take here would drop graphics planned
    # before recording, or cut them for good when a shorter take replaces one.
    # `resolved` clips to the paragraph's actual length at render time.
    from .block_presets import provenance
    library, clean, ids = blocks.discover(), [], set()
    for item in overlays:
        if (not isinstance(item, dict) or
                any(isinstance(item.get(k), bool) or not isinstance(item.get(k), (int, float))
                    or not math.isfinite(item[k]) for k in ('at', 'dur')) or item['dur'] <= 0
                or item.get('by', 'hand') not in ('hand', 'auto')):
            raise ValueError('Overlay needs finite at/dur, positive dur and by: hand or auto')
        ident, ref = item.get('id'), item.get('block_id')
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError('Overlay ids must be nonempty and unique')
        ids.add(ident)
        block = library.get(ref) if isinstance(ref, str) else None
        spec = block['meta'].get('overlay') if block else None
        if not spec:
            raise ValueError(f'Not an overlay block: {ref}')
        position = item.get('position', spec['position'][0])
        if position not in spec['position'] or item['dur'] > spec['max_dur']:
            raise ValueError('Unsupported overlay position or duration exceeds max_dur')
        if 'on' in item and not isinstance(item['on'], str):
            raise ValueError('Overlay on must be a word or phrase')
        values = blocks.validate_vars(block['meta'], item.get('vars', {}))
        if item['at'] < 0:
            raise ValueError('Overlay at must be zero or more seconds')
        clean.append(dict(id=ident, block_id=ref, vars=values, at=float(item['at']), dur=float(item['dur']),
                          position=position, by=item.get('by', 'hand'),
                          **provenance(item), **({'on': item['on']} if 'on' in item else {})))
    return clean


def resolved(take, overlays, length=None):
    """Match successive anchors in list order, retaining estimated confidence.

    `length` is the paragraph's screen time (the take, or the estimate for an
    unrecorded paragraph); overlays are clipped to it here, never in storage.
    """
    words = (take or {}).get('words', [])
    tokens = lambda text: re.findall(r'\w+', text.casefold())
    entries = [(token, word) for word in words for token in tokens(word.get('w', ''))]
    cursor, result = 0, []
    end = length if length is not None else take_duration(take or {})
    for item in validate(take, overlays):
        item = dict(item, src='user')
        anchor = tokens(item.get('on', ''))
        for i in range(cursor, len(entries)-len(anchor)+1) if anchor else []:
            if [e[0] for e in entries[i:i+len(anchor)]] == anchor:
                word = entries[i][1]
                at = word.get('start')
                if isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at) and 0 <= at < end:
                    item.update(at=at, src=word.get('src', 'est'))
                    cursor = i+len(anchor)
                break
        item['dur'] = min(item['dur'], end-item['at'])
        if item['at'] < end and item['dur'] > 0:
            result.append(item)
    return result


def clip(project, item, size, fps, channel=None, *, prepare_only=False):
    block = deepcopy(blocks.discover().get(item['block_id']))
    if block is None:
        raise ValueError(f"Block missing: {item['block_id']}")
    # Placement lengths need not satisfy the standalone preview's minimum.
    block['meta']['duration'] = dict(mode='range', min=0)
    ctx = scenes.context_base(project, channel)
    ctx['fps'] = fps
    template, ctx = blocks.prepare(item['block_id'], item['vars'],
        '9:16' if project.aspect == 'portrait' else '16:9', item['dur'], context=ctx,
        _block=block, overlay=True, position=item['position'])
    _, html, ctx = scenes._prepare(project, template, ctx, item['dur'], size, fps,
                                  ('block-overlay-v1', scene_builder.MOTIONS))
    out = html.with_suffix('.mov')
    if not prepare_only and (not out.exists() or not out.stat().st_size):
        with tempfile.TemporaryDirectory(dir=out.parent, prefix='overlay-') as work:
            from pathlib import Path
            scene_builder.render(project, template, ctx, Path(work)/'clip.mov',
                                 seconds=item['dur'], size=size, fps=fps, crf=18)
            (Path(work)/'clip.mov').replace(out)
    return out


def compose(project, group, inputs, graph, last, size, fps, channel=None, *, prepare_only=False):
    lead = cuts.transition_for(project.style)/2 + cuts.head_pad_for(project, group[0][0])
    offset, count = 0., 0
    for slide, duration in group:
        for item in resolved(slide.take, slide.overlays, duration):
            path = clip(project, item, size, fps, channel, prepare_only=prepare_only)
            index, tag = inputs.count('-i'), f'bo{count}'
            count += 1
            inputs += ['-i', str(path)]
            a, d = lead + offset + item['at'], item['dur']
            fade = min(.14, d/2)
            graph += (f';[{index}:v]format=rgba,fade=t=in:st=0:d={fade:.6f}:alpha=1,'
                      f'fade=t=out:st={d-fade:.6f}:d={fade:.6f}:alpha=1,'
                      f'setpts=PTS-STARTPTS+{a:.6f}/TB[{tag}s]'
                      f';{last}[{tag}s]overlay=0:0:enable=\'between(t,{a:.6f},{a+d:.6f})\':'
                      f'eof_action=pass:repeatlast=0:format=auto[{tag}]')
            last = f'[{tag}]'
        offset += duration
    return inputs, graph, last


def run_graph(args, *, threads=0):
    """Bound script graph threads; accept ffmpeg's replacement file syntax too."""
    from . import ffutil
    args = ['-filter_complex_threads', str(threads or ffutil._default_threads()), *args]
    try:
        ffutil.run(args, threads=threads)
    except ffutil.FFError as exc:
        if "Unrecognized option 'filter_complex_script'" not in str(exc):
            raise
        args[args.index('-filter_complex_script')] = '-/filter_complex'
        ffutil.run(args, threads=threads)

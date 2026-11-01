"""Flameboat builder context. cuts/kit remain the only cue timing authority."""
import json
import re

from .. import scene_builder, scenes
from . import flameboat as f, kit

TEMPLATE = 'cuts/flameboat.html'


def _camera(beat, i, offset, start, end):
    cue = beat.cues[i]
    a, b = f._image_run(beat, i) if cue['kind'] == 'image' else (i, i)
    origin, stop = beat.times[a][0], beat.times[b][1]
    duration = max(.2, stop-origin)
    side = {'left': -1, 'center': 0, 'right': 1}.get(beat.cues[a].get('focus'), 0)
    def key(t):
        u = t-offset-origin
        if cue['kind'] == 'image':
            push = .07*kit.clamp(u/duration)
            z = 1+.06*(1-kit.ease_out(u/.14))+push
            dx, dy = side*push*260, 0
        elif cue['kind'] == 'meme':
            z = 1.04+.05*kit.clamp(u/duration)
            dx, dy = kit.shake(u, i*7+beat.index, 22, .35)
        else:
            z, dx, dy = 1+.09*(1-kit.ease_out(u/.16)), 0, 0
        return dict(t=t, x=kit.clamp(960+dx,960/z,1920-960/z),
                    y=kit.clamp(540+dy,540/z,1080-540/z), zoom=z)
    # Sample only the short hit/shake; the rest is a linear hold/push. These
    # are camera keys, never screenshots or separate ffmpeg nodes per frame.
    hit = .35 if cue['kind'] == 'meme' else .16
    times = {start, end, *(offset+origin+hit*n/10 for n in range(11))}
    return [key(t) for t in sorted(times) if start <= t <= end]


def context(project, ctx, beats, sources, chapter='', card_at=None, hide=frozenset()):
    data = scenes.context_base(project, ctx.channel)
    lo, hi = f.GROUNDS.get(ctx.look, f.GROUNDS[''])
    data['palette'].update(ground=lo, grid=hi, ink=f.INK, dim=f.INK_DIM,
                           cyan=f.CYAN, accent=ctx.accent, accent2=ctx.accent2)
    data['fonts'].update({name: '/fonts/'+kit.FACES[face] for name, face in
                         [('Display','display'), ('Bold','sans_bold'), ('Sans','sans'),
                          ('Mono','mono'), ('MonoBold','mono_bold')]})
    data.update(look=ctx.look or 'charcoal', screens=[], chapter=chapter, card_at=card_at)
    data['chapter_size'], data['chapter_rows'] = kit.fit(chapter, 'mono_bold', 96, 1520, 2, floor=44)
    offset = 0
    for beat, source in zip(beats, sources):
        for i, (cue, (a, b)) in enumerate(zip(beat.cues, beat.times)):
            start, end = offset+(a if i else 0), min(offset+b, card_at if card_at is not None else float('inf'))
            if end <= start:
                continue
            cue = dict(cue)
            if cue['kind'] == 'image':
                cue = dict(beat.cues[f._image_run(beat, i)[0]])
            dur = max(.1, b-a)
            if cue['kind'] == 'code':
                budget = max(.3, min(.5*dur, .16*len(cue['lines'])))
                cue.update(budget=budget, rows=[dict(text=line.expandtabs(4), tokens=f.tokens(line.expandtabs(4), cue['lang']),
                    start=j*budget/len(cue['lines']), arrival=.9*budget/len(cue['lines'])) for j,line in enumerate(cue['lines'])])
            if cue['kind'] == 'term':
                cue['type_time'] = min(.9, .4*dur, .035*len(cue['cmd']))
                cue['outputs'] = [dict(text=line, color='#FF6B6B' if re.search(r'\b(error|fail|denied)\b',line,re.I)
                    else '#28C840' if re.search(r'\b(ok|done|success|passed)\b',line,re.I) else f.INK_DIM)
                    for line in cue['out']]
            if cue['kind'] == 'title':
                words = cue['text'].split()
                hot_a, hot_b = f._hot_range(words, cue.get('hot',''))
                cue['words'] = [dict(text=w, hot=hot_a<=j<hot_b) for j,w in enumerate(words)]
            hidden = 'cues' in hide
            data['screens'].append(dict(id=f'cue{len(data["screens"])}', start=start, duration=end-start,
                cue=cue, source=str(source) if source else '', video=bool(beat.motion),
                stamp=[source.stat().st_mtime_ns, source.stat().st_size] if source else None,
                media_time=max(0,start-offset), focal=[f.FOCUS.get(cue.get('focus'),.5),
                    .45 if beat.motion or cue['kind']=='image' else .5],
                media=bool(source) and (hidden or cue['kind'] in ('image','meme')), hidden=hidden,
                camera=_camera(beat,i,offset,start,end), local_start=a, cue_duration=dur))
        offset += beat.length
    return data


def render(project, ctx, beats, sources, out, *, seconds, size, fps, crf,
           chapter='', card_at=None, hide=frozenset(), frames=None):
    data = context(project, ctx, beats, sources, chapter, card_at, hide)
    # The last beat uses picture time; cover the rounded-up final frame too.
    if data['screens'] and card_at is None:
        data['screens'][-1]['duration'] = seconds-data['screens'][-1]['start']
    data['colors'] = f.COLORS
    result = scene_builder.render(project, TEMPLATE, data, out, seconds=seconds,
                                   size=size, fps=fps, crf=crf, frames=frames)
    out.with_suffix(out.suffix+'.stats.json').write_text(json.dumps(result.stats, sort_keys=True))
    return result.path

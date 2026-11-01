"""Group Chat plates; kit owns cue clocks and CSS measures the thread."""
import json

from .. import scene_builder, scenes
from . import groupchat as g, kit, source_for, cues_for

TEMPLATE = 'cuts/groupchat.html'


def _item(ctx, cue, slide, previous):
    who = cue.get('from')
    senders = g._senders(ctx)
    source = source_for(ctx, slide) if cue['kind'] == 'photo' else None
    return dict(cue, name=who if who and who != 'me' and who != previous else '',
        color=g.SENDER_COLORS[senders.index(who) % len(g.SENDER_COLORS)] if who in senders else g._theme(ctx)['muted'],
        source=str(source) if source else '',
        stamp=[source.stat().st_mtime_ns, source.stat().st_size] if source else None)


def context(project, ctx, beats, sources, chapter='', card_at=None, hide=frozenset()):
    data = scenes.context_base(project, ctx.channel)
    ground = '#'+''.join(f'{v:02x}' for v in kit.mix('#0B0B10',ctx.accent,.18)[:3])
    data['palette'].update(g._theme(ctx), ground=ground, accent=ctx.accent, accent2=ctx.accent2)
    data['fonts'].update(Sans='/fonts/'+kit.FACES['sans_med'], Bold='/fonts/'+kit.FACES['sans_bold'])
    data.update(look=ctx.look or 'dark', title=g._title(ctx), senders=len(g._senders(ctx)),
        avatar=g.SENDER_COLORS[0] if g._senders(ctx) else ctx.accent, screens=[], chapter=chapter, card_at=card_at)
    data['chapter_size'], data['chapter_rows'] = kit.fit(chapter, 'sans_bold', 78, g.PANEL_W-200, 2, floor=44)
    offset = 0
    for beat, source in zip(beats, sources):
        history = []
        for slide in project.slides:
            if slide.id == beat.slide.id:
                break
            if slide.chapter.strip():
                history = []
            history += [(c, slide) for c in cues_for(g, slide) if c['kind'] != 'image']
        history = [] if beat.slide.chapter.strip() else history[-12:]
        items, previous = [], None
        for cue, slide in history:
            items.append(_item(ctx, cue, slide, previous)); previous = cue.get('from')
        for i, (cue, (a,b)) in enumerate(zip(beat.cues, beat.times)):
            start = offset+(a if i else 0)
            end = min(offset+b, card_at if card_at is not None else float('inf'))
            typing = min(.7, (b-a)*.3) if cue['kind'] in ('msg','photo') and cue['from'] != 'me' else 0
            adds = cue['kind'] != 'image'
            incoming = _item(ctx, cue, beat.slide, previous) if adds else None
            cutaway = 'cues' in hide or bool(source) and cue['kind'] == 'image'
            arrival = offset+a+typing
            bounds = sorted({start, end, *[v for v in (arrival,arrival+.28) if start < v < end]}) if adds and not cutaway else [start,end]
            if end <= start:
                bounds = []
            for left,right in zip(bounds,bounds[1:]):
                if right <= left:
                    continue
                phase = 'hold' if not adds or cutaway else 'typing' if left < arrival else 'arrival' if left < arrival+.28 else 'hold'
                shown = items + ([incoming] if adds and phase != 'typing' else [])
                fx = g.FOCUS.get(cue.get('focus'), .5)
                def camera(t):
                    push = .08*kit.clamp((t-offset-a)/max(.2,b-a))
                    z = (1 if beat.motion else 1.12)*(1+push)
                    return dict(t=t,x=960+(fx-.5)*2*push*240,y=540,zoom=z)
                data['screens'].append(dict(id=f'cue{len(data["screens"])}', start=left, duration=right-left,
                    cue=cue, items=shown, phase=phase, typing=typing and phase=='typing',
                    arrival=arrival-left, elapsed=left-offset-a, cutaway=cutaway, hidden='cues' in hide,
                    source=str(source) if source else '', video=bool(beat.motion), media_time=left-offset,
                    stamp=[source.stat().st_mtime_ns,source.stat().st_size] if source else None,
                    camera=[camera(left),camera(right)] if cutaway and 'cues' not in hide else [dict(t=left,x=960,y=540,zoom=1)]))
            if incoming:
                items.append(incoming); previous=cue.get('from')
        offset += beat.length
    return data


def render(project, ctx, beats, sources, out, *, seconds, size, fps, crf,
           chapter='', card_at=None, hide=frozenset(), frames=None):
    data = context(project, ctx, beats, sources, chapter, card_at, hide)
    if data['screens'] and card_at is None:
        data['screens'][-1]['duration'] = seconds-data['screens'][-1]['start']
    result = scene_builder.render(project, TEMPLATE, data, out, seconds=seconds,
        size=size, fps=fps, crf=crf, frames=frames)
    out.with_suffix(out.suffix+'.stats.json').write_text(json.dumps(result.stats, sort_keys=True))
    return result.path

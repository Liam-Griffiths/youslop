"""Ticker plates and native media; cuts/kit own all cue clocks."""
import json

from .. import scene_builder, scenes
from . import kit, ticker as t

TEMPLATE = 'cuts/ticker.html'


def _numbers(pre, value, post, decimals, delay=0, arrival=1):
    return [f'{pre}{value*kit.ease_out((i/16*(delay+arrival)-delay)/arrival):,.{decimals}f}{post}' for i in range(17)]


def _panel(cue, dur, accent, pal):
    c = dict(cue)
    if c['kind'] == 'stat':
        pre, num, post, dec = t._split(c['value'])
        size, _ = kit.fit(c['value'], 'mono_bold', 220, 1500, 1, floor=80)
        c.update(size=size, cy=kit.H*.46, arrival=min(1, dur*.5),
                 values=_numbers(pre,num,post,dec,.05,min(1,dur*.5)) if num is not None else [c['value']],
                 down=c.get('delta','').startswith('-'))
    elif c['kind'] == 'chart':
        pts = c['points']; lo, hi = min(pts), max(pts)
        if hi-lo < 1e-9:
            lo, hi = lo-1, hi+1
        pad = (hi-lo)*.12; lo, hi = lo-pad, hi+pad
        dec = 0 if hi-lo > 20 else 1 if hi-lo > 2 else 2
        xy = [(1520*j/(len(pts)-1), 680-(p-lo)/(hi-lo)*680) for j,p in enumerate(pts)]
        arrival = min(1.6, dur*.6)
        # Include every vertex so interpolation never cuts across sharp turns.
        progress = sorted({j/32 for j in range(33)} | {j/(len(pts)-1) for j in range(len(pts))})
        keys = []
        for f in progress:
            u = (f/4)**(1/3) if f < .5 else 1-((1-f)/4)**(1/3)
            reach=f*(len(pts)-1); j=min(int(reach),len(pts)-2); r=reach-j
            keys.append(dict(t=.1+arrival*u,x=1520*f,y=kit.lerp(xy[j][1],xy[j+1][1],r)-xy[0][1]))
        c.update(xy=xy, points_svg=' '.join(f'{x},{y}' for x,y in xy), keys=keys,
                 arrival=arrival, color=t.UP if pts[-1]>=pts[0] else t.DOWN,
                 axes=[dict(y=930-j*170,label=t._fmt(lo+(hi-lo)*j/4,c['unit'],dec)) for j in range(5)],
                 final=t._fmt(pts[-1],c['unit'],dec))
    elif c['kind'] == 'bars':
        items=c['items']; top=max(abs(i['value']) for i in items) or 1
        slot=700/len(items); bh=min(110,slot*.62)
        best=max(range(len(items)),key=lambda j:items[j]['value'])
        c['rows']=[dict(label=it['label'], y=270+slot*j+(slot-bh)/2, h=bh,
            width=max(2,1060*abs(it['value'])/top), start=.1+j*.15,
            color=accent if j==best else pal['hi'], values=_numbers('',it['value'],'',0 if top>100 else 1,.1+j*.15,.7),
            keys=[dict(t=.1+j*.15,x=0,y=0),dict(t=.8+j*.15,x=1060*abs(it['value'])/top,y=0,ease='cubic-out')])
            for j,it in enumerate(items)]
    else:
        size, rows=kit.fit(c['text'],'display',84,1500,2,floor=40)
        c.update(size=size, rows=rows, ty=1010-(len(rows)-1)*size*1.1)
    return c


def context(project, ctx, beats, sources, chapter='', card_at=None, hide=frozenset()):
    data=scenes.context_base(project,ctx.channel)
    data['palette'].update(t._pal(ctx),accent=ctx.accent,accent2=ctx.accent2)
    data['fonts'].update({name:'/fonts/'+kit.FACES[face] for name,face in
        [('Display','display'),('Condensed','condensed'),('Bold','sans_bold'),('Mono','mono'),('MonoBold','mono_bold')]})
    title_size,title_rows=kit.fit(project.title.upper(),'condensed',36,1100,1,floor=20)
    chapter_size,chapter_rows=kit.fit(chapter.upper(),'mono_bold',92,1580,2,floor=44)
    data.update(look=ctx.look or 'terminal',screens=[],chapter=chapter,card_at=card_at,
        title_size=title_size,title=title_rows[0] if title_rows else '',
        chapter_size=chapter_size,chapter_rows=chapter_rows)
    offset=0
    for beat,source in zip(beats,sources):
        for i,(cue,(a,b)) in enumerate(zip(beat.cues,beat.times)):
            start=offset+(a if i else 0); end=min(offset+b,card_at if card_at is not None else float('inf'))
            if end<=start:
                continue
            data['screens'].append(dict(id=f'cue{len(data["screens"])}',start=start,duration=end-start,
                cue=_panel(cue,max(.2,b-a),ctx.accent,data['palette']), delay=a-(start-offset),
                source=str(source) if source else '',video=bool(beat.motion),media_time=start-offset,
                stamp=[source.stat().st_mtime_ns,source.stat().st_size] if source else None,
                hidden='cues' in hide,media=bool(source) and ('cues' in hide or cue['kind']=='headline')))
        offset+=beat.length
    return data


def render(project,ctx,beats,sources,out,*,seconds,size,fps,crf,
           chapter='',card_at=None,hide=frozenset(),frames=None):
    data=context(project,ctx,beats,sources,chapter,card_at,hide)
    if data['screens'] and card_at is None:
        data['screens'][-1]['duration']=seconds-data['screens'][-1]['start']
    result=scene_builder.render(project,TEMPLATE,data,out,seconds=seconds,size=size,fps=fps,crf=crf,frames=frames)
    out.with_suffix(out.suffix+'.stats.json').write_text(json.dumps(result.stats,sort_keys=True))
    return result.path

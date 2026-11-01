"""Casefile world plates; the existing board layout and kit own placement/time."""
import json
import random

from .. import scene_builder, scenes
from . import casefile as c, cues_for, kit, source_for

TEMPLATE = 'cuts/casefile.html'
SIZES = dict(photo=(600,700), card=(680,420), clipping=(600,640),
             note=(440,440), redacted=(580,720))


def _item(cue, source, board, n, seen):
    cue = dict(cue)
    if cue['kind'] == 'photo' and source:
        if str(source) in seen:
            cue = dict(kind='card', title='', text=cue.get('caption',''))
        else:
            seen.add(str(source))
    kind = cue['kind']; w,h = SIZES[kind]
    x,y,angle = c._slots(board)[n % (c.COLS*c.ROWS)]
    rng = random.Random(str(cue))
    paper = {'photo':['#f0ece2','#ece8dc','#f4f2ec'], 'card':['#f6f2e6','#f0f4ee','#f8eed6'],
        'clipping':['#e2ded0','#ded6be','#e8e6de'], 'note':['#fada54','#f8b0be','#aad6f0'],
        'redacted':['#eeeee8']}[kind]
    return dict(cue, x=x, y=y, w=w, h=h, angle=0 if kind=='photo' else -angle,
        paper=rng.choice(paper), rule=rng.choice(['#d65c5c','#5c78c8','#46966e']),
        pin='#'+''.join(f'{v:02x}' for v in c._pin_colour(board*100+n)),
        tape=kind=='photo' and rng.random()<.35,
        source=str(source) if source and kind=='photo' else '',
        stamp=[source.stat().st_mtime_ns,source.stat().st_size] if source and kind=='photo' else None,
        filler=[dict(width=rng.uniform(.4,1)* (w-80), black=rng.random()<.35) for _ in range(10)])


def _camera(beat, prev, item, a, offset, start, end):
    def sample(t):
        u=t-offset-a; m=kit.ease_in_out(kit.progress(u,0,.9))
        left,right=c._focus(prev),c._focus(item)
        cam=[kit.lerp(x,y,m) for x,y in zip(left,right)]
        if beat.last:
            pull=kit.ease_in_out(kit.progress(t-offset,beat.length-3.6,3))
            cam=[kit.lerp(x,y,pull) for x,y in zip(cam,c._focus(None))]
        # Match _view's clamping at the world edges.
        x,y,z=cam
        return dict(t=t,x=kit.clamp(x,960/z,max(960/z,c.WORLD_W-960/z)),
                    y=kit.clamp(y,540/z,max(540/z,c.WORLD_H-540/z)),zoom=z)
    # Sample only travel/overlapping overview, not holds or screenshot windows.
    times={start,end,offset+a,offset+a+.9}
    times.update(offset+a+.9*i/12 for i in range(13))
    if beat.last:
        times.update(offset+beat.length-3.6+3*i/20 for i in range(21))
    return [sample(t) for t in sorted(times) if start<=t<=end]


def context(project,ctx,beats,sources,chapter='',card_at=None,hide=frozenset()):
    data=scenes.context_base(project,ctx.channel)
    lo,hi={'wall':('#16161a','#343236'),'felt':('#163a28','#306e4a')}.get(ctx.look,('#4a2e1a','#96683e'))
    data['palette'].update(ground=lo,grain=hi,accent=ctx.accent,accent2=ctx.accent2)
    data['fonts'].update({name:'/fonts/'+kit.FACES[face] for name,face in
        [('Condensed','condensed'),('Mono','mono_bold'),('Typewriter','typewriter'),
         ('Hand','hand'),('Marker','marker'),('Serif','serif')]})
    data.update(look=ctx.look or 'cork',screens=[],chapter=chapter,card_at=card_at)
    boards=c._boards(ctx); offset=0
    for beat,source in zip(beats,sources):
        board,first=boards[beat.slide.id]; items=[]; seen=set()
        for slide in project.slides:
            if slide.id==beat.slide.id: break
            if boards[slide.id][0]==board:
                src=source_for(ctx,slide)
                for cue in cues_for(c,slide):
                    items.append(_item(cue,src,board,len(items),seen))
        for i,(cue,(a,b)) in enumerate(zip(beat.cues,beat.times)):
            item=_item(cue,source,board,first+i,seen)
            start=offset+(a if i else 0); end=min(offset+b,card_at if card_at is not None else float('inf'))
            if end>start:
                data['screens'].append(dict(id=f'cue{len(data["screens"])}',start=start,duration=end-start,
                    cue=cue,items=[*items,item],delay=offset+a-start,span=max(.6,(b-a)*.5),
                    camera=_camera(beat,items[-1] if items else None,item,a,offset,start,end),
                    hidden='cues' in hide,source=str(source) if source else '',video=bool(beat.motion),media_time=start-offset))
            items.append(item)
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

"""Casefile world plates; the existing board layout and kit own placement/time."""
import io
import json
import random

from PIL import Image, ImageFilter, ImageOps

from .. import scene_builder, scenes
from . import casefile as c, cues_for, kit, source_for

TEMPLATE = 'cuts/casefile.html'
SIZES = dict(photo=(600,700), card=(680,420), clipping=(600,640),
             note=(440,440), redacted=(580,720))


def _noise(size, sigma, rng):
    return Image.frombytes('L', size, bytes(
        max(0, min(255, int(rng.gauss(128, sigma)))) for _ in range(size[0]*size[1])))


def _assets(project, ctx):
    """Seeded equivalents of _ground; the lamp uses _light's exact pixels.

    Build once at Pillow's world resolution for this output size, never per
    frame. Keep generated assets in the scene cache, not in the source tree.
    """
    directory = scenes._directory(project)
    look = ctx.look if ctx.look in ('wall', 'felt') else 'cork'
    size = tuple(max(1, round(v * ctx.k * c.WORLD_SCALE)) for v in (c.WORLD_W, c.WORLD_H))
    ground = directory / f'casefile-ground-v1-{look}-{size[0]}x{size[1]}.png'
    if not ground.exists():
        rng = random.Random(f'casefile-ground-v1-{look}')

        small = tuple(max(1, v//3) for v in size)
        grain = _noise(small, 60, rng).resize(size, Image.Resampling.BILINEAR)
        lo, hi = {'wall':((22,22,26),(52,50,54)), 'felt':((22,58,40),(48,110,74))}.get(
            look, ((74,46,26),(150,104,62)))
        image = ImageOps.colorize(grain, lo, hi).convert('RGBA')
        if look == 'felt':
            mask = _noise(size, 90, rng).point(lambda v: 255 if v > 200 else 0)
            image.paste((150,200,170,36), (0,0,*size), mask)
        elif look == 'cork':
            mask = _noise(size, 120, rng).point(lambda v: 255 if v > 232 else 0)
            image.paste((40,22,10,120), (0,0,*size), mask)
        # _world drops alpha before softening. In particular, felt fibres and
        # cork specks retain their RGB, rather than blending with the backdrop.
        image = image.convert('RGB').filter(ImageFilter.GaussianBlur(2.9 * ctx.k * c.WORLD_SCALE))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        scene_builder._write(ground, buffer.getvalue())
    lamp = directory / f'casefile-lamp-v1-{ctx.size[0]}x{ctx.size[1]}.png'
    if not lamp.exists():
        buffer = io.BytesIO()
        c._light(ctx).save(buffer, format='PNG')
        scene_builder._write(lamp, buffer.getvalue())
    return '/scene/{token}/project/scenes/' + ground.name, str(lamp)


def _item(cue, source, board, n, seen):
    cue = dict(cue)
    if cue['kind'] == 'photo' and source:
        if str(source) in seen:
            cue = dict(kind='card', title='', text=cue.get('caption',''))
        else:
            seen.add(str(source))
    kind = cue['kind']; w,h = SIZES[kind]
    x,y,angle = c._slots(board)[n % (c.COLS*c.ROWS)]
    rng = random.Random(str(cue.get('title')) + str(cue.get('text')) if kind == 'card' else str(cue))
    paper = {'photo':['#f0ece2','#ece8dc','#f4f2ec'], 'card':['#f6f2e6','#f0f4ee','#f8eed6'],
        'clipping':['#e2ded0','#ded6be','#e8e6de'], 'note':['#fada54','#f8b0be','#aad6f0'],
        'redacted':['#eeeee8']}[kind]
    # _item(photo) consumes the paper choice before choosing monochrome. Use
    # that same caption seed and call order, including for settled history.
    photo_rng = random.Random(str(cue.get('caption')))
    photo_paper = photo_rng.choice(paper) if kind == 'photo' else None
    grayscale = photo_rng.random() < .3 if kind == 'photo' else False
    chosen_paper = rng.choice(paper)
    return dict(cue, x=x, y=y, w=w, h=h, angle=0 if kind=='photo' else -angle,
        paper=photo_paper or chosen_paper, rule=rng.choice(['#d65c5c','#5c78c8','#46966e']),
        pin='#'+''.join(f'{v:02x}' for v in c._pin_colour(board*100+n)),
        tape=kind=='photo' and rng.random()<.35,
        source=str(source) if source and kind=='photo' else '',
        grayscale=grayscale, wash=[255,220,170,34],
        card_lines=kit.wrap(cue.get('text',''), 'typewriter', 36, 600)[:5] if kind == 'card' else [],
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
    data['ground_url'], data['builder_top_plate'] = ('', None) if 'cues' in hide else _assets(project, ctx)
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

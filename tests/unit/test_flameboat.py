"""Flameboat migration: real cue clocks and compiler, mocked browser/encoder."""
import json
from pathlib import Path

from PIL import Image
import pytest

from app import cuts, render, scene_builder as b, scenes
from app.cuts import flameboat_scene as f
from tests.unit.test_scene_builder import mocked, scene

CUES = [dict(kind='image',focus='left',label='B roll'),
        dict(kind='title',text='Correct code ships faster',hot='ships faster'),
        dict(kind='code',lang='py',lines=['def run():','    return 42'],hot=2),
        dict(kind='term',cmd='echo ready',out=['success','error: denied']),
        dict(kind='diagram',nodes=['Client','API','DB'],label='The request'),
        dict(kind='logo',text='Python',sub='A tool'), dict(kind='stat',value='10x',label='faster'),
        dict(kind='meme',top='Ship it',bottom='this is fine'),
        dict(kind='post',handle='@made_up',text='Works on my machine')]


@pytest.mark.parametrize('look', ['', 'midnight'])
def test_flameboat_dispatch_timing_and_all_kinds(project, tmp_path, monkeypatch, look):
    project.style.format, project.style.cut_look = 'flameboat', look
    project.style.accent = '#ff6600'
    slide = project.slides[0]
    slide.take = {'duration':7.1}
    slide.cues['flameboat'] = [dict(c,at=i*.65) for i,c in enumerate(CUES)]
    group = [(slide,7.1),(project.slides[1],3)]
    expected = cuts.timed_cues(project,group,11.13,.6)
    before = render.timeline(project)
    calls=[]
    def builder(owner, template, ctx, out, **kw):
        calls.append((ctx,kw))
        html=scenes.render_html(template,dict(ctx,duration=kw['seconds']))
        assert scenes.lint(html)==[]
        assert 'data-capture="frames"' not in html and 'data-type' in html
        assert 'ArchivoBlack-Regular.ttf' in html and 'JetBrainsMono-Bold.ttf' in html
        assert ctx['palette']['ground']==cuts.flameboat.GROUNDS[look][0]
        assert ctx['palette']['accent']=='#ff6600'
        return b.Result(out,dict(captured_frames=0))
    monkeypatch.setattr(b,'render',builder)
    monkeypatch.setattr(cuts,'load_picture',lambda *a:pytest.fail('Pillow picture load'))
    monkeypatch.setattr(cuts.flameboat,'frame',lambda *a:pytest.fail('Pillow frame'))
    out=tmp_path/'out.webm'
    cuts.render_segment(project,group,11.13,out,size=(480,270),lead_in=.6,
                        chapter=('Next chapter',''),hold=1,frames=(4,20))
    ctx,kw=calls[0]
    for (_,cues,times),(_,dur) in zip(expected,group):
        for c,(a,z) in zip(cues,times):
            if a>=10.13 or z<=a:
                continue
            s=next(s for s in ctx['screens'] if s['start']==a)
            assert s['cue']['kind']==c['kind']
            assert s['duration']==pytest.approx(min(z,10.13)-a)
    assert kw['seconds']==cuts.frame_count(11.13,30)/30 and kw['frames']==(4,20)
    assert ctx['card_at']==10.13
    assert json.loads(out.with_suffix('.webm.stats.json').read_text())['captured_frames']==0
    project.style.cut_engine='pillow'
    assert cuts.timed_cues(project,group,11.13,.6)==expected
    assert render.timeline(project)==before


def test_flameboat_media_run_and_paragraph_clock(project,tmp_path):
    project.style.format='flameboat'
    slide=project.slides[0]
    slide.cues['flameboat']=[dict(CUES[0],at=0),dict(CUES[0],focus='right',at=1),
                            dict(CUES[1],at=2),dict(CUES[0],at=3)]
    source=tmp_path/'clip.mp4';source.touch()
    ctx=cuts.make_ctx(project,(480,270),30,image_for=lambda s:source)
    beat=cuts.beat_for(cuts.flameboat,ctx,slide,4,0,4,scene=True)
    data=f.context(project,ctx,[beat],[source])
    a,z,_,back=data['screens']
    assert a['focal']==z['focal']==[.18,.45]
    assert a['camera'][-1]==z['camera'][0]  # no second hit on adjacent images
    assert back['media_time']==3 and back['video']
    assert back['stamp']==[source.stat().st_mtime_ns,0]
    assert len(back['camera'])<=48
    hidden=f.context(project,ctx,[beat],[source],hide={'cues'})
    assert all(s['hidden'] and s['media'] for s in hidden['screens'])
    html=scenes.render_html(f.TEMPLATE,dict(hidden,colors=cuts.flameboat.COLORS))
    assert 'data-type data-start=' not in html and 'class="title fit"' not in html


def test_flameboat_still_bypass_and_pillow(project,tmp_path,monkeypatch):
    project.style.format='flameboat'
    monkeypatch.setattr(scenes,'handles',lambda fmt:True)
    monkeypatch.setattr(scenes,'render_segment',lambda *a,**k:pytest.fail('generic branch'))
    calls=[]
    def builder(*args,**kw):
        calls.append(kw);return b.Result(args[3])
    monkeypatch.setattr(b,'render',builder)
    monkeypatch.setattr(cuts.ffutil,'run',lambda args:Path(args[-1]).touch())
    out=tmp_path/'still.png'
    cuts.still(project,project.slides[0],out,at=.6)
    assert out.exists() and calls[0]['frames'][1]==calls[0]['frames'][0]+1
    render._render_segment(project,[(project.slides[0],3)],4,0,tmp_path/'out.mp4')
    assert len(calls)==2
    project.style.cut_engine='pillow'
    assert not cuts.uses_scene(project.style)
    drawn=[]
    monkeypatch.setattr(cuts.flameboat,'frame',lambda *a:drawn.append(a[2]) or Image.new('RGB',(48,27)))
    def encode(stream,out,**kw):
        next(stream);out.touch();return True
    monkeypatch.setattr(cuts.ffutil,'encode_frames',encode)
    cuts.render_segment(project,[(project.slides[0],2)],2,tmp_path/'pillow.mp4',size=(48,27),frames=(3,4))
    assert drawn==[.1]


def test_flameboat_native_media_and_shared_motions(tmp_path):
    ground=tmp_path/'ground.png';Image.new('RGBA',(48,27)).save(ground)
    data=scene(1,2)
    data.update(width=192,height=108,ground_color='#101010')
    data['layers'][0].update(path=str(ground),motion='wipe',ease='linear',steps=[(.1,4),(.2,8)])
    screen=dict(id='',start=0,duration=2,offset=.2,ground_path=str(ground),
        raster=dict(left=0,top=0,density=.25,width=48,height=27),
        camera=[dict(t=0,x=96,y=54,zoom=1)],
        media=[dict(path='video.mp4',video=True,time=3,box=[0,0,48,27],dim=1,focal=[.18,.45])])
    inputs,graph=b._compile(data,screen,(48,27),30,tmp_path)
    assert inputs[inputs.index('-ss')+1]=='3.2'
    assert 'rr=1:gg=1:bb=1' in graph and '(iw-ow)*0.18:(ih-oh)*0.45' in graph
    assert 'if(gte(T,' in graph and len(graph.encode())<65536
    assert '.53' in b._media_filter({},48,27)  # Loudmouth default remains dimmed
    for motion,s in [('node',1.9),('badge',2.4)]:
        layer=dict(motion=motion,start=0,arrival=.3)
        assert f'{s+1}' in b._motion(layer)['scale']


def test_flameboat_mocked_capture_cache_and_chunk(project,mocked,tmp_path,monkeypatch):
    data,captures=mocked
    data.update(scene(2,4))
    data['screens']=[dict(id=str(i),start=i*2,duration=2,world=True,
        camera=[dict(t=i*2,x=960,y=540,zoom=1),dict(t=i*2+2,x=960,y=540,zoom=1.07)]) for i in range(2)]
    for i,layer in enumerate(data['layers']):
        layer.update(screen=str(i),duration=2,motion='wipe',ease='linear',steps=[(.1,4),(.2,8)])
    original=b.stage.capture_stills
    def capture(items,directory,**kw):
        probe=kw['scene_probe']
        def world_probe(cdp,*args):
            send=cdp.send
            cdp.send=lambda method,params,session: {} if method.startswith('Emulation.') else send(method,params,session)
            return probe(cdp,*args)
        return original(items,directory,**dict(kw,scene_probe=world_probe))
    monkeypatch.setattr(b.stage,'capture_stills',capture)
    project.style.format='flameboat'
    out=tmp_path/'preview.webm'
    for n in range(2):
        cuts.render_segment(project,[(project.slides[0],4)],4,out,size=(480,270),frames=(59,62))
        stats=json.loads(out.with_suffix('.webm.stats.json').read_text())
        assert stats['passes']==2 and stats['captured_frames']==0
        assert stats['screenshots']==(2 if n==0 else 0)
        assert stats['largest_graph_bytes']<65536
    assert len(captures)==2

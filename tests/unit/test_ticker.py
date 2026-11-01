"""Ticker migration: actual cue clocks, mocked Chromium, shared ffmpeg motions."""
import json
from pathlib import Path

from PIL import Image
import pytest

from app import cuts, render, scene_builder as b, scenes
from app.cuts import ticker_scene as t
from tests.unit.test_scene_builder import mocked, scene, REAL_RUN

CUES=[dict(kind='stat',value='$4.2T',label='Market value',delta='-3.1%'),
      dict(kind='chart',title='Market trend',points=[4,2,8,3,9],unit='$',start='2015',end='2025',illustrative=True),
      dict(kind='bars',title='Comparison',items=[dict(label='Loss',value=-3),dict(label='Gain',value=8)]),
      dict(kind='headline',kicker='MARKETS',text='A headline that wraps across two lines with clear type')]


@pytest.mark.parametrize('look',['','amber'])
def test_ticker_dispatch_kinds_and_timing(project,tmp_path,monkeypatch,look):
    project.style.format,project.style.cut_look='ticker',look
    project.style.accent='#ff6600'
    slide=project.slides[0];slide.take={'duration':8}
    slide.cues['ticker']=[dict(c,at=i*2) for i,c in enumerate(CUES)]
    group=[(slide,8),(project.slides[1],3)]
    expected=cuts.timed_cues(project,group,12.13,.6);before=render.timeline(project)
    calls=[]
    def builder(owner,template,ctx,out,**kw):
        calls.append((ctx,kw));html=scenes.render_html(template,dict(ctx,duration=kw['seconds']))
        assert scenes.lint(html)==[]
        assert 'data-capture="frames"' not in html and 'data-atlas="17"' in html
        assert 'ArchivoNarrow-Bold.ttf' in html and 'JetBrainsMono-Bold.ttf' in html
        assert ctx['palette']['ground']==cuts.ticker.LOOKS_COLORS[look]['ground']
        assert ctx['palette']['accent']=='#ff6600'
        return b.Result(out,dict(captured_frames=0))
    monkeypatch.setattr(b,'render',builder)
    monkeypatch.setattr(cuts,'load_picture',lambda *a:pytest.fail('Pillow picture load'))
    monkeypatch.setattr(cuts.ticker,'frame',lambda *a:pytest.fail('Pillow frame'))
    out=tmp_path/'out.mp4'
    cuts.render_segment(project,group,12.13,out,size=(480,270),lead_in=.6,chapter=('Next section',''),hold=1,frames=(4,20))
    ctx,kw=calls[0]
    for _,cues,times in expected:
        for cue,(a,z) in zip(cues,times):
            if z<=a or a>=11.13:continue
            s=next(s for s in ctx['screens'] if s['start']==a)
            assert s['cue']['kind']==cue['kind']
            assert s['duration']==pytest.approx(min(z,11.13)-a)
    assert kw['seconds']==cuts.frame_count(12.13,30)/30 and kw['frames']==(4,20)
    assert ctx['card_at']==11.13
    assert json.loads(out.with_suffix('.mp4.stats.json').read_text())['captured_frames']==0
    project.style.cut_engine='pillow'
    assert cuts.timed_cues(project,group,12.13,.6)==expected and render.timeline(project)==before


def test_ticker_geometry_media_and_edge_values(project,tmp_path):
    project.style.format='ticker';slide=project.slides[0]
    slide.cues['ticker']=[dict(c,at=i*2) for i,c in enumerate(CUES)]
    source=tmp_path/'clip.mp4';source.touch()
    ctx=cuts.make_ctx(project,(480,270),30,image_for=lambda s:source)
    beat=cuts.beat_for(cuts.ticker,ctx,slide,8,0,8,scene=True)
    data=t.context(project,ctx,[beat],[source]);stat,chart,bars,headline=data['screens']
    assert stat['cue']['values'][0]=='$0.0T' and stat['cue']['values'][-1]=='$4.2T'
    assert stat['cue']['down'] and len(stat['cue']['values'])==17
    assert chart['cue']['final']=='$9.0' and chart['cue']['color']==cuts.ticker.UP
    assert chart['cue']['keys'][-1]['x']==1520 and len(chart['cue']['keys'])<=48
    assert bars['cue']['rows'][0]['values'][-1]=='-3.0'
    assert bars['cue']['rows'][1]['width']==1060
    assert headline['media'] and headline['video'] and headline['media_time']==6
    assert headline['stamp']==[source.stat().st_mtime_ns,0] and len(headline['cue']['rows'])==2
    hidden=t.context(project,ctx,[beat],[source],hide={'cues'})
    assert all(s['hidden'] and s['media'] for s in hidden['screens'])
    html=scenes.render_html(t.TEMPLATE,hidden)
    assert 'data-atlas="17"' not in html and 'data-media-dim="1"' in html
    for points in ([0,0],[9,1],list(range(16))):
        panel=t._panel(dict(CUES[1],points=points),2,ctx.accent,data['palette'])
        assert len(panel['keys'])<=48 and len(panel['axes'])==5
    assert t._panel(dict(CUES[0],value='N/A'),2,ctx.accent,data['palette'])['values']==['N/A']
    zero=t._panel(dict(CUES[2],items=[dict(label='A',value=0),dict(label='B',value=0)]),2,ctx.accent,data['palette'])
    assert all(r['width']==2 for r in zero['rows'])


def test_ticker_still_bypass_and_pillow(project,tmp_path,monkeypatch):
    project.style.format='ticker';calls=[]
    monkeypatch.setattr(scenes,'handles',lambda fmt:True)
    monkeypatch.setattr(scenes,'render_segment',lambda *a,**k:pytest.fail('generic branch'))
    monkeypatch.setattr(b,'render',lambda *a,**kw:calls.append(kw) or b.Result(a[3]))
    monkeypatch.setattr(cuts.ffutil,'run',lambda args:Path(args[-1]).touch())
    out=tmp_path/'still.png';cuts.still(project,project.slides[0],out,at=.6)
    assert out.exists() and calls[0]['frames'][1]==calls[0]['frames'][0]+1
    render._render_segment(project,[(project.slides[0],3)],4,0,tmp_path/'out.mp4')
    assert len(calls)==2
    project.style.cut_engine='pillow';assert not cuts.uses_scene(project.style)
    drawn=[]
    monkeypatch.setattr(cuts.ticker,'frame',lambda *a:drawn.append(a[2]) or Image.new('RGB',(48,27)))
    def encode(stream,out,**kw):next(stream);out.touch();return True
    monkeypatch.setattr(cuts.ffutil,'encode_frames',encode)
    cuts.render_segment(project,[(project.slides[0],2)],2,tmp_path/'pillow.mp4',size=(48,27),frames=(3,4))
    assert drawn==[.1]


def test_ticker_explicit_first_cue_and_max_chart_graph(project,tmp_path):
    project.style.format='ticker';slide=project.slides[0]
    slide.cues['ticker']=[dict(CUES[1],at=1,points=list(range(16)))]
    ctx=cuts.make_ctx(project,(480,270),30)
    beat=cuts.beat_for(cuts.ticker,ctx,slide,4,0,4,scene=True)
    data=t.context(project,ctx,[beat],[None]);screen=data['screens'][0]
    assert screen['start']==0 and screen['delay']==1
    assert 'data-cue-delay="1.0"' in scenes.render_html(t.TEMPLATE,data)
    ground=tmp_path/'ground.png';Image.new('RGBA',(48,28)).save(ground)
    probe=scene(1,4);probe.update(width=1920,height=1080,ground_path=str(ground))
    probe['layers'][0].update(path=str(ground),motion='none',pathKeys=screen['cue']['keys'])
    _,graph=b._compile(probe,dict(id='',start=0,duration=4),(48,28),30,tmp_path)
    assert len(graph.encode())<65536 and 'if(lt(t,' in graph


def test_ticker_mocked_capture_cache_and_chunk(project,mocked,tmp_path):
    data,captures=mocked;data.update(scene(2,4))
    data['screens']=[dict(id=str(i),start=i*2,duration=2) for i in range(2)]
    for i,layer in enumerate(data['layers']):layer.update(screen=str(i),duration=2,motion='reveal')
    data['layers'][0].update(motion='atlas',atlas=3,box=[0,0,20,60],
        pathKeys=[dict(t=0,x=0,y=0),dict(t=1,x=16,y=0)])
    project.style.format='ticker';out=tmp_path/'preview.mp4'
    for n in range(2):
        cuts.render_segment(project,[(project.slides[0],4)],4,out,size=(480,270),frames=(59,62))
        stats=json.loads(out.with_suffix('.mp4.stats.json').read_text())
        assert stats['passes']==2 and stats['captured_frames']==0
        assert stats['screenshots']==(3 if n==0 else 0) and stats['largest_graph_bytes']<65536
    assert len(captures)==3


def test_ticker_shared_atlas_and_path_pixels(tmp_path):
    """A tiny synthetic plate checks actual crop selection and chunk clock in ffmpeg."""
    ground=tmp_path/'ground.png';Image.new('RGBA',(48,28),'black').save(ground)
    atlas=tmp_path/'atlas.png';image=Image.new('RGBA',(8,12))
    for i,color in enumerate(['red','green','blue']):image.paste(color,(0,i*4,8,(i+1)*4))
    image.save(atlas)
    data=scene(1,2);data.update(width=48,height=28,ground_path=str(ground),alpha=True)
    data['layers'][0].update(path=str(atlas),box=[0,0,8,12],motion='atlas',arrival=1,atlas=3,
        pathKeys=[dict(t=0,x=0,y=0),dict(t=1,x=16,y=8)])
    for offset,color,x,y in [(0,(255,0,0),2,1),(.5,(0,128,0),10,5),(1.2,(0,0,255),18,9)]:
        inputs,graph=b._compile(data,dict(id='',start=0,duration=.1,offset=offset),(48,28),10,tmp_path)
        script=tmp_path/'graph.ffgraph';script.write_text(graph)
        out=tmp_path/'pixel.png'
        args=[*inputs,'-filter_complex_threads','1','-filter_complex_script',str(script),'-map','[out]','-frames:v','1',str(out)]
        try:REAL_RUN(args)
        except b.ffutil.FFError as exc:
            if "Unrecognized option 'filter_complex_script'" not in str(exc):raise
            args[args.index('-filter_complex_script')]='-/filter_complex';REAL_RUN(args)
        with Image.open(out) as frame:assert frame.getpixel((x,y))[:3]==color
    data['layers'][0]['atlas']=65
    data.update(budget=.1)
    with pytest.raises(ValueError,match='atlas'):b._plan(data,2,10)

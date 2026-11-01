"""Group Chat clocks/history and builder dispatch, without Chromium or an LLM."""
import json
from pathlib import Path

from PIL import Image
import pytest

from app import cuts, render, scenes, scene_builder as b
from app.cuts import groupchat_scene as g
from tests.unit.test_scene_builder import mocked, pixel_browser, scene, REAL_RUN

CUES = [dict(kind='msg', **{'from':'Mom'}, text='A long message with enough words to wrap clearly inside the bubble.'),
        dict(kind='msg', **{'from':'me'}, text='I will be there.'),
        dict(kind='photo', **{'from':'Mom'}), dict(kind='notice', text='Tuesday 11:42 PM'),
        dict(kind='image', focus='right', caption='The place we met')]


@pytest.mark.parametrize('look', ['', 'light'])
def test_groupchat_dispatch_clocks(project, tmp_path, monkeypatch, look):
    project.style.format, project.style.cut_look = 'groupchat', look
    slide = project.slides[0]; slide.take = {'duration':10}
    slide.cues['groupchat'] = [dict(c, at=i*2) for i,c in enumerate(CUES)]
    group = [(slide,10), (project.slides[1],3)]
    before = render.timeline(project); expected = cuts.timed_cues(project,group,14.13,.6); calls=[]
    def builder(owner, template, ctx, out, **kw):
        calls.append((ctx,kw)); html=scenes.render_html(template,dict(ctx,duration=kw['seconds']))
        assert scenes.lint(html)==[] and 'data-capture="frames"' not in html
        assert 'Inter-Medium.ttf' in html and 'Inter-Bold.ttf' in html
        assert ctx['palette']['panel']==cuts.groupchat.THEMES[look]['panel']
        return b.Result(out,dict(captured_frames=0))
    monkeypatch.setattr(b,'render',builder)
    monkeypatch.setattr(cuts,'load_picture',lambda *a:pytest.fail('Pillow picture load'))
    monkeypatch.setattr(cuts.groupchat,'frame',lambda *a:pytest.fail('Pillow frame'))
    out=tmp_path/'out.mp4'
    cuts.render_segment(project,group,14.13,out,size=(480,270),lead_in=.6,chapter=('Next chapter',''),hold=1,frames=(4,20))
    data,kw=calls[0]; screens=data['screens']
    assert kw['frames']==(4,20) and kw['seconds']==cuts.frame_count(14.13,30)/30
    assert screens[0]['start']==0 and screens[-1]['start']+screens[-1]['duration']==13.13
    assert all(a['start']+a['duration']==pytest.approx(z['start']) for a,z in zip(screens,screens[1:]))
    for _,cues,times in expected:
        for cue,(a,z) in zip(cues,times):
            if z<=a or a>=13.13:continue
            s=next(s for s in screens if s['start']==a)
            assert s['cue']==cue
    typing,arrival,hold=screens[:3]
    assert typing['duration']==pytest.approx(.6) and typing['typing']
    assert arrival['duration']==pytest.approx(.28) and hold['phase']=='hold'
    assert len(typing['items'])==0 and arrival['items'][-1]['name']=='Mom'
    assert json.loads(out.with_suffix('.mp4.stats.json').read_text())['captured_frames']==0
    project.style.cut_engine='pillow'
    assert cuts.timed_cues(project,group,14.13,.6)==expected and render.timeline(project)==before


def test_groupchat_history_media_chapters_and_missing_picture(project,tmp_path,monkeypatch):
    project.style.format='groupchat';a,z=project.slides[:2]
    a.cues['groupchat']=[dict(CUES[2]),dict(CUES[0])]
    z.cues['groupchat']=[dict(CUES[0],at=1),dict(CUES[4],at=3)]
    photo=tmp_path/'poster.png';Image.new('RGB',(8,8),'red').save(photo)
    clip=tmp_path/'clip.mp4';clip.touch()
    monkeypatch.setattr(cuts,'load_picture',lambda *a:pytest.fail('history decoded in Pillow'))
    ctx=cuts.make_ctx(project,(480,270),30,image_for=lambda s:photo if s.id==a.id else clip)
    beat=cuts.beat_for(cuts.groupchat,ctx,z,5,0,5,scene=True)
    data=g.context(project,ctx,[beat],[clip]);first=data['screens'][0]
    assert first['start']==0 and first['duration']==1.6
    assert first['items'][0]['source']==str(photo) and first['items'][0]['stamp'][1]>0
    incoming=next(s for s in data['screens'] if s['phase']=='arrival')
    assert incoming['items'][-1]['name']==''  # Mom continues the previous sender run.
    image=data['screens'][-1]
    assert image['cutaway'] and image['video'] and image['media_time']==3
    assert image['camera'][1]['zoom']>image['camera'][0]['zoom']==1
    html=scenes.render_html(g.TEMPLATE,data)
    assert scenes.lint(html)==[] and 'data-video="false"' in html and 'data-video="true"' in html
    z.chapter='New thread'
    assert not g.context(project,ctx,[beat],[clip])['screens'][0]['items']
    z.chapter='';hidden=g.context(project,ctx,[beat],[clip],hide={'cues'})
    assert all(s['cutaway'] and s['hidden'] for s in hidden['screens'])
    assert 'class="chrome"' not in scenes.render_html(g.TEMPLATE,hidden)
    missing=g.context(project,ctx,[beat],[None])
    assert not missing['screens'][-1]['cutaway'] and missing['screens'][-1]['phase']=='hold'
    assert missing['screens'][-1]['items']==missing['screens'][-2]['items']


def test_groupchat_still_bypass_and_pillow(project,tmp_path,monkeypatch):
    project.style.format='groupchat';calls=[]
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
    monkeypatch.setattr(cuts.groupchat,'frame',lambda *a:drawn.append(a[2]) or Image.new('RGB',(48,27)))
    def encode(stream,out,**kw):next(stream);out.touch();return True
    monkeypatch.setattr(cuts.ffutil,'encode_frames',encode)
    cuts.render_segment(project,[(project.slides[0],2)],2,tmp_path/'pillow.mp4',size=(48,27),frames=(3,4))
    assert drawn==[.1]


def test_groupchat_mocked_native_capture_cache_and_chunk(project,mocked,tmp_path):
    data,captures=mocked;data.update(scene(2,4))
    photo=tmp_path/'photo.png';Image.new('RGB',(8,8),'red').save(photo)
    data['layers'][0].update(native=str(photo),motion='none',clip=[0,0,20,20])
    project.style.format='groupchat';out=tmp_path/'preview.mp4'
    for n in range(2):
        cuts.render_segment(project,[(project.slides[0],4)],4,out,size=(480,270),frames=(59,62))
        stats=json.loads(out.with_suffix('.mp4.stats.json').read_text())
        assert stats['captured_frames']==0 and stats['largest_graph_bytes']<65536
        assert stats['screenshots']==(2 if n==0 else 0)
    assert len(captures)==2


def test_groupchat_native_scroll_clip_pixels(tmp_path):
    """Real ffmpeg on tiny synthetic plates checks clipping and chunk clocks."""
    ground=tmp_path/'ground.png';Image.new('RGBA',(48,28),'black').save(ground)
    photo=tmp_path/'photo.png';Image.new('RGBA',(8,8),'red').save(photo)
    data=scene(1,2);data.update(width=48,height=28,ground_path=str(ground),alpha=True)
    layer=data['layers'][0];layer.update(path=str(photo),native=str(photo),dim=1,motion='none',box=[8,4,16,12],clip=[10,8,18,14],
        pathKeys=[dict(t=0,x=0,y=0),dict(t=.5,x=0,y=8)])
    for offset,y in [(0,9),(.5,13)]:
        inputs,graph=b._compile(data,dict(id='',start=0,duration=.1,offset=offset),(48,28),10,tmp_path)
        script=tmp_path/'graph.ffgraph';script.write_text(graph);out=tmp_path/'pixel.png'
        args=[*inputs,'-filter_complex_threads','1','-filter_complex_script',str(script),'-map','[out]','-frames:v','1',str(out)]
        try:REAL_RUN(args)
        except b.ffutil.FFError as exc:
            if "Unrecognized option 'filter_complex_script'" not in str(exc):raise
            args[args.index('-filter_complex_script')]='-/filter_complex';REAL_RUN(args)
        with Image.open(out) as frame:
            assert frame.getpixel((12,y))[:3]==(255,0,0)
            assert frame.getpixel((9,y))[:3]==frame.getpixel((12,15))[:3]==(0,0,0)
    layer.update(video=True,time=1.25)
    inputs,_=b._compile(data,dict(id='',start=0,duration=.1,offset=.5),(48,28),10,tmp_path)
    assert inputs[inputs.index('-ss')+1]=='1.75'
    layer['clip']=[0,1,0,2]
    with pytest.raises(ValueError,match='clip'):b._plan(data,2,10)


def test_groupchat_native_world_probe_coordinates(pixel_browser,tmp_path):
    data,state=pixel_browser;data.update(scene(1,2))
    data['screens']=[dict(id='thread',start=0,duration=2,world=True,media=[],
        camera=[dict(t=0,x=72,y=48,zoom=1)])]
    photo=tmp_path/'photo.png';Image.new('RGB',(8,8),'red').save(photo)
    data['layers'][0].update(screen='thread',native=str(photo),motion='none',
        box=[30,20,50,40],clip=[24,16,96,64])
    stats=dict(captures=0,cache_hits=0,captured_frames=0)
    plates=b._plates(tmp_path/'plates','mock.html',dict(width=96,height=64,palette=dict(ground='#000000')),
        2,(48,32),30,stats)
    assert plates['layers'][0]['box']==[3,2,13,12]
    assert plates['layers'][0]['clip']==[0,0,36,24]
    assert plates['layers'][0]['path']==str(photo) and not state['shots']

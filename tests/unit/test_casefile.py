"""Casefile clocks, persistent boards and native plates, with mocked Chromium."""
import json
from pathlib import Path

from PIL import Image
import pytest

from app import cuts, render, scenes, scene_builder as b
from app.cuts import casefile_scene as c
from tests.unit.test_scene_builder import mocked, scene

CUES=[dict(kind='photo',caption='The evidence'),dict(kind='card',title='A date',text='A fact that needs several lines of typed text to explain.'),
      dict(kind='clipping',headline='A headline that wraps across lines',text='A paraphrase of the story.'),
      dict(kind='note',text='Who called at two am?'),dict(kind='redacted',title='The report',text='The hidden line is revealed.')]


@pytest.mark.parametrize('look,ground',[('','#4a2e1a'),('wall','#16161a'),('felt','#163a28')])
def test_casefile_dispatch_clocks_and_kinds(project,tmp_path,monkeypatch,look,ground):
    project.style.format,project.style.cut_look='casefile',look
    slide=project.slides[0];slide.take={'duration':15}
    slide.cues['casefile']=[dict(cue,at=i*3) for i,cue in enumerate(CUES)]
    group=[(slide,15),(project.slides[1],3)];expected=cuts.timed_cues(project,group,19.13,.6)
    before=render.timeline(project);calls=[]
    def builder(owner,template,ctx,out,**kw):
        calls.append((ctx,kw));html=scenes.render_html(template,dict(ctx,duration=kw['seconds']))
        assert scenes.lint(html)==[] and 'data-capture="frames"' not in html
        assert 'Caveat-Bold.ttf' in html and 'PermanentMarker-Regular.ttf' in html
        assert ctx['palette']['ground']==ground
        return b.Result(out,dict(captured_frames=0))
    monkeypatch.setattr(b,'render',builder)
    monkeypatch.setattr(cuts,'load_picture',lambda *a:pytest.fail('Pillow decode'))
    monkeypatch.setattr(cuts.casefile,'frame',lambda *a:pytest.fail('Pillow draw'))
    out=tmp_path/'out.mp4'
    cuts.render_segment(project,group,19.13,out,size=(480,270),lead_in=.6,chapter=('Next case',''),hold=1,frames=(4,20))
    data,kw=calls[0];screens=data['screens']
    assert kw['frames']==(4,20) and kw['seconds']==cuts.frame_count(19.13,30)/30
    assert screens[0]['start']==0 and screens[-1]['start']+screens[-1]['duration']==18.13
    assert data['card_at']==18.13 and screens[0]['delay']==0  # Explicit at is file time.
    for _,cues,times in expected:
        for cue,(a,z) in zip(cues,times):
            if z<=a or a>=18.13:continue
            screen=next(s for s in screens if s['start']==a)
            assert screen['cue']==cue and screen['duration']==pytest.approx(min(z,18.13)-a)
            assert len(screen['camera'])<=48
    assert json.loads(out.with_suffix('.mp4.stats.json').read_text())['captured_frames']==0
    project.style.cut_engine='pillow'
    assert cuts.timed_cues(project,group,19.13,.6)==expected and render.timeline(project)==before


def test_casefile_history_resets_dedup_and_overview(project,tmp_path,monkeypatch):
    project.style.format='casefile';a,z=project.slides[:2]
    a.cues['casefile']=[CUES[0]];z.chapter='';z.cues['casefile']=[dict(CUES[0],at=1)]
    source=tmp_path/'clip.mp4';source.touch()
    monkeypatch.setattr(cuts,'load_picture',lambda *a:pytest.fail('history Pillow decode'))
    def context():
        ctx=cuts.make_ctx(project,(480,270),30,image_for=lambda s:source)
        beat=cuts.beat_for(cuts.casefile,ctx,z,6,0,6,scene=True);beat.last=True
        return ctx,beat,c.context(project,ctx,[beat],[source])
    ctx,beat,data=context();s=data['screens'][0]
    assert [i['kind'] for i in s['items']]==['photo','card']
    assert s['items'][0]['source']==str(source) and s['items'][0]['angle']==0
    assert s['items'][1]['text']=='The evidence' and s['delay']==1
    assert s['camera'][-1]['zoom']==pytest.approx(1920/4608)
    assert s['camera'][0]['zoom']==cuts.casefile._focus(s['items'][0])[2]
    middle=next(k for k in s['camera'] if k['t']==pytest.approx(1.45))
    left,right=[cuts.casefile._focus(i) for i in s['items']]
    assert middle['zoom']==pytest.approx((left[2]+right[2])/2)
    assert middle['x']==pytest.approx((left[0]+right[0])/2)
    hidden=c.context(project,ctx,[beat],[source],hide={'cues'})
    html=scenes.render_html(c.TEMPLATE,hidden)
    assert 'data-video="true"' in html and 'class="board"' not in html
    z.chapter='New case';_,_,fresh=context();assert len(fresh['screens'][0]['items'])==1
    z.chapter='';a.cues['casefile']=[CUES[1]]*14
    _,_,full=context();assert len(full['screens'][0]['items'])==1


def test_casefile_still_generic_bypass_and_pillow(project,tmp_path,monkeypatch):
    project.style.format='casefile';calls=[]
    monkeypatch.setattr(scenes,'handles',lambda fmt:True)
    monkeypatch.setattr(scenes,'render_segment',lambda *a,**k:pytest.fail('generic branch'))
    monkeypatch.setattr(b,'render',lambda *a,**kw:calls.append(kw) or b.Result(a[3]))
    monkeypatch.setattr(cuts.ffutil,'run',lambda args:Path(args[-1]).touch())
    out=tmp_path/'still.png';cuts.still(project,project.slides[0],out,at=.6)
    assert out.exists() and calls[0]['frames'][1]==calls[0]['frames'][0]+1
    render._render_segment(project,[(project.slides[0],3)],4,0,tmp_path/'out.mp4');assert len(calls)==2
    project.style.cut_engine='pillow';assert not cuts.uses_scene(project.style)
    drawn=[]
    monkeypatch.setattr(cuts.casefile,'frame',lambda *a:drawn.append(a[2]) or Image.new('RGB',(48,27)))
    def encode(stream,out,**kw):next(stream);out.touch();return True
    monkeypatch.setattr(cuts.ffutil,'encode_frames',encode)
    cuts.render_segment(project,[(project.slides[0],2)],2,tmp_path/'pillow.mp4',size=(48,27),frames=(3,4))
    assert drawn==[.1]


def test_casefile_mocked_plates_chunk_and_shared_drop(project,mocked,tmp_path):
    data,captures=mocked;data.update(scene(2,4));data['layers'][0]['motion']='pin-drop'
    data['layers'][1].update(motion='reveal',steps=[(1.2,10),(1.4,20)])
    project.style.format='casefile';out=tmp_path/'preview.mp4'
    for n in range(2):
        cuts.render_segment(project,[(project.slides[0],4)],4,out,size=(480,270),frames=(59,62))
        stats=json.loads(out.with_suffix('.mp4.stats.json').read_text())
        assert stats['captured_frames']==0 and stats['largest_graph_bytes']<65536
        assert stats['screenshots']==(3 if n==0 else 0)
    assert len(captures)==3
    motion=b._motion(dict(motion='pin-drop',start=.495,arrival=.3))
    for value in [0,.15,.3]:
        # The shared compiler expresses the exact cubic-out drop, including opacity.
        env=dict(clip=lambda x,a,z:max(a,min(z,x)),pow=pow,t=.495+value)
        assert eval(motion['opacity'],{'__builtins__':{}},env)==pytest.approx(1-(1-value/.3)**3)
        assert eval(motion['scale'],{'__builtins__':{}},env)==pytest.approx(1+.14*(1-value/.3)**3)

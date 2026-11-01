"""Casefile clocks, persistent boards and native plates, with mocked Chromium."""
import json
from pathlib import Path
import random

from PIL import Image, ImageFilter, ImageOps
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
    assert hidden['builder_top_plate'] is None
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


@pytest.mark.parametrize('look', ['', 'wall', 'felt'])
def test_casefile_seeded_ground_and_lamp_match_pillow(project, monkeypatch, look):
    """Replay the seeded noise through the real Pillow ground/world recipe."""
    project.style.cut_look = look
    ctx = cuts.make_ctx(project, (96,54), 30)
    url, lamp = c._assets(project, ctx)
    path = scenes._directory(project) / url.rsplit('/',1)[-1]
    rng = random.Random(f'casefile-ground-v1-{look or "cork"}')
    monkeypatch.setattr(c.Image, 'effect_noise', lambda size,sigma: c._noise(size,sigma,rng))
    expected = cuts.casefile._ground(ctx).convert('RGB').filter(
        ImageFilter.GaussianBlur(2.9*ctx.k*cuts.casefile.WORLD_SCALE))
    with Image.open(path) as ground, Image.open(lamp) as light:
        assert ground.mode == 'RGB' and ground.size == expected.size
        assert ground.tobytes() == expected.tobytes()
        assert light.tobytes() == cuts.casefile._light(ctx).tobytes()
        assert light.getpixel((0,0))[3] > light.getpixel((40,20))[3]
    before = path.read_bytes(), Path(lamp).read_bytes()
    # The assets are deterministic after a cold rebuild, and warm calls do no work.
    path.unlink(); Path(lamp).unlink()
    assert c._assets(project, ctx) == (url,lamp)
    assert before == (path.read_bytes(), Path(lamp).read_bytes())
    monkeypatch.setattr(c, '_noise', lambda *a: pytest.fail('warm ground regenerated'))
    monkeypatch.setattr(c.c, '_light', lambda *a: pytest.fail('warm lamp regenerated'))
    assert c._assets(project, ctx) == (url,lamp)


@pytest.mark.parametrize('caption', ['The evidence', 'A print', 'Archive', 'Blue room'])
def test_casefile_photo_tint_matches_caption_seed(caption, tmp_path):
    source = tmp_path/'photo.png'
    Image.new('RGB', (540,520), (40,120,200)).save(source)
    cue = dict(kind='photo', caption=caption)
    spec = c._item(cue,source,0,0,set())
    with Image.open(source) as image:
        reference = cuts.casefile._item(cue,image,1).getpixel((300,290))[:3]
        tinted = Image.alpha_composite(image.convert('RGBA'), Image.new('RGBA',image.size,tuple(spec['wash'])))
        if spec['grayscale']:
            tinted = ImageOps.grayscale(tinted).convert('RGB')
        assert tinted.getpixel((300,290))[:3] == reference
    history = c._item(cue,source,0,1,set())
    assert (history['grayscale'],history['wash']) == (spec['grayscale'],spec['wash'])


def test_casefile_card_wrap_rules_and_baselines(project):
    cue = dict(kind='card', title='Timeline', text='A celebrity gossip story with long words and enough detail to wrap into several ruled lines.')
    spec = c._item(cue,None,0,0,set())
    assert len(spec['card_lines']) > 1
    assert spec['card_lines'] == cuts.kit.wrap(cue['text'],'typewriter',36,600)[:5]
    assert all(cuts.kit.measure(line,'typewriter',36)[0] <= 600 for line in spec['card_lines'])
    reference = cuts.casefile._item(cue,None,1)
    assert spec['paper'] == '#'+''.join(f'{v:02x}' for v in reference.getpixel((0,0))[:3])
    assert spec['rule'] == '#'+''.join(f'{v:02x}' for v in reference.getpixel((0,92))[:3])
    ctx = cuts.make_ctx(project,(96,54),30)
    beat = cuts.beat_for(cuts.casefile,ctx,project.slides[0],4,0,4,scene=True)
    data = c.context(project,ctx,[beat],[None])
    data['screens'][0]['items'] = [spec]
    html = scenes.render_html(c.TEMPLATE,data)
    for i,line in enumerate(spec['card_lines']):
        assert f'style="top:{100+i*50}px"><svg width="600" height="50"><text x="0" y="40">{line}</text>' in html
    assert 'getSubStringLength' in html  # Exact browser glyph advances, not average widths.

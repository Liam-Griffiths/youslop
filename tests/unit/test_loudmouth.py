"""Loudmouth migration: mocked Chromium/probes, real timing, bounded graphs."""
import json
from pathlib import Path

from PIL import Image
import pytest

from app import cuts, render, scene_builder as b, scenes
from app.schema import Project
from tests.unit.test_scene_builder import mocked, scene


@pytest.mark.parametrize('look', ['', 'paper', 'loud'])
def test_loudmouth_dispatch_timing_and_template(project, tmp_path, monkeypatch, look):
    project.style.format, project.style.cut_look = 'loudmouth', look
    group = [(s, 3.1) for s in project.slides[:2]]
    expected = cuts.timed_cues(project, group, 7.13, .6)
    calls = []
    def builder(owner, template, ctx, out, **kw):
        calls.append((ctx, kw))
        html = scenes.render_html(template, dict(ctx, duration=kw['seconds'], fps=30))
        assert scenes.lint(html) == []
        assert 'ArchivoBlack-Regular.ttf' in html and 'dataset.screen' in html
        assert ctx['palette'] == {**ctx['palette'], **cuts.loudmouth._palette(cuts.make_ctx(project,(480,270),30))}
        return b.Result(out, dict(captured_frames=0))
    monkeypatch.setattr(b, 'render', builder)
    monkeypatch.setattr(cuts, 'load_picture', lambda *a: pytest.fail('Pillow picture load'))
    monkeypatch.setattr(cuts.loudmouth, 'frame', lambda *a: pytest.fail('Pillow frame'))
    out = tmp_path/'out.webm'
    cuts.render_segment(project, group, 7.13, out, size=(480,270), lead_in=.6,
                        chapter=('Next', ''), hold=1, frames=(4,20))
    ctx, kw = calls[0]
    for beat, (_, cues, times) in zip(ctx['beats'], expected):
        assert [(c['start']+beat['start'],c['end']+beat['start']) for c in beat['cues']] == times
        assert [c['text'] for c in beat['cues']] == [c['text'] for c in cues]
    assert kw['seconds'] == cuts.frame_count(7.13,30)/30
    assert kw['frames'] == (4,20) and ctx['card_at'] == 6.13
    assert json.loads(out.with_suffix('.webm.stats.json').read_text())['captured_frames'] == 0
    project.style.cut_engine = 'pillow'
    assert cuts.timed_cues(project, group, 7.13, .6) == expected
    assert Project.from_dict(project.to_dict()).style.cut_engine == 'pillow'


def test_loudmouth_generic_bypass_and_pillow(project, tmp_path, monkeypatch):
    project.style.format = 'loudmouth'
    monkeypatch.setattr(scenes, 'handles', lambda fmt: True)
    monkeypatch.setattr(scenes, 'render_segment', lambda *a, **k: pytest.fail('generic scene branch'))
    monkeypatch.setattr(cuts, 'render_segment', lambda *a, **k: a[3])
    out = tmp_path/'out.mp4'
    assert render._render_segment(project, [(project.slides[0],3)], 4, 0, out) == out
    project.style.cut_engine = 'pillow'
    assert not cuts.uses_scene(project.style)


def world_data():
    data = scene(6, 2)
    data['screens'] = [dict(id=str(i), start=i, duration=1, world=True,
        signature=[f'ground{i}'], media=[], camera=[dict(t=i,x=96,y=56,zoom=1),
        dict(t=i+1,x=192,y=112,zoom=.5,ease='cubic-in-out')]) for i in range(2)]
    for i, layer in enumerate(data['layers']):
        layer.update(screen=str(i//3), duration=1, motion='slam', arrival=.16,
                     steps=[(j*.05, 2*(j+1)) for j in range(10)])
    return data


def test_loudmouth_world_plates_cache_and_frame_range(mocked, tmp_path, monkeypatch):
    data, captures = mocked
    data.update(world_data())
    # This fixture's browser returns fixed pixels, and exports world geometry.
    # Device metrics are the only additional CDP operation for world capture.
    original = b.stage.capture_stills
    def capture(items, directory, **kw):
        probe = kw['scene_probe']
        def world_probe(cdp, *args):
            send = cdp.send
            cdp.send = lambda method, params, session: ({} if method.startswith('Emulation.') else send(method,params,session))
            return probe(cdp, *args)
        return original(items, directory, **dict(kw, scene_probe=world_probe))
    monkeypatch.setattr(b.stage, 'capture_stills', capture)
    graphs, counts = [], []
    def encode(args):
        if '-filter_complex_script' in args:
            graphs.append(Path(args[args.index('-filter_complex_script')+1]).read_text())
            counts.append(int(args[args.index('-frames:v')+1]))
        Path(args[-1]).touch()
    monkeypatch.setattr(b.ffutil, 'run', encode)
    monkeypatch.setattr(b, 'PASS_WORKERS', 1)  # record passes in screen order
    for n in range(2):
        result = b.render(tmp_path, 'cuts/loudmouth.html', dict(width=192,height=112,palette=dict(ground='#101010')),
            tmp_path/'out.mp4', seconds=2,size=(48,28),fps=30,crf=28,frames=(29,33))
        assert result.stats['captures'] == (6 if n==0 else 0)  # grounds composed without CDP
        assert result.stats['screenshots'] == (6 if n==0 else 0)
        assert result.stats['captured_frames'] == 0 and result.stats['passes'] == 2
        assert result.stats['largest_graph_bytes'] < 65536
    assert counts == [1,3,1,3]
    assert all(g.count('overlay=') == 3 for g in graphs)  # 30 words, only three row nodes.
    assert all('zoompan' in g and 'if(gte(T,' in g for g in graphs)
    assert len(captures) == 6


def test_loudmouth_world_camera_and_video_clock(tmp_path, monkeypatch):
    data = world_data()
    screen = data['screens'][1]
    left, top, density, w, h = b._world_bounds(screen['camera'],192,112,.25)
    screen.update(raster=dict(left=left,top=top,density=density,width=w,height=h), offset=.2)
    ground = tmp_path/'ground.png'
    Image.new('RGBA',(w,h)).save(ground)
    screen.update(ground_path=str(ground),media=[dict(path='source.mp4',video=True,time=1.5,box=[0,0,32,32])])
    data.update(layers=[],width=192,height=112,ground_color='#121212')
    inputs, graph = b._compile(data, screen, (48,28),30,tmp_path)
    assert inputs[inputs.index('-ss')+1] == '1.7'
    assert '-stream_loop' in inputs and 'rr=.53:gg=.53:bb=.53' in graph
    photo = tmp_path/'photo.png'
    Image.new('RGB',(32,32),'red').save(photo)
    screen['media'] = [dict(path=str(photo),video=False,box=[0,0,32,32])]
    decoded=[]
    def decode(args):
        decoded.append(args); Image.new('RGBA',(32,32),'red').save(args[-1])
    monkeypatch.setattr(b.ffutil,'run',decode)
    for _ in range(2):
        b._compile(data,screen,(48,28),30,tmp_path)
    assert len(decoded)==1 and 'rr=.53:gg=.53:bb=.53' in decoded[0][decoded[0].index('-vf')+1]
    assert Image.open(photo).getpixel((0,0))==(255,0,0)
    assert w/h == 192/112 and density == .25
    assert "(on/30+1.2)" in graph
    with pytest.raises(ValueError,match='zoom'):
        b._camera([dict(t=0,zoom=.5)], 't')


def test_loudmouth_still_uses_builder(project, tmp_path, monkeypatch):
    project.style.format = 'loudmouth'
    calls = []
    def builder(*args, **kw):
        calls.append(kw)
        return b.Result(args[3])
    monkeypatch.setattr(b,'render',builder)
    monkeypatch.setattr(cuts.ffutil,'run',lambda args: Path(args[-1]).touch())
    cuts.still(project,project.slides[0],tmp_path/'still.png',at=.6)
    a,z = calls[0]['frames']
    assert a>0 and z==a+1


def test_loudmouth_scheduler_one_job_per_picture(project, tmp_path, monkeypatch):
    from tests.unit.test_resume import InlinePool
    project.style.format = 'loudmouth'
    jobs, pools = [], []
    class Pool(InlinePool):
        def __init__(self, **kw):
            pools.append(kw)
    def draw(job):
        jobs.append(job)
        job[4].write_bytes(b'fake segment')
        return job[8],job[9],job[4],False
    monkeypatch.setattr(render.cf,'ProcessPoolExecutor',Pool)
    monkeypatch.setattr(render,'_draw_segment',draw)
    monkeypatch.setattr(render.os,'cpu_count',lambda:16)
    monkeypatch.setattr(render.ffutil,'gpu_status',lambda:dict(active=False))
    groups = [[(project.slides[0],60)]]*4
    render._draw_segments(project,groups,[60]*4,0,tmp_path,None,None,lambda msg:None)
    assert len(jobs)==4 and all(j[10]==(0,1800) for j in jobs)
    assert pools[0]['max_workers']==3


def test_loudmouth_pillow_fallback_draws(project, tmp_path, monkeypatch):
    project.style.format,project.style.cut_engine = 'loudmouth','pillow'
    called=[]
    monkeypatch.setattr(cuts.loudmouth,'frame',lambda *a: called.append(a) or Image.new('RGB',(48,27)))
    def encode(stream,out,**kw):
        next(stream); out.touch(); return True
    monkeypatch.setattr(cuts.ffutil,'encode_frames',encode)
    cuts.render_segment(project,[(project.slides[0],2)],2,tmp_path/'out.mp4',size=(48,27),frames=(3,4))
    assert len(called)==1 and called[0][2]==.1

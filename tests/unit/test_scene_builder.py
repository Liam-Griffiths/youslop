"""Builder contract: one loaded page, bounded graphs, no real browser or LLM."""
import base64
import copy
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
import pytest

from app import scene_builder as b

REAL_RUN = b.ffutil.run


def scene(count=3, seconds=5):
    return dict(screens=[], camera=[], budget=.1, ground=['ground'], layers=[dict(
        id=f'l{i}', index=i, screen='', start=0, duration=seconds, arrival=.6,
        motion='rise', box=[0, 0, 20, 20], signature=[f'text{i}']) for i in range(count)])


@pytest.fixture
def mocked(tmp_path, monkeypatch):
    data = scene()
    image = io.BytesIO()
    Image.new('RGBA', (48, 28), (255, 0, 0, 128)).save(image, format='PNG')
    calls = []
    class CDP:
        def send(self, method, args, session):
            assert method == 'Page.captureScreenshot'
            calls.append(method)
            return dict(data=base64.b64encode(image.getvalue()).decode())
    def evaluate(cdp, session, js):
        return dict(result=dict(value=copy.deepcopy(data) if js == b._PROBE else None))
    def capture(items, directory, **kwargs):
        assert len(items) == 1 and items[0]['measure_only']
        kwargs['scene_probe'](CDP(), 'session', items[0], 0)
    def prepare(*args):
        path = tmp_path / 'page.html'
        path.write_text('mock')
        return 'key', path, args[2]
    def run(args):
        if '-filter_complex_script' in args:
            script = Path(args[args.index('-filter_complex_script')+1]).read_text()
            assert len(script.encode()) < 65536 and '-filter_complex' not in args
        Path(args[-1]).touch()
    monkeypatch.setattr(b.scenes, '_prepare', prepare)
    monkeypatch.setattr(b.stage, '_evaluate', evaluate)
    monkeypatch.setattr(b.stage, 'capture_stills', capture)
    monkeypatch.setattr(b.ffutil, 'run', run)
    return data, calls


def test_capture_cache_and_preview(mocked, tmp_path):
    data, calls = mocked
    for n in range(2):
        result = b.render(tmp_path, 'test.html', dict(width=192, height=112), tmp_path/'out.mp4',
                          seconds=5, size=(192,112), fps=30, crf=18, extra=['-vf','scale=48:28'])
        assert result.stats['captures'] == (4 if n == 0 else 0)
        assert result.stats['screenshots'] == (4 if n == 0 else 0)
        assert result.stats['cache_hits'] == (0 if n == 0 else 4)
        assert result.stats['layers'] == 3 and result.stats['passes'] == 1
    assert len(calls) == 4


@pytest.mark.parametrize('grayscale', [False, True])
def test_media_wash_and_grayscale_pixels(tmp_path, grayscale):
    photo = tmp_path/'photo.png'
    original = Image.new('RGB',(48,28))
    colors = [(0,0,0),(20,100,210),(255,0,0),(255,255,255)]
    for i,color in enumerate(colors):
        ImageDraw.Draw(original).rectangle((i*12,0,i*12+11,27),fill=color)
    original.save(photo)
    settings = dict(dim=1, wash=[255,220,170,34], grayscale=grayscale)
    expected = Image.alpha_composite(original.convert('RGBA'), Image.new('RGBA',original.size,tuple(settings['wash'])))
    if grayscale:
        expected = ImageOps.grayscale(expected).convert('RGB')
    out = tmp_path/'tinted.png'
    REAL_RUN(['-i',str(photo),'-vf',b._media_filter(settings,48,28),'-frames:v','1',str(out)])
    with Image.open(out) as image:
        for x in [6,18,30,42]:
            assert all(abs(a-z)<=1 for a,z in zip(image.getpixel((x,14))[:3],expected.getpixel((x,14))[:3]))
    # The native still's whole filter runs before looping, retaining the speed fix.
    data = scene(1,2)
    data.update(width=48,height=28,ground_path=str(photo))
    data['layers'][0].update(settings,path=str(photo),native=str(photo),motion='none',box=[0,0,48,28])
    _,graph = b._compile(data,dict(id='',start=0,duration=2),(48,28),10,tmp_path)
    effect = graph.split('[1:v]')[1].split('[l1]')[0]
    assert effect.index('lutrgb') < effect.index('loop=') and 'geq=' not in effect


def test_top_plate_stays_in_viewport_after_camera_and_chunk(tmp_path):
    ground = tmp_path/'ground.png'
    image = Image.new('RGB',(96,56),'black')
    ImageDraw.Draw(image).rectangle((0,0,47,55), fill='white')
    image.save(ground)
    top = tmp_path/'lamp.png'
    image = Image.new('RGBA',(48,28))
    ImageDraw.Draw(image).rectangle((0,0,7,7), fill='white')
    image.save(top)
    data = scene(0,1)
    data.update(width=48,height=28,ground_color='#000000',top_plate=str(top))
    screen = dict(id='',start=0,duration=.1,ground_path=str(ground),
        raster=dict(left=0,top=0,density=1,width=96,height=56),
        camera=[dict(t=0,x=24,y=14,zoom=1),dict(t=1,x=72,y=42,zoom=1)])
    centers = []
    for offset in [0,.9]:
        inputs,graph = b._compile(data,dict(screen,offset=offset),(48,28),10,tmp_path)
        assert inputs[-2:] == ['-i',str(top)]
        assert graph.index('zoompan=') < graph.index('[camera][top]overlay')
        assert 'geq=' not in graph
        script = tmp_path/'graph.ffgraph'; script.write_text(graph)
        out = tmp_path/'pixel.png'
        args = [*inputs,'-filter_complex_threads','1','-filter_complex_script',str(script),'-map','[out]','-frames:v','1',str(out)]
        try:
            REAL_RUN(args)
        except b.ffutil.FFError as exc:
            if "Unrecognized option 'filter_complex_script'" not in str(exc):
                raise
            args[args.index('-filter_complex_script')] = '-/filter_complex'
            REAL_RUN(args)
        with Image.open(out) as frame:
            assert min(frame.getpixel((3,3))[:3]) >= 250
            centers.append(frame.getpixel((24,14))[0])
    assert centers[0] > 250 and centers[1] < 5


def test_2000_layers_are_bounded(mocked, tmp_path):
    data, _ = mocked
    data.update(scene(2000, 1200))
    data['screens'] = [dict(id=str(i), start=i*24, duration=24) for i in range(50)]
    for i, layer in enumerate(data['layers']):
        layer.update(screen=str(i//40), duration=24)
    result = b.render(tmp_path, 'test.html', dict(width=192,height=112), tmp_path/'out.mp4',
                      seconds=1200, size=(48,28), fps=30, crf=18)
    assert result.stats['passes'] == 50
    assert result.stats['captures'] == 2001
    assert result.stats['largest_graph_bytes'] < 65536


@pytest.mark.parametrize('motion', b.MOTIONS)
def test_motion_table(motion):
    layer = scene(1)['layers'][0]
    layer['motion'] = motion
    expr = b._motion(layer)
    assert set(expr) == {'opacity', 'x', 'y', 'scale', 'wipe'}
    if motion == 'fly-left':
        assert '-240' in expr['x']
    if motion in ('scale-in', 'blur-in'):
        assert '0.85' in expr['scale']
    if motion == 'words':
        assert 'clip(' in expr['wipe']


@pytest.mark.parametrize('name', ['linear','quad-out','cubic-out','expo-out','back-out'])
def test_eases(name):
    assert b.ease(name, 'p')
    with pytest.raises(ValueError, match='unsupported ease'):
        b.ease('unknown', 'p')


def test_window_budget_before_capture(mocked, tmp_path):
    data, calls = mocked
    data['layers'][0].update(capture='frames', arrival=1)
    with pytest.raises(ValueError, match='l0.*budget'):
        b.render(tmp_path, 'test.html', dict(width=192,height=112), tmp_path/'out.mp4',
                 seconds=5, size=(48,28), fps=30, crf=18)
    assert not calls


@pytest.mark.parametrize('alpha', [False, True])
def test_encode_one_tiny_mocked_segment(mocked, tmp_path, monkeypatch, alpha):
    data, _ = mocked
    data.update(scene(len(b.MOTIONS), 1))
    for layer, motion in zip(data['layers'], b.MOTIONS):
        layer['motion'] = motion
    data['layers'][0].update(capture='frames', arrival=.1)
    data['camera'] = [] if alpha else [dict(t=0,zoom=1), dict(t=1,zoom=1.2,x=10,y=5)]
    monkeypatch.setattr(b.ffutil, 'run', REAL_RUN)
    result = b.render(tmp_path, 'test.html', dict(width=192,height=112, builder_alpha=alpha), tmp_path/('tiny.mov' if alpha else 'tiny.mp4'),
                      seconds=1, size=(48,28), fps=30, crf=28)
    assert result.path.stat().st_size > 0
    assert result.stats['captured_frames'] == 3
    assert b.ffutil.dimensions(result.path) == (48,28)
    if alpha:
        frame = tmp_path / 'frame.png'
        REAL_RUN(['-i', str(result.path), '-frames:v', '1', str(frame)])
        with Image.open(frame) as image:
            assert image.mode == 'RGBA' and image.getpixel((47, 27))[3] == 128



def test_limit_and_flatten_settled_layers(mocked, tmp_path):
    data, _ = mocked
    data.update(scene(49, 5))
    stats = dict(captures=0, cache_hits=0, captured_frames=0)
    plates = b._plates(tmp_path, 'test.html', dict(width=192,height=112), 5, (48,28), 30, stats)
    plates.update(width=192, height=112)
    with pytest.raises(ValueError, match='more than 48'):
        b._compile(plates, dict(id='',start=0,duration=5), (48,28), 30, tmp_path)
    _, graph = b._compile(plates, dict(id='later',start=1,duration=4), (48,28), 30, tmp_path)
    assert 'overlay=' not in graph
    # Timing changes reuse the same content plates, even after manifest invalidation.
    (tmp_path/'page.layers.json').unlink()
    for layer in data['layers']:
        layer['start'] = .1
    stats = dict(captures=0, cache_hits=0, captured_frames=0)
    b._plates(tmp_path, 'test.html', dict(width=192,height=112), 5, (48,28), 30, stats)
    assert stats['captures'] == 0 and stats['cache_hits'] == 50


def test_soft_wipe_and_caption_exit_compile_on_crop(mocked, tmp_path):
    data, _ = mocked
    data.update(scene(1))
    data['layers'][0].update(motion='wipe', start=.5, duration=4, arrival=.4,
                             feather=20, exit=.2, ease='quad-out')
    stats = dict(captures=0, cache_hits=0, captured_frames=0)
    plates = b._plates(tmp_path, 'test.html', dict(width=192,height=112), 5, (48,28), 30, stats)
    plates.update(width=192, height=112, alpha=True)
    _, graph = b._compile(plates, dict(id='', start=0, duration=5), (48,28), 30, tmp_path)
    assert '((5+10.0)*' in graph and '/10.0,0,1)' in graph  # five-pixel crop, scaled nib
    assert '/0.3,0,1)' in graph and '/0.4,0,1)' in graph
    assert "enable='between(t,0.5,0.9)'" in graph
    assert 'fade=t=out:st=4.3:d=0.2:alpha=1' in graph
    assert 'format=auto' in graph and 'zoompan' not in graph


def test_batch_gutters_and_viewport_limits(monkeypatch):
    def plate(box):
        return dict(box=box)
    rows = [plate([0,0,10,10]), plate([13,0,20,10]), plate([24,0,30,10]),
            plate([100,0,110,10])]
    groups = b._batches(rows, limit=40)
    # First two overlap once padded; distant rows exceed the viewport union.
    assert [len(group) for group, _ in groups] == [2,1,1]
    assert groups[0][1] == [-2,-2,32,12]
    monkeypatch.setattr(b, 'MAX_CAPTURE_PIXELS', 200)
    assert len(b._batches([rows[0],rows[2]])) == 2
    with pytest.raises(ValueError, match='viewport limits'):
        b._batches([plate([0,0,9000,10])])


def test_viewport_limit_before_capture(mocked, tmp_path):
    data, calls = mocked
    data['layers'][0]['box'] = [0,0,36000,10]
    with pytest.raises(ValueError, match='viewport limits'):
        b.inspect(tmp_path, 'mock.html', dict(width=192,height=112),
                  seconds=5, size=(48,28), fps=30)
    assert not calls


@pytest.fixture
def pixel_browser(tmp_path, monkeypatch):
    """Paint only selected mock DOM nodes, respecting viewport and translation."""
    import re
    data = scene(4)
    for layer, box in zip(data['layers'], [[2.25,3.75,22.25,15.75],
            [34.5,3,51.5,17], [55.25,30.5,73.25,44.5], [4,4,14,14]]):
        layer['box'] = box
    state = dict(active=set(), offset=(0,0), density=1, viewport=(96,64), shots=[])

    class CDP:
        def send(self, method, args, session):
            if method == 'Emulation.setDeviceMetricsOverride':
                state['density'] = args['deviceScaleFactor']
                state['viewport'] = (round(args['width']*state['density']),
                                     round(args['height']*state['density']))
                return {}
            assert method == 'Page.captureScreenshot'
            state['shots'].append(args)
            image = Image.new('RGBA', state['viewport'])
            if not state['active']:
                image.paste((7,11,13,255), (0,0,*image.size))
            for attr, i in sorted(state['active']):
                row = data['layers' if attr == 'data-layer' else 'grounds'][i]
                density = state['density']
                x0,y0,x1,y1 = [f(v*density) for f,v in zip(
                    [b.math.floor,b.math.floor,b.math.ceil,b.math.ceil],row['box'])]
                color = sum(map(ord, str(row['signature'])))
                plate = Image.new('RGBA', (x1-x0,y1-y0))
                plate.putdata([((color+x)%256,(color+y)%256,(x*7+y*3)%256,100+(x+y)%156)
                               for y in range(plate.height) for x in range(plate.width)])
                image.alpha_composite(plate, (x0+round(state['offset'][0]*density),
                                               y0+round(state['offset'][1]*density)))
            buf = io.BytesIO()
            image.save(buf, 'PNG')
            return dict(data=base64.b64encode(buf.getvalue()).decode())

    def evaluate(cdp, session, js):
        if js == b._PROBE:
            return dict(result=dict(value=copy.deepcopy(data)))
        if "transform='none'" in js:
            state['offset'] = (0,0)
        translate = re.search(r"translate\(([-.\de]+)px,([-.\de]+)px\)", js)
        if translate:
            state['offset'] = tuple(map(float,translate.groups()))
        state['active'].update((a,int(i)) for a,i in re.findall(
            r"querySelectorAll\('\[(data-layer|data-ground)\]'\)\[(\d+)\]\.setAttribute", js))
        if 'removeAttribute' in js:
            state['active'].clear()
        return dict(result=dict(value=None))

    def capture(items, directory, **kwargs):
        state.update(active=set(), offset=(0,0), density=items[0]['size'][0]/items[0]['W'],
                     viewport=items[0]['size'])
        kwargs['scene_probe'](CDP(), 'mock', items[0], 0)

    def prepare(project, template, ctx, *args):
        directory = Path(project)
        directory.mkdir(exist_ok=True)
        path = directory/'page.html'
        path.write_text('mock')
        return 'key', path, ctx

    monkeypatch.setattr(b.scenes, '_prepare', prepare)
    monkeypatch.setattr(b.stage, '_evaluate', evaluate)
    monkeypatch.setattr(b.stage, 'capture_stills', capture)
    return data, state


@pytest.mark.parametrize('world', [False, True])
def test_batched_plates_match_single_capture_bytes(pixel_browser, tmp_path, monkeypatch, world):
    data, state = pixel_browser
    if world:
        data['layers'] = data['layers'][:2]
        data['layers'][0]['box'] = [-22.25,-13.75,-2.25,-1.75]
        data['screens'] = [dict(id=str(i), start=i*2.5, duration=2.5, world=True,
            camera=[dict(t=i*2.5, x=20,y=10,zoom=.5+i*.5)], media=[]) for i in range(2)]
        for i, layer in enumerate(data['layers']):
            layer.update(screen=str(i), duration=2.5)
        # Same settled row in another screen; also capture a ground-only row.
        data['grounds'] = [dict(data['layers'][0], index=0, screen='1'),
                           dict(data['layers'][0], index=1, signature=['ground-only'],
                                box=[60,35,80,45], screen='1')]
    ctx = dict(width=96, height=64, palette=dict(ground='#123456'))
    def plates(directory):
        stats = dict(captures=0, cache_hits=0, captured_frames=0)
        result = b._plates(directory, 'mock.html', ctx, 5, (48,32), 30, stats)
        return result, stats
    batched, stats = plates(tmp_path/'batch')
    assert stats['captures'] == (3 if world else 5)
    assert stats['screenshots'] == (1 if world else 3)
    assert all(args == dict(format='png',fromSurface=True) for args in state['shots'])
    group = b._batches
    monkeypatch.setattr(b, '_batches', lambda rows, limit: [g for row in rows for g in group([row],limit)])
    single, single_stats = plates(tmp_path/'single')
    assert single_stats['screenshots'] == single_stats['captures']
    for rows in ('layers', 'grounds'):
        for batch_row, single_row in zip(batched.get(rows, []), single.get(rows, [])):
            assert batch_row['box'] == single_row['box']
            assert Path(batch_row['path']).read_bytes() == Path(single_row['path']).read_bytes()
    if world:
        assert {s['raster']['density'] for s in batched['screens']} == {.5}
        assert batched['grounds'][0]['path'] == batched['layers'][0]['path']
        assert batched['grounds'][0]['path'] != batched['grounds'][1]['path']
        for screen, reference in zip(batched['screens'], single['screens']):
            assert Path(screen['ground_path']).read_bytes() == Path(reference['ground_path']).read_bytes()
            r = screen['raster']
            expected = Image.new('RGBA', (r['width'],r['height']))
            for row in batched['grounds']:
                if row['screen'] == screen['id']:
                    with Image.open(row['path']) as plate:
                        expected.alpha_composite(plate, (row['box'][0]-round(r['left']*r['density']),
                                                        row['box'][1]-round(r['top']*r['density'])))
            with Image.open(screen['ground_path']) as ground:
                assert ground.tobytes() == expected.tobytes()
    else:
        assert Path(batched['ground_path']).read_bytes() == Path(single['ground_path']).read_bytes()
    _, warm_stats = plates(tmp_path/'batch')
    assert warm_stats['screenshots'] == warm_stats['captures'] == 0
    # Reprobe after timing-only changes also reuses the cropped plates.
    (tmp_path/'batch/page.layers.json').unlink()
    data['layers'][0]['start'] = .1
    _, timing_stats = plates(tmp_path/'batch')
    assert timing_stats['screenshots'] == timing_stats['captures'] == 0


def test_plate_key_ignores_root_position_only():
    from app.scene_builder import _unplaced
    a = _unplaced(['<p class="x" style="left:12.5px; top:-3px;width:40px"><b style="left:4px">a</b></p>', [1]])
    b = _unplaced(['<p class="x" style="left:900px;top:20.25px; width:40px"><b style="left:4px">a</b></p>', [1]])
    c = _unplaced(['<p class="x" style="left:12.5px;top:-3px;width:40px"><b style="left:5px">a</b></p>', [1]])
    assert a == b and a != c
    assert _unplaced({'kind': 'ground'}) == {'kind': 'ground'}


@pytest.mark.parametrize('motion', ['wipe', 'reveal'])
def test_native_media_keeps_shared_wipe_mask(tmp_path, motion):
    photo = tmp_path/'photo.png'
    Image.new('RGB',(48,28),'white').save(photo)
    data = scene(1,3)
    data.update(width=48,height=28,ground_path=str(photo))
    data['layers'][0].update(path=str(photo),native=str(photo),motion=motion,
                             start=.75,arrival=.75,box=[0,0,48,28])
    _, graph = b._compile(data,dict(id='',start=0,duration=3),(48,28),10,tmp_path)
    effect = graph.split('[1:v]')[1].split('[l1]')[0]
    assert effect.index('crop=') < effect.index('loop=') < effect.index('geq=')
    assert "a='alpha(X,Y)*" in effect and 'X' in effect
    assert "enable='between(t,0.75,1.5)'" in effect
    assert ('lte(X/W' in effect) == (motion == 'reveal')
    assert ('-X)' in effect) == (motion == 'wipe')

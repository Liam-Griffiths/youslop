"""Builder contract: one loaded page, bounded graphs, no real browser or LLM."""
import base64
import copy
import io
import json
from pathlib import Path

from PIL import Image
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
    Image.new('RGBA', (48, 28), (255, 0, 0, 255)).save(image, format='PNG')
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
        assert result.stats['cache_hits'] == (0 if n == 0 else 4)
        assert result.stats['layers'] == 3 and result.stats['passes'] == 1
    assert len(calls) == 4


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


def test_encode_one_tiny_mocked_segment(mocked, tmp_path, monkeypatch):
    data, _ = mocked
    data.update(scene(len(b.MOTIONS), 1))
    for layer, motion in zip(data['layers'], b.MOTIONS):
        layer['motion'] = motion
    data['layers'][0].update(capture='frames', arrival=.1)
    data['camera'] = [dict(t=0,zoom=1), dict(t=1,zoom=1.2,x=10,y=5)]
    monkeypatch.setattr(b.ffutil, 'run', REAL_RUN)
    result = b.render(tmp_path, 'test.html', dict(width=192,height=112), tmp_path/'tiny.mp4',
                      seconds=1, size=(48,28), fps=30, crf=28)
    assert result.path.stat().st_size > 0
    assert result.stats['captured_frames'] == 3
    assert b.ffutil.dimensions(result.path) == (48,28)


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

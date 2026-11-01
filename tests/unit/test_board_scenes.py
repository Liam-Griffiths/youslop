"""Board scene contracts without Chromium, encoders, network or an LLM."""
from dataclasses import asdict
import io

from PIL import Image
import pytest

from app import board, board_scenes, scenes, stage
from app.schema import Project, Slide

KEYS = [t['key'] for t in board.TEMPLATES if t['key'] != 'diagram']


def small_ground(project, channel=None):
    return Image.new('RGB', (32, 18), '#3A4552')


@pytest.fixture
def slide(project, tmp_path):
    project.id = 'board-' + tmp_path.name
    s = Slide(id='board-test', title='An argument', narration='An argument in beats.',
              board_lead='An <argument>', board_points=['*First point', 'Second | other'],
              board_note='A source')
    project.slides = [s]
    project.style.format = 'board'
    return s


@pytest.mark.parametrize('key', KEYS)
def test_templates_share_layout_timing_assets(project, slide, key):
    slide.board_template = key
    photo = Image.new('RGB', (48, 32), 'red')
    sheet = board.build(slide, key, project.style.accent, 'marker', photo)
    ctx = board_scenes.context(project, slide, key, sheet, small_ground(project),
                               'marker', 6, .5)
    assert ctx['board'] == board.content(slide)
    assert ctx['beats'] == board.reveal_plan(sheet, 6, .5)
    assert ctx['beats'] == board.dg.schedule(sheet.beats, 6, settle=.5)
    assert ctx['marks'][0]['order'] == sheet.marks[0].order
    assert ctx['ground_url'].startswith('/scene/{token}/project/scenes/board-')
    assert ctx['fonts']['BoardHand'].endswith('ShantellSans-SemiBold.ttf')
    html = scenes.render_html(f'board/{key}.html', ctx)
    assert scenes.lint(html) == []
    assert 'An &lt;argument&gt;' in html
    assert 'data-anim-exit="0"' in html
    assert 'data-start="' in html
    if key in ('taped', 'split'):
        assert '/scene/{token}/project/scenes/board-' in html
        assert '<image ' in html
    for order in range(sheet.beats):
        plate = scenes.render_html(f'board/{key}.html',
                                  {**ctx, 'active_order': order, 'plate': True, 'settled': True})
        assert plate.count('data-layer=') == 1
        assert 'data-anim=' not in plate
        assert 'background:transparent!important' in plate


@pytest.mark.parametrize('hand', board.dg.HAND_KEYS)
def test_fonts_and_unknown_schema(project, slide, hand):
    sheet = board.build(slide, 'bullets', '#ffaa00', hand)
    ctx = board_scenes.context(project, slide, 'bullets', sheet, small_ground(project), hand, 5, .5)
    assert ctx['fonts']['BoardHand'].endswith(board.dg.hand_stack(hand)[0][0].split('/')[-1])
    raw = project.to_dict()
    raw['style'].update(board_engine='pillow', future=1)
    assert Project.from_dict(raw).style.board_engine == 'pillow'
    del raw['style']['board_engine']
    assert Project.from_dict(raw).style.board_engine == 'scene'


@pytest.mark.parametrize('key', KEYS)
def test_still_routes_and_pillow_escape(project, slide, tmp_path, monkeypatch, key):
    slide.board_template = key
    monkeypatch.setattr(board, '_ground_for', small_ground)
    calls = []

    def capture(owner, name, ctx, **kw):
        calls.append((name, ctx, kw))
        assert ctx['settled']
        assert kw['t'] < ctx['duration']
        return b'png'

    monkeypatch.setattr(scenes, 'capture', capture)
    out = tmp_path / 'still.png'
    board.still(project, slide, out)
    assert out.read_bytes() == b'png'
    assert calls[0][0] == f'board/{key}.html'
    project.style.board_engine = 'pillow'
    board.still(project, slide, out)
    assert len(calls) == 1
    assert out.read_bytes().startswith(b'\x89PNG')


def test_diagram_and_missing_template_fallback(project, monkeypatch):
    assert board_scenes.handles(project, 'diagram')
    assert not scenes.handles('board')
    monkeypatch.setattr(scenes, 'SCENE_DIR', scenes.SCENE_DIR / 'missing')
    assert not board_scenes.handles(project, 'bullets')


@pytest.mark.parametrize('key', KEYS + ['diagram'])
def test_builder_wrapper(project, slide, tmp_path, monkeypatch, key):
    from types import SimpleNamespace
    from app import scene_builder
    sheet = board.build(slide, key, '#ffaa00', 'marker')
    ctx = board_scenes.context(project, slide, key, sheet, small_ground(project), 'marker', 6, .5)
    calls = []
    out = tmp_path / 'out.mp4'
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw:
                        calls.append((a, kw)) or SimpleNamespace(path=out))
    assert board_scenes.render(project, key, ctx, None, out, crf=28,
                              extra=('-vf', 'scale=480:270')) == out
    assert calls == [((project, f'board/{key}.html', ctx, out),
                      dict(seconds=6, size=(1920, 1080), fps=30, crf=28,
                           extra=('-vf', 'scale=480:270')))]
    html = scenes.render_html(f'board/{key}.html', ctx)
    assert html.count('data-layer=') == sheet.beats
    assert 'data-motion-ease="quad-out"' in html
    assert 'data-motion-feather=' in html


def test_capture_stills_forwards_probe(tmp_path, monkeypatch):
    from types import SimpleNamespace

    calls = []
    probe = object()

    def capture(data, progress, **kwargs):
        calls.append((data, kwargs))
        return SimpleNamespace(thumbs={'beat': b'png'})

    monkeypatch.setattr(stage, '_run_cdp', capture)
    assert stage.capture_stills([{'clip': 'beat'}], tmp_path, scene_probe=probe) == {'beat': b'png'}
    assert calls[0][1]['scene_probe'] is probe
    assert calls[0][0]['items'] == [{'clip': 'beat'}]


def test_segment_mixed_engines_and_length(project, slide, tmp_path, monkeypatch):
    handles = board_scenes.handles
    monkeypatch.setattr(board_scenes, 'handles',
                        lambda p, key: key != 'diagram' and handles(p, key))
    second = Slide.from_dict({**asdict(slide), 'id': 'diagram', 'board_template': 'diagram'})
    project.slides.append(second)
    slide.board_template = 'bullets'
    monkeypatch.setattr(board, '_ground_for', small_ground)
    scene_calls, pillow_calls, joins = [], [], []

    def render(owner, key, ctx, ground, out, **kw):
        scene_calls.append((key, ctx['duration'], kw))
        out.write_bytes(b'clip')

    def encode(frames, out, **kw):
        pillow_calls.append(kw)
        out.write_bytes(b'clip')
        return 1

    monkeypatch.setattr(board_scenes, 'render', render)
    monkeypatch.setattr(board.ffutil, 'encode_frames', encode)
    monkeypatch.setattr(board.ffutil, 'run', lambda args: joins.append(args))
    board.render_segment(project, [(slide, 2), (second, 2)], 5, tmp_path / 'out.mp4',
                         extra=('-vf', 'scale=480:270', '-r', '15'))
    assert scene_calls[0][0:2] == ('bullets', 2)
    assert len(pillow_calls) == 1
    assert 'concat=n=2:v=1:a=0[v]' in joins[0][joins[0].index('-filter_complex') + 1]
    assert joins[0][joins[0].index('-t') + 1] == '5.000'
    project.style.board_engine = 'pillow'
    board.render_segment(project, [(slide, 2)], 2, tmp_path / 'old.mp4')
    assert len(scene_calls) == 1
    assert len(pillow_calls) == 2


@pytest.mark.parametrize('key', KEYS)
def test_segment_scene_dispatch(project, slide, tmp_path, monkeypatch, key):
    slide.board_template = key
    monkeypatch.setattr(board, '_ground_for', small_ground)
    calls = []

    def render(owner, name, ctx, ground, out, **kw):
        calls.append(name)
        assert ctx['duration'] == 3
        out.write_bytes(b'clip')

    monkeypatch.setattr(board_scenes, 'render', render)
    monkeypatch.setattr(board.ffutil, 'encode_frames', lambda *a, **kw: pytest.fail('Pillow encode'))
    monkeypatch.setattr(board.ffutil, 'run', lambda *a: pytest.fail('Unnecessary second encode'))
    out = tmp_path / 'out.mp4'
    assert board.render_segment(project, [(slide, 2)], 3, out) == out
    assert calls == [key]
    assert out.read_bytes() == b'clip'

"""Diagram geometry and scene routing without Chromium or real encoders."""
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
import pytest

from app import board, board_scenes, diagram as dg, diagram_scenes, scenes, stage
from app.schema import Slide


def spec(kind='flow'):
    return dict(kind=kind, title='Request path', nodes=[
        dict(id='a', label='Browser'), dict(id='b', label='Edge', accent=True),
        dict(id='c', label='Server', note='Origin')], note='A source')


@pytest.mark.parametrize('kind', dg.KIND_KEYS)
def test_layout_deterministic_serializable_and_shared(kind):
    raw = spec(kind)
    before = json.dumps(raw)
    layout = dg.layout(raw, seconds=5)
    assert json.dumps(raw) == before
    assert layout == dg.layout(raw, seconds=5)
    json.dumps(layout)
    assert layout['marks'] == [asdict(m) for m in dg.marks_for(raw)]
    assert layout['beats'] == dg.schedule(len(layout['beats']), 5)
    assert layout['paths'] == [dict(points=m['pts'], order=m['order'])
                               for m in layout['marks'] if m['kind'] == 'stroke']
    assert sorted({m['order'] for m in layout['marks']}) == list(range(len(layout['beats'])))


@pytest.mark.parametrize('kind', ['flow', 'stack', 'tree'])
def test_boxes_are_original_layout_coordinates(kind):
    layout = dg.layout(dict(kind=kind, nodes=['A', 'B', 'C']))
    boxes = [n['box'] for n in layout['nodes']]
    if kind == 'flow':
        assert boxes == [(150 + i * (1448 / 3 + 86), 415, 1448 / 3, 250) for i in range(3)]
    elif kind == 'stack':
        assert boxes[0] == (239.1, 120, 1441.8, 808 / 3)
        assert boxes[-1][0:1] == (150.0,)
        assert boxes[-1][2] == 1620
    else:
        assert boxes[0] == (730, 120, 460, 150)
        assert boxes[1] == (150, 760, 788, 200)
    assert len(boxes) == 3


@pytest.mark.parametrize('kind', ['flow', 'tree', 'cycle'])
def test_pillow_unchanged_after_layout_extraction(kind):
    # Pixel hashes captured from the pre-extraction Pillow renderer (grain=0).
    hashes = {
        'flow': '07c2bfe52a357f95bee1ec47bf8fe9dca86c18ea435b5ea115c654595aa4dde7', 'tree': '899730d696f941935cea33275a586798ff9322c639f6255305e8d76ac557cde0', 'cycle': 'eb299098cab52f9ee035842a75c89a98a5f696794e92385b7840b773644d6934',
    }
    assert hashlib.sha256(dg.render_still(spec(kind), grain=0).tobytes()).hexdigest() == hashes[kind]


def test_reveal_all():
    layout = dg.layout({**spec(), 'reveal': 'all'}, seconds=5)
    assert set(layout['beats']) == {(0, .5)}


@pytest.mark.parametrize('kind', ['flow', 'stack', 'tree', 'cycle'])
def test_scene_contract_and_board_dispatch(project, tmp_path, monkeypatch, kind):
    slide = Slide(id='diagram', board_template='diagram', diagram=spec(kind))
    project.slides = [slide]
    sheet = board.build(slide, 'diagram', project.style.accent, 'marker')
    ground = Image.new('RGB', (32, 18))
    ctx = board_scenes.context(project, slide, 'diagram', sheet, ground, 'marker', 5, .5)
    html = scenes.render_html('board/diagram.html', ctx)
    assert scenes.lint(html) == []
    assert 'getTotalLength()' in html and 'strokeDashoffset' in html
    assert 'paused:true' in html and 'baseFrequency=".012"' in html
    assert '<text ' in html and '<path ' in html
    if kind != 'cycle':
        assert html.count('<rect ') == 3
    calls = []
    monkeypatch.setattr(board, '_ground_for', lambda *a: ground)
    monkeypatch.setattr(diagram_scenes, 'render', lambda *a, **kw: calls.append((a, kw)))
    board.render_segment(project, [(slide, 5)], 5, tmp_path / 'clip.mp4')
    assert len(calls) == 1
    assert calls[0][0][1]['beats'] == ctx['beats']
    project.style.board_engine = 'pillow'
    assert not board_scenes.handles(project, 'diagram')


def test_motion_capture_only_arrivals_cache_and_preview_scale(project, tmp_path, monkeypatch):
    ctx, ground = diagram_scenes.context(tmp_path, spec(), '#ffaa00', 'marker', 10, grain=0)
    captures, commands = [], []

    def render(items, directory):
        captures.extend(items)
        for item in items:
            (directory / (item['clip'] + '.mov')).write_bytes(b'motion')

    monkeypatch.setattr(stage, 'render_scene', render)
    monkeypatch.setattr(diagram_scenes.ffutil, 'run', lambda args: commands.append(args))
    for _ in range(2):
        diagram_scenes.render(tmp_path, ctx, ground, tmp_path / 'out.mp4',
                              extra=('-vf', 'scale=480:270', '-r', '15'))
    assert len(captures) == len(ctx['beats'])
    assert all(i['frames'] <= 18 and i['size'] == (480, 270) and i['alpha'] for i in captures)
    assert sum(i['frames'] for i in captures) < 10 * dg.FPS
    assert '-vf' not in commands[0]
    graph = commands[0][commands[0].index('-filter_complex') + 1]
    assert graph.count('tpad=stop_mode=clone') == len(ctx['beats'])
    for start, _ in ctx['beats']:
        assert f'setpts=PTS+{start}/TB' in graph
    assert commands[0][commands[0].index('-t') + 1] == '10'


def test_preview_and_standalone_flag(monkeypatch):
    from app.main import diagram_preview
    calls = []
    data = io.BytesIO()
    Image.new('RGB', (2, 2)).save(data, 'PNG')
    monkeypatch.setattr(diagram_scenes, 'still', lambda *a, **kw: calls.append((a, kw)) or data.getvalue())
    assert diagram_preview({'spec': spec()}).body.startswith(b'\x89PNG')
    assert len(calls) == 1
    assert diagram_preview({'spec': spec(), 'engine': 'pillow'}).body.startswith(b'\x89PNG')
    assert len(calls) == 1


def test_missing_motion_is_error(tmp_path, monkeypatch):
    ctx, ground = diagram_scenes.context(tmp_path, spec(), '#ffaa00', 'marker', 5, grain=0)
    monkeypatch.setattr(stage, 'render_scene', lambda *a: {})
    with pytest.raises(stage.StageError, match='Diagram motion did not render'):
        diagram_scenes.render(tmp_path, ctx, ground, tmp_path / 'out.mp4')


@pytest.mark.parametrize('motion', ['still', 'reveal'])
def test_candidate_scene_flag(tmp_path, monkeypatch, motion):
    captured, encoded = [], []
    data = io.BytesIO()
    Image.new('RGB', (2, 2)).save(data, 'PNG')
    monkeypatch.setattr(diagram_scenes, 'still',
                        lambda *a, **kw: captured.append(kw) or data.getvalue())

    def render(root, ctx, ground, out, **kw):
        encoded.append(ctx)
        out.write_bytes(b'clip')

    monkeypatch.setattr(diagram_scenes, 'render', render)
    candidate = dg.candidate(spec(), tmp_path, motion=motion, engine='scene', seconds=5)
    assert candidate['provider'] == 'diagram'
    assert len(captured) == 1
    assert len(encoded) == (motion == 'reveal')
    assert candidate['kind'] == ('image' if motion == 'still' else 'video')


def test_board_normalized_seed_and_all_reveal(project):
    raw = {**spec(), 'title': '', 'note': '', 'reveal': 'all'}
    slide = Slide(id='diagram', board_template='diagram', diagram=raw,
                  board_lead='Inherited title', board_note='Inherited note')
    sheet = board.build(slide, 'diagram', '#ffaa00', 'marker')
    expected = dg.layout({**raw, 'title': 'Inherited title', 'note': 'Inherited note'})
    assert sheet.seed == expected['seed']
    assert set(board.reveal_plan(sheet, 5)) == {(0, .5)}


def test_slide_endpoint_captures_outside_lock_and_reloads(project, tmp_path, monkeypatch):
    from contextlib import contextmanager
    from app import main
    project.slides = [Slide(id='diagram')]
    locked, loads = [], []

    @contextmanager
    def lock(pid):
        locked.append(pid)
        try:
            yield
        finally:
            locked.pop()

    def load(pid):
        loads.append(pid)
        return project

    def candidate(*a, **kw):
        assert not locked
        assert kw['engine'] == project.style.board_engine
        return {'id': 'new-diagram', 'local_path': 'media/diagram.mp4'}

    monkeypatch.setattr(main.store, 'lock_for', lock)
    monkeypatch.setattr(main, '_load', load)
    monkeypatch.setattr(main, 'project_dir', lambda pid: tmp_path)
    monkeypatch.setattr(main.diagram_mod, 'candidate', candidate)
    monkeypatch.setattr(main.store, 'save', lambda p: None)
    main.slide_diagram(project.id, 'diagram', {'spec': spec()})
    assert loads == [project.id, project.id]
    assert project.slides[0].chosen_id == 'new-diagram'

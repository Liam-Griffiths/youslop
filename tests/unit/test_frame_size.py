"""Aspect foundations: geometry and graph construction, without rendering."""
import re
from pathlib import Path

import pytest

from app import render
from app.schema import Project


@pytest.mark.parametrize('aspect,full,preview', [
    ('landscape', (1920, 1080), (480, 270)),
    ('portrait', (1080, 1920), (270, 480)),
    ('square', (1080, 1080), (270, 270)),
    ('unknown', (1920, 1080), (480, 270)),
])
def test_frame_size_roundtrip(aspect, full, preview):
    project = Project.from_dict({'id': 'aspect', 'idea': '', 'aspect': aspect,
                                 'future_field': True})
    restored = Project.from_dict(project.to_dict())
    assert restored.aspect == aspect
    assert render.frame_size(restored) == full
    assert render.frame_size(restored, preview=True) == preview
    assert render.preview_size(restored) == preview


def test_missing_aspect():
    project = Project.from_dict({'id': 'old', 'idea': ''})
    assert project.aspect == 'landscape'
    assert render.frame_size(project) == render.frame_size() == (1920, 1080)
    assert render.preview_size() == (480, 270)


@pytest.mark.parametrize('size', [(1080, 1920), (1080, 1080)])
@pytest.mark.parametrize('source', [(4000, 2000), (1000, 3000)])
@pytest.mark.parametrize('focal', [[0, 0], [.85, .4], [1, 1], None])
def test_cover_crop_geometry(monkeypatch, size, source, focal):
    monkeypatch.setattr(render.ffutil, 'dimensions', lambda _: source)
    graph, point = render._cover_crop(Path('photo.jpg'), *size, focal)
    match = re.fullmatch(r'scale=(\d+):(\d+),crop=(\d+):(\d+):(\d+):(\d+),setsar=1', graph)
    assert match
    sw, sh, w, h, x, y = map(int, match.groups())
    assert (w, h) == size
    assert 0 <= x <= sw - w and 0 <= y <= sh - h
    if focal is None:
        assert point is None
    else:
        assert 0 <= point[0] <= w and 0 <= point[1] <= h
        assert point == pytest.approx((focal[0] * sw - x, focal[1] * sh - y), abs=.5)


@pytest.mark.parametrize('size', [(1080, 1920), (1080, 1080)])
@pytest.mark.parametrize('move', ['set', 'creep_in', 'creep_out', 'punch', 'reveal'])
@pytest.mark.parametrize('edge', [0, 1])
def test_focal_moves_stay_inside_crop(size, move, edge):
    iw, ih = size[0] * 2, size[1] * 2
    graph = render._kenburns(move, 90, .12, (iw * edge, ih * edge), size, 30)
    zoom, x, y = re.search(r"z='([^']+)':x='([^']+)':y='([^']+)'", graph).groups()
    for on in (0, 1, 45, 89):
        context = dict(on=on, iw=iw, ih=ih, min=min, max=max,
                       clip=lambda n, lo, hi: min(max(n, lo), hi))
        # Expressions contain only the generated numeric camera vocabulary.
        z = eval(zoom, {'__builtins__': {}}, context)
        context['zoom'] = z
        px = eval(x, {'__builtins__': {}}, context)
        py = eval(y, {'__builtins__': {}}, context)
        assert 0 <= px <= iw - iw / z + 1e-8
        assert 0 <= py <= ih - ih / z + 1e-8


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
def test_graph_resolves_original_or_preview(project, monkeypatch, aspect):
    project.aspect = aspect
    project.style.format = 'kenburns'
    group = [(project.slides[0], 3)]
    seen = []
    monkeypatch.setattr(render, '_chosen', lambda *a, **kw: (seen.append(kw['preview']) or None, 'image', []))
    monkeypatch.setattr(render.titles, 'render_title', lambda *a, **kw: None)
    inputs, _, _ = render._segment_graph(project, group, 3, 'set')
    w, h = render.frame_size(project)
    assert any(f's={w}x{h}:' in arg for arg in inputs)
    assert seen == [False]
    render._segment_graph(project, group, 3, 'set', size=render.preview_size(project))
    assert seen == [False, True]


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
def test_essay_fallback_preserves_layout(project, monkeypatch, aspect):
    project.aspect = aspect
    project.style.format = 'essay'
    project.style.captions_engine = 'pillow'
    monkeypatch.setattr(render, '_chosen', lambda *a, **kw: (None, 'image', []))
    monkeypatch.setattr(render.titles, 'render_caption', lambda *a, **kw: None)
    inputs, graph, last = render._segment_graph(project, [(project.slides[0], 3)], 3, 'set')
    w, h = render.frame_size(project)
    assert any('s=1920x1080:' in arg for arg in inputs)
    assert f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black' in graph
    assert last == '[aspect]'


def test_landscape_cache_signatures(project, monkeypatch):
    """Captured before T14.2 edits with deterministic paths/stat inputs."""
    project.style.format = 'kenburns'
    project.style.captions_engine = 'pillow'
    groups = render._picture_groups(project, render._slide_durations(project, False))
    opts = dict(seg_len=3., op='set', channel=None, chapter=None, size=(1920, 1080), fps=30,
                dip_out=False, camera_index=0, last_line=False, crf=18, preset='veryfast')
    monkeypatch.setattr(render, 'project_dir', lambda _: Path('/tmp/t14-key-fixture'))
    monkeypatch.setattr(render, '_chosen', lambda *a, **kw: (None, 'image', []))
    monkeypatch.setattr(render, '_stat', lambda _: None)
    monkeypatch.setattr(render.titles, 'render_title', lambda *a, **kw: None)
    monkeypatch.setattr(render.ffutil, '_use_gpu', lambda _: None)
    assert render._segment_key(project, groups[0], opts) == '175223884cfd96ecf1ae33d15466dc3cd3a7faf5'
    assert render._proxy_key(project, groups, 0, None) == 'a3f1af825b8f3a36'
    assert render._slate_key(project, 'intro') == '8ba2ce23b02f6e1d'

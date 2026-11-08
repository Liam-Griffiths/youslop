"""Photographic graphs are reviewed as text, with stable paths and labels."""
import os

import pytest

from app import render
from tests._fixtures import ROOT


@pytest.mark.parametrize("name,fmt,size,fps", [
    ("doc_full", "kenburns", (render.WIDTH, render.HEIGHT), render.FPS),
    ("essay_full", "essay", (render.WIDTH, render.HEIGHT), render.FPS),
    ("doc_preview", "kenburns", render.preview_size(), render.PREVIEW_FPS),
])
def test_segment_graph(project, request, name, fmt, size, fps, seg_len=3.0):
    project.style.format = fmt
    project.style.captions_engine = "pillow"  # Preserve the legacy graph reference.
    project.slides[0].chapter = "Opening"
    group = render._picture_groups(project, render._slide_durations(project, False))[0]
    inputs, graph, last = render._segment_graph(
        project, group, seg_len, render.camera_plan(project, [group])[0], size=size, fps=fps,
        chapter=("Next chapter", "Test"))

    def norm(s):
        return s.replace(os.environ["CORKBORED_DATA"], "<DATA>").replace(str(ROOT), "<REPO>")

    actual = ("\n".join(norm(a) for a in inputs) + "\n---\n"
              + norm(graph).replace(";", ";\n") + "\n---\n" + last + "\n")
    golden = ROOT / "tests/golden" / f"{name}.txt"
    if request.config.getoption("--update-goldens"):
        golden.write_text(actual)
    assert actual == golden.read_text()


def test_archive_clip_sources_unchanged(monkeypatch):
    """Reference captured from HEAD's _clip_source before T11.6 edits."""
    import json
    from pathlib import Path
    for duration, length, expected in json.loads((ROOT / 'tests/golden/archive_clip_sources.json').read_text()):
        monkeypatch.setattr(render.ffutil, 'duration', lambda p: duration)
        args, graph = render._clip_source(Path('archive.mp4'), length, 'null')
        assert [args, graph] == expected


def test_video_graph_unchanged(project, request, monkeypatch):
    candidate = next(c for c in project.slides[0].candidates if c['id'] == project.slides[0].chosen_id)
    candidate['kind'] = 'video'
    monkeypatch.setattr(render.ffutil, 'duration', lambda path: 8.0)
    test_segment_graph(project, request, 'video_full', 'kenburns', (render.WIDTH, render.HEIGHT), render.FPS)


def test_footage_overlay(project, request, monkeypatch):
    # New golden: lower-third alpha compositing above a moving footage base.
    from app import block_overlays
    from pathlib import Path
    slide = project.slides[0]
    slide.overlays = [dict(id='name', block_id='lower_third_panel', vars={}, at=1., dur=3.)]
    slide.take['duration'] = 8
    candidate = next(c for c in slide.candidates if c['id'] == slide.chosen_id)
    candidate.update(kind='video', provider='footage', in_s=2., out_s=10.)
    monkeypatch.setattr(render, '_chosen', lambda *a, **kw: (ROOT/'tests/fixtures/project_min/media/pic.jpg', 'video', []))
    monkeypatch.setattr(render.ffutil, 'duration', lambda path: 12.)
    monkeypatch.setattr(block_overlays, 'clip', lambda *a, **kw: Path('<OVERLAY>/lower_third.mov'))
    test_segment_graph(project, request, 'footage_overlay', 'kenburns', (480, 270), 15, seg_len=9.)

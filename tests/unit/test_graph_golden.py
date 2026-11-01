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
def test_segment_graph(project, request, name, fmt, size, fps):
    project.style.format = fmt
    project.style.captions_engine = "pillow"  # Preserve the legacy graph reference.
    project.slides[0].chapter = "Opening"
    group = render._picture_groups(project, render._slide_durations(project, False))[0]
    inputs, graph, last = render._segment_graph(
        project, group, 3.0, render.camera_plan(project, [group])[0], size=size, fps=fps,
        chapter=("Next chapter", "Test"))

    def norm(s):
        return s.replace(os.environ["CORKBORED_DATA"], "<DATA>").replace(str(ROOT), "<REPO>")

    actual = ("\n".join(norm(a) for a in inputs) + "\n---\n"
              + norm(graph).replace(";", ";\n") + "\n---\n" + last + "\n")
    golden = ROOT / "tests/golden" / f"{name}.txt"
    if request.config.getoption("--update-goldens"):
        golden.write_text(actual)
    assert actual == golden.read_text()

"""Opt-in: encode exactly one three-second segment at quarter size."""
import os
import shutil

import pytest

from app import ffutil, render
from tests._fixtures import ROOT
from tests._ssim import ssim

pytestmark = pytest.mark.skipif(os.environ.get("YS_VISUAL") != "1", reason="set YS_VISUAL=1")


def test_documentary_preview(project, tmp_path, request):
    group = render._picture_groups(project, render._slide_durations(project, False))[0]
    segment = tmp_path / "segment.mp4"
    render._render_segment(project, group, 3.0, 0, segment,
                           size=render.preview_size(), fps=render.PREVIEW_FPS,
                           crf=render.PREVIEW_CRF, preset="ultrafast", threads=2)
    frame = tmp_path / "frame.png"
    ffutil.run(["-ss", "1", "-i", str(segment), "-frames:v", "1", str(frame)], threads=2)
    reference = ROOT / "tests/golden/segment_doc_preview.png"
    if request.config.getoption("--update-goldens") or not reference.exists():
        shutil.copyfile(frame, reference)
    score = ssim(frame, reference, tile=render.preview_size())
    assert score > 0.99, f"SSIM {score:.6f} <= 0.99"

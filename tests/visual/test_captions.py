"""Reviewer opt-in: one quarter-size essay segment against an approved frame."""
import os
import shutil

import pytest

from app import ffutil, render, stage
from tests._fixtures import ROOT
from tests._ssim import ssim

pytestmark = pytest.mark.skipif(os.environ.get('YS_VISUAL') != '1', reason='set YS_VISUAL=1')


def test_captions_preview(project, tmp_path, request):
    reference = ROOT / 'tests/golden/segment_captions_preview.png'
    update = request.config.getoption('--update-goldens')
    if not reference.exists() and not update:
        pytest.skip('BLOCKED: reviewer must approve/create caption golden with --update-goldens')
    if not stage.browser():
        pytest.skip('BLOCKED: Chromium unavailable')
    project.style.format = 'essay'
    project.slides[0].narration = 'A caption with emoji 🐈 and balanced wrapping.'
    project.slides[0].take = dict(duration=2.5, words=[])
    segment = tmp_path / 'segment.mp4'
    render._render_segment(project, [(project.slides[0], 3)], 3, 0, segment,
                           size=render.preview_size(), fps=render.PREVIEW_FPS,
                           crf=render.PREVIEW_CRF, preset='ultrafast', threads=2)
    frame = tmp_path / 'frame.png'
    ffutil.run(['-ss', '1', '-i', str(segment), '-frames:v', '1', str(frame)], threads=2)
    if update:
        shutil.copyfile(frame, reference)
    score = ssim(frame, reference, tile=render.preview_size())
    assert score > .99, f'SSIM {score:.6f} <= .99'

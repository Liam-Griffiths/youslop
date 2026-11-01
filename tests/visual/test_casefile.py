"""Only a reviewer's accepted real scene capture may become the golden."""
import os
from pathlib import Path

import pytest
from tests._ssim import ssim

pytestmark=pytest.mark.skipif(os.environ.get('YS_VISUAL')!='1',reason='set YS_VISUAL=1')


def test_casefile_scene_golden(project,tmp_path):
    from app import cuts,ffutil
    golden=Path(__file__).resolve().parents[1]/'golden/casefile_scene.png'
    if not golden.is_file():
        pytest.skip('Pending reviewer: Chromium capture and first accepted Casefile scene golden')
    project.style.format='casefile'
    movie,frame=tmp_path/'frame.mp4',tmp_path/'frame.png'
    cuts.render_segment(project,[(project.slides[0],3)],3,movie,size=(480,270),fps=30,frames=(45,46))
    ffutil.run(['-i',str(movie),'-frames:v','1',str(frame)])
    assert ssim(frame,golden)>.99

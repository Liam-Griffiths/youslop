"""Owner-run check: one Jinja scene PNG at quarter size; no MP4 render."""
import io
import os

from PIL import Image
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('YS_VISUAL') != '1', reason='set YS_VISUAL=1')


def test_jinja_scene_capture(tmp_path):
    from app import scenes

    png = scenes.capture(tmp_path, '_test/base.html', scenes.context_base(),
                         t=1.5, size=(480, 270))
    image = Image.open(io.BytesIO(png))
    assert image.size == (480, 270)
    assert len(list((tmp_path / 'scenes').glob('*_1.5.png'))) == 1

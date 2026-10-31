"""Opt-in: one quarter-size, 30-frame scene preview, plus PNG snapshots."""
import io
import json
import os
import subprocess

from PIL import Image
import pytest

from app import stage

pytestmark = pytest.mark.skipif(os.environ.get("YS_VISUAL") != "1", reason="set YS_VISUAL=1")


def test_scene_capture(tmp_path):
    page = "/static/scene/_test/static.html"
    items = [dict(clip="static", url_path=page, W=1920, H=1080,
                  size=(480, 270), fps=30, frames=30)]
    clips = stage.render_scene(items, tmp_path)
    result = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                             "-show_entries", "stream=nb_read_frames,width,height", "-of", "json",
                             str(clips["static"])], check=True, capture_output=True, text=True)
    stream = json.loads(result.stdout)["streams"][0]
    assert stream == {"width": 480, "height": 270, "nb_read_frames": "30"}
    one = stage.capture_one(page, 1920, 1080, 0, (480, 270))
    assert one == stage.capture_one(page, 1920, 1080, 0, (480, 270))
    image = Image.open(io.BytesIO(one))
    assert image.size == (480, 270)
    # The orange box also proves composition layout and upright output.
    assert image.getpixel((60, 120))[:3] == (255, 90, 31)

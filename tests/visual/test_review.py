"""Opt-in review check: one quarter-size photographic segment, no Chromium."""
import os

import pytest
from PIL import Image

from app import render, review

pytestmark = pytest.mark.skipif(os.environ.get('YS_VISUAL') != '1', reason='set YS_VISUAL=1')


def test_review_grab(project, tmp_path, monkeypatch):
    project.slides = project.slides[:1]
    project.use_intro = project.use_outro = False
    project.style.format = 'kenburns'
    # Every requested frame belongs to this one cheap segment.
    original = render.proxy_segment
    builds = []
    def proxy(*a, **kw):
        builds.append(a[1])
        assert len(builds) == 1
        return original(*a, **kw)
    monkeypatch.setattr(render, 'proxy_segment', proxy)
    rows = review.snapshots(project)
    root = render.project_dir(project.id)
    path = review.sheet([dict(row, path=root / row['path']) for row in rows], tmp_path / 'sheet.png')
    with Image.open(path) as image:
        assert image.width == 1440
    assert builds == [0]

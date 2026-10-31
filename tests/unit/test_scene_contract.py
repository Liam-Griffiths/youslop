"""Offline HTML contract check; browser behavior lives in scene/_test/check.html."""
from html.parser import HTMLParser
from pathlib import Path

import pytest

SCENE = Path(__file__).resolve().parents[2] / 'static/scene/_test/static.html'


class SceneContract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.roots = []
        self.clips = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'data-composition-id' in attrs:
            self.roots.append(attrs)
        if 'clip' in attrs.get('class', '').split():
            self.clips.append(attrs)
        if tag == 'script' and 'src' in attrs:
            self.scripts.append(attrs['src'])

    def check(self):
        assert len(self.roots) == 1, 'one composition root required'
        for key in ('data-composition-id', 'data-width', 'data-height', 'data-duration'):
            assert self.roots[0].get(key), f'root missing {key}'
        for clip in self.clips:
            for key in ('data-start', 'data-duration'):
                assert clip.get(key), f'clip missing {key}'


def test_scene_contract():
    parser = SceneContract()
    parser.feed(SCENE.read_text())
    parser.check()
    assert parser.clips
    assert parser.scripts[:2] == ['../runtime.js', '../../vendor/gsap/gsap.min.js']
    assert parser.clips[0]['data-anim'] == 'rise'
    assert float(parser.clips[0]['data-start']) == 0
    assert float(parser.clips[0]['data-duration']) == 3


@pytest.mark.parametrize('key', ['data-composition-id', 'data-width', 'data-height',
                                 'data-duration', 'data-start'])
def test_missing_contract_attribute_rejected(key):
    parser = SceneContract()
    html = SCENE.read_text()
    # Removing the root duration checks the root, removing start checks a clip.
    html = html.replace(key + '=', 'removed=', 1)
    parser.feed(html)
    with pytest.raises(AssertionError):
        parser.check()

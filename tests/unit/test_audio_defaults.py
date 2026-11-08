"""Music offset and master loudness follow the audio doctrine."""
import pytest

from app.render import _audio_graph
from app.schema import Channel, FrameSpec, IntroSpec, Project, Style


def test_music_defaults():
    style, frame = Style(), FrameSpec()
    assert style.music_db == -17.5
    assert frame.music_under_min_db <= -style.music_db <= frame.music_under_max_db
    assert not hasattr(style, 'duck_db')
    assert 'duck_db' not in style.to_dict()


@pytest.mark.parametrize('model', [Project, Channel])
def test_stale_style_keys_ignored(model):
    base = {'id': 'legacy', 'name': 'Legacy', 'idea': 'Test'}
    obj = model.from_dict({**base, 'style': {'duck_db': -11.0, 'music_db': -20.0}})
    assert obj.style.music_db == -20.0
    assert not hasattr(obj.style, 'duck_db')
    assert model.from_dict({**base, 'style': {}}).style.music_db == -17.5


@pytest.mark.parametrize('has_music,has_sting', [(False, False), (False, True),
                                               (True, False), (True, True)])
@pytest.mark.parametrize('master', [-14.0, -12.5])
def test_single_pass_fallback_loudness(project, has_music, has_sting, master):
    # The unmeasured graph deliberately retains the original fallback master;
    # test_master_loudnorm covers the measured graph used by both callers.
    project.frame.voice_lufs = master
    stings = [(2, 0.0, 3.0, IntroSpec(), 'intro')] if has_sting else None
    graph = _audio_graph(project, 1, 12.0, has_music, sting=stings)
    assert graph.endswith(f'loudnorm=I={master:.1f}:TP=-1.0:LRA=11[aout]')
    assert project.voice.target_lufs == -16.0
    if has_music:
        assert 'loudnorm=I=-16.0:TP=-2.0:LRA=11,volume=-17.5dB' in graph

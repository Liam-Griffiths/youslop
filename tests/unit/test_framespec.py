"""Frame doctrine storage, prompts and API patch persistence (no rendering)."""
import json

import pytest

from app import channels, store, storyboard
from app.schema import BANNED_DEFAULTS, BANNED_MEANINGS, Channel, FrameSpec, Project, new_project
from tests._fixtures import ROOT


def test_defaults_and_legacy():
    spec = FrameSpec()
    assert FrameSpec.from_dict(spec.to_dict()) == spec
    assert FrameSpec.from_dict({}) == spec
    assert FrameSpec.from_dict({'future_field': 42}) == spec
    legacy = json.loads((ROOT / 'tests/fixtures/project_min/project.json').read_text())
    assert 'frame' not in legacy
    assert Project.from_dict(legacy).frame == spec
    assert Channel.from_dict({'id': 'cold', 'name': 'Old channel'}).frame == spec
    assert set(BANNED_DEFAULTS) == set(BANNED_MEANINGS)


def test_round_trip_and_channel_copy():
    channel = Channel(id='cframe', name='Frame channel')
    channel.frame = channel.frame.merge({'arrive_s': '0.4', 'rules': ['Keep it still']})
    assert Channel.from_dict(channel.to_dict()).frame == channel.frame
    project = new_project('A test', channel=channel)
    assert Project.from_dict(project.to_dict()).frame == channel.frame
    assert project.frame == channel.frame
    project.frame.rules.append('Another rule')
    project.frame.banned.clear()
    project.frame.transition_types.append('wipe')
    assert channel.frame.rules == ['Keep it still']
    assert channel.frame.banned == BANNED_DEFAULTS
    assert channel.frame.transition_types == ['cut', 'fade', 'dip']
    assert FrameSpec().rules == []


def test_merge():
    spec = FrameSpec()
    merged = spec.merge({'arrive_s': '0.4', 'overlays_per_hook': '8',
                         'snap_on_cut': 'false', 'camera_origin': 'center',
                         'rules': [123]})
    assert merged.arrive_s == 0.4
    assert merged.overlays_per_hook == 8
    assert type(merged.overlays_per_hook) is int
    assert merged.snap_on_cut is False
    assert merged.merge({'snap_on_cut': 'yes'}).snap_on_cut is True
    assert merged.camera_origin == 'center'
    assert merged.rules == ['123']
    assert spec == FrameSpec()
    merged.transition_types.append('wipe')
    assert spec.transition_types == ['cut', 'fade', 'dip']


@pytest.mark.parametrize('patch', [
    {'nonsense': 1}, {'arrive_s': 'nonsense'}, {'arrive_s': None},
    {'overlays_per_hook': {}}, {'rules': 'not a list'}, None, [],
])
def test_bad_merge_is_atomic(patch):
    spec = FrameSpec()
    with pytest.raises(ValueError):
        spec.merge(patch)
    assert spec == FrameSpec()


@pytest.mark.parametrize('fmt', ['kenburns', 'loudmouth'])
def test_prompt_golden(fmt):
    text = FrameSpec().prompt_block(fmt)
    assert text + '\n' == (ROOT / f'tests/golden/framespec_{fmt}.txt').read_text()
    assert len(text.splitlines()) < 60
    assert '0.3 seconds per word' in text
    assert all(name in text for name in BANNED_DEFAULTS)
    assert ('Montage cuts' in text) == (fmt == 'loudmouth')
    assert ('Camera creeps' in text) == (fmt == 'kenburns')
    custom = FrameSpec().merge({'title_hold_per_word_s': 0.7, 'banned': ['custom_ban'],
                                'rules': ['Stay quiet'], 'design_md': 'Orange',
                                'frame_md': 'Wide', 'rejected_looks': ['neon']}).prompt_block(fmt)
    for expected in ('0.7 seconds per word', 'custom_ban', 'Stay quiet', 'Orange', 'Wide', 'neon'):
        assert expected in custom


@pytest.mark.parametrize('kind', ['project', 'channel'])
def test_api_patch(project, kind):
    from app import main
    if kind == 'project':
        store.save(project)
        ident, patch, load = project.id, main.patch_project, store.load
        assert main.get_project(ident)['frame'] == FrameSpec().to_dict()
    else:
        channel = Channel(id='cframeapi', name='Frame channel')
        channels.save(channel)
        ident, patch, load = channel.id, main.patch_channel, channels.load
    result = patch(ident, {'frame': {'arrive_s': '0.4', 'rules': ['Be clear']}})
    assert result['frame']['arrive_s'] == 0.4
    assert load(ident).frame == FrameSpec().merge({'arrive_s': 0.4, 'rules': ['Be clear']})
    for invalid in ({'nonsense': 1}, {'arrive_s': 'nonsense'}, {'rules': 'bad'}, None):
        before = load(ident).to_dict()
        with pytest.raises(main.HTTPException) as exc:
            patch(ident, {'frame': invalid})
        assert exc.value.status_code == 400
        assert load(ident).to_dict() == before


def test_storyboard_frame(project):
    project.frame.rules.append('Keep the title still')
    result = storyboard.build(project)
    assert result['frame'] == project.frame.to_dict()
    result['frame']['rules'].clear()
    assert project.frame.rules == ['Keep the title still']

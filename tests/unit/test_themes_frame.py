"""Theme pacing is opt-in and preserves unrelated frame settings."""
import pytest

from app import channels, themes
from app.schema import FrameSpec, new_project


@pytest.mark.parametrize('key, overrides', [
    ('arcade', {'montage_cut_max_s': 0.5, 'punch_max': 1.25,
                'transition_types': ['cut', 'dip', 'wipeleft']}),
    ('archive', {'move_max_s': 0.8, 'creep_max': 1.10,
                 'transition_types': ['fade', 'dip'], 'shot_avg_min_s': 2.5}),
    ('gloss', {}),
])
def test_theme_frame(key, overrides):
    original = FrameSpec().merge({'punch_max': 1.20, 'rules': ['Stay clear']})
    result = themes.apply_to_frame(original, key)
    assert result.to_dict() == {**original.to_dict(), **overrides}
    assert original.punch_max == 1.20
    result.rules.append('Independent')
    result.transition_types.clear()
    assert original.rules == ['Stay clear']
    assert themes.theme(key)['frame'] == overrides
    assert themes.apply_to_frame(FrameSpec(), key).to_dict() == {
        **FrameSpec().to_dict(), **overrides}


@pytest.mark.parametrize('templates', [True, False])
def test_channel_theme_and_project_copy(templates):
    from app import main

    created = main.create_channel({'name': 'Theme test'})
    cid = created['id']
    assert created['frame'] == FrameSpec().to_dict()
    main.patch_channel(cid, {'frame': {'rules': ['Keep this']},
                             'style': {'theme': 'arcade'}})
    before = channels.load(cid)
    assert before.frame.montage_cut_max_s == 0.8
    old_project = new_project('Existing episode', channel=before)
    result = main.apply_theme(cid, {'key': 'arcade', 'templates': templates})
    channel = channels.load(cid)
    assert channel.frame == themes.apply_to_frame(before.frame, 'arcade')
    assert result['style']['accent'] == themes.theme('arcade')['accent']
    assert result['intro']['template'] == ('arcade' if templates else before.intro.template)
    assert old_project.frame == before.frame
    project = new_project('New episode', channel=channel)
    assert project.frame == channel.frame
    project.frame.rules.clear()
    assert channel.frame.rules == ['Keep this']
    # Reloading legacy records never implicitly applies Archive's overrides.
    assert main.get_channel(cid)['frame'] == result['frame']


@pytest.mark.parametrize('templates', [True, False])
def test_theme_undo_patch_restores_saved_fields(templates):
    from app import main

    cid = main.create_channel({'name': 'Theme undo'})['id']
    before = main.patch_channel(cid, {
        'style': {'accent': '#123456', 'accent2': '#654321', 'grade': 'mono'},
        'frame': {'transition_types': ['fade'], 'punch_max': 1.21},
        'outro': {'template': 'console', 'slots': 3},
    })
    undo = {
        'style': {k: before['style'][k] for k in ('theme', 'accent', 'accent2', 'grade')},
        'frame': before['frame'], 'intro': {'template': before['intro']['template']},
        'thumb_template': before['thumb_template'],
        'outro': {k: before['outro'][k] for k in ('template', 'slots')},
    }
    applied = main.apply_theme(cid, {'key': 'arcade', 'templates': templates})
    assert applied['style']['accent'] != before['style']['accent']
    if templates:
        assert applied['outro']['slots'] < before['outro']['slots']
    restored = main.patch_channel(cid, undo)
    # Saving updates the modification timestamp, while channel contents return exactly.
    assert {**restored, 'updated_at': before['updated_at']} == before
    assert channels.load(cid).to_dict() == restored

"""Learning feedback stays local; no models, captures or renders."""
import pytest
from fastapi import HTTPException

from app import channels, cli, learning, main, ops, render, review, script_gen, store, storyboard
from app.schema import Channel, FrameSpec, Project, Slide, new_channel, new_project


@pytest.fixture
def episode(tmp_path):
    channel = new_channel('Learning')
    channel.id = 'c' + tmp_path.name
    channels.save(channel)
    project = new_project('A learning episode', channel=channel)
    store.save(project)
    return project, channel


def test_rules(episode):
    project, channel = episode
    learning.add(project.id, '  Use   concrete examples  ')
    learning.add(project.id, 'Use concrete examples')
    learning.add(project.id, 'Keep titles short', scope='channel')
    learning.add(project.id, 'x' * 250)
    project = store.load(project.id)
    assert project.frame.rules == ['Use concrete examples', 'x' * 200]
    prompt = script_gen._frame_text(project)
    assert 'House rules:' in prompt
    assert prompt.index('Keep titles short') < prompt.index('Use concrete examples')
    with pytest.raises(ValueError):
        learning.add(project.id, '  ')
    with pytest.raises(ValueError):
        learning.add(project.id, 'test', scope='other')


def test_camera_and_late_channel_feedback(episode):
    project, channel = episode
    learning.add(project.id, 'camera:punch', kind='rejected_looks', scope='channel')
    frame = learning.effective_frame(project)
    previous = None
    for i in range(200):
        previous = render._pick_op(frame, i, previous, bool(i % 2), True)
        assert previous != 'punch'
    project.slides = [Slide(id='s1', narration='A short paragraph.', chapter='Chapter')]
    story = storyboard.build(project)
    assert not any(s.get('camera') == 'punch' for s in story['segments'])
    assert 'camera:punch' in script_gen._frame_text(project)
    assert render.camera_plan(project, [[(project.slides[0], 2)]]) != ['punch']


def test_tokens_routes_and_exhaustion(episode, caplog):
    project, channel = episode
    with pytest.raises(ValueError):
        learning.add(project.id, 'No gradients', kind='rejected_looks')
    with pytest.raises(HTTPException) as error:
        main.reject_frame_look(project.id, {'look': 'camera:bogus'})
    assert error.value.status_code == 400
    assert main.add_frame_rule(project.id, {'text': 'Be specific'})['rules'] == ['Be specific']
    review.route_fix(project, {'kind': 'look', 'hint': 'camera:punch'}, apply=True)
    assert store.load(project.id).frame.rejected_looks == ['camera:punch']
    frame = FrameSpec(rejected_looks=['camera:' + op for op in render.CAMERA_OPS])
    assert render._pick_op(frame, 0, None, False, True) == 'punch'
    assert 'All camera candidates rejected' in caplog.text


def test_join_and_choices(episode):
    project, channel = episode
    a = [(Slide(id='a', narration='a', beat='same'), 1)]
    b = [(Slide(id='b', narration='b', beat='same'), 1)]
    frame = FrameSpec(rejected_looks=['join:cut'])
    assert render._join_for(a, b, frame) != 'cut'
    project.style.theme = 'archive'
    project.style.format = 'loudmouth'
    for token in ('theme:archive', 'cut:loudmouth'):
        learning.add(project.id, token, kind='rejected_looks', scope='channel')
    learning.resolve_choices(project)
    assert project.style.theme != 'archive'
    assert project.style.format != 'loudmouth'


def test_saved_format_roundtrip(episode):
    project, channel = episode
    project.style.accent = '#123456'
    project.frame.rules.append('Saved rule')
    store.save(project)
    result = main.save_channel_format(channel.id, {'pid': project.id, 'name': 'House'})
    channel = Channel.from_dict(channels.load(channel.id).to_dict())
    assert channel.formats == [result]
    fresh = new_project('Next episode', channel=channel, format_name='House')
    assert fresh.style.to_dict() == project.style.to_dict()
    assert fresh.frame.to_dict() == project.frame.to_dict()
    assert Project.from_dict(fresh.to_dict()).format_look == result['look']
    assert render._slate_channel(fresh).intro.to_dict() == result['look']['intro']
    fresh.frame.rules.append('Independent')
    fresh.format_look['intro']['template'] = 'changed'
    assert channel.formats[0] == result
    prepared, _ = ops.prepare_create({'idea': 'Another episode idea', 'channel_id': channel.id,
                                     'format_name': 'House', 'format': 'board', 'picture_every': 8})
    assert prepared.style.to_dict() == project.style.to_dict()
    with pytest.raises(ValueError):
        new_project('No match', channel=channel, format_name='missing')
    with pytest.raises(ValueError):
        learning.save_format(channel.id, project.id, 'House')
    assert Channel.from_dict({'id': 'old', 'name': 'Old', 'unknown': True}).formats == []


def test_cli(episode, capsys):
    project, channel = episode
    assert cli.main(['rule', 'add', 'Short titles', '--pid', project.id]) == 0
    assert cli.main(['look', 'reject', 'camera:punch', '--pid', project.id, '--scope', 'channel']) == 0
    assert cli.main(['format', 'save', 'CLI house', '--pid', project.id]) == 0
    assert cli.main(['format', 'list', channel.id]) == 0
    assert 'CLI house' in capsys.readouterr().out


def test_mocked_plan_uses_late_feedback(episode, monkeypatch):
    project, channel = episode
    project.slides = [Slide(id='s1', narration='Specific examples work.', chapter='Start')]
    learning.add(project.id, 'camera:punch', kind='rejected_looks', scope='channel')
    learning.add(project.id, 'Specific examples', scope='channel')
    def fake(prompt, **kwargs):
        assert 'Specific examples' in prompt and 'camera:punch' in prompt
        return [{'n': 1, 'queries': ['specific example'], 'kind': 'image', 'title': 'Start'}]
    monkeypatch.setattr(script_gen, 'complete_json', fake)
    script_gen.plan_visuals(project, project.slides)
    assert all(s.get('camera') != 'punch' for s in storyboard.build(project)['segments'])

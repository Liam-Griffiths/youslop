"""Mixed pictures share one narration clock and preserve inactive picture data."""
from copy import deepcopy
import re

import pytest

from app import board, check, cuts, edits, kinds, render, scenes, script_gen, stages, storyboard
from app.schema import Project, Slide


@pytest.fixture
def mixed(project):
    project.style.format, project.style.picture_every = 'kenburns', 1
    project.slides = [deepcopy(project.slides[0]) for _ in range(4)]
    for i, (slide, kind) in enumerate(zip(project.slides, ['kenburns', 'board', 'casefile', 'essay'])):
        slide.id, slide.kind, slide.title, slide.chapter = f'm{i}', kind, '', ''
    project.slides[-1].cues = {'blocks': [{'block': 'chapter_card', 'vars': {'title': 'End'}}]}
    return project


@pytest.mark.parametrize('left,right,hard', [
    ('kenburns', 'board', False), ('board', 'casefile', True), ('casefile', 'block', True),
    ('essay', 'kenburns', False), ('stage', 'board', True), ('camera', 'ticker', True)])
def test_join_table(project, left, right, hard):
    assert kinds.transition_for(project, left, right) == (cuts.HARD_CUT if hard else project.style.transition)


def test_mixed_contract_clock_and_checks(mixed):
    sb = storyboard.build(mixed)
    assert [s['kind'] for s in sb['segments']] == ['kenburns', 'board', 'casefile', 'block']
    assert set(sb['project']['kinds']) == kinds.kinds_in(mixed)
    assert stages.stages(mixed, {})[3]['kinds'] == dict(kenburns=1, board=1, casefile=1, block=1)
    assert [(f['code'], f['level']) for f in check.run(mixed)['findings'] if f['slide_id'] == 'm2'] == [('no_cues', 'P1')]
    groups = render._groups_for_preview(mixed)
    edges = render._overlaps(mixed, groups)
    assert edges == [mixed.style.transition, mixed.style.transition, cuts.HARD_CUT, cuts.HARD_CUT, mixed.style.transition]
    timing = [render._segment_timing(mixed, groups, i) for i in range(4)]
    graph = render._join_graph([t[2] for t in timing], edges[1:-1], groups, mixed.frame, 0)
    assert 'duration=0.033' in graph and graph.count("transition=custom") >= 2
    offsets = [float(v) for v in re.findall(r'offset=([0-9.]+)', graph)]
    file_start, voice_time = 0., 0.
    for i, (duration, incoming, length) in enumerate(timing):
        assert file_start + incoming/2 == pytest.approx(voice_time + edges[0]/2)
        if i < 3:
            assert offsets[i] == pytest.approx(file_start + length - edges[i+1], abs=.001)
        file_start += length - edges[i+1]
        voice_time += duration
    assert render._chain_overlaps(mixed, groups, {1: 0, 2: 1, 4: 2, 5: 3}, 7) == [edges[0], edges[0], edges[1], edges[2], edges[2], edges[3], edges[4], edges[4]]


def test_group_precedence_and_switch_restore(mixed):
    slide = mixed.slides[1]
    slide.board_lead, slide.board_points = 'Keep this board', ['One', 'Two']
    before = slide.to_dict()
    for kind in ['essay', 'board']:
        storyboard.apply(mixed, {'paragraphs': {slide.id: {'kind': kind}}})
    assert slide.to_dict() == before
    with pytest.raises(edits.EditError):
        edits.patch_slide_fields(slide, {'kind': 'unknown'})
    mixed.style.picture_every = 2
    assert kinds.kind_for(mixed, slide) == 'kenburns'
    mixed.slides[0].on_camera = True
    assert kinds.kind_for(mixed, mixed.slides[0]) == 'camera'
    assert Project.from_dict(mixed.to_dict()).slides[1].kind == 'board'
    assert Slide.from_dict({'unknown': 'ignored'}).kind == ''


@pytest.mark.parametrize('fmt', ['casefile', 'groupchat'])
def test_state_restarts(mixed, fmt, monkeypatch, tmp_path):
    for slide in mixed.slides:
        slide.cues = {}
        slide.kind = fmt
    mixed.slides[2].kind = 'board'
    from importlib import import_module
    captured = []
    drawer = import_module('app.cuts.' + fmt + '_scene')
    monkeypatch.setattr(drawer, 'render', lambda p, ctx, *a, **kw: captured.append((p, ctx)))
    cuts.render_segment(mixed, [(mixed.slides[3], 3)], 3.5, tmp_path/'mock.mp4')
    scoped, ctx = captured[0]
    assert [s.id for s in scoped.slides] == ['m3']
    if fmt == 'casefile':
        assert cuts.casefile._boards(ctx) == {'m3': (0, 0)}
    else:
        beat = cuts.beat_for(cuts.groupchat, ctx, mixed.slides[3], 3, 0, 2)
        assert cuts.groupchat._history(ctx, beat) == []


def test_planners_and_dispatch(mixed, monkeypatch, tmp_path):
    for i, slide in enumerate(mixed.slides):
        slide.narration = f"Unique paragraph number {i}."
    calls = []
    monkeypatch.setattr(script_gen, 'complete_json', lambda prompt, **kw: calls.append(prompt) or [])
    script_gen.plan_boards(mixed, mixed.slides)
    script_gen.plan_cues(mixed, mixed.slides)
    assert len(calls) == 2
    for prompt, index in zip(calls, [1, 2]):
        assert [i for i in range(4) if f'Unique paragraph number {i}.' in prompt] == [index]
    seen = []
    monkeypatch.setattr(scenes, 'render_segment', lambda *a, **kw: seen.append(kinds.kind_for(a[0], a[1][0][0])))
    monkeypatch.setattr(board, 'render_segment', lambda *a, **kw: seen.append(kinds.kind_for(a[0], a[1][0][0])))
    monkeypatch.setattr(cuts, 'render_segment', lambda *a, **kw: seen.append(kinds.kind_for(a[0], a[1][0][0])))
    monkeypatch.setattr(render, '_chapter_tail', lambda *a, **kw: a[1])
    for i in [1, 2]:
        render._render_segment(mixed, [(mixed.slides[i], 3)], 3.5, i, tmp_path/'preview.mp4')
    assert seen == ['board', 'casefile']

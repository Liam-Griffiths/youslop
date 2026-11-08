"""Overlay proposals never use a model or mutate hand placements."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from app import block_suggest, blocks, llm, main, overlay_plan, script_gen
from app.media import footage
from app.schema import MediaCandidate, Slide


@pytest.mark.parametrize('text,note,title,expected', [
    ('We met Hannah Chen at the dock.', '', '', 'Hannah Chen'),
    ('Hannah Chen boarded.', '', '', ''),
    ('Hannah Chen boarded.', '', 'Hannah Chen', 'Hannah Chen'),
    ('Hannah boarded.', 'Name: Hannah', '', 'Hannah'),
    ('The ferry reaches Vancouver.', 'lower third: Vancouver', '', 'Vancouver'),
    ('It stopped. New York was next.', '', '', ''),
    ('The ferry sails again.', '', '', ''),
])
def test_conservative_names(text, note, title, expected):
    result = overlay_plan.suggest(text, note, title)
    assert [r['on'] for r in result] == ([expected] if expected else [])
    assert result == overlay_plan.suggest(text, note, title)


@pytest.mark.parametrize('phrase', ['40 percent', 'forty per cent', 'twenty-five percent'])
def test_number_over_footage(phrase):
    result = overlay_plan.suggest(f'Ridership grew {phrase}.', footage=True)
    assert result == [dict(block_id='kinetic_caption_rise', vars={'title': phrase}, on=phrase)]
    assert overlay_plan.suggest(f'Ridership grew {phrase}.') == []
    assert any(r['block'] == 'number_slam' for r in block_suggest.suggest('Ridership grew 40 percent.'))


def test_replan_keeps_hand_and_caps_total(project, monkeypatch):
    monkeypatch.setattr(llm, 'complete_json', Mock(side_effect=AssertionError('No model')))
    s = project.slides[0]
    s.narration, s.title = 'We met Hannah Chen. Ridership grew 40 percent.', ''
    s.candidates, s.chosen_id = [dict(id='boat', provider='footage')], 'boat'
    hand = dict(id='mine', block_id='lower_third_rule', vars={'title':'My name'}, at=17, dur=6, position='top_right', by='hand')
    s.overlays = [deepcopy(hand)]
    overlay_plan.apply(project, s)
    assert s.overlays[0] == hand
    assert len(s.overlays) == 2
    assert s.overlays[1]['block_id'] == 'kinetic_caption_rise'
    first = deepcopy(s.overlays)
    overlay_plan.apply(project, s)
    assert s.overlays == first
    s.narration = 'The ferry sails again.'
    overlay_plan.apply(project, s)
    assert s.overlays == [hand]
    s.overlays = [dict(hand, id=str(i)) for i in range(3)]
    overlay_plan.apply(project, s)
    assert len(s.overlays) == 3  # Never discard manual work to satisfy the cap.


def test_fill_adds_graphic_keeps_base(project, monkeypatch):
    s = project.slides[0]
    project.slides = [s]
    s.narration, s.chosen_id = 'We met Hannah Chen beside the ferry.', ''
    candidate = MediaCandidate(id='boat', provider='footage', kind='video')
    candidate.matched = True
    monkeypatch.setattr(footage, 'suggestions', lambda *a, **kw: [candidate])
    assert footage.fill(project) == 1
    assert s.chosen_id == 'boat' and s.candidates[0]['provider'] == 'footage'
    assert s.overlays[0]['on'] == 'Hannah Chen' and s.overlays[0]['by'] == 'auto'
    blocks.validate_vars(blocks.discover()[s.overlays[0]['block_id']]['meta'], s.overlays[0]['vars'])


def test_visual_planner_uses_existing_call_only(project, monkeypatch):
    s = Slide(narration='We met Hannah Chen beside the ferry.')
    calls = Mock(return_value=[dict(n=1, queries=['ferry'], kind='video', title='')])
    monkeypatch.setattr(script_gen, 'complete_json', calls)
    script_gen.plan_visuals(project, [s])
    assert calls.call_count == 1 and s.queries == ['ferry']
    assert s.overlays[0]['on'] == 'Hannah Chen'


def test_overlay_browse_and_hide_contract():
    rows = main.list_blocks(overlay=True)
    assert len(rows) == 11 and all(r['overlay'] for r in rows)
    assert {'lower_third_kicker', 'lower_third_underline', 'lower_third_pill',
            'lower_third_reveal', 'lower_third_portrait'} <= {r['ref'] for r in rows}
    assert 'number_slam' not in {r['ref'] for r in rows}
    assert main._preview_hide('graphics') == frozenset({'graphics'})


def test_hidden_graphics_skip_composition(project, monkeypatch):
    from app import block_overlays, render
    s = project.slides[0]
    s.overlays = [dict(id='g', block_id='lower_third_panel', vars={}, at=0, dur=2)]
    group = [(s, 3)]
    compose = Mock(side_effect=AssertionError('hidden graphics must not be prepared'))
    monkeypatch.setattr(block_overlays, 'compose', compose)
    render._segment_graph(project, group, 4, 0, size=(480,270), fps=15,
                          hide=frozenset({'graphics'}), prepare_only=True)
    assert not compose.called
    groups = render._picture_groups(project, render._slide_durations(project, False))
    assert render._proxy_key(project, groups, 0, None, frozenset({'graphics'})) != render._proxy_key(project, groups, 0, None)


def test_hidden_graphics_on_block_base(project, monkeypatch, tmp_path):
    from app import block_overlays, render, scene_builder
    s = project.slides[0]
    s.cues['blocks'] = [dict(block='number_slam', vars={'value':42})]
    s.overlays = [dict(id='g', block_id='lower_third_panel', vars={}, at=0, dur=2)]
    rendered = []
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw: rendered.append(a[1]))
    monkeypatch.setattr(block_overlays, 'compose', Mock(side_effect=AssertionError('hidden graphics')))
    render._render_segment(project, [(s, 3)], 4, 0, tmp_path/'out.mp4',
                           size=(480,270), fps=15, hide=frozenset({'graphics'}))
    assert rendered == ['_blocks/number_slam/block.html']
    assert s.overlays[0]['id'] == 'g'

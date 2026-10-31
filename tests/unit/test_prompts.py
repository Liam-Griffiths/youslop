"""Planner contracts, checked offline against synthetic project data."""
from pathlib import Path

import pytest

from app import cuts, script_gen, store

GOLDEN = Path(__file__).resolve().parents[1] / 'golden' / 'cues_flameboat.txt'


def test_cues_golden(project, request):
    project.style.format = 'flameboat'
    actual = script_gen._cues_prompt(project, cuts.flameboat, project.slides, '') + '\n'
    # Initial reference: T1.3 adds FrameSpec house rules and generated pacing.
    if request.config.getoption('--update-goldens'):
        GOLDEN.write_text(actual)
    assert actual == GOLDEN.read_text()
    assert 'per word' in actual
    for name in project.frame.banned:
        assert name in actual


@pytest.mark.parametrize('module', cuts.MODULES, ids=lambda m: m.KEY)
def test_cut_frame_overrides(project, module):
    project.style.format = module.KEY
    project.frame.shot_avg_max_s = 2.7
    project.frame.montage_cut_max_s = 0.6
    prompt = script_gen._cues_prompt(project, module, project.slides, '')
    assert module.PLAN + '\n' + script_gen._frame_text(project) in prompt
    assert '1.8 to 2.7 seconds' in prompt
    assert '0.13 to 0.6 seconds' in prompt
    if module.KEY == 'flameboat':
        assert 'every 5-10 spoken words' in prompt
        assert 'longer than 2.7 seconds' in prompt
        assert '4 seconds' not in prompt
    else:
        assert module.PACE == {}


def hook_outline(payoff='Resolution'):
    return {'sections': [{'heading': 'Opening'}, {'heading': 'Discovery'},
                         {'heading': 'Resolution'}],
            'hook': {'muted_image': 'A cracked clock', 'first_line': 'The clock stopped.',
                     'open_loops': [{'question': 'Why did it stop?',
                                     'plant_beat': 'Opening', 'payoff_beat': payoff}]}}


def test_fresh_test_outline_preserves_hook(project, monkeypatch):
    project.test = True
    project.target_minutes = 1
    project.research = {}
    prompts = []

    def complete(prompt, **kwargs):
        prompts.append(prompt)
        return {'outline': hook_outline()}

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    project.outline = script_gen.build_outline(project)
    assert project.outline['hook'] == hook_outline()['hook']
    assert script_gen.check_hook(project.outline) == []
    store.save(project)
    assert store.load(project.id).outline['hook'] == project.outline['hook']
    prompt, = prompts
    assert script_gen._frame_text(project) in prompt
    for text in ('sound off', 'first spoken word', 'at most one main loop',
                 'before any call to action', 'sections[*].heading', 'exactly 1 main'):
        assert text in prompt


@pytest.mark.parametrize('payoff', [' Resolution ', 'rEsOlUtIoN'])
def test_payoff_heading_matching(payoff):
    assert script_gen.check_hook(hook_outline(payoff)) == []


@pytest.mark.parametrize('payoff', ['Missing', ''])
@pytest.mark.parametrize('with_research', [False, True])
def test_hook_check_with_and_without_dossier(project, monkeypatch, payoff, with_research):
    project.outline = hook_outline(payoff)
    project.research = {'facts': [{'claim': 'The clock stopped.'}]} if with_research else {}
    calls = []

    def complete(*args, **kwargs):
        calls.append(args)
        return [{'n': 1, 'claim': 'Unsupported date', 'issue': 'Not in dossier',
                 'severity': 'low'}]

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    flags = script_gen.verify_script(project)
    assert len(flags) == (2 if with_research else 1)
    assert ('does not name an existing section heading' in flags[-1]['issue'])
    assert flags[-1]['claim'] == 'Why did it stop?'
    assert bool(calls) == with_research
    project.slides = []
    assert script_gen.verify_script(project) == script_gen.check_hook(project.outline)


@pytest.mark.parametrize('raw', [{}, {'hook': None}, {'hook': {'open_loops': 'bad'}},
                               {'hook': {'open_loops': [None, 'bad']}}])
def test_missing_or_malformed_hook(raw):
    assert script_gen._normalise_hook(raw) == {
        'muted_image': '', 'first_line': '', 'open_loops': []}
    assert script_gen.check_hook(raw) == []


def test_nested_hook_bounds():
    raw = [{'outline': {'hook': {'muted_image': 'x' * 400,
                                'first_line': 'x' * 400,
                                'open_loops': [{'question': 'x' * 250}] * 5}}}]
    hook = script_gen._normalise_hook(raw)
    assert len(hook['muted_image']) == len(hook['first_line']) == 300
    assert len(hook['open_loops']) == 3
    assert len(hook['open_loops'][0]['question']) == 200


def test_other_prompt_injections(project, monkeypatch):
    prompts = []

    def complete(prompt, **kwargs):
        prompts.append(prompt)
        if prompt.startswith('Rewrite'):
            return {'text': 'Rewritten words.'}
        return []

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    project.outline = hook_outline()
    script_gen._write_section(project, project.outline, 0)
    script_gen.plan_visuals(project, project.slides)
    assert script_gen.rewrite_slide(project, project.slides[0], '') == 'Rewritten words.'
    assert len(prompts) == 3
    assert all(script_gen._frame_text(project) in prompt for prompt in prompts)
    assert 'HOOK PLAN' in prompts[0]


def test_plan_cues_uses_prompt_builder(project, monkeypatch):
    project.style.format = 'flameboat'
    for slide in project.slides:
        slide.cues = {}
    prompts = []

    def complete(prompt, **kwargs):
        prompts.append(prompt)
        return [{'n': 1, 'cues': [{'kind': 'image', 'on': 'Opening words'}]}]

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    expected = script_gen._cues_prompt(project, cuts.flameboat, project.slides, '')
    script_gen.plan_cues(project, project.slides)
    assert prompts == [expected]
    assert project.slides[0].cues['flameboat'][0]['kind'] == 'image'


def test_check_hook_checks_every_loop_without_truncating_headings():
    outline = hook_outline()
    outline['hook']['open_loops'] *= 4
    outline['hook']['open_loops'][-1] = {
        'question': 'Unpaid fourth loop', 'payoff_beat': 'Resolution' + 'x' * 80}
    flags = script_gen.check_hook(outline)
    assert len(flags) == 1
    assert flags[0]['claim'] == 'Unpaid fourth loop'

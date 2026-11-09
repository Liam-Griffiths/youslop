"""Section continuity and recovery, with all model responses supplied offline."""
from copy import deepcopy
import threading

import pytest

from app import llm, script_gen
from app.schema import Project


@pytest.fixture
def script():
    return Project(id='sequential-sections', idea='Synthetic story'), {
        'sections': [{'heading': f'Beat {i}', 'kind': 'main', 'words': 55}
                     for i in range(3)],
        'hook': {'first_line': 'An opening line.'},
    }


def paragraph(i):
    return {'text': f'Unique narration {i}.', 'visual': f'Picture {i}',
            'kind': 'main', 'beat': f'Beat {i}'}


@pytest.mark.parametrize('backend', ['lmstudio', 'ollama'])
def test_local_order_and_prior_narration(monkeypatch, script, backend):
    project, outline = script
    monkeypatch.setattr(llm, 'resolve_backend', lambda: backend)
    prompts, checkpoints, updates = [], [], []

    def complete(prompt, **kwargs):
        i = len(prompts)
        prompts.append(prompt)
        assert f'>>> WRITING NOW: "Beat {i}"' in prompt
        assert len(checkpoints) == i
        return [paragraph(i)]

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    slides = script_gen.write_script(project, outline, updates.append,
                                    lambda: checkpoints.append(deepcopy(project.draft)))
    assert [s.narration for s in slides] == [paragraph(i)['text'] for i in range(3)]
    assert 'ALREADY NARRATED' not in prompts[0]
    for i in (1, 2):
        prior = prompts[i].split('ALREADY NARRATED', 1)[1]
        hook = script_gen._hook_for_section(outline['hook'], outline['sections'][i])
        assert prompts[i].index(hook) < prompts[i].index('ALREADY NARRATED')
        for earlier in range(i):
            assert paragraph(earlier)['text'] in prior
        assert paragraph(i)['text'] not in prior
    assert len(checkpoints) == 3
    assert len([m for m in updates if m.startswith('Section ')]) == 3


@pytest.mark.parametrize('backend,sequential,enabled', [
    ('cli', None, True), ('lmstudio', False, True), ('lmstudio', None, False),
])
def test_parallel_prompts_and_concurrency(monkeypatch, script, backend, sequential, enabled):
    project, outline = script
    monkeypatch.setattr(llm, 'resolve_backend', lambda: backend)
    monkeypatch.setattr(script_gen, 'SEQUENTIAL_LOCAL', enabled)
    barrier = threading.Barrier(3)

    def complete(prompt, **kwargs):
        assert 'ALREADY NARRATED' not in prompt
        barrier.wait(timeout=2)
        i = next(i for i in range(3) if f'>>> WRITING NOW: "Beat {i}"' in prompt)
        return [paragraph(i)]

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    slides = script_gen.write_script(project, outline, sequential=sequential)
    assert [s.narration for s in slides] == [paragraph(i)['text'] for i in range(3)]


@pytest.mark.parametrize('sequential', [True, False])
def test_failure_banks_successes_and_resume_skips_them(monkeypatch, script, sequential):
    project, outline = script
    calls, checkpoints, updates = [], [], []
    failure = RuntimeError('synthetic section failure')

    def complete(prompt, **kwargs):
        i = next(i for i in range(3) if f'>>> WRITING NOW: "Beat {i}"' in prompt)
        calls.append(i)
        if i == 1:
            raise failure
        return [paragraph(i)]

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    with pytest.raises(RuntimeError) as caught:
        script_gen.write_script(project, outline, updates.append,
                                lambda: checkpoints.append(deepcopy(project.draft)),
                                sequential=sequential)
    assert caught.value is failure
    assert sorted(calls) == [0, 1, 2]
    assert set(project.draft['sections']) == {'0', '2'}
    assert len(checkpoints) == 2
    assert any('failed: synthetic section failure' in m for m in updates)

    def resume(prompt, **kwargs):
        assert '>>> WRITING NOW: "Beat 1"' in prompt
        assert (paragraph(0)['text'] in prompt) is sequential
        assert paragraph(2)['text'] not in prompt
        return [paragraph(1)]

    monkeypatch.setattr(script_gen, 'complete_json', resume)
    slides = script_gen.write_script(project, outline, updates.append, sequential=sequential)
    assert [s.narration for s in slides] == [paragraph(i)['text'] for i in range(3)]
    assert 'Resuming: 2 of 3 sections already written' in updates
    monkeypatch.setattr(script_gen, 'complete_json', lambda *a, **k: pytest.fail('Rewrote banked section'))
    resumed = script_gen.write_script(project, outline, sequential=sequential)
    assert [s.narration for s in resumed] == [s.narration for s in slides]


def test_prior_narration_keeps_latest_1200_words(monkeypatch, script):
    project, outline = script
    prompts = []
    monkeypatch.setattr(script_gen, 'complete_json',
                        lambda prompt, **kwargs: prompts.append(prompt) or [paragraph(2)])
    script_gen._write_section(project, outline, 2,
                              ['discard ' * 100, ' '.join(f'word{i}' for i in range(1200))])
    prior = prompts[0].split('ALREADY NARRATED', 1)[1].split('\n', 1)[1].split('\n\n', 1)[0]
    assert prior.split() == [f'word{i}' for i in range(1200)]

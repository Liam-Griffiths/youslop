"""Consistency model replies are synthetic; Check itself stays model-free."""
import pytest

from app import check, main, script_gen, store
from app.schema import Project, Slide


@pytest.fixture
def episode():
    return Project(id='consistency-fixture', idea='Tunguska', outline={'era': '1908'},
                   slides=[Slide(id='granite', narration=(
                       'On a clear morning in June 1908, the explosion flattened '
                       'eighty million trees overnight.'), visual_note=(
                       'An archival photograph of the fireball crossing the dawn sky.'))])


def test_reply_becomes_findings_and_survives_save(episode, monkeypatch):
    replies = [
        {'n': 1, 'kind': 'contradiction', 'claim': '“clear morning” / “overnight”',
         'issue': 'The same event cannot occur both in the morning and overnight.',
         'severity': 'low'},
        {'n': 1, 'kind': 'impossible_visual', 'claim': episode.slides[0].visual_note,
         'issue': "Use an artist's impression; nobody photographed the fireball.",
         'severity': 'high'},
    ]
    monkeypatch.setattr(script_gen, 'complete_json', lambda *a, **kw: replies)
    episode.research['flags'] = script_gen.consistency_check(episode)
    assert [f['severity'] for f in episode.research['flags']] == ['high', 'low']
    store.save(episode)
    monkeypatch.setattr(script_gen, 'complete_json',
                        lambda *a, **kw: pytest.fail('Check must not call a model'))
    findings = check.script(store.load(episode.id))['findings']
    assert [(f['code'], f['level'], f['slide_id']) for f in findings] == [
        ('script.contradiction', 'P1', 'granite'),
        ('script.impossible_visual', 'P2', 'granite')]
    assert 'clear morning' in findings[0]['msg'] and 'overnight' in findings[0]['msg']
    assert "artist's impression" in findings[1]['msg']


@pytest.mark.parametrize('item', [
    None, [], 'bad', {},
    {'n': 0}, {'n': 2}, {'n': -1}, {'n': 'bad'}, {'n': '2'},
    {'n': 1.5}, {'n': True}, {'n': None},
    {'claim': None}, {'claim': ''}, {'claim': '  '}, {'claim': ['morning']},
    {'issue': None}, {'issue': ''}, {'kind': 'style'}, {'kind': ['contradiction']},
])
def test_malformed_items_dropped(episode, monkeypatch, item):
    reply = {'n': 1, 'kind': 'contradiction', 'claim': 'morning / overnight',
             'issue': 'These times disagree.'}
    if isinstance(item, dict):
        reply.update(item)
        if not item:
            reply.pop('claim')
    else:
        reply = item
    monkeypatch.setattr(script_gen, 'complete_json', lambda *a, **kw: [reply])
    assert script_gen.consistency_check(episode) == []


def test_empty_reply_prompt_and_empty_project(episode, monkeypatch):
    calls = []
    episode.slides.append(Slide(id='second', narration='No crater was found.',
                                visual_note='A later photograph of the site.'))

    def complete(prompt, **kwargs):
        calls.append(prompt)
        assert kwargs['model'] == script_gen.MODEL_UTILITY
        assert kwargs['require']([])
        return []

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    episode.research['flags'] = script_gen.consistency_check(episode)
    assert check.script(episode)['findings'] == []
    prompt, = calls
    assert 'ERA: 1908' in prompt
    for slide in episode.slides:
        assert slide.narration in prompt and slide.visual_note in prompt
    episode.slides = []
    assert script_gen.consistency_check(episode) == []
    assert len(calls) == 1


def test_cross_batch_context_and_numbering(episode, monkeypatch):
    episode.slides = [Slide(id=f'p{i}', narration=f'Statement {i}.',
                            visual_note=f'Picture {i}.') for i in range(1, 26)]
    prompts = []

    def complete(prompt, **kwargs):
        prompts.append(prompt)
        for slide in episode.slides:
            assert slide.narration in prompt
        # Only the batch containing paragraph 25 may attach this flag.
        return [{'n': 25, 'kind': 'contradiction', 'claim': 'Statement 1 / Statement 25',
                 'issue': 'They disagree.'}]

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    flags = script_gen.consistency_check(episode)
    assert len(prompts) == 3
    assert len(flags) == 1 and flags[0]['slide_id'] == 'p25'
    for slide in episode.slides:
        assert sum(slide.visual_note in prompt for prompt in prompts) == 1


def test_generation_runs_checks_in_order(episode, monkeypatch):
    episode.research = {'facts': [{'claim': 'An explosion occurred in 1908.'}]}
    monkeypatch.setattr(script_gen, 'brief', lambda *a: episode.outline)
    monkeypatch.setattr(script_gen, 'write_script', lambda *a: episode.slides)
    for name in ('plan_visuals', 'plan_boards', 'plan_cues', '_plan_style_slides'):
        monkeypatch.setattr(script_gen, name, lambda *a: None)
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            assert 'RESEARCHED FACTS' in prompt
            return [{'n': 1, 'claim': 'June', 'issue': 'Verify date', 'severity': 'low'}]
        assert 'PARAGRAPHS TO CHECK' in prompt
        return [{'n': 1, 'kind': 'contradiction', 'claim': 'morning / overnight',
                 'issue': 'Times disagree'}]

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    script_gen.generate(episode)
    assert len(calls) == 2
    assert [f['code'] for f in check.script(episode)['findings']] == [
        'script_claim', 'script.contradiction']


def test_recheck_replaces_flags_and_preserves_concurrent_edits(episode, monkeypatch):
    episode.research = {'facts': [{'claim': 'An explosion occurred in 1908.'}],
                        'flags': [{'kind': 'contradiction', 'claim': 'Old warning'}]}
    store.save(episode)
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        fresh = store.load(episode.id)
        fresh.subtitle = 'Edited during check'
        store.save(fresh)
        return []

    monkeypatch.setattr(script_gen, 'complete_json', complete)
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: fn(lambda m: None))
    assert main.factcheck(episode.id) == {'job': {'flags': 0}}
    assert len(calls) == 2 and 'RESEARCHED FACTS' in calls[0]
    fresh = store.load(episode.id)
    assert fresh.research['flags'] == []
    assert fresh.subtitle == 'Edited during check'


def test_string_paragraph_numbers_are_accepted(monkeypatch):
    from app import script_gen
    from app.schema import Slide
    from types import SimpleNamespace
    slides = [Slide(narration="It was morning. It happened overnight.")]
    project = SimpleNamespace(slides=slides, outline={"era": "1908"})
    monkeypatch.setattr(script_gen, "complete_json", lambda *a, **k: [
        {"n": "1", "kind": "contradiction", "claim": "morning / overnight", "issue": "Both cannot be true."}])
    flags = script_gen.consistency_check(project)
    assert len(flags) == 1 and flags[0]["slide_id"] == slides[0].id

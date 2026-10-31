"""Ask packets/proposals use temporary data, tiny synthetic frames and no model."""
import json

import pytest
from PIL import Image

from app import cli, llm, main, review, store, storyboard


@pytest.fixture
def saved(project, monkeypatch):
    store.save(project)

    def grab(p, t, out, **kwargs):
        assert kwargs['size'] == (480, 270)
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (16, 9)).save(out)
        return out

    monkeypatch.setattr(review, 'grab', grab)
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: pytest.fail('Unexpected LLM call'))
    return project


def test_sections_frame_schema_and_findings(saved, monkeypatch):
    findings = [dict(t=0, msg='here'), dict(t=2, msg='edge'), dict(t=3, msg='far')]
    monkeypatch.setattr(review.check, 'run', lambda p: {'findings': findings})
    review._write_notes(saved.id, {'notes': [dict(t=1, problem='review here')]})
    data = review.packet(saved, 0, {}, 'shorter title')
    text = data['prompt']
    assert [line for line in text.splitlines() if line.startswith('## ')] == [
        '## Intent', '## Where', '## Frame', '## Findings here',
        '## Doctrine', '## Context', '## Reply format']
    assert 'here' in text and 'edge' in text and 'review here' in text
    assert '"far"' not in text
    assert 'paragraph s1' in text and saved.slides[0].narration in text
    assert 'Next: ' in text and saved.frame.prompt_block(saved.style.format) in text
    path = (store.project_dir(saved.id) / 'review/ask_0.00.png').resolve()
    assert str(path) in text and path.read_bytes() == data['image_png']
    fields = data['patch_schema']['properties']['paragraphs']['additionalProperties']['properties']
    assert set(fields) == storyboard.EDITABLE
    assert f'app.cli apply {saved.id} patch.json' in text


def test_trim_context_then_findings(saved, monkeypatch):
    saved.slides[0].narration = 'word ' * 10000
    findings = [dict(t=i / 10, msg='finding ' * 400) for i in range(20)]
    monkeypatch.setattr(review.check, 'run', lambda p: {'findings': findings})
    data = review.packet(saved, 0, {}, 'shorten')
    assert len(data['prompt']) <= 12000
    assert '[Context trimmed]' in data['prompt']
    assert data['prompt'].endswith(json.dumps(data['patch_schema']))


def test_copy_never_applies_or_calls_model(saved, monkeypatch):
    monkeypatch.setattr(storyboard, 'apply', lambda *a: pytest.fail('Applied in copy mode'))
    result = main.agent_ask(saved.id, dict(t=0, intent='shorten', mode='copy'))
    assert result['image'].startswith('data:image/png;base64,')
    assert '## Intent' in result['prompt']


def test_dry_diff_apply_and_preserve_audio(saved, monkeypatch):
    saved.slides[0].take['duration'] = 50
    store.save(saved)
    original = saved.to_dict()
    calls = []

    def fake(prompt, **kwargs):
        assert not store.lock_for(saved.id)._is_owned()
        assert kwargs['images'][0].startswith(b'\x89PNG')
        calls.append(prompt)
        return {'paragraphs': {'s1': {'title': 'Short'}}}

    monkeypatch.setattr(llm, 'complete_json', fake)
    proposal = main.agent_ask(saved.id, dict(t=42, intent='make this title shorter'))
    assert proposal['diff'] == [dict(id='s1', field='title', old=saved.slides[0].title, new='Short')]
    assert store.load(saved.id).to_dict() == original
    assert main.agent_apply(saved.id, proposal)['applied']
    current = store.load(saved.id)
    assert current.slides[0].title == 'Short'
    assert current.slides[0].take == saved.slides[0].take
    assert current.slides[0].takes == saved.slides[0].takes
    assert len(calls) == 1
    with pytest.raises(main.HTTPException, match='changed'):
        main.agent_apply(saved.id, proposal)


def test_diff_includes_raw_cues_and_picture_mode(saved, monkeypatch):
    patch = {'paragraphs': {'s1': {'picture_mode': 'new',
                                 'cues': {'loudmouth': [{'kind': 'shout', 'text': 'New'}]}}}}
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: patch)
    result = review.ask(saved, 0, {}, 'change cues')
    assert {d['field'] for d in result['diff']} == {'cues', 'picture_mode'}


@pytest.mark.parametrize('patch', ['free text', {'paragraphs': {'s1': {'unknown': 'x'}}},
                                  {'paragraphs': {'s1': {'title': {}}}},
                                  {'paragraphs': {'s1': {'cues': 'bad'}}},
                                  {'paragraphs': {'missing': {'title': 'x'}}}])
def test_invalid_reply_does_not_save(saved, monkeypatch, patch):
    before = saved.to_dict()
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: patch)
    with pytest.raises(main.HTTPException):
        main.agent_ask(saved.id, dict(t=0, intent='shorten'))
    assert store.load(saved.id).to_dict() == before


@pytest.mark.parametrize('payload', [dict(t=-1), dict(t=float('nan')), dict(mode='bad'),
                                     dict(selection={'slide_id': 'missing'})])
def test_invalid_request(saved, payload):
    with pytest.raises(main.HTTPException):
        main.agent_ask(saved.id, dict(t=0, intent='shorten') | payload)


def test_concurrent_edit_rejected(saved, monkeypatch):
    def fake(*a, **k):
        current = store.load(saved.id)
        current.slides[0].title = 'Manual edit'
        store.save(current)
        return {'paragraphs': {'s1': {'title': 'Agent title'}}}
    monkeypatch.setattr(llm, 'complete_json', fake)
    proposal = review.ask(saved, 0, {}, 'shorten')
    with pytest.raises(ValueError, match='changed'):
        review.apply_ask(saved.id, proposal)
    assert store.load(saved.id).slides[0].title == 'Manual edit'


def test_inactive_cues_concurrent_edit_rejected(saved, monkeypatch):
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: {'paragraphs': {'s1': {'title': 'x'}}})
    proposal = review.ask(saved, 0, {}, 'shorten')
    current = store.load(saved.id)
    current.slides[0].cues = {'loudmouth': [{'kind': 'shout', 'text': 'Manual'}]}
    store.save(current)
    with pytest.raises(ValueError, match='changed'):
        review.apply_ask(saved.id, proposal)


def test_cli_copy_and_apply(saved, monkeypatch, capsys):
    assert cli.main(['ask', saved.id, '0', 'shorter title', '--copy']) == 0
    assert capsys.readouterr().out.startswith('## Intent\n')
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: {'paragraphs': {'s1': {'title': 'CLI'}}})
    assert cli.main(['ask', saved.id, '0', 'shorter title']) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)['paragraphs']['s1']['title'] == 'CLI'
    assert json.loads(out.err)[0]['new'] == 'CLI'
    assert store.load(saved.id).slides[0].title != 'CLI'
    assert cli.main(['ask', saved.id, '0', 'shorter title', '--apply']) == 0
    capsys.readouterr()
    assert store.load(saved.id).slides[0].title == 'CLI'

"""Tiny thumbnails and mocked vision only; no source media or network."""
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app import footage, footage_labels as labels, llm


@pytest.fixture
def shoot(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    s = footage.Shoot('s1', files=[footage.SourceFile('f1')], vocabulary=['Lobby', 'Main entrance'])
    root = footage.shoot_dir(s.id)
    root.mkdir(parents=True)
    for i in range(23):
        path = root / f'{i}.jpg'
        Image.new('RGB', (160, 90), (i * 10, 30, 20)).save(path)
        s.clips.append(footage.Clip(f'c{i}', 'f1', i * 2, i * 2 + 2,
                                   [path.name] * 3, labels=['Owner tag']))
    footage._save(s)
    return s


def answer(count, place='Lobby'):
    return [dict(tile=i, **{f: (place if f == 'place' else 'wide' if f == 'shot_size' else '')
                           for f in labels.FIELDS}) for i in range(1, count + 1)]


def test_budget_confirmation_batches_cache_and_schema(shoot, monkeypatch):
    calls, approved = [], []

    def complete(prompt, **kwargs):
        assert approved
        assert 'Lobby' in prompt and 'Main entrance' in prompt
        with Image.open(io.BytesIO(kwargs['images'][0])) as image:
            assert image.width == 640 and image.height <= 570
        count = 20 if not calls else 3
        reply = answer(count)[::-1]  # mapping must use tile number, not response order
        assert kwargs['require'](reply)
        assert kwargs['retries'] == 0
        calls.append(count)
        return reply

    monkeypatch.setattr(llm, 'complete_json', complete)
    budget = labels.estimate(shoot.id)
    assert budget['calls'] == 2 and budget['uncached'] == 23
    assert budget['input_tokens'] > 0 and budget['output_tokens'] > 0
    assert labels.run(shoot.id, confirm=lambda b: False)['cancelled']
    assert not calls
    labels.run(shoot.id, confirm=lambda b: approved.append(b) or True)
    assert calls == [20, 3] and approved == [budget]
    saved = footage.load(shoot.id)
    assert all(c.auto_labels['place'] == 'Lobby' and 'Owner tag' in c.labels for c in saved.clips)
    assert all('Lobby' in c.labels for c in saved.clips)
    assert saved.vocabulary == shoot.vocabulary
    labels.run(shoot.id, confirm=lambda b: b['calls'] == 0)
    assert calls == [20, 3]
    assert footage.Clip.from_dict({'id': 'old', 'file': 'f1', 'future': True}).auto_labels == {}
    assert footage.Shoot.from_dict({'id': 'old', 'future': True}).vocabulary == []


def test_interruption_resumes_completed_batches(shoot, monkeypatch):
    calls = []

    def interrupted(prompt, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise llm.LLMError('interrupted')
        return answer(20)

    monkeypatch.setattr(llm, 'complete_json', interrupted)
    with pytest.raises(llm.LLMError, match='interrupted'):
        labels.run(shoot.id, confirm=lambda b: True)
    assert sum(bool(c.auto_labels) for c in footage.load(shoot.id).clips) == 20
    assert labels.estimate(shoot.id)['uncached'] == 3
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: answer(3))
    labels.run(shoot.id, confirm=lambda b: True)
    assert all(c.auto_labels for c in footage.load(shoot.id).clips)


@pytest.mark.parametrize('bad', [answer(20, 'invented'), answer(19), answer(20)[:-1] + [answer(20)[0]]])
def test_invalid_reply_not_persisted(shoot, monkeypatch, bad):
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: bad)
    with pytest.raises(llm.LLMError, match='Invalid footage labels'):
        labels.run(shoot.id, confirm=lambda b: True)
    assert not any(c.auto_labels for c in footage.load(shoot.id).clips)
    assert labels.estimate(shoot.id)['uncached'] == 23


def test_vocabulary_and_clip_hash_invalidation(shoot, monkeypatch):
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: answer(20 if 'through 20' in a[0] else 3))
    labels.run(shoot.id, confirm=lambda b: True)
    root = footage.shoot_dir(shoot.id)
    Image.new('RGB', (160, 90), 'white').save(root / '0.jpg')
    assert labels.estimate(shoot.id)['uncached'] == 1
    current = footage.load(shoot.id)
    current.clips[1].out_s += 1
    footage._save(current)
    assert labels.estimate(shoot.id)['uncached'] == 2
    labels.set_vocabulary(shoot.id, ['Courtyard', 'Courtyard'])
    assert footage.load(shoot.id).vocabulary == ['Courtyard']
    assert labels.estimate(shoot.id)['uncached'] == 23
    with pytest.raises(ValueError):
        labels.set_vocabulary(shoot.id, [''])


def test_cli_shows_budget_before_confirmation_and_call(shoot, monkeypatch, capsys):
    from app import cli
    monkeypatch.setattr(cli, '_guard_write', lambda: None)

    def confirm(prompt):
        assert 'Estimated token budget:' in capsys.readouterr().err
        return 'n'

    monkeypatch.setattr('builtins.input', confirm)
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: pytest.fail('Declined run called model'))
    cli.cmd_footage(SimpleNamespace(footage_cmd='labels', shoot=shoot.id, place=None, yes=False))
    assert '"cancelled": true' in capsys.readouterr().out


def test_cache_restores_suggestions_by_hash_not_clip_id(shoot, monkeypatch):
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: answer(20 if 'through 20' in a[0] else 3))
    labels.run(shoot.id, confirm=lambda b: True)
    current = footage.load(shoot.id)
    current.clips[0].id = 'replacement'
    current.clips[0].auto_labels = {}
    current.clips[0].labels = ['Owner tag']
    footage._save(current)
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: pytest.fail('Cache miss'))
    labels.run(shoot.id, confirm=lambda b: b['calls'] == 0)
    assert footage.load(shoot.id).clips[0].auto_labels['place'] == 'Lobby'


def test_missing_or_unsafe_thumbnail_stops_before_model(shoot, monkeypatch):
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: pytest.fail('Invalid image called model'))
    current = footage.load(shoot.id)
    current.clips[0].thumbs = []
    footage._save(current)
    with pytest.raises(ValueError, match='middle thumbnail'):
        labels.run(shoot.id, confirm=lambda b: True)
    current.clips[0].thumbs = ['0.jpg', '../outside.jpg']
    footage._save(current)
    with pytest.raises(ValueError):
        labels.run(shoot.id, confirm=lambda b: True)

"""Vision review is exercised with synthetic images and a fake model only."""
import io
import json

import pytest
from PIL import Image

from app import cli, llm, main, review, store, storyboard


def rows(count=40):
    return [dict(t=i * 1.5, why='chapter' if i > 3 else 'hook',
                 slide_id='s1', path=f'review/snaps/{i}.png') for i in range(count)]


def test_selection_budget_and_mandatory():
    snaps = rows()
    findings = [dict(level='P0', t=30, code='missing'),
                *[dict(level='P1', t=i*1.5, code='busy') for i in range(4, 30)]]
    selected = review.select(snaps, findings)
    assert len(selected) == 12
    assert {0, 1.5, 3, 30, 58.5} <= {r['t'] for r in selected}
    assert not any('chapter' == r['why'].split(' · ')[0] for r in selected)
    assert review.select(snaps, [], 'full') == snaps
    assert review.select([], []) == []
    close = [dict(snaps[0], t=.2), *snaps]
    assert len([r for r in review.select(close, []) if r['t'] < .5]) == 1
    excessive = [dict(level='P0', t=r['t'], code='missing') for r in snaps]
    with pytest.raises(ValueError, match='--full'):
        review.select(snaps, excessive)
    with pytest.raises(ValueError, match='mode'):
        review.select(snaps, [], 'other')


@pytest.fixture
def setup_review(project, monkeypatch, tmp_path):
    project.id = 'pvision_' + tmp_path.name
    store.save(project)
    snaps = rows(18)
    root = store.project_dir(project.id)
    image = io.BytesIO()
    Image.new('RGB', (1280, 720), 'white').save(image, format='PNG')
    for r in snaps:
        path = root / r['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image.getvalue())
    (root / 'review/snaps.json').write_text(json.dumps(dict(
        storyboard_hash=review._storyboard_hash(project), snaps=snaps)))
    monkeypatch.setattr(review.check, 'run', lambda p: dict(
        counts=dict(P0=0, P1=1, P2=0), findings=[dict(level='P1', t=6, code='busy')]))
    calls = []
    def fake(prompt, **kwargs):
        assert kwargs['require']({'notes': []})
        assert not kwargs['require']([])
        assert kwargs['model'] == llm.MODEL_UTILITY
        assert 'sound off' in kwargs['system']
        assert 'rejected_looks' in prompt and 'rules' in prompt
        for data in kwargs['images']:
            with Image.open(io.BytesIO(data)) as image:
                assert image.size == (640, 360) and image.format == 'JPEG'
        calls.append(kwargs)
        # First image caption includes an exact numeric seconds t.
        t = float(prompt.split('(t=')[1].split(',')[0])
        # Simulate a concurrent UI save while the slow model call is running.
        current = store.load(project.id)
        current.subtitle = 'Concurrent subtitle'
        store.save(current)
        return dict(score=9, notes=[dict(t=t, severity='P0' if len(calls) == 1 else 'P2',
                    see='A small title.', problem='Hard to read.', rating=3,
                    fix=dict(kind='text', slide_id='s1', hint='Enlarge title', stars=4)),
                    dict(t=t, severity='P1', see='A title.', problem='Crowded.',
                         fix=dict(kind='text', slide_id='s1', hint='Shorten title'))],
                    weakest=dict(t=t, why='Small title', grade='B'))
    monkeypatch.setattr(llm, 'complete_json', fake)
    return project, root, snaps, calls


@pytest.mark.parametrize('mode,expected', [('targeted', [12]), ('full', [16, 2])])
def test_run_batches_files_and_reload(setup_review, mode, expected, caplog):
    project, root, snaps, calls = setup_review
    messages = []
    result = review.run(project, messages.append, mode=mode)
    assert [len(c['images']) for c in calls] == expected
    assert result['frames_sent'] == sum(expected)
    assert result['snapshots_not_sent'] == len(snaps) - sum(expected)
    assert len(result['notes']) == 2 * len(expected)
    assert result['weakest']['t'] == 0
    assert 'Dropped review score key' in caplog.text
    assert 'score' not in json.dumps(result) and 'stars' not in json.dumps(result)
    assert json.loads((root / 'review/notes.json').read_text()) == result
    text = (root / 'review/REVIEW.md').read_text()
    assert [line for line in text.splitlines() if line.startswith('## ')] == [
        '## What was looked at', '## Choices made', '## Measured', '## Looked at',
        '## Weakest shot', '## Warnings kept']
    current = store.load(project.id)
    assert current.subtitle == 'Concurrent subtitle'
    assert current.review['p0'] == 1 and current.review['p2'] == len(expected)-1
    assert current.review['p1'] == len(expected)
    assert current.review['path'] == 'review/REVIEW.md'
    assert project.review == {}  # summary is applied to the reloaded project
    assert 'frames:' in messages[0]
    assert review.read_snapshots(project.id) == snaps


def test_freshness_and_kept_warnings(setup_review, monkeypatch):
    project, root, snaps, calls = setup_review
    built = []
    monkeypatch.setattr(review, 'snapshots', lambda p: built.append(True) or snaps)
    project.updated_at += 10
    review.run(project)
    assert not built
    project.slides[0].narration += ' Changed.'
    old = dict(notes=[dict(dismissed=True, problem='Intentional')], warnings_kept=[])
    (root / 'review/notes.json').write_text(json.dumps(old))
    result = review.run(project)
    assert built == [True] and result['warnings_kept'] == old['notes']
    assert 'Intentional' in (root / 'review/REVIEW.md').read_text()
    (root / 'review/snaps.json').write_text(json.dumps(snaps))
    assert review.read_snapshots(project.id) == snaps
    review.run(project)
    assert len(built) == 2  # legacy list is readable but has no freshness hash


def test_cli_api_and_validation(setup_review, monkeypatch, capsys):
    project, root, snaps, calls = setup_review
    monkeypatch.setattr(cli, '_guard_write', lambda: None)
    assert cli.main(['review', project.id, '--json']) == 1
    assert json.loads(capsys.readouterr().out)['mode'] == 'targeted'
    # Second call's fake result is P2: verify the successful CLI exit too.
    assert cli.main(['review', project.id, '--full', '--json']) == 0
    full = json.loads(capsys.readouterr().out)
    assert full['frames_sent'] == 18
    assert full['weakest']['t'] == 24  # Last batch wins when there is no P0.
    assert main.get_review(project.id)['mode'] == 'full'
    started = []
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: started.append(fn) or 'job1')
    assert main.start_review(project.id, {}) == dict(job='job1')
    assert started[0](lambda msg: None)['mode'] == 'targeted'
    with pytest.raises(main.HTTPException) as exc:
        main.start_review(project.id, dict(mode='other'))
    assert exc.value.status_code == 400
    monkeypatch.setattr(cli, '_guard_write', lambda: (_ for _ in ()).throw(ValueError('app is open')))
    assert cli.main(['review', project.id]) == 1
    assert len(calls) == 4

"""Narration lint uses synthetic prose, without models, media or browser work."""
import json

import pytest

from app import check, cli, main, review, store
from app.style_lint import lint, rate, sentences


@pytest.mark.parametrize('text', [
    'He spent most of the winter repairing the roof, which had leaked since the '
    'previous tenants left. It held. By spring the room was dry enough to use '
    'as a workshop, although the floor still needed replacing.',
    'The roof repairs lasted until spring, when the crew returned to finish '
    'the windows along the northern wall. The owner kept every receipt. '
    'By June the workshop could open, although the floor needed another coat '
    'of paint before machinery could be installed. Deliveries began the '
    'following week, a month later than originally planned.',
    'The survey began beside the river, where the crew could unload equipment '
    'without blocking the road. After a week of measurements they moved uphill '
    'to check the ground beneath the proposed route.',
    'Iron, glass, timber, and stone were all available from nearby suppliers.',
    'Dr. Lee measured 3.5 metres of cable before the first test began.',
    '',
])
def test_good_prose(text):
    assert lint(text) == []


@pytest.mark.parametrize(('text', 'kind'), [
    ('He built it. He tested it. He failed.', 'fragment_run'),
    ('He built it. He tested it. He failed.', 'parallel_triplet'),
    ('It was bold, bright, and beautiful.', 'triplet'),
    ('The load was heavy, bulky, and awkward.', 'triplet'),
    ('Elle avance. Elle attend. Elle revient.', 'parallel_triplet'),
    ('The new workshop finally opened!', 'exclamation'),
    ('The new workshop finally opened！', 'exclamation'),
    ('The crew surveyed the ground beside the old railway station. '
     'The workers measured the distance along the disused railway track. '
     'The surveyors checked the alignment against the original route drawings. '
     'The foreman recorded the results inside the small site office.', 'low_spread'),
])
def test_measures(text, kind):
    hits = lint(text)
    assert kind in {h['kind'] for h in hits}
    for hit in hits:
        assert hit['reason'] and hit['sentence'] in text
        assert sentences(text)[hit['sentence_index']] == hit['sentence']


@pytest.mark.parametrize('text', [
    'They had no idea how much the next test would change everything.',
    'Little did she know the first trial was only the beginning.',
    'This was just the start of a remarkable story.',
    'But here’s where things got interesting.',
    "Here's the inside scoop on the discovery.",
    'The inside scoop on the discovery was finally revealed.',
    'Here is where it gets interesting.',
    "Here's the thing about this machine.",
    'What came next would astonish the entire town.',
    'Spoiler alert: the machine was a game changer.',
    "Let's dive into this extraordinary journey.",
])
def test_phrase_families(text):
    assert any(h['kind'] == 'teaser_hype' for h in lint(text))


def test_boundaries_indices_and_short_sentence_exception():
    assert lint('It held.') == []
    assert lint('It held.\n\nIt worked.') == []
    assert not any(h['kind'] == 'low_spread' for h in lint('We arrived. We waited.'))
    text = 'Dr. Lee found 3.5 metres of cable in the original storage room.\n\nHe built it. He tried it.'
    hit, = lint(text)
    assert hit['sentence_index'] == 1 and hit['sentence_indices'] == [1, 2]
    assert sentences('“It held.” Then the crew continued work along the river.') == [
        '“It held.”', 'Then the crew continued work along the river.']
    assert len(sentences('J. R. Smith arrived in the afternoon. He left after dinner.')) == 2


@pytest.mark.parametrize('lengths', [
    [13, 9, 13, 13, 7, 11, 12],  # Before paragraph 1, review's measured lengths.
    [7, 7, 10, 6, 6, 15, 13],  # Before paragraph 3.
    [12, 12, 12, 12, 40],  # Fraction branch, despite a mean above 14.
    [12, 13, 13, 13],  # Mean branch, despite only one sentence <= 12 words.
])
def test_short_rhythm_review_lengths(lengths):
    # Synthetic words preserve the recorded lengths without inventing A/B text.
    paragraph = ' '.join(' '.join(['word'] * n) + '.' for n in lengths)
    prefix = 'The observations were recorded.\n\n'
    hit, = [h for h in lint(prefix + paragraph) if h['kind'] == 'short_rhythm']
    assert hit['sentence_index'] == 1
    assert hit['sentence_indices'] == list(range(1, len(lengths) + 1))
    assert hit['sentence'] == sentences(paragraph)[0]


def test_short_rhythm_before_excerpt():
    text = ('Operators in Europe and North America reported sparks jumping from their equipment. '
            'Some received shocks at their keys. '
            'In some offices, sparks were said to have set paper alight. '
            'Stranger still, some operators disconnected their batteries completely.')
    assert any(h['kind'] == 'short_rhythm' for h in lint(text))


def test_varied_paragraph_with_one_short_sentence():
    text = ('The roof repairs lasted until spring, when the crew returned to finish '
            'the windows along the northern wall. It held. '
            'By June the workshop could open, although the floor needed another coat '
            'of paint before machinery could be installed. Deliveries began the '
            'following week, a month later than the original schedule had allowed.')
    assert lint(text) == []


@pytest.mark.parametrize('lengths', [
    [12, 12, 18],  # Too few sentences.
    [13, 13, 13, 13],  # Mean exactly 13 and no short majority.
    [8, 10, 20, 24, 28],  # Varied paragraph with a short minority.
])
def test_short_rhythm_limits(lengths):
    text = ' '.join(' '.join(['word'] * n) + '.' for n in lengths)
    assert not any(h['kind'] == 'short_rhythm' for h in lint(text))


@pytest.mark.parametrize('opening', [
    'Stranger still', 'Weirder still', 'Even stranger', 'Even stranger still',
    'Even weirder', "But that's not all", 'But that’s not all',
    'But this is not all', 'And then',
])
def test_paragraph_teaser_transitions(opening):
    teaser = f'{opening}, the operators disconnected the batteries.'
    assert any(h['kind'] == 'teaser_hype' for h in lint(teaser))
    assert any(h['kind'] == 'teaser_hype' for h in lint('A report arrived.\n\n' + teaser))
    mid = any(h['kind'] == 'teaser_hype' for h in lint('A report arrived. ' + teaser))
    # Teaser openers count anywhere; "And then" only when it opens a paragraph.
    assert mid == (opening != 'And then')


def test_rate_counts_hits_over_all_sentences():
    bad = 'He built it. He tested it. He failed.'
    good = 'The crew returned to finish the windows along the northern wall.'
    assert rate([bad]) == pytest.approx(200 / 3)
    assert rate(iter([bad, good])) == 50.0
    assert rate(['A heading without punctuation\n\n' + bad]) == 50.0
    assert rate([good, '', '  ']) == 0.0
    assert rate([]) == rate(['', '  ']) == 0.0
    # Separate narration texts cannot create a run or a rhythm warning.
    assert rate(['It held.', 'It worked.']) == 0.0


def test_check_surfaces_and_nonblocking_render_gate(project, monkeypatch, capsys):
    project.slides[1].narration = 'He built it. He tested it. He failed.'
    monkeypatch.setattr('app.stage.browser', lambda: None)
    result = check.run(project)
    findings = [f for f in result['findings'] if f['code'] == 'script.style']
    assert result['ok'] is True and result['counts']['P3'] == len(findings) == 2
    assert sum(result['counts'].values()) == len(result['findings'])
    assert len({review.note_id(f) for f in findings}) == len(findings)
    legacy = dict(findings[0], code='banned_used')
    assert review.note_id(legacy) not in {review.note_id(f) for f in findings}
    assert all(f['level'] == 'P3' and f['slide_id'] == project.slides[1].id
               and f['t'] > 0 and f['fix']['kind'] == 'style' for f in findings)
    assert check.script(project)['counts']['P3'] == 2
    store.save(project)
    first = main.script_check(project.id)
    assert first['counts']['P3'] == 2
    main.dismiss_script_finding(project.id, first['findings'][0]['id'])
    assert main.script_check(project.id)['counts']['P3'] == 1
    monkeypatch.setattr(cli, '_operation', lambda *a: result)
    assert cli.main(['check', project.id]) == 0
    assert 'P3 (2)' in capsys.readouterr().out
    assert cli.main(['check', project.id, '--json']) == 0
    assert json.loads(capsys.readouterr().out)['counts']['P3'] == 2
    monkeypatch.setattr(main, '_load', lambda pid: project)
    monkeypatch.setattr(check, 'run', lambda *a, **kw: result)
    monkeypatch.setattr(main.jobs, 'start', lambda *a: 'synthetic-job')
    assert main.start_render(project.id, {}) == {'job': 'synthetic-job'}

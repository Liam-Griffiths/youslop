"""Hand-made archive regression, entirely offline and without model calls."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from app import check, llm, media
from app.media import providers
from app.media.relevance import concrete_queries, gate, paragraph_queries, rank
from app.schema import MediaCandidate, Project, Slide


@pytest.fixture
def tube(monkeypatch):
    data = json.loads(Path('tests/fixtures/media/tube_mail.json').read_text())
    p = Project(id='ptube', idea='', title=data['title'], outline=data['outline'],
                research=data['research'], slides=[Slide(id=f's{i}', **s)
                    for i, s in enumerate(data['paragraphs'])])
    hits = [MediaCandidate(id=f'c{i}', provider='wikimedia', kind='image',
                          url=f'https://offline.test/{i}.jpg', width=2000, height=1500, **h)
            for i, h in enumerate(data['hits'])]
    asked = []
    class Archive:
        name, kinds = 'wikimedia', ('image',)
        def available(self): return True
        def search(self, query, kind, limit):
            asked.append(query)
            return [replace(h, query=query) for h in hits]
    monkeypatch.setattr(media, 'ALL_PROVIDERS', [Archive()])
    monkeypatch.setattr(media, '_CACHE', {})
    def forbidden(*a, **kw): pytest.fail('Network or LLM called')
    monkeypatch.setattr(media, 'client', forbidden)
    monkeypatch.setattr(providers, '_get', forbidden)
    monkeypatch.setattr(llm, 'complete_json', forbidden)
    return p, hits, asked


def test_tube_mail_gather(tube):
    p, hits, asked = tube
    terms = media.subject_terms(p)
    assert {'pneumatic post', 'poste pneumatique', 'rohrpost', 'petit bleu',
            'carte pneumatique', 'pneumatic tube'} <= set(terms)
    media.gather(p)
    picks = [next(c for c in s.candidates if c['id'] == s.chosen_id)
             for s in p.slides if s.chosen_id]
    assert len(picks) >= 10
    assert not any(re.search('Autorennen|Escp|Citroen|senneur|Skulptur', c['title'], re.I)
                   for c in picks)
    assert all(not c['weak_match'] and c['relevance_score'] >= 1 for c in picks)
    assert max(Counter(c['url'] for c in picks).values()) <= 2
    assert any(c['weak_match'] for s in p.slides for c in s.candidates)
    assert asked[0] != 'Paris Berlin' and any('poste pneumatique' in q for q in asked)
    assert all(not h.weak_match and not h.relevance_score for h in hits)  # cache untouched
    findings = check.run(p)['findings']
    missing = {s.id for s in p.slides if not s.chosen_id}
    assert {f['slide_id'] for f in findings if f['code'] == 'needs_picture'} == missing
    assert all(f['msg'] == 'Needs a picture' and f['fix']['kind'] == 'picture'
               for f in findings if f['code'] == 'needs_picture')


@pytest.mark.parametrize('title,subject,anchors,good,weak', [
    ("Shackleton's Endurance",
     'Ernest Shackleton and the crew of the Endurance, Imperial Trans-Antarctic Expedition',
     {'shackleton', 'endurance'},
     ['Endurance trapped in the pack ice, 1915',
      'Frank Hurley photograph of the Endurance at night'], ['Ice in Antarctica']),
    ('The Tunguska event', 'The 1908 Tunguska explosion in Siberia', {'tunguska'},
     ['Tunguska event fallen trees 1927 Kulik expedition'], ['Siberian forest']),
    ('How the Hoover Dam was built',
     'Building the Hoover Dam on the Colorado River, 1931-1936', {'hoover'},
     ['Hoover Dam construction 1934'], ['Colorado River']),
])
def test_distinctive_subject_words(title, subject, anchors, good, weak):
    p = Project(id='psubject', idea='', title=title, outline={'subject': subject})
    terms = media.subject_terms(p)
    assert anchors <= set(terms)
    for title in good + weak:
        hit = {'provider': 'wikimedia', 'title': title}
        gate(hit, terms, subject)
        assert hit['weak_match'] == (title in weak)


@pytest.mark.parametrize('title,subject,anchor,good,weak', [
    ('The Tube Mail',
     'How Paris and Berlin sent letters by air (the pneumatic post)', 'pneumatic',
     ['Poste pneumatique Paris gravure'],
     ['Die Woche Autorennen Paris-Berlin 1901', 'Escp-Berlin',
      'Air France Paris', 'Letters sent by air']),
    ('Lagos traffic', 'Why Lagos traffic jams are so bad', 'traffic',
     ['Danfo bus in Lagos traffic'], ['Lagos at night', 'Bad air and jams']),
])
def test_round_two_subjects_without_research(title, subject, anchor, good, weak):
    p = Project(id='proundtwo', idea='', title=title, outline={'subject': subject})
    terms = media.subject_terms(p)
    assert anchor in terms
    assert not {'tube', 'sent', 'letters', 'air', 'bad', 'jams'} & set(terms)
    assert not any({'paris', 'berlin', 'lagos'} & set(t.split()) for t in terms)
    for caption in good + weak:
        hit = {'provider': 'wikimedia', 'title': caption}
        gate(hit, terms)
        assert hit['weak_match'] == (caption in weak)


@pytest.mark.parametrize('title,subject,research,word,expected', [
    ('A study of Zoric', '', {}, 'zoric', True),  # proper noun in title
    ('', 'A study of Zoric', {}, 'zoric', True),  # proper noun in subject
    ('zoric', '', {'summary': 'The inventor was Zoric.'}, 'zoric', True),
    ('Zoric', '', {}, 'zoric', False),  # initial capital alone is insufficient
    ('zoric', 'zoric', {}, 'zoric', True),  # two independent sources
    ('zoric', '', {'summary': 'A study of zoric.'}, 'zoric', True),
    ('', 'zoric', {'summary': 'A study of zoric.'}, 'zoric', True),
    ('zoric zoric', '', {}, 'zoric', False),  # repetition within one source
    ('', 'A study', {'facts': ['zoric', 'zoric']}, 'zoric', False),
    ('pneumatic', '', {}, 'pneumatic', True),  # long, uncommon word
    ('rohrpos', '', {}, 'rohrpos', False),  # seven letters still need evidence
    ('Information', 'The Information', {'summary': 'Information.'},
     'information', False),  # common overrides all three evidence rules
])
def test_single_word_anchor_evidence(title, subject, research, word, expected):
    p = Project(id='pevidence', idea='', title=title, outline={'subject': subject},
                research=research)
    assert (word in media.subject_terms(p)) is expected


def test_place_and_stop_words_cannot_enter_phrase_anchors():
    p = Project(id='pphrases', idea='', title='Pneumatic post',
                outline={'subject': 'Pneumatic post in Berlin',
                         'subject_terms': ['Berlin pneumatic', 'pneumatic and post']},
                research={'summary': 'The native term was "Paris pneumatic". '
                          'Berlin pneumatic and pneumatic and post were repeated.'})
    terms = media.subject_terms(p)
    assert 'pneumatic post' in terms
    assert not {'berlin pneumatic', 'paris pneumatic', 'pneumatic and post'} & set(terms)


@pytest.mark.parametrize('anchor,caption,weak', [
    ('pneumatic', 'Poste pneumatique Paris gravure', False),
    ('rohrposten', 'Rohrpost Berlin', False),
    ('rohrpost', 'Rohrposten Berlin', False),
    ('pneumatic', 'Pneumatische Post', False),
    ('pneumatic', 'Pneumonia ward', True),  # first six letters must agree
    ('hoover', 'Hooverville camp', True),  # short anchors require whole words
    ('hoover', 'Hoover Dam', False),
    ('pneumatic post', 'Pneumatique poste', True),  # phrases stay exact
])
def test_long_single_anchor_prefix_matching(anchor, caption, weak):
    hit = {'provider': 'wikimedia', 'title': caption}
    gate(hit, [anchor])
    assert hit['weak_match'] is weak


@pytest.mark.parametrize('context', ['outline', 'research'])
@pytest.mark.parametrize('place,location', [
    ('Valparaíso', {'summary': 'The city of Valparaíso hosted the factory.'}),
    ('Łódź', {'summary': 'The factory was built near Łódź.'}),
    ('Zambezi', {'summary': 'The factory stood on the Zambezi River.'}),
    ('Ouagadougou and Port Moresby', {'locations': ['Ouagadougou', 'Port Moresby']}),
])
def test_dossier_and_outline_places_are_not_anchors(context, place, location):
    p = Project(id='pplaces', idea='', title=f'Pneumatic post in {place}',
                outline={'subject': 'Pneumatic post'})
    getattr(p, context).update(location)
    terms = media.subject_terms(p)
    hit = {'provider': 'wikimedia', 'title': ' '.join(location.get('locations', []))
           or location['summary']}
    gate(hit, terms)
    assert hit['weak_match']
    assert 'pneumatic' in terms


@pytest.mark.parametrize('subject', [
    'Paris', 'Paris Berlin', 'New York', 'France Germany',
    'History story event building crew post city river built explosion expedition',
])
def test_places_and_generic_words_alone_do_not_supply_anchors(subject):
    p = Project(id='pweak', idea='', title=subject, outline={'subject': subject})
    assert media.subject_terms(p) == []


def test_bad_pool_leaves_gaps_and_locked_and_partial_gather_survive(tube):
    p, hits, _ = tube
    terms = media.subject_terms(p)
    for c in hits[:8]:
        d = c.to_dict()
        gate(d, terms, 'Paris Berlin')
        assert d['weak_match']
    for s in p.slides:
        s.candidates = [h.to_dict() for h in hits[:8]]
    media._top_up(p.slides, hits[:8], terms=terms)
    p.slides[0].locked_media, p.slides[0].chosen_id = True, 'c0'
    p.slides[1].chosen_id = 'c1'
    media._autopick(p, only={s.id for s in p.slides[2:]})
    assert [s.chosen_id for s in p.slides[:2]] == ['c0', 'c1']
    assert not any(s.chosen_id for s in p.slides[2:])
    # A category/description match works even if the title carries no subject.
    for c in (hits[10], hits[-1]):
        d = c.to_dict()
        gate(d, terms)
        assert not d['weak_match']


def test_queries_and_safe_licence_defaults(tube):
    p, _, _ = tube
    concrete = 'Tunguska fallen forest 1927'
    abstract = 'airburst explosion energy release megatons TNT'
    assert concrete_queries([abstract, concrete]) == [concrete]
    assert concrete_queries([abstract]) == [abstract]
    terms = media.subject_terms(p)
    assert paragraph_queries(['Bourse Paris 1866'], terms)[0].endswith(terms[0])
    assert 'Paris Berlin' not in paragraph_queries(['Paris Berlin'], terms)
    p.research['facts'].append({'claim': "The carrier was called 'train' or 'box'."})
    assert not {'train', 'box', 'post office'} & set(media.subject_terms(p))
    assert all(terms[0] in q for q in media._ladder(['Bourse Paris 1866'], terms))
    a = dict(weak_match=False, relevance_score=1, score=2, license='CC BY-SA 4.0')
    b = dict(a, license='CC0')
    assert rank(a) == rank(b)
    assert rank(b, True) > rank(a, True)
    assert rank(dict(a, relevance_score=2), True) > rank(b, True)
    for raw, expected in [({}, False), ({'example': True}, True),
                          ({'example': True, 'prefer_public_domain': False}, False)]:
        project = Project.from_dict(dict(id='pold', idea='', future='ignored', **raw))
        assert project.prefer_public_domain is expected
        assert Project.from_dict(project.to_dict()).prefer_public_domain is expected


def test_download_fallback_does_not_pick_weak(tube, monkeypatch):
    p, hits, _ = tube
    s = p.slides[0]
    s.candidates = [hits[0].to_dict(), hits[-1].to_dict()]
    for c in s.candidates: gate(c, media.subject_terms(p))
    s.chosen_id = hits[-1].id
    tried = []
    def fail(project, cand):
        tried.append(cand['id'])
        raise RuntimeError('offline failure')
    monkeypatch.setattr(media, 'download', fail)
    assert media.download_chosen(p, only=[s]) == [s.id]
    assert tried == [hits[-1].id]


def test_provider_metadata_reaches_gate(monkeypatch):
    monkeypatch.setattr(providers, '_get', lambda *a, **kw: {'query': {'pages': [
        {'title': 'File:Bourse 1866.jpg', 'imageinfo': [dict(url='offline.jpg',
            extmetadata={'ImageDescription': {'value': '<p>Poste pneumatique &amp; Paris</p>'},
                         'Categories': {'value': 'Telegraph offices|Paris'}})]}]}})
    hit = providers.Wikimedia().search('Bourse', 'image')[0].to_dict()
    assert hit['description'] == 'Poste pneumatique & Paris'
    assert hit['categories'] == ['Telegraph offices', 'Paris']
    gate(hit, ['poste pneumatique'])
    assert not hit['weak_match']
    monkeypatch.setattr(providers, '_get', lambda *a, **kw: {'results': [dict(
        title='Envelope', image_url=['offline.jpg'], description=['Rohrpost Berlin'],
        subject=['Postal stationery'])]})
    hit = providers.LibraryOfCongress().search('Berlin', 'image')[0].to_dict()
    gate(hit, ['rohrpost'])
    assert not hit['weak_match'] and hit['categories'] == ['Postal stationery']


def test_planner_filters_abstract_queries_without_model(tube, monkeypatch):
    from app import script_gen
    p, _, _ = tube
    prompts = []
    def fake(prompt, **kwargs):
        prompts.append(prompt)
        return [{'n': 1, 'queries': ['airburst explosion energy release megatons TNT',
                                     'Bourse Paris poste pneumatique'], 'kind': 'image'}]
    monkeypatch.setattr(script_gen, 'complete_json', fake)
    script_gen.plan_visuals(p, p.slides[:1])
    assert p.slides[0].queries == ['Bourse Paris poste pneumatique']
    assert 'camera, painter or mapmaker' in prompts[0]
    assert 'SUBJECT TERMS' in prompts[0]


def test_download_fallback_reserves_reuse_slots(tube, monkeypatch):
    p, hits, _ = tube
    p.slides = p.slides[:4]
    for i, s in enumerate(p.slides):
        s.candidates = [dict(hits[-2].to_dict(), id=f'fail{i}', url=f'offline:{i}'),
                        hits[-1].to_dict()]
        s.chosen_id = f'fail{i}'
    def download(project, cand):
        if cand['id'].startswith('fail'): raise RuntimeError('missing')
        return 'media/fixture.jpg'
    monkeypatch.setattr(media, 'download', download)
    assert len(media.download_chosen(p)) == 2
    assert sum(s.chosen_id == hits[-1].id for s in p.slides) == 2

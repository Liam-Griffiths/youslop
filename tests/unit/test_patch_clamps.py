"""Shared HTTP/storyboard timing validation, without reading or writing audio."""
from copy import deepcopy

import pytest

from app import edits, render


@pytest.mark.parametrize('field', ['title_at', 'at'])
@pytest.mark.parametrize('value,expected', [(-2, 0), (1.25, 1.25), (999, 4)])
def test_arrival_clamp(project, field, value, expected):
    slide = project.slides[0]
    slide.take['duration'] = 4
    take = deepcopy(slide.take)
    payload = {'title_at': value} if field == 'title_at' else {
        'cues': {'flameboat': [{'kind': 'title', 'text': 'Hi', 'at': value}]}}
    edits.patch_slide_fields(slide, payload)
    actual = slide.title_at if field == 'title_at' else slide.cues['flameboat'][0]['at']
    assert actual == expected
    assert slide.take == take


@pytest.mark.parametrize('value,expected', [(-2, 0), (1.5, 1.5), (20, 10), (None, None)])
def test_gap_clamp(project, value, expected):
    edits.patch_slide_fields(project.slides[0], {'gap_override': value})
    assert project.slides[0].gap_override == expected


@pytest.mark.parametrize('value', [float('inf'), float('nan'), True, '2'])
@pytest.mark.parametrize('field', ['at', 'title_at', 'gap_override'])
def test_invalid_seconds(project, field, value):
    payload = {field: value} if field != 'at' else {
        'cues': {'flameboat': [{'kind': 'title', 'text': 'Hi', 'at': value}]}}
    with pytest.raises(edits.EditError, match='finite'):
        edits.patch_slide_fields(project.slides[0], payload)


def test_clear_and_unrecorded(project):
    slide = project.slides[0]
    slide.take = None
    edits.patch_slide_fields(slide, {'title_at': 2})
    assert slide.title_at == 2
    edits.patch_slide_fields(slide, {'title_at': None, 'title_hold': None, 'chapter_hold': None})
    assert slide.title_at is slide.title_hold is slide.chapter_hold is None


def test_timeline_edit_metadata(project):
    project.style.format = 'flameboat'
    slide = project.slides[0]
    slide.take['words'] = [{'w': 'Hello', 'start': .2, 'end': .7, 'src': 'est'}]
    before = deepcopy(slide.take)
    tl = render.timeline(project)
    q = tl['segments'][0]['paragraphs'][0]
    assert q['word_times'] == [{'w': 'Hello', 'start': round(q['start'] + .2, 3),
                              'end': round(q['start'] + .7, 3), 'src': 'est'}]
    assert q['spoken'] == slide.take['duration']
    assert q['effective_cues']
    assert tl['last_line_min_s'] == project.frame.last_line_min_s
    assert slide.take == before


def test_title_resize_is_marked_user(project):
    project.style.format = 'kenburns'
    slide = project.slides[0]
    slide.title = 'Title'
    edits.patch_slide_fields(slide, {'title_hold': 1})
    item = next(t for t in render.timeline(project)['layers']['titles'] if t['sid'] == slide.id)
    assert item['src'] == 'user'

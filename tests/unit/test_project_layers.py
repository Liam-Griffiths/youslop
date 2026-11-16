"""Project tracks reuse existing spans without migrating or rendering assets."""
from copy import deepcopy
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import block_overlays, cuts, layers, main, render, store
from app.schema import Layer, LAYER_COLORS, LAYER_ROLES, Project


def test_lane_order_matches_current_editor():
    source = Path('static/js/timeline/layers.js').read_text()
    kinds = source.split('const TL_LAYER_KINDS = {', 1)[1].split('};', 1)[0]
    roles = ['pictures', 'voice']
    for role in re.findall(r'(\w+):', kinds):
        roles.append(role)
        if role == 'titles':
            roles.append('captions')
    assert tuple(roles) == LAYER_ROLES
    css = Path('static/styles.css').read_text()
    assert len(LAYER_COLORS) == 8
    assert all(f'--{color}:' in css for color in LAYER_COLORS)


def test_old_project_uses_real_spans_and_does_not_persist_derivation(project):
    project.slides[0].overlays = [dict(id='name', block_id='lower_third_panel', vars={}, at=0, dur=1)]
    project.slides[1].chapter = 'Next section'
    project.slides[2].title = 'Hidden title'
    project.slides[2].title_hold = 0
    before = deepcopy(project.to_dict())
    timeline = render.timeline(project)
    effective = layers.effective(project, items=layers.role_items(project, timeline))
    assert [layer.role for layer in effective] == ['pictures', 'voice', 'graphics', 'titles', 'chapters']
    assert [layer.name for layer in effective] == ['Pictures', 'Voice', 'Graphics', 'Titles', 'Chapters']
    assert [layer.id for layer in effective] == [layer.role for layer in effective]
    assert not any(layer.hidden or layer.locked for layer in effective)
    assert project.to_dict() == before
    store.save(project)
    assert store.load(project.id).layers == []


def test_empty_project_keeps_pictures_and_voice():
    project = Project(id='pempty', idea='')
    assert [layer.role for layer in layers.effective(project, items={})] == ['pictures', 'voice']


def test_essay_uses_caption_lane(project):
    project.style.format = 'essay'
    timeline = render.timeline(project)
    original = deepcopy(timeline)
    rows = layers.rows(project, timeline)
    assert [row['role'] for row in rows] == ['pictures', 'voice', 'captions']
    assert rows[-1]['items']
    assert [i['id'] for i in rows[-1]['items']] == [i['id'] for i in timeline['layers']['titles']]
    assert timeline == original


def test_schema_round_trip_unknown_keys_defaults_and_flags(project):
    raw = project.to_dict()
    raw['layers'] = [dict(id='maps', name='Maps', role='graphics', color='cool',
                          order=9, hidden=True, locked=True, future='ignored'), dict(id='other')]
    raw['slides'][0]['title_layer'] = 'headings'
    raw['music_layer'] = 'bed'
    raw['intro']['music_layer'] = 'opening'
    raw['outro']['sting_layer'] = 'closing'
    loaded = Project.from_dict(raw)
    store.save(loaded)
    restored = store.load(loaded.id)
    assert restored.layers == loaded.layers
    assert restored.layers[0].hidden and restored.layers[0].locked
    assert restored.layers[1].role == 'graphics' and restored.layers[1].color in LAYER_COLORS
    assert restored.slides[0].title_layer == 'headings'
    assert (restored.music_layer, restored.intro.music_layer, restored.outro.sting_layer) == (
        'bed', 'opening', 'closing')


@pytest.mark.parametrize('patch', [dict(role='anything'), dict(color='#ff0000'), dict(order=True),
                                  dict(hidden='false'), dict(locked=1), dict(id=''), dict(name='')])
def test_invalid_layer_metadata(patch):
    with pytest.raises(ValueError):
        Layer.from_dict(patch)


def test_saved_order_and_same_role_fallback(project, monkeypatch):
    maps = Layer(id='maps', name='Maps', order=8)
    graphics = Layer(id='graphics', name='Graphics', order=1)
    title = Layer(id='title', name='Title', role='titles', order=0)
    project.layers = [maps, graphics, title]
    monkeypatch.setattr(layers, 'role_items', lambda *a: pytest.fail('derived saved layers'))
    effective = layers.effective(project)
    assert effective == [title, graphics, maps]
    assert project.layers == [maps, graphics, title]
    assert layers.resolve(effective, 'graphics', 'maps') is maps
    for ident in ('', 'deleted', 'title'):
        assert layers.resolve(effective, 'graphics', ident) is graphics
    assert layers.resolve(effective, 'music') is None


def test_item_references_survive_normalisation_and_grouping(project):
    project.slides[0].overlays = [dict(id='map', block_id='lower_third_panel', vars={},
                                      at=0, dur=1, layer='maps')]
    project.slides[0].title_layer = 'headings'
    project.layers = [Layer(id='base', name='Graphics'), Layer(id='maps', name='Maps', order=1),
                      Layer(id='headings', name='Headings', role='titles')]
    original = deepcopy(project.to_dict())
    rows = {row['id']: row for row in layers.rows(project, render.timeline(project))}
    assert rows['base']['items'] == []
    assert rows['maps']['items'][0]['id'] == 'map'
    assert rows['headings']['items'][0]['layer'] == 'headings'
    assert rows['pictures']['items'] and rows['voice']['items']  # incomplete saved set is safe
    assert project.to_dict() == original
    assert block_overlays.validate(None, project.slides[0].overlays)[0]['layer'] == 'maps'
    project.style.format = 'flameboat'
    project.slides[0].cues['flameboat'] = [dict(kind='title', text='Hello', layer='callouts')]
    cue = cuts.cues_for(cuts.flameboat, project.slides[0])[0]
    assert cue['layer'] == 'callouts'
    assert render.timeline(project)['layers']['cues'][0]['layer'] == 'callouts'
    with pytest.raises(ValueError, match='layer'):
        block_overlays.validate(None, [dict(project.slides[0].overlays[0], layer=12)])


def test_notes_and_additive_api_match_standalone_derivation(project, monkeypatch):
    finding = dict(t=1, level='P1', msg='Check note', rule='test', slide_id='s1', fix={'kind': 'text'})
    monkeypatch.setattr(main, '_load', lambda pid: project)
    monkeypatch.setattr(main.check, 'run', lambda p: {'findings': [dict(finding)]})
    report = dict(notes=[dict(id='review', t=2, severity='P2', problem='Review note')])
    monkeypatch.setattr(main.review, 'read_notes', lambda pid: report)
    monkeypatch.setattr(main, 'get_review', lambda pid: report)
    timeline = main.get_timeline(project.id)
    rows = timeline['project_layers']
    assert isinstance(timeline['layers'], dict)
    assert [row['role'] for row in rows] == [layer.role for layer in layers.effective(project)]
    assert rows[-1]['role'] == 'notes'
    assert [i['text'] for i in rows[-1]['items']] == ['Check note', 'Review note']
    assert all(i['layer'] == row['id'] for row in rows for i in row['items'])
    note_id = main.review.note_id(finding)
    report['notes'] = [dict(id=note_id, source='check', state='dismissed')]
    assert 'notes' not in [layer.role for layer in layers.effective(project)]
    assert 'notes' not in [row['role'] for row in main.get_timeline(project.id)['project_layers']]


def test_audio_references_reach_spans(project, monkeypatch, tmp_path):
    monkeypatch.setattr(render, 'pick_music', lambda p: tmp_path / 'bed.wav')
    opening = SimpleNamespace(music_start=0, music_tail=1, music_fade=.5, music_layer='opening')
    closing = SimpleNamespace(music_start=0, music_tail=0, music_fade=.5,
                              _spec=SimpleNamespace(sting_layer='closing'))
    monkeypatch.setattr(render, '_stings_for', lambda *a: {
        'intro': (tmp_path / 'intro.wav', opening), 'outro': (tmp_path / 'outro.wav', closing)})
    project.music_layer = 'bed'
    spans = render._layers(project, [dict(type='intro', start=0, duration=4),
                                      dict(type='outro', start=4, duration=4)])
    assert spans['music'][0]['layer'] == 'bed'
    assert [item['layer'] for item in spans['stings']] == ['opening', 'closing']


def test_fallback_tracks_do_not_collide_with_saved_ids(project):
    project.layers = [Layer(id='pictures', name='Maps')]
    original = deepcopy(project.to_dict())
    rows = layers.rows(project, render.timeline(project))
    assert len({row['id'] for row in rows}) == len(rows)
    assert next(row for row in rows if row['role'] == 'pictures')['id'] == 'derived:pictures'
    assert next(row for row in rows if row['role'] == 'titles')['items']
    assert project.to_dict() == original

"""Home metadata and project creation; synthetic storage, no jobs or LLMs."""
from copy import deepcopy

import pytest

from app import channels, footage, main, ops, store
from app.schema import Channel, Project, Slide
from app.stages import home_summary, readiness_check, stages


def test_legacy_aspect_and_unknown_fields():
    p = Project.from_dict({'id': 'legacy', 'idea': 'Legacy project', 'future': True})
    assert p.aspect == 'landscape'
    p.aspect = 'portrait'
    assert Project.from_dict(p.to_dict()).aspect == 'portrait'


@pytest.mark.parametrize('aspect,minutes', [('landscape', 12), ('portrait', 1)])
def test_create_shape_without_initializing(monkeypatch, tmp_path, aspect, minutes):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    result, script = ops.prepare_create({'idea': 'An episode about clocks', 'aspect': aspect})
    loaded = store.load(result.id)
    assert not script and loaded.aspect == aspect and loaded.target_minutes == minutes
    assert not loaded.test


def test_invalid_shape():
    with pytest.raises(ops.PayloadError, match='Shape'):
        ops.prepare_create({'idea': 'An episode about clocks', 'aspect': 'square'})


def test_script_and_saved_format_keep_options(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    store.PROJECTS_DIR.mkdir()
    c = Channel(id='chome', name='Home fixtures', formats=[{
        'name': 'Essay preset', 'style': {'format': 'essay', 'accent': '#123456'}, 'frame': {},
    }])
    channels.save(c)
    payload = dict(script='A spoken word. ' * 50, channel_id=c.id, format_name='Essay preset',
                   delivery='mixed', fidelity='adapted', aspect='portrait', research_mode='deep')
    p, script = ops.prepare_create(payload)
    assert p.aspect == 'portrait' and p.style.format == 'essay'
    assert p.delivery == 'mixed' and p.fidelity == 'adapted' and p.research_mode == 'deep'
    assert (store.project_dir(p.id) / 'source.txt').read_text() == script
    preset = channels.list_channels()[0]['formats'][0]
    assert preset['style'] == {'format': 'essay', 'accent': '#123456'}


def test_home_stage_summary_and_list(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='phome', idea='An empty episode')
    assert home_summary(p)['id'] == 'plan'
    p.slides = [Slide(id='s1', narration='An imported paragraph')]
    before = deepcopy(p)
    row = home_summary(p)
    assert row['id'] == 'voice'
    assert row in stages(p, readiness_check(p)) and p == before
    store.save(p)
    assert main.list_projects()[0]['stage'] == row
    assert 'stage' not in store.list_projects()[0]  # channel counts need no readiness work
    p.set_take(p.slides[0], 'mic', {'path': 'takes/mic.wav', 'duration': 3})
    p.style.format = 'loudmouth'
    assert home_summary(p)['id'] == 'edit'
    p.render = {'output': 'out/video.mp4'}
    assert home_summary(p)['id'] == 'publish'


def test_footage_summary_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path)
    s = footage.Shoot(id='fhome', path='/synthetic/Tower shoot', files=[
        footage.SourceFile(id='source', duration=32)], clips=[
        footage.Clip(id='c1', file='source', labels=['tower'])])
    footage._save(s)
    manifest = tmp_path / s.id / 'shoot.json'
    before = manifest.read_bytes()
    assert main.list_footage_shoots() == [dict(id=s.id, name='Tower shoot', files=1,
                                             clips=1, seconds=32, labelled=1)]
    assert manifest.read_bytes() == before

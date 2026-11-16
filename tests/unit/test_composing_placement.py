"""3D/Create metadata placement: no solver, browser, renderer or model calls."""
from copy import deepcopy

import pytest

from app import audio, custom_scenes, inserts, llm, main, models3d, render, shots, store, undo


MODEL = dict(kind='stage', model_id='m12345678', seconds=4)
GRAPHIC = dict(kind='graphic', graphic_id='graphic', seconds=4)
HTML = '<section class="cb-slide"><h1 class="cb-number">427 km</h1></section>'


@pytest.fixture
def composing(project, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    model = dict(id='m12345678', title='Station', scale=1, heading=0, kind='object')
    def get(ident):
        if ident != model['id']:
            raise models3d.ModelError('No such model')
        return deepcopy(model)
    monkeypatch.setattr(models3d, 'get', get)
    def forbidden(*args, **kwargs):
        pytest.fail('Placement must not call a model, browser or renderer')
    monkeypatch.setattr(llm, 'complete_json', forbidden)
    monkeypatch.setattr(shots, 'complete_json', forbidden)
    monkeypatch.setattr(shots.stage_mod, 'render', forbidden)
    monkeypatch.setattr(custom_scenes, 'html_candidate', forbidden)
    monkeypatch.setattr(custom_scenes, 'render', forbidden)
    project.style.format, project.style.picture_every = 'kenburns', 3
    project.slides[1].picture_mode = 'hold'
    project.graphics = [dict(id='graphic', current=0, versions=[dict(html=HTML)], used_in=[])]
    root = store.project_dir(project.id)
    (root / 'recording.wav').write_bytes(b'recorded audio')
    project.set_take(project.slides[0], 'mic', dict(path='recording.wav', duration=3, words=[]))
    store.save(project)
    yield project, model
    assert (root / 'recording.wav').read_bytes() == b'recorded audio'


@pytest.mark.parametrize('payload', [MODEL, GRAPHIC])
def test_insert_timing_trim_cache_and_undo(composing, payload):
    p, _model = composing
    original, before = p.to_dict(), render.timeline(p)
    result = main.add_insert(p.id, dict(payload, after='s1'))
    row = result['slides'][1]
    p = store.load(p.id)
    added = p.slide(row['id'])
    assert added.insert['seconds'] == 4 and not added.narration and not added.take
    assert (added.id, 4) in audio.slide_durations(p)
    after = render.timeline(p)
    def start(timeline, sid):
        return next(q['start'] for seg in timeline['segments'] for q in seg.get('paragraphs', []) if q['id'] == sid)
    # Inserting breaks the old held group, but does not move its narration clock.
    assert after['total'] - before['total'] == pytest.approx(4)
    assert start(after, 's2') - start(before, 's2') == pytest.approx(4)
    groups = render._groups_for_preview(p)
    index = next(i for i, g in enumerate(groups) if g[0][0].id == added.id)
    key = render._proxy_key(p, groups, index, None)
    main.patch_insert(p.id, added.id, dict(seconds=6))
    trimmed = store.load(p.id)
    assert trimmed.slide(added.id).insert['seconds'] == 6
    assert render._proxy_key(trimmed, render._groups_for_preview(trimmed), index, None) != key
    main.undo_project(p.id)
    assert store.load(p.id).slide(added.id).insert['seconds'] == 4
    main.undo_project(p.id)
    restored = store.load(p.id)
    assert [s.to_dict() for s in restored.slides] == original['slides']
    assert restored.cast == original['cast'] and restored.graphics == original['graphics']
    main.redo_project(p.id)
    assert store.load(p.id).slide(added.id).to_dict() == added.to_dict()


@pytest.mark.parametrize('payload', [MODEL, GRAPHIC])
def test_replaces_held_lead_and_existing_insert(composing, payload):
    p, _model = composing
    original = deepcopy(p.slides[0].to_dict())
    main.replace_picture_source(p.id, 's2', payload)
    p = store.load(p.id)
    lead = p.slides[0]
    assert lead.locked_media
    assert lead.kind == ('stage' if payload['kind'] == 'stage' else 'custom:graphic')
    assert lead.take == original['take'] and lead.history == original['history']
    if payload['kind'] == 'stage':
        assert lead.shot['intent']['subjects'][0] == p.cast[-1]['id']
        assert shots.is_3d(lead) and shots.leads(p)
    else:
        assert lead.custom_html == HTML and p.graphics[0]['used_in'] == [lead.id]
    main.undo_project(p.id)
    assert store.load(p.id).slides[0].to_dict() == original
    result = main.add_insert(p.id, dict(kind='card', text='Before', seconds=7, after='s1'))
    sid = result['slides'][1]['id']
    p = store.load(p.id)
    p.slide(sid).chapter = 'Keep chapter'
    store.save(p)
    before = deepcopy(p.slide(sid).to_dict())
    main.replace_picture_source(p.id, sid, payload)
    row = store.load(p.id).slide(sid)
    assert row.id == sid and row.chapter == 'Keep chapter'
    assert row.insert['seconds'] == 7 and row.insert['kind'] == payload['kind']
    main.undo_project(p.id)
    assert store.load(p.id).slide(sid).to_dict() == before


def test_graphic_snapshot_survives_source_edits_and_delete(composing, monkeypatch, tmp_path):
    p, _model = composing
    result = main.add_insert(p.id, dict(GRAPHIC, after='s1'))
    sid = result['slides'][1]['id']
    p = store.load(p.id)
    p.graphics = []
    store.save(p)
    main.patch_insert(p.id, sid, dict(seconds=9))
    p = store.load(p.id)
    assert p.slide(sid).custom_html == HTML
    calls = []
    monkeypatch.setattr(custom_scenes, 'render', lambda root, ctx, ground, out, **kw: calls.append((ctx, kw)) or out)
    monkeypatch.setattr(render, '_chapter_tail', lambda project, out, *a: out)
    out = tmp_path / 'never-rendered.mp4'
    assert render._render_segment(p, [(p.slide(sid), 9)], 9.5, 1, out, size=(480, 270)) == out
    assert calls[0][0]['custom_html'] == HTML and calls[0][0]['duration'] == 9.5
    assert calls[0][1]['size'] == (480, 270)


def test_copy_hand_shot_keeps_path_after_source_deleted(composing):
    p, model = composing
    main.replace_picture_source(p.id, 's1', MODEL)
    p = store.load(p.id)
    source = p.slide('s1')
    source.shot.update(locked=True, solved=dict(shot=dict(start='hand path'), secs=3))
    store.save(p)
    result = main.add_insert(p.id, dict(kind='stage', source_slide='s1', seconds=5, after='s2'))
    sid = result['slides'][2]['id']
    p = store.load(p.id)
    assert p.slide(sid).shot == source.shot
    p.slides.remove(p.slide('s1'))
    store.save(p)
    main.patch_insert(p.id, sid, dict(seconds=8))
    p = store.load(p.id)
    assert p.slide(sid).shot == source.shot
    groups = render._groups_for_preview(p)
    index = next(i for i, g in enumerate(groups) if g[0][0].id == sid)
    before = render._proxy_key(p, groups, index, None)
    model['scale'] = 2
    assert render._proxy_key(p, groups, index, None) != before


def test_model_reuses_cast_and_invalidates_finished_segments(composing, monkeypatch):
    p, model = composing
    p.cast = [dict(id='known', subject='Existing station', model=model['id'], mode='model')]
    store.save(p)
    result = main.add_insert(p.id, dict(MODEL, after='s1'))
    p = store.load(p.id)
    row = p.slides[1]
    assert len(p.cast) == 1 and row.shot['intent']['subjects'] == ['known']
    monkeypatch.setattr(render, '_segment_graph', lambda *a, **kw: ([], 'stub graph', '[v]'))
    options = dict(seg_len=4, channel=None, chapter=None, size=(480, 270), fps=15,
        crf=28, preset='ultrafast', dip_out=False, op='set', camera_index=0, last_line=False)
    before = render._segment_key(p, [(row, 4)], options)
    model['heading'] = 90
    assert render._segment_key(p, [(row, 4)], options) != before
    # The source metadata round-trips without adding schema fields or a fake take.
    assert result['slides'][1]['insert'] == row.insert and not row.take


@pytest.mark.parametrize('payload', [dict(MODEL, model_id='missing'), dict(MODEL, source_slide='s1'),
    dict(kind='stage', source_slide='missing', seconds=4), dict(GRAPHIC, graphic_id='missing'),
    dict(GRAPHIC, seconds=float('nan')), dict(MODEL, seconds=True), dict(GRAPHIC, html=HTML)])
def test_invalid_source_never_publishes(composing, payload):
    p, _model = composing
    root = store.project_dir(p.id)
    before, history = (root / 'project.json').read_bytes(), undo.read(root)
    with pytest.raises(main.HTTPException) as error:
        main.add_insert(p.id, payload)
    assert error.value.status_code == 400
    assert (root / 'project.json').read_bytes() == before and undo.read(root) == history

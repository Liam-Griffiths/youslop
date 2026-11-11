"""Main-track insert model, timing and atomic edits; no encoders or models."""
from copy import deepcopy
import asyncio

import httpx
import pytest

from app import audio, check, edits, footage, inserts, main, render, script_gen, store, storyboard, undo
from app.schema import Project, Slide, group_slides


@pytest.fixture
def cut(project, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'shoots')
    original = tmp_path / 'source.mp4'
    original.write_bytes(b'original; never encode this fixture')
    footage._save(footage.Shoot('shoot', files=[footage.SourceFile('source', str(original),
        duration=20, audio=[dict(channels=1)])]))
    project.style.format = 'kenburns'
    project.style.picture_every = 1
    store.save(project)
    stamp = original.stat().st_mtime_ns
    yield project
    assert original.read_bytes() == b'original; never encode this fixture'
    assert original.stat().st_mtime_ns == stamp


CLIP = dict(kind='clip', shoot_id='shoot', source_id='source', in_s=2, out_s=6)


def test_roundtrip_defaults_and_isolation(cut):
    old = cut.to_dict()
    assert all('insert' not in row for row in old['slides'])
    assert not Slide.from_dict(dict(id='old', future=True, insert=None)).insert
    row, after = inserts.prepare(cut, CLIP | {'after': 's1'})
    inserts.place(cut, row, after)
    raw = cut.to_dict()
    loaded = Project.from_dict(raw)
    loaded.slide(row.id).insert['source_audio'] = True
    assert raw['slides'][1]['insert']['source_audio'] is False
    assert cut.slide(row.id).narration == '' and not cut.slide(row.id).take
    assert cut.est_seconds() - Project.from_dict(old).est_seconds() == pytest.approx(4)
    assert render._slide_durations(cut, False)[1] == (row, 4)
    assert (row.id, 4) in audio.slide_durations(cut)


@pytest.mark.parametrize('fmt', ['kenburns', 'essay', 'loudmouth'])
def test_four_second_ripple_and_attached_anchors(cut, fmt):
    cut.style.format = fmt
    second = cut.slides[1]
    second.title_at, second.title_hold = .8, 1.2
    second.overlays = [dict(id='graphic', block_id='lower_third_panel', vars={}, at=.3, dur=1)]
    second.cues = {'loudmouth': [dict(kind='shout', text='Anchored', at=.4)]}
    before = render.timeline(cut)
    gap_before = audio.gap_map(cut)
    anchors = deepcopy(second.to_dict())
    row, after = inserts.prepare(cut, CLIP | {'after': 's1'})
    inserts.place(cut, row, after)
    after_tl = render.timeline(cut)
    def paras(tl):
        return {p['id']: p for seg in tl['segments'] for p in seg['paragraphs']}
    old, new = paras(before), paras(after_tl)
    assert after_tl['total'] - before['total'] == pytest.approx(4)
    assert new['s1']['start'] == old['s1']['start']
    for sid in ('s2', 's3'):
        assert new[sid]['start'] - old[sid]['start'] == pytest.approx(4)
        assert audio.gap_map(cut)[sid] == gap_before[sid]
    assert new['s2']['timing']['title_at']['start'] - old['s2']['timing']['title_at']['start'] == pytest.approx(4)
    assert cut.slide('s2').to_dict() == anchors
    for lane in ('graphics', 'cues'):
        for old_item in before['layers'][lane]:
            if old_item['sid'] == second.id:
                item = next(x for x in after_tl['layers'][lane] if x['id'] == old_item['id'])
                assert item['t0'] - old_item['t0'] == pytest.approx(4)
                assert item['t1'] - old_item['t1'] == pytest.approx(4)
    assert new[row.id]['duration'] == 4 and new[row.id]['spoken'] == 0
    assert not new[row.id]['recorded'] and new[row.id]['word_times'] == []
    assert audio.gap_map(cut)[row.id] == 0
    sb = storyboard.build(cut)
    assert next(p for p in sb['paragraphs'] if p['id'] == row.id)['label'] == 'Insert · clip · 4.0 s'
    assert not any(f['slide_id'] == row.id and f['code'] == 'empty_narration'
                   for f in check.script(cut)['findings'])
    assert not any('not recorded' in problem for seg in after_tl['segments']
                   if seg['lead'] == row.id for problem in seg['problems'])
    # Both sides break a picture run, even with explicit holds.
    for s in cut.slides:
        s.picture_mode = 'hold'
    assert [[s.id for s in g] for g in group_slides(cut.slides, 8)] == [
        ['s1'], [row.id], ['s2', 's3']]


@pytest.mark.parametrize('patch', [dict(after='missing'), dict(after=None), dict(in_s=True), dict(in_s=None),
    dict(out_s=float('nan')), dict(in_s=6), dict(out_s=21), dict(source_audio='yes'),
    dict(seconds=3), dict(extra=True), dict(source_id='missing')])
def test_rejected_edits_never_publish(cut, patch):
    path = store.project_dir(cut.id) / 'project.json'
    before = path.read_bytes()
    with pytest.raises(main.HTTPException) as exc:
        main.add_insert(cut.id, CLIP | patch)
    assert exc.value.status_code == 400 and path.read_bytes() == before
    assert not undo.read(path.parent)['states']


def test_create_patch_move_delete_undo(cut):
    added = main.add_insert(cut.id, CLIP | {'after': 's1'})
    sid = added['slides'][1]['id']
    changed = main.patch_insert(cut.id, sid, dict(out_s=8, source_audio=True, after='intro'))
    assert changed['slides'][0]['insert']['seconds'] == 6
    assert changed['slides'][0]['insert']['source_audio'] is True
    main.undo_project(cut.id)
    assert store.load(cut.id).slides[1].insert['seconds'] == 4
    main.redo_project(cut.id)
    assert store.load(cut.id).slides[0].id == sid
    with pytest.raises(main.HTTPException):
        main.patch_insert(cut.id, sid, dict(after=sid))
    main.delete_insert(cut.id, sid)
    assert not store.load(cut.id).slide(sid)
    main.undo_project(cut.id)
    assert store.load(cut.id).slide(sid).insert['seconds'] == 6
    with pytest.raises(main.HTTPException):
        main.delete_insert(cut.id, 's1')


def test_http_edit_label_and_no_narration_routes(cut, monkeypatch):
    # Match test_undo: sandbox threadpool wakeups can stall ASGI tests.
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                    base_url='http://127.0.0.1') as client:
            response = await client.post(f'/api/projects/{cut.id}/inserts', json=CLIP,
                                        headers={'X-Edit-Label': 'Insert source range'})
            assert response.status_code == 200
            sid = response.json()['slides'][0]['id']
            response = await client.post(f'/api/projects/{cut.id}/slides/{sid}/rewrite',
                                         json={'instruction': 'Never call a model'})
            assert response.status_code == 400
    monkeypatch.setattr(script_gen, 'complete_json', lambda *a, **k: pytest.fail('model called'))
    asyncio.run(run())
    assert undo.read(store.project_dir(cut.id))['states'][-1]['label'] == 'Insert source range'


def test_other_kinds_and_pending_integration(cut, monkeypatch, tmp_path):
    from app import blocks, library
    path = tmp_path / 'picture.png'
    path.write_bytes(b'library fixture')
    monkeypatch.setattr(library, 'get', lambda ident: dict(kind='image') if ident == 'picture' else None)
    monkeypatch.setattr(library, 'file_path', lambda ident: path if ident == 'picture' else None)
    monkeypatch.setattr(blocks, 'discover', lambda: {'example': dict(meta=dict(aspects=['16:9'],
        variables={'headline': dict(type='text', default='Hello', max_length=10)}))})
    for payload in [dict(kind='card', text='A card', seconds=4),
                    dict(kind='picture', asset_id='picture', seconds=4),
                    dict(kind='block', block='example', vars={'headline': 'Hi'}, seconds=4)]:
        row, _ = inserts.prepare(cut, payload)
        assert row.insert['seconds'] == 4
    for payload in [dict(kind='card', text='', seconds=4),
                    dict(kind='picture', asset_id='missing', seconds=4),
                    dict(kind='block', block='example', vars={'unknown': 1}, seconds=4),
                    dict(kind='card', text='Card', seconds=True)]:
        with pytest.raises(ValueError):
            inserts.prepare(cut, payload)
    row, after = inserts.prepare(cut, CLIP)
    inserts.place(cut, row, after)
    with pytest.raises(edits.EditError):
        edits.patch_slide_fields(row, {'narration': 'Cannot speak this'})
    for operation in [lambda: script_gen.generate(cut),
                      lambda: script_gen.import_script(cut, 'replacement'),
                      lambda: script_gen.rewrite_slide(cut, row, 'rewrite'),
                      lambda: render._render(cut, lambda m: None, False),
                      lambda: audio.build_slice(cut, [row], path, 0)]:
        with pytest.raises(ValueError):
            operation()

"""Trims change bounded edit metadata, with atomic roll undo and intact media."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from app import footage, main, render, store, timeline_trims, undo
from app.edits import EditError
from app.schema import Project, Slide, SponsorSlot


@pytest.fixture
def cut(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'shoots')
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'Original picture and audio')
    footage._save(footage.Shoot('shoot', files=[footage.SourceFile('source', str(source), duration=20)]))
    p = Project(id='ptrims', idea='Trim fixture', use_intro=False, use_outro=False, music='',
        slides=[Slide(id=f's{i}', narration='Spoken words.', gap_override=2,
                      take={'path':f'takes/{i}.wav', 'duration':4}) for i in range(3)])
    p.style.picture_every = 2
    p.slides.append(Slide(id='clip', insert=dict(kind='clip', shoot_id='shoot',
        source_id='source', in_s=2., out_s=6., seconds=4., source_audio=False)))
    p.slides.append(Slide(id='card', insert=dict(kind='card', text='End', seconds=3.)))
    store.save(p)
    recording = store.project_dir(p.id) / 'takes' / '0.wav'
    recording.write_bytes(b'Recorded audio')
    before = [(f, f.read_bytes(), f.stat().st_mtime_ns) for f in (source, recording)]
    yield store.load(p.id)
    for f, data, stamp in before:
        assert f.read_bytes() == data and f.stat().st_mtime_ns == stamp


def trim(p, sid='s1', edge='end', delta=1., roll=False):
    return timeline_trims.apply(p, dict(sid=sid, edge=edge, delta=delta, roll=roll, version=p.updated_at))


def test_ripple_group_tail_and_speech(cut):
    old = render.timeline(cut)
    changed, delta = trim(cut)
    new = render.timeline(changed)
    assert delta == 1 and new['total']-old['total'] == pytest.approx(1)
    assert new['segments'][0]['duration']-old['segments'][0]['duration'] == pytest.approx(1)
    assert all(b['start']-a['start'] == pytest.approx(1) for a, b in zip(old['segments'][1:], new['segments'][1:]))
    changed, delta = trim(cut, delta=-100)
    assert delta == -2 and changed.slide('s1').gap_override == 0
    assert [s.take for s in changed.slides] == [s.take for s in cut.slides]
    assert trim(cut, delta=100)[0].slide('s1').gap_override == 10
    with pytest.raises(EditError, match='Speech'):
        trim(cut, edge='start')


def test_roll_clamps_neighbour_and_preserves_total(cut):
    changed, delta = trim(cut, delta=100, roll=True)
    assert delta == 2 and changed.slide('s2').gap_override == 0
    assert render.timeline(changed)['total'] == render.timeline(cut)['total']
    changed, delta = trim(cut, 'clip', 'start', 100, True)
    assert delta == 2 and changed.slide('clip').insert['in_s'] == 0
    assert changed.slide('s2').gap_override == 0
    assert render.timeline(changed)['total'] == render.timeline(cut)['total']
    with pytest.raises(EditError, match='neighbour'):
        trim(cut, 'card', roll=True)
    cut.sponsors = [SponsorSlot(id='ad', placement='mid', after_slide_id='s1', script='Read')]
    with pytest.raises(EditError, match='sponsor'):
        trim(cut, roll=True)


def test_insert_bounds_slip_and_validation(cut):
    changed, delta = trim(cut, 'clip', delta=100)
    assert delta == 14 and changed.slide('clip').insert['out_s'] == 20
    changed, delta = trim(cut, 'clip', 'start', -100)
    assert delta == pytest.approx(-3.95) and changed.slide('clip').insert['seconds'] == pytest.approx(.05)
    changed, delta = trim(cut, 'clip', 'slip', 100)
    assert delta == 14 and changed.slide('clip').insert['seconds'] == 4
    assert changed.slide('clip').insert['in_s'] == 16
    assert trim(cut, 'clip', 'slip', -100)[0].slide('clip').insert['in_s'] == 0
    assert trim(cut, 'card', delta=-100)[0].slide('card').insert['seconds'] == pytest.approx(.05)
    original = deepcopy(cut.to_dict())
    for delta in (float('nan'), float('inf'), True):
        with pytest.raises(EditError):
            trim(cut, delta=delta)
    assert cut.to_dict() == original


def test_atomic_http_roll_undo_and_conflict(cut, monkeypatch):
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    original = cut.to_dict()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            url = f'/api/projects/{cut.id}'
            payload = dict(sid='s1', edge='end', delta=1, roll=True, version=cut.updated_at)
            response = await client.patch(url+'/trim', json=payload, headers={'X-Edit-Label':'roll trim', 'X-Edit-Gesture':'drag-1'})
            assert response.status_code == 200, response.text
            assert len(undo.read(store.project_dir(cut.id))['states']) == 2
            assert store.load(cut.id).slide('s2').gap_override == 1
            assert (await client.patch(url+'/trim', json=payload)).status_code == 409
            assert (await client.post(url+'/undo')).status_code == 200
            assert store.load(cut.id).to_dict() == original
            await client.post(url+'/redo')
            assert store.load(cut.id).slide('s1').gap_override == 3
    asyncio.run(run())

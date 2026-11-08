"""Stage readiness uses synthetic data only; never render or contact an LLM."""
import asyncio
from copy import deepcopy
import json
from time import perf_counter

import httpx
import pytest

from app import cli, store
from app.schema import Project, Slide
from app.stages import readiness_check, render_signature, stages


@pytest.fixture
def episode():
    p = Project(id='stages-fixture', idea='Readiness fixture',
                outline={'sections': [{'heading': 'Opening'}]},
                slides=[Slide(id=f's{i}', narration='A fixture paragraph.') for i in range(4)])
    p.style.picture_every = 2
    for s in p.slides:
        p.set_take(s, 'mic', {'path': f'takes/{s.id}.wav', 'duration': 3})
        s.chosen_id = s.id
        s.candidates = [{'id': s.id, 'local_path': f'media/{s.id}.jpg'}]
    return p


def states(p, check=None):
    return {r['id']: r for r in stages(p, readiness_check(p) if check is None else check)}


def test_empty_project_and_contract():
    p = Project(id='empty', idea='Empty')
    before = deepcopy(p)
    rows = stages(p, readiness_check(p))
    assert [r['id'] for r in rows] == ['plan', 'script', 'voice', 'visuals', 'edit', 'publish']
    assert all(r['status'] == 'todo' for r in rows)
    fields = {'id', 'label', 'status', 'reason', 'next'}
    assert all(set(r) == fields | ({'rules', 'rule'} if r['id'] == 'visuals' else set()) for r in rows)
    assert all(len(r['reason']) < 28 and r['next'] for r in rows)
    assert p == before


def test_complete_and_publish_freshness(episode):
    p = episode
    assert all(r['status'] == 'ready' for k, r in states(p).items() if k != 'publish')
    assert states(p)['publish']['status'] == 'todo'
    p.render = {'output': 'out/video.mp4', 'stage_signature': render_signature(p)}
    assert states(p)['publish']['status'] == 'ready'
    store.save(p)
    assert states(store.load(p.id))['publish']['status'] == 'ready'
    p.updated_at += 50
    p.status = 'rendered'
    p.log.append('Saved')
    p.description = 'Upload description'
    p.render['youtube_url'] = 'fixture'
    assert states(p)['publish']['status'] == 'ready'
    p.slides[0].narration += ' Changed.'
    assert states(p)['publish']['reason'] == 'Render again'


@pytest.mark.parametrize('field', ['narration', 'take', 'chosen_id', 'gap_override', 'cues'])
def test_render_inputs_stale_output(episode, field):
    p = episode
    old = render_signature(p)
    setattr(p.slides[0], field, {'narration': 'New words', 'take': {'path': 'new.wav'},
                              'chosen_id': 'new', 'gap_override': 1.4,
                              'cues': {'blocks': [{'block': 'fixture'}]}}[field])
    assert render_signature(p) != old


@pytest.mark.parametrize('extra', [{}, {'preview': True}])
def test_legacy_and_preview_outputs_need_render(episode, extra):
    episode.render = {'output': 'out/video.mp4', **extra}
    if extra:
        episode.render['stage_signature'] = render_signature(episode)
    assert states(episode)['publish']['status'] == 'warn'


def test_plan_draft_and_partial_script(episode):
    p = episode
    p.outline = {}
    assert states(p)['plan']['status'] == 'todo'
    p.draft = {'outline': {'sections': [{'heading': 'Draft'}]}}
    assert states(p)['plan']['reason'] == '1 beat'
    p.slides[0].narration = '  '
    assert states(p)['script']['status'] == 'in_progress'
    assert states(p)['edit']['status'] != 'ready'


def test_active_voices_drafts_and_legacy(episode):
    p = episode
    p.use_track('kokoro')
    assert states(p)['voice']['status'] == 'todo'  # inactive mic reads do not count
    for s in p.slides:
        p.set_take(s, 'kokoro', {'path': f'takes/draft-{s.id}.wav', 'synthetic': True})
    assert states(p)['voice']['status'] == 'ready'
    assert states(p)['voice']['reason'] == '4 draft reads'
    p.set_take(p.slides[0], 'kokoro', None)
    assert states(p)['voice']['reason'] == '3 of 4 read · draft'
    assert states(p)['voice']['status'] == 'in_progress'
    legacy = Project.from_dict({'id': 'old', 'idea': 'Old', 'slides': [
        {'narration': 'Legacy', 'take': {'path': 'old.wav'}, 'unknown': True}]})
    assert states(legacy)['voice']['status'] == 'ready'


def test_shared_picture_runs(episode):
    p = episode
    for s in p.slides[1::2]:
        s.chosen_id = ''
    assert states(p)['visuals']['reason'] == '2 pictures'
    p.slides[1].picture_mode = 'new'
    assert states(p)['visuals']['reason'] == '2 need a picture'
    p.slides[1].picture_mode = 'hold'
    assert states(p)['visuals']['status'] == 'ready'
    p.slides[1].chapter = 'New chapter'
    assert states(p)['visuals']['status'] == 'in_progress'
    p.slides[0].chosen_id = 'not-in-candidates'
    assert states(p)['edit']['reason'] == '1 P0'


@pytest.mark.parametrize('fmt', ['board', 'loudmouth', 'casefile', 'flameboat', 'groupchat', 'ticker'])
def test_generated_visuals(episode, fmt):
    episode.style.format = fmt
    for s in episode.slides:
        s.candidates = []
    assert states(episode)['visuals']['status'] == 'ready'
    assert not readiness_check(episode)['findings']


def test_custom_and_3d_layouts(episode):
    p = episode
    p.style.format = 'custom:fixture'
    assert states(p)['visuals']['status'] == 'todo'
    for s in p.slides:
        s.custom_html = '<p>Fixture scene</p>'
    assert states(p)['visuals']['status'] == 'ready'
    p.style.format = 'stage'
    for s in p.slides:
        s.visual_note = '3D: fixture'
    assert states(p)['visuals']['status'] == 'todo'
    for s in p.slides:
        s.shot = {'solved': {'shot': {'camera': 'fixture'}}}
    assert states(p)['visuals']['status'] == 'ready'


def test_camera_layout_and_p0(episode):
    p = episode
    p.delivery = 'on_camera'
    for s in p.slides:
        s.on_camera = True
        p.set_take(s, 'camera', {'path': 'camera.wav', 'video': 'camera.mp4'})
    assert states(p)['voice']['label'] == 'Camera'
    assert states(p)['visuals']['reason'] == '4 pictures'
    p.slides[0].take['av_offset'] = .1
    assert states(p)['edit']['reason'] == '1 P0'
    p.slides[0].take['sync_corrected'] = True
    assert states(p)['edit']['status'] == 'ready'
    del p.slides[0].take['video']
    assert states(p)['visuals']['status'] == 'in_progress'


def test_supplied_full_check_findings(episode):
    assert states(episode, {'counts': {'P0': 2}})['edit']['reason'] == '2 P0'
    assert states(episode, {'findings': [{'level': 'P0', 'code': 'future_timing'}]})['edit']['status'] == 'warn'
    assert states(episode, {'findings': [{'level': 'P1'}]})['edit']['status'] == 'ready'


def test_under_20ms_for_40_paragraphs(episode):
    episode.slides = [deepcopy(episode.slides[i % 4]) for i in range(40)]
    for s in episode.slides:
        s.take['words'] = [{'w': 'fixture', 'start': i * .2, 'end': (i+1) * .2}
                           for i in range(100)]
    episode.render = {'output': 'out/fixture.mp4', 'stage_signature': render_signature(episode)}
    start = perf_counter()
    result = stages(episode, readiness_check(episode))
    elapsed = (perf_counter() - start) * 1000
    assert elapsed < 20, f'{elapsed:.1f} ms'
    assert result[-1]['status'] == 'ready'


def test_cli_and_http_agree(episode, monkeypatch, capsys):
    from app import main
    store.save(episode)
    expected = stages(store.load(episode.id), readiness_check(store.load(episode.id)))
    assert cli.main(['stages', episode.id]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://fixture') as client:
            response = await client.get(f'/api/projects/{episode.id}/stages')
            assert response.status_code == 200
            assert response.json() == expected
            assert (await client.get('/api/projects/missing/stages')).status_code == 404
    asyncio.run(exercise())

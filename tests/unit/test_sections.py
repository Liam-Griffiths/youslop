"""Section edits use synthetic metadata and never render or rewrite media."""
import asyncio

import httpx
import pytest

from app import main, render, sections, store, storyboard, undo
from app.schema import Project, Slide, SponsorSlot


@pytest.mark.parametrize('kind', ['clip', 'block', 'picture', 'card'])
def test_move_delete_undo_and_attachments(kind, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    p = Project(id='psection', idea='Synthetic sections', use_intro=False, use_outro=False, music='',
        slides=[Slide(id=f's{i}', narration=f'Paragraph {i}', title=f'Title {i}', title_at=.4,
            gap_override=.5, take={'path':f'takes/{i}.wav', 'duration':4, 'words':[]},
            cues={'loudmouth':[{'kind':'phrase', 'text':'Anchored', 'at':.6}]},
            overlays=[{'id':f'g{i}', 'block_id':'lower_third_panel', 'vars':{}, 'at':.2, 'dur':1}])
            for i in range(5)])
    p.style.format = 'loudmouth'
    p.style.picture_every = 1
    p.slides[2].chapter = 'Travelling chapter'
    # Missing sources are intentional: edits must not resolve, copy or encode them.
    p.slides.insert(3, Slide(id='insert', insert={'kind':kind, 'seconds':2, 'text':'Card',
        'shoot_id':'absent', 'source_id':'absent', 'asset_id':'absent', 'block':'title_card', 'vars':{}}))
    p.sponsors = [SponsorSlot(id='read', placement='mid', after_slide_id='s2', script='Synthetic read')]
    store.save(p)
    media = store.project_dir(p.id) / 'takes' / '0.wav'
    media.write_bytes(b'Untouched recording')
    stamp = media.stat().st_mtime_ns
    original = store.load(p.id).to_dict()
    old_timeline = render.timeline(p)
    def paragraphs(timeline):
        return [q for seg in timeline['segments'] for q in seg['paragraphs']]
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            path = f'/api/projects/{p.id}'
            payload = dict(op='move', ids=['s1','s2','insert'], to='s0', version=p.updated_at)
            response = await client.post(path+'/sections', json=payload)
            assert response.status_code == 200, response.text
            moved = store.load(p.id)
            assert [s.id for s in moved.slides] == ['s1','s2','insert','s0','s3','s4']
            assert moved.slide('s2').chapter == 'Travelling chapter'
            assert moved.sponsors[0].after_slide_id == 's2'
            for row in moved.slides:
                before = next(s for s in original['slides'] if s['id'] == row.id)
                assert all(row.to_dict().get(k) == before.get(k) for k in
                           ('take', 'takes', 'history', 'title_at', 'overlays', 'cues', 'insert'))
            timeline = render.timeline(moved)
            assert [q['id'] for q in paragraphs(timeline)] == [s.id for s in moved.slides]
            assert [q['id'] for q in storyboard.build(moved)['paragraphs']] == [s.id for s in moved.slides]
            for lane in ('graphics', 'cues'):
                for before in old_timeline['layers'][lane]:
                    after = next(x for x in timeline['layers'][lane] if x['id'] == before['id'])
                    a = next(q for q in paragraphs(old_timeline) if q['id'] == before['sid'])
                    b = next(q for q in paragraphs(timeline) if q['id'] == before['sid'])
                    assert after['t0']-b['start'] == pytest.approx(before['t0']-a['start'], abs=.001)
            assert len(undo.read(store.project_dir(p.id))['states']) == 2
            restored = await client.post(path+'/undo')
            assert restored.json()['edit_label'] == 'Moved 2 paragraphs and 1 insert'
            assert store.load(p.id).to_dict() == original
            await client.post(path+'/redo')
            payload.update(op='delete', version=store.load(p.id).updated_at)
            response = await client.post(path+'/sections', json=payload)
            assert response.status_code == 200
            deleted = store.load(p.id)
            assert [s.id for s in deleted.slides] == ['s0','s3','s4'] and not deleted.sponsors
            assert deleted.retired_takes  # Removed recordings remain referenced.
            after = render.timeline(deleted)
            qs = paragraphs(after)
            assert qs[1]['start'] == pytest.approx(qs[0]['start']+qs[0]['duration'], abs=.001)
            await client.post(path+'/undo')
            assert store.load(p.id).to_dict() == moved.to_dict()
            all_rows = [s.id for s in moved.slides]
            response = await client.post(path+'/sections', json=dict(op='delete', ids=all_rows,
                version=moved.updated_at))
            assert response.status_code == 200 and not store.load(p.id).slides
            assert not render.timeline(store.load(p.id))['segments']
            await client.post(path+'/undo')
            assert store.load(p.id).to_dict() == moved.to_dict()
    asyncio.run(run())
    assert media.read_bytes() == b'Untouched recording'
    assert media.stat().st_mtime_ns == stamp


def test_groups_stale_validation_and_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='pgroups', idea='Synthetic groups', slides=[Slide(id=f's{i}', narration='Synthetic paragraph') for i in range(6)])
    p.style.picture_every = 3
    p.slides[0].chosen_id = 'original-picture'
    store.save(p)
    request = dict(op='move', ids=['s1','s2'], to='s4', version=p.updated_at)
    result = main.edit_section(p.id, request)
    moved = store.load(p.id)
    assert moved.picture_runs() == [['s0'], ['s3'], ['s1','s2'], ['s4','s5']]
    assert moved.slide('s1').chosen_id == 'original-picture'
    assert 'split' in result['section_hint']
    before = (store.project_dir(p.id) / 'project.json').read_bytes()
    for patch, status in [({},409), ({'version':moved.updated_at,'ids':['s0','s2']},400),
            ({'version':moved.updated_at,'ids':['missing']},409),
            ({'version':moved.updated_at,'ids':['s0','s0']},400),
            ({'version':moved.updated_at,'to':'missing'},400)]:
        with pytest.raises(main.HTTPException) as exc:
            main.edit_section(p.id, request | patch)
        assert exc.value.status_code == status
        assert (store.project_dir(p.id) / 'project.json').read_bytes() == before
    monkeypatch.setattr(main.jobs, 'active_for', lambda pid, writing: [dict(writes=writing)])
    with pytest.raises(main.HTTPException) as exc:
        main.edit_section(p.id, request | {'version':moved.updated_at})
    assert exc.value.status_code == 409


def test_time_sponsors_follow_original_paragraph_and_whole_groups():
    p = Project(id='ptime', idea='Synthetic anchors', use_intro=False, use_outro=False,
        slides=[Slide(id=f's{i}', narration='Words') for i in range(6)])
    p.style.picture_every = 3
    p.sponsors = [SponsorSlot(id='time', placement='mid', at_s=0)]
    sections.apply(p, dict(op='move', ids=['s0','s1','s2'], to='', version=p.updated_at))
    assert p.picture_runs() == [['s3','s4','s5'], ['s0','s1','s2']]
    assert p.sponsors[0].after_slide_id == 's0'


@pytest.mark.parametrize('op', ['move', 'delete'])
def test_pre_end_sponsors_keep_placement_rules(op):
    p = Project(id='pplacements', idea='Synthetic sponsor placement',
        use_intro=False, use_outro=False,
        slides=[Slide(id=f's{i}', narration='Words', gap_override=0,
            take={'path':f'takes/{i}.wav', 'duration':5}) for i in range(5)])
    p.style.picture_every = 1
    p.frame.hook_s = 8
    # Suggestions may include an after_slide_id even for pre/end rules.
    p.sponsors = [SponsorSlot(id='pre', placement='pre', after_slide_id='s1'),
                  SponsorSlot(id='end', placement='end', after_slide_id='s4'),
                  SponsorSlot(id='anchored', placement='mid', after_slide_id='s2', at_s=0),
                  SponsorSlot(id='disabled', placement='mid', at_s=0, enabled=False)]
    original = [s.to_dict() for s in p.sponsors]
    sections.apply(p, dict(op=op, ids=['s4'], to='s0', version=p.updated_at))
    assert [s.to_dict() for s in p.sponsors] == original
    timeline = render.timeline(p)['segments']
    reads = {s['sponsor']: i for i, s in enumerate(timeline) if s['type'] == 'sponsor'}
    assert 'disabled' not in reads
    assert timeline[-1]['sponsor'] == 'end'
    # Five-second paragraphs: the first boundary after the eight-second hook
    # follows the second paragraph, whatever its new identity is.
    assert timeline[reads['pre']-1]['paragraphs'][-1]['id'] == p.slides[1].id
    assert timeline[reads['anchored']-1]['paragraphs'][-1]['id'] == 's2'

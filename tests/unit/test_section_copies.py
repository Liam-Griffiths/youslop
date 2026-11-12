"""Detached section copies and shared recordings, with synthetic files only."""
import asyncio
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from app import audio, main, render, store, undo
from app.schema import Project, Slide, SponsorSlot


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    take = dict(path='takes/shared.wav', raw_path='raw/shared.webm', duration=4, words=[])
    p = Project(id='pcopies', idea='Synthetic copy fixture', use_intro=False, use_outro=False,
        slides=[Slide(id=f's{i}', narration=f'Paragraph {i}', gap_override=.5, take=deepcopy(take),
            title='Title', title_at=.4, cues={'loudmouth':[{'kind':'phrase','text':'Cue','at':.6}]},
            overlays=[{'id':f'g{i}','block_id':'lower_third_panel','vars':{'title':'Graphic'},'at':.2,'dur':1}])
            for i in range(4)])
    p.style.picture_every = 3
    p.slides[0].chosen_id = 'shared-picture'
    p.slides[2].chapter = 'Chapter'
    p.slides[3:3] = [Slide(id='i'+kind, insert={'kind':kind,'seconds':2,'text':'Card',
        'block':'title_card','vars':{},'asset_id':'missing','shoot_id':'missing','source_id':'missing'})
        for kind in ('clip','block','picture','card')]
    p.sponsors = [SponsorSlot(id='read', placement='mid', after_slide_id='s2', script='Read', take=deepcopy(take))]
    store.save(p)
    root = store.project_dir(p.id)
    for path in ('takes/shared.wav', 'raw/shared.webm'):
        (root/path).write_bytes(b'Synthetic recording')
    return p


def test_copy_cut_paste_duplicate_atomic_and_detached(project):
    p = project
    ids = [s.id for s in p.slides[1:-1]]
    root = store.project_dir(p.id)
    files = {f:(f.read_bytes(), f.stat().st_mtime_ns) for f in root.rglob('*') if f.is_file() and f.suffix != '.json'}
    original = store.load(p.id).to_dict()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            path = f'/api/projects/{p.id}'
            async def edit(op, **extra):
                r = await client.post(path+'/sections', json=dict(op=op, ids=ids,
                    version=store.load(p.id).updated_at, **extra))
                assert r.status_code == 200, r.text
                return r.json()
            result = await edit('copy')
            clip = result['section_clipboard']
            assert store.load(p.id).to_dict() == original
            assert not undo.read(root)['states']
            assert clip['slides'][0]['chosen_id'] == 'shared-picture'  # middle of a picture run
            assert {s['insert']['kind'] for s in clip['slides'] if 'insert' in s} == {'clip','block','picture','card'}
            await edit('duplicate')
            copied = store.load(p.id)
            clones = copied.slides[1+len(ids):1+2*len(ids)]
            assert {s.id for s in clones}.isdisjoint(ids)
            assert len({s.id for s in copied.slides}) == len(copied.slides)
            for source, clone in zip(clip['slides'], clones):
                assert all(clone.to_dict()[k] == source[k] for k in ('takes','history','title_at','cues','chapter'))
                assert clone.take == source['take']
                assert clone.duplicate_of == (source['id'] if clone.narration else '')
                if clone.overlays:
                    assert clone.overlays[0]['id'] != source['overlays'][0]['id']
            assert copied.sponsors[1].id != 'read'
            assert copied.sponsors[1].after_slide_id == clones[1].id
            assert copied.sponsors[1].take == copied.sponsors[0].take
            def start(proj):
                return next(q['start'] for s in render.timeline(proj)['segments'] for q in s['paragraphs'] if q['id']=='s3')
            assert start(copied) > start(p) + 16  # two reads, all inserts and sponsor ripple
            assert len(undo.read(root)['states']) == 2
            response = await client.post(path+'/undo')
            assert response.json()['edit_label'] == 'Duplicated 2 paragraphs and 4 inserts'
            assert store.load(p.id).to_dict() == original
            await client.post(path+'/redo')
            assert store.load(p.id).to_dict() == copied.to_dict()
            await client.post(path+'/undo')
            # Change the source after Copy. Paste must use the detached snapshot.
            changed = store.load(p.id)
            changed.slide('s1').narration = 'Changed after copying'
            changed.slide('s1').overlays[0]['vars']['title'] = 'Changed'
            store.save(changed)
            baseline = store.load(p.id).to_dict()
            result = await edit('paste', to='s3', clipboard=clip)
            pasted = store.load(p.id)
            assert pasted.slides[-1-len(ids)].narration == 'Paragraph 1'
            assert pasted.slides[-1-len(ids)].overlays[0]['vars']['title'] == 'Graphic'
            await client.post(path+'/undo')
            assert store.load(p.id).to_dict() == baseline
            # Cut captures before removing rows; its clipboard survives deletion.
            result = await edit('cut')
            assert len(store.load(p.id).slides) == 2
            assert not store.load(p.id).sponsors
            assert (await client.post(path+'/undo')).json()['edit_label'] == 'Cut 2 paragraphs and 4 inserts'
            assert store.load(p.id).to_dict() == baseline
            await client.post(path+'/redo')
            await edit('paste', to='', clipboard=result['section_clipboard'])
            assert store.load(p.id).slides[-len(ids)].narration == 'Changed after copying'
            before = (root/'project.json').read_bytes()
            for patch in ({'version':0}, {'clipboard':{'project_id':'other'}}, {'to':'missing'}):
                r = await client.post(path+'/sections', json=dict(op='paste', to='',
                    clipboard=clip, version=store.load(p.id).updated_at) | patch)
                assert r.status_code in (400,409)
                assert (root/'project.json').read_bytes() == before
    asyncio.run(run())
    assert all((f.read_bytes(),f.stat().st_mtime_ns) == state for f,state in files.items())


def test_shared_take_retire_reprocess_delete_and_prune(project, monkeypatch):
    p, root = project, store.project_dir(project.id)
    old = deepcopy(p.slides[0].take)
    original = {f:(f.read_bytes(),f.stat().st_mtime_ns) for f in (root/'takes/shared.wav',root/'raw/shared.webm')}
    # Re-record one duplicate, retaining only that owner's reference in history.
    from fastapi import UploadFile
    from tempfile import SpooledTemporaryFile
    def process(raw, out, voice):
        assert not out.exists(), 'shared take would be rewritten'
        out.write_bytes(b'New derived read')
        return {'duration':4}
    monkeypatch.setattr(main.audio_mod, 'process_take', process)
    monkeypatch.setattr(main.words_mod, 'estimate', lambda *args: [])
    upload = SpooledTemporaryFile()
    upload.write(b'x'*2048)
    upload.seek(0)
    asyncio.run(main.upload_take(p.id, 's1', UploadFile(filename='new.webm',file=upload)))
    current = store.load(p.id)
    assert current.slide('s1').history[0]['path'] == old['path']
    assert not current.slide('s0').history and current.slide('s0').take == old
    assert current.sponsors[0].take == old
    main.delete_take(p.id, 's1')
    assert store.load(p.id).slide('s0').take == old
    assert main.reprocess_takes(p.id)['reprocessed'] == 3
    current = store.load(p.id)
    assert len({s.take['path'] for s in current.slides if s.take}) == 3
    assert current.sponsors[0].take == old
    # Deletions outside undo tracking also retain unique recordings.
    main.delete_slide(p.id, 's0')
    assert store.load(p.id).retired_takes
    monkeypatch.setattr(undo, 'MAX_ENTRIES', 1)
    for title in ('one','two','three'):
        token = undo.edit_source.set((title, title))
        try:
            current = store.load(p.id)
            current.title = title
            store.save(current)
        finally:
            undo.edit_source.reset(token)
    assert len(undo.read(root)['states']) == 2
    assert all((f.read_bytes(),f.stat().st_mtime_ns) == state for f,state in original.items())
    store.delete(p.id)
    assert not store.exists(p.id) and not store.list_projects()


def test_processing_refuses_existing_output(tmp_path):
    path = tmp_path/'shared.wav'
    path.write_bytes(b'Untouched')
    with pytest.raises(ValueError, match='fresh path'):
        audio.process_take(tmp_path/'raw.webm', path)
    assert path.read_bytes() == b'Untouched'


def test_presenter_raw_source_survives_replacement_and_removal(project, monkeypatch):
    from fastapi import UploadFile
    from tempfile import SpooledTemporaryFile
    p, root = project, store.project_dir(project.id)
    (root/'presenter').mkdir()
    source = root/'presenter/clip.mp4'
    source.write_bytes(b'Original camera recording')
    p.presenter.path = 'presenter/clip.mp4'
    p.slides[0].takes['mic']['raw_path'] = p.presenter.path
    store.save(p)
    stamp = source.stat().st_mtime_ns
    monkeypatch.setattr(main.ffutil, 'duration', lambda path: 3)
    monkeypatch.setattr(main.ffutil, 'dimensions', lambda path: (640,480))
    monkeypatch.setattr(main.ffutil, 'has_audio', lambda path: True)
    upload = SpooledTemporaryFile()
    upload.write(b'x'*5000)
    upload.seek(0)
    result = asyncio.run(main.upload_presenter(p.id, UploadFile(filename='camera.mp4',file=upload)))
    assert result['presenter']['path'] != 'presenter/clip.mp4'
    main.delete_presenter(p.id)
    assert source.read_bytes() == b'Original camera recording' and source.stat().st_mtime_ns == stamp
    assert store.load(p.id).slides[0].take['raw_path'] == 'presenter/clip.mp4'

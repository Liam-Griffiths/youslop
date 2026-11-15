"""Bin routes use synthetic bytes and ASGI, without browsers or media renders."""
import asyncio
import io
import json

import httpx
from PIL import Image

from app import footage, main, project_bin, store, undo
from app.schema import BinItem, Project, Slide


def test_model_round_trip():
    old = Project.from_dict({'id':'old', 'idea':'Old', 'unknown':True})
    assert old.bin == old.labels == []
    old.bin = [BinItem.from_dict({'id':'n', 'kind':'note', 'note':'Text', 'future':1, 'used_in':['ignored']})]
    old.labels = ['Place']
    assert Project.from_dict(old.to_dict()).to_dict() == old.to_dict()
    assert 'used_in' not in old.to_dict()['bin'][0]


def test_routes_labels_undo_and_preservation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    async def direct(fn, *args, **kwargs):
        kwargs.pop("limiter", None)
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    monkeypatch.setattr('starlette.responses.anyio.to_thread.run_sync', direct)
    store.save(Project(id='pbin', idea='Synthetic bin'))
    root = store.project_dir('pbin')
    recording = root / 'raw' / 'recording.webm'
    recording.write_bytes(b'Keep this recording')
    image = io.BytesIO()
    Image.new('RGB', (16, 12), 'red').save(image, 'PNG')
    # Probe and thumbnail extraction are mocked for the fake video only.
    thumb = project_bin.library._make_thumb
    monkeypatch.setattr(project_bin.ffutil, 'duration', lambda path: 2)
    monkeypatch.setattr(project_bin.ffutil, 'dimensions', lambda path: (16, 12))
    def thumbnail(src, kind, stem, **kwargs):
        return thumb(src if kind == 'image' else next(root.glob('bin/*.png')), 'image', stem, **kwargs)
    monkeypatch.setattr(project_bin.library, '_make_thumb', thumbnail)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            base = '/api/projects/pbin/bin'
            assert (await client.get(base)).json() == {'items':[], 'labels':[]}
            result = await client.post(base, files=[('files', (name, image.getvalue())) for name in ['Pneumatic_tube.png', 'Station-entrance.png', 'Photo.v2.png']] + [('files', ('Morning-commute_clip.mp4', b'fake video'))])
            assert result.status_code == 200, result.text
            items = result.json()['items']
            assert len(items) == 4 and [i['kind'] for i in items] == ['image']*3+['clip']
            assert [i['title'] for i in items] == ['Pneumatic tube', 'Station entrance', 'Photo.v2', 'Morning commute clip']
            assert len(undo.read(root)['states']) == 2  # One edit for the whole batch.
            for item in items:
                assert (await client.get(item['thumb'])).status_code == 200
                assert item['width'] == 16
            ident, rel = items[0]['id'], items[0]['file']
            path = base+'/'+ident
            assert (await client.patch(path, json={'labels':['Place'], 'title':'Door'})).json()['labels'] == ['Place']
            await client.post('/api/projects/pbin/undo')
            assert store.load('pbin').bin[0].labels == []
            await client.post('/api/projects/pbin/redo')
            result = await client.patch(base+'/labels', json={'old':'Place', 'new':'Street'})
            assert result.json()['items'][0]['labels'] == ['Street']
            assert (await client.patch(path, json={'labels':'bad'})).status_code == 400
            await client.post(base+'/note', json={'title':'Note', 'note':'Research **kept**'})
            await client.post(base+'/link', json={'url':'https://example.test/source'})
            assert (await client.post(base+'/link', json={'url':'javascript:alert(1)'})).status_code == 400
            p = store.load('pbin')
            p.slides = [Slide(id='chosen', chosen_id='candidate', candidates=[{'id':'candidate','local_path':rel}]),
                        Slide(id='unused', candidates=[{'id':'other', 'local_path':rel}]),
                        Slide(id='overlay', overlays=[{'vars':{'image':ident}}]),
                        Slide(id='insert', insert={'kind':'picture','asset_id':ident,'seconds':2})]
            store.save(p)
            rows = (await client.get(base)).json()['items']
            assert rows[0]['used_in'] == ['chosen','overlay','insert']
            assert (await client.delete(path)).status_code == 200
            removed = root/'bin'/'.removed'/rel.split('/')[-1]
            assert removed.read_bytes() == image.getvalue() and not (root/rel).exists()
            await client.post('/api/projects/pbin/undo')
            assert (await client.get(path+'/file')).content == image.getvalue()
            assert (await client.delete(path)).status_code == 200  # Repeated removal after undo.
            assert removed.read_bytes() == image.getvalue()
            assert (await client.post(base, files={'files':('bad.exe',b'bad')})).status_code == 400
            assert (await client.get('/api/projects/missing/bin')).status_code == 404
            # References retain external bytes and identify existing edit uses.
            external = tmp_path/'external.png'
            external.write_bytes(image.getvalue())
            monkeypatch.setattr(project_bin.library, 'get', lambda ident: dict(kind='image', title='External', width=16, height=12, duration=0) if ident == 'asset' else None)
            monkeypatch.setattr(project_bin.library, 'file_path', lambda ident: external)
            monkeypatch.setattr(project_bin.library, 'thumb_path', lambda ident: external)
            monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path/'shoots')
            footage._save(footage.Shoot('s1', files=[footage.SourceFile('f1', source_path=str(external))], clips=[footage.Clip('c1','f1',1,3)]))
            for source in ['library:asset', 'footage:s1/c1']:
                linked = (await client.post(base+'/link', json={'source':source})).json()['items'][-1]
                assert linked['file'] == '' and linked['source'] == source
            p = store.load('pbin')
            p.slides.extend([Slide(id='lib', insert={'asset_id':'asset','seconds':2}),
                Slide(id='ft', chosen_id='fts1_c1', candidates=[{'id':'fts1_c1'}])])
            store.save(p)
            references = (await client.get(base)).json()['items'][-2:]
            assert [r['used_in'] for r in references] == [['lib'],['ft']]
            for row in references:
                await client.delete(base+'/'+row['id'])
            assert external.read_bytes() == image.getvalue()
            p = store.load('pbin')
            p.bin.append(BinItem(id='unsafe', file='raw/recording.webm'))
            store.save(p)
            assert (await client.delete(base+'/unsafe')).status_code == 400
    asyncio.run(run())
    assert recording.read_bytes() == b'Keep this recording'
    assert 'used_in' not in json.loads((root/'project.json').read_text())['bin'][0]

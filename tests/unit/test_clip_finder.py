"""Synthetic ranges only: no inference, originals never modified."""
import pytest

from app import audio, clip_finder as finder, footage, jobs, stt, transcripts


@pytest.fixture
def recording(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'shoots')
    path = tmp_path / 'original.wav'
    path.write_bytes(b'original recording')
    before = path.stat()
    footage._save(footage.Shoot('s1', files=[footage.SourceFile('f1', str(path), duration=100)],
                               clips=[footage.Clip('old', 'f1', 0, 100)]))
    monkeypatch.setattr(audio, '_levels', lambda p: [-60]*50 + [-20]*450 + [-60]*50 + [-15]*4450)
    yield path
    assert path.read_bytes() == b'original recording'
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_manual_word_selection_cache_and_backwards_compatibility(recording, monkeypatch):
    # Pauses at 0–1 and 10–11, manual marks near either edge.
    c = finder.create('s1', 'f1', dict(in_s=1.1, out_s=9.9, title='Moment'))
    assert (c['in_s'], c['out_s']) == pytest.approx((.7, 10.3))
    assert c['title'] == 'Moment' and c['finder'] and c['file'] == 'f1'
    monkeypatch.setattr(audio, '_levels', lambda p: pytest.fail('must reuse envelope'))
    timing = [dict(w=w, start=a, end=b, src='stt') for w,a,b in
              [('So',1.1,1.3), ('the',1.3,1.5), ('changed',9.4,9.6), ('everything.',9.6,9.9)]]
    transcripts._write(transcripts._path('s1','f1'), dict(words=timing, coverage=[[0,100]], segments=[]))
    c = finder.create('s1','f1',dict(in_s=1.2,out_s=9.8,words=True))
    assert (c['in_s'], c['out_s']) == pytest.approx((.7,10.3))
    assert footage.load('s1').clips[0].id == 'old'
    assert not footage.Clip.from_dict({'id':'legacy','file':'f1','unknown':1}).finder
    assert len(finder.read('s1','f1')['waveform']) <= 1024


def test_range_transcription_and_refinement(recording, monkeypatch):
    c = finder.create('s1','f1',dict(in_s=20,out_s=30))
    received = []
    monkeypatch.setattr(transcripts.ffutil, 'run', lambda args: __import__('pathlib').Path(args[-1]).write_bytes(b'fake wav'))
    def engine(name, path, **kw):
        received.append((kw['start'],kw['end']))
        yield dict(start=21,end=29,text='Hello.',words=[dict(w='Hello.',start=21,end=29)])
    monkeypatch.setattr(stt,'transcribe',engine)
    monkeypatch.setattr(transcripts,'mark_turns',lambda *args: None)
    transcripts.transcribe('s1','f1',engine='fake',model='fake',start=c['in_s'],end=c['out_s'])
    assert received == [(20,30)]
    updated = finder.create('s1','f1',dict(in_s=20,out_s=30,refine=c['id']))
    assert (updated['in_s'],updated['out_s']) == (21,29)
    assert transcripts.load('s1','f1')['coverage'] == [[20,30]]


def test_offline_windows_complete_endings_and_whole_coverage():
    doc = dict(coverage=[[0,180]],segments=[dict(start=i*10,end=i*10+9,text=('Why 42?' if i%3==0 else 'Because it changed.')) for i in range(18)])
    env = dict(levels=[-20]*9000,runs=[[0,180]])
    results = finder.suggestions(doc,180,env)
    assert results and len(results)<=10
    assert all(20<=s['out_s']-s['in_s']<=90 for s in results)
    assert all(s['out_s'] in [x['end'] for x in doc['segments']] for s in results)
    doc['coverage']=[[0,90]]
    assert finder.suggestions(doc,180,env)==[]


@pytest.mark.parametrize('payload', [dict(in_s=-1,out_s=2),dict(in_s=True,out_s=2),
    dict(in_s=2,out_s=1),dict(in_s=0,out_s=101),dict(title=[]),dict(words='true'),dict(oops=1)])
def test_invalid_does_not_edit(recording,payload):
    before=footage.load('s1').to_dict()
    with pytest.raises(ValueError): finder.create('s1','f1',payload)
    assert footage.load('s1').to_dict()==before


def test_processing_and_uncovered_refinement(recording, monkeypatch):
    c=finder.create('s1','f1',dict(in_s=20,out_s=30))
    with pytest.raises(ValueError,match='Transcribe'):
        finder.create('s1','f1',dict(in_s=20,out_s=30,refine=c['id']))
    monkeypatch.setattr(jobs,'active_for',lambda sid:[object()])
    with pytest.raises(footage.ProcessingError): finder.create('s1','f1',dict(in_s=20,out_s=30))


def test_api_source_validation_and_persistence(recording, monkeypatch):
    import asyncio
    import httpx
    from app.main import app
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            base='/api/footage/shoots/s1/finder/'
            assert (await client.get(base+'missing')).status_code==404
            assert (await client.post(base+'f1',json={'out_s':101})).status_code==400
            created=await client.post(base+'f1',json={'in_s':20,'out_s':30,'title':'Keep me'})
            assert created.status_code==200 and created.json()['title']=='Keep me'
            result=await client.get(base+'f1')
            assert result.status_code==200 and result.json()['transcript']['words']==[]
    asyncio.run(run())


def test_ranking_estimate_confirmation_and_small_schema(monkeypatch):
    from app import llm
    candidates=[dict(in_s=0,out_s=30,title='Question?',reason='complete sentence')]
    monkeypatch.setattr(finder,'read',lambda *args: dict(suggestions=candidates,transcript=dict(words=[dict(w='Why?',start=0,end=1,src='stt')])) )
    calls=[]
    def fake(prompt, **kw):
        calls.append(prompt)
        assert kw['require']([dict(id=0,hook='A short hook')])
        assert not kw['require']([dict(id=99,hook='Bad')])
        assert not kw['require']([dict(id=0,hook='x'),dict(id=0,hook='y')])
        return [dict(id=0,hook='A short hook')]
    monkeypatch.setattr(llm,'complete_json',fake)
    estimate=finder.rank('s1','f1',{})
    assert estimate['input_tokens']>0 and not calls
    with pytest.raises(ValueError): finder.rank('s1','f1',dict(confirm=True,estimate={}))
    result=finder.rank('s1','f1',dict(confirm=True,estimate=estimate))
    assert result[0]['hook']=='A short hook' and len(calls)==1
    assert 'Why?' in calls[0] and 'audio' not in calls[0]


def test_shot_detection_keeps_named_ranges(recording, monkeypatch):
    c=finder.create('s1','f1',dict(in_s=0,out_s=100,title='Whole moment'))
    monkeypatch.setattr(footage,'_complete',lambda path: True)
    monkeypatch.setattr(footage,'_shot_signals',lambda path: (100,30,[],[],[]))
    monkeypatch.setattr(footage,'_shot_boundaries',lambda *args: [0,100])
    footage.detect_shots('s1')
    clips=footage.load('s1').clips
    assert [x.id for x in clips].count(c['id'])==1
    assert next(x for x in clips if x.id==c['id']).title=='Whole moment'
    assert any(x.id=='old' and not x.finder for x in clips)


def test_rank_endpoint_runs_confirmed_ranking_as_job(monkeypatch):
    from fastapi import HTTPException
    from app import main
    estimate = dict(input_tokens=5, output_tokens=512, fingerprint='f')
    ran = []
    monkeypatch.setattr(finder, 'rank', lambda sid, fid, payload: ran.append(payload) or (
        estimate if payload.get('confirm') is not True else [dict(hook='h')]))
    started = []
    def start(kind, pid, worker):
        started.append((kind, pid)); return dict(result=worker(lambda m: None))
    monkeypatch.setattr(main.jobs, 'start', start)
    assert main.clip_finder_rank('s1', 'f1', {}) == estimate and not started
    with pytest.raises(HTTPException):
        main.clip_finder_rank('s1', 'f1', dict(confirm=True, estimate={}))
    assert not started
    job = main.clip_finder_rank('s1', 'f1', dict(confirm=True, estimate=estimate))
    assert started == [('clip ranking', 's1')] and job['job']['result'] == [dict(hook='h')]

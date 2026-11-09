"""Offline integration: synthetic audio, fake engines and explicit API actions."""
import asyncio
import wave

import httpx
import pytest
from PIL import Image

from app import ffutil, footage, footage_export, footage_labels, jobs, stt, transcripts
from app.main import app


@pytest.fixture
def audio(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    path = tmp_path / 'recording.wav'
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\0\0' * 32000)
    before = path.read_bytes()
    shoot = footage.import_shoot(path)
    monkeypatch.setattr(footage, '_proxy', lambda *a: pytest.fail('audio must not make a video proxy'))
    footage.process_and_detect(shoot.id)
    shoot = footage.load(shoot.id)
    yield shoot, shoot.files[0], path
    assert path.read_bytes() == before


def test_audio_import_logger_and_video_audit(audio, tmp_path):
    shoot, source, path = audio
    assert source.kind == 'audio' and source.duration == 2
    assert footage.SourceFile.from_dict({'id': 'old', 'future': 1}).kind == 'video'
    proxy, sprite = footage._outputs(shoot, source)
    assert not proxy.exists()
    with Image.open(sprite) as image:
        assert image.size == (1600, 90)
    assert footage.status(shoot.id)['ready'] == 1
    assert footage.media_path(shoot.id, 'audio', source.id) == path
    with pytest.raises(FileNotFoundError):
        footage.media_path(shoot.id, 'audio', '../recording.wav')
    assert len(shoot.clips) == 1 and shoot.clips[0].out_s == 2
    assert not shoot.clips[0].quality
    assert footage_labels.estimate(shoot.id)['clips'] == 0
    from app.media.footage import suggestions
    assert suggestions('recording') == []
    for mode in ('encode', 'copy'):
        footage_export.export_clips(shoot.id, [shoot.clips[0].id], tmp_path / mode, mode=mode)
        files = list((tmp_path / mode).glob('*.m4a' if mode == 'encode' else '*.mka'))
        assert len(files) == 1
        assert all(s['codec_type'] == 'audio' for s in ffutil.probe(files[0])['streams'])
    # Re-processing preserves the manually trimmed audio clip.
    footage.edit_clips(shoot.id, [shoot.clips[0].id], {'in_s': .5, 'out_s': 1.5})
    footage.process_and_detect(shoot.id)
    assert footage.load(shoot.id).clips[0].in_s == .5


@pytest.fixture
def api_request(monkeypatch):
    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    def call(method, path, payload=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as c:
                return await c.request(method, path, json=payload)
        return asyncio.run(run())
    return call


def test_api_defaults_overrides_validation_and_confirmation(audio, api_request, tmp_path, monkeypatch):
    shoot, source, path = audio
    base = f'/api/footage/shoots/{shoot.id}/transcripts/{source.id}'
    model = tmp_path / 'model.bin'
    model.write_bytes(b'fake local model')
    engines = {name: dict(installed=True) for name in stt.ENGINES}
    monkeypatch.setattr(stt, 'configured', lambda **kw: engines)
    monkeypatch.setenv('CORKBORED_STT_ENGINE', 'whisper.cpp')
    monkeypatch.setenv('CORKBORED_STT_MODEL', str(model))
    monkeypatch.setenv('CORKBORED_STT_EXECUTABLE', '/fake/whisper-cli')
    options = []
    monkeypatch.setattr(transcripts, 'start_job', lambda sid, fid, **kw: options.append(kw) or 'fakejob')
    assert api_request('GET', base).json()['coverage'] == []
    assert api_request('GET', base.replace(source.id, 'unknown')).status_code == 404
    estimate = api_request('POST', base + '/estimate', {}).json()
    assert estimate['seconds'] == 2 and estimate['engine'] == 'whisper.cpp'
    assert options == []
    assert api_request('POST', base + '/start', {}).status_code == 400
    for bad in ({'start': -1}, {'end': 3}, {'start': True}, {'retranscribe': 'yes'},
                {'language': []}, {'engine': 'unknown'}, {'model': '/nonexistent'}, {'oops': True}):
        assert api_request('POST', base + '/start', {**bad, 'confirm': True}).status_code == 400
    assert options == []
    assert api_request('POST', base + '/start', {'confirm': True}).json()['job'] == 'fakejob'
    assert options[-1]['executable'] == '/fake/whisper-cli'
    assert api_request('POST', base + '/start', {'confirm': True, 'engine': 'faster-whisper'}).status_code == 200
    assert options[-1]['device'] == 'cpu' and 'executable' not in options[-1]
    # Legacy transcript missing optional keys still accepts a persistent correction.
    transcripts._write(transcripts._path(shoot.id, source.id), {'words': [dict(w='old', start=0, end=1)]})
    edited = api_request('PATCH', base, dict(start=0, end=1, text='Name'))
    assert edited.status_code == 200 and edited.json()['words'][0]['w'] == 'Name'
    assert api_request('PATCH', base, dict(start=0, end=3, text='bad')).status_code == 400
    monkeypatch.setattr(jobs, 'active_for', lambda sid: [object()])
    assert api_request('POST', base + '/start', {'confirm': True}).status_code == 409


def test_missing_engines_setup_settings(api_request, monkeypatch):
    monkeypatch.setattr(stt.importlib.util, 'find_spec', lambda name: None)
    monkeypatch.setattr(stt.shutil, 'which', lambda name: None)
    try:
        response = api_request('GET', '/api/stt/engines?refresh=true')
        assert response.status_code == 200
        assert all(not e['installed'] and e['install_url'] for e in response.json().values())
        assert stt.setup_status()['detail'] == 'none installed (optional)'
        fields = api_request('GET', '/api/settings').json()['fields']
        assert {f['key'] for f in fields if f['group'] == 'Speech-to-text'} == {
            'stt_engine', 'stt_model', 'stt_folder', 'stt_executable', 'stt_device'}
    finally:
        stt._detect.cache_clear()


@pytest.mark.parametrize('engine,extra', [('whisper.cpp', {'executable': '/fake/cli'}),
                                         ('faster-whisper', {'device': 'cuda'})])
def test_worker_forwards_adapter_options(audio, monkeypatch, engine, extra):
    shoot, source, path = audio
    calls = []
    def fake(name, wav, **kwargs):
        calls.append((name, kwargs))
        yield dict(start=0, end=1, text='Hello.', words=[dict(w='Hello.', start=0, end=1)])
    monkeypatch.setattr(stt, 'transcribe', fake)
    result = transcripts.transcribe(shoot.id, source.id, engine=engine, model='fake', **extra)
    assert result['coverage'] == [[0, 2]] and result['words'][0]['engine'] == engine
    assert all(calls[0][1][key] == value for key, value in extra.items())


def test_measured_estimate_and_replacement_resume(audio, api_request, tmp_path, monkeypatch):
    shoot, source, path = audio
    base = f'/api/footage/shoots/{shoot.id}/transcripts/{source.id}'
    model = tmp_path / 'model.bin'
    model.write_bytes(b'fake')
    monkeypatch.setattr(stt, 'configured', lambda **kw: {'openai-whisper': {'installed': True}})
    options = dict(engine='openai-whisper', model=str(model), retranscribe=True)
    calls = []
    def fake(*a, **kw):
        calls.append(kw)
        yield dict(start=0, end=1, text='word.', words=[dict(w='word.', start=0, end=1, src='stt')])
    monkeypatch.setattr(stt, 'transcribe', fake)
    real_monotonic = transcripts.time.monotonic
    clock = iter([0, 4, 4])
    monkeypatch.setattr(transcripts.time, 'monotonic', lambda: next(clock))
    # Complete chunk saved, crash before marking the replacement plan complete.
    original_write = transcripts._write
    def crash(path, value):
        if path.name.endswith('.run.json') and value['complete']:
            raise jobs.JobCancelled()
        original_write(path, value)
    monkeypatch.setattr(transcripts, '_write', crash)
    with pytest.raises(jobs.JobCancelled):
        transcripts.transcribe(shoot.id, source.id, **options)
    monkeypatch.setattr(transcripts.time, 'monotonic', real_monotonic)
    assert len(calls) == 1
    estimate = api_request('POST', base + '/estimate', options).json()
    assert estimate['seconds'] == 0 and estimate['chunks'] == 0 and estimate['runtime_seconds'] == 0
    assert len(calls) == 1  # Estimate never starts inference.
    whole = api_request('POST', base + '/estimate', {**options, 'retranscribe': False, 'start': 0, 'end': 1}).json()
    assert whole['runtime_seconds'] == 2
    assert 'Approximate' in whole['detail']
    model.write_bytes(b'changed')
    changed = api_request('POST', base + '/estimate', options).json()
    assert changed['seconds'] == 2 and changed['runtime_seconds'] is None

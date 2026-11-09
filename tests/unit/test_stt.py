"""All engines are fake: no optional imports, downloads or recorded media."""
import json
import sys
import wave
from types import SimpleNamespace as NS

import pytest

from app import footage, jobs, stt, transcripts


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    original = tmp_path / 'recording.mp4'
    original.write_bytes(b'original')
    shoot = footage.Shoot('shoot', str(original))
    shoot.files = [footage.SourceFile('file', str(original), duration=1500)]
    footage._save(shoot)
    def extract(args):
        with wave.open(args[-1], 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * 16000)
    monkeypatch.setattr(transcripts.ffutil, 'run', extract)
    return shoot


def fake_engine(calls):
    def run(engine, path, *, start, end, **kwargs):
        calls.append((engine, start, end))
        # Every chunk sees overlapping context including an exact seam word.
        yield dict(start=start, end=end, text='speech', words=[
            dict(w=str(i), start=i, end=i+.25, p=.9)
            for i in range(max(0, int(start)-2), min(1500, int(end)+2))])
    return run


def test_ranges_gap_fill_and_overrides(source, monkeypatch):
    calls = []
    monkeypatch.setattr(stt, 'transcribe', fake_engine(calls))
    run = lambda **kw: transcripts.transcribe('shoot', 'file', engine='fake', model='small', **kw)
    first = run(start=754.2, end=812.9)
    assert all(754.2 <= w['start'] < w['end'] <= 812.9 for w in first['words'])
    second = run(start=1000, end=1061)
    assert second['words'][:len(first['words'])] == first['words']
    transcripts.override('shoot', 'file', 755, 755.25, 'Name')
    run(start=754.2, end=812.9, retranscribe=True)
    assert next(w for w in transcripts.load('shoot', 'file')['words'] if w['start'] == 755)['w'] == 'Name'
    calls.clear()
    result = run()
    assert result['coverage'] == [[0, 1500]]
    assert [(a, b) for _, a, b in calls] == [(0, 600), (600, 754.2), (812.9, 1000), (1061, 1500)]
    transcripts.transcribe('shoot', 'file', engine='other', model='large', start=1000, end=1001)
    word = next(w for w in transcripts.load('shoot', 'file')['words'] if w['start'] == 1000)
    assert (word['engine'], word['model']) == ('other', 'large')


def test_cancel_resume_seams(source, monkeypatch):
    calls = []
    monkeypatch.setattr(stt, 'transcribe', fake_engine(calls))
    def progress(message):
        if message.startswith('chunk 2'):
            raise jobs.JobCancelled()
    with pytest.raises(jobs.JobCancelled):
        transcripts.transcribe('shoot', 'file', engine='fake', model='small', progress=progress)
    assert transcripts.load('shoot', 'file')['coverage'] == [[0, 600]]
    resumed = transcripts.transcribe('shoot', 'file', engine='fake', model='small')
    assert [(a, b) for _, a, b in calls] == [(0, 600), (600, 1200), (1200, 1500)]
    uninterrupted = transcripts.transcribe('shoot', 'file', engine='fake', model='small', retranscribe=True)
    assert resumed['words'] == uninterrupted['words']
    assert len(resumed['words']) == 1500
    assert len(list((footage.shoot_dir('shoot') / 'transcripts/file.chunks').glob('*.json'))) == 3


def test_detection_missing_cached_and_broken(monkeypatch):
    monkeypatch.setattr(stt.importlib.util, 'find_spec', lambda name: None)
    monkeypatch.setattr(stt.shutil, 'which', lambda name: None)
    assert all(not info['installed'] and info['install_url'] for info in stt.detect(refresh=True).values())
    monkeypatch.setattr(stt.importlib.util, 'find_spec', lambda name: True)
    assert not stt.detect()['faster-whisper']['installed']
    assert stt.detect(refresh=True)['faster-whisper']['installed']
    monkeypatch.setattr(stt.importlib, 'import_module', lambda *a: (_ for _ in ()).throw(ImportError('broken runtime')))
    with pytest.raises(ImportError):
        list(stt.transcribe('faster-whisper', 'unused'))
    assert 'broken runtime' in stt.detect()['faster-whisper']['notes']
    assert not stt.detect()['openai-whisper']['notes']
    stt._detect.cache_clear()
    stt._ERRORS.clear()


@pytest.mark.parametrize('engine', ['faster-whisper', 'openai-whisper', 'mlx-whisper', 'whisper.cpp'])
def test_adapter_contract(tmp_path, monkeypatch, engine):
    wav = tmp_path / 'input.wav'
    with wave.open(str(wav), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\0\0' * 16000 * 8)
    model = tmp_path / 'model'
    model.mkdir()
    word = dict(word=' Hello', start=2., end=2.5, probability=.8)
    result = dict(segments=[dict(start=2., end=2.5, text='Hello', words=[word])])
    monkeypatch.setitem(sys.modules, 'whisper', NS(load_model=lambda *a, **k: NS(transcribe=lambda *a, **k: result)))
    monkeypatch.setitem(sys.modules, 'mlx_whisper', NS(transcribe=lambda *a, **k: result))
    monkeypatch.setitem(sys.modules, 'faster_whisper', NS(WhisperModel=lambda *a, **k: NS(
        transcribe=lambda *a, **k: ([NS(start=2., end=2.5, text='Hello', words=[NS(**word)])], None))))
    class Process:
        def __init__(self, command, **kw):
            assert '-ojf' in command
            output = command[command.index('-of')+1] + '.json'
            with open(output, 'w') as out:
                json.dump(dict(transcription=[dict(offsets={'from': 2000, 'to': 2500}, text='Hello', tokens=[
                    dict(text=' Hel', offsets={'from': 2000, 'to': 2200}, p=.8),
                    dict(text='lo', offsets={'from': 2200, 'to': 2500}, p=.8)])]), out)
        def wait(self, **kw): return 0
        def poll(self): return 0
    from app.stt import cpp
    monkeypatch.setattr(cpp.subprocess, 'Popen', Process)
    segments = list(stt.transcribe(engine, wav, model=str(model), start=4, end=5,
                                   progress=lambda m: None, cancel=lambda: None))
    assert segments[0]['words'] == [dict(w='Hello', start=4., end=4.5, p=.8)]


def test_segment_fallback_and_cache_recovery(source, monkeypatch):
    def run(*args, **kwargs):
        yield dict(start=10, end=12, text='two words', words=[])
    monkeypatch.setattr(stt, 'transcribe', run)
    result = transcripts.transcribe('shoot', 'file', engine='fake', model='small', start=10, end=12)
    assert [w['src'] for w in result['words']] == ['stt-seg', 'stt-seg']
    assert result['words'][0]['start'] == 10 and result['words'][-1]['end'] == 12
    transcripts._path('shoot', 'file').unlink()  # Simulate crash before transcript merge, retain chunk.
    monkeypatch.setattr(stt, 'transcribe', lambda *a, **k: pytest.fail('must reuse completed chunk'))
    assert transcripts.transcribe('shoot', 'file', engine='fake', model='small', start=10, end=12)['words'] == result['words']


def test_padding_does_not_become_segment_fallback():
    from app.stt.common import local_model, normalize
    rows = [dict(start=0, end=3, text='padding', words=[dict(w='padding', start=0, end=1, p=.9)])]
    assert list(normalize(rows, 0, 2, 3, lambda: None)) == []
    with pytest.raises(ValueError, match='never downloads'):
        local_model('/nonexistent/corkbored-stt-test-model')

"""Take retention using isolated storage and synthetic audio only."""
import asyncio
import io
import wave
from tempfile import SpooledTemporaryFile
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from app import main, store
from app.audio_files import next_raw_path, next_take_path
from app.schema import Project, Slide


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x01\x00' * 1600)
    return out.getvalue()


@pytest.fixture
def saved(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='ptest', idea='Synthetic', slides=[Slide(narration='First sentence. Second sentence.')])
    store.save(p)
    return p


@pytest.fixture
def fake_audio(monkeypatch):
    def process(raw, out, voice):
        Path(out).write_bytes(Path(raw).read_bytes())
        return {'duration': .2, 'recorded_at': 1}
    monkeypatch.setattr(main.audio_mod, 'process_take', process)
    monkeypatch.setattr(main.words_mod, 'estimate', lambda *args: [])


def recording(body):
    file = SpooledTemporaryFile()
    file.write(body)
    file.seek(0)
    return UploadFile(filename="synthetic.wav", file=file)


def upload(p, body=None):
    return asyncio.run(main.upload_take(p.id, p.slides[0].id,
                       recording(body if body is not None else wav_bytes())))


def test_two_uploads_restore_and_reprocess(saved, fake_audio, monkeypatch):
    p, sid = saved, saved.slides[0].id
    root = store.project_dir(p.id)
    upload(p)
    first = store.load(p.id).slides[0].take
    original = (root / first['path']).read_bytes()
    # Fail on any unlink: neither upload, restore nor reprocess may remove audio.
    monkeypatch.setattr(Path, 'unlink', lambda *a, **k: pytest.fail('audio unlink'))
    upload(p)
    s = store.load(p.id).slides[0]
    assert len(list((root / 'raw').glob('*'))) == 2
    assert len(list((root / 'takes/mic').glob('*'))) == 2
    assert len(s.history) == 1 and s.history[0]['reason'] == 'rerecord'
    second = s.take['path']
    assert second != first['path']
    assert (root / first['path']).read_bytes() == original
    assert main.take_history(p.id, sid)['history'][0]['url'].endswith(first['path'])
    res = main.restore_take(p.id, sid, 0)
    assert res['stale'] is False
    assert res['slide']['take']['path'] == first['path']
    assert res['slide']['history'][0]['path'] == second
    main.reprocess_takes(p.id)
    assert len(store.load(p.id).slides[0].history) == 1
    assert (root / first['path']).read_bytes() == original


def test_rewrite_clears_all_tracks_and_stale_restore(saved, monkeypatch):
    p, s = saved, saved.slides[0]
    for track in ['mic', 'kokoro']:
        p.set_take(s, track, {'path': f'takes/{track}/old.wav', 'synthetic': track != 'mic'})
    store.save(p)
    monkeypatch.setattr(main.script_gen, 'rewrite_slide', lambda *a: 'Changed narration.')
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: fn(lambda msg: None))
    main.rewrite(p.id, s.id, {})
    s = store.load(p.id).slides[0]
    assert not s.takes and s.take is None
    assert len(s.history) == 2
    assert {x['reason'] for x in s.history} == {'rewrite'}
    assert main.restore_take(p.id, s.id, 0)['stale'] is True
    assert store.load(p.id).voice_track == 'mic'


def test_revoice_fresh_paths(saved, monkeypatch):
    p, s = saved, saved.slides[0]
    def speak(text, out, *a, **kw):
        out.write_bytes(wav_bytes())
        return {'synthetic': True, 'engine': 'kokoro', 'duration': .2}
    monkeypatch.setattr(main.tts_mod, 'speak_to_file', speak)
    root = store.project_dir(p.id)
    for _ in range(2):
        p.set_take(s, 'kokoro', main._voice_one(p, s, root, {}))
    assert len(list((root / 'takes/kokoro').glob('*.wav'))) == 2
    assert s.history[0]['reason'] == 'revoice'


def test_old_schema_and_history_snapshot():
    s = Slide.from_dict({'narration': 'old', 'unknown': True})
    assert s.history == []
    p = Project(id='ptest', idea='Synthetic', slides=[s])
    p.set_take(s, 'mic', {'path': 'old.wav', 'words': [{'start': 0}]})
    old = s.take
    p.set_take(s, 'mic', {'path': 'new.wav'})
    old['words'][0]['start'] = 8
    assert s.history[0]['words'][0]['start'] == 0
    assert Project.from_dict(p.to_dict()).slides[0].history == s.history


def test_names_skip_existing_and_empty_upload(saved):
    root = store.project_dir(saved.id)
    for allocate in [lambda: next_raw_path(root, 's'), lambda: next_take_path(root, 'mic', 's')]:
        first = allocate()
        first.write_bytes(b'old')
        second = allocate()
        second.write_bytes(b'new')
        assert allocate().name.startswith('s.3.')
        assert first.read_bytes() == b'old'
    with pytest.raises(HTTPException) as err:
        upload(saved, b'')
    assert err.value.status_code == 400
    assert not (root / 'raw' / f'{saved.slides[0].id}.webm').exists()


def test_bad_history_index(saved):
    for n in [-1, 0]:
        with pytest.raises(HTTPException) as err:
            main.restore_take(saved.id, saved.slides[0].id, n)
        assert err.value.status_code == 404


def test_mic_setup_preserves_previous(saved, fake_audio, monkeypatch):
    monkeypatch.setattr(main.audio_mod, 'analyse', lambda raw: {})
    for _ in range(2):
        asyncio.run(main.voice_test(saved.id, recording(wav_bytes())))
    p = store.load(saved.id)
    root = store.project_dir(p.id)
    assert len(list((root / 'raw').glob('_mictest*'))) == 2
    assert len(list((root / 'takes').glob('_mictest*'))) == 2
    assert (root / p.mic_test['raw_path']).exists()
    assert (root / p.mic_test['path']).exists()


def test_failed_processing_preserves_recordings(saved, fake_audio, monkeypatch):
    upload(saved)
    before = store.load(saved.id).slides[0].take
    root = store.project_dir(saved.id)
    def fail(*a):
        raise ValueError("synthetic failure")
    monkeypatch.setattr(main.audio_mod, 'process_take', fail)
    with pytest.raises(HTTPException):
        upload(saved)
    assert store.load(saved.id).slides[0].take == before
    assert len(list((root / 'raw').glob('*.webm'))) == 2
    assert (root / before['path']).read_bytes() == wav_bytes()


def test_mic_preview_failure_keeps_old_output(saved, fake_audio, monkeypatch):
    monkeypatch.setattr(main.audio_mod, 'analyse', lambda raw: {})
    asyncio.run(main.voice_test(saved.id, recording(wav_bytes())))
    p = store.load(saved.id)
    old = store.project_dir(p.id) / p.mic_test['path']
    monkeypatch.setattr(main.audio_mod, 'process_take', lambda *a: (_ for _ in ()).throw(ValueError('failed')))
    assert main.voice_preview(p.id, {})['error'] == 'failed'
    assert old.read_bytes() == wav_bytes()
    assert Project.from_dict(p.to_dict()).mic_test == p.mic_test


def test_retired_audio_is_seekable(saved, fake_audio):
    from starlette.requests import Request
    upload(saved)
    upload(saved)
    take = main.take_history(saved.id, saved.slides[0].id)['history'][0]
    request = Request({'type': 'http', 'headers': [(b'range', b'bytes=0-43')]})
    rel = take['url'].split('/file/', 1)[1]
    response = main.project_file(saved.id, rel, request)
    assert response.status_code == 206
    assert response.body == wav_bytes()[:44]
    assert response.headers['accept-ranges'] == 'bytes'


def test_restore_other_track_keeps_selected_voice(saved, fake_audio):
    upload(saved)
    p = store.load(saved.id)
    s = p.slides[0]
    p.set_take(s, 'kokoro', {'path': 'takes/kokoro/old.wav', 'synthetic': True})
    p.set_take(s, 'kokoro', {'path': 'takes/kokoro/new.wav', 'synthetic': True})
    store.save(p)
    restored = main.restore_take(p.id, s.id, 0)['slide']
    assert restored['takes']['kokoro']['path'] == 'takes/kokoro/old.wav'
    assert restored['take']['path'] == s.take['path']
    assert store.load(p.id).voice_track == 'mic'

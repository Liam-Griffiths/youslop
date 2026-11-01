"""Camera takes use only synthetic media and isolated project storage."""
import asyncio
import json
from pathlib import Path
from tempfile import SpooledTemporaryFile

import pytest
from fastapi import HTTPException, UploadFile

from app import audio, camera, ffutil, main, store, storyboard, render
from app.schema import CAMERA_TRACK, Project, Slide, take_track


def test_active_take_and_roundtrip():
    s = Slide(narration="Synthetic words")
    p = Project(id="ptestcamera", idea="Synthetic", slides=[s])
    p.set_take(s, 'mic', {'path': 'mic.wav', 'duration': 1})
    p.set_take(s, CAMERA_TRACK, {'path': 'camera.wav', 'video': 'camera.mp4', 'kind': 'camera'})
    assert p.voice_track == 'mic' and s.take['path'] == 'mic.wav'
    s.on_camera = True
    p.sync_takes()
    assert p.active_take(s) is s.takes[CAMERA_TRACK] is s.take
    p.use_track('kokoro')
    assert s.take['video'] == 'camera.mp4'
    s.take['duration'] = 2
    q = Project.from_dict(p.to_dict())
    assert q.slides[0].take['duration'] == 2
    assert take_track(q.slides[0].take) == CAMERA_TRACK
    s.on_camera = False
    p.sync_takes()
    assert s.take is None and s.takes['mic']['path'] == 'mic.wav'
    p.use_track('mic')
    assert s.take['path'] == 'mic.wav'


def test_camera_only_does_not_select_voice():
    s = Slide(on_camera=True)
    p = Project(id='ptestcamera', idea='Synthetic', slides=[s])
    p.set_take(s, CAMERA_TRACK, {'path': 'cam.wav', 'kind': 'camera'})
    p.sync_takes()
    assert p.voice_track == '' and s.take['path'] == 'cam.wav'
    p.use_track('mic')
    assert s.take['path'] == 'cam.wav'


def test_old_fixture_roundtrip():
    fixture = Path(__file__).parents[1] / 'fixtures/project_min/project.json'
    old = json.loads(fixture.read_text())
    assert all('on_camera' not in s for s in old['slides'])
    p = Project.from_dict(old)
    before = p.to_dict()
    q = Project.from_dict(before)
    assert q.to_dict() == before
    assert not any(s.on_camera for s in q.slides)
    assert [s.take for s in q.slides] == [s.take for s in p.slides]
    # Also exercise pre-multi-voice files, with a take but no takes dictionary.
    legacy = {'id': 'plegacy', 'idea': 'Old', 'slides': [
        {'id': 'sold', 'narration': 'Old words', 'take': {'path': 'takes/sold.wav', 'duration': 1.2}}]}
    p = Project.from_dict(legacy)
    assert p.voice_track == 'mic' and p.slides[0].take['path'] == 'takes/sold.wav'
    assert Project.from_dict(p.to_dict()).to_dict() == p.to_dict()


def test_old_active_take_metadata_is_preserved():
    old = {'id': 'plegacy', 'idea': 'Old', 'voice_track': 'mic', 'slides': [
        {'id': 'sold', 'take': {'path': 'old.wav', 'duration': 2},
         'takes': {'mic': {'path': 'old.wav', 'duration': 1}}}]}
    p = Project.from_dict(old)
    assert p.slides[0].take['duration'] == 2
    assert Project.from_dict(p.to_dict()).to_dict() == p.to_dict()


@pytest.fixture(scope='module')
def synthetic(tmp_path_factory):
    raw = tmp_path_factory.mktemp('camera') / 'synthetic.mkv'
    ffutil.run(['-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=1.8',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1.8',
                '-af', "volume=enable='lt(t,0.4)+gte(t,1.1)':volume=0",
                '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'pcm_s16le', str(raw)], threads=1)
    return raw


def test_real_processing(synthetic, tmp_path, monkeypatch):
    spans = []
    original = audio.process_take
    def observe(raw, out, voice):
        meta = original(raw, out, voice)
        spans.append(meta['trimmed'])
        return meta
    monkeypatch.setattr(audio, 'process_take', observe)
    wav, mp4 = tmp_path / 'voice.wav', tmp_path / 'picture.mp4'
    before = synthetic.read_bytes()
    meta = camera.process_camera_take(synthetic, wav, mp4)
    assert meta['trimmed'] == spans[0]
    start, end = meta['trimmed']
    assert 0 < start < .4 and 1.1 < end < 1.8
    assert abs(ffutil.duration(mp4) - ffutil.duration(wav) - meta['tail']) <= 1 / 30
    assert meta['tail'] == pytest.approx(1.8 - end, abs=.002)
    assert (meta['width'], meta['height'], meta['fps']) == (640, 360, 30)
    assert not ffutil.has_audio(mp4)
    assert synthetic.read_bytes() == before
    with pytest.raises(ValueError, match='fresh'):
        camera.process_camera_take(synthetic, wav, mp4)


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='ptestcamera', idea='Synthetic', slides=[Slide(narration='Synthetic words')])
    p.set_take(p.slides[0], 'mic', {'path': 'original.wav', 'duration': 1})
    store.save(p)
    return p


def upload(p, body):
    stream = SpooledTemporaryFile()
    stream.write(body)
    stream.seek(0)
    return asyncio.run(main.upload_camera(p.id, p.slides[0].id,
                       UploadFile(filename='synthetic.mkv', file=stream)))


def test_upload_history_toggle_restore(saved, synthetic, monkeypatch):
    def process(raw, wav, mp4, voice):
        wav.write_bytes(b'synthetic voice')
        mp4.write_bytes(b'synthetic picture')
        return {'duration': 1, 'kind': 'camera', 'av_offset': .12, 'sync_warning': True}
    monkeypatch.setattr(camera, 'process_camera_take', process)
    monkeypatch.setattr(main.words_mod, 'estimate', lambda *a: [])
    first = upload(saved, synthetic.read_bytes())['slide']['take']
    root = store.project_dir(saved.id)
    files = {k: (root / first[k]).read_bytes() for k in ('path', 'video', 'raw_path')}
    second = upload(saved, synthetic.read_bytes())['slide']['take']
    s = store.load(saved.id).slides[0]
    assert s.on_camera and len(s.history) == 1
    assert s.history[0]['video'] == first['video']
    assert all(first[k] != second[k] for k in files)
    assert all((root / first[k]).read_bytes() == value for k, value in files.items())
    assert 'check sync' in store.load(saved.id).log[-1]
    main.patch_slide(saved.id, s.id, {'on_camera': False})
    s = store.load(saved.id).slides[0]
    assert s.take['path'] == 'original.wav' and CAMERA_TRACK in s.takes
    main.patch_slide(saved.id, s.id, {'on_camera': True})
    assert store.load(saved.id).slides[0].take['video'] == second['video']
    main.restore_take(saved.id, s.id, 0)
    s = store.load(saved.id).slides[0]
    assert s.take['video'] == first['video'] and s.history[-1]['video'] == second['video']
    p = store.load(saved.id)
    para = storyboard.build(p)['paragraphs'][0]
    assert para['on_camera'] and para['take']['video'] == first['video']
    assert render.timeline(p)['segments'][0]['paragraphs'][0]['on_camera']


def test_failed_upload_retains_raw_and_current(saved, synthetic, monkeypatch):
    def fail(*args):
        raise ValueError('synthetic failure')
    monkeypatch.setattr(camera, 'process_camera_take', fail)
    with pytest.raises(HTTPException, match='400'):
        upload(saved, synthetic.read_bytes())
    p = store.load(saved.id)
    assert p.slides[0].take['path'] == 'original.wav'
    assert len(list((store.project_dir(p.id) / 'raw').iterdir())) == 1
    with pytest.raises(HTTPException):
        main.patch_slide(p.id, p.slides[0].id, {'on_camera': 'true'})


@pytest.mark.parametrize('offset', [-.15, .2])
def test_stream_offset_and_accurate_picture(synthetic, tmp_path, monkeypatch, offset):
    from PIL import Image, ImageChops, ImageStat
    # Remux with distinct nonzero stream starts; common timeline origin must
    # not affect the correction. Audio starts at .2, video at .2 - offset.
    raw = tmp_path / 'offset.mkv'
    ffutil.run(['-itsoffset', str(.2 - offset), '-i', str(synthetic),
                '-itsoffset', '0.2', '-i', str(synthetic),
                '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', str(raw)], threads=1)
    def process(raw, wav, voice):
        ffutil.run(['-i', str(raw), '-ss', '0.4', '-t', '0.6', str(wav)], threads=1)
        return {'trimmed': [.4, 1.0], 'duration': .6}
    monkeypatch.setattr(audio, 'process_take', process)
    wav, mp4 = tmp_path / 'voice.wav', tmp_path / 'picture.mp4'
    meta = camera.process_camera_take(raw, wav, mp4)
    assert meta['av_offset'] == pytest.approx(offset, abs=1 / 30)
    assert meta['sync_warning']
    assert meta['video_start'] == pytest.approx(.4 + meta['av_offset'])
    # Compare the first picture to a reference accurate seek on a reset
    # source timeline. This catches applying the offset with the wrong sign.
    reference, actual = tmp_path / 'ref.png', tmp_path / 'actual.png'
    ffutil.run(['-i', str(synthetic), '-ss', str(meta['video_start']),
                '-frames:v', '1', str(reference)], threads=1)
    ffutil.run(['-i', str(mp4), '-frames:v', '1', str(actual)], threads=1)
    error = ImageStat.Stat(ImageChops.difference(Image.open(reference), Image.open(actual)))
    assert max(error.mean) < 5


@pytest.mark.parametrize('streams, message', [
    ([{'codec_type': 'video', 'width': 320}, {'codec_type': 'audio'}], '640'),
    ([{'codec_type': 'video', 'width': 640}], 'both'),
    ([{'codec_type': 'audio'}], 'both'),
])
def test_reject_invalid_media(tmp_path, monkeypatch, streams, message):
    monkeypatch.setattr(ffutil, 'probe', lambda p: {'streams': streams})
    with pytest.raises(ValueError, match=message):
        camera.process_camera_take(tmp_path / 'raw', tmp_path / 'wav', tmp_path / 'mp4')
    assert not (tmp_path / 'wav').exists()


def test_real_upload(saved, synthetic, monkeypatch):
    monkeypatch.setattr(main.words_mod, 'estimate', lambda *a: [])
    take = upload(saved, synthetic.read_bytes())['slide']['take']
    root = store.project_dir(saved.id)
    assert take['trimmed'][0] > 0
    assert abs(ffutil.duration(root / take['video']) - take['duration'] - take['tail']) <= 1 / 30
    assert store.load(saved.id).voice_track == 'mic'


def test_tail_cap_and_accurate_seek_arguments(tmp_path, monkeypatch):
    calls = []
    source = {'streams': [{'codec_type': 'video', 'width': 640, 'start_time': '1', 'duration': '8'},
                          {'codec_type': 'audio', 'start_time': '1.2'}]}
    encoded = {'streams': [{'codec_type': 'video', 'width': 640, 'height': 360, 'avg_frame_rate': '30/1'}]}
    monkeypatch.setattr(ffutil, 'probe', lambda p: source if p.name == 'raw' else encoded)
    monkeypatch.setattr(ffutil, 'run', lambda args: calls.append(args))
    monkeypatch.setattr(audio, 'process_take', lambda *args: {'trimmed': [.5, 1.5], 'duration': 1})
    meta = camera.process_camera_take(tmp_path / 'raw', tmp_path / 'voice.wav', tmp_path / 'picture.mp4')
    assert meta['tail'] == camera.TAIL_S
    cmd = calls[-1]
    assert cmd.index('-ss') > cmd.index('-i')
    assert float(cmd[cmd.index('-ss') + 1]) == pytest.approx(.7)
    assert float(cmd[cmd.index('-t') + 1]) == 3.5


def test_variable_rate_input(synthetic, tmp_path, monkeypatch):
    raw = tmp_path / 'variable.mkv'
    ffutil.run(['-i', str(synthetic), '-vf', "select='if(lt(t,0.7),not(mod(n,3)),1)'",
                '-fps_mode', 'vfr', '-c:v', 'libx264', '-preset', 'ultrafast',
                '-c:a', 'copy', str(raw)], threads=1)
    def process(source, out, voice):
        ffutil.run(['-i', str(source), '-ss', '0.3', '-t', '0.8', str(out)], threads=1)
        return {'trimmed': [.3, 1.1], 'duration': .8}
    monkeypatch.setattr(audio, 'process_take', process)
    wav, mp4 = tmp_path / 'voice.wav', tmp_path / 'picture.mp4'
    meta = camera.process_camera_take(raw, wav, mp4)
    assert meta['fps'] == 30
    assert abs(ffutil.duration(mp4) - .8 - meta['tail']) <= 1 / 30

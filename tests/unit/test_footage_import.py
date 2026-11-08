"""Tiny synthetic camera files only; app data is isolated by conftest."""
import json
from pathlib import Path

import pytest
from PIL import Image

from app import ffutil, footage, jobs


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'data' / 'footage')
    monkeypatch.setenv('CORKBORED_ENCODER', 'cpu')
    root = tmp_path / 'camera'
    root.mkdir()
    # Three independent files, audio and tags included, with a fractional tail.
    for i in range(3):
        ffutil.run(['-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=8000',
                    '-t', '2.2', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-c:a', 'aac', '-metadata', 'creation_time=2026-10-31T12:00:00Z',
                    '-metadata', 'location=+37.3317-122.0307/', str(root / f'{i}.mov')], threads=1)
    return root


def snapshot(root):
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
            for p in root.iterdir()}


def test_import_three_resume_and_originals_untouched(sources, monkeypatch):
    before = snapshot(sources)
    shoot = footage.import_shoot(sources)
    original_proxy = footage._proxy
    calls = []

    def interrupted(src, out):
        calls.append(src.name)
        if len(calls) == 2:
            out.write_bytes(b'interrupted encode')
            raise KeyboardInterrupt
        original_proxy(src, out)

    monkeypatch.setattr(footage, '_proxy', interrupted)
    with pytest.raises(KeyboardInterrupt):
        footage.process_shoot(shoot.id)
    state = footage.status(shoot.id)
    assert state['ready'] == 1
    finished = [Path(state['files'][0][key]) for key in ('proxy', 'sprite')]
    saved = [p.stat().st_mtime_ns for p in finished]
    monkeypatch.setattr(footage, '_proxy', original_proxy)
    assert footage.import_shoot(sources).id == shoot.id
    messages = []
    state = footage.process_shoot(shoot.id, messages.append)
    assert state['ready'] == state['total'] == 3
    assert [p.stat().st_mtime_ns for p in finished] == saved
    assert messages[-1] == 'Done: 3/3 ready'
    for source in state['files']:
        assert source['duration'] == pytest.approx(2.2, abs=.1)
        assert (source['width'], source['height'], source['fps']) == (96, 64, 10)
        assert source['size'] > 0 and source['mtime_ns'] > 0
        assert source['creation_time'].startswith('2026-10-31')
        assert source['gps'].startswith('+37.3317-122.0307')
        assert source['audio'][0]['channels'] == 1
        probe = ffutil.probe(source['proxy'])
        video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        assert video['codec_name'] == 'h264'
        assert video['width'] <= 854 and video['height'] <= 480
        assert ffutil.has_audio(source['proxy'])
        with Image.open(source['sprite']) as img:
            assert img.size == (1600, 90)
            # Two timestamps (0, 2) occupy the first two tiles.
            assert img.crop((160, 0, 320, 90)).getextrema()[0][1] > 30
    assert snapshot(sources) == before
    assert len(footage.list_shoots()) == 1


def test_copy_survives_source_unavailable(sources):
    before = snapshot(sources)
    shoot = footage.import_shoot(sources / '0.mov', copy=True)
    footage.process_shoot(shoot.id)
    source = footage.load(shoot.id).files[0]
    owned = footage.source_path(shoot, source)
    assert owned.read_bytes() == (sources / '0.mov').read_bytes()
    assert snapshot(sources) == before
    # Simulate an offline source by changing only the manifest; no original is removed.
    shoot = footage.load(shoot.id)
    shoot.files[0].source_path = str(sources / 'offline.mov')
    footage._save(shoot)
    proxy, sprite = footage._outputs(shoot, source)
    proxy.unlink()  # Only app-owned derived media.
    sprite.unlink()
    assert footage.process_shoot(shoot.id)['ready'] == 1


def test_schema_rotation_and_quicktime_tags(tmp_path, monkeypatch):
    path = tmp_path / 'clip.mov'
    path.write_bytes(b'probe fixture')
    monkeypatch.setattr(ffutil, 'probe', lambda p: {
        'format': {'duration': '3', 'tags': {'com.apple.quicktime.location.ISO6709': '+1.2-3.4/'}},
        'streams': [{'codec_type': 'video', 'width': 1080, 'height': 1920,
                     'avg_frame_rate': '30000/1001', 'side_data_list': [{'rotation': -90}],
                     'tags': {'creation_time': '2026-10-31'}}]})
    source = footage.SourceFile('f1')
    footage._probe(source, path)
    assert source.rotation == -90 and source.fps == pytest.approx(29.97003)
    assert source.gps == '+1.2-3.4/' and source.audio == []
    restored = footage.Shoot.from_dict({'id': 's1', 'future': True,
                                       'files': [{'id': 'f1', 'future': True}]})
    assert restored.files[0].rotation == 0
    assert footage.Shoot.from_dict(restored.to_dict()) == restored


def test_job_entrypoint_and_cli(sources, monkeypatch, capsys):
    from app import cli
    assert cli.main(['footage', 'import', str(sources / '0.mov')]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state['ready'] == 1
    assert cli.main(['footage', 'list']) == 0
    assert json.loads(capsys.readouterr().out)[0]['id'] == state['id']
    assert cli.main(['footage', 'status', state['id']]) == 0
    assert json.loads(capsys.readouterr().out)['ready'] == 1
    captured = {}

    def start(kind, sid, fn, *, cancellable=False):
        assert cancellable is True
        messages = []
        captured.update(kind=kind, sid=sid, result=fn(messages.append), messages=messages)
        return 'job-test'

    monkeypatch.setattr(jobs, 'start', start)
    assert footage.start_processing(state['id']) == 'job-test'
    assert captured['kind'] == 'footage' and captured['result']['ready'] == 1
    assert captured['messages'][-1] == 'Done: 1/1 ready'
    assert cli.main(['footage', 'status', '../escape']) == 1
    assert 'Invalid footage id' in capsys.readouterr().err


def test_failed_file_is_logged_and_retried(sources, monkeypatch):
    shoot = footage.import_shoot(sources / '0.mov')
    original = footage._proxy
    monkeypatch.setattr(footage, '_proxy', lambda *a: (_ for _ in ()).throw(ffutil.FFError('broken')))
    with pytest.raises(ffutil.FFError, match='1 source file'):
        footage.process_shoot(shoot.id)
    assert footage.status(shoot.id)['files'][0]['error'] == 'broken'
    monkeypatch.setattr(footage, '_proxy', original)
    assert footage.process_shoot(shoot.id)['files'][0]['error'] == ''


def test_downscale_silent_clip_and_resume_sprite_only(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'data' / 'footage')
    monkeypatch.setenv('CORKBORED_ENCODER', 'cpu')
    src = tmp_path / 'silent.mp4'
    ffutil.run(['-f', 'lavfi', '-i', 'testsrc2=size=960x540:rate=10', '-t', '0.3',
                '-c:v', 'libx264', '-preset', 'ultrafast', str(src)], threads=1)
    shoot = footage.import_shoot(src)
    state = footage.process_shoot(shoot.id)
    proxy = Path(state['files'][0]['proxy'])
    assert ffutil.dimensions(proxy) == (854, 480)
    assert not ffutil.has_audio(proxy)
    saved = proxy.stat().st_mtime_ns
    Path(state['files'][0]['sprite']).unlink()
    assert footage.process_shoot(shoot.id)['ready'] == 1
    assert proxy.stat().st_mtime_ns == saved
    with pytest.raises(ValueError, match='outside the footage'):
        footage.import_shoot(proxy.parent)


def test_hardware_failure_retries_on_cpu(tmp_path, monkeypatch):
    attempts = []
    failed = []
    monkeypatch.setattr(ffutil, 'h264', lambda path, **kw:
                        (['-device', 'test'], 'hwupload', ['-c:v', 'h264_test']) if kw['gpu']
                        else ([], '', ['-c:v', 'libx264']))

    def run(args):
        attempts.append(args)
        if 'h264_test' in args:
            raise ffutil.FFError('GPU unavailable')

    monkeypatch.setattr(ffutil, 'run', run)
    monkeypatch.setattr(ffutil, 'gpu_failed', failed.append)
    footage._proxy(tmp_path / 'source.mov', tmp_path / 'proxy.mp4')
    assert len(attempts) == 2 and failed == ['GPU unavailable']
    assert 'hwupload' in attempts[0][attempts[0].index('-vf') + 1]
    assert 'hwupload' not in attempts[1][attempts[1].index('-vf') + 1]
    assert attempts[1][attempts[1].index('-c:v') + 1] == 'libx264'

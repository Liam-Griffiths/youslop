"""Proxy-only detection on tiny lavfi clips, with app data isolated by conftest."""
import pytest
from PIL import Image

from app import ffutil, footage


@pytest.fixture
def proxy_shoot(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'data' / 'footage')
    # Missing original deliberately proves no detection/thumbnail step opens it.
    shoot = footage.Shoot('s1', files=[footage.SourceFile('f1', '/offline/camera.mov')])
    footage._save(shoot)
    proxy, _ = footage._outputs(shoot, shoot.files[0])
    proxy.parent.mkdir()
    return shoot, proxy


def make_proxy(path, inputs, graph, audio=None):
    args = []
    for source in inputs:
        args += ['-f', 'lavfi', '-i', source]
    if audio:
        args += ['-f', 'lavfi', '-i', audio]
    args += ['-filter_complex', graph, '-map', '[v]']
    if audio:
        args += ['-map', f'{len(inputs)}:a', '-c:a', 'aac']
    ffutil.run([*args, '-c:v', 'libx264', '-preset', 'ultrafast',
                '-pix_fmt', 'yuv420p', str(path)], threads=1)


def test_known_cuts_thumbnails_persistence_and_resume(proxy_shoot):
    shoot, proxy = proxy_shoot
    make_proxy(proxy, ['testsrc=size=96x64:rate=10:duration=2',
                       'smptebars=size=96x64:rate=10:duration=2',
                       'color=white:size=96x64:rate=10:duration=2'],
               '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]')
    clips = footage.detect_shots(shoot.id)
    assert [c.in_s for c in clips] == pytest.approx([0, 2, 4], abs=.1)
    assert [c.out_s for c in clips] == pytest.approx([2, 4, 6], abs=.1)
    assert footage.load(shoot.id).clips == clips
    assert footage.status(shoot.id)['clips'] == [vars(c) for c in clips]
    paths = [footage.shoot_dir(shoot.id) / t for c in clips for t in c.thumbs]
    saved = [p.stat().st_mtime_ns for p in paths]
    for path in paths:
        with Image.open(path) as image:
            assert image.size == (160, 90)
    assert footage.detect_shots(shoot.id) == clips
    assert [p.stat().st_mtime_ns for p in paths] == saved
    # End thumbnail of the bars clip must precede the white cut.
    with Image.open(paths[5]) as image:
        assert image.getpixel((80, 45)) != (255, 255, 255)


def test_motion_and_silence_signals(proxy_shoot):
    shoot, proxy = proxy_shoot
    make_proxy(proxy, ['color=black:size=96x64:rate=10:duration=3',
                       'testsrc2=size=96x64:rate=10:duration=3'],
               '[0:v][1:v]concat=n=2:v=1:a=0[v]',
               "aevalsrc=if(between(t\\,2\\,4)\\,0\\,0.3*sin(440*2*PI*t)):s=8000:d=6")
    duration, fps, cuts, motion, silence = footage._shot_signals(proxy)
    assert duration == pytest.approx(6) and fps == 10
    assert cuts == pytest.approx([3], abs=.1)
    assert any(energy < footage.MOTION_THRESHOLD for _, energy in motion)
    assert any(energy >= footage.MOTION_THRESHOLD for _, energy in motion)
    assert silence == pytest.approx([2, 4], abs=.1)
    # Soft signals alone split a long take; no camera cut is necessary.
    edges = footage._shot_boundaries(9, 10, [], [(1, 0), (2, 0), (3, 10), (4, 10)],
                                     [6, 8], 1.5, 20)
    assert edges == [0, 3, 6, 9]


def test_short_clips_merged_and_long_holds_capped():
    edges = footage._shot_boundaries(47, 10, [.2, 4, 4.3, 46.8], [], [], 1.5, 20)
    assert edges[0] == 0 and edges[-1] == 47 and 4 in edges
    assert all(1.5 <= b - a <= 20 for a, b in zip(edges, edges[1:]))
    # Quietest second within the last third of the allowed span wins.
    edges = footage._shot_boundaries(30, 10, [], [(15, 9), (17, 3), (19, 5)], [], 1.5, 20)
    assert edges == [0, 17, 30]
    assert footage._shot_boundaries(.4, 10, [.1], [], [], 1.5, 20) == [0, .4]


def test_static_hold_configurable_maximum(proxy_shoot):
    shoot, proxy = proxy_shoot
    make_proxy(proxy, ['color=blue:size=96x64:rate=10:duration=7'], '[0:v]null[v]')
    clips = footage.detect_shots(shoot.id, min_s=1, max_s=3)
    assert clips[0].in_s == 0 and clips[-1].out_s == 7
    assert all(1 <= c.out_s - c.in_s <= 3 for c in clips)
    assert all(a.out_s == b.in_s for a, b in zip(clips, clips[1:]))


def test_schema_defaults_and_unknown_keys():
    old = footage.Shoot.from_dict({'id': 's1', 'future': True})
    assert old.clips == []
    restored = footage.Shoot.from_dict({'id': 's1', 'clips': [
        {'id': 'c1', 'file': 'f1', 'future': True}]})
    assert restored.clips == [footage.Clip('c1', 'f1')]
    assert footage.Shoot.from_dict(restored.to_dict()) == restored


def test_missing_proxy_and_invalid_limits(proxy_shoot):
    shoot, _ = proxy_shoot
    with pytest.raises(ValueError, match='Process proxy first'):
        footage.detect_shots(shoot.id)
    for minimum, maximum in [(0, 20), (2, 3), (1, float('inf'))]:
        with pytest.raises(ValueError, match='Require'):
            footage.detect_shots(shoot.id, min_s=minimum, max_s=maximum)

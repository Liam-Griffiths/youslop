"""Quality hints on tiny lavfi proxies; no originals or external services."""
import numpy as np
import pytest

from app import ffutil, footage, footage_quality as quality


def make_proxy(path, vf='null', audio=None):
    args = ['-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=8:duration=1']
    if audio:
        args += ['-f', 'lavfi', '-i', audio]
    ffutil.run([*args, '-vf', vf, '-c:v', 'libx264', '-preset', 'ultrafast',
                '-pix_fmt', 'yuv420p', *(['-c:a', 'aac'] if audio else []), str(path)], threads=1)


@pytest.mark.parametrize('vf,reason', [
    ('gblur=sigma=8', 'blur'),
    ('eq=brightness=-1', 'underexposed'),
    ('eq=brightness=1', 'overexposed'),
    ("scale=200:120,crop=160:90:x='20+12*sin(n*2)':y=15", 'shake'),
])
def test_synthetic_defects(tmp_path, vf, reason):
    proxy = tmp_path / 'proxy.mp4'
    make_proxy(proxy, vf)
    before = proxy.read_bytes(), proxy.stat().st_mtime_ns
    scores = quality.analyze_clip(proxy, 0, 1, False)
    assert reason in scores['reasons']
    assert not scores['usable']
    assert scores['audio_rms'] is None and scores['wind_fraction'] is None
    assert (proxy.read_bytes(), proxy.stat().st_mtime_ns) == before


def test_clean_and_audio_bands(tmp_path):
    proxy = tmp_path / 'clean.mp4'
    make_proxy(proxy, audio='sine=frequency=440:sample_rate=8000:duration=1')
    scores = quality.analyze_clip(proxy, 0, 1, True)
    assert scores['usable'], scores
    assert .05 < scores['audio_rms'] < .15
    assert scores['wind_fraction'] < .1
    make_proxy(tmp_path / 'soft.mp4', 'gblur=sigma=0.7')
    soft = quality.analyze_clip(tmp_path / 'soft.mp4', 0, 1, False)
    takes = [footage.Clip('clean', 'f1', 0, 1, quality=scores),
             footage.Clip('soft', 'f2', 0, 1, quality=soft)]
    quality.group_duplicates(takes)
    assert [c.best_take for c in takes] == ['clean', 'clean']
    assert quality.analyze_clip(proxy, 0, .04, True)['blur'] > 0
    t = np.arange(8000) / 8000
    frames = np.random.default_rng(1).integers(30, 220, (3, 90, 160), dtype=np.uint8)
    # Keep the picture stable so only the intended audio reason is relevant.
    frames[:] = frames[0]
    for samples, reason in [(np.zeros(8000), 'quiet_audio'),
                            (np.ones(8000) * .9, 'loud_audio'),
                            (.2 * np.sin(2 * np.pi * 60 * t), 'wind')]:
        assert reason in quality.score_frames(frames, samples)['reasons']
    make_proxy(tmp_path / 'wind.mp4', audio='sine=frequency=60:sample_rate=8000:duration=1')
    assert 'wind' in quality.analyze_clip(tmp_path / 'wind.mp4', 0, 1, True)['reasons']


def test_pipeline_persistence_duplicates_and_span(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'data' / 'footage')
    shoot = footage.Shoot('s1', files=[footage.SourceFile('f1', '/offline/camera.mov')])
    footage._save(shoot)
    proxy, _ = footage._outputs(shoot, shoot.files[0])
    proxy.parent.mkdir()
    # The second span is black. Analysis of the first must not include it.
    ffutil.run(['-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=8:duration=1',
                '-f', 'lavfi', '-i', 'color=black:size=160x90:rate=8:duration=1',
                '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]',
                '-c:v', 'libx264', '-preset', 'ultrafast', str(proxy)], threads=1)
    shoot.clips = [footage.Clip('c1', 'f1', 0, 1), footage.Clip('c2', 'f1', 0, 1),
                   footage.Clip('c3', 'f1', 1, 2)]
    footage._save(shoot)
    calls = []
    monkeypatch.setattr(footage, 'process_shoot', lambda *a: {'ready': 1, 'total': 1})
    monkeypatch.setattr(footage, 'detect_shots', lambda *a, **kw: calls.append('detect'))
    state = footage.process_and_detect(shoot.id)
    assert calls == ['detect']
    clips = footage.load(shoot.id).clips
    assert clips[0].quality['usable']
    assert 'underexposed' in clips[2].quality['reasons']
    assert [c.duplicate_group for c in clips] == ['c1', 'c1', '']
    assert [c.best_take for c in clips] == ['c1', 'c1', '']
    assert state['clips'] == [vars(c) for c in clips]
    assert footage.analyze_quality(shoot.id) == clips
    assert not (tmp_path / 'camera.mov').exists()


def test_hash_duration_and_best_take():
    rng = np.random.default_rng(42)
    a = rng.integers(0, 256, (90, 160), dtype=np.uint8)
    scores = quality.score_frames(np.stack([a, a, a]))
    clips = [footage.Clip(f'c{i}', 'f1', 0, duration, quality=dict(scores))
             for i, duration in enumerate([1, 1.05, 2, 1])]
    clips[0].quality.update(blur=50, shake=5)
    clips[1].quality.update(blur=100, shake=0)
    clips[3].quality['phash'] = format(int(scores['phash'], 16) ^ ((1 << 63) - 1), '016x')
    quality.group_duplicates(clips)
    assert [c.best_take for c in clips] == ['c1', 'c1', '', '']
    # Reanalysis clears obsolete grouping.
    quality.group_duplicates([clips[0]])
    assert clips[0].best_take == clips[0].duplicate_group == ''
    # Flat black and flat white must not group just because both lack texture.
    flat = [footage.Clip(str(v), 'f1', 0, 1, quality=quality.score_frames(
        np.full((3, 90, 160), v, dtype=np.uint8))) for v in (0, 255)]
    quality.group_duplicates(flat)
    assert all(not c.duplicate_group for c in flat)
    assert quality._shift(a, np.roll(a, (3, -6), axis=(0, 1))) == pytest.approx(np.hypot(3, 6))


def test_old_manifest_and_invalid_span(tmp_path):
    clip = footage.Clip.from_dict({'id': 'c1', 'file': 'f1', 'future': True})
    assert clip.quality == {} and clip.duplicate_group == clip.best_take == ''
    shoot = footage.Shoot('s1', clips=[clip])
    assert footage.Shoot.from_dict(shoot.to_dict()) == shoot
    with pytest.raises(ValueError, match='clip in < out'):
        quality.analyze_clip(tmp_path / 'missing', 1, 1, False)
    with pytest.raises(ValueError, match='No proxy frames'):
        quality.score_frames(np.empty((0, 90, 160), dtype=np.uint8))


def test_soft_relative_to_shoot_and_dim_exposure():
    from types import SimpleNamespace
    sharp = lambda: SimpleNamespace(quality={'blur': 800.0, 'reasons': [], 'usable': True})
    soft = SimpleNamespace(quality={'blur': 40.0, 'reasons': [], 'usable': True})
    dim = SimpleNamespace(quality={'blur': 50.0, 'reasons': ['underexposed'], 'usable': False})
    clips = [sharp(), sharp(), soft, dim]
    quality.flag_soft(clips)
    assert soft.quality['reasons'] == ['blur'] and not soft.quality['usable']
    assert dim.quality['reasons'] == ['underexposed']
    assert all(c.quality['reasons'] == [] for c in clips[:2])
    # Too few clips to judge relative softness.
    lone = SimpleNamespace(quality={'blur': 40.0, 'reasons': [], 'usable': True})
    quality.flag_soft([lone, sharp()])
    assert lone.quality['reasons'] == []
    # Dim but unclipped frames are underexposed.
    frames = np.full((8, 90, 160), 20, dtype=np.uint8)
    frames[:, :, :20] = 120
    assert 'underexposed' in quality.score_frames(frames)['reasons']

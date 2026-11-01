"""Tiny lavfi originals; no proxies, network, or user data."""
import csv
import json

import pytest

from app import ffutil, footage, footage_export


@pytest.fixture
def shoot(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'data' / 'footage')
    src = tmp_path / 'original.mp4'
    ffutil.run(['-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=10',
                '-f', 'lavfi', '-i', 'sine=sample_rate=8000', '-t', '2',
                '-c:v', 'libx264', '-g', '10', '-bf', '0', '-preset', 'ultrafast',
                '-c:a', 'aac', str(src)], threads=1)
    s = footage.Shoot('s1', files=[footage.SourceFile('f1', str(src), duration=2)],
                      clips=[footage.Clip('c1', 'f1', .3, 1.3, labels=['Wide / map'])])
    footage._save(s)
    return s, src


@pytest.mark.parametrize('mode,tolerance', [('encode', .1), ('copy', 1.0)])
def test_export_originals_sidecars_collision_and_timing(shoot, tmp_path, mode, tolerance):
    s, src = shoot
    before = (src.read_bytes(), src.stat().st_mtime_ns)
    out = tmp_path / 'exports'
    result = footage_export.export_clips(s.id, ['c1'], out, mode=mode)
    row = result['clips'][0]
    exported = out / row['filename']
    info = ffutil.probe(exported)
    video = next(v for v in info['streams'] if v['codec_type'] == 'video')
    assert abs(float(video.get('duration', info['format']['duration'])) - 1) <= tolerance + 1e-6
    assert (video['width'], video['height']) == (96, 64)
    # Decode the exported file, then compare its first frame to the intended
    # source frame (or the preceding keyframe for copy mode).
    def frame(path, start):
        target = tmp_path / (path.stem + '-frame.md5')
        ffutil.run(['-ss', str(start), '-i', str(path), '-map', '0:v:0',
                    '-frames:v', '1', '-f', 'framemd5', str(target)])
        return target.read_text().splitlines()[-1].split(',')[-1].strip()
    assert frame(exported, 0)
    if mode == 'copy':
        assert frame(exported, 0) == frame(src, 0)
    else:
        # Lossy encode: verify start content using decoded pixels with a small error.
        from PIL import Image, ImageChops, ImageStat
        for path, start, name in [(src, .3, 'expected'), (exported, 0, 'actual')]:
            ffutil.run(['-ss', str(start), '-i', str(path), '-frames:v', '1',
                        str(tmp_path / f'{name}.png')])
        with Image.open(tmp_path / 'expected.png') as a, Image.open(tmp_path / 'actual.png') as b:
            assert max(ImageStat.Stat(ImageChops.difference(a, b)).mean) < 5
    assert json.loads((out / 'clips.json').read_text())[0] == row
    with (out / 'clips.csv').open() as stream:
        csv_row = next(csv.DictReader(stream))
    assert json.loads(csv_row['labels']) == ['Wide / map']
    assert csv_row['source_path'] == str(src)
    assert csv_row['in_s'] == '0.3' and csv_row['out_s'] == '1.3'
    old = {p.name: p.read_bytes() for p in out.iterdir()}
    again = footage_export.export_clips(s.id, ['c1'], out, mode=mode)
    assert again['clips'][0]['filename'] != row['filename']
    assert all((out / name).read_bytes() == content for name, content in old.items())
    assert (src.read_bytes(), src.stat().st_mtime_ns) == before


def test_validation_schema_and_safe_names(shoot, tmp_path):
    s, src = shoot
    out = tmp_path / 'exports'
    for ids, kwargs in [([], {}), (['missing'], {}), (['c1', 'c1'], {}),
                        (['c1'], {'mode': 'bad'}), (['c1'], {'pattern': '{unknown}'})]:
        with pytest.raises(ValueError):
            footage_export.export_clips(s.id, ids, out, **kwargs)
    assert not out.exists()
    assert footage.Clip.from_dict({'id': 'old', 'file': 'f1'}).labels == []
    result = footage_export.export_clips(s.id, ['c1'], out, pattern='../../{label}')
    assert '/' not in result['clips'][0]['filename']
    s.clips[0].out_s = float('nan')
    footage._save(s)
    with pytest.raises(ValueError, match='span'):
        footage_export.export_clips(s.id, ['c1'], out)


def test_export_dialog_and_form(shoot, tmp_path):
    from app.footage_export_ui import export_dialog, export_selected
    page = export_dialog('s1')
    assert 'Wide / map' in page and 'one GOP' in page
    response = export_selected('s1', ['c1'], str(tmp_path / 'out'), '{label}-{id}', 'encode')
    assert response.status_code == 200 and b'Exported 1 clips' in response.body


def test_copied_original_and_missing_source(shoot, tmp_path):
    s, src = shoot
    owned = footage.shoot_dir(s.id) / 'originals' / 'camera.mp4'
    owned.parent.mkdir()
    owned.write_bytes(src.read_bytes())
    s.files[0].filename = 'originals/camera.mp4'
    footage._save(s)
    src.rename(tmp_path / 'offline.mp4')
    result = footage_export.export_clips(s.id, ['c1'], tmp_path / 'exports')
    assert result['clips'][0]['source_path'] == str(owned)
    owned.rename(owned.with_suffix('.offline'))
    with pytest.raises(FileNotFoundError):
        footage_export.export_clips(s.id, ['c1'], tmp_path / 'missing')
    assert not (tmp_path / 'missing').exists()

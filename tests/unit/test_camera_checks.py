"""Deterministic camera checks and one-pass synthetic measurement contracts."""
from copy import deepcopy

import pytest

from app import camera, check, ffutil, render, store, storyboard
from app.schema import CAMERA_TRACK, FrameSpec, Slide


def board(**take):
    return {'paragraphs': [dict(id='face', start=2, end=32, on_camera=True, take=take)]}


@pytest.mark.parametrize('rule,bad,good,level', [
    (check.camera_dark, dict(measure={'YAVG': 40}), dict(measure={'YAVG': 70}), 'P1'),
    (check.camera_blown, dict(measure={'clipped': .031}), dict(measure={'clipped': .03}), 'P1'),
    (check.camera_sync, dict(av_offset=-.081), dict(av_offset=.08), 'P0'),
    (check.camera_low_res, dict(width=1279), dict(width=1280), 'P2'),
    (check.camera_no_focal, dict(width=640, height=480), dict(width=1920, height=1080), 'P2'),
    (check.camera_held, {}, dict(overlays=[dict(at=15, dur=2, kind='cutaway')]), 'P2'),
])
def test_rules_positive_negative(rule, bad, good, level):
    found = rule(board(**bad), FrameSpec(), None)
    assert len(found) == 1 and found[0].code == rule.__name__ and found[0].level == level
    assert not rule(board(**good), FrameSpec(), None)
    sb = board(**bad)
    sb['paragraphs'][0]['on_camera'] = False
    assert not rule(sb, FrameSpec(), None)


def test_dark_respects_target_and_as_shot():
    sb = board(measure={'YAVG': 50})
    assert not check.camera_dark(sb, FrameSpec(), None)  # 50 + capped 15.3
    sb['camera_target'] = 50
    assert check.camera_dark(sb, FrameSpec(), None)
    sb['camera_target'] = 110
    sb['paragraphs'][0]['take']['look'] = 'as_shot'
    assert check.camera_dark(sb, FrameSpec(), None)


@pytest.mark.parametrize('extra', [{'sync_corrected': True}, {'video_start': .3}])
def test_corrected_sync_is_quiet(extra):
    assert not check.camera_sync(board(av_offset=.2, **extra), FrameSpec(), None)


def test_focal_and_missing_metadata():
    assert not check.camera_no_focal(board(width=640, height=480, focal=[.5, .5]), FrameSpec(), None)
    for rule in (check.camera_dark, check.camera_blown, check.camera_sync,
                 check.camera_low_res, check.camera_no_focal):
        assert not rule(board(), FrameSpec(), None)


def test_held_uses_longest_gap():
    assert not check.camera_held(board(cuts=[dict(a=15, b=16)]), FrameSpec(), None)
    assert check.camera_held(board(cuts=[dict(a=2, b=3)]), FrameSpec(), None)
    assert not check.camera_held(board(overlays=[dict(at=0, dur=30, kind='cutaway')]), FrameSpec(), None)
    sb = board()
    sb['paragraphs'][0]['end'] = 22
    assert not check.camera_held(sb, FrameSpec(), None)


@pytest.mark.parametrize('y,clipped', [(40, 0), (110, 0), (255, 1)])
def test_measure_lavfi(tmp_path, y, clipped):
    src = tmp_path / 'sample.mkv'
    ffutil.run(['-f', 'lavfi', '-i', f'nullsrc=s=64x48:r=2:d=0.6,geq=lum={y}:cb=128:cr=128',
                '-c:v', 'ffv1', str(src)], threads=1)
    stats = camera.measure(src)
    assert stats == pytest.approx(dict(YAVG=y, UAVG=128, VAVG=128, clipped=clipped), abs=.01)


def test_measure_clipped_share_and_cast(tmp_path):
    src = tmp_path / 'mixed.mkv'
    ffutil.run(['-f', 'lavfi', '-i',
                "nullsrc=s=100x50:r=1:d=1,geq=lum='if(lt(X,4),255,100)':cb=150:cr=100",
                '-c:v', 'ffv1', str(src)], threads=1)
    stats = camera.measure(src)
    assert stats == pytest.approx(
        dict(YAVG=106.2, UAVG=150, VAVG=100, clipped=.04), abs=.01)
    corrected = tmp_path / 'cast-corrected.mkv'
    ffutil.run(['-i', str(src), '-vf', camera.correction_filter({'measure': stats}, stats['YAVG']),
                '-c:v', 'ffv1', str(corrected)], threads=1)
    result = camera.measure(corrected)
    assert abs(result['UAVG'] - 128) + abs(result['VAVG'] - 128) < 50


def test_ffmpeg_exposure_matching(tmp_path):
    measured = []
    for y in (100, 120):
        src = tmp_path / f'{y}.mkv'
        correction = camera.correction_filter({'measure': dict(YAVG=y, UAVG=128, VAVG=128)}, 110)
        ffutil.run(['-f', 'lavfi', '-i', f'nullsrc=s=64x48:r=1:d=1,geq=lum={y}:cb=128:cr=128',
                    '-vf', correction, '-c:v', 'ffv1', str(src)], threads=1)
        measured.append(camera.measure(src)['YAVG'])
    # eq uses integer pixel math; a small bias near the target is acceptable.
    assert measured == pytest.approx([110, 110], abs=3)
    assert abs(measured[0] - measured[1]) <= 2


def test_matching_render_and_cache(project, monkeypatch):
    slides = [Slide(id=str(i), on_camera=True) for i in range(2)]
    project.slides = slides
    for slide, y in zip(slides, (100, 120)):
        project.set_take(slide, CAMERA_TRACK, dict(duration=1, measure=dict(YAVG=y, UAVG=150, VAVG=100)))
    assert camera.target(project) == 110
    corrected = [s.take['measure']['YAVG'] + camera.correction(s.take, camera.target(project))[0] * 255
                 for s in slides]
    assert corrected == pytest.approx([110, 110], abs=1)
    brightness, rgb = camera.correction(dict(measure=dict(YAVG=0, UAVG=255, VAVG=0)))
    assert brightness == .06 and max(abs(v) for v in rgb) <= .025
    assert camera.correction_filter({'measure': {'YAVG': 0}, 'look': 'as_shot'}) == ''
    monkeypatch.setattr(ffutil, 'dimensions', lambda _: (640, 480))
    chain = render._camera_look(project.style, None, (480, 270), 'unused', 15,
                                take=slides[0].take, target=110)
    assert chain.index('brightness=') < chain.index('gamma=')
    as_shot = render._camera_look(project.style, None, (480, 270), 'unused', 15,
                                 take={**slides[0].take, 'look': 'as_shot'})
    assert all(f not in as_shot for f in ('eq=', 'colorbalance=', 'vignette='))
    groups = [[(slides[0], 1)], [(slides[1], 1)]]
    # Cut formats bypass the photographic graph in the finished-segment key.
    project.style.format = 'flameboat'
    before = render._proxy_key(project, groups, 0, None)
    opts = dict(crf=18, preset='veryfast')
    finished = render._segment_key(project, groups[0], opts)
    slides[1].take['measure']['YAVG'] = 130
    assert render._proxy_key(project, groups, 0, None) != before
    assert render._segment_key(project, groups[0], opts) != finished
    sb = storyboard.build(project)
    assert sb['paragraphs'][0]['take']['measure']['YAVG'] == 100
    assert {r.__name__ for r in check.RULES} >= {'camera_dark', 'camera_blown', 'camera_sync',
        'camera_low_res', 'camera_no_focal', 'camera_held'}


def test_patch_persists_look_and_focal(project):
    from app.main import patch_slide
    from fastapi import HTTPException
    slide = project.slides[0]
    slide.on_camera = True
    project.set_take(slide, CAMERA_TRACK, dict(path='a.wav', video='a.mp4', duration=1, words=[]))
    original = deepcopy(slide.take)
    store.save(project)
    patch_slide(project.id, slide.id, {'camera_look': 'as_shot', 'camera_focal': [.3, .7]})
    loaded = store.load(project.id).slides[0]
    assert loaded.take == {**original, 'look': 'as_shot', 'focal': [.3, .7]}
    assert not loaded.history
    with pytest.raises(HTTPException):
        patch_slide(project.id, slide.id, {'camera_look': 'invalid'})
    assert store.load(project.id).slides[0].take == loaded.take


def test_check_uses_stored_camera_metadata(project, monkeypatch):
    from app import llm
    def forbidden(*args, **kwargs):
        pytest.fail('Camera checks must use stored metadata')
    for name in ('run', 'probe', 'duration'):
        monkeypatch.setattr(ffutil, name, forbidden)
    monkeypatch.setattr(llm, 'complete_json', forbidden)
    project.style.format = 'kenburns'
    project.slides = [Slide(id='camera', on_camera=True)]
    project.set_take(project.slides[0], CAMERA_TRACK, dict(
        path='voice.wav', video='video.mp4', duration=30, width=640, height=480,
        av_offset=.1, sync_corrected=False, measure=dict(YAVG=30, clipped=.1)))
    before = deepcopy(project.to_dict())
    findings = check.run(project)['findings']
    assert {f['code'] for f in findings if f['code'].startswith('camera_')} == {
        'camera_dark', 'camera_blown', 'camera_sync', 'camera_low_res', 'camera_held', 'camera_no_focal'}
    assert project.to_dict() == before

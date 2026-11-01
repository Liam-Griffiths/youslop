"""Camera render contracts use synthetic metadata; no browser or real projects."""
from pathlib import Path

import pytest

from app import audio, cuts, ffutil, render, scenes, store
from app.schema import CAMERA_TRACK, Slide, group_slides


def camera(project, *, raw=False, speech=1.0):
    slide = project.slides[0]
    slide.on_camera = True
    root = store.project_dir(project.id)
    take = dict(path='camera.wav', video='camera.mp4', duration=1.0,
                video_start=speech, tail=0.5, focal=[0.4, 0.5], raw_path='raw.mkv' if raw else '')
    for name in ('camera.wav', 'camera.mp4', *(['raw.mkv'] if raw else [])):
        (root / name).write_bytes(b'synthetic placeholder')
    project.set_take(slide, CAMERA_TRACK, take)
    return slide


@pytest.mark.parametrize('modes', [('hold', 'hold', 'hold'), ('auto', 'auto', 'auto')])
def test_camera_alone_even_between_holds(modes):
    slides = [Slide(id=str(i), picture_mode=m, on_camera=i in (1, 2))
              for i, m in enumerate((*modes, 'hold'))]
    assert [[s.id for s in g] for g in group_slides(slides, 8)] == [['0'], ['1'], ['2'], ['3']]


def test_concat_uses_active_camera(project, monkeypatch, tmp_path):
    slide = camera(project)
    slide.take = dict(path='stale-voice.wav', duration=99)  # Active track is authoritative.
    commands = []
    monkeypatch.setattr(ffutil, 'run', lambda args: commands.append(args))
    monkeypatch.setattr(ffutil, 'duration', lambda path: 1)
    audio._concat_takes(project, [slide], tmp_path / 'bed.wav', head=.3, tail=0)
    assert str(store.project_dir(project.id) / 'camera.wav') in commands[0]
    assert not any('stale-voice' in arg for arg in commands[0])


@pytest.mark.parametrize('raw,speech,start,pre,pad', [
    (False, 1.0, 0, 0, .9), (True, 1.0, .1, .9, 0), (True, .2, 0, .2, .7),
])
def test_camera_source_preroll_and_tail(project, monkeypatch, raw, speech, start, pre, pad):
    slide = camera(project, raw=raw, speech=speech)
    monkeypatch.setattr(cuts, 'transition_for', lambda style: .6)
    monkeypatch.setattr(ffutil, 'dimensions', lambda path: (640, 360))
    inputs, graph = render._camera_source(project, slide, 4, (480, 270), 15)
    assert inputs == ['-i', str(store.project_dir(project.id) / ('raw.mkv' if raw else 'camera.mp4'))]
    assert f'trim=start={start:.6f}:duration={1.5 + pre:.6f}' in graph
    assert f'tpad=start_mode=clone:start_duration={pad:.6f}:stop_mode=clone:stop_duration=4.000000' in graph
    assert 'loop=' not in graph and 'fps=15' in graph


@pytest.mark.parametrize('fmt', ['kenburns', 'essay', 'board', 'stage', 'flameboat', 'custom:missing'])
def test_camera_bypasses_engines(project, monkeypatch, tmp_path, fmt):
    slide = camera(project)
    project.style.format = fmt
    commands = []
    monkeypatch.setattr(ffutil, 'dimensions', lambda path: (640, 360))
    def record(args, **kw):
        args = list(args)
        at = args.index('-filter_complex_script')
        args[at:at+2] = ['-filter_complex', Path(args[at+1]).read_text()]
        commands.append(args)
    monkeypatch.setattr(ffutil, 'run', record)
    project.style.captions_engine = 'pillow'
    def forbidden(*args, **kwargs):
        pytest.fail('Camera must not dispatch to scene, stage, or drawn cut')
    monkeypatch.setattr(scenes, 'render_segment', forbidden)
    monkeypatch.setattr(cuts, 'render_segment', forbidden)
    monkeypatch.setattr(render.shots_mod, 'ensure_clips', forbidden)
    monkeypatch.setattr(render, '_render_custom_style', forbidden)
    render._render_segment(project, [(slide, 2)], 3, 0, tmp_path / 'out.webm',
                           chapter=('Next', ''), size=(480, 270), fps=15)
    assert len(commands) == 1
    graph = commands[0][commands[0].index('-filter_complex') + 1]
    assert 'tpad=start_mode=clone' in graph and '[chap]' in graph
    assert '[ttl0]' in graph  # photographic titles also survive in essay/cut formats


def test_proxy_key_camera_files_and_focal(project):
    slide = camera(project, raw=True)
    groups = [[(slide, 2)]]
    before = render._proxy_key(project, groups, 0, None)
    for name in ('camera.mp4', 'raw.mkv'):
        (store.project_dir(project.id) / name).write_bytes(b'changed file size')
        after = render._proxy_key(project, groups, 0, None)
        assert after != before
        before = after
    project.active_take(slide)['focal'] = [0.8, 0.2]
    assert render._proxy_key(project, groups, 0, None) != before


def test_timeline_camera_marker_and_no_missing_picture(project):
    slide = camera(project)
    slide.chosen_id = ''
    row = next(s for s in render.timeline(project)['segments'] if s.get('lead') == slide.id)
    assert row['kind'] == 'camera' and row['type'] == 'picture'
    assert row['camera_stamp']
    assert 'no picture chosen' not in row['problems']


def test_presenter_command_unchanged(project, monkeypatch, tmp_path):
    project.presenter.path = 'presenter.mp4'
    project.presenter.trim_start = .7
    monkeypatch.setattr(ffutil, 'dimensions', lambda path: (640, 360))
    commands = []
    monkeypatch.setattr(ffutil, 'run', lambda args: commands.append(args))
    out = tmp_path / 'presenter.mp4'
    render._render_presenter(project, 3, out)
    crop, _ = render._cover_crop(store.project_dir(project.id) / 'presenter.mp4', 1920, 1080, None)
    chain = [crop, 'fps=30', render.GRADES[project.style.grade],
             render._vignette(project.style.vignette * .6), 'format=yuv420p']
    assert commands == [[
        '-ss', '0.700', '-i', str(store.project_dir(project.id) / 'presenter.mp4'),
        '-t', '3.000', '-filter_complex', '[0:v]' + ','.join(x for x in chain if x) + '[v]',
        '-map', '[v]', '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
        '-pix_fmt', 'yuv420p', '-an', str(out)]]


def test_camera_graph_golden(project, monkeypatch, request):
    import os
    from tests._fixtures import ROOT
    slide = camera(project, raw=True)
    monkeypatch.setattr(ffutil, 'dimensions', lambda path: (640, 360))
    inputs, graph, last = render._segment_graph(project, [(slide, 2)], 3, 'set',
        chapter=('Next chapter', 'Test'), size=(480, 270), fps=15)
    def norm(value):
        return value.replace(os.environ['CORKBORED_DATA'], '<DATA>').replace(str(ROOT), '<REPO>')
    actual = '\n'.join(norm(a) for a in inputs) + '\n---\n' + norm(graph).replace(';', ';\n') + '\n---\n' + last + '\n'
    golden = ROOT / 'tests/golden/camera_preview.txt'
    if request.config.getoption('--update-goldens'):
        golden.write_text(actual)  # New camera reference; existing goldens stay unchanged.
    assert actual == golden.read_text()


def test_non_camera_ffmpeg_command_matches_existing_golden(project, monkeypatch):
    import os
    from app import stage
    from tests._fixtures import ROOT
    project.style.format = 'kenburns'
    project.style.captions_engine = 'pillow'
    project.slides[0].chapter = 'Opening'
    group = render._picture_groups(project, render._slide_durations(project, False))[0]
    commands = []
    monkeypatch.setattr(stage, 'browser', lambda: None)
    monkeypatch.setattr(ffutil, 'run', lambda args, **kwargs: commands.append(args))
    monkeypatch.setattr(ffutil, 'video_args', lambda *args, **kwargs: ['-c:v', 'libx264'])
    out = store.project_dir(project.id) / 'out.mp4'
    render._render_segment(project, group, 3, 0, out, chapter=('Next chapter', 'Test'),
        size=render.preview_size(), fps=render.PREVIEW_FPS,
        op=render.camera_plan(project, [group])[0])
    inputs, graph, last = (ROOT / 'tests/golden/doc_preview.txt').read_text().split('\n---\n')
    expected = [*inputs.splitlines(), '-filter_complex', graph.replace(';\n', ';'),
                '-map', last.strip(), '-t', '3.000', '-r', str(render.PREVIEW_FPS),
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', '<DATA>/projects/ptest0001/out.mp4']
    actual = [a.replace(os.environ['CORKBORED_DATA'], '<DATA>').replace(str(ROOT), '<REPO>')
              for a in commands[0]]
    assert actual == expected


def test_camera_never_falls_back_to_voiceover(project, monkeypatch, tmp_path):
    slide = camera(project)
    slide.takes = {}
    slide.take = dict(path='voiceover.wav', duration=1)
    with pytest.raises(ValueError, match='Nothing recorded'):
        audio._concat_takes(project, [slide], tmp_path / 'bed.wav', head=0, tail=0)


def test_camera_thumbnail_cache_uses_own_video(project, monkeypatch):
    slide = camera(project)
    calls = []
    def record(args):
        calls.append(args)
        Path(args[-1]).write_bytes(b'cached synthetic frame')
    monkeypatch.setattr(ffutil, 'run', record)
    first = render.camera_thumbnail(project, slide)
    assert render.camera_thumbnail(project, slide) == first
    assert len(calls) == 1
    assert calls[0][:4] == ['-i', str(store.project_dir(project.id) / 'camera.mp4'), '-frames:v', '1']
    (store.project_dir(project.id) / 'camera.mp4').write_bytes(b'new synthetic source')
    assert render.camera_thumbnail(project, slide) != first
    assert len(calls) == 2

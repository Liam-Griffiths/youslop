"""Resume bookkeeping only: no ffmpeg processes, browser, downloads or LLM."""
import os
from pathlib import Path

import pytest

from app import audio, channels, ffutil, learning, render
from app.schema import Slide


@pytest.fixture
def setup_render(project, tmp_path, monkeypatch):
    root = tmp_path / 'project'
    (root / 'out').mkdir(parents=True)
    monkeypatch.setattr(render, 'project_dir', lambda pid: root)
    monkeypatch.setattr(render, '_memory_check', lambda pr: None)
    monkeypatch.setattr(learning, 'resolve_choices', lambda p: None)
    monkeypatch.setattr(audio, 'audit_takes', lambda *a: ([], False))
    monkeypatch.setattr(render.media, 'download_chosen', lambda *a, **kw: [])
    monkeypatch.setattr(render, '_build_intro', lambda *a: (None, 0))
    monkeypatch.setattr(render, '_build_outro', lambda *a: (None, 0))
    monkeypatch.setattr(render, '_build_presenter', lambda *a: (None, 0, 0))
    monkeypatch.setattr(render, '_stings_for', lambda *a: {})
    monkeypatch.setattr(render, 'pick_music', lambda *a: None)
    monkeypatch.setattr(render, '_stage_clips', lambda *a: None)
    monkeypatch.setattr(channels, 'load_or_none', lambda *a: None)
    monkeypatch.setattr(render.sysinfo, 'available_mb', lambda: 1)
    monkeypatch.setattr(render.os, 'cpu_count', lambda: 2)
    monkeypatch.setattr(ffutil, 'gpu_status', lambda: {'active': False})
    monkeypatch.setattr(ffutil, 'h264', lambda *a, **kw: ([], '', ['-c:v', 'libx264']))
    monkeypatch.setattr(ffutil, 'duration', lambda *a: 3)
    monkeypatch.setattr(render, '_segment_graph', lambda *a, **kw: ([], 'null[v]', '[v]'))
    monkeypatch.setattr(audio, 'build_narration', lambda *a, **kw: None)
    project.style.format = 'kenburns'
    project.slides = [Slide(id=f's{i}', narration=f'Paragraph {i}',
                            take={'path': f'{i}.wav', 'duration': 2}) for i in range(5)]
    monkeypatch.setattr(render, '_slide_durations', lambda *a, **kw: [(s, 3) for s in project.slides])
    monkeypatch.setattr(render, '_picture_groups', lambda p, plan: [[row] for row in plan])
    return project, root


def fake_segment(project, group, length, index, out, **kwargs):
    ffutil.run(['-fake-segment', str(index), str(out)])
    return out


def test_failure_resume_and_sweep(setup_render, monkeypatch):
    project, root = setup_render
    calls = []
    fail = True
    monkeypatch.setattr(render.cf, 'ThreadPoolExecutor', InlinePool)

    def encode(args, **kwargs):
        path = Path(args[-1])
        if path.parent.name == 'segments':
            calls.append(int(args[1]))
            path.write_bytes(b'partial')
            if fail and int(args[1]) == 2:
                raise ffutil.FFError('segment 3 failed')
            path.write_bytes(f'finished-{args[1]}'.encode())
        else:
            # Deterministic fake mux: identical resumed/uninterrupted output.
            inputs = [Path(args[i + 1]) for i, arg in enumerate(args[:-1])
                      if arg == '-i' and Path(args[i + 1]).parent.name == 'segments']
            path.write_bytes(b''.join(p.read_bytes() for p in inputs))

    monkeypatch.setattr(render, '_render_segment', fake_segment)
    monkeypatch.setattr(ffutil, 'run', encode)
    logs = []
    with pytest.raises(ffutil.FFError, match='segment 3'):
        render.render(project, logs.append)
    directory = root / 'segments'
    assert len(list(directory.glob('*.partial.mp4'))) == 1
    assert len([p for p in directory.glob('*.mp4') if len(p.stem) == 40]) == 2
    assert logs[-1] == 'resumable: 2 segments kept'
    assert calls == [0, 1, 2]
    stale = directory / ('f' * 40 + '.mp4')
    stale.write_bytes(b'stale')
    fail = False
    result = render.render(project, logs.append)
    resumed = (root / result['output']).read_bytes()
    assert calls == [0, 1, 2, 2, 3, 4]
    assert 'reused 2 of 5 segments' in logs
    assert len(list(directory.iterdir())) == 5
    assert not stale.exists()
    for path in directory.iterdir():
        path.unlink()
    render.render(project)
    assert (root / result['output']).read_bytes() == resumed


def settings():
    return dict(seg_len=4, channel=None, chapter=('Next', ''), threads=2,
                size=(1920, 1080), fps=30, crf=18, preset='veryfast',
                dip_out=False, op='set', camera_index=0, last_line=False, index=0)


@pytest.mark.parametrize('field', ['slide', 'duration', 'take', 'picture', 'style', 'frame',
                                  'title', 'chapter', 'dip_out', 'size', 'fps', 'crf',
                                  'preset', 'threads', 'op', 'last_line', 'graph',
                                  'encoder', 'version', 'scene_version', 'video', 'cuts',
                                  'overlays', 'focal'])
def test_key_inputs(setup_render, monkeypatch, field):
    project, root = setup_render
    group = [(project.slides[0], 3)]
    picture = root / 'picture.png'
    picture.write_bytes(b'picture')
    take = root / '0.wav'
    take.write_bytes(b'audio')
    video = root / 'camera.mp4'
    video.write_bytes(b'video')
    project.slides[0].take['video'] = video.name
    monkeypatch.setattr(render, '_chosen', lambda *a: (picture, 'image', []))
    opts = settings()
    before = render._segment_key(project, group, opts)
    if field in ('take', 'video'):
        path = take if field == 'take' else video
        stat = path.stat()
        path.write_bytes(b'other')  # Same size and timestamps: content hash still changes.
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif field == 'picture':
        picture.write_bytes(b'changed picture')
    elif field == 'slide':
        project.slides[0].title = 'Changed'
    elif field == 'duration':
        group[0] = (group[0][0], 4)
    elif field == 'style':
        project.style.grade = 'cool'
    elif field == 'frame':
        project.frame.arrive_s += 0.1
    elif field == 'title':
        project.title += ' changed'
    elif field == 'graph':
        monkeypatch.setattr(render, '_segment_graph', lambda *a, **kw: ([], 'other[v]', '[v]'))
    elif field == 'encoder':
        monkeypatch.setattr(ffutil, 'h264', lambda *a, **kw: ([], '', ['gpu']))
    elif field == 'version':
        monkeypatch.setattr(render, 'SEGMENT_VERSION', 2)
    elif field == 'scene_version':
        monkeypatch.setattr(render.scenes, 'SCENE_VERSION', -1)
    elif field in ('cuts', 'overlays', 'focal'):
        project.slides[0].take[field] = [1, 2]
    else:
        opts[field] = {'chapter': ('Other', ''), 'dip_out': True, 'size': (480, 270),
                       'fps': 15, 'crf': 30, 'preset': 'slow', 'threads': 1,
                       'op': 'creep_in', 'last_line': True}[field]
    assert render._segment_key(project, group, opts) != before


def test_key_ignores_unrelated_inputs(setup_render):
    project, _ = setup_render
    group = [(project.slides[0], 3)]
    before = render._segment_key(project, group, settings())
    project.slides[0].candidates.append({'id': 'unused', 'url': 'unused'})
    project.slides[-1].narration = 'Other segment'
    project.render = {'output': 'old.mp4'}
    project.music = 'changed.wav'
    assert render._segment_key(project, group, settings()) == before


def test_empty_segment_is_not_published(tmp_path):
    temp, out = tmp_path / 'partial.mp4', tmp_path / 'key.mp4'
    temp.touch()
    with pytest.raises(ValueError, match='Empty segment'):
        render._publish_segment(temp, out)
    assert not out.exists()


class InlinePool:
    """Run process jobs inline so drawn-cut tests cannot launch a renderer."""
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def map(self, fn, jobs):
        return map(fn, jobs)

    def submit(self, fn, *args):
        future = render.cf.Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future


@pytest.mark.parametrize('chunks', [1, 2])
def test_drawn_resume(setup_render, monkeypatch, chunks):
    project, root = setup_render
    directory = root / 'segments'
    directory.mkdir()
    groups = [[(s, 3)] for s in project.slides]
    targets = [directory / f'{i:040x}.mp4' for i in range(5)]
    calls = []
    fail = True

    def draw(job):
        i, chunk, out = job[8], job[9], job[4]
        calls.append((i, chunk))
        out.write_bytes(b'piece')
        if fail and i == 2:
            raise ffutil.FFError('piece failed')
        return i, chunk, out, False

    monkeypatch.setattr(render.cf, 'ProcessPoolExecutor', InlinePool)
    monkeypatch.setattr(render, '_draw_segment', draw)
    monkeypatch.setattr(render.cuts, 'frame_count', lambda *a: chunks * render.CHUNK_SECONDS * render.FPS)
    monkeypatch.setattr(ffutil, 'run', lambda args, **kw: Path(args[-1]).write_bytes(b'joined'))
    with pytest.raises(ffutil.FFError):
        render._draw_segments(project, groups, [4] * 5, 0, directory, None, 1000,
                              lambda m: None, targets=targets)
    assert all(p.exists() for p in targets[:2])
    assert not targets[2].exists()
    previous = list(calls)
    fail = False
    assert render._draw_segments(project, groups, [4] * 5, 0, directory, None, 1000,
                                 lambda m: None, targets=targets) == targets
    assert all(i == 2 for i, chunk in calls[len(previous):])
    assert all(render._segment_ready(p) for p in targets)
    assert not (directory / 'pieces').exists()


def test_changed_segment_and_empty_cache(setup_render, monkeypatch):
    project, root = setup_render
    monkeypatch.setattr(render.cf, 'ThreadPoolExecutor', InlinePool)
    monkeypatch.setattr(render, '_render_segment', fake_segment)
    calls = []

    def encode(args, **kwargs):
        out = Path(args[-1])
        out.write_bytes(b'complete')
        if out.parent.name == 'segments':
            calls.append(int(args[1]))

    monkeypatch.setattr(ffutil, 'run', encode)
    render.render(project)
    project.slides[2].narration += ' edited'
    logs = []
    render.render(project, logs.append)
    assert calls == [0, 1, 2, 3, 4, 2]
    assert 'reused 4 of 5 segments' in logs
    assert len(list((root / 'segments').iterdir())) == 5
    cached = next((root / 'segments').iterdir())
    cached.write_bytes(b'')
    render.render(project, logs.append)
    assert len(calls) == 7
    assert cached.stat().st_size > 0


def test_final_mux_failure_preserves_all_segments(setup_render, monkeypatch):
    project, root = setup_render
    monkeypatch.setattr(render.cf, 'ThreadPoolExecutor', InlinePool)
    monkeypatch.setattr(render, '_render_segment', fake_segment)

    def encode(args, **kwargs):
        out = Path(args[-1])
        if out.parent.name != 'segments':
            raise ffutil.FFError('mux failed')
        out.write_bytes(b'complete')

    monkeypatch.setattr(ffutil, 'run', encode)
    logs = []
    with pytest.raises(ffutil.FFError, match='mux failed'):
        render.render(project, logs.append)
    assert logs[-1] == 'resumable: 5 segments kept'
    assert len(list((root / 'segments').iterdir())) == 5


def test_drawn_fallback_not_cached_under_gpu_key(setup_render, monkeypatch):
    project, root = setup_render
    directory = root / 'segments'
    directory.mkdir()
    groups = [[(project.slides[0], 3)]]
    target = directory / ('f' * 40 + '.mp4')
    monkeypatch.setattr(render.cf, 'ProcessPoolExecutor', InlinePool)
    monkeypatch.setattr(ffutil, 'gpu_status', lambda: {'active': True})

    def draw(job):
        job[4].write_bytes(b'cpu fallback')
        return 0, 0, job[4], False

    monkeypatch.setattr(render, '_draw_segment', draw)
    paths = render._draw_segments(project, groups, [4], 0, directory, None, 1000,
                                  lambda m: None, targets=[target])
    assert not target.exists()
    assert paths[0].name.endswith('.uncached.mp4')
    assert paths[0].read_bytes() == b'cpu fallback'

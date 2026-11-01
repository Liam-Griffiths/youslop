"""3D capture/composition contracts; no browser, GPU, encoder or model loads."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import ffutil, scene_builder, scenes, stage


@pytest.fixture
def shot():
    return dict(clip='shot', entries=[dict(sid='subject', model='model')],
                shot=dict(kind='still', pos=[0, 0, 5], aim=[0, 0, 0], secs=3),
                look='set', haze=None, W=1920, H=1080, fps=24, frames=72)


def mock_push(monkeypatch, items, directory, errors=()):
    calls = []

    def push(job, progress, **kwargs):
        calls.append((job, kwargs))
        clips = {}
        for item in items:
            path = directory / (item['clip'] + '.mp4')
            path.write_bytes(b'original push')
            clips[item['clip']] = dict(out=path, done=True)
        return SimpleNamespace(clips=clips, errors=errors)

    monkeypatch.setattr(stage, '_run', push)
    monkeypatch.setattr(stage, '_run_cdp', lambda *a, **kw: pytest.fail('3D video used CDP'))
    return calls


def test_stage_no_overlay_command_unchanged(tmp_path, monkeypatch, shot):
    commands = []
    monkeypatch.setattr(stage.subprocess, 'Popen',
                        lambda cmd, **kw: commands.append((cmd, kw)) or SimpleNamespace())
    run = stage._Run({}, tmp_path)
    stage._begin(run, 'shot', shot)
    assert commands == [([stage.FFMPEG, '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', '1920x1080', '-r', '24', '-i', '-',
        '-vf', 'vflip', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '12',
        '-pix_fmt', 'yuv420p', '-an', str(tmp_path / 'shot.part.mp4')],
        dict(stdin=stage.subprocess.PIPE, stderr=stage.subprocess.PIPE))]
    calls = mock_push(monkeypatch, [shot], tmp_path)
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw: pytest.fail('unexpected overlay'))
    monkeypatch.setattr(ffutil, 'run', lambda *a, **kw: pytest.fail('unexpected compositing'))
    made = stage.render([shot], {'model': {}}, tmp_path)
    assert made['shot'].read_bytes() == b'original push'
    assert calls == [(dict(task='render', models={'model': {}}, items=[shot]), dict(out_dir=tmp_path))]


@pytest.mark.parametrize('fail', [False, True, 'new-ffmpeg'])
def test_stage_overlay_builder_graph_and_atomic_publish(tmp_path, monkeypatch, shot, fail):
    ctx = scenes.context_base()
    ctx.update(title_at=.5, title_hold=1.25)
    shot['overlay'] = dict(template='stage/title.html', ctx=ctx, project_root=str(tmp_path))
    mock_push(monkeypatch, [shot], tmp_path)
    calls = []

    def builder(owner, template, context, out, **kw):
        assert (owner, template) == (str(tmp_path), 'stage/title.html')
        assert context['builder_alpha'] is True
        assert (context['width'], context['height']) == (1920, 1080)
        assert context['title_at'] == .5 and context['title_hold'] == 1.25
        assert kw == dict(seconds=3, size=(1920, 1080), fps=24, crf=12)
        assert Path(out).suffix == '.mov'
        html = scenes.render_html(template, dict(context, duration=3, fps=24))
        assert scenes.lint(html) == []
        assert 'data-start="0.5" data-duration="1.25"' in html
        assert 'background: transparent' in html
        calls.append('builder')
        Path(out).write_bytes(b'RGBA MOV')
        return SimpleNamespace(path=out)

    def composite(args):
        assert calls == ['builder']
        flag = '-filter_complex_script' if '-filter_complex_script' in args else '-/filter_complex'
        graph = Path(args[args.index(flag) + 1]).read_text()
        assert graph.count('overlay=') == 1
        assert 'setpts=PTS-STARTPTS' in graph
        assert 'eof_action=pass:repeatlast=0' in graph
        assert args[:2] == ['-i', str(tmp_path / 'shot.mp4')]
        assert args[2] == '-i' and Path(args[3]).read_bytes() == b'RGBA MOV'
        assert args[args.index('-frames:v') + 1] == '72'
        assert args[args.index('-r') + 1] == '24'
        if fail is True:
            raise ffutil.FFError('encoder failed')
        if fail == 'new-ffmpeg' and flag == '-filter_complex_script':
            raise ffutil.FFError("Unrecognized option 'filter_complex_script'")
        Path(args[-1]).write_bytes(b'composited')

    monkeypatch.setattr(scene_builder, 'render', builder)
    monkeypatch.setattr(ffutil, 'run', composite)
    if fail is True:
        with pytest.raises(stage.StageError, match='encoder failed'):
            stage.render_scene([shot], tmp_path, models={'model': {}})
        assert (tmp_path / 'shot.mp4').read_bytes() == b'original push'
    else:
        made = stage.render_scene([shot], tmp_path, models={'model': {}})
        assert made['shot'].read_bytes() == b'composited'
    assert not list(tmp_path.glob('stage-overlay-*'))
    assert 'builder_alpha' not in ctx


def test_stage_failed_push_never_composites(tmp_path, monkeypatch, shot):
    shot['overlay'] = dict(template='stage/title.html', ctx={})
    mock_push(monkeypatch, [shot], tmp_path, errors=['missing frame'])
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw: pytest.fail('failed push composited'))
    with pytest.raises(stage.StageError, match='missing frame'):
        stage.render([shot], {}, tmp_path)


def test_stage_stills_keep_original_shot_duration(tmp_path, monkeypatch, shot):
    jobs = []

    def capture(job, progress, **kwargs):
        jobs.append(job)
        return SimpleNamespace(thumbs={i['clip']: b'PNG' for i in job['items']})

    monkeypatch.setattr(stage, '_run_cdp', capture)
    models = {'model': {'id': 'model'}}
    assert stage.capture_one(stage.PAGE, 1920, 1080, 1.25, (480, 270),
                             stage_item=shot, models=models) == b'PNG'
    items = [dict(shot, clip='first', t=0, size=(480, 270)),
             dict(shot, clip='last', t=71/24, size=(480, 270))]
    assert stage.capture_stills(items, models=models) == {'first': b'PNG', 'last': b'PNG'}
    for job in jobs:
        assert job['task'] == 'still' and job['models'] == models
        for n, (capture, original) in enumerate(zip(job['items'], job['stage_items'])):
            assert capture['url_path'] == stage.PAGE + f'?item={n}'
            assert capture['frames'] == 1
            assert capture['t'] == original['t']
            assert capture['size'] == (480, 270)
            assert original['frames'] == 72 and original['fps'] == 24
            assert original['shot'] == shot['shot']
    with pytest.raises(ValueError, match='require models'):
        stage.capture_one(stage.PAGE, 1920, 1080, 1, (480, 270), stage_item=shot)

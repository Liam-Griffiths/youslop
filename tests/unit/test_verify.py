"""Tiny lavfi fixtures only; no project renders, network, browser or LLM."""
import json
from pathlib import Path

import pytest

from app import ffutil, render, verify
from app.schema import FrameSpec, Slide
from tests.unit.test_resume import InlinePool, fake_segment, setup_render


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    root = tmp_path_factory.mktemp('verify-media')
    paths = {}
    for name, video, audio in (
        ('black', 'color=black:s=64x36:r=10:d=2', 'sine=duration=2'),
        ('trim', 'color=red:s=64x36:r=10:d=1', 'sine=duration=0.7'),
        ('tail', 'color=red:s=64x36:r=10:d=2',
         'sine=duration=0.3,apad=whole_dur=2'),
    ):
        path = root / f'{name}.mp4'
        ffutil.run(['-f', 'lavfi', '-i', video, '-f', 'lavfi', '-i', audio,
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', str(path)], threads=1)
        paths[name] = path
    return paths


def test_black_at_zero_and_single_analysis_pass(clips, monkeypatch):
    capture, calls = ffutil.capture, []

    def record(args):
        calls.append(args)
        return capture(args)

    monkeypatch.setattr(ffutil, 'capture', record)
    result = verify.run(clips['black'])
    assert len(calls) == 1
    assert all(filter_ in ' '.join(calls[0]) for filter_ in
               ('blackdetect', 'ebur128', 'silencedetect'))
    finding = next(f for f in result['findings'] if f['kind'] == 'black_run')
    assert finding['t'] == 0 and finding['severity'] == 'P0'
    assert result['loudness_lufs'] is not None
    assert not any(f['kind'] in ('av_delta', 'silent_tail') for f in result['findings'])


def test_audio_trim(clips):
    result = verify.run(clips['trim'])
    finding = next(f for f in result['findings'] if f['kind'] == 'av_delta')
    assert finding['severity'] == 'P0'
    assert '0.300s' in finding['detail']


def test_silent_tail(clips):
    result = verify.run(clips['tail'])
    tail = next(f for f in result['findings'] if f['kind'] == 'silent_tail')
    assert tail['severity'] == 'P1' and tail['t'] == pytest.approx(0.3, abs=0.05)


@pytest.fixture
def analysis(monkeypatch):
    monkeypatch.setattr(ffutil, 'probe', lambda path: {
        'format': {'duration': '10'},
        'streams': [{'codec_type': 'video', 'width': 1920, 'height': 1080,
                     'duration': '10', 'bit_rate': '100000'},
                    {'codec_type': 'audio', 'duration': '10'}]})
    log = ['']
    monkeypatch.setattr(ffutil, 'capture', lambda args: ('', log[0]))
    return log


def test_interior_black_loudness_and_bitrate(analysis):
    analysis[0] = 'black_start:3 black_end:4\nSummary:\n I: -18.0 LUFS'
    frame = FrameSpec(voice_lufs=-18)
    result = verify.run('unused', frame=frame)
    assert {f['kind']: f['severity'] for f in result['findings']} == {
        'black_run': 'P1', 'bitrate_low': 'P2'}
    result = verify.run('unused')
    assert any(f['kind'] == 'loudness_off' for f in result['findings'])
    analysis[0] = 'black_start:8 black_end:9\n I: -16.0 LUFS'
    result = verify.run('unused')
    assert any(f['kind'] == 'black_run' and f['severity'] == 'P0'
               for f in result['findings'])
    assert not any(f['kind'] == 'loudness_off' for f in result['findings'])


def test_short_fades_and_dips_are_not_findings(analysis):
    analysis[0] = ('black_start:0 black_end:0.4\n'
                   'black_start:5 black_end:5.8\n I: -16.0 LUFS')
    result = verify.run('unused')
    assert not any(f['kind'] == 'black_run' for f in result['findings'])


def test_only_edge_words_and_confidence(analysis):
    story = {'segments': [{'start': 2, 'duration': 4, 'paragraphs': [
        {'id': 's1', 'word_times': [
            {'start': 2.05, 'end': 2.3, 'src': 'est'},
            {'start': 4, 'end': 4.3, 'src': 'tts'},
            {'start': 5.7, 'end': 5.96, 'src': 'tts'}]},
        {'id': 's2', 'word_times': [{'start': 3, 'end': 3.5, 'src': 'tts'}]},
    ]}]}
    findings = [f for f in verify.run('unused', story)['findings']
                if f['kind'] == 'clipped_word']
    assert [(f['t'], f['severity']) for f in findings] == [(2.05, 'P2'), (5.96, 'P1')]


def test_silence_interior_and_nonfinite_loudness(analysis):
    analysis[0] = 'silence_start: 1\nsilence_end: 3\n I: -inf LUFS'
    result = verify.run('unused')
    assert not any(f['kind'] == 'silent_tail' for f in result['findings'])
    assert any(f['kind'] == 'loudness_off' for f in result['findings'])
    assert result['loudness_lufs'] is None
    json.dumps(result, allow_nan=False)


def test_video_without_audio(analysis, monkeypatch):
    monkeypatch.setattr(ffutil, 'probe', lambda path: {
        'streams': [{'codec_type': 'video', 'duration': '1'}],
        'format': {'duration': '1'}})
    calls = []
    monkeypatch.setattr(ffutil, 'capture', lambda args: (calls.append(args) or '', ''))
    assert verify.run('unused')['findings'] == []
    assert '-af' not in calls[0]


def test_report_layout_and_persistence(project, tmp_path, monkeypatch):
    monkeypatch.setattr(render, 'project_dir', lambda pid: tmp_path)
    slide = Slide(id='s1', take={'words': [{'start': 0, 'end': 1, 'src': 'tts'}]})
    captured = {}

    def run(path, story, frame):
        captured.update(story)
        assert frame is project.frame
        return {'findings': [], 'counts': {'P0': 1, 'P1': 2, 'P2': 3}}

    monkeypatch.setattr(verify, 'run', run)
    # Two inserted segments before the only rendered group; no omitted takes.
    summary = render._verify_output(tmp_path / 'out.mp4', project, [[(slide, 2)]],
                                    [1, 3, 2.6], {2: 0}, 0.4, lambda msg: None)
    assert summary == {'p0': 1, 'p1': 2, 'path': 'render/verify.json'}
    seg = captured['segments'][2]
    assert seg['start'] == 4.2
    assert seg['paragraphs'][0]['word_times'][0]['start'] == pytest.approx(4.8)
    assert json.loads((tmp_path / summary['path']).read_text())['counts']['P2'] == 3


def test_analysis_failure_is_report_only(project, tmp_path, monkeypatch):
    monkeypatch.setattr(render, 'project_dir', lambda pid: tmp_path)

    def fail(*args):
        raise ffutil.FFError('analysis failed')

    monkeypatch.setattr(verify, 'run', fail)
    summary = render._verify_output(tmp_path / 'out.mp4', project, [], [], {}, .4, print)
    assert summary['error'] == 'analysis failed'
    assert json.loads((tmp_path / summary['path']).read_text())['error'] == 'analysis failed'


def test_cli_arbitrary_file(clips, capsys):
    from app import cli
    assert cli.main(['verify', str(clips['black'])]) == 1
    assert json.loads(capsys.readouterr().out)['counts']['P0'] >= 1


@pytest.mark.parametrize('analysis_fails', [False, True])
def test_mux_calls_verifier_without_failing_render(setup_render, monkeypatch, analysis_fails):
    project, root = setup_render
    monkeypatch.setattr(render.cf, 'ThreadPoolExecutor', InlinePool)
    monkeypatch.setattr(render, '_render_segment', fake_segment)
    monkeypatch.setattr(ffutil, 'run', lambda args, **kw: Path(
        args[-1]).write_bytes(b'fake encode'))
    calls = []

    def check(path, story, frame):
        assert path.read_bytes() == b'fake encode'
        calls.append(story)
        if analysis_fails:
            raise ffutil.FFError('analysis failed')
        return {'findings': [{'severity': 'P0', 'kind': 'black_run', 't': 0,
                              'detail': 'Black lead-in'}],
                'counts': {'P0': 1, 'P1': 0, 'P2': 0}}

    monkeypatch.setattr(verify, 'run', check)
    result = render.render(project)
    assert len(calls) == 1 and project.status == 'rendered'
    assert project.render == result
    assert (root / result['verify']['path']).exists()
    if analysis_fails:
        assert result['verify']['error'] == 'analysis failed'
    else:
        assert result['verify']['p0'] == 1

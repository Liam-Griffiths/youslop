"""Two-pass mastering preserves the bed/voice gap and degrades safely."""
import json
import subprocess

import pytest

from app import audio, ffutil, render
from app.schema import IntroSpec


REPORT = dict(input_i='-16.2', input_tp='-6.0', input_lra='2.3',
              input_thresh='-26.4', target_offset='0.12')


@pytest.mark.parametrize('music,sting', [(False, False), (False, True),
                                        (True, False), (True, True)])
@pytest.mark.parametrize('target', [-14.0, -12.5])
def test_linear_master(project, monkeypatch, music, sting, target):
    project.frame.voice_lufs = target
    calls = []
    def capture(args, **kwargs):
        calls.append(args)
        return '', json.dumps(REPORT)
    monkeypatch.setattr(ffutil, 'capture', capture)
    stings = [(3, 0, 3, IntroSpec(), 'intro')] if sting else []
    graph = render._audio_graph(project, 2, 12, music, sting=stings)
    inputs = ['-i', 'picture0.mp4', '-i', 'picture1.mp4', '-i', 'voice.wav']
    if sting:
        inputs += ['-i', 'sting.wav']
    if music:
        inputs += ['-stream_loop', '-1', '-i', 'bed.wav']
    notes = []
    result = render._master_audio_graph(project, inputs, graph, 12, 2, notes.append)
    assert result.rsplit('loudnorm=', 1)[0] == graph.rsplit('loudnorm=', 1)[0]
    assert f'I={target:.3f}:TP=-1.0:LRA=20:measured_I=-16.2:measured_TP=-6.0:' in result
    assert 'measured_LRA=2.3:measured_thresh=-26.4:offset=0.12:linear=true:print_format=summary' in result
    args = calls[0]
    assert 'picture0.mp4' not in args and 'picture1.mp4' not in args
    assert args[:3] == ['-vn', '-i', 'voice.wav']
    analysis = args[args.index('-filter_complex') + 1]
    assert '[0:a]' in analysis and ':print_format=json[aout]' in analysis
    assert not any(':v]' in arg for arg in args)
    assert args[-3:] == ['-f', 'null', '-']
    assert any('normalization: linear' in note for note in notes)


@pytest.mark.parametrize('value', ['-inf', 'inf', 'nan', '-Infinity', float('nan'), None, 'oops'])
@pytest.mark.parametrize('key', list(REPORT))
def test_parse_rejects_nonfinite(key, value):
    assert audio._parse_loudnorm(json.dumps({**REPORT, key: value})) is None


def test_parse_uses_last_report():
    assert audio._parse_loudnorm('noise ' + json.dumps(REPORT) + json.dumps(
        {**REPORT, 'input_i': '-inf'})) is None
    assert audio._parse_loudnorm('{broken input_i}') is None
    assert audio._parse_loudnorm('{}') is None


@pytest.mark.parametrize('failure', [None, ffutil.FFError('bad input'),
                                     subprocess.TimeoutExpired('ffmpeg', 900)])
def test_measure_failure_keeps_single_pass(project, monkeypatch, failure):
    def capture(*args, **kwargs):
        if failure:
            raise failure
        return '', 'unparseable'
    monkeypatch.setattr(ffutil, 'capture', capture)
    graph = render._audio_graph(project, 0, 12, False)
    notes = []
    assert render._master_audio_graph(project, ['-i', 'voice.wav'], graph,
                                      12, 0, notes.append) == graph
    assert 'Warning:' in notes[-1] and 'single-pass' in notes[-1]


def test_peak_and_lra_constraints(project, monkeypatch):
    monkeypatch.setattr(ffutil, 'capture', lambda *a, **kw: (
        '', json.dumps({**REPORT, 'input_tp': '-1.2', 'input_lra': '23.1'})))
    notes = []
    result = render._master_audio_graph(project, ['-i', 'voice.wav'],
                                        render._audio_graph(project, 0, 12, False),
                                        12, 0, notes.append)
    assert 'I=-16.220:TP=-1.0:LRA=24:' in result
    assert any('target reduced' in note for note in notes)

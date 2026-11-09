"""Synthetic recordings and fake inference only."""
import wave
from copy import deepcopy

import pytest

from app import jobs, store, stt, take_timing
from app.schema import Project, Slide


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    project = Project(id='timing', idea='Synthetic', slides=[Slide(id='s', narration='Hello there')])
    path = store.project_dir(project.id) / 'takes' / 'recorded.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 32000)
    take = dict(path='takes/recorded.wav', raw_path='raw/kept.webm', duration=2,
                words=[dict(w='Hello', start=0, end=1, src='est')], custom='kept')
    project.set_take(project.slides[0], 'mic', take)
    store.save(project)
    original = path.read_bytes()
    yield project.id, path
    assert path.read_bytes() == original


def run(pid, progress=lambda m: None):
    _, identity = take_timing.snapshot(pid, 's', 'mic', 'takes/recorded.wav')
    return take_timing.retime(pid, 's', 'mic', 'takes/recorded.wav', identity,
                              dict(engine='fake', model='local'), progress)


def fake(**kw):
    yield dict(start=.2, end=1.5, text='Hello there', words=[
        dict(w='Hello', start=.2, end=.6, p=.9), dict(w='there', start=.9, end=1.5, p=.8)])


def test_retime_only_writes_words_and_reloads_other_edits(recorded, monkeypatch):
    pid, _ = recorded
    before = store.load(pid).slides[0].to_dict()
    def infer(**kw):
        p = store.load(pid)
        p.title = 'Edited while decoding'
        store.save(p)
        yield from fake(**kw)
    monkeypatch.setattr(stt, 'transcribe', infer)
    assert run(pid) == {'words': 2}
    p = store.load(pid)
    after = p.slides[0].to_dict()
    assert p.title == 'Edited while decoding'
    assert [w['src'] for w in after['take']['words']] == ['stt', 'stt']
    assert after['take']['words'][1]['end'] == 1.5
    for key in ('take', 'takes'):
        after.pop(key); before.pop(key)
    assert after == before
    take = p.slides[0].take
    assert take['custom'] == 'kept' and take['path'] == 'takes/recorded.wav'
    assert take['raw_path'] == 'raw/kept.webm' and take['duration'] == 2


@pytest.mark.parametrize('change', ['replacement', 'words', 'narration', 'track', 'retirement'])
def test_stale_results_never_apply(recorded, monkeypatch, change):
    pid, _ = recorded
    def infer(**kw):
        p = store.load(pid)
        s = p.slides[0]
        if change == 'replacement':
            p.set_take(s, 'mic', {**s.take, 'path': 'takes/new.wav'})
        elif change == 'words':
            s.take['words'][0]['w'] = 'Corrected'
        elif change == 'narration':
            s.narration = 'Changed'
        elif change == 'track':
            p.use_track('kokoro')
        else:
            p.set_take(s, 'mic', None)
        store.save(p)
        yield from fake(**kw)
    monkeypatch.setattr(stt, 'transcribe', infer)
    with pytest.raises(ValueError, match='changed|recorded'):
        run(pid)
    p = store.load(pid)
    assert not any(w.get('src') == 'stt' for t in p.slides[0].takes.values() for w in t['words'])
    if change in ('replacement', 'retirement'):
        assert p.slides[0].history[0]['path'] == 'takes/recorded.wav'


def test_cancel_and_segment_only_keep_estimates(recorded, monkeypatch):
    pid, _ = recorded
    before = deepcopy(store.load(pid).slides[0].to_dict())
    monkeypatch.setattr(stt, 'transcribe', fake)
    def cancel(message):
        if message == 'Saving word timings':
            raise jobs.JobCancelled()
    with pytest.raises(jobs.JobCancelled):
        run(pid, cancel)
    monkeypatch.setattr(stt, 'transcribe', lambda **kw: iter([dict(start=0, end=2, text='Hello', words=[])]))
    with pytest.raises(ValueError, match='no real word timings'):
        run(pid)
    assert store.load(pid).slides[0].to_dict() == before


def test_queued_stale_take_rejected_before_inference(recorded, monkeypatch):
    pid, _ = recorded
    _, identity = take_timing.snapshot(pid, 's', 'mic', 'takes/recorded.wav')
    p = store.load(pid)
    p.slides[0].narration = 'New text'
    store.save(p)
    monkeypatch.setattr(stt, 'transcribe', lambda **kw: pytest.fail('stale inference started'))
    with pytest.raises(ValueError, match='before retiming'):
        take_timing.retime(pid, 's', 'mic', 'takes/recorded.wav', identity, {}, lambda m: None)


def test_camera_timings_use_processed_audio_clock(recorded, monkeypatch):
    pid, _ = recorded
    p = store.load(pid)
    p.set_take(p.slides[0], 'camera', {**p.slides[0].take, 'video': 'takes/kept.mp4', 'trimmed': [3, 5]})
    p.slides[0].on_camera = True
    store.save(p)
    monkeypatch.setattr(stt, 'transcribe', fake)
    _, identity = take_timing.snapshot(pid, 's', 'camera', 'takes/recorded.wav')
    take_timing.retime(pid, 's', 'camera', 'takes/recorded.wav', identity,
                        dict(engine='fake', model='local'), lambda m: None)
    take = store.load(pid).slides[0].take
    assert take['words'][0]['start'] == .2  # No raw/video trim offset.
    assert take['trimmed'] == [3, 5] and take['video'] == 'takes/kept.mp4'


def test_retime_uses_shared_jitter_seams(recorded, monkeypatch):
    pid, _ = recorded
    monkeypatch.setattr(take_timing.ffutil, 'duration', lambda path: 601)
    def infer(**kw):
        assert kw['context'] is True
        shift = .3 if kw['start'] == 0 else -.3
        yield dict(start=598, end=601, text='go go now', words=[
            dict(w=text, start=t+shift, end=t+.1+shift)
            for text,t in [('go',599.7), ('go',600.1), ('now',600.6)]])
    monkeypatch.setattr(stt, 'transcribe', infer)
    assert run(pid) == {'words': 3}
    words = store.load(pid).slides[0].take['words']
    assert [w['w'] for w in words] == ['go','go','now']
    assert all(w['src'] == 'stt' for w in words)
    assert all(a['end'] <= b['start'] for a,b in zip(words, words[1:]))

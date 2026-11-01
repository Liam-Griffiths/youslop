"""Razor checks use synthetic WAVs and isolated project storage only."""
import wave

import pytest
from fastapi import HTTPException

from app import audio, ffutil, main, razor, store
from app.schema import Project, Slide


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='prazor', idea='Synthetic', slides=[Slide(
        narration='First sentence. Second sentence.', beat='A chapter',
        chosen_id='picture', locked_media=True,
        cues={'loudmouth': [{'on': 'First', 'text': 'one'},
                            {'on': 'Second', 'text': 'two', 'at': .7}]})])
    store.save(p)
    return p


def record(p, track='mic', tone=.4):
    root = store.project_dir(p.id)
    s = p.slides[0]
    path = root / 'takes' / track / f'{s.id}.wav'
    path.parent.mkdir(parents=True, exist_ok=True)
    ffutil.run(['-f', 'lavfi', '-i', f'sine=frequency=440:duration={tone}',
                '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono:d=0.2',
                '-f', 'lavfi', '-i', f'sine=frequency=660:duration={tone}',
                '-filter_complex', '[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]',
                '-map', '[a]', '-c:a', 'pcm_s16le', str(path)])
    p.set_take(s, track, {'path': path.relative_to(root).as_posix(),
                         'raw_path': 'raw/original.webm', 'duration': tone * 2 + .2,
                         'words': [
                             {'w': 'First', 'start': 0., 'end': tone / 2, 'src': 'tts'},
                             {'w': 'sentence.', 'start': tone / 2, 'end': tone, 'src': 'tts'},
                             {'w': 'Second', 'start': tone + .2, 'end': tone * 1.5 + .2, 'src': 'tts'},
                             {'w': 'sentence.', 'start': tone * 1.5 + .2, 'end': tone * 2 + .2, 'src': 'tts'}]})
    store.save(p)
    return path


def files(p):
    return {str(f.relative_to(store.project_dir(p.id))): f.read_bytes()
            for f in store.project_dir(p.id).rglob('*') if f.is_file()}


def test_split_all_tracks_preserves_originals(saved):
    originals = [record(saved), record(saved, 'kokoro', .6)]
    before = files(saved)
    result = main.split_slide(saved.id, saved.slides[0].id, {'at': .5})
    assert result['approximate'] is False
    p = store.load(saved.id)
    head, tail = p.slides
    root = store.project_dir(p.id)
    assert head.narration + ' ' + tail.narration == saved.slides[0].narration
    assert tail.picture_mode == 'hold' and tail.chosen_id == 'picture' and tail.locked_media
    assert head.gap_override == 0 and audio.paragraph_gaps(p)[0] == 0
    assert head.cues['loudmouth'][0]['on'] == 'First'
    assert tail.cues['loudmouth'][0]['on'] == 'Second'
    assert not head.needs_cues and not tail.needs_cues
    assert {h['track'] for h in head.history} == {'mic', 'kokoro'}
    for original, track, start, stop in zip(originals, ['mic', 'kokoro'], [.4, .6], [.6, .8]):
        a, b = head.takes[track], tail.takes[track]
        cut = a['split_from']['end']
        assert start < cut < stop
        assert b['split_from']['start'] == cut
        assert a['split_from']['path'] == b['split_from']['path'] == str(original.relative_to(root))
        assert abs(a['duration'] + b['duration'] - ffutil.duration(original)) < .025
        assert (root / a['path']).exists() and (root / b['path']).exists()
        assert a['raw_path'] == b['raw_path'] == ''
        assert b['words'][0]['start'] == pytest.approx(stop - cut)
        assert original.read_bytes() == before[str(original.relative_to(root))]
        def samples(path):
            with wave.open(str(path), 'rb') as wav:
                return wav.readframes(wav.getnframes())
        assert samples(root / a['path']) + samples(root / b['path']) == samples(original)
    assert head.take == head.takes['mic'] and tail.take == tail.takes['mic']
    assert all(h['reason'] == 'split' and h['raw_path'] for h in head.history)
    assert tail.cues['loudmouth'][0]['at'] == pytest.approx(.7 - head.take['duration'], abs=.001)
    assert len(files(p)) == len(before) + 4


def test_ffmpeg_failure_is_atomic(saved, monkeypatch):
    record(saved)
    record(saved, 'kokoro')
    before = files(saved)
    real = ffutil.run
    calls = 0
    def fail(args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ffutil.FFError('forced ffmpeg failure')
        return real(args, **kwargs)
    monkeypatch.setattr(ffutil, 'run', fail)
    with pytest.raises(HTTPException) as exc:
        main.split_slide(saved.id, saved.slides[0].id, {'at': .5})
    assert exc.value.status_code == 409
    assert 'forced ffmpeg failure' in exc.value.detail
    assert files(saved) == before
    assert not list(store.project_dir(saved.id).glob('.razor-*'))


def test_estimated_words(saved):
    record(saved)
    p = store.load(saved.id)
    p.slides[0].take['words'] = []
    store.save(p)
    main.split_slide(p.id, p.slides[0].id, {'at': .5})
    head, tail = store.load(p.id).slides
    assert head.take['words'] and tail.take['words']
    assert all(w['src'] == 'est' for w in head.take['words'])


def test_text_only_default_and_approximate(saved):
    result = main.split_slide(saved.id, saved.slides[0].id, {})
    assert [s['narration'] for s in result['slides']] == ['First sentence.', 'Second sentence.']
    assert not result['slides'][0]['takes']
    p = store.load(saved.id)
    p.slides[0].narration = 'Words without sentence punctuation'
    store.save(p)
    result = main.split_slide(p.id, p.slides[0].id, {'at': .8})
    assert result['approximate'] is True
    assert result['slides'][0]['needs_cues'] is False
    assert result['slides'][1]['needs_cues'] is True


@pytest.mark.parametrize('at', [-1, float('nan'), 'invalid'])
def test_bad_time_changes_nothing(saved, at):
    before = files(saved)
    with pytest.raises(HTTPException) as exc:
        main.split_slide(saved.id, saved.slides[0].id, {'at': at})
    assert exc.value.status_code == 409
    assert files(saved) == before


def test_overlapping_words_refused(saved):
    record(saved)
    p = store.load(saved.id)
    for w in p.slides[0].take['words']:
        w['start'], w['end'] = 0., 1.
    store.save(p)
    before = files(p)
    with pytest.raises(HTTPException) as exc:
        main.split_slide(p.id, p.slides[0].id, {'at': .5})
    assert exc.value.status_code == 409
    assert files(p) == before


def test_concurrent_edit_is_not_overwritten(saved, monkeypatch):
    real = razor.prepare
    def edit(*args):
        result = real(*args)
        p = store.load(saved.id)
        p.slides[0].beat = 'Concurrent edit'
        store.save(p)
        return result
    monkeypatch.setattr(razor, 'prepare', edit)
    with pytest.raises(HTTPException) as exc:
        main.split_slide(saved.id, saved.slides[0].id, {})
    assert exc.value.status_code == 409
    p = store.load(saved.id)
    assert len(p.slides) == 1 and p.slides[0].beat == 'Concurrent edit'


def test_save_failure_removes_only_new_halves(saved, monkeypatch):
    record(saved)
    before = files(saved)
    def fail(*args):
        raise OSError('forced save failure')
    monkeypatch.setattr(store, 'save', fail)
    with pytest.raises(HTTPException) as exc:
        main.split_slide(saved.id, saved.slides[0].id, {})
    assert exc.value.status_code == 409
    assert files(saved) == before


def test_existing_numbered_file_is_preserved(saved):
    record(saved)
    root = store.project_dir(saved.id)
    occupied = root / 'takes' / 'mic' / f'{saved.slides[0].id}.2.wav'
    occupied.write_bytes(b'existing recording')
    main.split_slide(saved.id, saved.slides[0].id, {})
    assert occupied.read_bytes() == b'existing recording'
    assert store.load(saved.id).slides[0].take['path'].endswith('.3.wav')


def test_sentence_preference_and_default_middle():
    text = 'One. Two three four. Five.'
    items = [{'start': i, 'end': i + .8} for i in range(5)]
    assert razor.boundary(text, items, 1.7) == (1, False)
    assert razor.boundary(text, items, None) == (1, False)
    assert razor.boundary('one two three', items[:3], 1.7) == (2, True)


def test_spoken_number_timings_group_onto_narration_words():
    from app import razor
    items = [{'w': w, 'start': i, 'end': i + .9} for i, w in
             enumerate('In twenty seventeen Bridle wrote.'.split())]
    grouped = razor._group_spoken(items, 'In 2017 Bridle wrote.'.split())
    assert [g['w'] for g in grouped] == ['In', '2017', 'Bridle', 'wrote.']
    assert grouped[1]['start'] == 1 and grouped[1]['end'] == 2.9

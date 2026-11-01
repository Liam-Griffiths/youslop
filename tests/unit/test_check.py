"""Check doctrine with synthetic storyboards and no media/model work."""
from time import perf_counter
from types import SimpleNamespace

import pytest

from app import audio, check, ffutil, llm, render, storyboard, titles
from app.config import HEAD_PAD
from app.schema import FrameSpec


def _sb(**overrides):
    frame = FrameSpec()
    p = dict(id='s1', start=.6, end=5, narration='Hello world.', title='', chapter='',
             picture={'path': 'fixture.jpg'},
             take={'path': 'take.wav', 'duration': 4, 'words': [
                 {'w': 'Hello', 'start': 0, 'end': .3, 'src': 'tts'}]})
    seg = dict(type='picture', lead='s1', start=0, duration=5, skip=.2,
               camera='creep', problems=[], paragraphs=[dict(id='s1', duration=4.4)])
    return dict(project={'format': 'kenburns', 'duration': 5}, frame=frame.to_dict(),
                style={'captions_engine': 'pillow'},
                segments=[seg], paragraphs=[p], outline={'hook': {'muted_image': 'A face'}},
                music=False) | overrides


def _cue(sb, start=0, end=3, kind='shout', text='Hello', on='Hello'):
    sb['project']['format'] = 'loudmouth'
    sb['paragraphs'][0].setdefault('cues', []).append(
        dict(start=start, end=end, kind=kind, text=text, on=on))


def _fire(code, sb, frame=None):
    frame = frame or FrameSpec.from_dict(sb['frame'])
    return getattr(check, code)(sb, frame, check._ctx(sb))


# Sponsor rule fixtures live in test_sponsors.py.
@pytest.mark.parametrize('code', [r.__name__ for r in check.RULES if not r.__name__.startswith("sponsor_")])
def test_each_rule_positive_and_negative(code, monkeypatch):
    sb = _sb()
    if code == 'empty_first_frame':
        sb['paragraphs'][0]['picture']['path'] = ''
    elif code == 'hook_muted':
        sb['outline'] = {}
    elif code == 'first_word_collision':
        sb['sting_end'] = 1
    elif code == 'dead_stretch':
        sb['segments'][0]['duration'] = 16
    elif code == 'overlay_budget':
        sb['frame'].update(overlays_per_hook=2, overlays_per_90_s=2)
    elif code == 'small_text':
        sb['project']['format'] = 'essay'
        monkeypatch.setattr(titles, '_fit_caption', lambda *a: (SimpleNamespace(size=26), []))
    elif code in {'unreadable_line', 'last_line_short'}:
        _cue(sb, end=.5)
    elif code == 'anchor_off':
        _cue(sb, start=1)
    elif code == 'same_device_twice':
        sb['segments'].append(dict(sb['segments'][0], start=5, lead='s2'))
    elif code == 'silent_film':
        sb['project']['duration'] = 21
        sb['paragraphs'][0]['take'] = {}
    elif code == 'open_loop_unpaid':
        sb['outline']['hook']['open_loops'] = [{'payoff_beat': 'Answer'}]
    elif code == 'banned_used':
        sb['frame']['banned'] = ['creep']
    elif code == 'timeline_problem':
        sb['segments'][0]['problems'] = ['no picture chosen']
    result = _fire(code, sb)
    assert result and all(f.code == code for f in result)
    assert all(set(f.to_dict()) == {'code', 'level', 't', 'slide_id', 'msg', 'fix'} for f in result)
    if code == 'empty_first_frame':
        sb['paragraphs'][0]['picture']['path'] = 'fixture.jpg'
    elif code == 'hook_muted':
        sb['outline'] = {'hook': {'muted_image': 'A face'}}
    elif code == 'first_word_collision':
        sb['sting_end'] = .6  # end is exclusive
    elif code == 'dead_stretch':
        sb['segments'][0]['duration'] = 15
    elif code == 'overlay_budget':
        sb['frame'].update(overlays_per_hook=1, overlays_per_90_s=1)
    elif code == 'small_text':
        monkeypatch.setattr(titles, '_fit_caption', lambda *a: (SimpleNamespace(size=70), []))
    elif code in {'unreadable_line', 'last_line_short'}:
        sb['paragraphs'][0]['cues'][0]['end'] = 3
    elif code == 'anchor_off':
        sb['paragraphs'][0]['cues'][0]['start'] = .7
    elif code == 'same_device_twice':
        sb['segments'][1]['camera'] = 'punch'
    elif code == 'silent_film':
        sb['music'] = True
    elif code == 'open_loop_unpaid':
        sb['outline']['sections'] = [{'heading': 'Answer'}]
    elif code == 'banned_used':
        sb['frame']['banned'] = ['spin']
    elif code == 'timeline_problem':
        sb['segments'][0]['problems'] = []
    assert _fire(code, sb) == []


def test_cuts_missing_cue_and_dead_stretch():
    sb = _sb()
    sb['project']['format'] = 'loudmouth'
    assert _fire('empty_first_frame', sb)
    _cue(sb)
    assert not _fire('empty_first_frame', sb)
    assert _fire('dead_stretch', sb)
    _cue(sb, start=2, end=5, kind='quote')
    assert not _fire('dead_stretch', sb)
    assert not _fire('same_device_twice', sb)
    sb['paragraphs'][0]['cues'][1]['kind'] = 'shout'
    assert _fire('same_device_twice', sb)


def test_gap_limits_and_dedup():
    sb = _sb()
    seg = sb['segments'][0]
    seg.update(start=91, duration=26, problems=['the same picture holds for 26s', 'no picture chosen'])
    assert _fire('dead_stretch', sb)
    assert [f.msg for f in _fire('timeline_problem', sb)] == ['no picture chosen']
    sb['frame'].update(max_gap_after_s=40, max_gap_ever_s=25)
    assert _fire('dead_stretch', sb)
    seg['duration'] = 25
    assert not _fire('dead_stretch', sb)
    assert len(_fire('timeline_problem', sb)) == 2


def test_anchors_normalise_search_forward_and_estimated():
    sb = _sb()
    p = sb['paragraphs'][0]
    p['start'] = 10
    p['take']['words'] = [dict(w=w, start=i, src='est')
                          for i, w in enumerate(['HELLO,', 'world!', 'Hello', 'world'])]
    _cue(sb, start=10, on='hello world extra')
    _cue(sb, start=13, on='hello world extra')
    _cue(sb, start=100, on='absent')
    findings = _fire('anchor_off', sb)
    assert len(findings) == 1
    assert findings[0].level == 'P2'
    assert findings[0].fix['anchor'] == 12
    p['cues'][1]['start'] = 11.4  # exactly anchor_before_s
    assert not _fire('anchor_off', sb)


def test_text_and_collision_windows():
    sb = _sb()
    sb['paragraphs'][0]['title'] = 'Opening'
    assert _fire('first_word_collision', sb)  # .6 is in .25 .. .70 title arrival
    sb['paragraphs'][0]['take']['words'][0]['start'] = 1
    assert not _fire('first_word_collision', sb)
    sb['segments'][0]['cards'] = [dict(start=1, end=2, text='Chapter', slide_id='s1')]
    assert _fire('first_word_collision', sb)
    assert not _fire('small_text', sb)
    sb['project']['format'] = 'essay'
    assert any(l['type'] == 'caption' for l in check._ctx(sb).lines)


def test_silence_merges_coverage_and_includes_tail():
    sb = _sb(music_spans=[(0, 16), (10, 20)])
    sb['project']['duration'] = 35
    assert not _fire('silent_film', sb)
    sb['project']['duration'] = 35.01
    assert _fire('silent_film', sb)[0].t == 20


def test_run_fixture(project, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('check attempted rendering, probing or a model call')
    monkeypatch.setattr(ffutil, 'run', forbidden)
    monkeypatch.setattr(ffutil, 'duration', forbidden)
    monkeypatch.setattr(llm, 'complete_json', forbidden)
    before = project.to_dict()
    build = storyboard.build
    calls = []
    def counted(p):
        calls.append(p.id)
        return build(p)
    monkeypatch.setattr(storyboard, 'build', counted)
    start = perf_counter()
    result = check.run(project)
    elapsed = perf_counter() - start
    assert elapsed < .3
    assert calls == [project.id]
    assert project.to_dict() == before
    assert result['ok'] is True
    assert result['counts'] == {'P0': 0, 'P1': 5, 'P2': 2}
    assert [f['code'] for f in result['findings']] == [
        'hook_muted', 'last_line_short', 'timeline_problem', 'timeline_problem',
        'timeline_problem', 'overlay_budget', 'overlay_budget']
    project.slides[0].chosen_id = ''
    assert check.run(project)['ok'] is False
    # Independent narration-bed placement for a recorded paragraph: no extra T/2.
    sb = build(project)
    gaps = audio.paragraph_gaps(project)
    assert sb['paragraphs'][0]['start'] == HEAD_PAD
    assert sb['paragraphs'][1]['start'] == pytest.approx(
        HEAD_PAD + project.slides[0].take['duration'] + gaps[0], abs=.001)


def test_real_font_cache_and_fit():
    font, _ = titles._fit_caption('Hello', titles.CAPTION_MAX_W)
    assert titles._load(titles.DISPLAY_STACK, font.size) is font
    sb = _sb()
    sb['project']['format'] = 'essay'
    sb['paragraphs'][0]['narration'] = 'Extraordinarilylongword ' * 6
    sb['frame']['title_height_pct_min'] = 9
    assert _fire('small_text', sb)


@pytest.mark.parametrize('fmt', ['essay', 'loudmouth', 'ticker', 'groupchat'])
def test_run_other_formats(project, fmt, monkeypatch):
    project.style.format = fmt
    monkeypatch.setattr('app.stage.browser', lambda: None)
    monkeypatch.setattr(ffutil, 'run', lambda *a, **k: pytest.fail('rendered media'))
    result = check.run(project)
    assert sum(result['counts'].values()) == len(result['findings'])
    assert result['ok'] == (result['counts']['P0'] == 0)
    assert not any(f['code'] == 'empty_first_frame' for f in result['findings'])


def test_intro_title_only_and_sting(project, monkeypatch, tmp_path):
    from app.schema import IntroSpec
    project.intro = IntroSpec(template='columns', images=[])
    project.outline = {'hook': {'muted_image': 'A portrait'}}
    project.slides[0].take['words'] = [dict(w='First', start=0, end=.3, src='tts')]
    spec = IntroSpec(music_tail=1.1)
    sting = tmp_path / 'sting.wav'
    sting.write_bytes(b'fixture')
    monkeypatch.setattr(render, '_stings_for', lambda *a: {'intro': (sting, spec)})
    result = check.run(project)
    assert any(f['code'] == 'hook_muted' for f in result['findings'])
    assert any(f['code'] == 'first_word_collision' for f in result['findings'])
    project.intro.images = ['portrait.jpg']
    spec.music_tail = 0
    project.slides[0].title = ''
    result = check.run(project)
    assert not any(f['code'] in {'hook_muted', 'first_word_collision'} for f in result['findings'])

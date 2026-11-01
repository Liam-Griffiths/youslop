"""Layer planning and preview variants, without rendering, network or a browser."""
from types import SimpleNamespace

import pytest

from app import cuts, main, render, scenes


def test_titles_chapters_match_graph(project, monkeypatch):
    project.style.format = 'kenburns'
    project.style.picture_every = 1
    project.slides[0].title_at = 1
    project.slides[0].title_hold = 2
    project.slides[1].chapter = 'Next section'
    project.slides[1].chapter_hold = 1.2
    monkeypatch.setattr(render.titles, 'render_title', lambda *a, **k: None)
    monkeypatch.setattr(render.titles, 'render_chapter', lambda *a, **k: None)
    tl = render.timeline(project)
    groups = render._groups_for_preview(project)
    for seg, group in zip(tl['segments'], groups):
        _, _, length = render._segment_timing(project, groups, seg['group'])
        _, graph, _ = render._segment_graph(project, group, length, 'set')
        for item in tl['layers']['titles']:
            if item['sid'] not in {s.id for s, _ in group}:
                continue
            start = item['t0'] - seg['start'] + seg['skip']
            assert f'fade=t=in:st={start:.3f}' in graph
    chapter = tl['layers']['chapters'][0]
    first = tl['segments'][0]
    assert chapter['sid'] == project.slides[1].id
    assert chapter['t0'] == pytest.approx(first['duration'] + first['skip'] - 1.2, abs=.001)
    assert chapter['t1'] == first['duration']
    _, graph, _ = render._segment_graph(project, groups[0], first['duration'] + 2 * first['skip'],
                                       'set', chapter=('Next section', ''))
    assert f"fade=t=in:st={chapter['t0'] + first['skip']:.3f}" in graph
    _, hidden, _ = render._segment_graph(project, groups[0], 8, 'set',
                                         chapter=('Next section', ''), hide={'titles', 'chapters'})
    assert '[ttl' not in hidden and '[chap]' not in hidden


def test_cues_include_derived_and_user_times(project):
    project.style.format = 'flameboat'
    slide = project.slides[0]
    slide.cues['flameboat'] = [{'kind': 'title', 'text': 'Test cue', 'at': 1.25}]
    tl = render.timeline(project)
    cue = next(c for c in tl['layers']['cues'] if c['sid'] == slide.id)
    para = tl['segments'][0]['paragraphs'][0]
    assert cue['t0'] == para['timing']['cues'][0]['start']
    group = render._groups_for_preview(project)[0]
    seg = tl['segments'][0]
    _, _, length = render._segment_timing(project, render._groups_for_preview(project), 0)
    _, _, spans = cuts.timed_cues(project, group, length, seg['skip'] + render.HEAD_PAD)[0]
    assert cue['t0'] == pytest.approx(spans[0][0] - seg['skip'], abs=.001)
    assert cue['text'] == 'Test cue' and cue['src'] == 'user' and cue['cue'] == 0
    assert any(c['sid'] == project.slides[1].id for c in tl['layers']['cues'])


def test_music_sting_and_sponsor_spans(project, monkeypatch, tmp_path):
    music = tmp_path / 'bed.wav'
    monkeypatch.setattr(render, 'pick_music', lambda *a: music)
    spec = SimpleNamespace(music_tail=1.5, music_start=0, music_fade=.5)
    monkeypatch.setattr(render, '_stings_for', lambda *a: {'intro': (tmp_path / 'sting.wav', spec)})
    layers = render._layers(project, [dict(type='intro', start=0, duration=4),
        dict(type='sponsor', start=4, duration=6, sponsor='slot', script='Sponsor read')])
    assert (layers['music'][0]['t0'], layers['music'][0]['t1']) == (3.65, 10)
    assert layers['stings'][0]['t1'] == 5.5
    assert layers['sponsors'][0]['t0'] == 4


def test_proxy_variants_reuse_and_hide_threading(project, monkeypatch):
    monkeypatch.setattr(render.media, 'download_chosen', lambda *a, **kw: pytest.fail('download'))
    calls = []
    def draw(*args, **kwargs):
        calls.append(kwargs['hide'])
        args[4].write_bytes(b'proxy')
    monkeypatch.setattr(render, '_render_segment', draw)
    monkeypatch.setattr(render.audio_mod, 'build_slice', lambda *a, **kw: (_ for _ in ()).throw(ValueError()))
    plain = render.proxy_segment(project, 0, download=False)
    hidden = render.proxy_segment(project, 0, download=False, hide=frozenset({'cues'}))
    again = render.proxy_segment(project, 0, download=False)
    assert calls == [frozenset(), frozenset({'cues'})]
    assert plain['path'] == again['path'] != hidden['path']
    assert plain['key'] != hidden['key']
    assert render.timeline(project, frozenset({'cues'}))['segments'][0]['ready']


def test_hidden_cuts_skip_cue_pixels(project, monkeypatch, tmp_path):
    project.style.format = 'flameboat'
    project.style.cut_engine = 'pillow'  # This test exercises the Pillow stream.
    monkeypatch.setattr(cuts.flameboat, 'frame', lambda *a: pytest.fail('cue frame drawn'))
    frames = []
    def encode(stream, out, **kw):
        frames.extend(stream)
        out.write_bytes(b'encoded')
        return True
    monkeypatch.setattr(cuts.ffutil, 'encode_frames', encode)
    cuts.render_segment(project, [(project.slides[0], 1)], 1, tmp_path / 'proxy.webm',
                        size=(48, 27), fps=1, hide={'cues'})
    assert len(frames) == 1 and frames[0].size == (48, 27)


def test_mix_hidden_inputs_and_cache(project, monkeypatch, tmp_path):
    music, sting = tmp_path / 'music.wav', tmp_path / 'sting.wav'
    monkeypatch.setattr(render, 'pick_music', lambda *a: music)
    spec = project.intro
    monkeypatch.setattr(render, '_stings_for', lambda *a: {'intro': (sting, spec)})
    lay = render._layout(project)
    lay['intro'] = {'length': 4}
    monkeypatch.setattr(render, '_layout', lambda p: lay)
    monkeypatch.setattr(render.audio_mod, 'build_narration', lambda p, path, **kw: path.write_bytes(b'nar'))
    captured = []
    def run(args, **kw):
        captured.append(args)
        from pathlib import Path
        Path(args[-1]).write_bytes(b'mix')
    monkeypatch.setattr(render.ffutil, 'run', run)
    plain = render.build_mix(project)
    hidden = render.build_mix(project, hide={'music', 'stings'})
    assert str(music) in captured[0] and str(sting) in captured[0]
    assert str(music) not in captured[1] and str(sting) not in captured[1]
    assert plain['path'] != hidden['path']
    assert render.build_mix(project)['ready']
    assert len(captured) == 2


def test_notes_endpoint_and_hide_validation(project, monkeypatch):
    monkeypatch.setattr(main, '_load', lambda pid: project)
    monkeypatch.setattr(main.check, 'run', lambda p: {'findings': [
        dict(t=1, level='P1', msg='Check note', rule='test', slide_id=project.slides[0].id, fix={'kind': 'text'})]})
    monkeypatch.setattr(main.review, 'read_notes', lambda pid: {'notes': []})
    monkeypatch.setattr(main, 'get_review', lambda pid: {'notes': [
        dict(id='review', t=2, severity='P2', problem='Review note')]})
    notes = main.get_timeline(project.id, hide='cues')['layers']['notes']
    assert [n['text'] for n in notes] == ['Check note', 'Review note']
    assert notes[0]['t1'] - notes[0]['t0'] == pytest.approx(.8)
    with pytest.raises(main.HTTPException):
        main.get_timeline(project.id, hide='unknown')


def test_essay_caption_windows(project, monkeypatch):
    project.style.captions_engine = "pillow"  # This test inspects legacy fades.
    project.style.format = 'essay'
    monkeypatch.setattr(render.titles, 'render_caption', lambda *a, **kw: None)
    tl = render.timeline(project)
    groups = render._groups_for_preview(project)
    assert tl['layers']['titles']
    for seg, group in zip(tl['segments'], groups):
        _, _, length = render._segment_timing(project, groups, seg['group'])
        _, graph, _ = render._segment_graph(project, group, length, 'set',
                                           last_line=seg is tl['segments'][-1])
        for item in tl['layers']['titles']:
            if item['sid'] not in {s.id for s, _ in group} or item['t0'] == 0:
                continue
            start = item['t0'] - seg['start'] + seg['skip']
            import re
            arrivals = [float(t) for t in re.findall(r'fade=t=in:st=([\d.]+)', graph)]
            assert any(abs(t - start) < .001 for t in arrivals)


def test_scene_hide_preserves_project(project, monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(scenes, 'ensure_clip', lambda p, name, ctx, **kw: captured.append(ctx) or tmp_path / 'clip')
    monkeypatch.setattr(scenes, '_encode', lambda *a: None)
    project.style.format = 'flameboat'
    slide = project.slides[0]
    title = slide.title
    scenes.render_segment(project, [(slide, 3)], 3, tmp_path / 'proxy', hide={'titles', 'cues'})
    assert captured[0]['titles'] == captured[0]['cues'] == []
    assert captured[0]['slides'][0]['title'] == ''
    assert slide.title == title

"""Essay planning and scene integration: no browser, encoder or model calls."""
import io
from types import SimpleNamespace

import pytest

from app import check, cuts, render, scenes, stage, titles
from app.schema import FrameSpec, Project
from tests.unit.test_scene_contract import SceneContract


def timed(text, step=.4):
    return [dict(w=w, start=i * step, end=(i + .7) * step, src='est')
            for i, w in enumerate(text.split())]


def test_split_and_fallback_preserve_legacy():
    text = 'A sentence with enough words. Another sentence that should stay together. ' * 3
    chunks = titles.essay_chunks(text)
    shares = render._caption_timings(chunks, 12, FrameSpec())
    plan = titles.phrases(text, [], duration=12, lead_in=99)
    assert [p['text'] for p in plan] == chunks
    assert plan[0]['t0'] == 0  # Same first start as the old PNG loop.
    assert [p['t1'] - p['t0'] for p in plan] == pytest.approx(shares)
    assert plan[-1]['t1'] == pytest.approx(12)
    assert titles.phrases('', [], duration=1) == []


@pytest.mark.parametrize('words', [None, [], [{'w': 'stale'}],
    [{'w': 'Hello', 'start': float('nan'), 'end': 1}],
    [{'w': 'Hello', 'start': 1, 'end': 0}],
    [{'w': 'Hello', 'start': 0, 'end': 5}]])
def test_unusable_words_fall_back(words):
    assert titles.phrases('Hello', words, duration=2) == [dict(text='Hello', t0=0, t1=2)]


def test_word_anchors_floor_no_overlap_and_lead():
    text = 'one two three four five six seven eight nine ten eleven twelve'
    words = timed(text)
    plan = titles.phrases(text, words, max_words=4, duration=6, lead_in=.875)
    assert len(plan) == 3
    assert plan[0]['t0'] == pytest.approx(.975)
    assert plan[0]['t1'] == pytest.approx(plan[1]['t0'] - .6)
    assert all(a['t1'] <= b['t0'] for a, b in zip(plan, plan[1:]))
    fast = titles.phrases(text, timed(text, .1), max_words=4, duration=2)
    assert all(a['t1'] <= b['t0'] for a, b in zip(fast, fast[1:]))
    assert plan[-1]['t1'] == pytest.approx(6.875)


def test_scene_contract_and_escaping(project):
    ctx = scenes.context_base(project)
    ctx['phrases'] = [dict(text='<b>Emoji 🐈 & wrapping</b>', t0=.1, t1=2)]
    html = scenes.render_html('essay/captions.html', ctx)
    assert scenes.lint(html) == []
    parser = SceneContract()
    parser.feed(html)
    parser.check()
    assert len(parser.clips) == 1
    assert parser.clips[0]['data-anim'] == 'rise'
    assert float(parser.clips[0]['data-start']) == .1
    assert float(parser.clips[0]['data-duration']) == 1.9
    assert '&lt;b&gt;Emoji 🐈 &amp; wrapping&lt;/b&gt;' in html
    assert 'ArchivoBlack-Regular.ttf' in html
    assert 'background: transparent !important' in html
    assert 'text-wrap: balance' in html and 'max-height: 3.12em' in html
    assert f'font-size: {titles.CAPTION_CAP}px' in html
    assert 'const min = Math.min(62, 43.2)' in html
    assert 'while (size > min &&' in html


def test_plate_overlays_group_offsets_hidden_and_legacy(project, tmp_path, monkeypatch):
    project.style.format = 'essay'
    first, second = project.slides[:2]
    first.narration = second.narration = 'one two three four'
    first.take = dict(duration=2, words=timed(first.narration))
    second.take = dict(duration=2, words=[])
    calls = []

    def plates(p, ctx, **kwargs):
        calls.append((ctx, kwargs))
        return tmp_path / 'captions.mov'

    monkeypatch.setattr(scenes, 'caption_plates', plates)
    monkeypatch.setattr(titles, 'render_caption', lambda *a, **k: pytest.fail('PNG scene caption'))
    group = [(first, 3), (second, 3)]
    inputs, graph, last = render._segment_graph(project, group, 6, 'set', size=(480, 270), last_line=True)
    assert len(calls) == 1
    assert inputs.count(str(tmp_path / 'captions.mov')) == 1
    assert 'overlay=0:0:eof_action=pass:repeatlast=0:format=auto' in graph
    assert last == '[vcaptions]'
    plan = calls[0][0]['phrases']
    lead = cuts.transition_for(project.style) / 2 + cuts.head_pad_for(project, first)
    assert plan[0]['t0'] == pytest.approx(lead + .1)
    assert plan[1]['t0'] == 3  # Legacy offset for a take without word timings.
    assert plan[1]['t1'] == 5
    assert calls[0][1]['size'] == (480, 270)
    render._segment_graph(project, group, 4, 'set', last_line=True)
    assert calls[-1][0]['phrases'][-1]['t1'] == pytest.approx(3.95)
    render._segment_graph(project, group, 6, 'set', hide=frozenset({'titles'}))
    assert len(calls) == 2
    project.style.captions_engine = 'pillow'
    pngs = []
    monkeypatch.setattr(titles, 'render_caption', lambda text, **kw: pngs.append(text))
    _, legacy, _ = render._segment_graph(project, group, 6, 'set')
    assert len(calls) == 2 and pngs == [first.narration, second.narration]
    assert 'fade=t=in:st=0.000:d=0.14:alpha=1' in legacy
    assert 'fade=t=in:st=3.000:d=0.14:alpha=1' in legacy


def test_caption_builder_cache_and_prepare_only(project, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import scene_builder
    ctx = scenes.context_base(project)
    ctx.update(duration=6, phrases=[dict(text='Hello', t0=0, t1=2), dict(text='World', t0=2, t1=4)])
    calls = []
    def build(*args, **kwargs):
        calls.append((args, kwargs))
        args[3].write_bytes(b'mocked transparent clip')
        return SimpleNamespace(path=args[3])
    monkeypatch.setattr(scene_builder, 'render', build)
    path = scenes.caption_plates(tmp_path, ctx, size=(480, 270), render=False)
    assert not calls and not path.exists()
    assert scenes.caption_plates(tmp_path, ctx, size=(480, 270)) == path
    assert scenes.caption_plates(tmp_path, ctx, size=(480, 270)) == path
    assert len(calls) == 1 and calls[0][0][2]['builder_alpha']
    assert calls[0][1] == dict(seconds=6, size=(480, 270), fps=30, crf=17)
    ctx['phrases'][0]['text'] = 'Changed'
    assert scenes.caption_plates(tmp_path, ctx, size=(480, 270)) != path
    assert len(calls) == 2


def test_alpha_encoder_argv(tmp_path, monkeypatch):
    calls = []
    def popen(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdin=io.BytesIO(), stderr=io.BytesIO())
    monkeypatch.setattr(stage.subprocess, 'Popen', popen)
    run = SimpleNamespace(out_dir=tmp_path, clips={})
    stage._begin_png(run, 'alpha', 480, 270, 15, 30, alpha=True)
    argv = calls[-1]
    assert argv[argv.index('-pix_fmt') + 1] == 'rgba'
    assert argv.count('png') == 2 and argv[-1].endswith('.part.mov')
    assert run.clips['alpha']['out'].suffix == '.mov'
    stage._begin_png(run, 'opaque', 480, 270, 15, 30)
    assert 'libx264' in calls[-1] and 'yuv420p' in calls[-1]


def test_geometry_one_dry_capture_and_check(project, monkeypatch):
    calls = []
    def measure(items, root, **kwargs):
        calls.append(len(items))
        return {item['clip']: [dict(px=43.2, overflow=bool(i))] for i, item in enumerate(items)}
    monkeypatch.setattr(stage, 'measure_many', measure)
    texts = ['Good', 'Too much text']
    metrics = scenes.measure_captions(project, texts)
    assert scenes.measure_captions(project, texts) == metrics
    assert calls == [2]
    ctx = check.Ctx([], [], [dict(type='caption', start=0, end=4, slide_id='s', text=t, metrics=m)
                            for t, m in zip(texts, metrics)])
    monkeypatch.setattr(titles, '_fit_caption', lambda *a: pytest.fail('Pillow scene geometry'))
    findings = check.text_overflow({}, project.frame, ctx)
    assert len(findings) == 1 and findings[0].code == 'text_overflow'


def test_schema_defaults_and_legacy_round_trip(project):
    old = project.to_dict()
    old['style'].pop('captions_engine', None)
    assert Project.from_dict(old).style.captions_engine == 'scene'
    project.style.captions_engine = 'pillow'
    assert Project.from_dict(project.to_dict()).style.captions_engine == 'pillow'


def test_check_scene_measurement_wiring(project, monkeypatch):
    project.style.format = 'essay'
    calls = []
    monkeypatch.setattr(stage, 'browser', lambda: 'mock-chromium')
    def measure(p, texts, *, render=True):
        if not render:
            return []
        calls.append(texts)
        return [dict(size=43.2, overflow=True) for _ in texts]
    monkeypatch.setattr(scenes, 'measure_captions', measure)
    monkeypatch.setattr(titles, '_fit_caption', lambda *a: pytest.fail('Pillow scene geometry'))
    result = check.run(project, measure=True)
    assert len(calls) == 1
    assert sum(f['code'] == 'text_overflow' for f in result['findings']) == len(calls[0])
    monkeypatch.setattr(stage, 'browser', lambda: None)
    assert not any(f['code'] == 'small_text' for f in check.run(project)['findings'])
    assert len(calls) == 1


def test_cdp_alpha_after_navigation_and_reset(tmp_path, monkeypatch):
    """Exercise capture transport with fake browser and server."""
    import base64
    import os
    calls, launches = [], []
    class CDP:
        def __init__(self, w, r):
            self.fds = (w, r)
        def send(self, method, params=None, session=None):
            calls.append((method, params))
            if method == 'Target.getTargets':
                return {'targetInfos': [{'type': 'page', 'targetId': 'target'}]}
            if method == 'Target.attachToTarget':
                return {'sessionId': 'session'}
            if method == 'Page.captureScreenshot':
                return {'data': base64.b64encode(b'png').decode()}
            if method == 'Runtime.evaluate' and 'const rows = []' in params['expression']:
                return {'result': {'value': [dict(id='caption', px=62, overflow=False)]}}
            return {}
        def clear_events(self):
            pass
        def wait_event(self, method):
            calls.append((method, None))
        def close(self):
            for fd in self.fds:
                os.close(fd)
    monkeypatch.setattr(stage, '_Cdp', CDP)
    monkeypatch.setattr(stage, 'browser', lambda: 'mock-chromium')
    def launch(*args, **kwargs):
        launches.append(args)
        return SimpleNamespace(terminate=lambda: None, wait=lambda **k: 0)
    monkeypatch.setattr(stage.subprocess, 'Popen', launch)
    monkeypatch.setattr(stage.http.server, 'ThreadingHTTPServer', lambda *a:
                        SimpleNamespace(server_address=('127.0.0.1', 1), serve_forever=lambda: None,
                                        shutdown=lambda: None, server_close=lambda: None))
    items = [dict(url_path='/static/test.html', W=1920, H=1080, size=(480, 270), alpha=alpha)
             for alpha in (True, False)]
    run = stage._run_cdp({'items': items}, lambda m: None)
    assert run.thumbs['snapshot'] == b'png'
    backgrounds = [params for method, params in calls if method == 'Emulation.setDefaultBackgroundColorOverride']
    assert backgrounds == [{'color': {'r': 0, 'g': 0, 'b': 0, 'a': 0}}, {}]
    loaded = next(i for i, c in enumerate(calls) if c[0] == 'Page.loadEventFired')
    alpha = next(i for i, c in enumerate(calls) if c[0] == 'Emulation.setDefaultBackgroundColorOverride')
    shot = next(i for i, c in enumerate(calls) if c[0] == 'Page.captureScreenshot')
    assert loaded < alpha < shot

    calls.clear()
    launches.clear()
    plates = [{**items[0], 'clip': f'phrase{i}', 't': 2.5} for i in range(3)]
    assert stage.capture_stills(plates, tmp_path) == {
        f'phrase{i}': b'png' for i in range(3)}
    assert len(launches) == 1
    assert sum(method == 'Page.captureScreenshot' for method, _ in calls) == 3
    assert sum(method == 'Page.navigate' for method, _ in calls) == 3

    calls.clear()
    launches.clear()
    measured = stage.measure_many(plates, tmp_path)
    assert len(measured) == 3 and measured['phrase0'][0]['px'] == 62
    assert len(launches) == 1
    assert not any(method == 'Page.captureScreenshot' for method, _ in calls)
    assert sum(method == 'Page.navigate' for method, _ in calls) == 3


def test_long_caption_segment_partitions_builder_screens(project):
    from html.parser import HTMLParser
    class Screens(HTMLParser):
        def handle_starttag(self, tag, attrs):
            row = dict(attrs)
            if 'data-screen' in row:
                screens.append((float(row['data-start']), float(row['data-duration'])))
    ctx = scenes.context_base(project)
    ctx.update(duration=130, phrases=[dict(text=f'Phrase {i}', t0=i*2+.1, t1=i*2+1.9)
                                    for i in range(65)])
    screens = []
    html = scenes.render_html('essay/captions.html', ctx)
    Screens().feed(html)
    assert screens == [(0, 64.1), (64.1, 64), (128.1, pytest.approx(1.9))]
    assert html.count('data-layer=') == 65

"""Text geometry uses mocked CDP; no browser, rendering or model calls."""
import pytest

from app import check, scenes, stage


def test_stage_measure_parses_cdp(tmp_path, monkeypatch):
    page = tmp_path / 'scene.html'
    page.write_text('scene')
    rows = [dict(id='line', x=10, y=20, width=500, height=40,
                 px=32, overflow=True, start=2, t=2.45)]
    calls = []

    class CDP:
        def send(self, method, params, session):
            calls.append(params)
            assert method == 'Runtime.evaluate'
            assert params['returnByValue'] is True
            assert params['awaitPromise'] is True
            expression = params['expression']
            assert 'await window.__seek(t)' in expression
            assert 'start + arrive' in expression
            assert 'scrollWidth' in expression and 'getBoundingClientRect' in expression
            assert 'Math.max(0, start + arrive)' in expression
            return {'result': {'value': rows}}

    def run(job, progress, **kwargs):
        assert job['scene_root'] == str(tmp_path)
        item = job['items'][0]
        assert item['measure_only'] is True
        assert item['size'] == (480, 270)
        kwargs['scene_probe'](CDP(), 'session', item, item['t'])

    monkeypatch.setattr(stage, '_run_cdp', run)
    assert stage.measure(page, 1920, 1080, 0) == rows
    assert len(calls) == 1
    for t in [-1, float('nan'), float('inf')]:
        with pytest.raises(ValueError):
            stage.measure(page, 1920, 1080, t)


def test_cache_batches_deduplicates_and_invalidates(project, monkeypatch):
    ctx = scenes.context_base(project)
    ctx.update(phrases=[dict(text='First', t0=0, t1=5)], settled=True)
    other = dict(ctx, phrases=[dict(text='Second', t0=0, t1=5)])
    calls = []

    def measure(items, root, **roots):
        calls.append(items)
        return {i['clip']: [dict(id='caption-0', px=24, overflow=True)] for i in items}

    monkeypatch.setattr(stage, 'measure_many', measure)
    request = ('essay/captions.html', ctx, 0)
    requests = [request, ('essay/captions.html', other, 0), request]
    assert scenes.measure_many(project, requests, render=False) == [[], [], []]
    assert calls == []
    first = scenes.measure_many(project, requests)
    assert len(calls) == 1 and len(calls[0]) == 2
    assert first[0] == first[2]
    assert scenes.measure_many(project, requests, render=False) == first
    assert scenes.measure(project, *request) == first[0]
    assert len(calls) == 1
    scenes.measure(project, request[0], ctx, 1)
    assert len(calls) == 2 and len(calls[-1]) == 1
    monkeypatch.setattr(scenes, '_asset_hash', lambda: 'changed fonts/runtime')
    assert scenes.measure_many(project, [request], render=False) == [[]]


def test_board_rule_time_cache_and_default_never_launches(project, monkeypatch):
    project.style.format = 'board'
    project.slides[0].board_template = 'statement'
    project.slides[0].title = 'Extremelylongword' * 100
    calls = []

    def measure(items, root, **roots):
        calls.append(items)
        return {i['clip']: [dict(id='mark-0-0', px=20, overflow=True, start=.8)] for i in items}

    monkeypatch.setattr(stage, 'browser', lambda: 'mock-chromium')
    monkeypatch.setattr(stage, 'measure_many', measure)
    assert not any(f['code'] == 'text_overflow' for f in check.run(project)['findings'])
    assert calls == []
    before = project.to_dict()
    result = check.run(project, measure=True)
    assert len(calls) == 1 and len(calls[0]) > 1
    finding = next(f for f in result['findings'] if f['code'] == 'text_overflow')
    sb = check.storyboard.build(project)
    seg = next(s for s in sb['segments'] if s['type'] == 'picture')
    assert finding['slide_id'] == project.slides[0].id
    assert finding['t'] == pytest.approx(seg['start'] - seg['skip'] + .8, abs=.001)
    assert finding['level'] == 'P1'
    assert any(f['code'] == 'small_text' for f in result['findings'])
    assert check.run(project) == result
    assert check.run(project, measure=True) == result
    assert len(calls) == 1
    assert project.to_dict() == before


def test_custom_html_and_positioned_specs(project, monkeypatch):
    project.style.format = 'custom:missing-style'
    project.slides[0].custom_html = '<section class="cb-slide"><p>Text</p></section>'
    project.slides[1].custom = {'elements': [{'type': 'text', 'text': 'Hello'}]}
    calls = []

    def measure(items, root, **roots):
        calls.extend(items)
        return {i['clip']: [dict(id='element-0', px=40, overflow=True, start=0)] for i in items}

    monkeypatch.setattr(stage, 'browser', lambda: 'mock-chromium')
    monkeypatch.setattr(stage, 'measure_many', measure)
    result = check.run(project, measure=True)
    assert len(calls) >= 2
    assert any(f['slide_id'] == project.slides[0].id and f['code'] == 'text_overflow'
               for f in result['findings'])
    assert check.run(project) == result


def test_caption_misses_are_per_phrase_and_unavailable_is_safe(project, monkeypatch):
    project.style.format = 'essay'
    monkeypatch.setattr(stage, 'browser', lambda: None)
    assert not any(f['code'] in {'text_overflow', 'small_text'}
                   for f in check.run(project, measure=True)['findings'])
    calls = []

    def measure(items, root, **roots):
        calls.append(items)
        return {i['clip']: [dict(px=62, overflow=False)] for i in items}

    monkeypatch.setattr(stage, 'measure_many', measure)
    scenes.measure_captions(project, ['First', 'Second', 'First'])
    assert len(calls) == 1 and len(calls[0]) == 2
    scenes.measure_captions(project, ['Second', 'Changed', 'First'])
    assert len(calls) == 2 and len(calls[1]) == 1


def test_small_scene_text_is_one_finding_per_paragraph():
    from types import SimpleNamespace
    from app import check
    from app.schema import FrameSpec
    lines = [dict(type='scene', start=1.0, end=4, slide_id='s1', metrics={'px': px})
             for px in (40, 33, 36)] + [
             dict(type='scene', start=5.0, end=8, slide_id='s2', metrics={'px': 60})]
    found = check.small_text({}, FrameSpec(), SimpleNamespace(lines=lines))
    assert [(f.slide_id, f.t) for f in found] == [('s1', 1.0)]
    assert '33px (3 text elements)' in found[0].msg

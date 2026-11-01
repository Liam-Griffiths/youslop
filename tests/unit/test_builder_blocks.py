"""Block/card migration and authoring budgets with mocked layout and captures."""
import base64
from html.parser import HTMLParser
import io
import json
from pathlib import Path

from PIL import Image
import pytest

from app import block_authoring, blocks, cli, custom_scenes, scene_builder as builder, scenes, stage


class Layers(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.rows, self.depth, self.stack, self.budget = [], 0, [], .1
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'data-budget' in a:
            self.budget = float(a['data-budget'])
        if 'data-layer' in a:
            assert not any(self.stack), 'nested layer'
            self.rows.append(dict(id=a['data-layer'], index=len(self.rows), screen='',
                start=float(a.get('data-start', 0)), duration=float(a.get('data-duration', 5)),
                arrival=float(a.get('data-motion-duration', .6)),
                motion=a.get('data-motion', a.get('data-anim', 'none')), capture=a.get('data-capture'),
                atlas=int(a.get('data-atlas', 1)), pathKeys=json.loads(a.get('data-path', '[]')),
                exit=float(a.get('data-motion-exit', 0)), box=[0, 0, 80, 40], signature=[a]))
            self.rows[-1].update(native=a.get('data-media', ''),
                dim=float(a.get('data-media-dim', 1)),
                focal=json.loads(a.get('data-media-focal', '[0.5,0.5]')))
        if tag not in ('img', 'meta', 'link', 'br', 'input', 'source', 'hr'):
            self.stack.append('data-layer' in a)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


@pytest.fixture
def capture_mock(monkeypatch):
    active, shots = {}, []
    buf = io.BytesIO()
    Image.new('RGBA', (480, 480), '#FF5A1F').save(buf, 'PNG')
    png = base64.b64encode(buf.getvalue()).decode()

    class CDP:
        def send(self, method, params, session):
            assert method == 'Page.captureScreenshot'
            shots.append(method)
            return dict(data=png)

    def evaluate(cdp, session, expression):
        if expression == builder._PROBE:
            parsed = Layers(active['html'])
            return dict(result=dict(value=dict(layers=parsed.rows, screens=[], camera=[],
                        budget=parsed.budget, ground=['mock ground'])))
        return dict(result=dict(value=[] if expression.startswith('(() =>') else None))

    def capture(items, directory, **kw):
        active['html'] = (directory / Path(items[0]['url_path']).name).read_text()
        kw['scene_probe'](CDP(), 'mock', items[0], 0)

    def check_capture(job, progress, **kw):
        item = job['items'][0]
        kw['scene_probe'](CDP(), 'mock', item, item['t'])

    monkeypatch.setattr(stage, '_evaluate', evaluate)
    monkeypatch.setattr(stage, 'capture_stills', capture)
    monkeypatch.setattr(stage, '_run_cdp', check_capture)
    monkeypatch.setattr(builder.ffutil, 'run', lambda *a, **kw: pytest.fail('check encoded video'))
    return shots


@pytest.mark.parametrize('ref', sorted(p.parent.name for p in blocks.BUILTIN_DIR.glob('*/block.json')))
def test_builtin_checks_and_builder_stats(ref, capture_mock):
    reports = []
    meta = blocks.discover()[ref]['meta']
    assert block_authoring.check(ref, report=lambda a, s: reports.append((a, s))) == []
    assert {a for a, _ in reports} == set(meta['aspects'])
    for aspect, stats in reports:
        assert stats['captured_frames'] == 0
        assert 1 <= stats['layers'] <= 48 and stats['passes'] == 1
        # Native media is not screenshotted; warm manifests also count its files.
        if ref in blocks.core_explainer_blocks.IDS and ref != 'step_list':
            assert 1 <= stats['captures'] + stats['cache_hits'] <= stats['layers'] + 1
        else:
            assert stats['captures'] + stats['cache_hits'] == stats['layers'] + 1
        assert stats['largest_graph_bytes'] < 65536
    # This is a mocked geometry/contrast check; real layout needs Chromium review.


def test_check_budget_rejected_before_screenshots(tmp_path, monkeypatch, capture_mock, capsys):
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'blocks')
    root = block_authoring.new('window')
    meta = json.loads((root / 'block.json').read_text())
    meta['budget'] = 0
    (root / 'block.json').write_text(json.dumps(meta))
    (root / 'block.html').write_text(block_authoring.TEMPLATE.replace(
        'data-layer="copy"', 'data-layer="copy" data-capture="frames"'))
    assert cli.main(['block', 'check', 'user/window']) == 1
    assert 'copy: capture window exceeds frame budget' in capsys.readouterr().err
    assert capture_mock == []
    meta['budget'] = 1
    (root / 'block.json').write_text(json.dumps(meta))
    assert cli.main(['block', 'check', 'user/window']) == 0
    output = capsys.readouterr().out
    assert '"captured_frames": 18' in output and '"passes": 1' in output
    assert 'Block checks passed' in output


@pytest.mark.parametrize('budget', [-.1, 1.1, True, '0.1', float('nan')])
def test_invalid_budget_metadata(tmp_path, monkeypatch, budget):
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'blocks')
    root = block_authoring.new('budget')
    meta = json.loads((root / 'block.json').read_text())
    meta['budget'] = budget
    (root / 'block.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='budget'):
        blocks.prepare('user/budget')


def test_html_layers_compile_and_static_fallback(tmp_path, capture_mock):
    fragment = '<section class="cb-slide"><h1 data-layer="title" data-start="0.2" data-duration="4" data-motion="words">A whole line</h1></section>'
    ctx = custom_scenes.html_context(tmp_path, fragment, seconds=5)
    stats = builder.inspect(tmp_path, 'slides/custom.html', ctx, seconds=5, size=(480,270), fps=30)
    assert stats['layers'] == 1 and stats['captures'] == 2 and stats['captured_frames'] == 0
    html = scenes.render_html('slides/custom.html', ctx)
    assert 'data-layer="html"' not in html
    ctx = custom_scenes.html_context(tmp_path, '<h1>Static</h1>', seconds=5)
    assert 'data-layer="html"' in scenes.render_html('slides/custom.html', ctx)


def test_sponsor_block_beats_and_standalone_timeline():
    ctx = scenes.context_base()
    ctx.update(beats=dict(made=.5, brand=2, learn=3, link=4), logo='/static/brand/corkbored-icon.svg')
    template, ctx = blocks.prepare('sponsor_house_read', seconds=8, context=ctx)
    html = scenes.render_html(template, ctx)
    rows = {r['id']: r for r in Layers(html).rows}
    assert rows['brand']['start'] == pytest.approx(1.95)
    assert rows['learn']['start'] == 3 and rows['link']['start'] == pytest.approx(3.9)
    assert 'sponsor-house-short' not in html and 'id="paper"' not in html
    standalone = scenes.render_html('sponsor/house_short.html', ctx)
    assert 'sponsor-house-short' in standalone and not Layers(standalone).rows


@pytest.mark.parametrize('ref', blocks.core_data_blocks.IDS)
@pytest.mark.parametrize('aspect', ['16:9', '9:16'])
def test_data_blocks_maximum_datasets_compile(ref, aspect, capture_mock, tmp_path):
    meta = blocks.discover()[ref]['meta']
    values = block_authoring.samples(meta)
    if 'rows' in values:
        count = {'stat_comparison': 2, 'line_chart': 8, 'bar_race': 5,
                 'date_timeline': 5}.get(ref, 6)
        values['rows'] = [dict(label='W'*(47 if ref == 'date_timeline' else 17)+str(i), **(
            dict(date='W'*12) if ref == 'date_timeline' else
            dict(first=i*100, middle=(count-i)*100, last=i*200) if ref == 'bar_race' else
            dict(value='W'*18) if ref == 'simple_table' else dict(value=999999)))
            for i in range(count)]
    else:
        values['value'] = 100 if ref == 'percentage_ring' else -999999
    template, ctx = blocks.prepare(ref, values, aspect, seconds=3)
    stats = builder.inspect(tmp_path, template, ctx, seconds=3,
                            size=(ctx['width']//4, ctx['height']//4), fps=30)
    assert stats['captured_frames'] == 0 and stats['passes'] == 1
    assert stats['layers'] <= 7 and stats['largest_graph_bytes'] < 65536
    parsed = Layers(scenes.render_html(template, ctx))
    if ref in ('number_slam', 'percentage_ring', 'bar_race'):
        assert all(r['motion'] == 'atlas' for r in parsed.rows)
        assert all(1 < r['atlas'] <= 17 for r in parsed.rows)
    if ref == 'bar_race':
        assert len(parsed.rows) == 6
        assert all(len(r['pathKeys']) == 5 for r in parsed.rows[1:])


@pytest.mark.parametrize('ref', blocks.core_explainer_blocks.IDS)
@pytest.mark.parametrize('aspect', ['16:9', '9:16'])
def test_explainer_maximum_inputs_compile(ref, aspect, capture_mock, tmp_path):
    meta = blocks.discover()[ref]['meta']
    values = block_authoring.samples(meta)
    if ref == 'step_list':
        values['rows'] = [dict(label='W'*48)]*5
    elif ref == 'labelled_diagram':
        values['rows'] = [dict(label='W'*32,x=i/2,y=i/2) for i in range(3)]
    template, ctx = blocks.prepare(ref, values, aspect, seconds=3)
    html = scenes.render_html(template, ctx)
    parsed = Layers(html)
    rows = parsed.rows
    stats = builder.inspect(tmp_path, template, ctx, seconds=3,
                            size=(ctx['width']//4,ctx['height']//4), fps=30)
    assert stats['captured_frames'] == 0 and stats['passes'] == 1
    assert stats['layers'] <= 5 and stats['largest_graph_bytes'] < 65536
    native = [r for r in rows if r['native']]
    assert len(native) == (0 if ref == 'step_list' else 2 if ref in ('before_after_wipe','split_comparison') else 1)
    # Every native still bypasses screenshot capture entirely.
    assert stats['captures'] == 1+len(rows)-len(native)
    assert len(capture_mock) <= stats['captures']
    if ref == 'before_after_wipe':
        assert native[1]['motion'] == 'wipe'
        assert native[1]['start'] == .75 and native[1]['arrival'] == .75
    if ref in ('document_highlight', 'callout_arrow', 'map_highlight', 'labelled_diagram'):
        assert 'class="annotation"' in html
        assert next(r for r in rows if r['id'] == 'annotation')['motion'] in ('wipe', 'reveal')

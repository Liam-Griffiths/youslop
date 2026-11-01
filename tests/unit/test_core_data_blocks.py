"""Data honesty, bounded inputs, local assets and channel inheritance."""
import pytest
from app import blocks, core_data_blocks, paths, scenes


@pytest.mark.parametrize('ref', core_data_blocks.IDS)
def test_data_contracts(ref):
    meta = blocks.discover()[ref]['meta']
    assert set(meta['aspects']) == {'16:9', '9:16'} and meta['budget'] == 0
    assert all((paths.resource_root()/'resources'/url.lstrip('/')).is_file() for url in meta['fonts'])
    channel = scenes.context_base()
    channel['vars'].update(bg='#F4EAD8', ink='#2E241C', accent='#D9482B')
    for aspect in meta['aspects']:
        template, ctx = blocks.prepare(ref, aspect=aspect, context=channel)
        assert all(ctx['vars'][k] == channel['vars'][k] for k in ('bg', 'ink', 'accent'))
        assert ctx['palette']['ground'] == channel['vars']['bg']
        html = scenes.render_html(template, ctx)
        assert not scenes.lint(html, asset_root=ctx['block_assets_root'])
        assert 'data-capture="frames"' not in html


@pytest.mark.parametrize('ref', ['stat_comparison', 'line_chart', 'bar_chart', 'bar_race'])
def test_zero_series_and_common_scale(ref):
    rows = [dict(label='A', value=0, first=0, middle=0, last=0),
            dict(label='B', value=0, first=0, middle=0, last=0)]
    template, ctx = blocks.prepare(ref, dict(rows=rows))
    assert ctx['data']['maximum'] == 1 and ctx['data']['scale'].startswith('0 — 1')
    assert not scenes.lint(scenes.render_html(template, ctx), asset_root=ctx['block_assets_root'])
    rows[1].update(value=100, first=100, middle=50, last=25)
    _, ctx = blocks.prepare(ref, dict(rows=rows))
    assert ctx['data']['maximum'] == 100


@pytest.mark.parametrize('ref,values,match', [
    ('bar_chart', dict(rows=[]), 'rows'),
    ('line_chart', dict(rows=[dict(label='A', value=1)]), 'rows'),
    ('simple_table', dict(rows=[dict(label='A', value=True)]), 'value'),
    ('date_timeline', dict(rows=[dict(date='x'*13, label='A')]*2), 'date'),
    ('bar_chart', dict(rows=[dict(label='x'*19, value=1)]), 'label'),
    ('bar_chart', dict(rows=[dict(label='A', value=-1)]), 'value'),
    ('bar_chart', dict(rows=[dict(label='A', value='3')]), 'value'),
    ('bar_chart', dict(rows=[dict(label='A', value=True)]), 'value'),
    ('bar_chart', dict(rows=[dict(label='A', value=1000000)]), 'value'),
    ('bar_chart', dict(rows=[dict(label='A', value=float('nan'))]), 'scalar'),
    ('bar_race', dict(rows=[dict(label='A', first=1, middle=2, last=3)]*2), 'unique'),
    ('percentage_ring', dict(value=101), 'maximum'),
])
def test_bad_data_fails_before_builder(ref, values, match, monkeypatch):
    monkeypatch.setattr(blocks.scene_builder, 'render', lambda *a, **k: pytest.fail('capture invoked'))
    with pytest.raises(ValueError, match=match):
        blocks.render(ref, values)


def test_atlas_endpoints_ranks_and_escaping():
    for n in (-999999, 0, 999999):
        _, ctx = blocks.prepare('number_slam', dict(value=n, decimals='2'))
        assert ctx['data']['frames'][0] == '0.00'
        assert ctx['data']['frames'][-1] == f'{n:,.2f}'
    for n in (0, 100):
        _, ctx = blocks.prepare('percentage_ring', dict(value=n))
        assert ctx['data']['frames'][0] == 0 and ctx['data']['frames'][-1] == n
    _, ctx = blocks.prepare('bar_race')
    rail, bus, cycle = ctx['data']['rows']
    assert rail['y'] > bus['y'] and rail['y'] < cycle['y']
    assert rail['y']+rail['path'][-1]['y'] < cycle['y']+cycle['path'][-1]['y'] < bus['y']+bus['path'][-1]['y']
    template, ctx = blocks.prepare('simple_table', dict(rows=[dict(label='<b>x</b>', value='<script>')]))
    html = scenes.render_html(template, ctx)
    assert '&lt;b&gt;x&lt;/b&gt;' in html and '&lt;script&gt;' in html

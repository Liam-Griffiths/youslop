"""Explainers: local media, honest coordinates, safe slots and bounded graphs."""
from pathlib import Path
import pytest

from app import blocks, core_explainer_blocks as explainers, paths, scenes


@pytest.mark.parametrize('ref', explainers.IDS)
@pytest.mark.parametrize('aspect', ['16:9', '9:16'])
def test_explainer_contract_and_safe_slots(ref, aspect):
    meta = blocks.discover()[ref]['meta']
    assert set(meta['aspects']) == {'16:9', '9:16'} and meta['budget'] == 0
    for font in meta['fonts']:
        assert (paths.resource_root()/'resources'/font.lstrip('/')).is_file()
    channel = scenes.context_base()
    channel['vars'].update(bg='#F4EAD8', ink='#2E241C', accent='#D9482B')
    template, ctx = blocks.prepare(ref, aspect=aspect, context=channel)
    assert all(ctx['vars'][k] == channel['vars'][k] for k in ('bg', 'ink', 'accent'))
    html = scenes.render_html(template, ctx)
    assert not scenes.lint(html, asset_root=ctx['block_assets_root'])
    assert 'data-capture="frames"' not in html
    assert 'font:44px/62px' in html and 'scrollHeight <= el.clientHeight' in html
    d = ctx['explain']
    assert d['x'] >= ctx['width']*.1 and d['x']+d['w'] <= ctx['width']*(.85 if aspect == '9:16' else .9)
    assert d['header'] >= ctx['height']*(.15 if aspect == '9:16' else .1)
    assert d['bottom'] < d['footer'] and d['footer']+84 <= ctx['height']*(.8 if aspect == '9:16' else .9)
    if ref == 'step_list':
        _, maximum = blocks.prepare(ref, dict(rows=[dict(label='W'*48)]*5), aspect)
        assert maximum['explain']['gap']-38 >= 62
    else:
        assert Path(d['picture']).is_file() and 'data-media=' in html
        if ref == 'labelled_diagram':
            assert d['label_x']+d['label_w'] <= d['x']+d['w']
            assert d['label_y']+2*d['label_gap']+88 <= d['bottom']
        if ref == 'split_comparison':
            a, b = d['panels']
            assert a['x']+a['w'] < b['x'] or a['y']+a['h'] < b['y']
            assert b['x']+b['w'] <= d['x']+d['w'] and b['y']+b['h'] <= d['bottom']


@pytest.mark.parametrize('ref,values,match', [
    ('step_list', dict(rows=[]), 'rows'),
    ('step_list', dict(rows=[dict(label='x')]*6), 'rows'),
    ('step_list', dict(rows=[dict(label='x'*49)]*2), 'label'),
    ('labelled_diagram', dict(rows=[dict(label='x', x=True, y=.5)]), 'x'),
    ('labelled_diagram', dict(rows=[dict(label='x', x=-.1, y=.5)]), 'x'),
    ('labelled_diagram', dict(rows=[dict(label='x', x=.5)]), 'y'),
    ('labelled_diagram', dict(rows=[dict(label='x', x=.5, y=2)]), 'y'),
    ('document_highlight', dict(x=.9, w=.2), 'region'),
    ('document_highlight', dict(h=0), 'region'),
    ('map_highlight', dict(mode='region', y=.9, h=.2), 'region'),
    ('callout_arrow', dict(x=.2,y=.3,from_x=.2,from_y=.3), 'arrow'),
    ('map_highlight', dict(picture='https://example.com/map.png'), 'local'),
    ('callout_arrow', dict(picture=''), 'local'),
    ('split_comparison', dict(after='/static/missing.png'), 'missing'),
])
def test_bad_inputs_fail_before_builder(ref, values, match, monkeypatch):
    monkeypatch.setattr(blocks.scene_builder, 'render', lambda *a, **k: pytest.fail('builder invoked'))
    with pytest.raises(ValueError, match=match):
        blocks.render(ref, values)


def test_local_asset_roots_and_no_traversal(tmp_path):
    (tmp_path/'map.png').write_bytes(b'local placeholder')
    ctx = dict(block_assets_root=str(tmp_path), asset_roots=dict(project_root=str(tmp_path)))
    for kind in ('assets', 'project'):
        assert explainers.media_path(f'/scene/{{token}}/{kind}/map.png', ctx) == str(tmp_path/'map.png')
    for url in ('/scene/{token}/channel/map.png', '/scene/{token}/assets/%2e%2e/map.png',
                '/static/../README.md', '/scene/{token}/assets/'):
        with pytest.raises(ValueError):
            explainers.media_path(url, ctx)
    (tmp_path/'escape').symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        explainers.media_path('/scene/{token}/assets/escape/map.png', ctx)


def test_map_modes_arrow_direction_and_escaping(monkeypatch):
    # A map block never invokes the network-backed generator.
    from app import maps
    monkeypatch.setattr(maps, '_fetch_raw', lambda *a, **k: pytest.fail('map fetch'))
    for mode in ('pin', 'region'):
        template, ctx = blocks.prepare('map_highlight', dict(mode=mode, label='<script>'))
        html = scenes.render_html(template, ctx)
        assert '&lt;script&gt;' in html
        assert ('<rect ' in html) == (mode == 'region')
    _, ctx = blocks.prepare('callout_arrow', dict(x=.2, y=.8, from_x=.2, from_y=.2))
    assert ctx['explain']['angle'] == pytest.approx(90)
    template, ctx = blocks.prepare('labelled_diagram', dict(rows=[dict(label='<b>x</b>',x=0,y=1)]))
    assert '&lt;b&gt;x&lt;/b&gt;' in scenes.render_html(template, ctx)

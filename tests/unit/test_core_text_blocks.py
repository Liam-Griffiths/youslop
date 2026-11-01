"""Batch 1 contracts: worst-case copy, channel colours and existing chapter API."""
import pytest
from app import block_authoring, blocks, scenes, stage

IDS = ('lower_third_rule', 'lower_third_panel', 'lower_third_stack', 'title_card',
       'chapter', 'quote_card', 'pull_quote_picture', 'kicker_headline', 'end_card',
       'kinetic_caption_rise', 'kinetic_caption_words', 'kinetic_caption_slam')


@pytest.mark.parametrize('ref', IDS)
def test_text_blocks_static_and_channel_context(ref, monkeypatch):
    monkeypatch.setattr(stage, '_run_cdp', lambda *a, **k: pytest.fail('browser invoked'))
    block = blocks.discover()[ref]
    meta = block['meta']
    assert set(meta['aspects']) == {'16:9', '9:16'}
    assert block_authoring.check(ref, static_only=True) == []
    for aspect, size in [('16:9', (1920, 1080)), ('9:16', (1080, 1920))]:
        _, defaults = blocks.prepare(ref, aspect=aspect)
        assert defaults['vars']['accent'] == '#FF5A1F'
        assert (defaults['width'], defaults['height']) == size
        channel = scenes.context_base()
        channel['vars'].update(bg='#F4EAD8', ink='#2E241C', accent='#D9482B', panel='#FFFFFF')
        _, inherited = blocks.prepare(ref, aspect=aspect, context=channel)
        assert {k: inherited['vars'][k] for k in ('bg', 'ink', 'accent', 'panel')} == {
            k: channel['vars'][k] for k in ('bg', 'ink', 'accent', 'panel')}
    # Limits and font URLs are metadata contracts; check the actual local files.
    from app import paths
    assert all((paths.resource_root() / 'resources' / url.lstrip('/')).is_file()
               for url in meta['fonts'])


def test_chapter_legacy_limits_and_safe_escaping():
    template, ctx = blocks.prepare('chapter', dict(title='W'*240, kicker='W'*120,
        channel_name='W'*120, tagline='W'*240), aspect='9:16', seconds=.1)
    assert scenes.lint(scenes.render_html(template, ctx), asset_root=ctx['block_assets_root']) == []
    template, ctx = blocks.prepare('pull_quote_picture', dict(title='<script>alert(1)</script>',
        picture='/static/local-still.png'))
    html = scenes.render_html(template, ctx)
    assert '&lt;script&gt;' in html and 'src="/static/local-still.png"' in html

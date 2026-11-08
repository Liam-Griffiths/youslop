"""Opt-in single quarter-size title-card capture; no movie render."""
import io
import os

from PIL import Image
import pytest

from app import blocks, channels, scene_builder, scenes, stage
from app.schema import Channel

pytestmark = pytest.mark.skipif(os.environ.get('YS_VISUAL') != '1', reason='set YS_VISUAL=1')


def test_themed_title_card(project, tmp_path, monkeypatch):
    channel = Channel(id='theme', name='Theme')
    channel.style.block_theme = dict(accent='#3DFFDC', font_display='EB Garamond', radius=12, pace=1.3)
    project.channel_id = channel.id
    project.style.block_theme = dict(accent='#FF3366')
    monkeypatch.setattr(channels, 'load_or_none', lambda _: channel)
    template, ctx = blocks.prepare('title_card', dict(title='A new perspective'),
                                  context=scenes.context_base(project))
    html = tmp_path / 'title.html'
    html.write_text(scenes.render_html(template, ctx))
    def probe(cdp, session, item, t):
        face = stage._evaluate(cdp, session, 'getComputedStyle(document.querySelector("h1")).fontFamily')
        assert 'EB Garamond' in face['result']['value']
        assert stage._evaluate(cdp, session, 'document.fonts.check(\'96px "EB Garamond"\')')['result']['value']
        layers = stage._evaluate(cdp, session, scene_builder._PROBE)['result']['value']['layers']
        assert layers[0]['arrival'] == pytest.approx(.45 * 1.3)
    png = stage.capture_one(html, 1920, 1080, 1.5, (480,270),
                            assets_root=ctx['block_assets_root'], scene_probe=probe)
    image = Image.open(io.BytesIO(png)).convert('RGB')
    # The horizontal accent border is at 18% height, 12%..88% width.
    # At quarter size the 6 px rule is 1.5 px tall, so take the closest row.
    best = min(max(abs(a-b) for a, b in zip(image.getpixel((100,y)), (255,51,102)))
               for y in range(44, 55))
    assert best <= 20


def test_preview_as_channel_rule_pixels(tmp_path, monkeypatch):
    """The same on-demand endpoint used by visible Blocks cards, one still."""
    from app import block_library, paths
    monkeypatch.setattr(paths, 'data_root', lambda: tmp_path)
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.delenv('CORKBORED_BLOCK_POSTERS', raising=False)
    channel = Channel(id='preview-as', name='Preview as')
    channel.style.block_theme = {'accent': '#3DFFDC'}
    channels.save(channel)
    result = block_library.theme_sheet(dict(scope='channel', id=channel.id,
        ref='title_card', aspect='16:9', session='preview-as-pixels', sequence=0))
    key = result['posters'][0]['url'].split('/')[-2]
    image = Image.open(block_library.preview_file(key, 'trial')).convert('RGB')
    assert image.size == (480, 270)
    best = min(max(abs(a-b) for a,b in zip(image.getpixel((100,y)), (61,255,220)))
               for y in range(44,55))
    assert best <= 20

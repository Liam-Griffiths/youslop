"""Local picture contracts; browser fit/contrast remains a separate acceptance check."""
import json
from pathlib import Path

from PIL import Image
import pytest

from app import block_authoring, block_library, blocks, scenes

IDS = ('photo_stack', 'filmstrip', 'polaroid_pair', 'viewfinder',
       'archive_frame', 'triptych', 'zoom_detail', 'caption_strip')
LIGHT = dict(bg='#F5F5F5', ink='#151515', panel='#FFFFFF', line='#CCCCCC',
             dim='#454545', accent='#993300', accent2='#335588', pace=1.4, radius=12)


@pytest.mark.parametrize('ref', IDS)
def test_picture_metadata_tokens_and_local_samples(ref):
    item = blocks.discover()[ref]
    meta = item['meta']
    assert meta['default_colors'] == blocks.discover()['title_card']['meta']['default_colors']
    assert meta['budget'] == 0
    assert block_authoring.check(ref, static_only=True) == []
    assert block_authoring.check(ref, static_only=True, theme=LIGHT) == []
    assert not block_authoring.token_lint((item['root']/'block.html').read_text())
    for asset in meta['assets']:
        with Image.open(item['root']/asset) as im:
            assert im.size == (960,640)
    for key, spec in meta['variables'].items():
        if spec['type'] == 'image':
            assert Path(spec['default'].removeprefix('/')).is_file()
    assert not block_authoring.token_lint(Path('static/blocks/photo_stack/pictures_base.html').read_text())


@pytest.mark.parametrize('ref,key,bad', [
    ('photo_stack','count','5'), ('filmstrip','count','2'),
    ('zoom_detail','focal_x',-0.01), ('zoom_detail','focal_y',1.01),
    ('zoom_detail','picture','https://example.com/image.png'),
    ('caption_strip','caption','W'*65),
])
def test_invalid_picture_inputs_fail_before_capture(ref,key,bad):
    with pytest.raises(ValueError):
        blocks.prepare(ref,{key:bad})


def test_authored_copy_is_escaped_and_timecode_stays_static():
    template, ctx = blocks.prepare('viewfinder',dict(label='<REC>',timecode='12:34:56:00'),overlay=True)
    html = scenes.render_html(template,ctx)
    assert '&lt;REC&gt;' in html and '12:34:56:00' in html
    assert 'setInterval(' not in html and 'data-capture="frames"' not in html
    template, ctx = blocks.prepare('zoom_detail',dict(focal_x=0,focal_y=1))
    html = scenes.render_html(template,ctx)
    assert ctx['vars']['focal_x'] == 0 and ctx['vars']['focal_y'] == 1
    assert 'await image.decode()' in html and 'image.naturalWidth*scale*2' in html


def test_shared_picture_base_invalidates_posters(monkeypatch,tmp_path):
    item = blocks.discover()['triptych']
    before = block_library.signature(item)
    shared = tmp_path/'photo_stack'
    shared.mkdir()
    (shared/'pictures_base.html').write_text('changed shared template')
    monkeypatch.setattr(blocks,'BUILTIN_DIR',tmp_path)
    # Preserve the built-in classification while redirecting only shared files.
    altered = dict(item,root=tmp_path/'triptych')
    altered['root'].mkdir()
    (altered['root']/'block.json').write_text(json.dumps(item['meta']))
    first = block_library.signature(altered)
    (shared/'pictures_base.html').write_text('another shared template')
    assert block_library.signature(altered) != first
    assert before

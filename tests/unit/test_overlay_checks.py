"""Overlay checks read Pillow frames and cached geometry; no render/browser/model."""
from copy import deepcopy
import socket
from types import SimpleNamespace

from PIL import Image
import pytest

from app import block_library, check, ffutil, llm, overlay_checks as oc, render, scenes, stage, storyboard
from app.overlay_checks import _geometry as cached_geometry


@pytest.fixture
def setup(project, monkeypatch, tmp_path):
    def forbidden(*a, **kw):
        pytest.fail('Overlay check attempted render, browser, probe or model work')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    # Timeline proxy signatures consult the separately cached browse registry.
    monkeypatch.setattr(block_library, '_REGISTRY', (None, {}))
    for module, names in ((ffutil, ('run', 'duration', 'dimensions')),
                          (llm, ('complete_json',)), (stage, ('browser', 'measure_many')),
                          (render, ('_render_segment',))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    # Add a transparent authored block alongside the opaque built-ins.
    library = deepcopy(oc.blocks.discover())
    block = deepcopy(library['lower_third_panel'])
    block['meta']['id'] = 'transparent_test'
    block['meta']['overlay'].pop('panel', None)  # Transparent: no opaque panel.
    library['transparent_test'] = block
    monkeypatch.setattr(oc.blocks, 'discover', lambda: library)
    monkeypatch.setattr(oc, '_geometry', lambda *a: [(.15, .65, .65, .85)])
    image = tmp_path/'frame.png'
    Image.new('RGB', (480, 270), 'white').save(image)
    slide = project.slides[0]
    slide.candidates = [dict(id='base', local_path=str(image), kind='image')]
    slide.chosen_id = 'base'
    slide.take = dict(duration=8, words=[dict(w='Hello', start=2, end=2.5, src='est')])
    slide.overlays = [dict(id='o1', block_id='transparent_test', vars={},
                           at=1., dur=3., position='bottom_left', on='Hello')]
    # Use the same resolved colour source as the renderer, controlled here to
    # isolate white-on-white from the fixture project's theme.
    context_base = scenes.context_base
    monkeypatch.setattr(scenes, 'context_base', lambda *a, **kw:
                        {**context_base(*a, **kw), 'vars': dict(ink='#FFFFFF', bg='#000000')})
    return project, slide, image


def findings(project):
    sb = storyboard.build(project)
    sb['layers'] = render._layers(project, sb['segments'])
    return oc.run(project, sb)


def codes(project):
    return {f.code for f in findings(project)}


def test_white_dark_panel_missing_and_anchor(setup):
    project, slide, image = setup
    before = deepcopy(slide.overlays)
    result = findings(project)
    assert 'overlay_contrast' in {f.code for f in result}
    anchor = next(f for f in result if f.code == 'overlay_anchor_estimated')
    assert anchor.level == 'P2' and anchor.t == pytest.approx(2.6)
    assert anchor.fix['overlay_id'] == 'o1'
    Image.new('RGB', (480, 270), 'black').save(image)
    assert 'overlay_contrast' not in codes(project)
    Image.new('RGB', (480, 270), 'white').save(image)
    slide.overlays[0]['block_id'] = 'lower_third_panel'
    assert 'overlay_contrast' not in codes(project)
    image.unlink()
    # A panel block's contrast is ink on its own panel: no base frame needed.
    assert not {'overlay_contrast', 'overlay_contrast_unmeasured'} & set(codes(project))
    slide.overlays[0]['block_id'] = 'transparent_test'
    result = findings(project)
    assert next(f for f in result if f.code == 'overlay_contrast_unmeasured').level == 'P2'
    assert not any(f.code == 'overlay_contrast' for f in result)
    assert slide.overlays == before  # Resolution never writes the anchored time.


def test_spatial_and_temporal_title_caption_overlap(setup, monkeypatch):
    project, slide, _ = setup
    slide.title = 'A title'
    slide.title_hold = 6
    assert 'overlay_overlap' in codes(project)
    monkeypatch.setattr(oc, '_geometry', lambda *a: [(.15, .2, .65, .35)])
    assert 'overlay_overlap' not in codes(project)
    monkeypatch.setattr(oc, '_geometry', lambda *a: [(.15, .65, .65, .85)])
    sb = storyboard.build(project)
    sb['layers'] = render._layers(project, sb['segments'])
    sb['layers']['titles'] = []
    graphic = sb['layers']['graphics'][0]
    sb['layers']['captions'] = [dict(text='Caption', t0=graphic['t1'], t1=100)]
    assert not any(f.code == 'overlay_overlap' for f in oc.run(project, sb))
    sb['layers']['captions'][0]['t0'] = graphic['t0']
    assert any(f.code == 'overlay_overlap' for f in oc.run(project, sb))


@pytest.mark.parametrize('aspect,box,unsafe', [
    ('landscape', (.15, .2, .7, .8), False),
    ('landscape', (.01, .2, .7, .8), True),
    ('portrait', (.15, .2, .84, .79), False),
    ('portrait', (.15, .2, .86, .79), True),
    ('portrait', (.15, .12, .84, .79), True),
    ('portrait', (.15, .2, .84, .81), True),
])
def test_safe_areas(setup, monkeypatch, aspect, box, unsafe):
    project, _, _ = setup
    project.aspect = aspect
    monkeypatch.setattr(oc, '_geometry', lambda *a: [box])
    assert ('overlay_safe_area' in codes(project)) == unsafe


def test_missing_geometry_and_precise_anchor(setup, monkeypatch):
    project, slide, _ = setup
    monkeypatch.setattr(oc, '_geometry', lambda *a: [])
    slide.overlays[0]['position'] = 'top_right'
    slide.title = 'A title'
    slide.take['words'][0]['src'] = 'tts'
    result = findings(project)
    # No per-graphic note for missing bounds; the position region stands in.
    assert not any(f.code == 'overlay_geometry' for f in result)
    assert not {'overlay_safe_area', 'overlay_overlap', 'overlay_anchor_estimated'} & {f.code for f in result}


def test_held_picture_and_screen_length(setup, monkeypatch):
    project, slide, _ = setup
    held = project.slides[1]
    held.picture_mode = 'hold'
    slide.overlays = []
    held.overlays = [dict(id='held', block_id='transparent_test', vars={}, at=1, dur=3)]
    held.take = dict(duration=2)
    seen = []
    def frame(owner, lead, seconds, size, cache):
        seen.append((lead.id, seconds))
        return None
    monkeypatch.setattr(oc, '_base_frame', frame)
    sb = storyboard.build(project)
    sb['layers'] = render._layers(project, sb['segments'])
    oc.run(project, sb)
    seg = next(s for s in sb['segments'] if any(q['id'] == held.id for q in s.get('paragraphs', [])))
    span = next(r for r in sb['layers']['graphics'] if r['id'] == 'held')
    assert seen == [(slide.id, pytest.approx((span['t0']+span['t1'])/2-seg['paragraphs'][0]['start']))]
    assert span['t1']-span['t0'] > 1  # Includes the paragraph gap beyond its take.


def test_local_frame_crop_and_cache(setup):
    project, slide, image = setup
    im = Image.new('RGB', (200, 100), 'black')
    im.paste('white', (100, 0, 200, 100))
    im.save(image)
    candidate = slide.candidates[0]
    candidate['focal'] = [1, .5]
    cache = {}
    right = oc._base_frame(project, slide, 1, (50, 50), cache)
    assert right.getpixel((25, 25)) == (255, 255, 255)
    assert oc._base_frame(project, slide, 1, (50, 50), cache) is right
    candidate['focal'] = [0, .5]
    assert oc._base_frame(project, slide, 1, (50, 50), cache).getpixel((25, 25)) == (0, 0, 0)
    candidate.update(local_path='composited.mp4', thumb='https://example.invalid/frame.jpg')
    assert oc._base_frame(project, slide, 1, (50, 50), {}) is None


def test_footage_range_thumbs(setup, monkeypatch):
    from app import footage
    project, slide, image = setup
    clip = SimpleNamespace(id='clip', file='file', in_s=0, out_s=12, thumbs=['a', 'b', 'c'])
    source = SimpleNamespace(id='file', duration=15, width=480, height=270)
    shoot = SimpleNamespace(id='shoot', clips=[clip], files=[source])
    monkeypatch.setattr(footage, 'load', lambda *a: shoot)
    seen = []
    monkeypatch.setattr(footage, 'media_path', lambda sid, kind, name: seen.append(name) or image)
    slide.candidates[0].update(provider='footage', shoot_id='shoot', clip_id='clip', in_s=5, out_s=9)
    assert oc._base_frame(project, slide, 1, (480, 270), {}) is not None
    assert seen == ['b']  # Nearest permitted sample at 6s, not the first thumb.
    slide.candidates[0].update(in_s=7, out_s=9)
    assert oc._base_frame(project, slide, 1, (480, 270), {}) is None


def test_cached_geometry_only_and_check_integration(setup, monkeypatch):
    project, slide, _ = setup
    # Exercise real preparation and measurement-cache lookup without a browser.
    slide.overlays[0]['block_id'] = 'lower_third_panel'
    seen = []
    def cached(owner, requests, *, render):
        seen.append(render)
        return [[dict(x=192, y=648, width=384, height=108)]]
    monkeypatch.setattr(scenes, 'measure_many', cached)
    result = cached_geometry(project, slide.overlays[0], oc.blocks.discover()['lower_third_panel'],
                             scenes.context_base(project))
    assert result == [(.1, .6, .3, .7)] and seen == [False]
    monkeypatch.setattr(oc, '_geometry', lambda *a: result)
    before = project.to_dict()
    result = check.run(project)
    assert any(f['code'] == 'overlay_anchor_estimated' for f in result['findings'])
    assert project.to_dict() == before


def test_new_lower_thirds_declare_their_panel():
    """Contrast is measured on the panel for every overlay that declares one."""
    library = oc.blocks.discover()
    for ref in ('lower_third_kicker', 'lower_third_underline', 'lower_third_pill',
                'lower_third_reveal', 'lower_third_portrait', 'lower_third_panel'):
        assert library[ref]['meta']['overlay'].get('panel') is True, ref

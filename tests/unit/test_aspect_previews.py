"""Aspect dispatch and graph regressions without rendering or opening browsers."""
from pathlib import Path

import pytest
from PIL import Image

from app import block_overlays, blocks, check, render, scene_builder, thumbs, titles


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
def test_proxy_geometry_and_roundtrip_key(project, monkeypatch, aspect):
    groups = render._groups_for_preview(project)
    original = render._proxy_key(project, groups, 0, None)
    project.aspect = aspect
    shaped = render._proxy_key(project, groups, 0, None)
    assert shaped != original
    seen = []
    def draw(*args, **kw):
        seen.append(kw['size'])
        args[4].write_bytes(b'proxy')
    monkeypatch.setattr(render, '_render_segment', draw)
    monkeypatch.setattr(render.audio_mod, 'build_slice', lambda *a: (_ for _ in ()).throw(ValueError()))
    result = render._build_proxy(project, groups, 0, lambda _: None, reuse=False, download=False)
    assert seen == [render.preview_size(project)]
    assert (result['width'], result['height']) == render.preview_size(project)
    state = render.timeline(project)
    assert (state['width'], state['height']) == render.preview_size(project)
    project.aspect = 'landscape'
    assert render._proxy_key(project, groups, 0, None) == original


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
@pytest.mark.parametrize('engine', ['scene', 'pillow'])
def test_native_essay_preview_graph(project, monkeypatch, aspect, engine):
    project.aspect = aspect
    project.style.format = 'essay'
    project.style.captions_engine = engine
    seen = []
    monkeypatch.setattr(titles, 'render_caption', lambda *a, **kw: seen.append(kw['canvas']))
    monkeypatch.setattr(render, '_chosen', lambda *a, **kw: (Path('photo.jpg'), 'image', []))
    monkeypatch.setattr(render.ffutil, 'dimensions', lambda _: (1600, 900))
    _, graph, _ = render._segment_graph(project, [(project.slides[0], 3)], 3, 'set',
                                        size=render.preview_size(project))
    w, h = render.preview_size(project)
    assert seen and set(seen) == {render.frame_size(project)}
    assert f'scale={w}:{h}' in graph
    assert '[aspect]' not in graph
    assert 'force_original_aspect_ratio=decrease' in graph


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
@pytest.mark.parametrize('preview', [False, True])
def test_legacy_fallback_keeps_source_selection(project, tmp_path, monkeypatch, aspect, preview):
    project.aspect = aspect
    project.style.format = 'custom:missing'
    seen = []
    monkeypatch.setattr(render, '_render_custom_style', lambda *a: None)
    monkeypatch.setattr(render, '_chosen', lambda *a, **kw: seen.append(kw['preview']) or (None, 'image', []))
    monkeypatch.setattr(render.ffutil, 'run', lambda *a, **kw: None)
    render._render_segment(project, [(project.slides[0], 3)], 3, 0, tmp_path/'out.mp4',
                           size=render.preview_size(project) if preview else None)
    assert seen == [preview]


def test_square_overlay_fallback_keeps_photo_and_anchors_graph(project, tmp_path, monkeypatch):
    project.aspect = 'square'
    slide = project.slides[0]
    slide.overlays = [dict(id='lower', block_id='lower_third_kicker', vars={}, at=0, dur=2,
                           position='bottom_left', by='hand')]
    assert render.layout_fallback(project, slide) is None
    seen, commands = [], []
    def draw(*a, **kw):
        seen.append(kw['size'])
        a[3].write_bytes(b'clip')
    monkeypatch.setattr(scene_builder, 'render', draw)
    monkeypatch.setattr(block_overlays.scenes, '_prepare', lambda *a: ('key', tmp_path/'graphic.html', a[2]))
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: commands.append(args))
    size = render.preview_size(project)
    block_overlays.clip(project, slide.overlays[0], size, render.PREVIEW_FPS)
    assert seen == [blocks.source_size('16:9', size)]
    assert 'format=rgba,pad=270:270:' in commands[0][3]
    bottom = titles.safe_area(size)[3]
    assert f':{bottom-seen[0][1]}:color=black@0' in commands[0][3]
    report = check.run(project)
    assert any(f['code'] == 'aspect_overlay' and 'lower_third_kicker' in f['msg']
               for f in report['findings'])
    assert not any(f['code'] == 'aspect_letterbox' and f['slide_id'] == slide.id
                   for f in report['findings'])


def test_block_without_landscape_uses_declared_source(project, monkeypatch, tmp_path):
    project.aspect = 'square'
    project.slides[0].cues = {'blocks': [{'block': 'portrait_only', 'vars': {}}]}
    meta = {'aspects': {'9:16': 'block.html'}, 'duration': {}}
    monkeypatch.setattr(blocks, 'discover', lambda: {'portrait_only': {'meta': meta}})
    shapes = []
    monkeypatch.setattr(blocks, 'prepare', lambda ref, values, shape, *a, **kw: shapes.append(shape) or ('block.html', {}))
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw: shapes.append(kw['size']))
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: shapes.append(args[3]))
    render._render_segment(project, [(project.slides[0], 3)], 3, 0, tmp_path/'out.mp4')
    assert shapes[:2] == ['9:16', (594, 1056)]
    assert 'pad=1080:1080:' in shapes[2]


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
def test_sponsor_proxy_shape(project, monkeypatch, tmp_path, aspect):
    from app.schema import SponsorSlot
    project.aspect = aspect
    slot = SponsorSlot(id='read', script='A short read', variant='short',
                       take={'duration': 3, 'path': 'takes/read.wav'})
    project.sponsors = [slot]
    keys = []
    for shape in ['landscape', aspect, 'landscape']:
        project.aspect = shape
        keys.append(render._sponsor_preview(project, slot)[2])
    assert keys[0] == keys[2] != keys[1]
    project.aspect = aspect
    sizes = []
    def draw(*a, **kw):
        sizes.append(kw['size'])
        a[3].write_bytes(b'clip')
    monkeypatch.setattr(scene_builder, 'render', draw)
    monkeypatch.setattr(render, '_fit_clip', lambda src, out, size, *a: sizes.append(size) or out.write_bytes(b'fit'))
    render.sponsor_proxy(project, slot.id)
    assert sizes[-1] == render.preview_size(project)
    assert sizes[0][0] / sizes[0][1] == pytest.approx(16/9, abs=.01)


def test_native_caption_checks_skip_legacy_measurement(project, monkeypatch):
    project.aspect = 'square'
    project.style.format = 'essay'
    monkeypatch.setattr(render.scenes, 'measure_captions', lambda *a, **kw: pytest.fail('legacy scene measurement'))
    check.run(project)
    metrics = titles._native_card('A caption', '', '#ffffff', None, (1080, 1080), 'caption', measure_only=True)
    assert metrics['lines'] <= 2 and metrics['px'] > 0


@pytest.mark.parametrize('aspect,expected', [('landscape', (1280, 720)), ('portrait', (405, 720)), ('square', (720, 720))])
def test_thumbnail_fit_retains_whole_composition(project, aspect, expected):
    project.aspect = aspect
    image = Image.new('RGB', (1280, 720), 'white')
    result = thumbs._project_thumb(project, image)
    assert result.size == expected
    if aspect != 'landscape':
        assert result.getpixel((expected[0]//2, expected[1]//2)) == (255, 255, 255)
        assert result.getpixel((0, 0)) != (255, 255, 255)


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
@pytest.mark.parametrize('kind', ['cutaway', 'split'])
def test_camera_template_preserves_source_canvas(project, monkeypatch, tmp_path, aspect, kind):
    from app import camera_overlays
    from tests.unit.test_camera_render import camera
    project.aspect = aspect
    slide = camera(project)
    slide.take['overlays'] = [dict(kind=kind, at=0, dur=1,
        source={'template': 'slides/custom.html', 'context': {'width': 1600, 'height': 1200}})]
    seen = []
    monkeypatch.setattr(render.scenes, '_prepare', lambda *a: seen.append(a[4]) or ('key', tmp_path/'scene.html', a[2]))
    size = render.preview_size(project)
    _, graph, _ = camera_overlays.compose(project, slide, ['-i', 'camera.mp4'],
        '[0:v]null[base]', '[base]', size, 15, prepare_only=True)
    assert seen == [blocks.source_size('1600:1200', size)]
    if kind == 'split':
        assert f'pad={size[0]//4*2}:{size[1]}' in graph
    assert f'pad={size[0]}:{size[1]}' in graph
    assert 'force_original_aspect_ratio=decrease' in graph
    assert any('Camera overlay slides/custom.html' in f['msg']
               for f in check.run(project)['findings'])


@pytest.mark.parametrize('preview', [True, False])
def test_camera_overlay_footage_resolves_selected_source(project, tmp_path, monkeypatch, preview):
    from app import camera_overlays
    from app.media import footage
    from tests.unit.test_camera_render import camera
    slide = camera(project)
    source = tmp_path/'footage.mp4'
    source.write_bytes(b'fixture')
    slide.candidates = [dict(id='clip', provider='footage', kind='video')]
    slide.take['overlays'] = [dict(kind='cutaway', at=0, dur=1, source={'candidate_id':'clip'})]
    seen = []
    monkeypatch.setattr(footage, 'resolve', lambda *a, **kw: seen.append(kw['preview']) or source)
    monkeypatch.setattr(render, '_cover_crop', lambda *a: ('null', None))
    camera_overlays.compose(project, slide, ['-i', 'camera.mp4'], '[0:v]null[base]',
                           '[base]', (270, 270), 15, prepare_only=True, preview=preview)
    assert seen == [preview]


def test_square_presets_and_theme_context(project, monkeypatch):
    from app import block_library, block_presets
    project.aspect = 'square'
    monkeypatch.setattr(block_library.channels, 'load', lambda _: project)
    assert block_library.theme_context('channel', project.id)['aspect'] == '1:1'
    from copy import deepcopy
    library = deepcopy(blocks.discover())
    library['title_card']['meta']['aspects']['1:1'] = 'block.html'
    monkeypatch.setattr(blocks, 'discover', lambda: library)
    preset = block_presets.validate(dict(name='Square card', block='title_card', values={}, aspect='1:1'))
    assert preset['aspect'] == '1:1'


@pytest.mark.parametrize('aspect,target', [('16:9', (270, 167)), ('16:9', (1080, 670)),
                                           ('9:16', (270, 270)), ('1:1', (271, 480)),
                                           ('16:9', (480, 270)), ('9:16', (1080, 1920))])
def test_source_size_keeps_exact_ratio(aspect, target):
    # Chromium capture refuses any drift from the composition ratio.
    w, h = map(int, aspect.split(':'))
    sw, sh = blocks.source_size(aspect, target)
    assert sw * h == sh * w and sw % 2 == 0 and sh % 2 == 0
    assert sw <= target[0] and sh <= target[1]

"""Native type and full-render dispatch; no browsers or renderer processes."""
from pathlib import Path

import pytest
from PIL import Image

from app import blocks, check, render, titles


@pytest.mark.parametrize('canvas', [(1080, 1920), (1080, 1080)])
@pytest.mark.parametrize('kind', ['caption', 'title', 'chapter'])
def test_native_text_stays_inside_safe_area(tmp_path, canvas, kind):
    text = 'A long sentence with punctuation and a verylongunbrokenword' * 3
    out = tmp_path / f'{kind}.png'
    getattr(titles, f'render_{kind}')(text, out_path=out, canvas=canvas)
    image = Image.open(out).convert('RGBA')
    assert image.size == canvas
    if kind == 'caption':
        assert image.getbbox()[1] > canvas[1] * .54  # below the essay picture
    # Isolate white text from the dark plate, accent and chapter background.
    mask = image.convert('RGB').point(lambda v: 255 if v > 245 else 0).convert('L')
    bbox = mask.getbbox()
    assert bbox
    left, top, right, bottom = titles.safe_area(canvas)
    assert left <= bbox[0] < bbox[2] <= right
    assert top <= bbox[1] < bbox[3] <= bottom


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
@pytest.mark.parametrize('engine', ['scene', 'pillow'])
def test_camera_essay_native_captions(project, monkeypatch, aspect, engine):
    project.aspect = aspect
    project.style.format = 'essay'
    project.style.captions_engine = engine
    slide = project.slides[0]
    slide.on_camera = True
    seen = []
    monkeypatch.setattr(render, '_camera_source', lambda *a: (['-i', 'camera.mp4'], 'null'))
    monkeypatch.setattr(titles, 'render_caption', lambda *a, **kw: seen.append(kw))
    monkeypatch.setattr(render.scenes, 'caption_plates', lambda *a, **kw: pytest.fail('landscape captions'))
    inputs, graph, _ = render._segment_graph(project, [(slide, 3)], 3, 'set')
    assert seen and all(kw['canvas'] == render.frame_size(project) for kw in seen)
    assert '_cap00_' in ' '.join(inputs)
    assert '[aspect]' not in graph


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
def test_essay_image_and_video_keep_whole_source(project, monkeypatch, aspect):
    project.aspect = aspect
    project.style.format = 'essay'
    project.style.captions_engine = 'pillow'
    monkeypatch.setattr(titles, 'render_caption', lambda *a, **kw: None)
    monkeypatch.setattr(render.ffutil, 'dimensions', lambda _: (1600, 900))
    monkeypatch.setattr(render.ffutil, 'duration', lambda _: 8)
    for kind in ['image', 'video']:
        monkeypatch.setattr(render, '_chosen', lambda *a, **kw: (Path('source'), kind, []))
        _, graph, _ = render._segment_graph(project, [(project.slides[0], 3)], 3, 'set')
        assert 'force_original_aspect_ratio=decrease' in graph
        assert '[0:v]setsar=1,fps=' in graph if kind == 'video' else '[0:v]split=2' in graph
        bw, bh, x, y = render._essay_card(Path('source'), canvas=render.frame_size(project))
        w, h = render.frame_size(project)
        assert x >= 0 and x + bw <= w and y >= 0 and y + bh <= h * .55


@pytest.mark.parametrize('fmt', ['board', 'custom:mine', 'loudmouth'])
def test_unsupported_layout_letterboxes(project, tmp_path, monkeypatch, fmt):
    project.aspect = 'square'
    project.style.format = fmt
    seen = []
    def legacy(*args, **kwargs):
        seen.append('legacy')
        return args[3] if fmt != 'board' else None
    monkeypatch.setattr(render, '_render_custom_style', legacy)
    monkeypatch.setattr(render.cuts, 'render_segment', legacy)
    from app import board
    monkeypatch.setattr(board, 'render_segment', legacy)
    monkeypatch.setattr(render, '_chapter_tail', lambda p, out, *a: out)
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: seen.append(args))
    render._render_segment(project, [(project.slides[0], 3)], 3, 0, tmp_path / 'out.mp4', frames=(15, 30))
    assert seen[0] == 'legacy'
    assert 'force_original_aspect_ratio=decrease' in seen[-1][3]
    assert 'pad=1080:1080:' in seen[-1][3]


@pytest.mark.parametrize('aspect,expected', [('portrait', '9:16'), ('square', '1:1')])
def test_native_or_unsupported_block(project, tmp_path, monkeypatch, aspect, expected):
    project.aspect = aspect
    slide = project.slides[0]
    slide.cues = {'blocks': [{'block': 'test', 'vars': {}}]}
    supported = ['16:9', expected]
    monkeypatch.setattr(blocks, 'discover', lambda: {'test': {'meta': {'duration': {}, 'aspects': supported}}})
    seen = []
    def prepare(ref, values, shape, seconds, **kw):
        seen.append(shape)
        return 'test.html', {}
    monkeypatch.setattr(blocks, 'prepare', prepare)
    from app import scene_builder
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw: None)
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: seen.append(args))
    out = tmp_path / 'out.mp4'
    assert render.layout_fallback(project, slide) is None
    render._render_segment(project, [(slide, 3)], 3, 0, out)
    assert seen == [expected]
    supported.remove(expected)
    assert render.layout_fallback(project, slide) == 'Block'
    render._render_segment(project, [(slide, 3)], 3, 0, out)
    assert seen[1] == '16:9'
    assert 'force_original_aspect_ratio=decrease' in seen[2][3]


def test_aspect_check_finding(project, monkeypatch):
    project.aspect = 'portrait'
    project.style.format = 'board'
    monkeypatch.setattr(check, '_scene_text', lambda *a: None)
    report = check.run(project)
    assert any(f['code'] == 'aspect_letterbox' and 'letterboxed' in f['msg']
               for f in report['findings'])


@pytest.mark.parametrize('kind', ['intro', 'outro'])
@pytest.mark.parametrize('aspect', ['portrait', 'square'])
def test_slates_fit_without_stretch(project, tmp_path, monkeypatch, kind, aspect):
    from app import intro, outro
    project.aspect = aspect
    project.use_intro = project.use_outro = True
    project.intro.template = 'terminal'
    project.outro.enabled = True
    seen = []
    def draw(*a):
        seen.append(a[2])
        return 4
    monkeypatch.setattr(intro, 'render_intro', draw)
    monkeypatch.setattr(outro, 'render_outro', draw)
    monkeypatch.setattr(outro, 'wants_backdrop', lambda _: False)
    monkeypatch.setattr(render, '_last_picture', lambda _: None)
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: seen.append(args))
    out = tmp_path / f'{kind}.mp4'
    result, length = getattr(render, f'_build_{kind}')(project, lambda _: None, out)
    assert (result, length) == (out, 4)
    assert seen[0] != out
    assert f'pad={render.frame_size(project)[0]}:{render.frame_size(project)[1]}:' in seen[1][3]


@pytest.mark.parametrize('aspect', ['portrait', 'square'])
def test_presenter_uses_project_frame(project, tmp_path, monkeypatch, aspect):
    project.aspect = aspect
    seen = []
    monkeypatch.setattr(render, '_camera_look', lambda style, focal, size, *a: seen.append(size) or 'null')
    monkeypatch.setattr(render.ffutil, 'run', lambda *a, **kw: None)
    render._render_presenter(project, 3, tmp_path / 'presenter.mp4')
    assert seen == [render.frame_size(project)]


def test_slate_cache_aspect_switch(project):
    keys = []
    for aspect in ['landscape', 'portrait', 'square', 'landscape']:
        project.aspect = aspect
        keys.append(render._slate_key(project, 'intro'))
    assert len(set(keys[:3])) == 3
    assert keys[0] == keys[-1]

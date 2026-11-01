"""Custom-slide geometry and routing, without Chromium, archives or an LLM."""
from contextlib import contextmanager
from html.parser import HTMLParser
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from app import custom_scenes, custom_slide as custom, diagram, render, scenes, stage
from app.schema import Project, Slide


class Clips(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.clips = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'custom-element' in attrs.get('class', '').split():
            self.clips.append(attrs)


def spec():
    return {'elements': [
        dict(type='rect', x=.08, y=.12, w=.5, h=.2, order=8, anim='none', opacity=.5),
        dict(type='text', text='A <number>', x=.1, y=.2, w=.3, h=.2, order=4, anim='rise'),
        dict(type='circle', order=-1, anim='pop', fill=False),
        dict(type='line', order=4, anim='fly-left'),
        dict(type='image', local_path='a photo.png', fit='contain', order=9, anim='fly-right'),
        dict(type='text', text='Second', order=4, anim='fade', font='mono', align='right')]}


@pytest.mark.parametrize('reveal', ['sequence', 'all'])
def test_template_positions_schedule_and_assets(tmp_path, reveal):
    Image.new('RGB', (8, 8), 'red').save(tmp_path / 'a photo.png')
    raw = {**spec(), 'reveal': reveal}
    before = json.dumps(raw)
    ctx, _ = custom_scenes.context(tmp_path, raw, 6, grain=0)
    assert json.dumps(raw) == before
    html = scenes.render_html('slides/custom.html', ctx)
    assert scenes.lint(html) == []
    clips = Clips(html).clips
    assert len(clips) == len(raw['elements'])
    for index, (el, clip) in enumerate(zip(ctx['elements'], clips)):
        for prop in ('left', 'top', 'width', 'height'):
            field = dict(left='x', top='y', width='w', height='h')[prop]
            assert f'{prop}:{el[field] * 100}%' in clip['style']
        assert clip['data-track-index'] == str(index)
        assert clip['data-anim'] == el['anim']
        if el['anim'] == 'none':
            assert (el['start'], el['arrival']) == (0, 0)
        else:
            # Static order 8 is excluded; equal orders share one beat.
            expected = diagram.schedule(3, 6, reveal)[[-1, 4, 9].index(el['order'])]
            assert (el['start'], el['arrival']) == expected
        assert float(clip['data-start']) == el['start']
        assert float(clip['data-duration']) == 6 - el['start']
        assert clip['data-anim-exit'] == '0'
    assert 'A &lt;number&gt;' in html
    assert 'object-fit:contain' in html and '/scene/{token}/project/scenes/board-' in html
    assert 'font-mono size-md' in html and 'text-align:right' in html
    assert 'border-radius:50%' in html and 'opacity:0.5' in html
    for font in custom.FONT_KEYS:
        assert ctx['fonts']['Custom' + font].endswith(custom._stack(font, custom.DEFAULT_HAND)[0][0].split('/')[-1])


@pytest.mark.parametrize('face', sorted(custom.FONT_KEYS))
@pytest.mark.parametrize('size,width,height', [('md', .8, .2), ('xxl', .8, .6), ('xxl', .18, .12)])
def test_text_baselines_match_pillow_top_anchor(tmp_path, face, size, width, height):
    raw = dict(elements=[dict(type='text', text='Égj ÁT pqy 42 café', font=face,
                             size=size, x=0, y=0, w=width, h=height)])
    ctx, _ = custom_scenes.context(tmp_path, raw, 6, grain=0)
    el = ctx['elements'][0]
    font, lines, line_h = custom._fit_text(
        el['text'], custom._stack(face, custom.DEFAULT_HAND), el['_w'], el['_h'],
        custom.SIZE_PX[size])
    if width == .18:
        assert font.size < custom.SIZE_PX[size]
        assert len(lines) > 1
    assert [line['text'] for line in el['text_lines']] == lines
    # Render the supplied SVG baselines with Pillow's baseline anchor and
    # compare against the real custom-slide tile's per-line top anchors.
    baseline_tile = Image.new('RGBA', (el['_w'], el['_h']))
    draw = ImageDraw.Draw(baseline_tile)
    for i, line in enumerate(el['text_lines']):
        top_from_ascent = font.getbbox(line['text'])[1] - font.getmetrics()[0]
        assert line['baseline'] + top_from_ascent == pytest.approx(i * line_h)
        draw.text((0, line['baseline']), line['text'], font=font, fill='white', anchor='ls')
    pillow_tile = custom._build_tile(el, custom.DEFAULT_HAND, tmp_path)
    assert baseline_tile.getchannel('A').tobytes() == pillow_tile.getchannel('A').tobytes()
    html = scenes.render_html('slides/custom.html', ctx)
    for line in el['text_lines']:
        assert f'y="{line["baseline"]}"' in html
    assert 'dominant-baseline="alphabetic"' in html
    assert 'line-height:' not in html


def test_elements_use_builder(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import scene_builder
    ctx, ground = custom_scenes.context(tmp_path, spec(), 6, grain=0)
    out = tmp_path / 'out.mp4'
    calls = []
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw:
                        calls.append((a, kw)) or SimpleNamespace(path=out))
    assert custom_scenes.render(tmp_path, ctx, ground, out, size=(480, 270), fps=15) == out
    assert calls == [((tmp_path, 'slides/custom.html', ctx, out),
                      dict(seconds=6, size=(480, 270), fps=15, crf=17))]
    clips = Clips(scenes.render_html('slides/custom.html', ctx)).clips
    assert [c['data-motion'] for c in clips] == [e['anim'] for e in ctx['elements']]
    assert [c['data-motion-ease'] for c in clips] == [
        'back-out' if e['anim'] == 'pop' else 'quad-out' for e in ctx['elements']]
    assert ctx['elements'][0]['anim'] == 'none'
    assert [e['order'] for e in ctx['elements'][1:]] == sorted(e['order'] for e in ctx['elements'][1:])


def test_schema_default_fallback_unknown_fields(project):
    raw = project.to_dict()
    raw['style'].update(custom_engine='pillow', future='ignored')
    assert Project.from_dict(raw).style.custom_engine == 'pillow'
    del raw['style']['custom_engine']
    assert Project.from_dict(raw).style.custom_engine == 'scene'


@pytest.mark.parametrize('style', json.loads((Path(__file__).resolve().parents[2] /
    'docs/tickets/05-migrations/compare/custom/styles.json').read_text()), ids=lambda s: s['name'])
def test_comparison_style_contract(tmp_path, style):
    Image.new('RGB', (8, 8), 'red').save(tmp_path / 'photo.png')
    ctx, _ = custom_scenes.context(tmp_path, style['spec'], 6, grain=0)
    html = scenes.render_html('slides/custom.html', ctx)
    assert scenes.lint(html) == []
    assert len(Clips(html).clips) == len(style['spec']['elements'])


@pytest.mark.parametrize('motion', ['still', 'reveal'])
@pytest.mark.parametrize('engine', ['scene', 'pillow'])
def test_candidate_engines(tmp_path, monkeypatch, motion, engine):
    captures, encodes = [], []
    data = io.BytesIO()
    Image.new('RGB', (2, 2)).save(data, 'PNG')
    monkeypatch.setattr(custom, 'resolve_images', lambda spec, dest: spec)
    monkeypatch.setattr(custom_scenes, 'still', lambda *a, **kw: captures.append(kw) or data.getvalue())
    monkeypatch.setattr(custom_scenes, 'render', lambda *a, **kw: encodes.append('scene'))
    monkeypatch.setattr(custom.ffutil, 'encode_frames', lambda *a, **kw: encodes.append('pillow') or 180)
    cand = custom.candidate(spec(), tmp_path, motion=motion, engine=engine, grain=0)
    assert cand['provider'] == 'custom' and cand['custom'] == custom.normalise(spec())
    assert cand['kind'] == ('image' if motion == 'still' else 'video')
    assert len(captures) == (engine == 'scene')
    assert encodes == ([] if motion == 'still' else [engine])


def test_segment_routes_and_saved_style_fallback(project, tmp_path, monkeypatch):
    from app import slide_styles
    slide = Slide(id='custom', custom=spec())
    calls, pillow = [], []
    monkeypatch.setattr(render, 'project_dir', lambda pid: tmp_path)
    monkeypatch.setattr(custom, 'resolve_images', lambda *a: pytest.fail('render must not fetch'))
    monkeypatch.setattr(custom_scenes, 'render', lambda *a, **kw: calls.append((a, kw)) or a[3])
    monkeypatch.setattr(custom.ffutil, 'encode_frames', lambda *a, **kw: pillow.append(kw) or 180)
    out = tmp_path / 'out.mp4'
    assert render._render_custom_style(project, [(slide, 5)], 6, out, (480, 270), 15) == out
    assert calls[0][1] == dict(size=(480, 270), fps=15, crf=17)
    assert calls[0][0][1]['duration'] == 6
    project.style.custom_engine = 'pillow'
    assert render._render_custom_style(project, [(slide, 5)], 6, out, (480, 270), 15) == out
    assert pillow[0]['extra'] == ('-vf', 'scale=480:270', '-r', '15')
    project.style.custom_engine = 'scene'
    slide.custom = {}
    monkeypatch.setattr(slide_styles, 'get', lambda key: slide_styles.SlideStyle(id='ss', name='Saved', spec=spec()))
    assert render._render_custom_style(project, [(slide, 5)], 6, out) == out
    monkeypatch.setattr(slide_styles, 'get', lambda key: None)
    assert render._render_custom_style(project, [(slide, 5)], 6, out) is None


def test_candidate_job_unlocks_and_reloads(project, tmp_path, monkeypatch):
    from app import main
    project.slides = [Slide(id='custom')]
    locked, loads = [], []

    @contextmanager
    def lock(pid):
        locked.append(pid)
        try:
            yield
        finally:
            locked.pop()

    def load(pid):
        loads.append(pid)
        return project

    def candidate(*a, **kw):
        assert not locked
        assert kw['engine'] == project.style.custom_engine
        return dict(id='new', custom=custom.normalise(spec()))

    monkeypatch.setattr(main.store, 'lock_for', lock)
    monkeypatch.setattr(main, '_load', load)
    monkeypatch.setattr(main, 'project_dir', lambda pid: tmp_path)
    monkeypatch.setattr(main.custom_mod, 'candidate', candidate)
    monkeypatch.setattr(main.store, 'save', lambda p: None)
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, work: work(lambda m: None))
    result = main.slide_custom(project.id, 'custom', {'spec': spec()})
    assert loads == [project.id, project.id]
    assert result['job']['slide']['chosen_id'] == 'new'

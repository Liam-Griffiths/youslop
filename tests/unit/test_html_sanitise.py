"""Adversarial fragments and the HTML editor path: no LLM, network or browser."""
from contextlib import contextmanager
import io

from PIL import Image
import pytest

from app import custom_scenes, llm, render, sanitise, scenes, script_gen, stage
from app.schema import Project, Slide

GOOD = '<section class="cb-slide"><p class="cb-label">The turning point</p><h1 class="cb-number cb-accent">1910</h1></section>'
SOURCE = '/scene/{token}/project/scenes/board-' + 'a' * 40 + '.png'


@pytest.mark.parametrize('payload', [
    '<img src=x onerror=alert(1)>', '<scr<script>ipt>alert(1)</script>',
    '<a href="javascript:alert(1)">x</a>', '<svg><script>alert(1)</script></svg>',
    '<p style="background:url(javascript:1)">', '<img src="http://evil/x.png">',
    '<math><mtext><style>...', '<script>alert(1)</script>', '<style>@import "//evil";</style>',
    '<iframe src="//evil"></iframe>', '<object></object>', '<template><p>x</p></template>',
    '<svg><foreignObject><p>x</p></foreignObject></svg>',
    '<p onclick="alert(1)">x</p>', '<p ONMOUSEOVER="alert(1)">x</p>',
    '<p style="width:expression(alert(1))">x</p>', '<p style="color:red">x</p>',
    '<p class="clip">x</p>', '<p class="cb-title evil">x</p>',
    '<p data-text="url(https://evil)">x</p>', '<p alt="EXPRESSION(alert(1))">x</p>',
    '<p alt="@import https://evil">x</p>', '<img src="javascript:alert(1)">',
    '<img src="data:image/png;base64,AAAA">', '<img src="data:image/svg+xml,evil">',
    '<p data-text="java&#x73;cript:alert(1)">x</p>',
    '<p data-text="java&#9;script:alert(1)">x</p>',
    '<p alt="%256a%2561vascript:alert(1)">x</p>',
    '<p alt="u&#114;l(https://evil)">x</p>', '<p alt="u\\72l(https://evil)">x</p>',
    '<p class="cb&#45;title">x</p>', '<p data-start="&#49;">x</p>',
    '''<p alt="class='cb-title'" class="cb&#45;title">x</p>''',
    '<p alt="%' + '25' * 12 + '6aavascript:alert(1)">x</p>',
    '<p class="cb-title" class="evil">x</p>', '<p data-start="NaN">x</p>',
    '<p data-start="inf">x</p>', '<p data-start="-1">x</p>', '<p data-start="1e3">x</p>',
    '<section><p>x</section></p>', '<p>x', '<p title="unterminated',
    '<img src="unterminated', '<p>x</p bogus>', '<p/>', '<p>x</p',
    '<p>x</p\x00>', '<!-- <script> -->', '<!DOCTYPE html>', '<?xml version="1.0"?>',
    '<p data-composition-src="/evil">x</p>', '<p src="' + SOURCE + '">x</p>',
    '<img src="/scene/{token}/project/../../secret.png">',
    '<img src="/scene/{token}/project/%2e%2e/secret.png">',
    '<img src="//evil/a.png">', '<img src="' + SOURCE.replace('board-', 'board-&#97;') + '">',
])
def test_reject_entire_unsafe_fragment(payload):
    with pytest.raises(sanitise.UnsafeHTML):
        sanitise.clean(GOOD + payload, [SOURCE])


def test_rebuild_and_text_entities():
    assert sanitise.clean(GOOD) == GOOD
    tags = '<section><h2>Title</h2><ul><li><strong>Strong</strong><em>Emphasis</em></li></ul><figure><figcaption><span>Caption</span></figcaption></figure></section>'
    assert sanitise.clean(tags) == tags
    text = '<p class="cb-title" data-start="1.25" data-text="A &amp; B">&lt;script&gt; &amp; &#60;img&#62;</p>'
    assert sanitise.clean(text) == '<p class="cb-title" data-start="1.25" data-text="A &amp; B">&lt;script&gt; &amp; &lt;img&gt;</p>'
    assert sanitise.clean(sanitise.clean(text)) == sanitise.clean(text)
    assert sanitise.clean(f"<img src='{SOURCE}' alt='photo'/>", [SOURCE]) == f'<img src="{SOURCE}" alt="photo">'
    with pytest.raises(sanitise.UnsafeHTML):
        sanitise.clean(f'<img src="{SOURCE}">')
    with pytest.raises(sanitise.UnsafeHTML):
        sanitise.clean('<img src="https://evil/x">', ['https://evil/x'])


def test_sources_generation_and_template_boundary(project, tmp_path, monkeypatch):
    root = tmp_path / 'media'
    root.mkdir()
    Image.new('RGB', (8, 8), 'red').save(root / 'photo.jpg')
    Image.new('RGB', (8, 8), 'blue').save(tmp_path / 'outside.png')
    (root / 'link.png').symlink_to(tmp_path / 'outside.png')
    slide = Slide(id='html', narration='The year everything changed.', custom={'elements': [
        dict(type='image', local_path='photo.jpg'), dict(type='image', local_path='../outside.png'),
        dict(type='image', local_path='link.png')]})
    project.slides = [slide]
    monkeypatch.setattr('app.store.project_dir', lambda pid: tmp_path)
    sources = custom_scenes.html_sources(root, slide.custom)
    assert len(sources) == 1
    with Image.open(root / sources[0].split('/project/')[1]) as image:
        assert image.format == 'PNG'

    def complete(prompt, **kwargs):
        assert sources[0] in prompt and 'cb-row' in prompt and 'Allowed tags:' in prompt
        assert kwargs['require']({'html': GOOD})
        return {'html': GOOD}

    monkeypatch.setattr(llm, 'complete_json', complete)
    assert script_gen.generate_custom_html(project, slide, 'Make the year enormous') == GOOD
    ctx = custom_scenes.html_context(root, GOOD, slide.custom, project=project)
    html = scenes.render_html('slides/custom.html', ctx)
    assert GOOD in html and scenes.lint(html) == []
    assert html.index('Content-Security-Policy') < html.index('<script')
    assert "connect-src 'none'" in html and "default-src 'none'" in html
    assert "img-src 'self'" in html and 'data:' not in html
    with pytest.raises(sanitise.UnsafeHTML):
        scenes.render_html('slides/custom.html', {**ctx, 'custom_html': '<script>bad</script>'})
    with pytest.raises(sanitise.UnsafeHTML):
        scenes.env.get_template('slides/custom.html').render(**{**ctx, 'custom_html': '<script>bad</script>'})
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: {'html': '<p onclick="evil()">x</p>'})
    with pytest.raises(sanitise.UnsafeHTML):
        script_gen.generate_custom_html(project, slide)
    slide.custom_html = GOOD
    assert Project.from_dict(project.to_dict()).slides[0].custom_html == GOOD
    assert Slide.from_dict({'id': 'old', 'future': True}).custom_html == ''
    script_gen.plan_custom_slides(project, [slide], {'elements': [dict(type='text', text='Keep HTML')]})
    assert slide.custom_html == GOOD


def test_preview_apply_generate_and_json_switch(project, tmp_path, monkeypatch):
    from app import main
    slide = Slide(id='html', narration='1910 changed everything.')
    project.slides = [slide]
    locked, captures, saves = [], [], []

    @contextmanager
    def lock(pid):
        locked.append(pid)
        try:
            yield
        finally:
            locked.pop()

    def capture(path, width, height, t, size, **kwargs):
        assert not locked
        html = path.read_text()
        assert GOOD in html and 'Content-Security-Policy' in html
        captures.append(size)
        data = io.BytesIO()
        Image.new('RGB', size).save(data, 'PNG')
        return data.getvalue()

    monkeypatch.setattr(main, '_load', lambda pid: project)
    monkeypatch.setattr(main, 'project_dir', lambda pid: tmp_path)
    monkeypatch.setattr(main.store, 'lock_for', lock)
    monkeypatch.setattr(main.store, 'save', lambda p: saves.append(p.to_dict()))
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, work: work(lambda m: None))
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: {'html': GOOD})
    monkeypatch.setattr(stage, 'capture_one', capture)
    generated = main.generate_slide_custom(project.id, slide.id, {'html': True})['job']
    assert generated == {'custom_html': GOOD} and slide.custom_html == ''
    response = main.custom_preview({**generated, 'project_id': project.id, 'slide_id': slide.id})
    assert response.media_type == 'image/png' and captures == [(480, 270)]
    for endpoint, payload in [(main.custom_preview, {'project_id': project.id, 'slide_id': slide.id}),
                              (lambda p: main.slide_custom(project.id, slide.id, p), {})]:
        with pytest.raises(main.HTTPException) as exc:
            endpoint({**payload, 'custom_html': GOOD + '<script>bad</script>'})
        assert exc.value.status_code == 400
    assert not saves and len(captures) == 1
    main.slide_custom(project.id, slide.id, {**generated, 'motion': 'still'})
    assert slide.custom_html == GOOD and slide.prefer_kind == 'custom' and saves
    monkeypatch.setattr(main.custom_mod, 'candidate', lambda *a, **kw: dict(id='json', custom={'elements': []}))
    main.slide_custom(project.id, slide.id, {'spec': {'elements': [dict(type='text', text='JSON')]}})
    assert slide.custom_html == '' and slide.chosen_id == 'json'


def test_html_render_and_candidate_motion(project, tmp_path, monkeypatch):
    project.slides = [Slide(id='html', custom_html=GOOD)]
    calls = []
    monkeypatch.setattr(render, 'project_dir', lambda pid: tmp_path)
    monkeypatch.setattr(scenes, 'ensure_clip', lambda *a, **kw: calls.append(kw) or tmp_path / 'clip.mp4')
    monkeypatch.setattr(scenes, '_encode', lambda *a: None)
    monkeypatch.setattr(scenes, 'capture', lambda *a, **kw: b'fake png')
    root = tmp_path / 'media'
    root.mkdir()
    cand = custom_scenes.html_candidate(GOOD, root, {}, seconds=4)
    assert cand['kind'] == 'video' and cand['custom_html'] == GOOD and cand['duration'] == 4
    render._render_custom_style(project, [(project.slides[0], 4)], 5, tmp_path / 'out.mp4', (480, 270), 15)
    assert calls[-1] == dict(seconds=5, size=(480, 270), fps=15)
    project.slides[0].custom_html = '<img src="https://evil/x">'
    with pytest.raises(sanitise.UnsafeHTML):
        render._render_custom_style(project, [(project.slides[0], 4)], 5, tmp_path / 'out.mp4')


def test_documented_class_allowlist():
    doc = (scenes.SCENE_DIR / 'slides/classes.md').read_text()
    assert all('| ' + name + ' |' in doc for name in sanitise.CLASSES)

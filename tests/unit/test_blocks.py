"""Block discovery, validation and scene dispatch without Chromium or LLMs."""
import json
import re

import pytest

from app import blocks, cli, scenes, scene_builder, stage, packs
from types import SimpleNamespace


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks, 'USER_DIR', tmp_path / 'blocks')
    monkeypatch.setattr(packs, 'PACKS_DIR', tmp_path / 'packs')
    monkeypatch.setattr(packs, 'BUILTIN_DIR', tmp_path / 'builtin-packs')
    return tmp_path


def add_block(root, **updates):
    root.mkdir(parents=True)
    meta = json.loads((blocks.BUILTIN_DIR / 'chapter/block.json').read_text())
    meta.update(id=root.name, **updates)
    (root / 'block.json').write_text(json.dumps(meta))
    (root / 'block.html').write_text('{% extends "_base.html" %}{% block body %}{{ vars.title }}{% endblock %}')
    return meta


def test_discovery_and_cli(library, capsys):
    add_block(blocks.USER_DIR / 'mine')
    pack = packs.PACKS_DIR / 'demo-pack'
    add_block(pack / 'blocks/mine')
    (pack / 'pack.json').write_text('{"id":"demo-pack","name":"Demo pack","version":"1.0.0","author":"Fixture","licence":"CC0"}')
    found = blocks.discover()
    count = len(list(blocks.BUILTIN_DIR.glob('*/block.json'))) + 2
    assert len(found) == count and {'user/mine', 'pack/demo-pack/mine'} <= found.keys()
    assert cli.main(['block', 'list']) == 0
    assert len(json.loads(capsys.readouterr().out)) == count
    assert cli.main(['block', 'show', 'chapter']) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'chapter'


@pytest.mark.parametrize('ref', ['_test', 'intro_solo', 'intro_dossier',
                                    'intro_folio', 'intro_portrait', 'outro_twoup',
                                    'outro_quiet'])
def test_existing_html_identical(library, ref):
    template, ctx = blocks.prepare(ref)
    original = 'sponsor/house_short.html' if ref.startswith('sponsor') else f'cards/{ref}.html'
    html = scenes.render_html(template, ctx)
    assert scenes.lint(html, asset_root=ctx['block_assets_root']) == []
    without_base = lambda h: re.sub(r'<base href="[^"]*">', '', h).strip()
    assert without_base(html) == without_base(scenes.render_html(original, ctx))


@pytest.mark.parametrize('values,match', [({'title':'x'*241}, 'maxLength'),
                                         ({'title':42}, 'expected string'),
                                         ({'unknown':1}, 'unknown block variables')])
def test_refused_before_render(library, monkeypatch, values, match):
    monkeypatch.setattr(scenes, 'ensure_clip', lambda *a, **k: pytest.fail('render invoked'))
    with pytest.raises(ValueError, match=match):
        blocks.render('chapter', values)


@pytest.mark.parametrize('spec,bad', [
    (dict(type='number', default=1, min=0, max=2), True),
    (dict(type='number', default=1), float('nan')),
    (dict(type='colour', default='var(--accent)'), 'red'),
    (dict(type='image', default=''), 'https://remote/image.png'),
    (dict(type='clip', default=''), '/scene/%2e%2e/private'),
    (dict(type='table', default=[{'n':1}]), [[1,2]]),
    (dict(type='enum', default='a', choices=['a','b']), 'c'),
])
def test_variable_types(spec, bad):
    meta = {'variables': {'value':spec}}
    assert blocks.validate_vars(meta, {})['value'] == spec['default']
    with pytest.raises(ValueError):
        blocks.validate_vars(meta, {'value':bad})


def test_variants_duration_cache_and_assets(library, monkeypatch):
    root = blocks.USER_DIR / 'custom'
    add_block(root, aspects={'9:16':'block.html', '1:1':'block.html'},
              duration=dict(mode='from_words', min=1, max=10, variable='title', words_per_minute=60))
    (root / 'asset.txt').write_text('first')
    calls = []
    def render(owner, template, ctx, out, **kw):
        calls.append((ctx, kw))
        out.write_bytes(b'fake')
        return SimpleNamespace(path=out)
    monkeypatch.setattr(scene_builder, 'render', render)
    kw = dict(aspect='9:16', project=library / 'cache')
    first = blocks.render('user/custom', {'title':'two words'}, **kw)
    assert blocks.render('user/custom', {'title':'two words'}, **kw) == first
    assert len(calls) == 1 and calls[0][0]['block_assets_root'] == str(root)
    assert calls[0][1]['size'] == (1080,1920) and calls[0][1]['seconds'] == 2
    (root / 'asset.txt').write_text('changed')
    assert blocks.render('user/custom', {'title':'two words'}, **kw) != first
    for kwargs in [dict(aspect='16:9'), dict(aspect='1:1', seconds=11)]:
        with pytest.raises(ValueError):
            blocks.prepare('user/custom', **kwargs)
    assert blocks.prepare('user/custom', aspect='1:1')[1]['height'] == 1080


def test_bad_manifest_and_escape(library):
    root = blocks.USER_DIR / 'bad'
    add_block(root, version=3)
    with pytest.raises(ValueError, match='version'):
        blocks.discover()
    add = json.loads((root / 'block.json').read_text())
    add['version'] = '1.0.0'
    add['aspects']['16:9'] = '../private.html'
    (root / 'block.json').write_text(json.dumps(add))
    with pytest.raises(ValueError, match='invalid format'):
        blocks.discover()


def test_preview_and_lint(library, monkeypatch):
    monkeypatch.setattr(stage, 'render_scene', lambda *a, **k: pytest.fail('browser invoked'))
    root = blocks.USER_DIR / 'custom'
    add_block(root, aspects={'9:16':'block.html'})
    (root / 'block.html').write_text('{% extends "_base.html" %}{% block body %}<script>Date.now()</script>{% endblock %}')
    with pytest.raises(ValueError, match='unsafe block tag: script'):
        blocks.render('user/custom', aspect='9:16', project=library / 'cache')
    (root / 'block.html').write_text('{% extends "_base.html" %}')
    def capture(*args, **kwargs):
        assert args[1:3] == (1080,1920) and args[4] == (270,480)
        assert kwargs['assets_root'] == str(root)
        return b'fake png'
    monkeypatch.setattr(stage, 'capture_one', capture)
    out = library / 'preview.png'
    assert cli.main(['block','preview','user/custom','--aspect','9:16','--t','1.5','--out',str(out)]) == 0
    assert out.read_bytes() == b'fake png'


def test_fixed_duration_beats_and_symlink(library):
    root = blocks.USER_DIR / 'timed'
    add_block(root, duration=dict(mode='fixed', seconds=5), beats={'hit':'land here'})
    context = scenes.context_base()
    context['take'] = {'words':[{'w':'Land', 'start':1.2, 'src':'est'},
                                {'w':'here', 'start':1.6, 'src':'est'}]}
    _, ctx = blocks.prepare('user/timed', context=context)
    assert ctx['beats'] == {'hit':1.2} and ctx['beat_sources'] == {'hit':'est'}
    assert ctx['safe_areas'] == {'title':.1, 'action':.05}
    with pytest.raises(ValueError, match='duration'):
        blocks.prepare('user/timed', seconds=6)
    (library / 'private.html').write_text('<template/>')
    (root / 'escape.html').symlink_to(library / 'private.html')
    with pytest.raises(ValueError, match='outside folder'):
        blocks.prepare('user/timed')


@pytest.mark.parametrize('resource', ['<style>@font-face{src:url(https://remote/font.ttf)}</style>',
                                     '<link href="//remote/style.css" rel="stylesheet">'])
def test_remote_resources_refused(library, monkeypatch, resource):
    root = blocks.USER_DIR / 'remote'
    add_block(root)
    (root / 'block.html').write_text('{% extends "_base.html" %}{% block head %}' + resource + '{% endblock %}')
    monkeypatch.setattr(stage, 'render_scene', lambda *a, **k: pytest.fail('browser invoked'))
    with pytest.raises(ValueError, match='unsafe block'):
        blocks.render('user/remote', project=library / 'cache')


def test_range_default_is_a_watchable_length():
    from app import blocks
    _, ctx = blocks.prepare('sponsor_house_read')
    assert ctx['duration'] == 8
    _, ctx = blocks.prepare('chapter')
    assert ctx['duration'] == 5.0


def test_authoring_scaffold_and_static_checks(library, monkeypatch, capsys):
    from app import block_authoring as kit
    monkeypatch.setattr(stage, '_run_cdp', lambda *a, **k: pytest.fail('browser invoked'))
    assert cli.main(['block', 'new', 'my-title']) == 0
    root = blocks.USER_DIR / 'my-title'
    assert kit.lint('user/my-title') == []
    assert cli.main(['block', 'check', 'user/my-title', '--static-only']) == 0
    assert 'browser checks skipped' in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        kit.new('my-title')
    with pytest.raises(ValueError):
        kit.new('../escape')
    assert kit.samples(blocks.discover()['user/my-title']['meta']) == {'title':'W'*80}
    (root / 'block.html').write_text(kit.TEMPLATE.replace('{% block body %}',
        '{% block body %}<script>Date.now()</script>'))
    assert any('unsafe block tag: script' in error for error in kit.lint('user/my-title'))


def test_authoring_browser_measurements(library, monkeypatch):
    from app import block_authoring as kit
    kit.new('probe')
    visited = []
    class CDP:
        def send(self, method, params, session):
            if method == 'Page.captureScreenshot':
                import base64
                import io
                from PIL import Image
                out = io.BytesIO()
                Image.new('RGB', (2,2)).save(out, format='PNG')
                return {'data':base64.b64encode(out.getvalue()).decode()}
            expression = params['expression']
            return {'result':{'value':['title: text overflow'] if 'querySelectorAll' in expression else None}}
    def run(job, progress, **kwargs):
        item = job['items'][0]
        visited.append((item['W'], item['H']))
        kwargs['scene_probe'](CDP(), 'session', item, item['t'])
    monkeypatch.setattr(stage, '_run_cdp', run)
    monkeypatch.setattr(scene_builder, 'inspect', lambda *a, **kw: {})
    errors = kit.check('user/probe')
    assert len(errors) == 3 and all('title: text overflow' in e for e in errors)
    assert visited == [(1920,1080), (1080,1920), (1080,1080)]


def test_authoring_preview_bundle(library, monkeypatch):
    from app import block_authoring as kit
    import io
    from PIL import Image
    kit.new('preview')
    out = io.BytesIO()
    Image.new('RGB', (480,270)).save(out, format='PNG')
    times = []
    def capture(*a, **kw):
        assert kw['size'] == (480,270)
        times.append(kw['t'])
        return out.getvalue()
    def clip(root, template, ctx, dest, **kw):
        assert kw['size'] == (480,270) and kw['seconds'] == 3
        path = dest
        path.write_bytes(b'mock mp4')
        return path
    monkeypatch.setattr(scenes, 'capture', capture)
    monkeypatch.setattr(scene_builder, 'render', clip)
    target = library / 'preview-output'
    assert cli.main(['block','preview','user/preview','--out',str(target)]) == 0
    assert {p.name for p in target.iterdir()} == {'preview.png','sheet.png','preview.mp4'}
    assert times == [1.5, 0, .5, 1, 1.5, 2, 2.5]


def test_typed_csv_and_legacy_tables():
    columns = [dict(key='name', label='Name', type='text'),
               dict(key='count', label='Trips', type='number', unit='million'),
               dict(key='date', type='date')]
    meta = {'variables': {'rows': dict(type='table', default=[], columns=columns)}}
    rows = blocks.validate_vars(meta, {'rows': 'date,Name,Trips\n2024,Rail,"1,200 million"\n2025-01-01,Bus,68%\n'})['rows']
    assert rows == [dict(date='2024', name='Rail', count=1200),
                    dict(date='2025-01-01', name='Bus', count=68)]
    assert blocks.validate_vars({'variables': {'rows': dict(type='table', default=[{'old': True}])}}, {})['rows'] == [{'old': True}]
    for value, error in [([dict(name='Rail', count='oops', date='2024')], 'row 1 column count'),
                         ([dict(name='Rail', count=True, date='2024')], 'row 1 column count'),
                         ([dict(name='Rail', count=2, date='2024-99-99')], 'row 1 column date'),
                         ([dict(name='Rail', count=float('inf'), date='2024')], 'row 1 column count'),
                         ('Name,Name,date\na,b,2024', 'headers'),
                         ('Name,Trips,date\na,2', 'row 1')]:
        with pytest.raises(ValueError, match=error):
            blocks.validate_vars(meta, {'rows': value})
    _, ctx = blocks.prepare('bar_chart', {'rows': 'Label,Value\nRail,72\nBus,54'})
    assert ctx['vars']['rows'][0]['value'] == 72


@pytest.mark.parametrize('text,value,unit,ref,bad', [
    ('72 million trips.', 72, 'million trips', 'number_slam', False),
    ('72 million trips.', 68, 'million trips', 'number_slam', True),
    ('68 percent.', 68, '', 'percentage_ring', False),
    ('68%.', 72, '', 'percentage_ring', True),
    ('72 residents.', 72.4, 'residents', 'number_slam', False),
    ('72 residents.', 73, 'residents', 'number_slam', True),
    ('Roughly 1,200 residents.', 1100, 'residents', 'number_slam', True),
    ('Roughly 1,200 residents.', 1180, 'residents', 'number_slam', False),
    ('72.4 residents.', 72.44, 'residents', 'number_slam', False),
    ('About 70 residents.', 72, 'residents', 'number_slam', False),
    ('70 residents.', 72, 'residents', 'number_slam', True),
    ('In 2024, 1,200 residents.', 1200, 'residents', 'number_slam', False),
    ('-12.5 residents.', -12.5, 'residents', 'number_slam', False),
])
def test_number_match(text, value, unit, ref, bad):
    from app import check
    values = {'value': value}
    if ref == 'number_slam':
        values['unit'] = unit
        values['decimals'] = '2'
    sb = {'paragraphs': [dict(id='s1', start=1.5, narration=text,
                             block_cues=[dict(block=ref, vars=values)])]}
    findings = check.number_match(sb, None, None)
    assert bool(findings) == bad
    if bad:
        assert findings[0].level == 'P1' and findings[0].slide_id == 's1'
        assert str(value) in findings[0].msg and 'narration [' in findings[0].msg


def test_number_match_headline_years_and_multiple_blocks():
    from app import check
    p = dict(id='s1', start=0, narration='54 million trips in 2024.', block_cues=[
        dict(block='bar_chart', vars={'rows': [{'label': 'A', 'value': 72}, {'label': 'B', 'value': 54}]})])
    assert '72' in check.number_match({'paragraphs': [p]}, None, None)[0].msg
    p['narration'] = '72 million trips and 54 million trips in 2024.'
    assert check.number_match({'paragraphs': [p]}, None, None) == []
    p['block_cues'].append(dict(block='date_timeline', vars={}))
    assert check.number_match({'paragraphs': [p]}, None, None) == []
    p['narration'] = '72 million trips in 2025.'
    assert '2025' in check.number_match({'paragraphs': [p]}, None, None)[0].msg
    p['narration'] = 'A growing network.'
    assert check.number_match({'paragraphs': [p]}, None, None) == []


def test_research_source_defaults(library):
    research = {'facts': [{'source': 'First report', 'url': 'https://first.example/a'},
                          {'source': 'Second report', 'url': 'https://second.example/b'}]}
    context = scenes.context_base()
    context.update(research=research, narration='As reported [2].')
    assert blocks.prepare('bar_chart', {'source': ''}, context=context)[1]['vars']['source'] == 'Source: Second report'
    context['narration'] = 'See https://second.example/b'
    assert blocks.prepare('bar_chart', {'source': ''}, context=context)[1]['vars']['source'] == 'Source: Second report'
    context['narration'] = 'No citation.'
    assert blocks.prepare('bar_chart', {'source': ''}, context=context)[1]['vars']['source'] == 'Source: First report'
    assert 'illustrative sample data' in blocks.prepare('bar_chart', context=context)[1]['vars']['source']
    assert blocks.prepare('bar_chart', {'source': 'My source'}, context=context)[1]['vars']['source'] == 'My source'
    assert blocks.source_line({'facts': [{'url': 'https://example.org/report'}]}, '') == 'Source: example.org'
    assert blocks.source_line({}, '') == ''


def test_saved_block_cue_checked_without_mutation(project, monkeypatch):
    from app import check, ffutil, llm, storyboard
    monkeypatch.setattr(ffutil, 'run', lambda *a, **k: pytest.fail('render invoked'))
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: pytest.fail('LLM invoked'))
    slide = project.slides[0]
    slide.narration = 'There are 72 residents.'
    storyboard.apply(project, {'paragraphs': {slide.id: {'cues': {
        'blocks': [{'block': 'number_slam', 'vars': {'value': 68}}]}}}})
    before = project.to_dict()
    sb = storyboard.build(project)
    assert sb['paragraphs'][0]['block_cues'] == slide.cues['blocks']
    sb['paragraphs'][0]['block_cues'][0]['vars']['value'] = 99
    assert slide.cues['blocks'][0]['vars']['value'] == 68
    findings = [f for f in check.run(project)['findings'] if f['code'] == 'number_match']
    assert len(findings) == 1 and findings[0]['level'] == 'P1'
    assert '72' in findings[0]['msg'] and '68' in findings[0]['msg']
    assert project.to_dict() == before
    with pytest.raises(ValueError, match='No such block'):
        storyboard.apply(project, {'paragraphs': {slide.id: {'cues': {'blocks': [{'block': 'missing'}]}}}})
    assert project.to_dict() == before
    storyboard.apply(project, {'paragraphs': {slide.id: {'cues': {'blocks': []}}}})
    assert 'blocks' not in slide.cues


@pytest.mark.parametrize('failures', [0, 1, 3])
def test_describe_block_retries_and_storage(library, monkeypatch, failures):
    from copy import deepcopy
    from app import block_authoring as kit, block_creation, llm
    root = kit.new('receipt')
    meta = json.loads((root / 'block.json').read_text())
    meta.update(budget=0, duration=dict(mode='range', min=1, max=10))
    original = (root / 'block.html').read_text()
    if failures == 0:
        (blocks.USER_DIR / 'receipt-2').mkdir()  # Even empty existing ids are reserved.
    calls, checked = [], []
    def complete(prompt, **kwargs):
        calls.append(prompt)
        assert kwargs['retries'] == 0
        llm._record_usage('mock-model', {'input_tokens': 20, 'output_tokens': 10})
        return {'block.html': kit.TEMPLATE, 'block.json': deepcopy(meta)}
    def check(ref, *, report):
        assert ref not in {key for key in blocks.discover() if not key.startswith('user/draft_')}
        checked.append(ref)
        for aspect in meta['aspects']:
            report(aspect, dict(captured_frames=0, layers=1, passes=1))
        return ['title: text overflow'] if len(checked) <= failures else []
    monkeypatch.setattr(llm, 'complete_json', complete)
    monkeypatch.setattr(kit, 'lint', lambda ref: [])
    monkeypatch.setattr(kit, 'check', check)
    result = block_creation.describe('A receipt with a total')
    assert len(calls) == min(failures + 1, 3)
    assert (root / 'block.html').read_text() == original
    if failures == 3:
        assert result['id'] is None and result['errors'] == ['title: text overflow']
        assert list(blocks.USER_DIR.iterdir()) == [root]
    else:
        assert result['id'] == ('user/receipt-3' if failures == 0 else 'user/receipt-2')
        saved = blocks.discover()[result['id']]['meta']
        assert saved['origin']['description'] == 'A receipt with a total'
        assert saved['origin']['model'] == llm.MODEL_SCRIPT
        assert len(saved['origin']['token_usage']) == len(calls)
        assert saved['origin']['created_at']
        if failures:
            assert 'title: text overflow' in calls[1]
    assert blocks.STAGED.get() == ()


@pytest.mark.parametrize('stats', [dict(captured_frames=1, layers=1, passes=1),
                                    dict(captured_frames=0, layers=13, passes=1),
                                    dict(captured_frames=0, layers=1, passes=2), {}])
def test_describe_builder_budget_rejection(library, monkeypatch, stats):
    from app import block_authoring as kit, block_creation, llm
    root = kit.new('source')
    meta = json.loads((root / 'block.json').read_text())
    meta.update(id='generated', budget=0, duration=dict(mode='range', min=1, max=10))
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: {'block.html':kit.TEMPLATE, 'block.json':meta.copy()})
    def check(ref, *, report):
        for aspect in meta['aspects']:
            report(aspect, stats)
        return []
    monkeypatch.setattr(kit, 'check', check)
    monkeypatch.setattr(kit, 'lint', lambda ref: [])
    result = block_creation.describe('A small panel')
    assert result['id'] is None and any('builder' in e for e in result['errors'])
    assert not (blocks.USER_DIR / 'generated').exists()


@pytest.mark.parametrize('payload', [
    '{% include "/etc/passwd" %}', '{% import "_base.html" as x %}',
    '{% macro x() %}bad{% endmacro %}', '{{ vars.__class__ }}',
    '{{ vars["__class__"] }}', '{{ width.__class__ }}', '{{ data.x.items() }}',
    '{{ cycler.__init__.__globals__ }}', '{% extends "cards/chapter.html" %}',
    '<script>alert(1)</script>', '<iframe src="data:text/html,bad"></iframe>',
    '<style/><!--</style><script>alert(1)</script>-->',
    '<img src="/fonts/a.ttf" onerror="alert(1)">', '<img src="file:///etc/passwd">',
    '<img src="//evil.test/a.png">', '<img src="/static/private.png">',
    '<img src="data:image/svg+xml;base64,PHN2Zz4=">',
    '<style>div{background:url(/scene/{token}/assets/../private.png)}</style>',
    '<style>@import "https://evil.test/a.css";</style>',
    r'<style>div{background:u\72l(https://evil.test/a)}</style>',
    '<div data-composition-src="/static/evil.html"></div>',
    '<img data-var-src="title" src="/fonts/a.ttf">',
])
def test_user_block_sandbox(library, monkeypatch, payload):
    from app import block_authoring as kit
    root = kit.new('unsafe')
    source = '{% extends "_base.html" %}{% block body %}' + payload + '{% endblock %}'
    (root / 'block.html').write_text(source)
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **k: pytest.fail('render invoked'))
    with pytest.raises((ValueError, __import__('jinja2').TemplateError)):
        blocks.render('user/unsafe')


def test_block_creation_routes_and_channel_persistence(library, monkeypatch):
    from app import main, jobs, channels, block_creation
    from app.schema import Channel
    monkeypatch.setattr(channels, 'CHANNELS_DIR', library / 'channels')
    channels.save(Channel(id='ctest', name='Test'))
    add_block(blocks.USER_DIR / 'mine')
    assert main.add_channel_block('ctest', {'id':'user/mine'})['blocks'] == ['user/mine']
    main.add_channel_block('ctest', {'id':'user/mine'})
    assert channels.load('ctest').blocks == ['user/mine']
    assert Channel.from_dict({'id':'old', 'name':'Old', 'unknown':1}).blocks == []
    result = dict(id='user/mine', errors=[], usage=[])
    monkeypatch.setattr(block_creation, 'describe', lambda *a: result)
    monkeypatch.setattr(jobs, 'start', lambda kind, pid, fn: (kind, pid, fn(lambda m: None)))
    assert main.describe_block({'description':'My panel'})['job'] == ('create block', '', result)
    assert any(b['id'] == 'user/mine' for b in main.list_blocks())


def test_usage_capture_reads_provider_envelope(monkeypatch):
    from app import llm
    payload = dict(result='{}', usage=dict(input_tokens=12, output_tokens=7))
    monkeypatch.setattr(llm.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=json.dumps(payload)))
    with llm.capture_usage() as usage:
        assert llm._complete_cli('mock', '', 'mock-model', 1, False) == '{}'
        with llm.capture_usage() as nested:
            llm._record_usage('nested', {'output_tokens':1})
        assert nested == [dict(model='nested', usage={'output_tokens':1})]
    assert usage == [dict(model='mock-model', usage=payload['usage'])]


def test_user_media_paths_are_confined_and_normalized(library):
    from app import block_authoring as kit
    root = kit.new('media')
    (root / 'picture.png').write_bytes(b'local asset')
    source = '{% extends "_base.html" %}{% block body %}<img data-media=\'picture.png\'>{% endblock %}'
    (root / 'block.html').write_text(source)
    template, ctx = blocks.prepare('user/media')
    assert f'data-media="{root}/picture.png"' in scenes.render_html(template, ctx)
    (root / 'picture.png').unlink()  # Only this test's disposable non-audio fixture.
    (library / 'private.png').write_bytes(b'private')
    (root / 'picture.png').symlink_to(library / 'private.png')
    with pytest.raises(ValueError, match='unsafe block resource'):
        scenes.render_html(template, ctx)


def test_generated_script_rejected_before_checker(library, monkeypatch):
    from app import block_authoring as kit, block_creation, llm
    root = kit.new('source')
    meta = json.loads((root / 'block.json').read_text())
    meta.update(id='malicious', budget=0, duration=dict(mode='range', min=1, max=10))
    source = kit.TEMPLATE.replace('{% block body %}', '{% block body %}<script>alert(1)</script>')
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: {'block.html':source, 'block.json':meta.copy()})
    monkeypatch.setattr(kit, 'check', lambda *a, **k: pytest.fail('unsafe code reached checker'))
    assert block_creation.describe('A panel')['id'] is None
    assert list(blocks.USER_DIR.iterdir()) == [root]


def test_user_block_sandbox_allows_plain_text_and_builder_attributes(library, monkeypatch):
    from app import block_authoring as kit
    root = kit.new('handles')
    (root / 'block.html').write_text(
        '{% extends "_base.html" %}{% block body %}<p class="clip" data-layer="a" data-start="0" '
        'data-duration="1" data-motion="rise" data-motion-duration="0.4" data-capture="frames">'
        'Follow @fieldnotes at https://field.example</p>{% endblock %}')
    rendered = []
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **k: rendered.append(1))
    blocks.render('user/handles', {'title': 'Visit https://field.example @fieldnotes'})
    assert rendered


def test_user_block_variable_rejects_css_resources(library, monkeypatch):
    from app import block_authoring as kit
    kit.new('vars')
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **k: pytest.fail('render invoked'))
    with pytest.raises(ValueError):
        blocks.render('user/vars', {'title': 'url(https://evil.test/a.png)'})

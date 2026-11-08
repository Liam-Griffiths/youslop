"""Legacy projects remain checkable/renderable without any catalog cache."""
import json

import jinja2
import pytest

from app import check, cli, main, scenes, settings, stage
from app.retired_catalog import placeholder
from app.schema import Project, Slide


LEGACY = '/catalog/unknown-block/component.html'


def test_legacy_project_placeholder_and_finding(tmp_path, monkeypatch):
    project = Project(id='pretired', idea='', slides=[Slide(
        id='slegacy', narration='A saved project.',
        cues={'legacy': {'source': LEGACY, 'vars': {'text': 'Keep this'}}},
        take={'path': 'takes/recorded.wav', 'duration': 3})])
    before = project.to_dict()
    template = tmp_path / 'mounted.html'
    template.write_text(
        '<html data-composition-id="test" data-width="1920" data-height="1080" '
        'data-duration="3"><div class="clip" data-start="0" data-duration="3" '
        'data-composition-src="{{ source }}"></div></html>')
    monkeypatch.setattr(scenes, 'env', jinja2.Environment(
        loader=jinja2.FileSystemLoader(tmp_path), autoescape=True))
    ctx = dict(source=project.slides[0].cues['legacy']['source'], width=1920, height=1080)
    # Actual scene cache preparation/lint resolves the missing mount without
    # touching the old data root. Only the expensive browser capture is mocked.
    def capture(path, *args, **kwargs):
        assert scenes.lint(path.read_text()) == []
        handler = object.__new__(stage._handler(stage._Run({}, None)))
        mounted = handler.translate_path(LEGACY)
        assert mounted == str(placeholder(LEGACY))
        html = placeholder(LEGACY).read_text()
        assert '<template>' in html and 'data-layer=' in html
        assert 'Catalog block retired' in html
        assert 'Choose a Corkbored block in Visuals.' in html
        return b'fixture png'
    monkeypatch.setattr(stage, 'capture_one', capture)
    assert scenes.capture(tmp_path, 'mounted.html', ctx, t=0, size=(480, 270)) == b'fixture png'
    findings = [f for f in check.run(project)['findings'] if f['code'] == 'retired_catalog']
    assert len(findings) == 1
    assert findings[0]['slide_id'] == 'slegacy'
    assert LEGACY in findings[0]['msg'] and 'Visuals' in findings[0]['msg']
    assert findings[0]['fix']['kind'] == 'none'  # No evidenced automatic mapping.
    assert project.to_dict() == before


@pytest.mark.parametrize('url', ['/catalog/../escape', '/catalog/%2e%2e/escape',
                                  '/catalog/_index/registry.json', '/catalog/a/../b',
                                  '/catalog/a\\b', '/catalog/'])
def test_unsafe_catalog_paths_remain_blocked(url):
    with pytest.raises(ValueError):
        placeholder(url)
    handler = object.__new__(stage._handler(stage._Run({}, None)))
    assert handler.translate_path(url) == '/nonexistent'


def test_old_settings_ignored_and_catalog_surfaces_removed(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'third_party_blocks': 'on', 'user_agent': 'Creator'}))
    monkeypatch.setattr(settings, 'path', lambda: path)
    assert settings.load_file() == {'user_agent': 'Creator'}
    assert 'third_party_blocks' not in settings.FIELDS_BY_KEY
    assert '/api/blocks/third-party' not in {route.path for route in main.app.routes}
    with pytest.raises(SystemExit) as exc:
        cli.main(['catalog', 'list'])
    assert exc.value.code == 2
    assert 'invalid choice' in capsys.readouterr().err


def test_local_composition_mount_compatibility():
    # Keep the non-catalog contract: variables, paused timelines and the mount
    # shim fixtures continue to lint, without the retired fetcher dependency.
    html = scenes.render_html('_test/static.html', {})
    assert scenes.lint(html) == []
    component = scenes.SCENE_DIR / '_test/component.html'
    assert scenes.lint_component(component.read_text(), component.parent) == []
    assert 'data-composition-variables' in component.read_text()
    assert 'window.__timelines' in component.read_text()
    assert 'window.__hyperframes.getVariables()' in component.read_text()

"""Reviewer-only speed check. Baseline replays the same plates through ffmpeg."""
import json
import os
import time

import jinja2
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('YS_VISUAL') != '1', reason='set YS_VISUAL=1')


def test_scene_speed(tmp_path, monkeypatch, record_property, capsys):
    from app import scene_builder as b, scenes
    template = '''{% extends '_base.html' %}
    {% block body %}{% for i in range(40) %}
    <div data-layer="l{{i}}" data-start="{{i * 0.1}}" data-duration="{{60-i*0.1}}"
      data-motion="rise" data-motion-duration="{{1 if i == 0 else 0.6}}"
      {% if i == 0 %}data-capture="frames"{% endif %}
      style="position:absolute;left:{{(i%8)*230}}px;top:{{(i//8)*190}}px;
      width:200px;height:120px;color:#eee;font:40px Inter">Layer {{i}}</div>
    {% endfor %}{% endblock %}'''
    monkeypatch.setattr(scenes.env, 'loader', jinja2.ChoiceLoader([
        jinja2.DictLoader({'_speed.html': template}), scenes.env.loader]))
    ctx = scenes.context_base()
    # Camera is declared on the composition root, preserving the base contract.
    template = template.replace("{% block body %}", '''{% block script %}<script>
    document.documentElement.dataset.camera = '[{"t":0,"zoom":1},{"t":60,"zoom":1.2,"x":100,"y":50}]';
    </script>{% endblock %}{% block body %}''')
    monkeypatch.setattr(scenes.env, 'loader', jinja2.ChoiceLoader([
        jinja2.DictLoader({'_speed.html': template}), scenes.env.loader]))
    args = dict(seconds=60, size=(480,270), fps=30, crf=28)
    started = time.monotonic()
    result = b.render(tmp_path, '_speed.html', ctx, tmp_path/'scene.mp4', **args)
    elapsed = time.monotonic()-started
    manifest = next((tmp_path/'scenes').glob('*.layers.json'))
    plates = json.loads(manifest.read_text())
    monkeypatch.setattr(b, '_plates', lambda *args: plates)
    started = time.monotonic()
    b.render(tmp_path, '_speed.html', ctx, tmp_path/'baseline.mp4', **args)
    baseline = time.monotonic()-started
    report = dict(seconds=elapsed, baseline_seconds=baseline, **result.stats)
    record_property('scene_speed', json.dumps(report))
    with capsys.disabled():
        print(json.dumps(report, sort_keys=True))
    assert result.stats['captures'] == 71  # 40 layers + ground + 30 window frames
    assert result.stats['captured_frames'] == 30
    assert elapsed < 3*baseline, report

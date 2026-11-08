"""Graphics use the voice clock and keep full-frame block cues independent."""
import pytest

from app import block_overlays as overlays, blocks, edits, render, scene_builder, storyboard
from app.schema import Slide


def item(**changes):
    return dict(id='name', block_id='lower_third_panel', vars={}, at=1., dur=3., **changes)


def voiced():
    return dict(duration=8, words=[dict(w='Hello,', start=2., end=2.4, src='est'),
                                  dict(w='HELLO!', start=5., end=5.4, src='est')])


def test_schema_and_edits(project):
    slide = Slide.from_dict({'narration': 'Old project', 'unknown': True})
    assert slide.overlays == Slide.from_dict(slide.to_dict()).overlays == []
    slide.take = voiced()
    edits.add_overlay(slide, item())
    edits.update_overlay(slide, 'name', {'at': 2})
    assert slide.overlays[0]['at'] == 2
    edits.remove_overlay(slide, 'name')
    assert not slide.overlays
    with pytest.raises(edits.EditError):
        edits.remove_overlay(slide, 'missing')
    slide = project.slides[0]
    slide.take = voiced()
    storyboard.apply(project, {'paragraphs': {slide.id: {'overlays': [item()]}}})
    assert storyboard.build(project)['paragraphs'][0]['overlays'] == slide.overlays
    assert project.to_dict()['slides'][0]['overlays'] == slide.overlays


@pytest.mark.parametrize('patch', [dict(at=float('nan')), dict(dur=0), dict(at=True),
    dict(dur=31), dict(block_id='number_slam'), dict(block_id='callout_arrow'),
    dict(position='nowhere'), dict(vars={'title': 'W'*49}), dict(by='other'), dict(on=42)])
def test_validation(patch):
    with pytest.raises(ValueError):
        overlays.validate(voiced(), [{**item(), **patch}])


def test_bounds_ids_and_anchors():
    with pytest.raises(ValueError):
        overlays.validate(voiced(), [item()]*2)
    with pytest.raises(ValueError):
        overlays.validate(voiced(), [{**item(), 'id': str(i)} for i in range(9)])
    # Stored as written (no take clipping: planned-before-recording overlays survive);
    # clipped to the paragraph's length only when resolved.
    assert overlays.validate({}, [{**item(), 'at': 9}])[0]['at'] == 9
    assert overlays.resolved(voiced(), [{**item(), 'at': 9}]) == []
    assert overlays.resolved({}, [{**item(), 'at': 1}], length=3.0)[0]['dur'] == 2
    with pytest.raises(ValueError):
        overlays.validate(voiced(), [{**item(), 'at': -1}])
    raw = [item(on='hello'), {**item(on='hello'), 'id': 'second'},
           {**item(on='absent'), 'id': 'fallback'}]
    resolved = overlays.resolved(voiced(), raw)
    assert [o['at'] for o in resolved] == [2, 5, 1]
    assert [o['src'] for o in resolved] == ['est', 'est', 'user']
    assert raw[0]['at'] == 1


def test_transparent_clip_and_positions(project, monkeypatch):
    captured = []
    def fake_render(owner, template, ctx, out, **kwargs):
        captured.append((ctx, out, kwargs))
        out.write_bytes(b'cached')
    monkeypatch.setattr(scene_builder, 'render', fake_render)
    clean = overlays.validate(voiced(), [{**item(), 'position': 'top_right'}])[0]
    out = overlays.clip(project, clean, (480, 270), 15)
    assert out.suffix == '.mov'
    assert captured[0][0]['builder_alpha'] is True
    from app import scenes
    html = scenes.render_html(blocks.prepare('lower_third_panel')[0], captured[0][0])
    assert 'background:transparent!important' in html and 'left:30%;right:12%' in html
    overlays.clip(project, clean, (480, 270), 15)
    assert len(captured) == 1
    _, base = blocks.prepare('lower_third_panel')
    assert not base.get('builder_alpha')


def test_keys_and_graphics(project, monkeypatch):
    slide = project.slides[0]
    slide.take = voiced()
    groups = render._picture_groups(project, render._slide_durations(project, False))
    monkeypatch.setattr(render, '_segment_graph', lambda *a, **k: ([], 'null[v]', '[v]'))
    monkeypatch.setattr(render.ffutil, 'h264', lambda *a, **k: ([], '', []))
    settings = dict(seg_len=9, op='set', channel=None, chapter=None, size=(480,270),
                    fps=15, dip_out=False, camera_index=0, last_line=False, crf=18, preset='veryfast')
    segment_before = render._segment_key(project, groups[0], settings)
    before = render._proxy_key(project, groups, 0, None)
    edits.add_overlay(slide, item())
    after = render._proxy_key(project, groups, 0, None)
    assert before != after
    segment_after = render._segment_key(project, groups[0], settings)
    assert segment_before != segment_after
    monkeypatch.setattr(render, '_block_versions', lambda s: ['edited-block'])
    assert render._proxy_key(project, groups, 0, None) != after
    assert render._segment_key(project, groups[0], settings) != segment_after
    row = render.timeline(project)['layers']['graphics'][0]
    assert row['id'] == 'name' and row['kind'] == 'overlay'
    assert row['t1'] - row['t0'] == pytest.approx(3)
    assert row['t0'] == pytest.approx(1.6)


def test_block_base_and_overlay(project, monkeypatch, tmp_path):
    slide = project.slides[0]
    slide.take, slide.overlays = voiced(), [item()]
    slide.cues['blocks'] = [dict(block='lower_third_rule', vars={})]
    seen = []
    def fake_render(owner, template, ctx, out, **kw):
        seen.append((template, ctx.get('builder_alpha', False)))
        out.write_bytes(b'base')
    monkeypatch.setattr(scene_builder, 'render', fake_render)
    monkeypatch.setattr(overlays, 'clip', lambda *a, **k: tmp_path/'overlay.mov')
    commands = []
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: commands.append(args))
    render._render_segment(project, [(slide, 8)], 9, 0, tmp_path/'out.mp4', size=(480,270), fps=15)
    assert seen == [('_blocks/lower_third_rule/block.html', False)]
    assert any('-filter_complex_script' in c for c in commands)
    assert slide.overlays and slide.cues['blocks']


def test_api_and_cli(project, monkeypatch, tmp_path, capsys):
    import json
    from argparse import Namespace
    from app import cli, main, store
    slide = project.slides[0]
    slide.take = voiced()
    monkeypatch.setattr(main, '_load', lambda pid: project)
    monkeypatch.setattr(store, 'load', lambda pid: project)
    monkeypatch.setattr(store, 'save', lambda p: None)
    monkeypatch.setattr(cli, '_guard_write', lambda: None)
    assert main.patch_slide(project.id, slide.id, {'overlays': [item()]})['overlays']
    patch = tmp_path/'patch.json'
    patch.write_text(json.dumps({'paragraphs': {slide.id: {'overlays': []}}}))
    cli.cmd_apply(Namespace(pid=project.id, patch=str(patch)))
    assert not slide.overlays
    assert json.loads(capsys.readouterr().out) == ['overlays']


def test_script_compatibility(monkeypatch):
    from app import ffutil
    calls = []
    def fake_run(args, **kw):
        calls.append(args)
        if '-filter_complex_script' in args:
            raise ffutil.FFError("Unrecognized option 'filter_complex_script'")
    monkeypatch.setattr(ffutil, 'run', fake_run)
    overlays.run_graph(['-filter_complex_script', 'graph.ffgraph', 'out.mp4'], threads=2)
    assert calls[1] == ['-filter_complex_threads', '2', '-/filter_complex', 'graph.ffgraph', 'out.mp4']

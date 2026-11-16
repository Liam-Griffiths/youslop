"""Media graphs and ownership without rendering, downloading or touching recordings."""
from copy import deepcopy
from pathlib import Path

import pytest

from app import block_overlays, edits, layers, media_overlays as media, render, store
from app.schema import Layer, Project


def item(**patch):
    return {**dict(id='inset', type='media', source={'source_slide': 'source', 'candidate_id': 'c'},
                   at=1, dur=2, box=dict(x=.65, y=.05, w=.3, h=.3)), **patch}


@pytest.fixture
def owned(project, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    path = store.project_dir(project.id) / 'media' / 'source.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'local-source')
    slide = project.slides[0]
    slide.id = 'source'
    slide.take = dict(duration=8, path='takes/kept.wav')
    slide.candidates.append(dict(id='c', kind='image', local_path='media/source.png'))
    return project, slide, path


def test_round_trip_and_validation(owned):
    p, s, _ = owned
    edits.add_overlay(s, item(unknown='ignored'))
    clean = s.overlays[0]
    assert clean['volume'] == clean['in'] == 0
    assert Project.from_dict(p.to_dict()).slides[0].overlays == [clean]
    assert s.take['path'] == 'takes/kept.wav'
    for patch in [dict(source={'path': '/etc/passwd'}), dict(at=-1), dict(dur=0),
                  dict(volume=2), dict(fade_in=float('nan')), {'in': True},
                  dict(box=dict(x=.9, y=0, w=.3, h=.3)), dict(fit='stretch')]:
        with pytest.raises(ValueError):
            block_overlays.validate(s.take, [item(**patch)])
    assert block_overlays.resolved(s.take, [item(at=7)])[0]['dur'] == 1


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_graph_goldens(owned, kind, monkeypatch):
    p, s, path = owned
    s.candidates[-1].update(kind=kind, duration=9)
    raw = item(**{'in': .75}, fit='contain', volume=.4)
    s.overlays = block_overlays.validate(s.take, [raw])
    monkeypatch.setattr(render.ffutil, 'run', lambda *a, **k: pytest.fail('must not render'))
    inputs, graph, last = block_overlays.compose(p, [(s, 8)], ['-i', 'base.mp4'],
        '[0:v]null[base]', '[base]', (480, 270), 15, prepare_only=True)
    assert last == '[mo0]' and inputs.count('-i') == 2
    golden = Path(__file__).parents[1] / 'golden' / f'media_{kind}.ffgraph'
    assert graph+'\n' == golden.read_text()
    assert '-stream_loop' not in inputs and '-loop' not in inputs
    if kind == 'image':
        assert graph.index('scale=') < graph.index(render.HOLD_STILL)
    else:
        assert inputs[inputs.index('-ss')+1] == '0.750000'
        assert inputs[inputs.index('-t')+1] == '2.000000'
    hidden = block_overlays.compose(p, [(s, 8)], [], 'null[base]', '[base]',
                                   (480, 270), 15, hide={'media'})
    assert hidden == ([], 'null[base]', '[base]')


def test_layer_order_locks_and_cache(owned, monkeypatch, tmp_path):
    p, s, path = owned
    block = dict(id='g', block_id='lower_third_panel', vars={}, at=0, dur=2)
    s.overlays = block_overlays.validate(s.take, [item(layer='m'), block])
    p.layers = [Layer(id='m', role='media', order=0), Layer(id='g', role='graphics', order=1)]
    monkeypatch.setattr(block_overlays, 'clip', lambda *a, **k: tmp_path/'block.mov')
    assert layers.graphics_order(p, [(s, 8)]) == [(0, 0), (0, 1)]
    p.layers.reverse()
    for i, track in enumerate(p.layers):
        track.order = i
    assert layers.graphics_order(p, [(s, 8)]) == [(0, 1), (0, 0)]
    spans = render.timeline(p)['layers']
    assert spans['media'][0]['kind'] == 'media' and spans['graphics'][0]['id'] == 'g'
    p.layers[-1].locked = True
    changed = Project.from_dict(p.to_dict())
    changed.slides[0].overlays[0]['box']['x'] = .6
    with pytest.raises(layers.LockedLayerError):
        layers.assert_unlocked(p, changed)
    changed = Project.from_dict(p.to_dict())
    changed.slides[0].overlays[1]['at'] = 1  # Media lock doesn't lock blocks.
    layers.assert_unlocked(p, changed)
    before = media.cache_state(p, s)
    path.write_bytes(b'changed-local-source')
    assert before != media.cache_state(p, s)
    s.candidates[-1]['local_path'] = '../outside.png'
    with pytest.raises(ValueError, match='inside the project'):
        media.cache_state(p, s)


def test_audio_level_range_and_visibility(owned, monkeypatch):
    from app import audio
    p, s, _ = owned
    s.candidates[-1].update(kind='video', duration=9)
    s.overlays = block_overlays.validate(s.take, [item(volume=.4, **{'in': .75})])
    captured = []
    monkeypatch.setattr(audio.ffutil, 'run', lambda args, **kw: captured.append(args))
    monkeypatch.setattr(audio.ffutil, 'duration', lambda *a: 9)
    monkeypatch.setattr(audio.ffutil, 'has_audio', lambda *a: True)
    original = deepcopy(s.take)
    audio.build_slice(p, [s], Path('/tmp/unused-media-test.wav'), head=.6)
    inputs = captured[-1]
    graph = inputs[inputs.index('-filter_complex')+1]
    assert 'volume=0.400000,volume=-17.5dB' in graph
    assert 'adelay=1600|1600' in graph and 'normalize=0' in graph
    assert inputs[inputs.index('-ss')+1] == '0.750000'
    audio.build_slice(p, [s], Path('/tmp/unused-media-test.wav'), head=.6, hide={'voice'})
    assert ',volume=0[nar0]' in captured[-1][captured[-1].index('-filter_complex')+1]
    audio.build_slice(p, [s], Path('/tmp/unused-media-test.wav'), head=.6, hide={'media'})
    assert 'ma0_' not in captured[-1][captured[-1].index('-filter_complex')+1]
    assert s.take == original


def test_owned_materials_library_and_clip_bounds(owned, monkeypatch):
    from app import library, project_bin
    from app.schema import BinItem
    p, s, path = owned
    monkeypatch.setattr(library, 'get', lambda ident: dict(kind='video', duration=6))
    monkeypatch.setattr(library, 'file_path', lambda ident: path)
    monkeypatch.setattr(project_bin, 'file_path', lambda *args: path)
    p.bin = [BinItem(id='b', kind='image', source='dropped', file='bin/pic.png')]
    clean = block_overlays.validate({}, [item(source={'asset_id': 'lib'}, **{'in': 5})])[0]
    assert media.source(p, clean) == (path, 'video', 0, 6)
    inputs, graph, _ = media.compose(p, clean, [], 'null[v]', '[v]', (480,270), 15, 1, 'm')
    assert inputs[inputs.index('-t')+1] == '1.000000'  # No looping past the owned range.
    with pytest.raises(ValueError, match='outside the clip'):
        media.source(p, dict(clean, **{'in': 6}))
    clean['source'] = {'bin_id': 'b'}
    assert media.source(p, clean) == (path, 'image', 0, 0)
    # New dependencies invalidate the proxy key independently of stored IDs.
    s.overlays = [clean]
    groups = render._picture_groups(p, render._slide_durations(p, False))
    before = render._proxy_key(p, groups, 0, None)
    path.write_bytes(b'new-owned-bytes')
    assert before != render._proxy_key(p, groups, 0, None)


def test_patch_undo_preserves_recording(owned, monkeypatch):
    from app import main, undo
    p, s, _ = owned
    recording = store.project_dir(p.id) / s.take['path']
    recording.parent.mkdir(exist_ok=True)
    recording.write_bytes(b'kept recording')
    store.save(p)
    original = deepcopy(store.load(p.id).slides[0].take)
    monkeypatch.setattr(render, '_render_segment', lambda *a, **k: pytest.fail('placement rendered'))
    token = undo.edit_source.set(('add media', 'media-test'))
    try:
        main.patch_slide(p.id, s.id, {'overlays': [item()]})
    finally:
        undo.edit_source.reset(token)
    assert store.load(p.id).slides[0].overlays[0]['type'] == 'media'
    main.undo_project(p.id)
    assert not store.load(p.id).slides[0].overlays
    main.redo_project(p.id)
    assert store.load(p.id).slides[0].take == original
    assert recording.read_bytes() == b'kept recording'

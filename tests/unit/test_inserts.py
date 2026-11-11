"""Main-track inserts: isolated edits, render dispatch and real audio filters."""
from copy import deepcopy
import asyncio

import httpx
import pytest

from app import audio, check, edits, footage, inserts, main, render, script_gen, store, storyboard, undo
from app.schema import Project, Slide, group_slides


@pytest.fixture
def cut(project, tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'shoots')
    original = tmp_path / 'source.mp4'
    original.write_bytes(b'original; never encode this fixture')
    footage._save(footage.Shoot('shoot', files=[footage.SourceFile('source', str(original),
        duration=20, audio=[dict(channels=1)])]))
    project.style.format = 'kenburns'
    project.style.picture_every = 1
    store.save(project)
    stamp = original.stat().st_mtime_ns
    yield project
    assert original.read_bytes() == b'original; never encode this fixture'
    assert original.stat().st_mtime_ns == stamp


CLIP = dict(kind='clip', shoot_id='shoot', source_id='source', in_s=2, out_s=6)


def test_roundtrip_defaults_and_isolation(cut):
    old = cut.to_dict()
    assert all('insert' not in row for row in old['slides'])
    assert not Slide.from_dict(dict(id='old', future=True, insert=None)).insert
    row, after = inserts.prepare(cut, CLIP | {'after': 's1'})
    inserts.place(cut, row, after)
    raw = cut.to_dict()
    loaded = Project.from_dict(raw)
    loaded.slide(row.id).insert['source_audio'] = True
    assert raw['slides'][1]['insert']['source_audio'] is False
    assert cut.slide(row.id).narration == '' and not cut.slide(row.id).take
    assert cut.est_seconds() - Project.from_dict(old).est_seconds() == pytest.approx(4)
    assert render._slide_durations(cut, False)[1] == (row, 4)
    assert (row.id, 4) in audio.slide_durations(cut)


@pytest.mark.parametrize('fmt', ['kenburns', 'essay', 'loudmouth'])
def test_four_second_ripple_and_attached_anchors(cut, fmt):
    cut.style.format = fmt
    second = cut.slides[1]
    second.title_at, second.title_hold = .8, 1.2
    second.overlays = [dict(id='graphic', block_id='lower_third_panel', vars={}, at=.3, dur=1)]
    second.cues = {'loudmouth': [dict(kind='shout', text='Anchored', at=.4)]}
    before = render.timeline(cut)
    gap_before = audio.gap_map(cut)
    anchors = deepcopy(second.to_dict())
    row, after = inserts.prepare(cut, CLIP | {'after': 's1'})
    inserts.place(cut, row, after)
    after_tl = render.timeline(cut)
    def paras(tl):
        return {p['id']: p for seg in tl['segments'] for p in seg['paragraphs']}
    old, new = paras(before), paras(after_tl)
    assert after_tl['total'] - before['total'] == pytest.approx(4)
    assert new['s1']['start'] == old['s1']['start']
    for sid in ('s2', 's3'):
        assert new[sid]['start'] - old[sid]['start'] == pytest.approx(4)
        assert audio.gap_map(cut)[sid] == gap_before[sid]
    assert new['s2']['timing']['title_at']['start'] - old['s2']['timing']['title_at']['start'] == pytest.approx(4)
    assert cut.slide('s2').to_dict() == anchors
    for lane in ('graphics', 'cues'):
        for old_item in before['layers'][lane]:
            if old_item['sid'] == second.id:
                item = next(x for x in after_tl['layers'][lane] if x['id'] == old_item['id'])
                assert item['t0'] - old_item['t0'] == pytest.approx(4)
                assert item['t1'] - old_item['t1'] == pytest.approx(4)
    assert new[row.id]['duration'] == 4 and new[row.id]['spoken'] == 0
    assert not new[row.id]['recorded'] and new[row.id]['word_times'] == []
    assert audio.gap_map(cut)[row.id] == 0
    sb = storyboard.build(cut)
    assert next(p for p in sb['paragraphs'] if p['id'] == row.id)['label'] == 'Insert · clip · 4.0 s'
    assert not any(f['slide_id'] == row.id and f['code'] == 'empty_narration'
                   for f in check.script(cut)['findings'])
    assert not any('not recorded' in problem for seg in after_tl['segments']
                   if seg['lead'] == row.id for problem in seg['problems'])
    # Both sides break a picture run, even with explicit holds.
    for s in cut.slides:
        s.picture_mode = 'hold'
    assert [[s.id for s in g] for g in group_slides(cut.slides, 8)] == [
        ['s1'], [row.id], ['s2', 's3']]


@pytest.mark.parametrize('patch', [dict(after='missing'), dict(after=None), dict(in_s=True), dict(in_s=None),
    dict(out_s=float('nan')), dict(in_s=6), dict(out_s=21), dict(source_audio='yes'),
    dict(seconds=3), dict(extra=True), dict(source_id='missing')])
def test_rejected_edits_never_publish(cut, patch):
    path = store.project_dir(cut.id) / 'project.json'
    before = path.read_bytes()
    with pytest.raises(main.HTTPException) as exc:
        main.add_insert(cut.id, CLIP | patch)
    assert exc.value.status_code == 400 and path.read_bytes() == before
    assert not undo.read(path.parent)['states']


def test_create_patch_move_delete_undo(cut):
    added = main.add_insert(cut.id, CLIP | {'after': 's1'})
    sid = added['slides'][1]['id']
    changed = main.patch_insert(cut.id, sid, dict(out_s=8, source_audio=True, after='intro'))
    assert changed['slides'][0]['insert']['seconds'] == 6
    assert changed['slides'][0]['insert']['source_audio'] is True
    main.undo_project(cut.id)
    assert store.load(cut.id).slides[1].insert['seconds'] == 4
    main.redo_project(cut.id)
    assert store.load(cut.id).slides[0].id == sid
    with pytest.raises(main.HTTPException):
        main.patch_insert(cut.id, sid, dict(after=sid))
    main.delete_insert(cut.id, sid)
    assert not store.load(cut.id).slide(sid)
    main.undo_project(cut.id)
    assert store.load(cut.id).slide(sid).insert['seconds'] == 6
    with pytest.raises(main.HTTPException):
        main.delete_insert(cut.id, 's1')


def test_http_edit_label_and_no_narration_routes(cut, monkeypatch):
    # Match test_undo: sandbox threadpool wakeups can stall ASGI tests.
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                    base_url='http://127.0.0.1') as client:
            response = await client.post(f'/api/projects/{cut.id}/inserts', json=CLIP,
                                        headers={'X-Edit-Label': 'Insert source range'})
            assert response.status_code == 200
            sid = response.json()['slides'][0]['id']
            response = await client.post(f'/api/projects/{cut.id}/slides/{sid}/rewrite',
                                         json={'instruction': 'Never call a model'})
            assert response.status_code == 400
    monkeypatch.setattr(script_gen, 'complete_json', lambda *a, **k: pytest.fail('model called'))
    asyncio.run(run())
    assert undo.read(store.project_dir(cut.id))['states'][-1]['label'] == 'Insert source range'


def test_other_kinds_and_rejected_insert_rewrite(cut, monkeypatch, tmp_path):
    from app import blocks, library
    path = tmp_path / 'picture.png'
    path.write_bytes(b'library fixture')
    monkeypatch.setattr(library, 'get', lambda ident: dict(kind='image') if ident == 'picture' else None)
    monkeypatch.setattr(library, 'file_path', lambda ident: path if ident == 'picture' else None)
    monkeypatch.setattr(blocks, 'discover', lambda: {'example': dict(meta=dict(aspects=['16:9'],
        variables={'headline': dict(type='text', default='Hello', max_length=10)}))})
    for payload in [dict(kind='card', text='A card', seconds=4),
                    dict(kind='picture', asset_id='picture', seconds=4),
                    dict(kind='block', block='example', vars={'headline': 'Hi'}, seconds=4)]:
        row, _ = inserts.prepare(cut, payload)
        assert row.insert['seconds'] == 4
    for payload in [dict(kind='card', text='', seconds=4),
                    dict(kind='picture', asset_id='missing', seconds=4),
                    dict(kind='block', block='example', vars={'unknown': 1}, seconds=4),
                    dict(kind='card', text='Card', seconds=True)]:
        with pytest.raises(ValueError):
            inserts.prepare(cut, payload)
    row, after = inserts.prepare(cut, CLIP)
    inserts.place(cut, row, after)
    with pytest.raises(edits.EditError):
        edits.patch_slide_fields(row, {'narration': 'Cannot speak this'})
    with pytest.raises(ValueError):
        script_gen.rewrite_slide(cut, row, 'rewrite')


def test_insert_range_handles_and_missing_sources(cut, monkeypatch, tmp_path):
    row, after = inserts.prepare(cut, CLIP)
    inserts.place(cut, row, after)
    monkeypatch.setattr(render, '_cover_crop', lambda *a: ('null', None))
    groups = render._groups_for_preview(cut)
    _, transition, length = render._segment_timing(cut, groups, 0)
    args, graph, _ = render._segment_graph(cut, groups[0], length, 'set', size=(480, 270), fps=15)
    assert args[:4] == ['-ss', '2.000000', '-t', '4.000000']
    assert f'start_duration={transition/2 + render.HEAD_PAD:.6f}' in graph
    assert 'setpts=PTS-STARTPTS' in graph and 'fps=15' in graph
    assert 'setpts=1.' not in graph and 'xfade=' not in graph
    original = inserts.source(row.insert)
    proxy = footage.shoot_dir('shoot') / 'proxies/source.mp4'
    proxy.parent.mkdir()
    proxy.write_bytes(b'proxy fixture')
    assert inserts.source(row.insert, preview=True) == proxy
    assert inserts.source(row.insert) == original
    # Use a separate manifest to simulate an offline original without touching it.
    shoot = footage.load('shoot')
    shoot.files[0].source_path = str(tmp_path / 'offline.mp4')
    footage._save(shoot)
    assert inserts.source(row.insert) == proxy
    is_file = type(proxy).is_file
    with monkeypatch.context() as m:
        m.setattr(type(proxy), 'is_file', lambda p: p != proxy and is_file(p))
        with pytest.raises(FileNotFoundError):
            inserts.source(row.insert)
    shoot.files[0].id = 'unavailable'
    footage._save(shoot)
    with pytest.raises(ValueError):
        inserts.source(row.insert)


def test_insert_cache_and_readiness(cut, monkeypatch):
    monkeypatch.setattr(render, 'pick_music', lambda *a: None)
    monkeypatch.setattr(render, '_cover_crop', lambda *a: ('null', None))
    row, after = inserts.prepare(cut, CLIP | dict(source_audio=True))
    inserts.place(cut, row, after)
    groups = render._groups_for_preview(cut)
    opts = dict(seg_len=render._segment_timing(cut, groups, 0)[2], op='set', channel=None,
        chapter=None, size=(480, 270), fps=15, dip_out=False, camera_index=0,
        last_line=False, crf=28, preset='ultrafast')
    def keys():
        return (render._proxy_key(cut, groups, 0, None),
                render._mix_key(cut, render._layout(cut)),
                render._segment_key(cut, groups[0], opts))
    before = keys()
    path = inserts.source(row.insert)
    import os
    stamp = path.stat().st_mtime_ns
    try:
        os.utime(path, ns=(stamp + 1, stamp + 1))
        assert all(a != b for a, b in zip(before, keys()))
    finally:
        os.utime(path, ns=(stamp, stamp))
    before = keys()
    row.insert.update(in_s=3, out_s=7)
    assert all(a != b for a, b in zip(before, keys()))
    before = keys()
    row.insert['source_audio'] = False
    assert all(a != b for a, b in zip(before, keys()))
    cut.slides = [row]
    lay = render._layout(cut)
    assert not render._mix_state(cut, lay)['audible']
    row.insert['source_audio'] = True
    state = render._mix_state(cut, lay)
    assert state['audible'] and not state['ready']


def test_card_picture_and_block_dispatch(cut, monkeypatch, tmp_path):
    from app import blocks, library, scene_builder
    monkeypatch.setattr(library, 'get', lambda ident: dict(kind='image'))
    monkeypatch.setattr(library, 'file_path', lambda ident: tmp_path / 'still.png')
    (tmp_path / 'still.png').write_bytes(b'fixture')
    monkeypatch.setattr(render.titles, 'render_chapter', lambda *a, **k: None)
    monkeypatch.setattr(render, '_cover_crop', lambda *a: ('null', None))
    monkeypatch.setattr(render, '_kenburns', lambda *a, **kw: 'null')
    calls = []
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: calls.append(args))
    for payload in [dict(kind='card', seconds=4, text='Title card'),
                    dict(kind='picture', seconds=4, asset_id='still')]:
        row, _ = inserts.prepare(cut, payload)
        cut.slides = [row]
        render._render_segment(cut, [(row, 4)], 6, 0, tmp_path / 'section.webm',
                               size=(480, 270), fps=15)
        assert calls[-1][calls[-1].index('-t') + 1] == '6.000'
        if payload['kind'] == 'card':
            assert any('_insert.png' in arg for arg in calls[-1])
    row = Slide(kind='kenburns', insert=dict(kind='block', seconds=4,
        block='lower_third_panel', vars={}))
    cut.slides = [row]
    prepared = []
    monkeypatch.setattr(blocks, 'prepare', lambda *a, **kw: (prepared.append(a) or ('template', {})))
    monkeypatch.setattr(scene_builder, 'render', lambda *a, **kw: prepared.append(kw))
    render._render_segment(cut, [(row, 4)], 5, 0, tmp_path / 'block.webm', size=(480, 270), fps=15)
    assert prepared[0][:2] == ('lower_third_panel', {})
    assert prepared[-1]['seconds'] == 5
    assert not row.cues


def test_insert_chapter_uses_own_seconds(cut, monkeypatch, tmp_path):
    row, after = inserts.prepare(cut, CLIP | dict(after='s1'))
    inserts.place(cut, row, after)
    before = render.timeline(cut)
    row.chapter, row.chapter_hold = 'Inserted chapter', 1.25
    after_tl = render.timeline(cut)
    assert after_tl['total'] == before['total']
    card = after_tl['layers']['chapters'][0]
    para = next(p for s in after_tl['segments'] for p in s['paragraphs'] if p['id'] == row.id)
    assert (card['t0'], card['t1']) == (para['start'], para['start'] + 1.25)
    assert render.chapter_card(cut, row) is None
    monkeypatch.setattr(render.titles, 'render_chapter', lambda *a, **k: None)
    monkeypatch.setattr(render, '_cover_crop', lambda *a: ('null', None))
    calls = []
    monkeypatch.setattr(render.ffutil, 'run', lambda args, **kw: calls.append(args))
    render._render_segment(cut, [(row, 4)], 5, 0, tmp_path / 'chapter.webm', size=(480, 270), fps=15)
    end = render._lead_overlap(cut, row) / 2 + 1.25
    assert len(calls) == 2 and f"overlay=enable='lt(t,{end:.6f})'" in calls[-1][calls[-1].index('-filter_complex')+1]


@pytest.mark.parametrize('sound', [False, True])
def test_real_insert_audio_range_and_silence(project, monkeypatch, tmp_path, sound):
    """Exercise ffmpeg's actual concat filters; no video render or model call."""
    import array
    import wave
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'shoots')
    original = tmp_path / 'source.wav'
    samples = array.array('h', (1000 * (1 + i // 48000) for i in range(8 * 48000)))
    with wave.open(str(original), 'wb') as stream:
        stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        stream.writeframes(samples.tobytes())
    footage._save(footage.Shoot('shoot', files=[footage.SourceFile('source', str(original),
        duration=8, audio=[dict(channels=1)])]))
    row, _ = inserts.prepare(project, CLIP | dict(source_audio=sound))
    second = Slide(insert=dict(kind='card', text='Silence', seconds=.5), kind='kenburns')
    project.slides = [row, second]
    project.style.format = 'kenburns'
    out = tmp_path / 'bed.wav'
    seconds = audio.build_narration(project, out, lead_in=.5)
    assert seconds == pytest.approx(.5 + render.HEAD_PAD + 4.5 + render.TAIL_PAD, abs=.001)
    with wave.open(str(out)) as stream:
        actual = array.array('h', stream.readframes(stream.getnframes()))
    lead = round((.5 + render.HEAD_PAD) * 48000)
    assert not any(actual[:lead])
    assert actual[lead:lead+4*48000] == (samples[2*48000:6*48000] if sound else array.array('h', [0]) * (4*48000))
    assert not any(actual[lead+4*48000:])
    assert not row.take and not row.takes


def test_insert_sponsor_and_spoken_alignment(cut, monkeypatch, tmp_path):
    import re
    from app.schema import SponsorSlot
    row, after = inserts.prepare(cut, CLIP | dict(after='s1', source_audio=True))
    inserts.place(cut, row, after)
    cut.sponsors = [SponsorSlot(id='read', after_slide_id=row.id,
        script='Sponsor', take=dict(path='sponsor.wav', duration=2))]
    calls = []
    monkeypatch.setattr(audio.ffutil, 'run', lambda args: calls.append(args))
    monkeypatch.setattr(audio.ffutil, 'duration', lambda path: 0)
    plan = render._slide_durations(cut, True)
    gaps = audio.gap_map(cut)
    fill = {s.id: d-gaps[s.id] for s, d in plan if not s.take}
    audio.build_narration(cut, tmp_path / 'bed.wav', lead_in=0, fill=fill)
    graph = calls[0][calls[0].index('-filter_complex')+1]
    branches = graph.split(';')[:-1]
    cursor = 0
    starts = {}
    for (s, d), branch in zip(plan, branches):
        delay = re.search(r'adelay=(\d+)\|', branch)
        cursor += int(delay[1])/1000 if delay else 0
        starts[s.id] = cursor
        pad = float(re.search(r'apad=pad_dur=([\d.]+)', branch)[1])
        cursor += d - gaps[s.id] + pad
    paras = [p for seg in render.timeline(cut)['segments'] for p in seg['paragraphs']]
    assert all(starts[p['id']] == pytest.approx(p['start'], abs=.001) for p in paras)
    assert starts['s2'] - starts[row.id] == 6
    assert 'sponsor.wav' not in ' '.join(calls[0])  # The read is mixed separately.


def test_insert_proxy_mux_hides_and_reuse(cut, monkeypatch, tmp_path):
    row, after = inserts.prepare(cut, CLIP | dict(after='s1', source_audio=True))
    inserts.place(cut, row, after)
    groups = render._groups_for_preview(cut)
    encoded, heads = [], []
    def picture(*args, **kwargs):
        encoded.append(kwargs['hide'])
        args[4].write_bytes(b'picture')
    def voice(project, slides, out, head):
        heads.append(head)
        out.write_bytes(b'audio')
    def mux(args):
        from pathlib import Path
        Path(args[-1]).write_bytes(b'mux')
    monkeypatch.setattr(render, '_render_segment', picture)
    monkeypatch.setattr(audio, 'build_slice', voice)
    monkeypatch.setattr(render.ffutil, 'run', mux)
    hide = frozenset({'graphics', 'chapters'})
    result = render._build_proxy(cut, groups, 1, lambda m: None, reuse=True, hide=hide)
    assert result['width'] == 480 and result['height'] == 270
    assert encoded == [hide] and heads == [render._lead_overlap(cut, row)/2]
    assert render._proxy_ready(cut, groups, 1, None, hide)
    assert render._build_proxy(cut, groups, 1, lambda m: None, reuse=True, hide=hide) == result
    assert len(encoded) == 1
    row.insert['source_audio'] = False
    assert not render._proxy_ready(cut, groups, 1, None, hide)
    def broken_voice(*a):
        raise render.ffutil.FFError('Unreadable insert audio')
    monkeypatch.setattr(audio, 'build_slice', broken_voice)
    with pytest.raises(render.ffutil.FFError, match='Unreadable insert audio'):
        render._build_proxy(cut, groups, 1, lambda m: None, reuse=True, hide=hide)

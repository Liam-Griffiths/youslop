"""Sponsor timing and assembly tests; no capture, render, or model calls."""
from copy import deepcopy
from pathlib import Path

import pytest

from app import audio, render, sponsors, storyboard, youtube
from app.schema import Project, Slide, SponsorSlot


@pytest.fixture
def cut():
    p = Project(id="sponsor-test", idea="test", use_intro=False, use_outro=False)
    p.style.picture_every = 1
    p.slides = [Slide(id=f"s{i}", narration=f"Paragraph {i}", chapter=f"Chapter {i}",
                      take={"path": f"takes/{i}.wav", "duration": 15.0}) for i in range(3)]
    return p


def slot(**kwargs):
    return SponsorSlot(id="read", script="A sponsor read", after_slide_id="s0",
                       take={"path": "takes/sponsor.wav", "duration": 6.0}, **kwargs)


def test_roundtrip_and_old_projects(cut):
    assert Project.from_dict({"id": "old", "idea": "old", "unknown": True}).sponsors == []
    cut.sponsors = [slot()]
    data = cut.to_dict()
    data["sponsors"][0]["future"] = True
    restored = Project.from_dict(data)
    assert restored.sponsors == cut.sponsors
    assert restored.style.sponsor_music_db == -6
    old = deepcopy(restored.sponsors[0].take)
    restored.sponsors[0].set_take({"path": "takes/new.wav", "duration": 5})
    assert restored.sponsors[0].history[0]["path"] == old["path"]
    assert Project.from_dict(restored.to_dict()).sponsors[0].history


def test_mid_timeline_storyboard_and_chapters(cut):
    original = render.timeline(cut)
    before, _ = youtube.chapter_points(cut)
    cut.sponsors = [slot()]
    tl = render.timeline(cut)
    assert [s["type"] for s in tl["segments"]] == ["picture", "sponsor", "picture", "picture"]
    assert tl["segments"][1]["start"] == original["segments"][1]["start"]
    assert tl["total"] == original["total"] + 6
    for old, new in zip(original["segments"][1:], tl["segments"][2:]):
        assert new["start"] == old["start"] + 6
        assert new["paragraphs"][0]["timing"]["title_at"]["start"] == old["paragraphs"][0]["timing"]["title_at"]["start"] + 6
    board = storyboard.build(cut)
    assert board["segments"][1]["sponsor"] == "read"
    notes = []
    after, exact = youtube.chapter_points(cut, notes.append)
    assert exact
    assert not any(p["title"] == "Sponsor" for p in after)
    assert any('Sponsor chapter' in note and '10 seconds' in note for note in notes)
    assert next(p for p in after if p["title"] == "Chapter 2")["t"] == before[2]["t"] + 6
    cut.sponsors[0].enabled = False
    assert render.timeline(cut) == original


@pytest.mark.parametrize("placement,at_s,expected", [("pre", None, "s1"), ("mid", 18, "s1"), ("end", None, "s2")])
def test_boundaries_and_held_pictures(cut, placement, at_s, expected):
    cut.style.picture_every = 3
    for slide in cut.slides:
        slide.chapter = ""
    cut.frame.hook_s = 20
    cut.sponsors = [slot(placement=placement, at_s=at_s)]
    cut.sponsors[0].after_slide_id = ""
    plan = render._slide_durations(cut, True)
    assert list(render._sponsor_placements(cut, plan)) == [expected]
    tl = render.timeline(cut)
    read = next(s for s in tl["segments"] if s["type"] == "sponsor")
    previous = tl["segments"][read["index"] - 1]
    assert previous["paragraphs"][-1]["id"] == expected
    assert tl["total"] == render._layout(cut)["total"]


def test_multiple_disabled_and_missing_anchor(cut):
    cut.sponsors = [slot(), slot(), slot(enabled=False)]
    cut.sponsors[-1].after_slide_id = "missing"
    tl = render.timeline(cut)
    reads = [s for s in tl["segments"] if s["type"] == "sponsor"]
    assert len(reads) == 2
    assert reads[1]["start"] == reads[0]["start"] + 6


def test_narration_leaves_read_silence(cut, monkeypatch, tmp_path):
    cut.sponsors = [slot()]
    commands = []
    monkeypatch.setattr(audio.ffutil, "run", lambda args: commands.append(args))
    monkeypatch.setattr(audio.ffutil, "duration", lambda _: 0)
    audio.build_narration(cut, tmp_path / "narration.wav", lead_in=0)
    graph = commands[0][commands[0].index("-filter_complex") + 1]
    gap = audio.gap_map(cut)["s0"] + 6
    assert f"apad=pad_dur={gap}[a0]" in graph
    assert f"apad=pad_dur={audio.gap_map(cut)['s1']}[a1]" in graph


def test_midroll_graph_golden(cut):
    cut.sponsors = [slot()]
    lay = render._layout(cut)
    start = lay["sponsors"][0][1]
    graph = render._audio_graph(cut, 4, lay["total"], True,
                               sponsor_audio=[(5, start, 6)], sponsor_windows=[(start, 6)])
    lengths = [d + lay["T"] for d in [lay["body"][0], 6, *lay["body"][1:]]]
    video = render._join_graph(lengths, lay["T"], lay["groups"], cut.frame, 0,
                               group_indices={0: 0, 2: 1, 3: 2}, sponsor_indices={1})
    actual = (video + ";" + graph).replace(";", ";\n") + "\n"
    assert actual == (Path(__file__).parents[1] / "golden/sponsor_mid.txt").read_text()


def test_slates_time_anchor_end_and_estimates(cut, monkeypatch):
    monkeypatch.setattr(render, "_slate_state", lambda _p, kind:
                        {"length": 10 if kind == "intro" else 8, "ready": False,
                         "known": True, "stamp": 0})
    original = render.timeline(cut)
    cut.sponsors = [slot(placement="mid", at_s=28), slot(placement="end")]
    cut.sponsors[0].after_slide_id = ""
    cut.sponsors[0].take = None
    cut.sponsors[1].variant = "long"
    tl = render.timeline(cut)
    reads = [s for s in tl["segments"] if s["type"] == "sponsor"]
    assert tl["segments"][reads[0]["index"] - 1]["paragraphs"][-1]["id"] == "s1"
    assert reads[0]["estimated"]
    assert tl["segments"][-2]["type"] == "sponsor"
    assert tl["segments"][-1]["type"] == "outro"
    assert tl["total"] == original["total"] + sponsors.duration(cut.sponsors[0]) + 6
    assert not youtube.chapter_points(cut)[1]


def test_cue_times_shift(cut):
    cut.style.format = "loudmouth"
    for slide in cut.slides:
        slide.cues = {"loudmouth": [{"kind": "shout", "text": "Paragraph", "at": 0.5}]}
    before = storyboard.build(cut)
    cut.sponsors = [slot()]
    after = storyboard.build(cut)
    for old, new in zip(before["paragraphs"][1:], after["paragraphs"][1:]):
        assert new["cues"][0]["start"] == pytest.approx(old["cues"][0]["start"] + 6)
        assert new["timing"]["cues"][0]["start"] == pytest.approx(old["timing"]["cues"][0]["start"] + 6)


def test_mix_input_indices_and_cache(cut, monkeypatch, tmp_path):
    cut.sponsors = [slot()]
    lay = render._layout(cut)
    original = render._mix_key(cut, lay)
    cut.sponsors[0].take["path"] = "takes/replacement.wav"
    assert render._mix_key(cut, render._layout(cut)) != original
    args = []
    monkeypatch.setattr(render, "_mix_paths", lambda _p, hide=frozenset(): (tmp_path / "mix.webm", tmp_path / "mix.key"))
    monkeypatch.setattr(audio, "build_narration", lambda *a, **kw: None)
    monkeypatch.setattr(render.ffutil, "run", lambda command, **kw: args.extend(command))
    monkeypatch.setattr(render, "pick_music", lambda *a: tmp_path / "music.wav")
    render.build_mix(cut)
    graph = args[args.index("-filter_complex") + 1]
    assert "[1:a]" in graph and "[2:a]" in graph
    assert args[args.index("-stream_loop") + 3].endswith("music.wav")
    assert "volume=-6.0dB:enable=" in graph


def test_sponsor_scene_contract(cut):
    from app import scenes
    ctx = scenes.context_base(cut)
    ctx.update(duration=6, script="A sponsor read")
    assert scenes.lint(scenes.render_html("sponsor/house_short.html", ctx)) == []


def test_resume_held_picture(cut):
    cut.style.picture_every = 3
    for slide in cut.slides:
        slide.chapter = ""
    cut.sponsors = [slot()]
    groups = render._picture_groups(cut, render._slide_durations(cut, True))
    assert groups[1][0][0].id == "s1"
    assert render._picture_source(cut, groups[1][0][0]).id == "s0"
    cut.slides[2].picture_mode = "new"
    assert render._picture_source(cut, cut.slides[2]).id == "s2"


def test_invalid_anchor_leaves_cut_unchanged(cut):
    cut.style.picture_every = 3
    for slide in cut.slides:
        slide.chapter = ""
    before = render.timeline(cut)
    cut.sponsors = [slot()]
    cut.sponsors[0].after_slide_id = "missing"
    assert render.timeline(cut) == before
    assert render._picture_source(cut, cut.slides[1]) is cut.slides[1]


def test_suggestions_are_pure_and_shared(cut):
    cut.frame.hook_s = 20
    before = deepcopy(cut.to_dict())
    suggestions = sponsors.suggest_slots(cut)
    assert [s['after_slide_id'] for s in suggestions] == ['s1', 's0', 's2']
    assert [s['placement'] for s in suggestions] == ['pre', 'mid', 'end']
    assert render.timeline(cut)['sponsor_suggestions'] == suggestions
    assert cut.to_dict() == before
    cut.sponsors = [slot()]
    assert sponsors.suggest_slots(cut) == suggestions
    cut.slides = []
    assert sponsors.suggest_slots(cut) == []
    assert render.timeline(cut)['sponsor_suggestions'] == []


def test_suggestion_chapter_preference_and_fallback(cut):
    cut.slides = [Slide(id=f's{i}', narration='Text.', gap_override=0,
                        take={'duration': 10}) for i in range(10)]
    cut.slides[5].chapter = 'Middle'
    assert sponsors.suggest_slots(cut)[1]['after_slide_id'] == 's4'
    cut.slides[5].chapter = ''
    assert sponsors.suggest_slots(cut)[1]['after_slide_id'] == 's3'
    cut.frame.hook_s = 1000
    assert sponsors.suggest_slots(cut)[0]['after_slide_id'] == 's9'
    cut.slides = cut.slides[:1]
    assert {s['after_slide_id'] for s in sponsors.suggest_slots(cut)} == {'s0'}


@pytest.mark.parametrize('code', ['sponsor_early_long', 'sponsor_count',
                                  'sponsor_disclosure', 'sponsor_question', 'sponsor_music'])
def test_sponsor_rules_positive_negative(cut, code):
    from app import check
    cut.sponsors = [slot()]
    if code == 'sponsor_early_long':
        cut.sponsors[0].variant = 'long'
    elif code == 'sponsor_count':
        cut.sponsors.append(SponsorSlot(id='second', after_slide_id='s1'))
    elif code == 'sponsor_disclosure':
        cut.sponsors[0].paid = True
    elif code == 'sponsor_question':
        cut.slides[0].narration = 'Why? '
    elif code == 'sponsor_music':
        cut.style.music_db = -3
        cut.style.sponsor_music_db = 4
    sb = storyboard.build(cut)
    sb['music'] = True
    rule = getattr(check, code)
    result = rule(sb, cut.frame, check._ctx(sb))
    assert len(result) == 1 and result[0].code == code
    assert result[0].slide_id in {'s0', 's1'}
    assert result[0].fix['kind'] in {'none', 'style'}
    if code == 'sponsor_early_long':
        next(s for s in sb['segments'] if s['type'] == 'sponsor')['start'] = 60
    elif code == 'sponsor_count':
        sb['sponsors'][1]['variant'] = 'long'
    elif code == 'sponsor_disclosure':
        sb['sponsors'][0]['vars']['made'] = 'Paid promotion'
    elif code == 'sponsor_question':
        sb['paragraphs'][0]['narration'] = 'The answer.'
    elif code == 'sponsor_music':
        sb['style']['sponsor_music_db'] = 3  # equal gain is not louder
    assert rule(sb, cut.frame, check._ctx(sb)) == []
    cut.sponsors[0].enabled = False
    sb = storyboard.build(cut)
    sb['music'] = True
    assert rule(sb, cut.frame, check._ctx(sb)) == []


def test_paid_roundtrip_and_custom_disclosure(cut):
    from app import check
    cut.sponsors = [slot(paid=True)]
    assert Project.from_dict(cut.to_dict()).sponsors[0].paid
    assert not SponsorSlot.from_dict({}).paid
    cut.sponsors[0].vars['made'] = 'Sponsored by Example'
    sb = storyboard.build(cut)
    assert check.sponsor_disclosure(sb, cut.frame, check._ctx(sb)) == []
    sb['sponsors'][0]['template'] = 'custom.html'
    assert len(check.sponsor_disclosure(sb, cut.frame, check._ctx(sb))) == 1


def test_check_run_includes_sponsors(cut, monkeypatch):
    from app import check
    cut.sponsors = [slot(paid=True, variant='long')]
    monkeypatch.setattr(render, 'pick_music', lambda _: None)
    result = check.run(cut)
    codes = {f['code'] for f in result['findings']}
    assert {'sponsor_disclosure', 'sponsor_early_long'} <= codes
    cut.sponsors[0].after_slide_id = 'missing'
    assert not any(f['code'].startswith('sponsor_') for f in check.run(cut)['findings'])


def test_music_absent_and_preceding_reads_shift_check_time(cut):
    from app import check
    cut.sponsors = [slot(), SponsorSlot(id='later', variant='long', after_slide_id='s1')]
    cut.sponsors[0].take['duration'] = 60
    cut.style.music_db = 2
    sb = storyboard.build(cut)
    sb['music'] = False
    assert check.sponsor_music(sb, cut.frame, check._ctx(sb)) == []
    assert check.sponsor_early_long(sb, cut.frame, check._ctx(sb)) == []
    sb['music'] = True
    sb['style']['sponsor_music_db'] = 0
    assert len(check.sponsor_music(sb, cut.frame, check._ctx(sb))) == 2


@pytest.fixture
def sponsor_channel():
    from app import channels
    from app.schema import Channel
    channel = Channel(id='sponsor-library-test', name='Library test')
    channels.save(channel)
    return channel


def test_channel_library_roundtrip_and_house(sponsor_channel, cut):
    from app import brand, channels
    from app.schema import Channel, Sponsor
    assert Channel.from_dict({'id': 'old', 'name': 'Old', 'future': 1}).sponsors == []
    sponsor_channel.sponsors = [Sponsor(name='Example', short_copy='A short read')]
    channels.save(sponsor_channel)
    raw = sponsor_channel.to_dict()
    raw['sponsors'][0]['future'] = True
    assert Channel.from_dict(raw).sponsors == channels.load(sponsor_channel.id).sponsors
    assert [s.id for s in sponsors.library(sponsor_channel)][0] == 'house'
    house = sponsors.house()
    assert house.name == brand.NAME and house.url == brand.SITE_URL and not house.paid
    assert house.short_copy.startswith(f'This video was made with {brand.NAME}.')
    assert house.template == 'sponsor/house_short.html'
    assert not any(s.id == 'house' for s in channels.load(sponsor_channel.id).sponsors)
    sponsors.suggest_slots(cut)
    render.timeline(cut)
    assert cut.sponsors == []
    assert Project.from_dict(cut.to_dict()).sponsors == []


def test_library_crud_snapshots_and_takes(sponsor_channel, cut):
    from app import channels, main, store
    cid = sponsor_channel.id
    created = main.add_channel_sponsor(cid, {'name': 'Example', 'short_copy': 'Short read',
                                           'long_copy': 'Long read', 'code': 'SAVE'})
    ident = created['id']
    assert len(main.list_channel_sponsors(cid)) == 2
    cut.channel_id = cid
    cut.sponsors = [slot()]
    store.save(cut)
    before = deepcopy(cut.sponsors[0].to_dict())
    saved = main.patch_sponsor(cut.id, 'read', {'sponsor_id': ident})['sponsors'][0]
    assert saved['script'] == 'Short read' and saved['vars']['code'] == 'SAVE'
    assert saved['take'] == before['take'] and saved['history'] == before['history']
    main.edit_channel_sponsor(cid, ident, {'short_copy': 'Edited library copy'})
    assert store.load(cut.id).sponsors[0].script == 'Short read'
    main.patch_sponsor(cut.id, 'read', {'variant': 'long', 'sponsor_id': ident})
    assert store.load(cut.id).sponsors[0].script == 'Long read'
    main.delete_channel_sponsor(cid, ident)
    assert len(main.list_channel_sponsors(cid)) == 1
    assert store.load(cut.id).sponsors[0].vars['name'] == 'Example'
    saved = main.patch_sponsor(cut.id, 'read', {'sponsor_id': 'house', 'variant': 'short'})['sponsors'][0]
    assert saved['script'] == sponsors.house().short_copy and not saved['paid']
    assert not channels.load(cid).sponsors


@pytest.mark.parametrize('payload', [{'name': ''}, {'name': 3}, {'name': 'x', 'paid': 'yes'},
    {'name': 'x', 'accent': 'red'}, {'name': 'x', 'ink': None}, {'name': 'x', 'url': 'x' * 121},
    {'name': 'x', 'logo': '../outside.png'}, {'name': 'x', 'id': 'house'}])
def test_library_validation(sponsor_channel, payload):
    from app import main
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        main.add_channel_sponsor(sponsor_channel.id, payload)
    assert exc.value.status_code == 400


def test_library_readonly_and_missing(sponsor_channel):
    from app import main
    from fastapi import HTTPException
    for ident, status in [('house', 400), ('missing', 404)]:
        for operation in (lambda: main.edit_channel_sponsor(sponsor_channel.id, ident, {'name': 'x'}),
                          lambda: main.delete_channel_sponsor(sponsor_channel.id, ident)):
            with pytest.raises(HTTPException) as exc:
                operation()
            assert exc.value.status_code == status


def test_library_logo_validation_and_immutable_files(sponsor_channel):
    import io
    from PIL import Image
    from fastapi import HTTPException, UploadFile
    from app import channels, main
    cid = sponsor_channel.id
    ident = main.add_channel_sponsor(cid, {'name': 'Logo test', 'ink': '#123456'})['id']
    def upload(data):
        return main.upload_sponsor_logo(cid, ident, UploadFile(filename='../bad.svg', file=io.BytesIO(data)))
    for data in (b'<svg/>', b'x' * (2 * 1024 * 1024 + 1)):
        with pytest.raises(HTTPException) as exc:
            upload(data)
        assert exc.value.status_code == 400
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), 'red').save(buf, 'PNG')
    first = upload(buf.getvalue())['logo']
    second = upload(buf.getvalue())['logo']
    assert first != second and first.startswith('sponsors/')
    assert (channels.channel_dir(cid) / first).exists()
    read = SponsorSlot()
    sponsors.copy_to_slot(channels.load(cid), read, ident)
    p = Project(id='logo-preview', idea='test', channel_id=cid)
    _, ctx, _ = render._sponsor_preview(p, read)
    assert ctx['asset_roots']['channel_root'] == str(channels.CHANNELS_DIR / cid)
    assert ctx['sponsor']['logo'] == '/scene/{token}/channel/' + second
    assert ctx['sponsor']['ink'] == '#123456'


def test_sponsor_cli_guard_and_add(sponsor_channel, monkeypatch, capsys):
    import os
    import json
    from app import cli
    from app.config import CACHE_DIR, ensure_dirs
    ensure_dirs()
    marker = CACHE_DIR / 'server.json'
    marker.write_text(json.dumps({'pid': os.getpid()}))
    try:
        assert cli.main(['sponsor', 'list', sponsor_channel.id]) == 0
        assert cli.main(['sponsor', 'add', sponsor_channel.id, 'Blocked']) == 1
        assert 'the app is open' in capsys.readouterr().err
    finally:
        marker.unlink()
    assert cli.main(['sponsor', 'add', sponsor_channel.id, 'CLI sponsor', '--short-copy', 'Read']) == 0
    assert json.loads(capsys.readouterr().out)['short_copy'] == 'Read'


@pytest.fixture
def sponsor_jobs(monkeypatch):
    from app import main
    pending = []
    def start(kind, pid, work):
        pending.append(work)
        return 'mock-job'
    monkeypatch.setattr(main.jobs, 'start', start)
    return pending


def test_read_drafts_are_proposals_with_brief_and_disclosure(cut, sponsor_channel,
                                                            sponsor_jobs, monkeypatch):
    from app import channels, llm, main, store
    from app.schema import Sponsor
    sponsor_channel.tone = 'Dry and specific'
    sponsor_channel.sponsors = [Sponsor(id='example', name='Example', url='example.test',
        code='SAVE', short_copy='Short facts', long_copy='Long facts', disclosure='Paid promotion')]
    channels.save(sponsor_channel)
    cut.channel_id = sponsor_channel.id
    cut.sponsors = [slot()]
    sponsors.copy_to_slot(sponsor_channel, cut.sponsors[0], 'example')
    store.save(cut)
    before = deepcopy(cut.sponsors[0].to_dict())
    # A library change must not leak into the saved brief.
    main.edit_channel_sponsor(sponsor_channel.id, 'example', {'long_copy': 'New library facts'})
    def complete(prompt, **kwargs):
        for text in ('Example', 'example.test', 'SAVE', 'Short facts', 'Long facts',
                     'Paid promotion', 'Dry and specific', '5–10', '30–60'):
            assert text in prompt
        assert 'New library facts' not in prompt
        assert not store.lock_for(cut.id)._is_owned()
        assert kwargs['require']({'short': 'Text', 'long': 'More text'})
        assert not kwargs['require']({'short': '', 'long': 3})
        return {'short': 'Example read.', 'long': 'Paid promotion. Longer Example read.'}
    monkeypatch.setattr(llm, 'complete_json', complete)
    estimate = main.draft_sponsor(cut.id, 'read', {'dry_run': True})
    assert estimate['input_tokens'] > 0 and not sponsor_jobs
    main.draft_sponsor(cut.id, 'read', {})
    drafts = sponsor_jobs.pop()(lambda _: None)['drafts']
    assert all('Paid promotion' in text for text in drafts.values())
    assert store.load(cut.id).sponsors[0].to_dict() == before
    main.patch_sponsor(cut.id, 'read', {'variant': 'long', 'script': drafts['long']})
    selected = store.load(cut.id).sponsors[0]
    assert selected.script == drafts['long'] and selected.variant == 'long'
    assert selected.take == before['take'] and selected.vars['made'] == 'Paid promotion'


def test_voice_read_keeps_files_words_and_concurrent_edits(cut, sponsor_jobs, monkeypatch):
    from app import main, store
    cut.sponsors = [slot(paid=True)]
    read = cut.sponsors[0]
    read.script = 'Paid promotion. This video was made with Example. Learn more at the link.'
    read.vars.update(name='Example', made='Paid promotion')
    root = store.project_dir(cut.id)
    old = root / read.take['path']
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b'original recording')
    store.save(cut)
    monkeypatch.setattr(main, '_engine_ready', lambda _: None)
    paths = []
    def speak(text, out, *args, **kwargs):
        assert not store.lock_for(cut.id)._is_owned()
        assert not out.exists()
        paths.append(out)
        out.write_bytes(b'new voice')
        # An inspector edit while synthesis runs must survive the reload.
        main.patch_sponsor(cut.id, 'read', {'vars': {'code': 'EDITED'}})
        return {'duration': 8, 'synthetic': True,
                'words': [{'w': 'Example', 'start': 2.3, 'end': 2.7, 'src': 'tts'}]}
    monkeypatch.setattr(main.tts_mod, 'speak_to_file', speak)
    # Two jobs start before either has written a file.
    main.voice_sponsor(cut.id, 'read')
    main.voice_sponsor(cut.id, 'read')
    for work in sponsor_jobs:
        work(lambda _: None)
    current = store.load(cut.id)
    read = current.sponsors[0]
    assert len(set(paths)) == 2 and all(path.is_file() for path in paths)
    assert old.read_bytes() == b'original recording'
    assert len(read.history) == 2 and read.take['words']
    assert read.vars['code'] == 'EDITED' and 'Paid promotion' in read.take['narration']
    _, ctx, _ = render._sponsor_preview(current, read)
    assert ctx['beats']['brand'] == 2.3 and ctx['beat_sources']['brand'] == 'tts'
    original_voice = read.take['path']
    restored = main.restore_sponsor_take(cut.id, 'read', 0)['sponsors'][0]
    assert restored['take']['path'] == old.relative_to(root).as_posix()
    assert original_voice in {t['path'] for t in restored['history']}
    assert all((root / t['path']).exists() for t in [restored['take'], *restored['history']])


def test_read_mic_uploads_keep_raw_and_processed_files(cut, monkeypatch):
    import asyncio
    from tempfile import SpooledTemporaryFile
    from fastapi import UploadFile, HTTPException
    from app import main, store
    cut.sponsors = [SponsorSlot(id='read', script='Paid promotion. Example.', paid=True,
                               vars={'made': 'Paid promotion'})]
    store.save(cut)
    def process(raw, out, voice):
        assert not store.lock_for(cut.id)._is_owned()
        assert raw.read_bytes() == b'm' * 2048 and not out.exists()
        out.write_bytes(b'processed')
        return {'duration': 3, 'recorded_at': 123}
    monkeypatch.setattr(main.audio_mod, 'process_take', process)
    monkeypatch.setattr(main.words_mod, 'estimate', lambda path, text:
                        [{'w': 'Example', 'start': 1, 'end': 2, 'src': 'est'}])
    def upload(body):
        with SpooledTemporaryFile() as file:
            file.write(body)
            file.seek(0)
            return asyncio.run(main.upload_sponsor_take(cut.id, 'read',
                UploadFile(filename='voice.wav', file=file)))
    upload(b'm' * 2048)
    result = upload(b'm' * 2048)['sponsors'][0]
    assert result['take']['words'][0]['src'] == 'est'
    assert len(result['history']) == 1
    root = store.project_dir(cut.id)
    assert len({t['raw_path'] for t in [result['take'], *result['history']]}) == 2
    for take in [result['take'], *result['history']]:
        assert (root / take['raw_path']).read_bytes() == b'm' * 2048
        assert (root / take['path']).read_bytes() == b'processed'
    with pytest.raises(HTTPException, match='empty'):
        upload(b'')
    assert store.load(cut.id).sponsors[0].take == result['take']
    def fail(*args):
        raise ValueError('processing failed')
    monkeypatch.setattr(main.audio_mod, 'process_take', fail)
    with pytest.raises(HTTPException, match='processing failed'):
        upload(b'm' * 2048)
    assert len(list((root / 'raw').iterdir())) == 3
    assert store.load(cut.id).sponsors[0].take == result['take']


@pytest.mark.parametrize('kind', ['paid', 'house', 'none', 'disabled'])
def test_publish_description_and_chapters(cut, sponsor_channel, monkeypatch, kind):
    from app import brand, script_gen
    from app.schema import Sponsor
    read = slot()
    sponsor_channel.sponsors = [Sponsor(id='paid', name='Snapshot brand',
        url='https://example.test/offer', code='SAVE', disclosure='Paid promotion')]
    sponsors.copy_to_slot(sponsor_channel, read, 'house' if kind == 'house' else 'paid')
    read.take['duration'] = 15
    read.enabled = kind != 'disabled'
    cut.sponsors = [] if kind == 'none' else [read]
    # Library mutations cannot affect the slot's copied publishing values.
    sponsor_channel.sponsors[0].name = 'Changed library'
    monkeypatch.setattr(script_gen, 'write_description', lambda *args: {
        'hook': 'Hook', 'summary': 'Summary', 'chapter_titles': ['Writer title'] * 4,
        'hashtags': [], 'tags': ['test']})
    out = youtube.build_description(cut)
    text = out['description']
    points, exact = youtube.chapter_points(cut)
    assert exact and points[0]['start'] == '0:00'
    assert len(points) >= 3
    stamps = [int(p['t']) for p in points]
    assert all(b - a >= 10 for a, b in zip(stamps, stamps[1:]))
    assert render.timeline(cut)['total'] - stamps[-1] >= 10
    if kind in ('paid', 'house'):
        start = next(s['start'] for s in render.timeline(cut)['segments'] if s['type'] == 'sponsor')
        assert next(p['t'] for p in points if p.get('sponsor')) == start
        assert f'{youtube._stamp(start)} Sponsor' in text
        if kind == 'paid':
            assert 'Snapshot brand: https://example.test/offer\nCode: SAVE\nPaid promotion' in text
        else:
            assert f'{brand.NAME}: {brand.SITE_URL}' in text
            assert read.vars['made'] not in text and 'Code:' not in text
    else:
        assert 'Sponsor' not in text and 'Snapshot brand' not in text
        assert not any(p.get('sponsor') for p in points)
    assert 'Changed library' not in text


def test_multiple_description_blocks(cut, monkeypatch):
    from app import script_gen
    cut.sponsors = [slot(paid=True, vars={'name': 'One', 'url': 'one.test', 'made': 'Paid promotion'}),
                    slot(paid=True, vars={'name': 'Two', 'url': 'two.test', 'code': 'TWO'})]
    monkeypatch.setattr(script_gen, 'write_description', lambda *args: {
        'hook': '', 'summary': '', 'chapter_titles': [], 'hashtags': [], 'tags': []})
    text = youtube.build_description(cut)['description']
    assert 'One: one.test\nPaid promotion' in text
    assert 'Two: two.test\nCode: TWO' in text


def test_chapter_minimum_and_tail(cut, monkeypatch):
    monkeypatch.setattr(render, 'timeline', lambda _: {'total': 34, 'segments': [
        {'type': 'picture', 'paragraphs': [
            {'id': 's0', 'start': 0.6, 'chapter': 'Opening', 'text': ''},
            {'id': 's1', 'start': 10.1, 'chapter': 'Middle', 'text': ''},
            {'id': 's2', 'start': 30, 'chapter': 'Tail', 'text': ''}]},
        {'type': 'sponsor', 'start': 5, 'script': '', 'sponsor': 'read', 'estimated': False}]})
    notes = []
    points, _ = youtube.chapter_points(cut, notes.append)
    assert [p['t'] for p in points] == [0, 10.1]
    assert notes and len(points) < 3  # build_description omits the chapter list


@pytest.mark.parametrize('kind', ['paid', 'house', 'none', 'disabled'])
@pytest.mark.parametrize('response', ['confirmed', 'missing', 'false', 'rejected'])
def test_paid_upload_and_fallback(cut, monkeypatch, tmp_path, kind, response):
    import httpx
    cut.render = {'output': 'video.mp4'}
    (tmp_path / 'video.mp4').write_bytes(b'mocked video')
    cut.sponsors = [] if kind == 'none' else [slot(paid=kind != 'house', enabled=kind != 'disabled')]
    paid = kind == 'paid'
    monkeypatch.setattr(youtube, 'project_dir', lambda _: tmp_path)
    monkeypatch.setattr(youtube, '_access_token', lambda _: 'mock-token')
    posts, updates = [], []
    def result(code, **kwargs):
        return httpx.Response(code, request=httpx.Request('POST', 'https://mock.test'), **kwargs)
    def post(url, **kwargs):
        posts.append(deepcopy(kwargs))
        if paid and response == 'rejected' and len(posts) == 1:
            return result(400, json={'error': {'message': 'Invalid part paidProductPlacementDetails'}})
        return result(200, headers={'Location': 'https://mock.test/upload'})
    def update(url, **kwargs):
        assert url == f'{youtube.API}/videos'
        updates.append(kwargs)
        return result(200, json={'id': 'uploaded'})
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def put(self, url, **kwargs):
            assert url == 'https://mock.test/upload'
            body = {'id': 'uploaded'}
            if response in ('confirmed', 'false'):
                body['paidProductPlacementDetails'] = {'hasPaidProductPlacement': response == 'confirmed'}
            return result(201, json=body)
    monkeypatch.setattr(youtube.httpx, 'post', post)
    monkeypatch.setattr(youtube.httpx, 'put', update)
    monkeypatch.setattr(youtube.httpx, 'Client', Client)
    out = youtube.upload_video(cut, 'channel', title='Title', description='Description',
        tags=[], category_id='22', privacy='private')
    assert out['video_id'] == 'uploaded'
    part = 'paidProductPlacementDetails'
    assert (part in posts[0]['json']) == paid
    assert (part in posts[0]['params']['part']) == paid
    assert posts[0]['json']['status'] == {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}
    assert len(updates) == int(paid and response != 'confirmed')
    if updates:
        assert updates[0]['params'] == {'part': part}
        assert updates[0]['json'] == {'id': 'uploaded', part: {'hasPaidProductPlacement': True}}
    assert len(posts) == (2 if paid and response == 'rejected' else 1)
    if len(posts) == 2:
        assert part not in posts[1]['json'] and part not in posts[1]['params']['part']

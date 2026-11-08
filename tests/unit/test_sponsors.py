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
    after, exact = youtube.chapter_points(cut)
    assert exact
    assert next(p for p in after if p["title"] == "Sponsor")["t"] == tl["segments"][1]["start"]
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

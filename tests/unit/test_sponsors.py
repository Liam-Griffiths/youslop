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

"""Camera selection, reading time and joins without rendering or calling an LLM."""
import re

import pytest

from app import render, storyboard
from app.schema import FrameSpec, Slide


def group(**kwargs):
    return [(Slide(**kwargs), 3.0)]


@pytest.mark.parametrize("snap", [False, True])
@pytest.mark.parametrize("cut", [False, True])
@pytest.mark.parametrize("payoff", [False, True])
def test_pick_never_repeats(snap, cut, payoff):
    frame = FrameSpec(snap_on_cut=snap)
    previous = None
    for i in range(20):
        op = render._pick_op(frame, i, previous, cut, payoff)
        assert op in render.CAMERA_OPS
        assert op != previous
        if cut and snap:
            assert op not in {"creep_out", "reveal"}
            graph = render._kenburns(op, 60, .2)
            assert "z='1'" in graph or "z='1+0.2000*" in graph
        previous = op


def test_payoff_chapter_and_storyboard_share_plan(project):
    project.slides[0].chapter = "Opening"
    project.slides[2].beat = "answer"
    project.outline = {"hook": {"open_loops": [{"payoff_beat": "answer"}]}}
    groups = render._groups_for_preview(project)
    plan = render.camera_plan(project, groups)
    assert plan[0] == plan[2] == "punch"
    assert plan[1] != "punch"
    assert [s["camera"] for s in storyboard.build(project)["segments"]
            if s["type"] == "picture"] == plan
    project.use_intro = True  # Cards ahead of the pictures cannot change the plan.
    assert render.camera_plan(project, groups) == plan


def test_camera_amount_and_arrival_hold(project):
    assert render._camera_amount(project, "creep_in", 0) == pytest.approx(.11)
    assert render._camera_amount(project, "punch", 1) == pytest.approx(.25)
    project.style.ken_burns_amount = .05
    assert render._camera_amount(project, "punch", 1) == pytest.approx(.125)
    graph = render._kenburns("punch", 150, .2, fps=30, ease="expo_out",
                             move_max_s=.6, origin="top")
    assert "min(1,on/18)" in graph
    assert "pow(2,-10*" in graph
    assert "if(gte(min(1,on/18),1),1," in graph
    assert "y='(ih-ih/zoom)*0.33'" in graph
    focal = render._kenburns("reveal", 150, .2, focal_px=(200, 400), origin="top")
    assert "0.33" not in focal
    assert "clip(" in focal
    assert render._kenburns("set", 150, .2).startswith("zoompan=z='1':")


def test_title_hold_grows_and_clamps():
    frame = FrameSpec()
    assert render._title_hold(frame, "one", 10) == .8
    assert render._title_hold(frame, "one two three", 10) == 1.4
    assert render._title_hold(frame, "one two three", 2) == .8
    assert render._title_hold(frame, "one", .5) == 0
    shares = render._caption_timings(["one", "a much longer caption than the first"], 8, frame)
    assert shares[0] >= frame.title_hold_base_s + frame.title_hold_per_word_s
    assert sum(shares) == pytest.approx(8)


@pytest.mark.parametrize("fmt", ["kenburns", "essay"])
def test_last_line_extends_tail_and_matches_timeline(project, fmt):
    project.style.format = fmt
    project.slides = project.slides[:1]
    project.slides[0].take["duration"] = .1
    project.slides[0].title = "Last"
    project.slides[0].narration = "Last."
    project.frame.last_line_min_s = 4
    groups = render._groups_for_preview(project)
    screen, overlap, length = render._segment_timing(project, groups, 0)
    assert render._tail_pad(project, groups) > render.TAIL_PAD
    assert length == pytest.approx(screen + overlap)
    assert render.timeline(project)["segments"][0]["duration"] == pytest.approx(screen, abs=.001)
    _, graph, _ = render._segment_graph(project, groups[0], length, "set", last_line=True)
    fades = re.findall(r"fade=t=(in|out):st=([\d.]+):d=([\d.]+):alpha=1", graph)
    assert float(fades[1][1]) - float(fades[0][1]) >= 4 - (.16 if fmt == "essay" else 0)
    if fmt == "essay":
        assert fades[0][2] == "0.14" and fades[1][2] == "0.16"
    else:
        assert fades[0][1:] == ("0.450", "0.450")
        assert fades[1][2] == "0.248"


def test_join_causes_and_named_allowlist():
    frame = FrameSpec(transition_types=["cut", "fade", "dip", "invalid", "wipeleft"])
    first = group(beat="same", section="main")
    same = group(beat="same", section="main")
    changed = group(beat="other", section="main")
    section = group(beat="same", section="conclusion")
    chapter = group(beat="same", chapter="Chapter")
    assert render._join_for(first, same, frame) == "cut"
    assert render._join_for(first, changed, frame) == "fade"
    assert render._join_for(first, section, frame) == "wipeleft"
    assert render._join_for(first, chapter, frame) == "dip"
    frame.transition_types = ["invalid", "cut", "fade", "dip"]
    assert render._join_for(first, section, frame) == "fade"


def test_join_graph_preserves_overlap_and_card_offsets():
    groups = [group(beat="same"), group(beat="same"), group(chapter="Next")]
    graph = render._join_graph([4.55, 3.55, 3.55, 3.55, 4.55], .55,
                               groups, FrameSpec(), slide_at=1)
    assert graph.count("duration=0.550") == 4
    assert "transition=custom:expr='if(gt(P,0.5),A,B)':duration=0.550:offset=7.000" in graph
    assert "transition=fadeblack:duration=0.550:offset=10.000" in graph
    assert "transition=fade:duration=0.550:offset=4.000" in graph
    assert "transition=fade:duration=0.550:offset=13.000" in graph


def test_proxy_invalidates_for_frame_and_previous_payoff(project):
    groups = render._groups_for_preview(project)
    original = render._proxy_key(project, groups, 1, None)
    project.frame.arrive_s += .1
    assert render._proxy_key(project, groups, 1, None) != original
    original = render._proxy_key(project, groups, 1, None)
    project.slides[1].beat = "payoff"
    project.outline = {"hook": {"open_loops": [{"payoff_beat": "payoff"}]}}
    assert render._proxy_key(project, groups, 1, None) != original


def test_preview_uses_shared_plan_without_downloads(project, monkeypatch):
    from app import audio, media
    project.slides[0].chapter = "Opening"
    groups = render._groups_for_preview(project)
    captured = []

    def fake_segment(_project, _group, _length, _index, out, **kwargs):
        captured.append(kwargs)
        out.write_bytes(b"preview stub")

    def no_audio(*args, **kwargs):
        raise ValueError("silent fixture")

    def no_download(*args, **kwargs):
        pytest.fail("preview verification must not download")

    monkeypatch.setattr(render, "_render_segment", fake_segment)
    monkeypatch.setattr(audio, "build_slice", no_audio)
    monkeypatch.setattr(media, "download_chosen", no_download)
    result = render._build_proxy(project, groups, 0, lambda msg: None,
                                 reuse=False, download=False)
    assert captured[0]["op"] == render.camera_plan(project, groups)[0] == "punch"
    assert captured[0]["size"] == render.preview_size()
    assert result["width"] == 480


def test_proxy_invalidates_when_group_becomes_final(project):
    groups = render._groups_for_preview(project)
    original = render._proxy_key(project, groups, 1, None)
    assert render._proxy_key(project, groups[:2], 1, None) != original

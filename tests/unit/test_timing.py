"""Compare picture offsets with the actual narration concat graph, without encoding."""
import re

import pytest

from app import audio, render


@pytest.mark.parametrize("fmt", ["kenburns", "essay"])
@pytest.mark.parametrize("every", [1, 2])
@pytest.mark.parametrize("estimates", [False, True])
@pytest.mark.parametrize("pre_slides", [0.0, 4.0])
def test_paragraph_alignment(project, monkeypatch, tmp_path, fmt, every, estimates, pre_slides):
    project.style.format = fmt
    project.style.picture_every = every
    plan = render._slide_durations(project, use_estimates=estimates)
    assert len(plan) == (3 if estimates else 2)
    groups = render._picture_groups(project, plan)
    captured = []
    monkeypatch.setattr(audio.ffutil, "run", lambda args: captured.append(args))
    monkeypatch.setattr(audio.ffutil, "duration", lambda path: 0.0)
    transition = render.cuts.transition_for(project.style)
    fill = {s.id: d - audio.gap_map(project)[s.id] for s, d in plan if not s.take}
    audio.build_narration(project, tmp_path / "bed.wav",
                          lead_in=transition / 2 + pre_slides, fill=fill)
    args = captured[0]
    graph = args[args.index("-filter_complex") + 1]
    filters = graph.split(";")[:-1]
    assert len(filters) == len(plan)
    narration_starts = {}
    cursor = 0.0
    for (slide, _), branch in zip(plan, filters):
        delay = re.search(r"adelay=(\d+)\|", branch)
        cursor += int(delay[1]) / 1000 if delay else 0.0
        narration_starts[slide.id] = cursor
        pad = float(re.search(r"apad=pad_dur=([\d.]+)", branch)[1])
        spoken = slide.take["duration"] if slide.take else fill[slide.id]
        cursor += spoken + pad
    picture_cursor = pre_slides
    for i, group in enumerate(groups):
        screen, overlap, file_length = render._segment_timing(project, groups, i)
        assert overlap == transition
        assert file_length == pytest.approx(screen + overlap)
        local = overlap / 2 + (render.HEAD_PAD if i == 0 else 0.0)
        for slide, duration in group:
            assert picture_cursor + local == pytest.approx(narration_starts[slide.id], abs=0.001)
            local += duration
        picture_cursor += file_length - overlap
    assert cursor == pytest.approx(picture_cursor + transition / 2, abs=0.001)


def test_retime_patch_roundtrip_and_clear(project):
    from app import storyboard
    from app.schema import Project
    s = project.slides[0]
    patch = {"gap_override": 20, "title_at": 1, "title_hold": 2, "chapter_hold": 3}
    assert set(storyboard.apply(project, {"paragraphs": {s.id: patch}})) == set(patch)
    loaded = Project.from_dict(project.to_dict())
    assert loaded.slides[0].gap_override == 10
    assert loaded.slides[0].title_at == 1
    assert loaded.slides[0].title_hold == 2
    assert loaded.slides[0].chapter_hold == 3
    storyboard.apply(project, {"paragraphs": {s.id: dict.fromkeys(patch)}})
    assert all(getattr(s, key) is None for key in patch)


def test_gap_moves_next_paragraph(project):
    project.style.format = "kenburns"
    project.style.picture_every = 1
    before = render.timeline(project)
    old_gap = audio.paragraph_gaps(project)[0]
    project.slides[0].gap_override = 2.0
    after = render.timeline(project)
    def paragraphs(tl):
        return [p for seg in tl["segments"] for p in seg["paragraphs"]]
    assert paragraphs(after)[1]["start"] - paragraphs(before)[1]["start"] == pytest.approx(2 - old_gap)
    assert paragraphs(after)[0]["timing"]["gap"] == {"value": 2.0, "src": "user"}


def test_title_graph_and_timeline(project, monkeypatch):
    from app import storyboard
    project.style.format = "kenburns"
    s = project.slides[0]
    s.title = "A title"
    storyboard.apply(project, {"paragraphs": {s.id: {"title_at": 1, "title_hold": 2}}})
    monkeypatch.setattr(render.titles, "render_title", lambda *a, **kw: None)
    group = [(s, 6.0)]
    _, graph, _ = render._segment_graph(project, group, 8, "set")
    lead = render.cuts.transition_for(project.style) / 2 + render.cuts.head_pad_for(project, s)
    assert f"fade=t=in:st={lead + 1:.3f}" in graph
    assert f"fade=t=out:st={lead + 3:.3f}" in graph
    para = render.timeline(project)["segments"][0]["paragraphs"][0]
    assert para["timing"]["title_at"] == {"value": 1, "start": para["start"] + 1, "src": "user"}
    assert storyboard.build(project)["paragraphs"][0]["timing"] == para["timing"]


def test_cue_at_survives_patch(project):
    from app import storyboard
    s = project.slides[0]
    storyboard.apply(project, {"paragraphs": {s.id: {"cues": {
        "flameboat": [{"kind": "title", "text": "Hello", "at": 1.25}]
    }}}})
    assert s.cues["flameboat"][0]["at"] == 1.25


def test_chapter_hold_graph_timeline_and_proxy(project, monkeypatch):
    project.style.format = "kenburns"
    project.style.picture_every = 1
    first, second = project.slides[:2]
    second.chapter = "Next chapter"
    first.gap_override = 3
    groups = render._picture_groups(project, render._slide_durations(project, True))
    before = render._proxy_key(project, groups, 0, None)
    second.chapter_hold = 1.25
    assert render._proxy_key(project, groups, 0, None) != before
    monkeypatch.setattr(render.titles, "render_title", lambda *a, **kw: None)
    monkeypatch.setattr(render.titles, "render_chapter", lambda *a, **kw: None)
    _, graph, _ = render._segment_graph(project, groups[0], 8, "set", chapter=(second.chapter, ""))
    assert "fade=t=in:st=6.750" in graph
    paras = [p for seg in render.timeline(project)["segments"] for p in seg["paragraphs"]]
    assert paras[1]["timing"]["chapter_hold"] == {"value": 1.25, "src": "user"}


@pytest.mark.parametrize("value, expected", [(-2, 0), (20, 10)])
def test_gap_clamp(project, value, expected):
    project.slides[0].gap_override = value
    assert audio.paragraph_gaps(project)[0] == expected

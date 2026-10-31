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

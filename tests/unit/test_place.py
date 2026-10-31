"""Cue anchors fit both readable and crowded paragraphs without overrunning."""
import pytest

from app.cuts.kit import place

TEXT = "First we look at the picture. Then we find the missing detail. Finally we leave."


@pytest.mark.parametrize("cues", [
    [{"on": "First"}, {"on": "Then"}, {"on": "Finally"}],
    [{}, {}, {}, {}],
    [{"on": "First"}, {}, {"on": "Finally"}],
    [{"on": "Finally"}, {"on": "First"}, {"on": "missing anchor"}],
    [{}],
])
@pytest.mark.parametrize("crowded", [False, True])
def test_place_bounds(cues, crowded):
    length, spoken = (0.7, 0.5) if crowded else (10.0, 8.0)
    minimum = 0.35
    spans = place(TEXT, cues, spoken=spoken, length=length, lead=0.2, min_hold=minimum)
    starts = [a for a, _ in spans]
    assert len(spans) == len(cues)
    assert starts[0] == 0
    assert starts == sorted(starts)
    assert all(0 <= a <= b <= length for a, b in spans)
    assert spans[-1][1] == length
    assert sum(b - a for a, b in spans) <= length + 1e-9
    if not crowded:
        assert all(b - a >= minimum - 1e-9 for a, b in spans)


def test_no_cues():
    assert place(TEXT, [], spoken=2, length=3) == []


def test_anchor_position():
    assert place("alpha beta gamma", [{"on": "alpha"}, {"on": "gamma"}],
                 spoken=16, length=20, lead=1) == [(0.0, 12.0), (12.0, 20)]


def test_explicit_start_and_neighbours():
    cues = [{"on": "Finally"}, {"at": 2.0}, {}, {"at": 6.0}, {}]
    spans = place(TEXT, cues, spoken=8, length=10, lead=1)
    starts = [a for a, _ in spans]
    assert starts[1] == 2.0
    assert starts[3] == 6.0
    assert starts == sorted(starts)


@pytest.mark.parametrize("at, expected", [(-1, 0), (30, 8), (1, 1)])
def test_explicit_first_cue(at, expected):
    assert place(TEXT, [{"at": at}], spoken=8, length=10, lead=1)[0][0] == expected

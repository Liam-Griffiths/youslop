"""Timing logic and take integration, without a model, ffmpeg or hosted calls."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import audio, main, store, tts, voice_cloud, words
from app.schema import Project, Take


@pytest.fixture
def envelope(monkeypatch):
    env = [-60.0] * 10 + [-20.0] * 20 + [-60.0] * 15 + [-20.0] * 30 + [-60.0] * 10
    monkeypatch.setattr(audio, "_levels", lambda path: env)
    return env


def test_estimate(envelope, tmp_path):
    result = words.estimate(tmp_path / "take.wav", "Hello, Detroit, we are here.")
    assert [w["w"] for w in result] == "Hello, Detroit, we are here.".split()
    assert {w["src"] for w in result} == {"est"}
    assert 0 <= result[0]["start"] < result[-1]["end"] <= audio.speech_span(envelope).end
    assert all(a["end"] <= b["start"] for a, b in zip(result, result[1:]))
    assert all(w["start"] <= w["end"] for w in result)


def test_runs_and_weighting():
    assert words._runs([-60, -20, -60, -20, -60], -40) == [(0.02, 0.08)]
    assert words._runs([-20] + [-60] * 8 + [-20], -40) == [(0, 0.02), (0.18, 0.2)]
    result = words.spread(["a", "banana", "cat"], [(0, 1), (2, 6)])
    assert [(w["start"], w["end"]) for w in result] == [(0, 1), (2, 5), (5, 6)]
    assert words.spread([], [(0, 1)]) == []
    assert words.spread(["cat"], []) == []


def test_estimate_silence_and_spoken_form(monkeypatch, tmp_path):
    monkeypatch.setattr(audio, "_levels", lambda path: [-120.0] * 50)
    result = words.estimate(tmp_path / "silent.wav", "In 1996.")
    assert [w["w"] for w in result] == tts.spoken_form("In 1996.").split()
    assert result[-1]["end"] == 1.0
    assert words.estimate(tmp_path / "silent.wav", "") == []


def test_phonemes(envelope, tmp_path):
    timing = lambda p, s, e: SimpleNamespace(phoneme=p, start=s, end=e)
    timings = [timing(" ", 0, 0.1), timing("h", 0.1, 0.2), timing("i", 0.2, 0.4),
               timing(" ", 0.4, 0.5), timing(" ", 0.5, 0.6), timing("b", 0.6, 0.8)]
    assert words.from_phonemes(timings, "Hi, Bob!", 0.15) == [
        {"w": "Hi,", "start": 0.0, "end": 0.25, "src": "tts"},
        {"w": "Bob!", "start": 0.45, "end": 0.65, "src": "tts"}]
    path = tmp_path / "take.wav"
    assert words.from_phonemes(timings, "Only", 0.15, path) == words.estimate(path, "Only")
    assert words.from_phonemes(timings, "Only", 0.15) == []


def test_head_trim(monkeypatch, tmp_path):
    monkeypatch.setattr(audio, "_levels", lambda path: path)
    monkeypatch.setattr(audio, "speech_span", lambda path: SimpleNamespace(
        start=0.5 if path.name == "raw.wav" else 0.1))
    assert words.head_trim(tmp_path / "raw.wav", tmp_path / "processed.wav") == pytest.approx(0.4)


def test_old_project_and_roundtrip(project_min):
    old = project_min.to_dict()
    old["slides"][0]["future_key"] = True
    project = Project.from_dict(old)
    assert Take().words == []
    assert project.slides[0].take["words"] == []
    assert all(take["words"] == [] for take in project.slides[0].takes.values())
    project.slides[0].take["words"] = [{"w": "hello", "start": 0, "end": 1, "src": "est"}]
    assert Project.from_dict(project.to_dict()).slides[0].take["words"][0]["w"] == "hello"


@pytest.mark.parametrize("has_timings", [False, True])
@pytest.mark.parametrize("lexicon", [None, {"hello": "h"}])
def test_synthesise_contract(monkeypatch, has_timings, lexicon):
    model = SimpleNamespace(has_timings=has_timings,
                            create=Mock(return_value=([0], 24000)),
                            create_timed=Mock(return_value=([0], 24000, ["timing"])))
    monkeypatch.setattr(tts, "_model", lambda: model)
    monkeypatch.setattr(tts, "phonemise_with_lexicon", lambda *args: ("h", 1))
    assert tts.synthesise("hello", lexicon=lexicon) == ([0], 24000)
    assert tts.synthesise("hello", lexicon=lexicon, timed=True) == (
        [0], 24000, ["timing"] if has_timings else None)
    call = (model.create_timed if has_timings else model.create).call_args
    assert call.args == ("h" if lexicon else "hello",)
    assert call.kwargs.get("is_phonemes", False) == bool(lexicon)


@pytest.mark.parametrize("loaded", [None, False, True])
def test_status_does_not_load_model(monkeypatch, loaded):
    monkeypatch.setattr(tts, "_MODEL", None if loaded is None else SimpleNamespace(has_timings=loaded))
    monkeypatch.setattr(tts, "is_installed", lambda: True)
    monkeypatch.setattr(tts, "_model", Mock(side_effect=AssertionError("model loaded")))
    assert main.tts_status()["has_timings"] is loaded


@pytest.mark.parametrize("engine", ["kokoro", "openai", "elevenlabs"])
@pytest.mark.parametrize("timed", [False, True])
def test_speak_to_file(monkeypatch, tmp_path, engine, timed):
    import soundfile

    timing = SimpleNamespace(phoneme="h", start=0.2, end=0.6)
    monkeypatch.setattr(tts, "synthesise", lambda *args, **kwargs: ([0], 24000, [timing] if timed else None))
    monkeypatch.setattr(soundfile, "write", lambda *args: None)
    monkeypatch.setattr(voice_cloud, "synthesise", lambda engine, text, raw, *args, **kwargs: raw)
    monkeypatch.setattr(tts.ffutil, "run", lambda args: Path(args[-1]).touch())
    monkeypatch.setattr(tts.ffutil, "duration", lambda path: 1.0)
    monkeypatch.setattr(words, "head_trim", lambda *args: 0.1)
    estimated = [{"w": "Hello", "start": 0, "end": 1, "src": "est"}]
    monkeypatch.setattr(words, "estimate", lambda path, text: estimated)
    out = tmp_path / "take.wav"
    meta = tts.speak_to_file("Hello", out, engine=engine)
    assert meta["words"][0]["src"] == ("tts" if engine == "kokoro" and timed else "est")
    assert out.is_file()
    assert not out.with_suffix(".raw.wav").exists()


@pytest.mark.parametrize("fails", [False, True])
def test_upload_keeps_take_if_estimate_fails(project, monkeypatch, tmp_path, fails):
    slide = project.slides[0]
    (tmp_path / "raw").mkdir()
    monkeypatch.setattr(main, "_load", lambda pid: project)
    monkeypatch.setattr(main, "project_dir", lambda pid: tmp_path)
    monkeypatch.setattr(store, "save", lambda p: None)
    monkeypatch.setattr(audio, "process_take", lambda *args: {"duration": 2.0})
    estimate = Mock(side_effect=RuntimeError("envelope failed")) if fails else Mock(return_value=[{"src": "est"}])
    monkeypatch.setattr(words, "estimate", estimate)
    async def read():
        return b"x" * 1024

    file = SimpleNamespace(read=read)
    result = asyncio.run(main.upload_take(project.id, slide.id, file))
    assert result["slide"]["takes"]["mic"]["words"] == ([] if fails else [{"src": "est"}])

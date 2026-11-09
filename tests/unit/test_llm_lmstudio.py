"""LM Studio backend: model detection, reasoning stripping, error mapping.

No real server: httpx.get/post are monkeypatched.
"""
import json

import httpx
import pytest

from app import llm


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)


NATIVE = {"data": [
    {"id": "text-embedding-nomic", "type": "embeddings", "state": "loaded"},
    {"id": "big-model", "type": "llm", "state": "not-loaded", "max_context_length": 131072},
    {"id": "qwen3-30b", "type": "llm", "state": "loaded", "max_context_length": 131072,
     "loaded_context_length": 32768},
]}


@pytest.fixture(autouse=True)
def lmstudio(monkeypatch):
    monkeypatch.setattr(llm, "LLM_BACKEND", "lmstudio")
    monkeypatch.setattr(llm, "LMSTUDIO_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "")
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL_UTILITY", "")
    llm._detected.update(at=0.0, models=None)
    yield
    llm._detected.update(at=0.0, models=None)


def _native_get(url, timeout=None):
    assert url.endswith("/api/v0/models")
    return Resp(200, NATIVE)


def test_picks_loaded_chat_model_and_its_context(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    assert llm.resolve_backend() == "lmstudio"
    assert llm._lmstudio_model(llm.MODEL_SCRIPT) == "qwen3-30b"
    assert llm.local_context_tokens() == 32768


def test_configured_models_and_passthrough(monkeypatch):
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "mine")
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL_UTILITY", "small")
    assert llm._lmstudio_model(llm.MODEL_SCRIPT) == "mine"
    assert llm._lmstudio_model(llm.MODEL_UTILITY) == "small"
    assert llm._lmstudio_model("some/real-id") == "some/real-id"


def test_nothing_loaded_says_so(monkeypatch):
    body = {"data": [{"id": "big-model", "type": "llm", "state": "not-loaded"}]}
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: Resp(200, body))
    with pytest.raises(llm.LLMUnavailable, match="no model loaded"):
        llm._lmstudio_model(llm.MODEL_SCRIPT)


def test_generic_openai_server_falls_back_to_v1_models(monkeypatch):
    def get(url, timeout=None):
        if url.endswith("/api/v0/models"):
            return Resp(404, {})
        return Resp(200, {"data": [{"id": "llama-server-model"}]})
    monkeypatch.setattr(httpx, "get", get)
    assert llm._lmstudio_model(llm.MODEL_SCRIPT) == "llama-server-model"


def test_unreachable_server_is_unavailable(monkeypatch):
    def get(url, timeout=None):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "get", get)
    with pytest.raises(llm.LLMUnavailable, match="start the server"):
        llm.complete("hi")


def test_complete_strips_thinking_and_sends_images(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    sent = {}

    def post(url, json=None, timeout=None):
        sent.update(url=url, body=json)
        return Resp(200, {"model": "qwen3-30b", "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                          "choices": [{"message": {"content": "<think>{\"draft\": 1}</think>\n{\"ok\": true}"}}]})
    monkeypatch.setattr(httpx, "post", post)
    with llm.capture_usage() as usage:
        assert llm.complete_json("x", images=[b"\x89PNG\r\n\x1a\nrest"]) == {"ok": True}
    assert sent["url"].endswith("/v1/chat/completions")
    assert sent["body"]["model"] == "qwen3-30b"
    parts = sent["body"]["messages"][-1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert usage[0]["usage"]["input_tokens"] == 5


def test_context_overflow_is_not_retried(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    calls = []

    def post(url, json=None, timeout=None):
        calls.append(1)
        return Resp(400, {"error": "The number of tokens to keep from the initial prompt is greater than the context length"})
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(llm.LLMUnavailable, match="larger context length"):
        llm.complete_json("x")
    assert len(calls) == 1


def test_strip_reasoning_with_only_closing_tag():
    assert llm.strip_reasoning("thinking aloud</think>\n[1, 2]") == "[1, 2]"
    assert llm.strip_reasoning("plain") == "plain"


def test_probe_warns_about_small_context(monkeypatch):
    body = {"data": [{"id": "m", "type": "llm", "state": "loaded", "loaded_context_length": 4096}]}
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: Resp(200, body))
    r = llm.local_probe()
    assert r["reachable"] and r["model"] == "m" and r["context"] == 4096
    assert "16k" in r["warning"]


def test_status_labels_local_backend():
    s = llm.backend_status()
    assert s["resolved"] == "lmstudio" and s["local"] and s["label"] == "LM Studio"


def test_pictures_go_to_a_loaded_vision_model(monkeypatch):
    body = {"data": [{"id": "text-model", "type": "llm", "state": "loaded"},
                     {"id": "eyes", "type": "vlm", "state": "loaded"}]}
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: Resp(200, body))
    assert llm._lmstudio_model(llm.MODEL_UTILITY) == "text-model"
    assert llm._lmstudio_model(llm.MODEL_UTILITY, vision=True) == "eyes"
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL_VISION", "named-eyes")
    assert llm._lmstudio_model(llm.MODEL_UTILITY, vision=True) == "named-eyes"


def test_json_calls_are_constrained_and_fall_back(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    monkeypatch.setitem(llm._json_mode, "on", True)
    bodies = []

    def post(url, json=None, timeout=None):
        bodies.append(dict(json))
        if "response_format" in json:
            return Resp(400, {"error": "'response_format.type' must be 'json_schema'"})
        return Resp(200, {"choices": [{"message": {"content": "[1]"}}]})
    monkeypatch.setattr(httpx, "post", post)
    assert llm.complete_json("x") == [1]
    assert "response_format" in bodies[0] and "response_format" not in bodies[1]
    assert llm._json_mode["on"] is False
    llm.complete("plain")
    assert "response_format" not in bodies[-1]


def test_plain_calls_are_not_constrained(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    monkeypatch.setitem(llm._json_mode, "on", True)
    seen = {}

    def post(url, json=None, timeout=None):
        seen.update(body=json, timeout=timeout)
        return Resp(200, {"choices": [{"message": {"content": "prose"}}]})
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(llm, "LOCAL_TIMEOUT_FACTOR", 3.0)
    assert llm.complete("x", timeout=100) == "prose"
    assert "response_format" not in seen["body"]
    assert seen["timeout"] == 300


def test_thinking_auto_skips_chores_and_keeps_script(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    monkeypatch.setattr(llm, "LMSTUDIO_THINKING", "auto")
    bodies = []

    def post(url, json=None, timeout=None):
        bodies.append(dict(json))
        return Resp(200, {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "post", post)
    llm.complete("chore", model=llm.MODEL_UTILITY)
    llm.complete("script", model=llm.MODEL_SCRIPT, effort="")
    llm.complete("script", model=llm.MODEL_SCRIPT, effort="max")
    assert bodies[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in bodies[1]
    assert bodies[2]["reasoning_effort"] == "high"


def test_rejected_reasoning_effort_is_dropped(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    monkeypatch.setitem(llm._effort_ok, "on", True)
    bodies = []

    def post(url, json=None, timeout=None):
        bodies.append(dict(json))
        if "reasoning_effort" in json:
            return Resp(400, {"error": "Unrecognized key: reasoning_effort"})
        return Resp(200, {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "post", post)
    assert llm.complete("chore") == "ok"
    assert llm._effort_ok["on"] is False
    monkeypatch.setitem(llm._effort_ok, "on", True)


def test_replies_are_capped(monkeypatch):
    monkeypatch.setattr(httpx, "get", _native_get)
    monkeypatch.setattr(llm, "LMSTUDIO_THINKING", "auto")
    bodies = []

    def post(url, json=None, timeout=None):
        bodies.append(dict(json))
        return Resp(200, {"choices": [{"message": {"content": "[1]"}, "finish_reason": "length"}]})
    monkeypatch.setattr(httpx, "post", post)
    llm.complete("chore", model=llm.MODEL_UTILITY)
    llm.complete("script", model=llm.MODEL_SCRIPT)
    assert bodies[0]["max_tokens"] == llm.LOCAL_MAX_TOKENS
    assert bodies[1]["max_tokens"] == llm.LOCAL_MAX_TOKENS_THINKING

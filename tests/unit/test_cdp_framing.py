import json
import os
import queue
import threading

import pytest

from app.stage import StageError, _Cdp, _Run, _handler


def test_framing_routing_and_eof():
    request_r, request_w = os.pipe()
    response_r, response_w = os.pipe()
    cdp = _Cdp(request_w, response_r)
    results = queue.Queue()

    def send(method):
        try:
            results.put((method, cdp.send(method, timeout=1)))
        except StageError as exc:
            results.put((method, exc))

    def request():
        data = b""
        while not data.endswith(b"\0"):
            data += os.read(request_r, 1)
        return json.loads(data[:-1])

    try:
        first = threading.Thread(target=send, args=("first",))
        first.start()
        a = request()
        second = threading.Thread(target=send, args=("second",))
        second.start()
        b = request()
        # Out-of-order replies, a concatenated event, and a split message.
        msg = json.dumps({"id": b["id"], "result": {"value": 2}}).encode() + b"\0"
        msg += b'{"method":"Page.loadEventFired"}\0'
        split = json.dumps({"id": a["id"], "result": {"value": 1}}).encode() + b"\0"
        os.write(response_w, msg + split[:10])
        assert results.get(timeout=1) == ("second", {"value": 2})
        os.write(response_w, split[10:])
        assert results.get(timeout=1) == ("first", {"value": 1})
        assert cdp.wait_event("Page.loadEventFired", 1)["method"] == "Page.loadEventFired"
        first.join()
        second.join()
        pending = threading.Thread(target=send, args=("pending",))
        pending.start()
        request()
        os.close(response_w)
        response_w = None
        assert isinstance(results.get(timeout=1)[1], StageError)
        pending.join()
        with pytest.raises(StageError, match="closed"):
            cdp.send("after EOF")
    finally:
        if response_w is not None:
            os.close(response_w)
        cdp.close()
        os.close(request_r)


def test_scene_paths_are_token_scoped_and_contained(tmp_path):
    root = tmp_path / "scene"
    root.mkdir()
    (root / "index.html").write_text("scene")
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    (root / "link").symlink_to(outside)
    run = _Run({"scene_root": str(root)}, None)
    handler = object.__new__(_handler(run))
    translate = handler.translate_path
    prefix = f"/scene/{run.token}/"
    assert translate(prefix + "index.html") == str(root / "index.html")
    for path in ("/scene/stale/index.html", prefix + "../private.txt",
                 prefix + "%2e%2e/private.txt", prefix + "link"):
        assert translate(path) == "/nonexistent"


def test_scene_fonts_and_project_assets(tmp_path):
    run = _Run({'scene_root': str(tmp_path / 'scenes'), 'assets_root': str(tmp_path)}, None)
    translate = object.__new__(_handler(run)).translate_path
    assert translate('/fonts/Inter-Medium.ttf').endswith('/resources/fonts/Inter-Medium.ttf')
    assert translate('/fonts/%2e%2e/secret') == '/nonexistent'
    assert translate(f'/scene/{run.token}/assets/media/photo.png') == str(tmp_path / 'media/photo.png')
    assert translate(f'/scene/{run.token}/assets/../../secret') == '/nonexistent'
    assert translate('/scene/wrong/assets/media/photo.png') == '/nonexistent'


def test_cdp_error_reply_and_event_limit():
    request_r, request_w = os.pipe()
    response_r, response_w = os.pipe()
    cdp = _Cdp(request_w, response_r)

    def reply():
        raw = b""
        while not raw.endswith(b"\0"):
            raw += os.read(request_r, 1)
        ident = json.loads(raw[:-1])["id"]
        events = b''.join(json.dumps({"method": "event", "params": {"n": n}}).encode()
                          + b"\0" for n in range(205))
        data = events + json.dumps({"id": ident, "error": {
            "message": "bad command"}}).encode() + b"\0"
        while data:
            data = data[os.write(response_w, data):]

    worker = threading.Thread(target=reply)
    worker.start()
    try:
        with pytest.raises(StageError, match="bad command"):
            cdp.send("bad", timeout=0.2)
        worker.join()
        assert len(cdp.events) == 200
        assert cdp.events[0]["params"]["n"] == 5
        cdp.clear_events()
        with pytest.raises(StageError, match="timed out"):
            cdp.wait_event("missing", timeout=0.001)
    finally:
        os.close(response_w)
        cdp.close()
        os.close(request_r)


def test_scene_exceptions_and_windows_guard(monkeypatch):
    from app import stage

    class Cdp:
        def send(self, *args):
            return {"exceptionDetails": {"exception": {"description": "Error: seek failed"}}}

    with pytest.raises(StageError, match="seek failed"):
        stage._evaluate(Cdp(), "session", "window.__seek(0)")
    monkeypatch.setattr(stage.sys, "platform", "win32")
    with pytest.raises(StageError, match="Linux or macOS"):
        stage._run_cdp({}, lambda m: None)

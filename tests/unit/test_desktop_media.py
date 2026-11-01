"""Native media handlers with platform modules mocked; no hardware access."""
import sys
from types import SimpleNamespace as NS

from app import desktop


def test_macos_media_request(monkeypatch):
    calls = []
    av = NS(AVMediaTypeAudio='soun', AVMediaTypeVideo='vide', AVCaptureDevice=NS(
        requestAccessForMediaType_completionHandler_=lambda kind, cb: calls.append(kind)))
    monkeypatch.setitem(sys.modules, 'AVFoundation', av)
    desktop._request_macos_media()
    assert calls == ['soun', 'vide']


def test_linux_media_permission(monkeypatch):
    class Request:
        def __init__(self, audio=False, video=False):
            self.props = NS(is_for_audio_device=audio, is_for_video_device=video)
            self.allowed = False

        def allow(self):
            self.allowed = True

    hooks = []
    view = NS(connect=lambda event, fn: hooks.append(fn))
    monkeypatch.setitem(sys.modules, 'gi', NS(require_version=lambda *a: None))
    monkeypatch.setitem(sys.modules, 'gi.repository', NS(WebKit2=NS(UserMediaPermissionRequest=Request)))
    monkeypatch.setitem(sys.modules, 'webview.platforms', NS(gtk=NS(BrowserView=NS(instances={1:NS(webview=view)}))))
    monkeypatch.setattr(desktop.threading, 'Thread', lambda target, **kw: NS(start=target))
    monkeypatch.setattr(desktop.time, 'sleep', lambda _: None)
    desktop._patch_linux_media()
    assert len(hooks) == 1
    for request, expected in [(Request(audio=True), True), (Request(video=True), True),
                              (Request(), False), (object(), False)]:
        assert hooks[0](view, request) is expected
        if isinstance(request, Request):
            assert request.allowed is expected


def test_windows_media_permission(monkeypatch):
    class Events:
        def __iadd__(self, callback):
            self.callback = callback
            return self

    core = NS(PermissionRequested=Events())
    win = NS(gui=NS(webview=NS(CoreWebView2=core)))
    monkeypatch.setitem(sys.modules, 'clr', NS())
    monkeypatch.setitem(sys.modules, 'Microsoft.Web.WebView2.Core', NS(
        CoreWebView2PermissionKind=NS(Microphone=1, Camera=2), CoreWebView2PermissionState=NS(Allow=1)))
    monkeypatch.setitem(sys.modules, 'webview', NS(windows=[win]))
    monkeypatch.setattr(desktop.threading, 'Thread', lambda target, **kw: NS(start=target))
    monkeypatch.setattr(desktop.time, 'sleep', lambda _: None)
    desktop._patch_windows_media()
    for kind, expected in [(1, True), (2, True), (3, False)]:
        args = NS(PermissionKind=kind, State=0, Handled=False)
        core.PermissionRequested.callback(None, args)
        assert args.Handled is expected
        assert args.State == int(expected)

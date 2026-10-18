"""The desktop shell: a native window around the same server, instead of a
browser tab you have to find and open yourself.

PyWebView rather than Electron — one Python process, no second toolchain. The
server starts on a background thread over the entry point in `app/__main__.py`,
the window loads its own URL once the server answers, and closing the window
stops the server behind it.

The one thing every embedded-webview framework gets wrong by default is the
microphone. WKWebView, WebView2 and WebKitGTK each need to be told, natively,
that this specific app is allowed to ask for one — otherwise `getUserMedia`
either has no API to call at all, or hangs forever on a permission prompt that
never appears, because the webview has no native UI of its own to show one
with. Each platform's fix is its own function below.

**Only the macOS path has been run on real hardware.** It is proven working —
see the spike in the packaging plan: `NSMicrophoneUsageDescription` in the
bundle's `Info.plist`, `AVCaptureDevice` asked for authorisation once the
event loop is already running (asking before it starts means the system
prompt has nothing to draw itself on), and a
`requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:`
method attached to pywebview's own `BrowserDelegate` class. The Windows and
Linux functions below are written from each platform's own documented
permission API, following the same pattern pywebview already uses elsewhere in
each backend (see the citations in each function) — but neither has been
exercised on a Windows or Linux machine, because this project has only ever
had a Mac available to build on. Verify both before shipping `--desktop` as
the default launch path there; until then the Record tab still works in any
system browser pointed at the same URL, which needs none of this.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from typing import Callable

from . import jobs
from .__main__ import configure, free_port, serve
from .paths import data_root


def _log(message: str) -> None:
    import logging
    logging.getLogger("youslop.desktop").info(message)


# ------------------------------------------------------------- macOS (WebKit)
def _patch_macos_microphone() -> None:
    """Make this process able to ask for the microphone at all, and answer
    WebKit's permission request with a grant once the page asks.

    Two separate problems, each with its own fix:

    1. WebKit will not expose `navigator.mediaDevices` to a page at all unless
       the *host bundle* declares `NSMicrophoneUsageDescription` — confirmed by
       testing a bare script against a real `http://127.0.0.1` origin (absent,
       despite `isSecureContext` being true) against the same page inside a
       `.app` carrying that key (present). PyInstaller's generated
       `Info.plist` needs this key added after the build (see
       `scripts/build_macos.py`); this function sets it on the live bundle
       dictionary too, which covers a non-frozen dev run.
    2. Once the API exists, a call to it raises WebKit's native permission
       request, routed through `WKUIDelegate`'s
       `webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:`.
       pywebview's Cocoa backend does not implement this delegate method, so
       the request is left unanswered and the page's promise never settles.
       Attached here via `objc.classAddMethods` onto pywebview's own
       `BrowserDelegate` class — not a replacement delegate, which would lose
       pywebview's own JS-bridge handling on the same object.
    """
    try:
        import AppKit
        import objc
        from webview.platforms import cocoa
    except ImportError:
        return     # not actually running the Cocoa backend; nothing to patch

    info = AppKit.NSBundle.mainBundle().infoDictionary()
    if not info.get("NSMicrophoneUsageDescription"):
        info["NSMicrophoneUsageDescription"] = (
            "Youslop records your narration for the video you are making.")

    selector = ("webView:requestMediaCapturePermissionForOrigin:"
               "initiatedByFrame:type:decisionHandler:")
    delegate_cls = cocoa.BrowserView.BrowserDelegate
    if delegate_cls.instancesRespondToSelector_(selector):
        return     # a previous call already patched this process

    def _grant(self, webview, origin, frame, capture_type, handler):
        handler(1)   # WKPermissionDecisionGrant

    objc.classAddMethods(delegate_cls, [
        objc.selector(_grant, selector=selector.encode(), signature=b"v@:@@@q@?"),
    ])


def _request_macos_microphone() -> None:
    """Ask TCC for the microphone. Must run after the run loop has started —
    asked any earlier, the system prompt has nowhere to appear and the call
    silently does nothing (confirmed by testing both orders)."""
    try:
        import AVFoundation
    except ImportError:
        return
    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        "soun", lambda ok: _log(f"microphone authorisation: {bool(ok)}"))


# --------------------------------------------------------- Linux (WebKitGTK)
def _patch_linux_microphone() -> None:
    """Auto-grant WebKitGTK's microphone permission dialog.

    **Unverified** — written from the documented WebKitGTK API
    (`WebKitWebView::permission-request`, `WebKitUserMediaPermissionRequest`)
    and pywebview's own `BrowserView.instances` pattern (the same mechanism
    the macOS function above uses, confirmed present in `gtk.py`), but never
    run on a Linux machine. `gtk.py` already turns on
    `webkit_settings.enable_media_stream`, which makes the media API available
    to the page; what it does not do is answer the permission dialog that
    then appears, which is what this adds.
    """
    try:
        import gi
        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2
        from webview.platforms import gtk as gtk_platform
    except (ImportError, ValueError):
        return

    def _on_permission(webview, request, *_a):
        if isinstance(request, WebKit2.UserMediaPermissionRequest):
            request.allow()
            return True
        return False

    # `instances` fills in as each window is created; poll briefly rather than
    # hooking window creation itself, since pywebview gives no signal for it.
    def _attach():
        for _ in range(100):
            for inst in list(gtk_platform.BrowserView.instances.values()):
                webview = getattr(inst, "webview", None)
                if webview is not None and not getattr(webview, "_youslop_mic_patched", False):
                    webview.connect("permission-request", _on_permission)
                    webview._youslop_mic_patched = True
            time.sleep(0.2)

    threading.Thread(target=_attach, daemon=True).start()


# -------------------------------------------------------- Windows (WebView2)
def _patch_windows_microphone() -> None:
    """Auto-grant WebView2's microphone permission.

    **Unverified** — written from the documented WebView2 API
    (`CoreWebView2.PermissionRequested`, `CoreWebView2PermissionKind.Microphone`)
    following the exact pattern `edgechromium.py` already uses for its own
    events (`NewWindowRequested`, `DownloadStarting`, ... — all hooked the
    same way, after `CoreWebView2InitializationCompleted` fires), but never run
    on a Windows machine.
    """
    try:
        import clr  # noqa: F401  (pythonnet — confirms we're on the winforms backend)
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2PermissionKind, CoreWebView2PermissionState,
        )
        import webview
    except ImportError:
        return

    def _on_permission(sender, args):
        if args.PermissionKind == CoreWebView2PermissionKind.Microphone:
            args.State = CoreWebView2PermissionState.Allow
            args.Handled = True

    def _attach():
        for _ in range(100):
            for win in list(getattr(webview, "windows", [])):
                gui = getattr(win, "gui", None)
                core = getattr(gui, "webview", None)
                core = getattr(core, "CoreWebView2", None) if core else None
                if core is not None and not getattr(win, "_youslop_mic_patched", False):
                    core.PermissionRequested += _on_permission
                    win._youslop_mic_patched = True
            time.sleep(0.2)

    threading.Thread(target=_attach, daemon=True).start()


def _patch_microphone() -> None:
    if sys.platform == "darwin":
        _patch_macos_microphone()
    elif sys.platform.startswith("linux"):
        _patch_linux_microphone()
    elif sys.platform == "win32":
        _patch_windows_microphone()


# -------------------------------------------------------------------- window
def _confirm_quit() -> bool:
    """Block a close that would kill a render mid-flight.

    There is no browser-tab "are you sure you want to leave?" here — closing
    the window ends the process — so this is the one chance to catch it.
    """
    active = jobs.running()
    if not active:
        return True
    import webview as wv
    kinds = ", ".join(sorted({j["kind"] for j in active})) or "a job"
    return bool(wv.windows[0].create_confirmation_dialog(
        "Still working",
        f"{kinds} is still running. Quit anyway? It will not finish."))


def _menu():
    import webview as wv

    def new_video():
        wv.windows[0].load_url(wv.windows[0].get_current_url().split("#")[0] + "#/new")

    def open_data_folder():
        import os
        import subprocess
        d = str(data_root())
        if sys.platform == "darwin":
            subprocess.run(["open", d])
        elif sys.platform == "win32":
            os.startfile(d)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", d])

    return [
        wv.menu.Menu("Youslop", [
            wv.menu.MenuAction("New video", new_video),
            wv.menu.MenuAction("Open data folder", open_data_folder),
            wv.menu.MenuSeparator(),
            wv.menu.MenuAction("Quit", lambda: wv.windows[0].destroy()),
        ]),
    ]


def _install_folder_dialog(window) -> None:
    """Wire the Media Library's "choose a folder" button to a real native
    dialog — the one thing a browser's own file input cannot do, since it
    never hands a filesystem path back to the page for a folder, only file
    contents. See the matching note on `app.main.FOLDER_DIALOG`."""
    import webview as wv
    from . import main as main_mod

    def pick() -> str:
        result = window.create_file_dialog(wv.FileDialog.FOLDER)
        return result[0] if result else ""

    main_mod.FOLDER_DIALOG = pick

    # Saving a project file: a download from inside the webview has nowhere to
    # go (pywebview turns downloads off), so the server writes the file itself
    # to wherever the person picks.
    def save_as(suggested: str) -> str:
        result = window.create_file_dialog(wv.FileDialog.SAVE, save_filename=suggested)
        if not result:
            return ""
        return result if isinstance(result, str) else result[0]

    main_mod.SAVE_DIALOG = save_as


def main(open_in_browser: bool = False) -> None:
    """Start the server and open the window. Blocks until the window closes."""
    import webview as wv

    port, token = configure()
    ready = threading.Event()
    threading.Thread(target=serve, args=(port,), kwargs={"ready": ready},
                     daemon=True, name="youslop-server").start()
    if not ready.wait(timeout=20):
        raise RuntimeError("The server did not start in time.")

    url = f"http://127.0.0.1:{port}/" + (f"?t={token}" if token else "")
    if open_in_browser:
        webbrowser.open(url)
        return

    _patch_microphone()
    window = wv.create_window("Youslop", url, width=1360, height=900, min_size=(960, 640))
    window.events.closing += _confirm_quit
    _install_folder_dialog(window)
    wv.start(_request_macos_microphone if sys.platform == "darwin" else (lambda: None),
            menu=_menu(), private_mode=False)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()      # render workers; see build_entry.py
    main()

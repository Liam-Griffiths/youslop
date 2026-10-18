"""Why a video will not play in the app's own window, and what to do about it.

The desktop window is WebKitGTK on Linux, and WebKitGTK plays video through
GStreamer — not through anything this project ships. A desktop with only
`gst-plugins-base` and `-good` installed has no H.264 or AAC decoder at all
(`avdec_h264` lives in `gst-libav`, which nothing pulls in by default), so a
perfectly good mp4 comes up as a broken play button with no error anywhere
that the app can see.

Previews avoid the problem entirely by being VP9/Opus in WebM, which those
two plugin sets do decode (see `ffutil.video_args`). The finished render
cannot: it is H.264/AAC because that is what YouTube wants. So this module
exists for that one file — it says whether this machine can decode it, gives
the exact command for this distribution, and can open the folder it is in so
the creator can watch it in their own player meanwhile.

macOS and Windows decode H.264 in the webview itself and never need any of
this; the fix text there is about opening the file, not installing anything.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# The package that carries GStreamer's libav-based decoders, per family. The
# key is matched against ID and then ID_LIKE from /etc/os-release.
_LIBAV_PACKAGES = {
    "arch": ("sudo pacman -S gst-libav", ""),
    "debian": ("sudo apt install gstreamer1.0-libav", ""),
    "ubuntu": ("sudo apt install gstreamer1.0-libav", ""),
    "fedora": ("sudo dnf install gstreamer1-libav",
               "On Fedora this package lives in RPM Fusion (free), which a "
               "stock install does not enable."),
    "rhel": ("sudo dnf install gstreamer1-libav",
             "This package comes from RPM Fusion (free)."),
    "suse": ("sudo zypper install gstreamer-plugins-libav", ""),
    "alpine": ("sudo apk add gst-libav", ""),
}
_GENERIC_LINUX = (
    "Install your distribution's GStreamer libav plugin "
    "(gst-libav, gstreamer1.0-libav or gstreamer1-libav)."
)

_h264: bool | None | str = "unknown"      # cached; "unknown" = not asked yet


def _os_release() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    out[k] = v.strip().strip('"')
    except OSError:
        pass
    return out


def _linux_fix() -> tuple[str, str]:
    """The install command for this distribution, and any caveat with it."""
    info = _os_release()
    names = [info.get("ID", "")] + (info.get("ID_LIKE", "") or "").split()
    for name in names:
        if name in _LIBAV_PACKAGES:
            return _LIBAV_PACKAGES[name]
    return "", _GENERIC_LINUX


def can_decode_h264() -> bool | None:
    """Can the app's own window play an H.264 video? None when it cannot be told.

    Asked of GStreamer's plugin registry, which is the thing WebKitGTK will
    ask when it tries to play one. Cached: the registry is read once per
    process and installing a plugin needs a restart to take effect anyway.
    """
    global _h264
    if _h264 != "unknown":
        return _h264               # type: ignore[return-value]
    _h264 = None
    if sys.platform != "linux":
        _h264 = True               # WKWebView and WebView2 decode it themselves
        return _h264
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        if not Gst.is_initialized():
            Gst.init_check(None)
        _h264 = Gst.ElementFactory.find("avdec_h264") is not None
    except Exception:
        # No PyGObject, no GStreamer, or a registry that would not load. The
        # honest answer is "cannot tell", which the UI reports as such rather
        # than accusing a working machine of missing a codec.
        _h264 = None
    return _h264                   # type: ignore[return-value]


def status() -> dict:
    """What this machine can play, and how to fix it if it cannot."""
    ok = can_decode_h264()
    command, note = ("", "")
    if sys.platform == "linux":
        command, note = _linux_fix()
        if not note:
            note = ("GStreamer reads its plugin list at startup, so restart "
                    "Youslop once it is installed.")
    elif ok:
        note = ("This machine decodes H.264 itself, so a video that will not "
                "play here is unlikely to be a codec. Open the folder and try "
                "it in your own player.")
    return {
        "platform": sys.platform,
        "distro": _os_release().get("PRETTY_NAME", "") if sys.platform == "linux" else "",
        "h264": ok,                       # True / False / None = cannot tell
        "command": command,
        "note": note,
        "previews_ok": True,              # previews are VP9/Opus; see ffutil
    }


# --------------------------------------------------------------- the folder
class RevealError(RuntimeError):
    pass


def reveal(path: Path) -> tuple[bool, str]:
    """Show `path` in the desktop's file manager. Returns (opened, folder).

    Deliberately not `xdg-open <file>`, which hands the video to a player: the
    point is to show the creator where it lives so they can do as they like
    with it. Returns opened=False — rather than raising — when there is no
    desktop session to ask, so the caller can fall back to printing the path.
    """
    path = Path(path)
    folder = path if path.is_dir() else path.parent
    if not folder.is_dir():
        raise RevealError(f"There is no folder at {folder}")
    try:
        if path.is_dir():
            # A folder is opened itself rather than selected inside its parent.
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            else:
                try:
                    subprocess.Popen(["xdg-open", str(path)])
                except OSError:
                    return False, str(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform == "win32":
            # explorer exits non-zero even when it has done the right thing,
            # so its return code is deliberately not checked.
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            return _reveal_linux(path, folder), str(folder)
    except OSError as exc:
        raise RevealError(f"Could not open the folder: {exc}") from exc
    return True, str(folder)


def _reveal_linux(path: Path, folder: Path) -> bool:
    """FileManager1 first — it highlights the file — then plain xdg-open."""
    show_items = [
        "gdbus", "call", "--session",
        "--dest", "org.freedesktop.FileManager1",
        "--object-path", "/org/freedesktop/FileManager1",
        "--method", "org.freedesktop.FileManager1.ShowItems",
        f"['{path.as_uri()}']", "",
    ]
    try:
        if subprocess.run(show_items, capture_output=True, timeout=8).returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        subprocess.Popen(["xdg-open", str(folder)])
        return True
    except OSError:
        # A headless or sandboxed session: the caller shows the path instead.
        return False

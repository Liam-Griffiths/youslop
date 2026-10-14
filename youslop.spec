# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a local, unsigned build — macOS (.app) or Linux
(one-dir folder). See THIRD-PARTY.md and the packaging plan for the
signed/notarised release build, and scripts/fetch_ffmpeg.py for the bundled
ffmpeg, which must be fetched before building.

The local voice (Kokoro) is bundled, not left for the user to install. A
frozen app runs its own private Python, so a `pip install kokoro-onnx` in a
terminal goes into a different interpreter that the app can never see — the
engine has to be inside the bundle or it is not there at all. Only the ~337MB
of weights stay outside it, in the per-user data folder (see app/paths.py).
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

block_cipher = None
ROOT = Path(SPECPATH)
MACOS = sys.platform == "darwin"

datas = [
    (str(ROOT / "static"), "static"),
    (str(ROOT / "resources" / "fonts"), "resources/fonts"),
    (str(ROOT / "resources" / "bin"), "resources/bin"),
]
binaries = []

hiddenimports = [
    "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "uvicorn.logging",
]
if MACOS:
    hiddenimports += ["webview.platforms.cocoa",
                      "AVFoundation", "objc", "AppKit", "WebKit"]
elif sys.platform == "win32":
    hiddenimports += ["webview.platforms.edgechromium",
                      "webview.platforms.winforms", "clr"]
else:
    hiddenimports += ["webview.platforms.gtk", "gi"]

# Kokoro and everything it reaches at runtime. These packages find their own
# files relative to `__file__` (espeakng_loader's libespeak-ng and its
# espeak-ng-data, kokoro_onnx's config.json, language_tags' registry), so each
# is collected whole rather than left to import analysis.
for pkg in ("kokoro_onnx", "espeakng_loader", "phonemizer", "language_tags",
            "segments", "csvw", "onnxruntime", "soundfile"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
# kokoro_onnx asks importlib.metadata for its own version on every load.
datas += copy_metadata("kokoro-onnx")

excludes = ["numpy.testing"]

# Linux: PyInstaller's GTK hook otherwise copies every icon theme and locale
# installed on the build machine (~400MB on a typical desktop). Adwaita is
# GTK's own fallback theme and all the webview's chrome needs.
hooksconfig = {} if MACOS else {
    "gi": {"icons": ["Adwaita", "hicolor"], "themes": ["Adwaita"],
           "languages": ["en_GB", "en_US"]},
}

a = Analysis(
    ["build_entry.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    hooksconfig=hooksconfig,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Youslop",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="Youslop",
)

if MACOS:
    ICON = str(ROOT / "resources" / "icon.icns") if (ROOT / "resources" / "icon.icns").exists() else None

    app = BUNDLE(
        coll,
        name="Youslop.app",
        icon=ICON,
        bundle_identifier="dev.youslop.app",
        info_plist={
            "NSMicrophoneUsageDescription": "Youslop records your narration for the video you are making.",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "NSHighResolutionCapable": True,
        },
    )

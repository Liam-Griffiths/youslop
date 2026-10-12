# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a local, unsigned macOS build — see THIRD-PARTY.md and
the packaging plan for the signed/notarised release build. This spec is the
first-run version: TTS (Kokoro/onnxruntime/espeak) is excluded to keep the
build fast and the failure surface small; see scripts/fetch_ffmpeg.py for the
bundled ffmpeg this build already includes.
"""
import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "static"), "static"),
    (str(ROOT / "resources" / "fonts"), "resources/fonts"),
    (str(ROOT / "resources" / "bin"), "resources/bin"),
]

hiddenimports = [
    "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "uvicorn.logging",
    "webview.platforms.cocoa",
    "AVFoundation", "objc", "AppKit", "WebKit",
]

excludes = [
    "kokoro_onnx", "onnxruntime", "soundfile", "espeakng_loader",
    "phonemizer", "phonemizer_fork", "numpy.testing",
]

a = Analysis(
    ["build_entry.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
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

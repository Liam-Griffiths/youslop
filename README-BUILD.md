To build the macOS app, you need to run PyInstaller with the spec file. Here are the steps:

# Install PyInstaller if you don't have it
pip install pyinstaller

# Build the app using the spec file
pyinstaller youslop.spec

This will:
1. Create a Youslop.app bundle in the dist/ directory
2. Bundle all dependencies (ffmpeg, fonts, etc.) into the app package
3. Exclude TTS/Kokoro to keep the build smaller

Output locations:
- dist/Youslop.app — The compiled macOS app (ready to run or distribute)
- build/youslop/ — Build artifacts and intermediate files

To run the app after building:
open dist/Youslop.app

Notes from the spec:
- The first build excludes Kokoro/onnxruntime/soundfile to keep it fast and reduce the failure surface
- It includes bundled ffmpeg (see scripts/fetch_ffmpeg.py)
- Microphone permissions are handled via macOS-specific code in app/desktop.py

If you need a signed/notarized release build for distribution, there's a packaging plan mentioned in the spec comments you'd need to follow.
# Building Youslop — maintainer notes

The step-by-step build for macOS, Linux and Windows is in the
[README](README.md#building-it-yourself). This file covers what's behind it.

- **One spec, every platform.** `youslop.spec` builds for whatever it runs on.
  PyInstaller does not cross-compile, so each OS/architecture needs its own
  build machine (or CI runner).
- **Output.** macOS: `dist/Youslop.app`. Linux/Windows: the `dist/Youslop/`
  folder. For a release, archive it:
  `tar -C dist -czf dist/youslop-<version>-linux-<arch>.tar.gz Youslop`
  (zip the folder on Windows).
- **ffmpeg** is fetched by `scripts/fetch_ffmpeg.py` (gitignored, ~250MB) and
  checked against `resources/bin/MANIFEST.json`. Commit the manifest when a
  new platform is added.
- **Linux** bundles GTK and WebKitGTK from the build machine, so target
  machines need a glibc at least as new as the build machine's. The spec
  limits the GTK hook to the Adwaita theme. Without that limit it copies every
  icon theme installed (~400MB).
- **The voice engine** (kokoro-onnx, onnxruntime, espeak-ng, soundfile) is
  bundled. A packaged app runs its own private Python, so a `pip install`
  outside it can never be seen. Only the model weights stay outside, in the
  per-user data folder (`app/paths.py`); `YOUSLOP_DATA` overrides it.
- **Tested so far:** macOS (arm64) and Linux (arm64, Arch). The Windows path
  and microphone permission handling on Linux/Windows (`app/desktop.py`)
  have not been run on real hardware yet.
- **Signing/notarisation** for a distributable macOS build is not set up yet;
  see the packaging plan referenced in the spec comments.

# Third-party components

Youslop is **GPLv3**. That choice is not decorative: the renderer encodes with
**libx264**, which is GPL, so a bundled ffmpeg carrying it makes the whole
distribution GPL. Shipping it as free software is the straightforward way to
honour that, and it is why there is no closed-source or paid build.

## ffmpeg and libx264

Fetched at build time by `scripts/fetch_ffmpeg.py` into `resources/bin/`, which
is not committed — `resources/bin/MANIFEST.json` records the exact URL and
SHA-256 of every binary a release was built with.

| Platform | Build | Licence |
| --- | --- | --- |
| macOS arm64 / x86_64 | [eugeneware/ffmpeg-static](https://github.com/eugeneware/ffmpeg-static) b6.1.1 | GPL |
| Linux x86_64 / arm64 | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) `*-gpl` | GPL |
| Windows x86_64 | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) `win64-gpl` | GPL |

GPL obliges us to offer the corresponding source for those binaries. Both
upstreams publish the source and the build scripts they used; a release must
link to the exact tag in `MANIFEST.json` from its release notes, and keep a
copy of the source tarball for as long as the binary is distributed.

- FFmpeg — <https://ffmpeg.org/download.html>, GPLv2-or-later as built here
- x264 — <https://www.videolan.org/developers/x264.html>, GPLv2-or-later

If ffmpeg is absent from `resources/bin/`, the app falls back to whatever is on
`PATH` (`app/config.py:_binary`), which is how a development checkout works.

## Typefaces

Fifteen faces under the **SIL Open Font License 1.1**, bundled in
`resources/fonts/` because the typography used to resolve to macOS system font
paths and fell apart anywhere else. Per-face attribution, the replacement table
and the licence are in `resources/fonts/README.md` and `resources/fonts/OFL.txt`.

## Python dependencies

Declared in `requirements.txt`; all permissively licensed (BSD/MIT/Apache)
except where noted by their own distributions. Two deserve a mention:

- **Kokoro** (the local narrator) — Apache-2.0 weights, reached through
  `kokoro-onnx`. Chosen over better-known local models precisely because
  several of those are research-only or non-commercial, which is a bad
  foundation for a tool whose point is publishing.
- **espeak-ng**, pulled in transitively by `phonemizer-fork` via
  `espeakng-loader`, is **GPLv3** — compatible with this project's licence, and
  another reason the GPL choice is the honest one.

## Map and archive data

Not bundled; fetched at runtime and credited per video by the app's own
credits block. Tile and API terms are the user's to honour — see the
"Licensing" section of the README, which says plainly that the tool records
provenance but does not clear rights for you.

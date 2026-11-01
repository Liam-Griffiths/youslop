# Third-party components

Corkbored is **GPLv3**. That choice is not decorative: the renderer encodes with
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

## GSAP

GSAP **3.13.0**, core only, is vendored at
`static/vendor/gsap/gsap.min.js`, supplied from
[cdnjs](https://cdnjs.cloudflare.com/ajax/libs/gsap/3.13.0/gsap.min.js).
Copyright 2025 GreenSock; author Jack Doyle.
Distributed under the [GSAP Standard "no charge" licence](https://gsap.com/standard-license),
as referenced by the preserved file header. No plugins are bundled.

## Typefaces

Seventeen faces under the **SIL Open Font License 1.1**, bundled in
`resources/fonts/` because the typography used to resolve to macOS system font
paths and fell apart anywhere else. Per-face attribution, the replacement table
and the licence are in `resources/fonts/README.md` and `resources/fonts/OFL.txt`.

The app and offline landing page also use Archivo variable (width 62–125,
weight 100–900), Copyright 2020 The Archivo Project Authors, from
`google/fonts/ofl/archivo`, and Space Grotesk variable (weight 300–700),
Copyright 2020 The Space Grotesk Project Authors, from
`google/fonts/ofl/spacegrotesk`. Their licences are preserved alongside the
TTFs as `OFL-Archivo.txt` and `OFL-SpaceGrotesk.txt` (SIL OFL 1.1).

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

## Third-party scene catalog (temporary compatibility)

The Hyperframes catalog is retained for compatibility only, pending replacement
by Corkbored's own blocks. Catalog search, fetch and list are currently CLI-only.
The `third_party_blocks` setting defaults to off; any future catalog UI must
honour it and label each item **third-party** with its licence. Shared catalog
metadata excludes upstream preview URLs and branding. Never fetch or display
upstream previews; any future posters must be rendered locally with neutral
sample values. Downloads retain upstream licences and SOURCE.json provenance.

Packs, built-in defaults and new-channel templates must never reference catalog
blocks (`/catalog/`); T8.3 pack lint must reject these references when pack tooling
is implemented. Existing project compositions remain compatible.

Retirement criteria (T12.7): every catalog block used by any local project has a
Corkbored equivalent, and the core set has shipped all four batches. Provide a
catalog-to-block variable mapping and replacement action before removing the
catalog CLI and setting; keep runtime compatibility for old compositions.

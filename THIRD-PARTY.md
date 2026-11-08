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

## Retired scene catalog

The Hyperframes catalog was retired by T12.7 on 2026-11-08. The app no longer
fetches, lists or offers catalog blocks; the catalog CLI, API and setting have
been removed. The fetcher was deleted rather than retained as a developer script:
clean-room Corkbored blocks replace it, and porting third-party block source is
not part of the authoring workflow. No downloaded files or projects are deleted.

Retirement criteria: every catalog block used in a local project has a Corkbored
equivalent, and all four core batches have shipped. Both are met:

- Usage evidence supplied by the reviewer (read-only check, 2026-11-08): no
  catalog block references in the owner's local project JSON files or the repo's
  projects. The only matches were narration words "catalogue" and "cataloguing".
  The implementer did not read or touch either location.
- T12.3 shipped all four batches: 31 core blocks, with contact sheet
  `docs/blocks/core-v1.png`.
- The replacement mapping is empty: code offered no default catalog ids.
  `lower-third` and `lower-third-gpu` in the former offline fetcher tests were
  synthetic registry fixtures, not defaults. There are no evidenced variable
  mappings or project/bulk/finding replacement actions to offer.

Old `/catalog/` mounts resolve to a local "Catalog block retired" placeholder,
even when the old cache is missing or unsafe. The project check reports a
`retired_catalog` finding directing the user to choose a Corkbored block in
Visuals. Saved project references remain intact for manual replacement.
Packs, built-in defaults and new-channel templates must never reference catalog
blocks.

Runtime compatibility with Hyperframes-style compositions remains: local
templates can use `data-composition-variables`, `window.__timelines` and the
mount shim. This contract does not depend on the retired catalog.

# Ticker comparison pending reviewer capture

Chromium is unavailable. Tests mock probes/captures; no mock image is an
accepted golden or a comparison artifact.

Set `CORKBORED_DATA` to a temporary directory before importing `app`. Use
`tests._fixtures.load_project()`'s first paragraph, three seconds, no lead-in
or chapter, at 480×270/30fps. Capture frames 9, 45 and 81 with `cut_engine`
set to `pillow` and `scene` via `cuts.render_segment(..., frames=(i,i+1))`.
Save the six PNGs here. After acceptance, the middle scene PNG becomes
`tests/golden/ticker_scene.png`; the opt-in test skips until that file exists.

Also inspect all four explicit kinds in `tests/unit/test_ticker.py`, both looks,
custom accents, negative/zero/nonnumeric stats, negative/flat charts, five bars,
long labels, wrapped headlines, still/video media, first-cue retiming and chapter.
Check early/middle/settled numbers and dot placement at chart vertices. Media
must continue on paragraph time across headline cues and through chapter tails.

Deliberate differences: numbers count through 17 samples in one atlas plate;
chart dot translation samples the eased path at vertices plus a progress grid;
the halo holds its settled size (Pillow does not actually pulse it). Bar ends
use a hard reveal of rounded plates, rather than redrawing the rounded cap.
Headline rows/kicker share each row's slide. CSS metrics, shade/vignette/chip
geometry and .65 native-media dim replace Pillow's raster geometry/colour tint.
Chapter contents settle before the wash, as in the preceding migrations.
An explicitly delayed first cue holds the terminal ground and static labels
until its moving layers arrive; Pillow can show zero/unsettled text earlier.
No capture windows, per-word backgrounds, per-digit nodes or per-frame CDP.

Measure one picture via `preview_segment` at 480×270: cold scene target ≤2×
this cut's Pillow time. Inspect the mute preview's `.stats.json` for zero
capture-window frames, graph bytes <65536, and capture reuse. Frames and speed
remain unverified until this reviewer pass; no preview or benchmark ran here.

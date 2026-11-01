# Flameboat comparison pending reviewer capture

Chromium is unavailable; implementation tests mock probes/captures. No mock PNG
is a comparison artifact or an accepted golden.

Set `CORKBORED_DATA` to a temporary directory before importing `app`. Use
`tests._fixtures.load_project()`'s first paragraph, three seconds, no lead-in or
chapter, at 480×270/30fps. Capture frames 9, 45 and 81 with `cut_engine` set to
`pillow` and `scene` via `cuts.render_segment(..., frames=(i,i+1))`. Save the six
PNGs here; after acceptance, the middle scene PNG becomes
`tests/golden/flameboat_scene.png`. The opt-in test skips until it exists.

Also inspect explicit cues for all nine kinds (examples in
`tests/unit/test_flameboat.py`), both looks/custom accents, long code/terminal
rows, wrapped titles/hot phrases, adjacent image cues, video cutaways and chapter.
The fixture-only golden does not cover that entire visual vocabulary.

Deliberate differences: row-based simultaneous highlighter wipes across wrapped
title rows; character reveals share a row plate; moving/blinking cursors omitted;
meme shake/punch sampled as camera keys; diagram arrowhead wipes with its shaft;
CSS panel sizing/shadows and badge layout replace Pillow pixel geometry. Source
media uses ffmpeg cover crop/focal points; the still-image pre-crop is omitted.

Measure one picture via `preview_segment` at 480×270: cold scene target ≤2× this
cut's Pillow time. Check the mute preview's `.stats.json` for zero capture-window
frames, bounded graph bytes (<65536) and capture reuse. No speed claim is made
without that measurement.

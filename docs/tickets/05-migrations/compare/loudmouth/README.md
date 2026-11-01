# Loudmouth comparison pending reviewer capture

Chromium captures/probes were mocked for implementation. No mock PNG is a
comparison artifact or an accepted scene golden.

Set `CORKBORED_DATA` to a temporary directory before importing `app`.
Use the fixture project's first paragraph (`tests._fixtures.load_project`),
three seconds, no lead-in/chapter, at 480×270 and 30 fps. Compare frames 9,
45 and 81 (0.3s, 1.5s, 2.7s) with `style.cut_engine` set to `pillow` and
`scene`. `cuts.render_segment(..., frames=(i,i+1))` can produce each still.
Save the six PNGs here after capture becomes available. Inspect wrapping,
punctuation, accent/stopword sizes, panel cover, camera travel and overview.
Words retain their stagger but share a row pop; turns become rightward layout
and nested zooms become downward layout. These differences are deliberate.

After visual acceptance, the scene's middle PNG is the reference for
`tests/golden/loudmouth_scene.png` (the opt-in test skips until it exists).
Also check a chapter, video panel, and all three looks. Reviewer measures one
picture with `preview_segment` at 480×270: cold target ≤9.2s (2× Pillow 4.6s).
The builder writes `<mute-preview>.webm.stats.json`: check `captured_frames=0`,
one pass per cue plus chapter, and `largest_graph_bytes<65536`.

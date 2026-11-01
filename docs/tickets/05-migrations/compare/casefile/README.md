# Casefile comparison pending reviewer capture

Chromium is unavailable during implementation. Mock probes/captures are covered
by unit tests; no mocked image is a real comparison frame or accepted golden.
Use a temporary data root and a copied/synthetic project for review.

Use `tests/unit/test_casefile.py:CUES` on one paragraph, duration 15 s, explicit
cue starts 0, 3, 6, 9, 12 and a synthetic picture. Save paired Pillow/scene frames
here at .3 s (camera only), .65 s (paper arrival), and 1.5 s (settled photo/pin).
Also inspect each other kind at its arrival and reveal, all three looks, long
text, chapter label, previous-paragraph history, repeated photos becoming cards,
chapter/capacity resets and the last paragraph's overview. Put the five-kind
comparison on a non-final paragraph so the final overview does not obscure it.
Known visual differences are in `notes-casefile.md`.

The opt-in SSIM test has its own unchanged fixture paragraph at 1.5 s of 3 s.
Only the first reviewer-accepted scene frame belongs at
`tests/golden/casefile_scene.png`; never regenerate it implicitly.
Measure one picture through `preview_segment` at 480×270, cold scene ≤2× Pillow;
inspect `<output>.stats.json` for bounded graphs and zero capture-window frames.
No preview or benchmark was run during implementation.

Round 2 review: compare cork's warm brown noise/dark specks, wall's grey noise and
felt's pale fibres against Pillow. The lamp should stay fixed at (42%,38%) during
travel and overview; also check the chapter tail (the scene's top plate lights
the label too). Compare both warmed colour and caption-seeded monochrome prints,
including settled history. Check long index-card text (including “celebrity
gossip”) within the 600px measure, with baselines at 140+50*n and rules at
146+50*n, for current reveals and historical cards. The new unit checks use
seeded asset comparisons and tiny synthetic ffmpeg pixel checks; Chromium
captures remain mocked. Re-measure the same review picture cold at 480×270
against 7.8 s; no claim of measured Round 2 performance is made here.

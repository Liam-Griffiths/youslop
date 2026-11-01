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

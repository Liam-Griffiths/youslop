# Group Chat comparison pending reviewer capture

Chromium is unavailable during implementation. No synthetic capture was accepted
as a real frame or golden. Use a temporary project/data root for all captures.

For a repeatable three-time comparison, use the first fixture paragraph with
`tests/unit/test_groupchat.py:CUES`, take duration 10, explicit cue starts
0, 2, 4, 6, 8, and a synthetic picture. Compare Pillow and scene at .3 s (typing),
.74 s (arrival/scroll), and 1.5 s (settled). Save paired stills here. Also inspect
photo delivery, image/video cutaways, the light look, long unbroken text, history
clipping at the header/input, and the chapter notice.

The opt-in SSIM test uses its own unchanged fixture paragraph at 1.5 s of 3 s;
only a reviewer-accepted scene frame belongs at `tests/golden/groupchat_scene.png`.
Measure one `preview_segment` at 480×270, cold and Pillow; target ≤2× Pillow.
Known visual differences are in `notes-groupchat.md`. No preview or benchmark
was run during implementation.

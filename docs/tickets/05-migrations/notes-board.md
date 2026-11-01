# Board scene layout contract

Coordinates are composition pixels (1920×1080). `MARGIN=140`,
`BODY=(140,118,1640,844)`. `build()` is the shared geometry source: it fits
and wraps text, seeds stroke wobble from slide ID/template, prepares photo
prints and compresses the used `Mark.order`/`Photo.order` values to consecutive
beats. Scene wrappers consume that geometry with CSS fonts, SVG text/strokes
and project-local photo PNGs; no JavaScript content/layout derivation.

| Template | Elements and boxes | Sizes and original order |
| --- | --- | --- |
| statement | Lead centered vertically in BODY, underline on last line; two supporting points below; footer | Lead fit from 132, max 3 lines, leading 1.16; line beats 0…n−1, underline n−1; points n+i at 38; note n+2 |
| bullets | Lead/underline at BODY top; dashes and points below lead+54; slots min(132, remaining/n) | Lead 78 beat 0; points 56 (≤4) or 46, max 2 lines, beats 1+i; note n+1 |
| steps | Lead; up to 5 numbered rings across BODY, arrows between; labels below rings | Lead 70 beat 0; ring radius min(96, slot×.30), number radius×1.1, label 46 max 3 lines, beat 1+i; note n+1 |
| versus | Lead; vertical center rule and circled vs; paired columns at BODY.x and midpoint+86 | Lead 66 beat 0; divider/vs (50) beat 1; rows 48 max 2 lines, order 2+2i+side; note 2+2n |
| code | Lead; outlined window, titlebar rule and three dots; up to 8 code lines, accent boxes for `>` | Lead 62 (no underline) beat 0; window beat 1; mono lines 44 (≤6) or 36, beat 2+i; note 2+n |
| stat | Figure at (960,496.8), ring around it, caption below, optional footer | Figure fit from 300 in .74×BODY.w beat 0; ring beat 1; caption 50 max 2 lines beat 2; note 3 |
| quote | Inner box BODY+(130,60), width BODY.w−200, height BODY.h−150; two hand hooks, quote lines, attribution with dash | Hooks beat 0; quote fit from 92 max 4 lines leading 1.2, beats 1+i; attribution 42 beat 1+n |
| taped | Lead in left half; print at x=.30W, width=.62W below lead+40, bordered/shadowed/rotated ±2.6° with tape; left points, arrow, footer | Lead 62 beat 0; photo beat 1; up to 3 points 40 max 2 lines beat 2+i, stacked by actual height+22; arrow 2+n; note 3+n; absent photo uses statement |
| split | Left .44×BODY.w for heading and 4 points; rule at .48×BODY.w; bordered/shadowed print to right rotated ±1.4° | Lead 64 beat 0; rule/photo beat 1; points 44 max 2 lines beat 2+i; note 2+n; absent photo uses bullets |

All text uses `diagram.HAND_STACKS`: marker→ShantellSans-SemiBold,
bradley→Caveat-Bold, chalk→RockSalt-Regular, casual→PatrickHand-Regular,
poster→PermanentMarker-Regular. Code uses titles.MONO_STACK's bundled
JetBrainsMono-Bold. Footers use 28, INK_SOFT, (MARGIN,H−86), max 2 lines.
Lead underlines and emphasized points use the style accent; secondary rules
use INK_FAINT. Native text baselines come from the selected font's anchor box.

`reveal_plan()` calls `diagram.schedule`: usable=max(.4,seconds×.66),
step=usable/beats, start=i×step, arrival=min(settle,max(.22,step×1.35)).
Render settle is clamped to .18…1.2. Both paths share these times. Scene
ink beats use an eased left-to-right soft wipe, including Pillow's initial
text opacity ramp. Stroke-only beats use the same wipe (an approximation of
Pillow's path-length prefix); washes and photo beats retain the existing fade.
Pillow also raises arriving photos by up to 26px; scenes keep their fixed placement.
Photos retain their prepared tape, shadow, rotation and placement. Paper
and avatar come from `_ground_for` and are saved by content hash in scenes/.
Each transparent beat is captured once. A `scene_probe` measures the union of
its SVG children's `getBoundingClientRect()` bounds in that same session,
with stroke/antialias padding. Bounds are scaled outwards to capture pixels;
the PNG is cropped once and cached with a `.bounds.json` sidecar. ffmpeg
overlays each crop at its saved origin, evaluating its alpha ramp only within
that crop and only until its arrival ends. Photo beats (including split's
shared divider/photo beat) and washes use fades without geq.

The chapter scene tail remains in render._chapter_tail. No board template
includes a chapter card. Diagram and board_engine=pillow keep the old path.
Timing and still comparisons require the reviewer's Chromium environment.

# Loudmouth drawer inventory

Read from `loudmouth.frame`, `_blocks`, `_words_onto`, and `chapter` before
writing the scene template. Coordinates are on a 1920 × 1080 page.

| Element | Appearance | Motion / timing | Ease |
| --- | --- | --- | --- |
| Ground | Entire paragraph | Flat look palette: ink, paper, accent ground | none |
| Phrase blocks | Current and all previous cues | Down, right, ±90° turn, or 0.32× nested zoom; first always down | none (layout) |
| Stressed word | Own row, 210px Archivo Black, accent | Word stagger across 80% of cue, minimum 0.2s; 0.16s arrival from 1.55× | cubic out scale; linear alpha ×2.2 |
| Plain word | 118px Archivo Black, ink | Same arrival | same |
| Short stopword | 64px Inter Bold, dim | Same arrival | same |
| Picture panel | Image cues with a source | Full-frame cover, black overlay alpha 120/255; panel cannot turn/zoom | none |
| Moving panel | Video/GIF source | Seek footage at paragraph-local time, darken to 0.53 | linear media time |
| Camera travel | Each cue start | Previous target to current over min(0.45s, 40% cue) | cubic in-out |
| Camera hold drift | Throughout cue | Zoom ×(1 + 0.03 × clamp(elapsed/4)) | linear |
| Paragraph overview | Voice end + 0.05s, if tail >0.5s and >1 block | Fit all revealed blocks, up to 0.9s | cubic in-out |
| Chapter ground | Last hold seconds | Blend last page to look ground over 0.12s | linear |
| Chapter title | Chapter +0.1s | Uppercase, max 3 rows, 260px down to 90px; scale .6→1 and alpha | back.out(1.9), 0.35s |

CSS grid/flex supplies browser wrapping; stressed rows remain separate. No
texture exists in the original. CSS replaces the bitmap zoom cap and manual
word advances; camera geometry is measured after fonts load. All content uses
autoescaped text. No planner, cue placement, or taste policy changes.

## Review round 2: capture states, animate pixels in ffmpeg

This supersedes round 1's screenshot-per-frame movie path. Chromium measures
and captures **one transparent sheet per beat**, with settled words and no
photos, at intrinsic layout resolution. A probe exports the same block bounds,
word bounds, targets and overview used by the GSAP still path. Word and block
plates have transparent gutters. Cache the sheets' cropped plates and geometry
by content, template, font and palette key, independently of output resolution,
fps and frame range. Batch all missing sheets (plus one chapter title plate)
in a single browser session per picture.

**Per state:** browser text layout / wrapping / rasterisation and title layout;
source photo decode, cover sizing and darkening; settled type plates. A word
and its trailing punctuation stay in one `white-space:nowrap` span. A long word
expands its block instead of clipping its punctuation.

**Per frame:** native ffmpeg affine `perspective` corner expressions reproduce
the GSAP camera from the exported targets: cubic in-out travel over
`min(.45, .4*cue_duration)`, 3% clamped hold drift over four seconds, rotation,
and the cubic overview pullback after voice end + .05. Words use timed overlay
enables, linear alpha over `.16/2.2`, and cubic-out scale 1.55 to 1 over .16s.
Stop composing words once they settle and hold that state with `tpad`; the
camera continues. Photo panels come from the original image, directly in
ffmpeg, with cover crop and .53 darkening. Decode stills once, apply static
filters, then repeat pixels with `loop` (avoid image2 `-loop 1` decoding every
frame). Video panels loop from paragraph-local time; GIFs retain the fixed
poster convention. Still previews supply a video poster while a frame loads.
Chapter ground fade, title alpha and back.out(1.9) scale also run in ffmpeg.
No Loudmouth effect requires browser capture at output fps.

Split ffmpeg work at cue and chapter boundaries, cull blocks conservatively
outside the swept camera, encode on the original segment frame grid and
concatenate the resulting clips. Honour `frames=(a,b)` without rounding each
beat's duration independently. Scene Loudmouth gets one scheduler job per
picture (up to three pictures at once), avoiding duplicate sheet capture by
20-second workers. Pillow retains its existing chunking and explicit flag.
Use these conventions for T5.3b-e; only effects that truly cannot be expressed
in ffmpeg may capture short motion windows at target fps and hold between them.

Reviewer still owns visual acceptance and the real-project speed check against
the approximately 2× Pillow target. No benchmark or owner-media render was run.

# Casefile element spec

Read from `casefile.frame`, `_world`, `_item`, `_finish`, `_light` and `chapter`
before implementing the scene template. Times below are paragraph-local; `a,b`
are the unchanged `kit.place` cue span, `u=t-a`, `span=max(.6,(b-a)*.5)`.

| Element | Appears | Motion / ease |
| --- | --- | --- |
| Cork / dark wall / green felt world | Entire paragraph | Static textured 4608×2592 board |
| Earlier paragraphs' items | From paragraph start, same board only | Settled, softened; chapter/capacity reset via `_boards` |
| Earlier cues' items | Following cue boundary | Settled, softened; same deterministic `_slots` |
| Camera | Each cue at `a` | Previous focus → current focus, .9 s cubic-in-out, then still |
| Closing overview | Last paragraph, length−3.6 | Camera → whole board over 3 s cubic-in-out |
| Current paper, shadow, rotation | `a+.495` | .3 s opacity 0→1 and scale 1.14→1, cubic-out |
| Photo print | With paper | 600×700 polaroid, 540×520 inset, warmed/faded; deterministic occasional monochrome |
| Photo caption / optional corner tape | With paper | Handwritten caption, translucent angled tape |
| Repeated photo | When same picture already pinned | Card containing the caption instead of duplicate print |
| Index card | With paper | 680×420, coloured title rule and blue ruled lines |
| Index-card body | `a+1.1` | Character reveal, stepped at 12 Hz over `span`, one row at a time |
| Newspaper clipping | With paper | 600×640, condensed headline, serif body, filler rules |
| Headline highlighter | `a+1.1+.45*span` | Yellow wash left→right, .5*span cubic-out |
| Sticky note | With paper | 440×440, deterministic yellow/pink/blue, darker top band, marker copy |
| Redacted page | With paper | 580×720, title, CONFIDENTIAL label, rule, deterministic filler/redactions |
| Revealed document line | `a+1.1+.25*span` | Black mask slides right over .6*span, cubic-in-out |
| Push pin | `a+.795` | Instant dome/rim/highlight; deterministic weighted colour |
| Lamp / vignette | Entire frame | Warm wash plus dark edges, fixed in viewport |
| Chapter shadow | Chapter start | Dim board to warm black .62 over .45 s, cubic-out |
| Chapter label | Chapter start+.2 | 1180×420 paper, red CASE FILE · NEXT header, condensed title; .35 s scale 1.12→1 / fade cubic-out |
| Chapter pin | Chapter start+.55 | Instant pin |

Builder plan: cue screens with earlier paper flattened into grounds; one native
ffmpeg still per photo (including video poster frames), one layer per typed row,
shared camera keys and motion presets, no capture windows. CSS measures wrapping
and shrinks copy to its longest line before row measurement. The board is laid
out using the existing jittered slots, rather than an unrelated CSS grid.

Review differences: deterministic CSS grain replaces Pillow's unseeded noise;
CSS shadows/pin domes/tape replace raster sprites. Native photos remain square to
the board (their paper and caption too) and fade in; other items keep slot rotation
and scale/drop. Warmth is a board-anchored CSS lamp wash rather than a fixed
viewport vignette; occasional monochrome printing is omitted. Redacted lines use
paper-backed row wipes over black bars (same timing/ease), without off-page mask
spill. The chapter uses the shared 1.14 drop. Human review
must judge these differences, all five kinds, three looks, history and overview.

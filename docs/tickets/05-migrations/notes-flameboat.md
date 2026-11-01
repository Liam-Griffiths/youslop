# Flameboat element spec (2026-10-31)

Read from `frame`, its `_shot_*` helpers, `_moving`, and `chapter` before
starting the scene template. Times below are local to the current cue (`u`),
except image runs and video, which keep their run/paragraph clocks.

| Element | Appearance / layout | Motion / ease |
| --- | --- | --- |
| Ground | Charcoal or midnight; 60px dot grid, dark vignette | Static |
| Every non-picture cue | Full shot, hard replacement at `kit.place` boundary | 1.09→1 punch, .16s, cubic-out |
| Title | Archivo Black, centered, ≤3 rows; matching hot phrase or whole line | Accent band + dark ink swipe from .12s, min(.5s, .35×hold), cubic-out |
| Stat value | Accent display, centered at 44% height | Scale max(.2, back-out(1.9)), .28s |
| Stat label | White bold below value | Linear alpha from .18s over .2s |
| Logo badge | Tinted rounded box, accent outline, white display name | Scale from zero, .32s, back-out(2.4) |
| Logo subline | Dim bold under badge | Linear alpha from .25s over .2s |
| Editor window | Centered rounded panel, shadow, title bar, traffic lights, main.lang | Static within punched shot |
| Code rows / line numbers | Mono syntax colors, 34–46px, up to nine rows | Characters reveal line by line, budget max(.3,min(.5×hold,.16×rows)); linear |
| Code hot row | Accent wash and left rule; other syntax dims | Switch after typing budget + .15s |
| Code cursor | Accent rectangle at typed end | Visible while typing, then blink at 2.4 half-cycles/s |
| Terminal window / prompts | Dark window, zsh title, cyan ~ and green $ | Static within punched shot |
| Terminal command | White mono | Characters from .05s, min(.9,.4×hold,.035×characters), linear |
| Terminal cursor | White block at typed end | Visible while typing, then same blink |
| Terminal output | Dim, red error/fail/denied, green ok/done/success/passed | Whole rows at command end + .12s + .07s×row |
| Diagram heading | White display above boxes | Static |
| Diagram nodes | 2–4 tinted rounded boxes, last accent, others cyan; wrapped labels | Left to right every min(.32,.6×hold/n), .26s back-out(1.9) |
| Diagram arrows | Dim shaft and arrowhead between nodes | Cubic-out growth with destination node; head after 60% |
| Image | Full-frame cover, focal x .18/.5/.82, y .45; initial 1.12 crop | Consecutive image cues share first framing/label; .06 hit releases in .14s cubic-out, .07 linear push with lateral drift over whole run |
| Image label | Bottom-left translucent black pill, white bold | Travels with picture punch |
| Meme | Full-frame picture, or red missing-visual warning | 1.04→1.09 linear creep; decaying sinusoidal shake .35s, seed cue index×7+paragraph index |
| Meme captions | White outlined uppercase display at top/bottom, ≤2 rows | Travel with picture |
| Video/GIF | Image or meme source; same captions | Decodes on paragraph clock even after cutting away/back; image focus from run leader |
| Post | Rounded card, accent avatar/initial, invented display name/handle, wrapped text, three metrics | Fade and rise 60px in .22s, cubic-out |
| Chapter ground | Last live shot sunk 94% into look ground | .3s cubic-out |
| Chapter label | // next chapter, dim mono | Immediate |
| Chapter heading / cursor | White bold mono, > prefix, ≤2 rows, cyan block | Characters from .2s over .7s; cursor blinks when complete |

Builder implementation uses cue screens (consecutive images share their camera
clock), one layer per text row, native ffmpeg media and shared motion presets.
Reviewer must judge rasterization, sampled camera shake, typing cursor treatment,
wrapping, and cold speed; mock captures cannot establish visual acceptance.

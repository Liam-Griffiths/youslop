# Group Chat element inventory

Read from `groupchat.frame`, `_ground`, `_tiles`, `_bubble`, `_typing`,
`_cutaway`, `_caption` and `chapter` before writing the scene.
All clocks come from `kit.place`; times below are relative to the cue.

| Element | Appearance / layout | Motion / ease | Builder treatment |
| --- | --- | --- | --- |
| Picture ground | Cover, blurred at 1/8 size then darkened; accent-tinted fallback | Static | Dim native media; blur deliberately omitted |
| Thread panel / shadow | x=440, y=34, 1040×1012, radius 46 | Static | CSS ground, dark/light theme from `_theme` |
| Header / avatar | 120 high; initial, thread title, online/people status | Static | Ground; sender order/colours from `_senders` |
| Input / send button | Bottom 96 high; Message placeholder, blue circle / arrow | Static | Ground |
| History | Last 12 non-image cues since chapter; previous photo source retained | Bottom-up stack; latest pushes earlier messages up | CSS measures bubbles; settled rows become ground; clipped translation during arrival |
| Sender label | First message in a sender run; absent for me, reset by notice | Moves with bubble | One text row; bundled Inter Bold 28 |
| Message bubble | Left/them or right/me; max width 700; Inter Medium 40/1.3, padding 32/17 | After typing, .28 s cubic-out fade and rise 30, stack rises by tile height | One bubble background and one layer per text row; shared path and viewport clipping |
| Photo bubble | 560×400, sender label when needed; Photo placeholder without source | Same typing/arrival as message | Native ffmpeg photo (poster for clips), straight corners rather than rounded raster mask |
| Notice | Centred muted Inter Medium 28, tile height 64 | No typing; .28 s cubic-out arrival | One row |
| Delivered | Below newest right bubble, after arrival finishes | Hard appearance | Settled ground only |
| Typing bubble | Left, 130×74, before incoming message/photo | min(.7, .3 cue duration); three sinusoidal dots, 9 rad/s, phase .9, rise 6 | Short typing screen; keyed dot translation, constant muted colour |
| Thread viewport | y=154..950; stack floor y=934 | Clips scrolling beneath header/input | CSS clips settled grounds; shared `data-clip` clips moving rows in ffmpeg |
| Cutaway | Full picture/video, focus .2/.5/.8, y=.45 | 8% linear push, horizontal drift; clip plays at paragraph time | Native media and shared camera keys; captions remain still above camera |
| Cutaway caption | Max 6 words, bottom 90, white bold 64 fitted to 2 lines, black outline | Static in source, scales with cutaway | CSS ground |
| Chapter wash | Thread/picture dims to panel colour .8 | .4 s cubic-out | Last screen settled, shared fade |
| Chapter notice | Header-colour rounded box; NEW CHAPTER, title bold 78 fitted to 2 lines | Fade from .15 over .4, cubic-out | One card layer |

History resets at a chapter on the current slide, exactly as Pillow does. Cue
screens split again at typing end and arrival end; holds need no animated text
layers. No frame capture windows, word backgrounds, private compositor or LLM.
Reviewer must judge CSS wrapping, omitted ground blur, photo corners, constant
dot colour and the equivalent cover/camera crop against three Pillow stills.

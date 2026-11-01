# Ticker element inventory

Read from `ticker.frame`, `_ground`, `_p_*` and `chapter` before implementation.
Times below are seconds after the cue starts; cue boundaries remain `kit.place`.

| Element | Appearance / layout | Motion / ease | Builder treatment |
| --- | --- | --- | --- |
| Terminal ground | Navy or amber, 80 px grid below y=76, vignette | Static | Shared ground plate |
| Top chrome | Project title left, MARKETS · EXPLAINED right, rule | Static | Ground, exact bundled condensed/mono faces |
| Stat label / value | Centred at y=.46H; label above | Number ramps at .05 for min(1, .5 duration), cubic-out | One numeric atlas plate, sampled values selected in ffmpeg; nonnumeric value static |
| Change chip | Below figure, after .5 | Hard appearance, green/up or red/down triangle | One chip plate, no per-character backgrounds |
| Chart title / disclaimer | y=160; ILLUSTRATIVE at right when requested | Static | Ground |
| Chart axes | Five rules, formatted values, endpoint date labels | Static | Ground |
| Chart area / line | x=200..1720, y=250..930, 12% range padding | Horizontal draw from .1 for min(1.6, .6 duration), cubic-in-out | One SVG plate with hard horizontal reveal |
| Chart endpoint / halo | Follows interpolated last shown segment; larger halo when settled | Same cubic-in-out draw | Shared keyed translation, one dot plate; settled halo retained |
| Chart final value | Above/left of endpoint after draw | Hard appearance | One plate |
| Bars title / labels | Title y=160, 2–5 rows from y=270..970 | Static | Ground |
| Bars | Magnitude proportional to max absolute value; highest signed value uses accent | .1 + .15 row index, .7 s cubic-out | One reveal plate per bar |
| Bar figures | Move with bar end and count to signed value | Same cubic-out | One numeric atlas per row, keyed horizontal translation |
| Headline picture/video | Cover below top chrome; dimmed toward terminal ground | Video uses paragraph time | Native ffmpeg media, .65 dim; CSS shade above |
| Headline shade | Bottom gradient, transparent at .45H | Static | Ground above native media |
| Kicker / headline rows | Accent block, black mono kicker; white display text, max two lines | From x=40 to120 at .05 over .35, cubic-out | One plate per row; whole kicker block |
| Chapter wash | Over the last panel | Ground tint to .93 over .3, cubic-out | Last panel cloned as settled ground, fade wash |
| Chapter text / rail | SECTION ▸, two mono title rows, hi-colour vertical rail | Fade from .15 over .45, cubic-out | Shared fade preset |
| Chapter underline | Below chapter title | Length grows with text fade | Shared hard horizontal reveal |

No capture windows. Atlas samples approximate smooth numeric counting (16 intervals),
without one node or screenshot per number. Shared translation keys follow the chart
vertices and bar endpoints. CSS typography, vignette/shade and native media tint
replace Pillow raster geometry; reviewer judges these differences. Chart halo holds
its settled size (the Pillow drawer does not actually pulse it).

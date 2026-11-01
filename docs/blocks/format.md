# Corkbored blocks, version 1

A block is a folder containing `block.json`, `block.html`, optional local
assets and a generated `preview.png`. Previews are generated with
`python -m app.cli block preview <id> --t 1.5 --out preview.png`; they are
optional for discovery and never written into installed packs by the app.
The normative metadata schema is [block.schema.json](block.schema.json).
Unknown metadata keys are ignored; declared fields and variable defaults are
validated with the schema vocabulary implemented in `app/blocks.py`.
Optional `default_colors` maps CSS variable names to hex colours for standalone
block previews (the Text set uses Instrument). Passing a scene `context` to
`prepare`/`render` preserves its resolved channel colours instead. Text blocks
use the channel's `bg`, `ink` and `accent`; `panel`, `line` and `dim` can also
be supplied, otherwise they derive from the channel ground and ink. Display
type loads `/fonts/Archivo-Variable.ttf` locally at weight 800, stretch 62%.

Built-ins live in `static/blocks/<id>/`; user blocks in `<data>/blocks/<id>/`
are addressed as `user/<id>`. Installed packs supply
`<data>/packs/<pack-id>/blocks/<id>/`, addressed as `<pack-id>/<id>`; the pack
manifest id must match its folder. Scans are fresh, deterministic and fail
with a field-specific error on malformed metadata. No downloading occurs.

`id` matches the folder name; `name`, `kind`, semantic `version` and `licence`
are required. `aspects` maps supported `16:9`, `9:16`, `1:1` ratios to HTML
files inside the block. Unsupported variants fail explicitly; existing cards
support their original landscape layout. Composition sizes are 1920×1080,
1080×1920 and 1080×1080. `fonts` lists local `/fonts/` URLs; `assets` lists
files relative to the block folder. Symlinks must not escape that folder.

`variables` maps names to definitions with `type` and `default`: `text`
requires `max_length`; `number` accepts `min`/`max`; `colour` accepts `#RRGGBB`
or `var(--token)`; `image`/`clip` accept local `/static/` or `/scene/` URLs
(or an empty default); `table` is an array of objects with scalar cells;
`enum` requires nonempty string `choices`. Unknown supplied variables, wrong
types, nonfinite numbers and out-of-range values fail before capture.

`duration` uses `mode: fixed` with `seconds`, `mode: range` with `min`/`max`
(and an optional `default` preview length; otherwise 5 s clamped to the range),
or `mode: from_words` with `variable`, `words_per_minute`, `min` and `max`.
Word count sets the default duration clamped to those limits. Explicit
seconds must satisfy the rule.

`beats` maps beat names to phrases to land on. Given a context `take.words`
(`w`, `start`, `src`), the first matching phrase supplies a take-relative
second in `beats` and preserves confidence in `beat_sources`; unmatched beats
are omitted. Sponsor wrappers retain the existing sponsor proportional
fallback and word-timing logic. `safe_areas.title` and `.action` are fractional
insets (normally .10 and .05), exposed to templates as `safe_areas`; the
existing base CSS supplies `.title-safe` and `.action-safe` at those defaults.

`block.html` is a strict, autoescaped Jinja scene extending `_base.html`.
Custom includes use `_blocks/<registry-id>/<file>` names. The scene contract retains
composition id/width/height/duration attributes, timed `.clip`
children, `window.__vars`, `data-var-text`/`data-var-src`, paused GSAP timelines,
`__ready` and `__seek(t)`. Use the vendored GSAP and local `/fonts/` only;
remote resources and nondeterministic scene code fail lint. Relative assets
resolve through the existing token-protected scene asset host. HTML, metadata,
local assets and shared runtime dependencies participate in cache invalidation.

`blocks.render(id, vars, aspect, seconds, project=..., context=...)` validates
and delegates to `scene_builder.render`; `prepare` exposes the same template and
context for `scenes.render_html` or `capture`. The CLI supports `block list`,
`block show <id>` and `block preview <id> --aspect 9:16 --t 1.5` (quarter size,
with optional `--vars values.json`, `--seconds`, `--out`). Built-in wrappers
reuse Corkbored templates; no third-party block source is used.

Authoring: `block new my-title` creates `<data>/blocks/my-title` without
replacing existing work; address it as `user/my-title`. The commented scaffold
uses Instrument tokens, local Inter and the runtime rise preset in all three
aspects. `block check user/my-title --static-only` validates metadata and lints
rendered HTML at maximum text lengths without starting Chromium. This reports
browser checks as skipped. Full `block check user/my-title` also measures text
bounds, title safety (portrait excludes the top 15%, bottom 20% and right 15%
for Shorts controls), opaque text contrast (WCAG 3:1 large / 4.5:1 normal), and
pixel equality after seeking away and back. It uses wide, unbroken W samples
and reports the variable name on text failures. It also captures builder plates and
compiles each pass without encoding a video, reporting captures, cache hits, layers,
passes, largest graph bytes and capture-window frames per aspect. An exceeded
capture budget fails before builder screenshots. Gradient/image backgrounds
need reviewer contrast judgement; the automated calculation uses the nearest
opaque ancestor colour. Measure at the midpoint after fonts and runtime ready.

`block preview user/my-title --out /tmp/my-title-preview` writes `preview.png`
at the midpoint (override with `--t`), `sheet.png` at six times and one
quarter-size `preview.mp4`. Default copy is locally authored metadata copy;
`--vars` can replace it. Use a short block or `--seconds` within its duration
rules. For compatibility, an `--out frame.png` path still captures just one
PNG. No preview is fetched or written into the block directory by default.

Blocks declare independently moving panels or lines with unique `data-layer` ids,
`data-start`, `data-duration` and `data-motion`. The preset names match the former
`data-anim` vocabulary (a declared layer also accepts `data-anim` as an alias):
none, fade, rise, fly-left, fly-right, scale-in, wipe,
words, blur-in, pop. Use `data-motion-duration` for arrival seconds and
`data-motion-exit` for a final alpha fade; default is no exit. Layers cannot nest.
Kinetic words use one panel wipe, never per-word elements or ffmpeg nodes.
See [scene builder](../scene-builder.md) for screens, bounds and parameters.

Optional metadata `budget` is a fraction from 0 to 1 (default 0.1), copied to the
composition's `data-budget`. Only a layer explicitly marked `data-capture="frames"`
may request frame captures, confined to its arrival window. The summed windows,
rounded up individually, must fit the budget. Built-ins declare no frame windows.
The sponsor block replaces its legacy rotations and board breathing with beat-timed
panel/text presets; standalone sponsor templates retain their existing timelines.

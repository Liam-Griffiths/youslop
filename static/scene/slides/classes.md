# Custom HTML slides

Tags: `section h1 h2 p ul li img span figure figcaption strong em`.
Attributes: `class`, `alt`, `data-text`, `data-start` (0–9999 seconds), `data-layer`, `data-duration`, `data-motion`.
`src` belongs only on `img`, and must exactly match a supplied image URL.
Images come from the slide's already-resolved JSON image elements, re-encoded
as PNG. No remote paths, data URIs, new searches, or arbitrary project files.

Class allowlist (classes can be combined):

| Class | Effect |
| --- | --- |
| cb-slide | Full composition with 10% safe margins, vertical layout |
| cb-row | Equal columns with a gap |
| cb-stack | Vertical layout with a gap |
| cb-card | Padded panel with a thin rule |
| cb-title | Large Archivo heading |
| cb-number | Very large Archivo number |
| cb-label | Small uppercase mono label |
| cb-accent | Channel accent text |
| cb-muted | Muted text |
| cb-center | Centered text and alignment |
| cb-photo | Bounded photograph, cropped to fit |

No model CSS properties are allowed. Styles, scripts, other tags/attributes/
classes, duplicate attributes, encoded structural attributes and malformed or
unclosed markup reject the entire fragment. Text entities remain escaped text.
`data-text` and `data-start` on elements without a layer remain inert metadata.
With `data-layer="heading" data-start="0.2" data-duration="4" data-motion="rise"`,
the builder captures the element once and ffmpeg animates it. Layer ids match
`[a-z][a-z0-9_-]{0,63}` and must be unique; nesting and more than 48 layers fail.
Durations are positive decimal seconds up to 9999.999999, starts are nonnegative
in the same range. Motion is one of none, fade, rise, fly-left, fly-right, scale-in,
wipe, words, blur-in, pop. Motion and duration require a layer; omitted duration
uses the composition duration. Capture windows, scripts and motion parameters
remain unavailable to model HTML. Use panels or lines, never a layer per word.
Fragments without layers keep the original single static plate.

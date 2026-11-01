# Custom HTML slides

Tags: `section h1 h2 p ul li img span figure figcaption strong em`.
Attributes: `class`, `alt`, `data-text`, `data-start` (0–9999 seconds).
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
`data-start` and `data-text` are inert metadata; this version holds the layout.

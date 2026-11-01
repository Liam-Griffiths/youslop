# Scene builder

`app.scene_builder.render(project, template, ctx, out, seconds=..., size=...,
fps=..., crf=..., extra=...)` returns `Result(path, stats)`. Nothing uses it
implicitly: renderer migrations belong to T2.9/T2.10.

Chromium loads one page, probes settled bounds and computed styles, then captures
one cropped RGBA PNG per layer plus a shared ground. Content-addressed plates
include template, HTML, computed styles, bounds, runtime assets and output size.
A manifest bypasses Chromium on repeat. Timing and motion run in ffmpeg; a literal
`-vf scale=W:H` in `extra` sets plate size before capture.

```html
{% extends '_base.html' %}
{% block body %}
<div data-screen="first" data-start="0" data-duration="5">
  <h1 data-layer="heading" data-start="0.2" data-duration="4.8"
      data-motion="rise" data-motion-duration="0.6">Hello</h1>
</div>
{% endblock %}
```

Screens partition the segment with unique `data-screen` ids, start and duration.
Layer starts inside a screen are local; layers outside screens use segment time
and can persist across screens. Screen containers hold layers; put shared static
ground outside screens. Children belong to their layer; nested `data-layer` is an
error. DOM order is paint order, above the shared ground. Bounds must include any
painted overflow (use padding for shadows). Use one wipe layer or one per line for
word arrivals, never one per word/letter.

`static/scene/motion.json` is shared with runtime presets. Defaults:

| Preset | Arrival | Ease |
| --- | --- | --- |
| none | settled | linear |
| fade | opacity 0 → 1 | expo-out |
| rise | fade, y 48 → 0 | expo-out |
| fly-left / fly-right | fade, x ±240 → 0 | expo-out |
| scale-in | fade, scale .85 → 1 | expo-out |
| words | rise and horizontal wipe | expo-out |
| blur-in | blur 16 → 0 in browser; fade + scale in encode | expo-out |
| pop | opacity overshoot, clamped | back-out |

Arrivals default to .6 seconds. Layer parameters are `data-motion-duration`,
`data-motion-y`, `data-motion-ease` (linear, quad-out, cubic-out, expo-out, back-out).
Legacy `data-anim` word stagger and pop remain unchanged; builder words use a wipe.
Root or screen `data-camera='[{"t":0,"x":0,"y":0,"zoom":1},...]'` specifies absolute
segment-time keys, optional ease on the destination. Zoom must be ≥1. Camera
coordinates are in composition pixels, measured from the top left; one zoompan
operates on the finished screen. No per-layer camera nodes.

Each screen is a pass, with at most 48 live layers and a graph below 64 KB.
Settled persistent layers at the back of the paint order flatten into the next
screen's ground. More live layers require another screen boundary; the builder
raises rather than generating an unbounded graph. Frame counts use absolute
screen boundaries before concatenation. Graphs use `-filter_complex_script`
(or ffmpeg 9's `-/filter_complex`), never graph text in argv.

`data-capture="frames"` captures only that layer's arrival window, then holds its
settled plate. Root `data-budget` defaults to .1 of segment frames, summed across
windows, rounded up per window. Exceeding it fails before screenshots and names
the layer. Stats report screenshots, cache hits, layers, screen passes, largest
graph bytes and window frames requested. Debug logs include the same stats.

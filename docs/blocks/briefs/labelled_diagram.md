# Labelled Diagram

Purpose: Identify parts of an object in a still.

Variables: title (48 chars), source (64 chars); picture; rows: 1–3 objects with label (32 chars), x/y target fractions of the visible picture panel.

Motion: Picture holds; one SVG leader layer reveals; numbered opaque label rows rise sequentially. No capture windows; shared scene builder only.

Layout: both 16:9 and 9:16, Instrument channel tokens and local Archivo/Inter/JetBrains Mono. Titles 96/86 px, labels and numbers 44 px in 62 px line boxes; source 30 px. Ellipsise overflow after fonts load, never shrink below the floor. Header, content and footer stay inside title-safe bounds, including portrait controls. Coordinates refer to the cover-cropped visible panel, not source-image pixels; choose focal controls first. Sample values live in block.json; local illustrative Pillow stills ship with the picture blocks.

Picture controls: picture_dim (0–1 brightness, default 1), focal_x/focal_y (0–1, default .5). Image variables are local /static/ or /scene/{token}/{project,channel,assets}/ URLs with a configured root. Region and arrow fractions use the 16 px inset panel; numbered diagram targets use a 40 px inset for their 44 px markers.

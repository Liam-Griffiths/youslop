# Percentage ring

Show a part of a whole with a numeric percentage as well as colour.

- Variables: title <=48 characters; source <=64 characters; value: 0..100 (sample 68); label: <=48 characters (Trips on public transport).
- Motion: Fill a ring using a 17-row atlas of precomputed SVG arcs over 0.9 s, then hold; percentage is static and explicit. No capture windows; budget 0.
- Layout/look: both 16:9 and 9:16; portrait stays within 15–80% height and left of 85% width. Instrument channel tokens; local Archivo 800/62%, Inter and JetBrains Mono for numbers. Round 2: titles 96/86 px, labels/values >=44 px, sources 30 px; bounded copy wraps or is shortened with an ellipsis after fonts load, never reduced below the floor. Data limits fail before capture; all-zero series use a labelled 0..1 scale.
- Preview: metadata samples in both aspects; midpoint poster and six-time sheet deferred to reviewer along with browser checks and timings (Chromium unavailable).

Round 2 layout: Ring atlas grows to 560/700 px; percent is 260/200 px beside/inside the ring, with a separate caption box. Existing layers and motion beats are retained.

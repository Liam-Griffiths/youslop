# Line chart

Show a labelled series with an honest zero baseline.

- Variables: title <=48 characters; source <=64 characters; rows: 2..8 {label: <=18 characters, value: 0..999999}; sample 2020..2024: 24, 32, 28, 46, 63; unit: <=16 characters (million trips).
- Motion: Reveal the polyline left to right over 0.9 s; axes and endpoint values stay static. No capture windows; budget 0.
- Layout/look: both 16:9 and 9:16; portrait stays within 15–80% height and left of 85% width. Instrument channel tokens; local Archivo 800/62%, Inter and JetBrains Mono for numbers. Round 2: titles 96/86 px, labels/values >=44 px, sources 30 px; bounded copy wraps or is shortened with an ellipsis after fonts load, never reduced below the floor. Data limits fail before capture; all-zero series use a labelled 0..1 scale.
- Preview: metadata samples in both aspects; midpoint poster and six-time sheet deferred to reviewer along with browser checks and timings (Chromium unavailable).

Round 2 layout: 8 px line with an end dot; endpoint labels and values have separate grid boxes. Existing layers and motion beats are retained.

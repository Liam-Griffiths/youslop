# Bar chart

Compare up to six categories on one zero-based scale.

- Variables: title <=48 characters; source <=64 characters; rows: 1..6 {label: <=18 characters, value: 0..999999}; sample Rail 72 / Bus 54 / Cycle 31; unit: <=16 characters (million trips).
- Motion: Reveal one layer per bar over 0.7 s, staggered by 0.12 s; labels and values hold. No capture windows; budget 0.
- Layout/look: both 16:9 and 9:16; portrait stays within 15–80% height and left of 85% width. Instrument channel tokens; local Archivo 800/62%, Inter and JetBrains Mono for numbers. Round 2: titles 96/86 px, labels/values >=44 px, sources 30 px; bounded copy wraps or is shortened with an ellipsis after fonts load, never reduced below the floor. Data limits fail before capture; all-zero series use a labelled 0..1 scale.
- Preview: metadata samples in both aspects; midpoint poster and six-time sheet deferred to reviewer along with browser checks and timings (Chromium unavailable).

Round 2 layout: Inline labels, proportional bars (44–76 px), and values occupy separate columns; row pitch fills the content height. Existing layers and motion beats are retained.

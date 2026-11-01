# Bar race

Show rank changes across three labelled snapshots without interpolating invented data.

- Variables: title <=48 characters; source <=64 characters; rows: 2..5 unique {label: <=18 characters, first/middle/last: 0..999999}; sample Rail 30/55/80, Bus 60/65/70, Cycle 10/35/75. first_period/middle_period/last_period: <=10 characters each (2020 / 2022 / 2024). unit: <=16 characters (million trips).
- Motion: One layer per bar; data-path moves ranks at two discrete snapshot boundaries. Widths and printed values switch using three atlas rows; no per-frame capture. No capture windows; budget 0.
- Layout/look: both 16:9 and 9:16; portrait stays within 15–80% height and left of 85% width. Instrument channel tokens; local Archivo 800/62%, Inter and JetBrains Mono for numbers. Round 2: titles 96/86 px, labels/values >=44 px, sources 30 px; bounded copy wraps or is shortened with an ellipsis after fonts load, never reduced below the floor. Data limits fail before capture; all-zero series use a labelled 0..1 scale.
- Preview: metadata samples in both aspects; midpoint poster and six-time sheet deferred to reviewer along with browser checks and timings (Chromium unavailable).

Round 2 layout: 44 px bars and copy use separate columns; rank pitch fills the available height without changing snapshot timing. Existing layers and motion beats are retained.

# News Ticker

Purpose: Carry a slowly crawling headline on an opaque overlay band.

Original layout: themed Instrument typography with no product or operating-system chrome. Both aspects use border-box text panels inside title safety; wide copy wraps, then ellipsises after fonts load with full copy retained in titles.

Inputs: label (16), text (64). Rows are validated before capture; defaults are illustrative.

Motion: whole panels/rows use presets and a 0.25 s exit. Zero frame-window budget. Ticker uses one linear leftward path; no repeated captures.

One opaque band with an accent rule and label; headline travels 120 composition pixels left over the duration, then fades. Top/bottom positions use safe margins; full-width bands share left/right alignment.

# Code Typing

Purpose: Type a short code example in a plain panel with token syntax colours.

Original layout: themed Instrument typography with no product or operating-system chrome. Both aspects use border-box text panels inside title safety; wide copy wraps, then ellipsises after fonts load with full copy retained in titles.

Inputs: code (160). Rows are validated before capture; defaults are illustrative.

Motion: whole panels/rows use presets and a 0.25 s exit. One 0.8 s typing frame window; budget 0.30, minimum duration 4 s. Pace 1.4 requests 34 frames of 120 at 30 fps. Deterministic text reveal, no per-letter layers.

Code bounds: at most four logical lines, 160 total characters; tokens are escaped text and never executed. Syntax uses accent for keywords, accent2 for literals and dim for comments.

Accent spine and syntax emphasis; syntax is illustrative, not a language parser.

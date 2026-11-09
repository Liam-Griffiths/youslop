# Region Map

Shade countries by measured value and show a shared numeric legend.

- Layout: Country fills mix from the ground to the accent, with an explicit no-data key.
- Both aspects respect title/Shorts safety; text boxes use border-box and font-ready ellipsis with full copy retained in titles. Title ≤36, source ≤56, place names ≤32. Dense bubble key: up to 10 points; clocks: up to 6 cities.
- Core default colours and theme font, weight, radius and pace tokens. Original layout; local Natural Earth public-domain outlines only.
- Typed tables, bounded inputs and deterministic number matching. Maps are prepared once in Python as SVG geometry; only preset arrivals and a 0.25 s exit, budget 0. No per-frame drawing.

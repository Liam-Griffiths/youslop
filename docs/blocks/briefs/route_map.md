# Route Map

Trace a journey between two labelled places on an offline country outline.

- Layout: Accent arc with two endpoint rings, plus a separate itinerary rail.
- Both aspects respect title/Shorts safety; text boxes use border-box and font-ready ellipsis with full copy retained in titles. Title ≤36, source ≤56, place names ≤32. Dense bubble key: up to 10 points; clocks: up to 6 cities.
- Core default colours and theme font, weight, radius and pace tokens. Original layout; local Natural Earth public-domain outlines only.
- Typed tables, bounded inputs and deterministic number matching. Maps are prepared once in Python as SVG geometry; only preset arrivals and a 0.25 s exit, budget 0. No per-frame drawing.

Two coordinate rows identify A and B. `view` selects the world or a bounded region around the shortest longitude span, including dateline crossings. The equirectangular arc is schematic.

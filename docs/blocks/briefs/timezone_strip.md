# Timezone Strip

Compare city clocks at one explicit UTC instant, including local day changes.

- Layout: Six ruled clock cells with accent times, IANA zones and relative-day labels.
- Both aspects respect title/Shorts safety; text boxes use border-box and font-ready ellipsis with full copy retained in titles. Title ≤36, source ≤56, place names ≤32. Dense bubble key: up to 10 points; clocks: up to 6 cities.
- Core default colours and theme font, weight, radius and pace tokens. Original layout; local Natural Earth public-domain outlines only.
- Typed tables, bounded inputs and deterministic number matching. Maps are prepared once in Python as SVG geometry; only preset arrivals and a 0.25 s exit, budget 0. No per-frame drawing.

The one-row `reference` table takes an ISO `utc` timestamp with an explicit zero offset; each city supplies an installed IANA `zone`. Clocks hold at that instant, with daylight saving and previous/same/next-day labels. No live wall clock or network.

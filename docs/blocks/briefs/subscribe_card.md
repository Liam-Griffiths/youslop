# subscribe_card

Purpose: Invite viewers to subscribe without platform branding.

Variables: channel_name (64), handle (48), optional local avatar; focal_x/y (0–1). Character counts are hard maxima; missing optional images leave useful copy. Long media requires 2–4 pictures.

Motion: A ruled Subscribe heading rises, followed by the channel identity and optional square avatar. No logos, icons or play buttons. Shared builder presets only; zero capture-window budget, no per-word layers. Sponsor timing reuses `sponsors.scene_context`: take words plus word_offset, confidence retained, proportional fallback, explicit context beats override.

Layout: both 16:9 and 9:16. Instrument ground, channel tokens, local Archivo 800/62%, Inter and JetBrains Mono. Headings 96/86 px, labels/copy at least 44 px with 62 px line boxes. All content within title safety (portrait also clears Shorts controls). Font-ready fitting ellipsises overflow, preserving full text in the title attribute; never shrinks below the floor. Native pictures fill their slots with cover crop and controllable focal points.

Samples: committed Pillow stills, meaningful defaults and `sample-max.json` exercising every text maximum (and four media slots for the long read). No downloads or platform branding. Browser fit, contrast, reverse seeks and posters are reviewer checks; no contact sheet in this batch.

# Take waveform

Pair a paragraph’s local narration waveform with a short quote.

- Layout and accent: An accent waveform line with end stops sits over a quotation. Read-only local take analysis at preparation; clearly labelled deterministic sample when no usable take exists.
- Both 16:9 and 9:16, inside landscape title safety and portrait Shorts safety. Theme colours, font, weight, radius and pace; core default colours.
- Take input: `context.take.path` resolved inside `context.asset_roots.project_root`; WAV or other ffmpeg-readable local audio. Decode ≤600 s at 8 kHz mono into a temporary file, remove take cuts, compute 96 normalised RMS bins. Missing, unreadable, escaping or longer takes use the labelled sample. Cache includes file mtime/size and cuts. Silence is flat.
- Copy: title ≤36, source ≤56; rows bounded and validated before capture. Values use typed tables and number matching (waveform has no numeric claim).
- Motion: shared presets with final 0.25 s fades; no nested layers. Budget 0, no frame windows.
- Review: default and alternate themes, both aspects, maximum copy and reverse seeks. Browser posters and motion review required.

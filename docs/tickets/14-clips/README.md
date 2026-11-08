# Phase 14: clips from long recordings

Owner request, 2026-11-08: "a ticket for building clipping for longer videos. People have podcasts, live streams etc that they clip for short form content. This pipeline will need speech to text for optional subtitles. And clips often have text overlay and a description with a link to the full clip."

The flow:
1. Import the long recording (a podcast, stream VOD or interview).
2. Choose how to work:
   - **Whole:** transcribe the whole recording locally, then find moments in the transcript or in suggestions.
   - **Manual:** scrub and mark clips by time, and transcribe only the clips you keep, if you want captions.
3. Each clip becomes a short project: reframed to 9:16, 1:1 or 16:9, with burned-in captions and a hook title, plus a description linking to the full recording at that moment.
4. Render the clips in a batch, then upload or export them.

| Ticket | What | Depends on |
|---|---|---|
| T14.1 | Local speech-to-text: word-timed transcripts for long recordings | T11.1, T9.12 |
| T14.2 | Vertical and square output for the whole render pipeline | — |
| T14.3 | Clip finder: transcript view, select by words, suggested moments | T14.1, T11.5 |
| T14.4 | Clip projects: reframe, trim, hook title and graphics | T14.2, T14.3, T12.10a |
| T14.5 | Captions: burned-in styles from word timings, plus SRT/VTT | T14.1, T14.4 |
| T14.6 | Clip descriptions, links to the full recording, batch render and upload | T14.4, T10.7 |

## Owner decisions
- **Speech-to-text engines (T14.1), settled 2026-11-08.** Support a range of engines and use whichever the user has installed and chooses: faster-whisper, whisper.cpp, openai-whisper and mlx-whisper to start. The default engine and model are set in Settings, with a per-run override. The app detects engines and never installs them.
- **Suggested moments (T14.3).** The offline heuristic always works. The LLM ranking is opt-in and shows its cost first, like the T11.4 labels.

## Rules for this phase
- Originals are never copied unless asked (T11.1), and never modified. A clip is a time range on the original.
- Transcribing a long recording is heavy work. Show the estimate (duration × the measured real-time factor) and require a click. Never transcribe automatically on import.
- Previews are at quarter size. A batch render of clips is an explicit action listing each clip and its length.

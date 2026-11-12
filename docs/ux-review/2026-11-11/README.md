# UX self-review, 2026-11-11 (T20.1)

Claude Opus 5.5 reviewed the app end to end, as a new creator would, against
`docs/design/studio-flow.md`. The review changed no code. Fix tickets
(T20.2+) are written only after the owner triages this list.

## How it was run
- **Data:** a fresh temp `CORKBORED_DATA` with the snapshot fixtures, plus
  the bundled example "Under the Street / The Tube Mail". Owner data was not
  touched.
- **Browser:** headless Chromium over CDP at 1440×900, with a second pass at
  1280×720 on Home and all six stages.
- **Per-screen audit:** visible accent buttons, unlabelled controls and
  fields, horizontal overflow, and console errors. The console stayed at
  **0 errors on every screen**.
- **Writing model:** LM Studio wasn't running, and hosted models are off
  limits for a review. Generation journeys therefore started from the
  imported example, and a model failure was simulated (the harness blocks
  every model call).

**Not covered:**
- real script generation;
- a real microphone take (headless has no mic, and the app refused it);
- importing a new footage clip (the fixture shoots were used instead);
- offline picture search;
- a section preview render (skipped to save CPU);
- clicking Cancel on a running job (the drawer's Cancel button was
  checked, not pressed).

Severity: **P1** blocks or loses work, **P2** confuses, **P3** polish.
Screenshots sit beside this file and are git-ignored.

## P1

| id | where | what happens | what it should do | shot |
|---|---|---|---|---|
| UX-01 | Recovery: a recording file deleted on disk | Voice still shows the take as "0:09 · in the cut". Check reports **0 P0**. Edit's whole sound mix fails with a raw toast: "FFError: ffmpeg failed: [in#0 @ 0x…] … /tmp/…/takes/kokoro/sab421ba0.2.wav". Nothing names paragraph 1. | Check raises a P0, "Recording for ¶1 is missing on disk", with Re-voice and Locate file. Voice marks the row. The timeline mixes silence for that paragraph and names it, instead of failing the whole mix. | j8-02-missing-take.png, j8-03-edit-missing.png |
| UX-02 | Channels: picking a theme | Clicking a theme card opens a native `confirm()`. **Cancel doesn't cancel**: it means "colours only", so a misclick always overwrites the channel's colours, and channels have no undo. | Show an in-app dialog with three choices: "Use colours and templates", "Colours only" and "Cancel". Or apply the theme with an Undo toast. | j4-04-kitchen.png |

## P2

| id | where | what happens | what it should do | shot |
|---|---|---|---|---|
| UX-03 | Edit | The player is 65vh tall. At 1440×900 the timeline starts at the fold (y≈820). At 1280×720 the toolbar wraps to two rows and **no lane is visible** without scrolling. After Phase 17, the timeline is the main work surface. | Cap the player so the ruler, pictures and voice lanes are visible at 1280×720. Keep the toolbar on one row, moving rare actions into a menu. | j2-14-edit.png, s-06-edit.png |
| UX-04 | Voice at 1280×720 | The project bar breaks: the title floats at the top, the extra buttons crowd it, and "Next: Visuals" drops onto the stage bar. | Fold "Microphone setup" and "Draft voice settings" into More below about 1400 px, so the bar stays on one row. | s-04-voice.png |
| UX-05 | Review & publish | Three accent buttons are visible at once: "Next: Review by Claude", "Render the video" and "download". The guide allows one per screen. | Keep the one finish-list action as the accent; make the others secondary. | j2-15-publish.png |
| UX-06 | Errors everywhere | Errors show raw exceptions with no next step: "RuntimeError: …" plus "FAILED: …" when the model fails; "Microphone blocked: Permission denied"; "FFError: ffmpeg failed: [in#0 @ 0x…]"; "StageError: TypeError: window.__seek is not a function". | Give one plain sentence and an action, for example "The writing model didn't answer. Check Settings → Writing model, then Retry"; "The microphone is blocked. Allow it in system settings, or use a draft voice". Raw detail goes in a "Details" fold or the job log. | j2-03-model-fails.png, j2-20-record-nomic.png, j8-03-edit-missing.png |
| UX-07 | Dialogs | About 20 actions use native `prompt()`/`confirm()`: new channel name and concept, chapter name, paragraph rewrite instruction, preset and style names, delete project/paragraph/channel, theme apply. They're unstyled, block the whole window, and webview support varies by platform. | Use the app's own dialog component (`.studio-dialog`) with labelled fields, Escape and focus return. | (code: home.js:297, plan.js:105, script.js:210, channels.js:1002 …) |
| UX-08 | Channel setup: Block theme preview | Intermittently fails: the panel shows "StageError: TypeError: window.__seek is not a function at <anonymous>:1:8" and the server logs a 500. It didn't reproduce on a rerun. | Wait for the block runtime before seeking (a race in the preview render), retry once, and show "Preview failed. Try again." | j4-06-block-theme.png |
| UX-09 | Blocks, previewed as a channel | While themed posters render, cards show broken-image alt text ("Lower third / Panel, 16:9 themed preview"). | Show the existing "Poster pending" placeholder until the image loads. | j4-08-blocks-as-channel.png |
| UX-10 | Channel page | Under "Videos in this channel", the empty state says **"No music yet. Add a track above."** | "No videos yet. Start one with + New video." | j4-03-channel.png |
| UX-11 | Settings | One page about 7,000 px long. Speech-to-text (optional) comes before Writing model (essential). Every provider's keys and paths show whatever backend is chosen. The sticky "Save settings" overlaps section headings and is half hidden behind the jobs strip. | Add a section nav, ordered Writing model, Voices, Research, Archives, Speech-to-text and so on. Show only the selected backend's fields, with "Other providers" folded. Sit the save bar above the jobs strip. | j7-01-settings.png, j7-03-settings-2.png, j7-05-settings-4.png |
| UX-12 | Home | "A footage shoot" is disabled with "coming with footage integration", but the same page lists footage shoots and the top bar has Footage. | Either enable it (the guide's Home spec includes it) or explain what's missing in words that match the Footage screen. | j1-02-home.png |
| UX-13 | Focus | There's no global `:focus-visible` style. Outside dialogs and the timeline, focus is the browser's 1 px auto outline, not the guide's 2 px `--cool` ring with a 2 px offset. | Add one global focus ring rule. | — |
| UX-14 | Labels | Review & publish's thumbnail kicker and description textarea have no label (placeholder only). Library's "Add a single file" fields are labelled only by placeholders. | Give every field a micro-label linked with `for`/`id`, as the guide requires. | j2-15-publish.png, j2-22-library-tab.png |
| UX-15 | Footage logger | A "Footage unavailable" box sits under the player while the clip is playing. | Hide it when the proxy plays, or say what's unavailable (the original file?). | j6-02-shoot.png |
| UX-16 | Plan | The 6th chapter column is clipped at the right edge with no scroll cue. Beat titles truncate ("Stock Prices Undergro…"). The thesis is a one-line input that cuts off long text. | Show a horizontal scroll cue or wrap columns; wrap beat titles to two lines; make the thesis an auto-growing textarea. | j2-10-plan.png |
| UX-17 | Check findings | Findings read as debug output: "Numbers disagree: narration [1875, 1870, about 45]; block [1.5 minutes, 5 minutes]. Unmatched: about 45. · open". The shipped example opens with 4 P1s of this kind. | Write it as a sentence: "The block shows 1.5 minutes, but the narration doesn't say it." See guide question G3 on strictness. | j2-15-publish.png |
| UX-18 | Jobs | The background "timeline sound" job opens a card at the top of Review & publish and Script: "Measuring the audio for linear master normalization". The jobs drawer shows internal job ids (j0f31af6862). | Keep background jobs in the jobs strip, unless they belong to the stage. Use plain words ("Mixing the sound"). Drop the ids. | j2-15-publish.png, j8-04-jobs-drawer.png |
| UX-19 | Script check column | Findings are squeezed into a narrow column, and quoted facts join with doubled punctuation ("…to 1868.: The research…"). | Give the text the full row width, with buttons under it, and clean the joined punctuation. | j2-11-script.png |
| UX-20 | Timeline polish (collected during the Phase 17 reviews) | Selecting a section makes the lanes jump down 22 px. The section toolbar can cover the playhead handle, and the drop hint overlaps it. The always-visible nearest + catches drags that start on it. A 4 s overlay at fit zoom is 25 px wide, and its two 8 px handles leave little room to move it. The graphic toolbar sits over the voice lane. A new title card shows a blank tile. | Reserve the toolbar row, keep toolbars clear of the handle and lanes, hide + while dragging, shrink handles on narrow items, and draw the card text on its tile. | t-section-toolbar.png, t-graphic-toolbar.png |

## P3

| id | where | what happens | what it should do |
|---|---|---|---|
| UX-21 | Copy, everywhere | Lowercase controls go against the guide's sentence case: "save project file…", "dismiss", "script · error/done", "previous", "next", "jump to next blank", "check the microphone", "draw all", "loop picture", "the opening slate is not drawn yet", "connect it", "download", "channel setup", "all channels", "+ new video", "← videos", "browse…", "add folder", "choose a file", "add to library", "no folders linked yet". | Do one copy pass to sentence case. |
| UX-22 | Voice | "Microphone setup" and "Draft voice settings" appear in the project bar, and again as an in-page button and a "Voice & draft settings" fold. | Keep one of each. |
| UX-23 | Edit | "Auto-edit · all camera paragraphs" and "Undo auto-edit" show on a project with no camera paragraphs. The inspector's lone "Ask" button isn't explained. | Hide camera tools when no paragraph is on camera; give Ask a label ("Ask Claude about this item"). |
| UX-24 | Visuals | Kind chips sit detached under each list row, doubling its height. Source tabs wrap so "Upload" sits alone on a second row. Footage is the default tab with no footage of the project's own. In the mix bar, Block is green, the "done" colour. | Put the chip inside the row; tabs on one row or scrollable; default to the first useful source; blocks in `--cool`. |
| UX-25 | Blocks: Try it | Field labels show raw types: "title · text", "decimals · enum". | "Title", "Decimals". Types go in a tooltip if they're needed at all. |
| UX-26 | Channels index | A bare list of links, with no look preview, video count or empty-state help. | Cards with the theme swatch, video count and last updated. |
| UX-27 | Home: my own script | The "too short" toast doesn't give the minimum (120 words). The Length selector stays active although length "comes from your script". | "Paste at least 120 words (you have 11)"; disable Length in script mode. |
| UX-28 | Settings | Developer copy: "New-channel cards: Chromium scenes. Channel preview templates marked 'scene' use Chromium; other templates use Pillow." | Remove it or say it plainly. |
| UX-29 | Plan (new project) | "Write the script from this board" is disabled with no reason. | Add "Add at least one beat first" beside it. |
| UX-30 | Undo/Redo | Both stay enabled when there's nothing to undo or redo (noted in T17.1). | Disable them, with a tooltip naming the next step. |

## Guide questions (for the owner)
- **G1. Edit layout.** The guide puts the player first in Edit. With Phase 17
  the timeline is the main tool, so should Edit be timeline-first, with a
  smaller player (see UX-03)?
- **G2. Footage start.** The guide's Home spec lists "a footage shoot" as a
  start option. Is it meant to be enabled now (UX-12)?
- **G3. number_match strictness.** This is the open owner item. The example
  ships with 4 P1 "Numbers disagree" findings on correct content (UX-17).
- **G4. Mid-century and other period looks** (the owner's "great hotels of
  the past" test channel). Colours, panels, rules and radius can all be set
  per channel, and the contrast check works: turquoise on cream was flagged
  at 2.67:1, needing 3:1. Fonts can't: only Inter, Archivo Narrow, EB
  Garamond and JetBrains Mono, plus pack fonts. A small OFL "period faces"
  pack (a 1950s script and a geometric sans) would cover it. Wanted?

## Journeys walked
1. **First run:** setup step 1 and system checks, Home, Projects, the guide
   (j1-*).
2. **Idea to video:**
   - a new project from an idea, with a simulated model failure (j2-01…03);
   - the six stages on the example (j2-10…15);
   - a no-mic record attempt, the Archive and Library sources, and the
     Thumbnail → Upload steps (j2-20…27);
   - the timeline itself was exercised during the Phase 17 reviews.
3. **Bring your own script:** the paste and too-short validation (j3-*). The
   import job itself is stubbed in the harness.
4. **Channels:**
   - created "Grand Hotels" ("great hotels of the past");
   - picked the Kitchen theme for its cream ground;
   - set mid-century colours: cream `#F3E5C8`, walnut `#3B2A1E`, turquoise
     `#2A9D8F`, mustard `#E3A33B`, a 14 px radius, Archivo titles and EB
     Garamond body;
   - previewed the blocks in that look (j4-*).
5. **Blocks library:** browse, detail with Try it, the no-match search
   (j5-*).
6. **Footage:** the shoot list and the logger on a fixture shoot (j6-*).
7. **Settings:** every section, and Packs (j7-*).
8. **Recovery:** a model failure, a missing recording on disk, the jobs
   drawer, a reload mid-job (the job carried on) (j8-*).
9. **1280×720 pass:** Home and the six stages (s-*).

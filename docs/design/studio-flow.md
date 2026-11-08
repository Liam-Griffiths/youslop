# Corkbored studio: design guide

The reference for building the new studio UI (Phase 9) and the features that
plug into it (Phase 10 sponsors, Phase 11 footage, Phase 4 timeline editor,
Phase 7 camera). Written 2026-10-31.

**Status: Approved by the owner on 2026-11-01** (studio flow canvas and this
guide, as they stand). Phase 9 code tickets (T9.3 onward) build from them.

**Mockups (the visual source of truth):**
- Corkbored studio flow canvas: https://claude.ai/artifact/MD9aLnpScZExrv7PuP8FYS
  (ten screens from first run to the finished video, and three scenario screens).
  Snapshot of its artboard sources in `docs/design/mockups/*.dc.html` (2026-11-01):
  inline-styled HTML, read them for layout; `{{...}}` holes are filled by each file's
  `renderVals()` at the bottom (accent `#FF5A1F`, display face Archivo 62% / 800).
- Rostrum app mockup canvas, the original Instrument look this guide keeps:
  https://claude.ai/artifact/NeqUBGKSb8Va4CjbEnwLvw (Episodes, Timeline,
  Review, Channel, Stage)

Where this guide and a mockup disagree, this guide wins for rules (tokens,
behaviour, accessibility) and the mockup wins for layout. Fix whichever is
wrong and note it in the ticket log.

---

## 1. Principles

1. **A serious instrument.** Corkbored is a production tool, not a toy. The
   UI is the Instrument look: near-black, ruled, labelled, one accent. **Cork
   appears only in the logo mark.** No cork textures, sticky-note cards, pins,
   handwriting fonts or paper in the app chrome. (Video looks and scene
   templates may use them; the app does not.)
2. **Showrunner first.** The app takes an idea to a published video. Every
   project screen answers "what is left?" and offers one button that does the
   next step automatically. The user corrects exceptions instead of building
   from scratch.
3. **The model decides, code draws.** Claude writes the script and chooses
   from fixed menus (format, template, shot, layout, cue times). Templates,
   ffmpeg, Chromium scenes and the 3D shot planner draw the frames. The UI
   must make every model decision visible and editable as a plain field.
4. **Cheap to check, expensive to render.** Checks run on the storyboard
   instantly with no model. Previews render one segment at quarter size. A full
   render is an explicit step in Review & publish.
5. **Nothing the user made is ever lost.** Recordings, camera takes and
   footage originals are never deleted or overwritten. Replaced takes go to
   history. Jump cuts strike through; they do not cut the file.
6. **Local first.** Everything works on the user's machine. Network use
   (research, archive search, uploads, model calls) is visible in the status
   area and the jobs strip.
7. **Numbers are data.** Every time, count, size and level is set in the mono
   face with tabular figures, so the eye can scan and compare.

---

## 2. Brand in the app

| Asset | File | Where |
|---|---|---|
| App icon (textured cork tile) | `docs/brand/corkbored-icon.svg`, `-1024.png`, `-256.png` | OS icon, about screen, first run |
| Flat mark (no texture) | `docs/brand/corkbored-mark.svg` (copy in `static/brand/`) | favicon, top bar, anything under 64 px |
| Header lockup | `docs/brand/corkbored-header.svg` | optional; the bar normally sets the wordmark as live text |
| README lockups | `docs/brand/corkbored-light.svg`, `-dark.svg`, banner | docs only |

- **Wordmark:** "CORKBORED" in the display face, uppercase, 22 px in the top
  bar. One word, one colour (`--ink`). No "AI" badge, no accent on "bored".
- **Mark in the top bar:** 24 px flat mark. The pin uses `--accent`, so if
  the accent tweak changes, the pin follows.
- **Regenerate, never redraw:** `python3 docs/brand/src/build.py`.
- **Tagline:** "Idea in. Episode out." Used on Home only.

---

## 3. Design tokens

Put these in `static/styles.css` `:root` (T6.1). Names are the contract; later
tickets refer to tokens, not hex values.

### Colour

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0E0F11` | app background |
| `--panel` | `#16181C` | panels, side columns, cards |
| `--raised` | `#1D2026` | selected rows, secondary buttons, active nav |
| `--line` | `#23262C` | every 1 px border and rule |
| `--line-strong` | `#2E3239` | dashed "add" buttons, tick marks |
| `--ink` | `#F2F2F2` | primary text |
| `--ink-2` | `#C9CDD3` | secondary text in lists |
| `--dim` | `#A0A6AE` | labels, metadata (passes 4.5:1 on `--bg` and `--panel`) |
| `--accent` | `#FF5A1F` | signal orange: one primary action per screen, selection, playhead, P1 |
| `--accent-tint` | `#2A1A12` | background of accent chips |
| `--cool` | `#6FB7FF` | links to elsewhere, P2, scenes, secondary state |
| `--cool-tint` | `#13202E` | background of cool chips |
| `--good` | `#39D98A` | done, verified, healthy |
| `--good-tint` | `#12261C` | background of good chips |
| `--warn` | `#F2B134` | meter warning zone only |
| `--bad` | `#E8776A` | destructive and failed states, removed values in diffs |

Rules:
- **One accent action per screen** (the "Next" button or the stage's main
  button). Everything else is secondary or ghost.
- Colour never carries meaning alone: chips always have text, levels have
  "P0/P1/P2" labels, meters have numbers.
- No gradients in the chrome. No shadows except the 1 px line.

### Type

| Role | Face | Size / weight | Notes |
|---|---|---|---|
| Display | Archivo 800, `font-stretch: 62%` (condensed); switchable to Space Grotesk 500 (T6.1) | 22 px wordmark, 36–44 px screen titles | uppercase, `letter-spacing: -0.01em` |
| UI | Inter | 13 px / 1.5, 500 for emphasis, 600 for primary buttons | sentence case |
| Body (script, prompter) | Inter | 14 px / 1.6 in Script; 34 px / 1.35 in the prompter | |
| Mono | JetBrains Mono | 11–15 px | **all** numbers: times, counts, sizes, levels, file names, keys |
| Micro-label | Inter | 11 px, uppercase, `letter-spacing: .08em`, `--dim` | above fields and sections |

Fonts ship in `resources/fonts` and load with `@font-face` (no network).

### Shape and space

- Radius: **4 px** for buttons, inputs, panels; **2 px** for chips and tiny
  swatches; 50% only for dots, the record button and avatars.
- Borders: 1 px `--line`. Selected item: `--raised` background, or a 2 px
  `--accent` outline for the one thing being edited.
- Spacing scale: 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40 px. Panels pad
  14–20 px; screens pad 20–32 px.
- Hit targets: at least 34 px tall for buttons in dense bars, 44 px for
  primary actions and anything on the record screen.

### Motion

- One easing family: `cubic-bezier(.16, 1, .3, 1)` (expo out), 150–250 ms.
- Nothing in the chrome loops or pulses, except the recording indicator.
- Respect `prefers-reduced-motion`: no slide-ins; instant state changes.

---

## 4. The shell

```
┌ top bar (52 px) ─────────────────────────────────────────────────────────┐
│ [mark] CORKBORED   Projects Footage Library Channels Packs Settings  ·status· Ctrl K │
├ project bar (inside a project only) ─────────────────────────────────────┤
│ / Project title   channel · format · aspect                [secondary] [NEXT: …] │
├ stage bar ───────────────────────────────────────────────────────────────┤
│ 1 · PLAN    2 · SCRIPT   3 · VOICE   4 · VISUALS   5 · EDIT   6 · REVIEW & PUBLISH │
│ 19 beats    34 ¶         34 of 34    14 of 21      not started  —                  │
├──────────────┬──────────────────────────────────────┬───────────────────┤
│ list column  │ work area                            │ source / inspector│
│ (260–300 px) │ (flex)                               │ (320–360 px)      │
├──────────────┴──────────────────────────────────────┴───────────────────┤
│ jobs strip (32 px): Jobs · Render 64% · Labelling 64 of 120 · …          │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Top bar:** mark + wordmark (links Home), app screens, status
  (Claude backend, voice engine, Chromium), `Ctrl K` palette hint. In a project
  the app-screen nav collapses into the breadcrumb and the project bar appears.
- **Project bar:** title, one line of mono metadata, at most two secondary
  buttons and **one** accent "Next: …" button that goes to the next stage
  (or runs the stage's main action when it is not done).
- **Stage bar:** six stages, each with number · name and a one-line mono
  state from `GET /api/projects/{pid}/stages` (T9.4). Current stage: 2 px
  accent underline. Done: state in `--good`. Current: state in `--accent`.
  Future: `--dim`. Stages are always clickable; nothing is locked.
- **Three columns:** list (what you are working through), work area (the
  selected thing, big), right panel (sources for Visuals, inspector for Edit,
  checks for Script). Columns wrap below 1100 px: right panel drops under the
  work area, list becomes a horizontal strip.
- **Jobs strip:** always visible, mono, one item per running job, click opens
  the jobs drawer (T9.12). Shows token cost for model jobs.

---

## 5. Components

Each component appears in the mockups; build them once in
`static/ui/*.js|css` (after T4.1's split) and reuse.

| Component | Spec |
|---|---|
| Primary button | `--accent` bg, `--bg` text, 600, radius 4, 34–44 px. One per screen. |
| Secondary button | `--raised` bg, 1 px `--line`, `--ink` text. |
| Light button | `--ink` bg, `--bg` text, 600: used for "Fix", "Apply", "Preview" inside a panel that already has an accent action elsewhere. |
| Ghost / link | no bg, `--dim`, underline on hover. Destructive ghost ("Turn off", "Dismiss") never red unless it deletes data (it never does). |
| Dashed add | transparent, 1 px dashed `--line-strong`, `--dim`, left-aligned: "Import a shoot", "Add a source". |
| Segmented control | 1 px `--line` group; selected segment `--raised` + 500 weight; `aria-pressed`. Used for Short/Long, cut style, read variant. |
| Chip | 11 px 600, radius 2, tinted bg + strong fg: stage (accent/good/cool/neutral), kind (3D, archive, scene, footage, camera), level (P0 `--bad`, P1 accent, P2 cool). |
| Micro-label | see type. Every field has one, linked with `for`/`id`. |
| Input / select | `--bg` (inside panels) or `--raised` (bars), 1 px `--line`, radius 4, 7–8 px padding; mono for times and numbers with a unit suffix in `--dim`. |
| Stage tab | see shell. |
| List row | grid, 6–8 px padding, radius 4; selected: `--raised`; meta line in mono `--dim`; state at right in a semantic colour. |
| Finding row | chip · mono time · message · Fix / Dismiss / Keep. Same row in Script, Edit, Review. |
| Proposed change | mono block on `--bg`: `field  old → new`, old in `--bad` struck, new in `--good`, one-line reason, then Apply / Dismiss / Keep as warning / Make this a rule. |
| Progress | 4–6 px bar on `--line`, accent fill; mono numbers above ("14 of 22 · 64% · about 3 min"). Per-segment grid for renders. |
| Visual mix bar | 10 px stacked bar of visual kinds + mono legend + the format rule in `--dim`. Top of Visuals. |
| Sequence strip | the whole video as blocks sized by duration, coloured by kind, current block outlined in accent. Bottom of Visuals. |
| Timeline lane | 104 px label column + lane; items radius 3; titles and sponsor use accent tint; notes are 0.8 s ticks; playhead 2 px accent. |
| Keyboard hint | mono 11 px in a 1 px `--line-strong` box: `J K L`, `I`, `O`, `1–9`. |
| Empty state | one sentence saying what goes here and the action that fills it; never an illustration. |

Accessibility (applies to every component): real `<button>`, `<a>`,
`<input>` + `<label>`; `aria-label` on icon-only buttons; text contrast
4.5:1 (all tokens above pass on `--bg` and `--panel`); visible focus ring
(2 px `--cool`, offset 2 px); every action reachable by keyboard; no colour-only
meaning.

---

## 6. Information architecture

### App screens (top bar)

| Screen | Route | Contents | Tickets |
|---|---|---|---|
| Home / Projects | `#/` | Start panel, projects table, shoots list | T9.5 |
| Footage | `#/footage`, `#/footage/<shoot>` | shoots, logger | T11.1–T11.8 |
| Library | `#/library`, `#/library/blocks` | stock and linked folders; the app-wide block library | T12.8, T12.9 |
| Channels | `#/channels/<id>` | look, voice, rules, sponsors, intro/outro | T10.2, T3.6 |
| Packs | `#/packs` | content packs | T8.2 |
| Settings | `#/settings` | everything in `.env`, first run again | T9.13 |

### Project stages

| # | Stage | Route | Replaces today's | Main button |
|---|---|---|---|---|
| 1 | Plan | `#/p/<id>/plan` | outline part of Script | Write the script |
| 2 | Script | `#/p/<id>/script` | Script | Next: voice |
| 3 | Voice (Camera for piece-to-camera) | `#/p/<id>/voice` | Record | Draft the rest / Next: pictures |
| 4 | Visuals | `#/p/<id>/visuals` | Media, Cast, Stage | Fill the rest / Plan all shots / Auto-edit cutaways |
| 5 | Edit | `#/p/<id>/edit` | Render tab's Timeline | Next: review & publish |
| 6 | Review & publish | `#/p/<id>/publish` | Thumbnail, Render, publish panel | Publish when ready |

Old routes redirect: `script→script`, `media|cast|stage→visuals`,
`record→voice`, `render→edit`, `thumb→publish`.

**Why Voice before Visuals:** picture lengths come from real takes, and cuts,
titles and cues land on spoken words (word timings, T0.6/T0.10). Choosing
pictures first means re-timing them after recording. A draft voice (local TTS)
counts as a take, marked "draft", so Visuals can start before the user records.

---

## 7. Screen by screen

Each entry: purpose · layout · data · states · ticket. Mockup names in brackets.

### 00 First run [FirstRun]
- Purpose: get a new machine to a working state without reading docs.
- Layout: step list left (data folder, Claude, voice for drafts, research,
  YouTube), one step at a time right, live system checks (ffmpeg, Chromium,
  GPU/RAM, mic).
- Data: `config.ffmpeg_ready`, `llm.resolve_backend`, `tts.status`,
  `paths.describe`, `sysinfo`.
- Rules: no download without a click; every step skippable; reopen from
  Settings. Ticket T9.13.

### 01 Home [Main]
- Start from: idea · my own script · a footage shoot · a saved format · open a
  `.corkbored` file. Shape: Short 9:16 or Long 16:9. Length, research depth,
  channel, format. Optional "Use footage from <shoot>".
- Projects table (title, channel, stage chip + detail, length, updated) and a
  shoots list with state.
- Ticket T9.5.

### 02 Plan [Plan]
- Sources column (research results with how each is used) · outline as
  **chapter columns of plain beat cards** · the hook line with "works muted"
  check. Beats carry kind tags (footage, archive, data, interview).
- Drag beats between chapters (keyboard: Alt + arrows). "Write the script"
  regenerates only changed beats.
- Ticket T9.6.

### 03 Script [Script]
- Paragraph cards: number, narration, picture note, title, words · time,
  inline findings with Fix/Dismiss, Rewrite / Split / Start a chapter. Chapter
  dividers. Right: words-only check summary and channel rules.
- Keyboard: J/K move, Enter edit, Esc leave.
- Ticket T9.7.

### 04 Footage [Footage] (app screen, used between Script and Visuals when the user shoots)
- Labels column (user vocabulary with number keys, model labels, show
  usable/flagged/rejected) · player on the proxy with in/out bar and key
  hints · clip inspector (labels, quality, best of duplicates, matched
  paragraph) · clip grid grouped by label.
- Shot list from the script can be printed before filming (T11.7).
- Tickets T11.1–T11.8.

### 05 Voice [Voice] (Camera for piece-to-camera)
- Paragraph list with take state (mic, draft voice, recording, not voiced;
  sponsor reads included) · prompter (34 px, current sentence bright, rest
  dim) with record button, level meter, peak and room readout · takes panel:
  every take kept, "in the cut" vs history, "Use this take".
- Mic setup is a drawer, not a page section.
- Camera variant: same layout with a camera preview above the prompter (T7.2).
- Ticket T9.9.

### 06 Visuals [Visuals and the three scenario screens]
- Same skeleton for every format: visual mix bar · list of picture groups (or
  paragraphs, or beats) with a kind chip · big preview of the selected one
  with its controls · **source panel that adapts to the format** · sequence
  strip.
- See section 8 for the per-format behaviour. Ticket T9.8.

### 07 Edit [Edit]
- The Timeline workspace: player · inspector (whatever is selected: title,
  cue, picture, sponsor, chapter) · lanes: Pictures, Voice, Sponsor, Titles,
  Captions, Chapters, Music, Notes · compact check bar.
- Selecting a sponsor shows: sponsor, Short/Long, placement with the suggested
  spot, voice, music dip, disclosure, description effect; Preview read, Edit
  copy, Turn off.
- Tickets T9.10, Phase 4 (T4.3–T4.8), T10.6.

### 08 Review & publish [Publish]
- Six-step finish list: Check → Review by Claude → Render → Thumbnail →
  Description & chapters → Upload. Each step shows state and its own button.
- Render: mono progress, per-segment grid (finished segments kept; resumes),
  pause. Thumbnail: three options at phone size. Description: chapters from the
  edit (sponsor chapter included), sponsor block, sources, paid-promotion flag.
  Upload: channel, visibility/schedule, starts after verification.
- Ticket T9.11; T3.2, T3.3, T5.6, T5.7, T10.7.

### 09 Finished video [Done]
- Player with chapter bar · file (path, length, picture, size, render time,
  Show in folder, captions) · verified-after-render list · YouTube state ·
  next steps (cut a Short from the hook, save the look as a format, unused
  clips).
- Ticket T9.11 (end state), T5.7.

---

## 8. Visuals by format

The left list, preview, mix bar and sequence strip never change. The source
panel and preview controls do.

| Format | Base layer | Source panel tabs (first = default) | Preview controls | Stage button |
|---|---|---|---|---|
| Documentary with footage | footage clips + archive stills | Footage · Archive · Library · Scenes · Upload | camera move, source in, speed, lock | Fill the rest from footage |
| 3D explainer (+ archive) | 3D shots | 3D (cast + shot options) · Archive · Footage · Library · Scenes · Upload | model, shot, subject part, section cut + labels; solver checks shown in mono (subject fill, parts clipped, label overlap) | Plan all shots |
| Piece to camera (vlog) | camera takes, jump-cut | Layout · Footage · Screens · Library · Scenes | layout per paragraph (full face, split, cutaway over voice, picture in picture), jump-cut strip with Natural/Tight | Auto-edit cutaways |
| Vertical data Short | Corkbored blocks + data | Blocks (built in, packs, mine; third-party only if enabled, labelled) | template, headline, data table from a research source, draw-in word, caption style, safe-area and number-match checks | Preview all at ¼ size |
| Essay / board / drawn cuts | the format's own drawing | Archive · Library · Scenes | format-specific fields (existing) | Fill the rest |

Rules:
- **Every format declares a visual rule** shown in the mix bar ("3D for how
  it works, archive for who and when, scenes for numbers").
- **Numbers are drawn, never searched for.** A paragraph whose narration
  contains a statistic gets a scene suggestion first.
- **Cutaways come from words.** In camera projects, nouns and places in the
  take's word timings are matched against footage labels; the suggestion names
  the word ("paper map").
- **Kinds** (for chips and the mix bar): footage, archive, library, scene,
  3D, camera, drawn. Each kind has one colour: camera `--ink`, 3D and footage
  cutaways `--accent`, scenes `--cool`, archive/library `--ink-2`.

---

## 9. Blocks

- Scenes are built from **Corkbored blocks** (Phase 12): a folder with
  `block.html` and `block.json` (typed variables, aspect variants, duration
  rules, word-timed beats, licence). Built in, from packs, or the user's own.
- Every block passes `block check` (text fit at max lengths, safe areas,
  contrast, no remote assets, deterministic seek) and has locally generated
  previews.
- **Third-party blocks (Hyperframes catalog) are temporary and quarantined**
  (T2.7c): off by default, labelled "third-party" with their licence, never
  showing upstream previews or branding, never in packs or defaults; retired
  by T12.7. Our runtime stays compatible with that composition style.
- The model chooses blocks by id and fills variables; it writes a new block
  only on request (T12.6), once, and the result is reused for free.
- **Blocks are app-wide** (owner, 2026-11-08). Library > Blocks is the one
  place to browse, preview (local posters and quarter-size loops) and try a
  block with your own text; Visuals and the channel page open the same
  browser (T12.8). Channels and projects customise with **presets** (saved
  values and pins), never copies of block code; "Duplicate as mine" is the
  only way to change code (T12.9).

## 10. Sponsors

- A sponsor read is a segment, not a paragraph: its own copy, take, scene and
  placement (pre after the hook, mid at a paragraph boundary, end before the
  outro). Short (5–10 s) or Long (30–60 s). (T10.1)
- Sponsors live on channels; the house sponsor (Corkbored) is built in
  (T10.2). Opt-in until the owner decides otherwise.
- Voice stage lists sponsor reads with the paragraphs. Edit has a Sponsor lane.
  Review & publish shows the sponsor chapter, the description block and the
  paid-promotion flag (paid sponsors only).
- Checks (T10.5): no long read in the first 60 s; not between a question and
  its answer; disclosure on screen for paid sponsors; music under the read
  dips 6 dB.
- Reference: `static/scene/sponsor/house_short.html`,
  `docs/brand/mockups/sponsor-house-short.mp4`.

---

## 11. Footage

- A shoot is linked (originals untouched) or copied; proxies and filmstrips
  are made in the background; the jobs strip shows progress.
- Clips come from shot detection; quality flags (blur, shake, exposure,
  audio) hide misfires without deleting; near-duplicates are grouped with a
  "best" pick.
- Labels: the user's vocabulary (number keys) first, model labels second.
  Labelling shows its token estimate before it runs.
- In Visuals, footage is a source tab ranked ahead of archives; a chosen clip
  stores source + in/out; renders cut from the original.

---

## 12. Copy

- Plain, specific, sentence case. "Next: pictures", not "Proceed".
- Say what happened and what is left: "14 of 21 chosen", "3 notes, 2 applied".
- Never "AI", "magic", "smart". Name the thing: "Claude", "the shot planner",
  "the check".
- Numbers in mono with units: `0:14.6`, `−14.1 LUFS`, `1.21 GB`.
- Placeholders in brackets when a fact is unknown: `[amount]`, `[video-id]`.
- No emoji anywhere in the chrome.

---

## 13. Where the model is used (and where it is not)

Show the cost; keep it low by design.

| Step | Model? | How it is kept cheap |
|---|---|---|
| Research, outline, script | yes (largest share) | one pass; rewrite only changed beats/paragraphs |
| Visual plan (which kind, which template, which shot) | yes, once | choices from fixed menus, returned as storyboard JSON |
| Footage labels | yes, once per shoot | batched contact sheets, cached per clip |
| Clip matching | mostly no | lexical match on labels; optional re-rank of top 20 |
| Blocks, scenes, charts, 3D framing, jump cuts | **no** | code: Jinja + Chromium, ffmpeg, the shot planner's solver |
| Check | **no** | `check.py` on the storyboard |
| Review | yes, targeted | at most 12 frames per pass (`--full` on request) |
| Fixes | small | field-level proposals, not regenerated code |

Proposed follow-up ticket: a per-project **token meter** (tokens per stage,
shown in Review & publish and the jobs strip) so the cost claim is measured.

---

## 14. Build order

1. T4.1 split the front end into files (no behaviour change).
2. T9.2 screenshot + console harness (every later ticket uses it).
3. T6.1 tokens and fonts (section 3), T6.2 logo wiring (section 2).
4. T9.1 owner approval of this guide and the canvas.
5. T9.3 shell and routes, T9.4 stages API.
6. Stages in flow order: T9.5 Home, T9.6 Plan, T9.7 Script, T9.9 Voice,
   T9.8 Visuals, T9.10 Edit, T9.11 Review & publish; then T9.12 jobs/palette,
   T9.13 first run.
7. T2.7c (quarantine the catalog) early; Phase 12 blocks T12.1–T12.3 alongside Phase 9.
8. Phase 10 and Phase 11 data tickets can run in parallel from now; their UI
   tickets plug into T9.8 / T9.10 / the Footage screen.

**Verify every UI ticket** with
`CORKBORED_DATA=$(mktemp -d) .venv/bin/python scripts/ui_snapshots.py --out /tmp/ui`
(T9.2): no console errors, a PNG per route, compared against the mockup.

---

## 15. Open decisions (owner)

- Display face: condensed Archivo (mockups) or Space Grotesk (T6.1 ships both
  behind a switch).
- House sponsor read on new projects: opt-in (current) or opt-out (T10.2).
- T1.7 mastering: keep single-pass loudnorm or move to two-pass linear.
- Approval of this guide and the canvas (T9.1).

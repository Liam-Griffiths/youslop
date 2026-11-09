# Progress

Status values: `todo`, `doing`, `done`, `blocked`, `parked`, `dropped`. Update the row when you
start and when you finish. Keep the newest note in the Notes column; the
full log lives in the ticket file.

Last updated: 2026-10-31 (Codex gpt-6.1-sol implementing, Claude Opus 5.5 reviewing)

> **Codex limit, 2026-10-31 14:50 PDT:** the 5-hour Codex window hit 99% after T4.2 (weekly 18%).
> Resumed 18:17 PDT at T4.1 after the window reset; done since then: T4.1, T2.7c, T6.1, T6.2, T9.2, T10.1, T11.1–T11.3, T4.3–T4.8, T10.3, T10.5, T11.8, T12.1, T12.2, T11.4.
> **2026-11-01 01:55 PDT:** owner made the scene builder the priority. T2.8 and T2.9 done. Codex 5-hour window at 89% (weekly 45%); paused until it resets (~04:45 PDT), then T2.10, T5.3a on the builder, T12.3. T10.2/T10.4/T10.7 wait on the house-read decision; Phase 9 waits on T9.1 sign-off.
> **2026-11-01 ~05:10 PST:** window reset; T2.10, T5.3a–e done (all drawn cuts on the builder; each preview within ~2x Pillow, Group Chat cold ~2.5x, see its log). Builder fixes along the way: parallel passes, cheap probe signatures, stills filtered once, ground overflow, media blur. Next: T12.3 batches 2–4, T5.4, T5.5, T6.3.
> **2026-11-01 ~06:30 PST:** T12.3 batches 2 and 3 done (27 core blocks). Codex 5-hour window at 92% (weekly 60%); paused until it resets (~08:40 PST), then T12.3 batch 4, T5.4, T5.5, T6.3.
> **2026-11-01 ~09:40 PST:** window reset at 08:24; T12.3 batch 4 (31 core blocks, contact sheet `docs/blocks/core-v1.png`), T5.4, T5.5 and T6.3 done. Codex 5-hour window ~25%, weekly ~63%. Queue empty apart from owner decisions: T9.1 sign-off, house-read opt-in (T10.2/T10.4/T10.7), T1.7 mastering, T6.4 visual review.
> **2026-11-01 ~14:50 PST:** since the 13:25 reset: T7.4, T8.3, T7.5, T7.7, T10.6 done. Remaining tickets wait on the owner (T9.1 sign-off, house-read opt-in for T10.2/T10.4/T10.7, T8.3 step 3, T6.4) or are optional (T7.8 stretch, T2.7b temporary). Codex 5-hour 40%, weekly 79%.
> **2026-11-01 ~18:45 PST:** owner approved T9.1. T9.3–T9.10 done (shell, stages API, Home, Plan, Script, Voice, Visuals, Edit). Codex 5-hour 87% (paused for the reset), weekly 87%: T9.11 and maybe T9.12 before the weekly stop at ~90%; T9.13, T11.5/6, T12.5 wait for the weekly reset. UI harness flake noted in NOTES.md.
> **2026-11-01 ~19:00 PST:** paused by the owner after T9.11. Next: T9.12 (not started), T9.13, then T11.5/T11.6/T12.5 and the owner-decision tickets. Codex weekly 88%. Owner plans user testing once the ticket list is complete.
> **2026-11-08:** owner decisions: house read opt-in (T10.2/T10.4/T10.7 unblocked); packs permissive, MIT (T8.3 step 3 reopened); mastering two-pass linear loudnorm approved (T1.7 reopened, owner listens to one quarter-size preview); T6.4 closed (dropdown contrast fixed); T0.10 parked; T7.8 and T2.7b dropped. Queue: T9.12, T9.13, T11.5, T11.6, T12.5, T12.7, T10.2, T10.4, T10.7, T8.3 step 3, T1.7; then user testing.
> **2026-11-08 (later):** owner asked for an app-wide block library: T12.8 (top-level Blocks screen `#/blocks`, posters, motion preview, try-with-your-text, use/pin/duplicate) and T12.9 (channel and project presets). T12.5 now builds on T12.8. Queue: T9.12, T9.13, T11.5, T11.6, T12.8, T12.5, T12.9, T12.7, T10.2, T10.4, T10.7, T8.3 step 3, T1.7; then user testing.
> **2026-11-08 (night):** T9.12, T9.13, T11.5, T11.6 done. Owner approved T12.10a/b (block overlays on any picture: blocks over footage, planned and edited). Queue: T10.2, T10.4, T10.7, T8.3 step 3, T1.7; then user testing.
> **Owner decision pending (T12.8c log):** "Duplicate as mine" cannot fork built-in blocks: none of the 39 pass the user-block sandbox. Choose (a) convert built-ins over time, (b) trust unedited forks of built-ins, or (c) presets only. The button is disabled with a reason until then.
> **2026-11-08 (morning): queue complete; ready for user testing.** Done since the night note: T12.8 (+b, c), T12.5, T12.10a/b/c, T12.9 (+b), T12.7, T10.2, T10.4, T10.7, T8.3 step 3, T1.7 (implemented; owner listens). Owner items: (1) listen to the T1.7 before/after section and keep or revert the linear master; (2) decide "Duplicate as mine" for built-in blocks (T12.8c log); (3) first real paid-sponsor upload confirms the YouTube flag path (T10.7). Codex 5-hour ~40%, weekly ~19%.
> **2026-11-08 (afternoon):** owner rethink of video styles around blocks. Decisions: mix kinds of picture within a video; "Design a style" becomes "Design a block"; block themes per channel or standalone video, with previews; more blocks (inspired by the HyperFrames registry, clean-room); fix the block preview (doesn't play in the app window: H.264 previews, no expand). Queue: T12.11, T12.12a, T12.12b, T13.1, T13.2, T13.3, T13.4, T12.13 batches A–E. T13.5 later.
> **2026-11-08 (evening):** owner asked for clipping of long recordings (podcasts, streams) into short-form clips: Phase 14 (T14.1–T14.6), queued after T12.13. Speech-to-text: support any installed engine (decided same evening).
> **2026-11-08 (night):** owner asked for first-class local models (no frontier model needed). LM Studio backend landed in f2cef05; live runs on Granite 4.1 8B and Qwen 3.5 9B produced Phase 16 (T16.1–T16.5) and a step in T15.2. T16.3 done. Queue: T16.1, T16.2, T16.4, T16.5, then T12.13 C–E, Phase 14, T15.1/T15.2. Codex 5-hour reset, weekly 33%.
> Owner checks collected per row below.

## Phase 0: foundations

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T0.1 | Brand module and env alias helper | M | — | done | 2026-10-31 Codex; 28 unit tests |
| T0.2 | Data folder compatibility | S | T0.1 | done | 2026-10-31 Codex; falls back to the youslop folder |
| T0.3 | Project file and bundle compatibility | S | T0.1 | done | 2026-10-31 Codex; .corkbored export, reads .youslop |
| T0.4 | Mechanical rename | M | T0.1, T0.2, T0.3 | done | 2026-10-31 Codex; owner: eyeball desktop window + temp C icon; GitHub repo rename is manual |
| T0.5 | Test scaffold and graph goldens | M | — | done | 2026-10-31 Codex; 74 unit tests 0.5s, graph goldens, 1 opt-in visual test |
| T0.6 | Word timestamps on takes | M | T0.5 | done | 2026-10-31 Codex; estimates for now, timed path ready for T0.10 |
| T0.7 | Storyboard contract and CLI skeleton | M | T0.5 | done | 2026-10-31 Codex; 104 tests; gap: run.sh skips server marker (see log) |
| T0.8 | Re-measure the render memory cap | S | — | done | 2026-10-31 measured essay 2058 MB, kenburns 1406 MB; cap 2500/1500 |
| T0.9 | CLAUDE.md and repo hygiene | S | T0.7 | done | 2026-10-31 Codex; CLAUDE.md added (T0.10 marked blocked: owner A/B) |
| T0.10 | Kokoro model with word timings | S | T0.6 | parked | owner 2026-11-08: parked; revisit after user testing |

## Phase 1: doctrine and check

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T1.1 | FrameSpec dataclass | M | T0.5 | done | 2026-10-31 Codex; 119 tests |
| T1.2 | Theme defaults for frame | S | T1.1 | done | 2026-10-31 Codex; 124 tests |
| T1.3 | Prompt block and hook gate | M | T1.1 | done | 2026-10-31 Codex; 145 tests; owner: one real-LLM outline run to eyeball the hook |
| T1.4 | ffmpeg camera vocabulary and title timing | M | T1.1, T0.5 | done | 2026-10-31 Codex; 163 tests; preview checked by Claude, owner: watch a join |
| T1.5 | check.py findings | L | T1.1, T0.6, T0.7 | done | 2026-10-31 Codex; 14 rules, 189 tests; real project: P0 0 / P1 12 / P2 13 |
| T1.6 | Check in the UI, CLI and render gate | S | T1.5 | done | 2026-10-31 Codex; panel checked headless; owner: click through render gate |
| T1.7 | Audio doctrine defaults | S | T1.1 | blocked | 2026-11-08 two-pass linear master implemented + measured on real voice (gap 17.9 → 18.3 dB at default; master ~1.3 dB quieter); owner: listen to the before/after clips |

## Phase 2: scene engine

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T2.1 | CDP capture mode in the stage runner | L | T0.5 | done | 2026-10-31 Codex; visual test passes; 10.9 fps at 1080p, 15.5 fps quarter |
| T2.2 | Scene runtime and vendored GSAP | M | — | done | 2026-10-31 Codex; GSAP 3.13.0 vendored; browser checks 17/17 |
| T2.3 | scenes.py and Jinja templates | M | T2.1, T2.2 | done | 2026-10-31 Codex; needs jinja2 (installed); 227 unit + 3 visual pass |
| T2.4 | Render branch point for scenes | M | T2.3 | done | 2026-10-31 Codex; 239 tests; scene preview renders (checked by Claude) |
| T2.5 | Migration: outro and chapter cards | M | T2.4 | done | 2026-10-31 Codex; outro compared by Claude; owner: chapter card in Timeline |
| T2.6 | Migration: intro slates | M | T2.5 | done | 2026-10-31 Codex; 4 intro scenes checked; owner: Dossier lost its stamp, Folio kicker contrast |
| T2.7 | Catalog fetcher | S | T2.3 | done | 2026-10-31 Codex; real catalog search works |
| T2.7b | Make fetched Hyperframes blocks render offline | S | T2.7 | dropped | owner 2026-11-08: dropped (catalog retired by T12.7) |
| T2.8 | Scene builder: layers, motion as data, one compositor | L | T2.4, T5.1, T5.2a, T5.2c | done | 2026-11-01 Codex + review; 60s/40 layers in 7.3s (vs ~2min every-frame), 22KB graph |
| T2.9 | Move captions, boards, diagrams, custom slides onto the builder | M | T2.8 | done | 2026-11-01 Codex + review; board 7.2s, essay 10.9s cold / 6.7s warm; four compositors deleted |
| T2.10 | Blocks, cards and HTML slides through the builder | M | T2.8 | done | Blocks/cards/HTML on builder; lower third 1.55 s at 1080p; zoompan skipped without camera |
| T2.7c | Quarantine the third-party catalog | S | T2.7 | done | 2026-10-31 Codex; off by default, metadata allowlist hides previews; UI gating waits for a catalog UI |

## Phase 3: review loop and agent surface

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T3.1 | Snapshots and contact sheet | M | T0.7, T1.5 | done | 2026-10-31 Codex; labels moved under frames by Claude; 298 tests |
| T3.2 | Claude vision review and REVIEW.md | M | T3.1 | done | 2026-10-31 Codex; mocked only, owner: one real review; suite now 2.7s |
| T3.3 | Fix routing | M | T3.2 | done | 2026-10-31 Codex; 317 tests (3.4s); UI rows checked headless |
| T3.4 | Ask the agent packet | M | T3.1 | done | 2026-10-31 Codex; 334 tests; owner: try Ask the agent copy in the desktop window |
| T3.5 | CLI full loop, ops.py and SKILL.md | M | T0.7, T1.6, T3.2 | done | 2026-10-31 Codex; ops.py, doctrine, corkbored-producer skill; render/publish split to T3.5b |
| T3.5b | Render and publish shared ops and CLI | S | T3.5 | done | 2026-10-31 Codex; full CLI render needs --full --yes; 361 tests |
| T3.6 | Learning loop: rules, rejected looks, formats | S | T1.1, T3.2 | done | 2026-10-31 Codex; 368 tests; owner: try rules/rejected-look controls |

## Phase 4: timeline editor

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T4.1 | Split app.js and timeline.js into files | M | — | done | 2026-10-31 Codex; 20 files under static/js, lines preserved; owner: click through every tab + timeline playback |
| T4.2 | Retime fields in the schema | S | T0.6 | done | 2026-10-31 Codex; 391 tests; skill reference regenerated |
| T4.3 | Selection and per-kind inspector | M | T4.1, T4.2 | done | 2026-10-31 Codex; one selection, per-kind inspector, titles lane, keys; fixed music select; owner: try title timing edits |
| T4.4 | Layers rows | M | T4.3, T0.7 | done | 2026-10-31 Codex; layer rows (titles/cues/chapters/music/stings/notes/sponsors), hide in preview; owner: play with a layer hidden |
| T4.5 | Drag and resize timing | M | T4.4 | done | 2026-10-31 Codex; drag/resize titles, gaps, cues, chapters with snapping; storyboard kept lean; owner: try snapping and Esc |
| T4.6 | Razor (keeps audio) | M | T4.3, T0.6 | done | 2026-10-31 Codex + review fixes (spoken-number timings, snap to real pauses); originals kept; owner: try a mic take |
| T4.7 | Variables panel | S | T4.3, T1.1 | done | 2026-10-31 Codex; variables panel (colours/copy/frame, project or channel scope); owner: slates now follow project style |
| T4.8 | Quick wins: search, suggest chapters | S | T4.1 | done | 2026-10-31 Codex; home search/filter/sort, suggest chapters (no model); fixed beat title casing |
| T4.9 | Keep every take | S | — | done | 2026-10-31 Codex; audited: no take deleted or overwritten; owner: try earlier-takes UI |

## Phase 5: migrations, resume, verify

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T5.1 | Essay captions as a scene | M | T2.4 | done | 2026-10-31 Codex, 2 rounds; plates once per phrase + ffmpeg motion, faster than Pillow; owner: T0.8 RSS re-measure needs a full render |
| T5.2a | Board templates as scenes | M | T2.4, T2.5 | done | 2026-10-31 Codex, 2 rounds + review fixes; 2.3x faster than Pillow, pen write-on kept; owner: watch one board video |
| T5.2b | Diagrams as SVG scenes | M | T5.2a | done | 2026-11-01 Codex; stills match Pillow; owner: boxes are cleaner rectangles than Pillow's pen corners |
| T5.2c | Custom slides through a scene template | S | T5.2a | done | 2026-11-01 Codex, 2 rounds; text baselines now match Pillow |
| T5.2d | Custom slides written as sanitised HTML | M | T5.2c | done | 2026-11-01 Codex (high); allowlist rebuild, reject-not-strip, CSP; reviewer probes all rejected |
| T5.2e | Real text measurement for scenes | S | T5.2a, T1.5 | done | 2026-11-01 Codex + review; overflow caught on real Chromium; small_text one per paragraph; owner: board body text is 33-40px |
| T5.3a | Drawn cut to scene: Loudmouth | L | T2.8, T0.6 | done | Loudmouth on the builder: cold 8.0 s, warm 5.6 s (Pillow 4.3 s); frames match Pillow |
| T5.3b | Drawn cut to scene: Flameboat | L | T5.3a | done | Flameboat on the builder: cold 5.7 s, warm 3.4 s (Pillow 3.3 s); code/terminal/diagram cues not yet seen in a browser |
| T5.3c | Drawn cut to scene: Ticker | L | T5.3b | done | Ticker on the builder: cold 3.1 s, warm 2.25 s (Pillow 2.0 s); all cue kinds checked; empty-ground and ground-overflow builder fixes |
| T5.3d | Drawn cut to scene: Group Chat | L | T5.3c | done | Group Chat on the builder: warm 2.9 s (Pillow 2.2 s); cold ~5-6 s misses 2x target, follow-up noted; bubble alignment, background blur, position-free plate keys |
| T5.3e | Drawn cut to scene: Casefile | L | T5.3d | done | Casefile on the builder: cold 7.5 s, warm 4.0 s (Pillow 3.9 s); cork, lamp, greyscale prints, cards |
| T5.4 | Thumbnails as a scene | M | T2.4 | done | 2026-11-01 Codex (2 rounds); 12 templates match Pillow; ~1 s per thumbnail; Pillow fallback |
| T5.5 | 3D stage under CDP | M | T2.1 | done | 2026-11-01 Codex; revised for the builder: push unchanged (SSIM 1.0), __seek still SSIM 0.995, title overlay +1 s |
| T5.6 | Resume a failed render | S | T0.5 | done | 2026-10-31 Codex; keyed segment cache, atomic publish, Resume button; owner: interrupt a real render and resume |
| T5.7 | verify.py after render | S | T0.6 | done | 2026-10-31 Codex + review: fades/dips under 1s ignored, bitrate P2; real render reports one P2 |

## Phase 6: brand rollout

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T6.1 | Instrument design tokens and fonts | S | T0.4 | done | 2026-10-31 Codex; Instrument tokens, Archivo/Space Grotesk switch; owner: pick a face from compare/ shots, check desktop window |
| T6.2 | Mark, favicon and app icon | S | T0.4 | done | 2026-10-31 Codex; cork/post-it mark in header, favicon, icons regenerated; owner: check launcher icon |
| T6.3 | Copy, README and mockup | S | T6.1, T6.2 | done | 2026-11-01 Codex; README, copy pass, scene card defaults for new channels; mockup side-by-side moved to T6.4 |
| T6.4 | Review studio against the mockup | S | T6.3 | done | owner 2026-11-08: closed, superseded by Phase 9; dropdown contrast fixed (light text on light options) |

## Phase 7: camera (piece to camera)

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T7.1 | Camera takes in the data model | M | T0.5, T4.9 | done | 2026-11-01 Codex; synthetic A/V sync within a frame; owner: first-word lip sync on a real webcam take |
| T7.2 | Record on camera in the Record tab | M | T7.1 | done | 2026-11-01 Codex + review fix (WebM duration); browser flow verified with fake devices; owner: Linux desktop permissions, real webcam |
| T7.3 | Camera paragraphs in the render | M | T7.1, T0.5 | done | 2026-11-01 Codex; synthetic A/V sync within a preview frame; owner: real webcam paragraph by eye and ear |
| T7.4 | Trims and jump cuts on camera takes | M | T7.3, T4.4 | done | review: button styling, source strip at ruler scale |
| T7.5 | Cutaways and layouts over camera | M | T7.4, T2.4 | done | includes the Auto-edit button; review: PIP mask drawn once; owner: Auto-edit on real paragraphs |
| T7.6 | Camera look and checks | S | T7.3, T1.5 | done | 2026-11-01 Codex; bounded look matching, deterministic checks; owner: two differently lit real takes |
| T7.7 | Talking-head videos end to end | S | T7.2, T7.3, T7.4 | done | owner: record three paragraphs on camera from a faithful import |
| T7.8 | Long-take import (stretch goal) | L | T7.1, T7.2, T7.4 | dropped | owner 2026-11-08: dropped |

## Phase 8: content packs

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T8.1 | Pack format and loader | M | T0.2, T2.3 | done | 2026-11-01 Codex; pack blocks sandboxed and browser-checked; bad items listed, not offered |
| T8.2 | Packs screen and install from a file | S | T8.1, T6.1 | done | 2026-11-01 Codex; staged, validated install; Packs screen checked in Chromium; drag and drop untested |
| T8.3 | Pack tooling, format spec and first free pack | S | T8.1, T8.2, T0.7 | done | 2026-11-08 step 3 done (Codex + review): shared scene base files MIT (static/scene/LICENSE-MIT), packs and Starter MIT, app stays GPL |

## Phase 9: studio flow overhaul

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T9.1 | Studio flow map and screen spec | S | T6.1, owner sign-off | done | 2026-11-01 owner approved the canvas; sources in docs/design/mockups/ |
| T9.2 | UI screenshot and console harness | S | T0.5 | done | 2026-10-31 Codex; scripts/ui_snapshots.py: 28 routes in 17.6s, exits 1 on console.error |
| T9.3 | New app shell and routes | M | T9.1, T4.1, T6.1 | done | 2026-11-01 Codex; top bar, stage bar, Next, inspector slot, jobs strip; old tabs inside stages; review: stage bar packing, 1100 px top bar |
| T9.4 | Stage model and readiness API | S | T9.1, T1.5 | done | 2026-11-01 Codex; app/stages.py, GET .../stages, CLI stages; P0 subset only (full check 36 ms); review: warn colour |
| T9.5 | Home and start-a-video flow | M | T9.3 | done | 2026-11-01 Codex; mockup Home, projects table with stage, Project.aspect flag; review: search/label styling |
| T9.6 | Plan stage: sources and the outline in chapter columns | M | T9.3, T9.4 | done | 2026-11-01 Codex; Plan board (sources, chapter columns, hook, write script); review: compact beat cards |
| T9.7 | Script stage redesign | M | T9.3, T9.4 | done | 2026-11-01 Codex; paragraph cards, inline findings, words-only check column; review: auto-height text, quiet actions |
| T9.8 | Visuals stage: one picker for every source | M | T9.3, T9.4 | done | 2026-11-01 Codex; shared picker, groups, mix bar; cast/3D on sub-pages, Footage stub; review: tab wrap, a.btn |
| T9.9 | Voice stage redesign | M | T9.3, T4.9 | done | 2026-11-01 Codex; takes list, prompter, every-take column; review: settings collapsed once voiced, dark audio controls; owner: record a paragraph |
| T9.10 | Edit stage: the Timeline workspace | M | T9.3, T4.3 | done | 2026-11-01 Codex; full-width Timeline workspace, inspector slot, shortcuts sheet; review: inspector wiped by shell repaint, draw all restored |
| T9.11 | Review & publish stage | M | T9.3, T3.3 | done | 2026-11-01 Codex; merged Render+Thumbnail into a six-step Finish screen; review: harness Chromium restart; deferred items in log |
| T9.12 | Jobs centre and command palette | S | T9.3 | done | 2026-11-08 Codex + review; drawer, cancel (opt-in jobs), Ctrl K palette; checked headless |
| T9.13 | First-run setup | S | T9.3 | done | 2026-11-08 Codex + review; #/setup wizard, existing data roots skip it; checked headless |

## Phase 10: sponsor segments

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T10.1 | Sponsor segments in the data model and the cut | M | T0.7, T4.2, T2.4 | done | 2026-10-31 Codex; SponsorSlot model, pre/mid/end at paragraph boundaries, music ducks, chapter marker; 425 tests |
| T10.2 | Sponsor library on channels | S | T10.1 | done | 2026-11-08 Codex + review; channel sponsor library + built-in house sponsor (opt-in), slot picker copies values |
| T10.3 | Sponsor scene templates: short and long | M | T10.1, T2.3 | done | 2026-10-31 Codex (2 rounds); short/long + vertical templates, dark card ink, copy fits; frames in compare/ |
| T10.4 | Writing and voicing the read | S | T10.2 | done | 2026-11-08 Codex + review; drafts (mocked LLM), TTS and recorded takes with history and restore; all files kept |
| T10.5 | Placement suggestions and checks | S | T10.1, T1.5 | done | 2026-10-31 Codex; suggest_slots (pre/mid/end) + 5 sponsor checks; paid flag for disclosure |
| T10.6 | Sponsors in the editor | M | T10.1, T9.10 or T4.4 | done | inline sponsor copy until T10.2's library; review: input styling, lead-in label, block validation cache |
| T10.7 | Description, chapters and YouTube flags | S | T10.1, T10.2 | done | 2026-11-08 Codex + review; sponsor description block + chapter, paid flag (insert, fallback update; mocked); owner: first real paid upload confirms the path |

## Phase 11: footage (import, clip, label)

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T11.1 | Shoots: import and proxies | M | T0.5 | done | 2026-10-31 Codex; footage import (link or copy), proxies + sprites, resumable; sources untouched |
| T11.2 | Shot detection into clips | M | T11.1 | done | 2026-10-31 Codex; scene+motion+silence shots on proxies, wired into import; owner: time a 20-min shoot |
| T11.3 | Quality signals and duplicates | S | T11.2 | done | 2026-10-31 Codex + review fixes (shoot-relative blur, mean-luma exposure); owner: sanity-check flags on a real shoot |
| T11.4 | Auto labels for clips | M | T11.2, T3.2 | done | 2026-10-31 Codex; batched thumbnail labels, fixed vocabulary, cached, token estimate + confirm before any call; owner: try on a real shoot |
| T11.5 | Footage logger UI | M | T11.2, T9.3 | done | 2026-11-08 Codex + review; keyboard logger, proxy-only media, edits 409 while processing; checked headless incl. a real processed shoot |
| T11.6 | Clips into the edit | M | T11.4, T9.8 | done | 2026-11-08 Codex + review; footage provider first, fill only on word matches, -ss/-t on original (proxy for previews); one ¼ preview checked |
| T11.7 | Shot list from the script | S | T11.4 | done | 2026-11-01 Codex; page + PDF checked on project copy; coverage untested on a real shoot |
| T11.8 | Export clips | S | T11.2 | done | 2026-10-31 Codex + review fixes; export clips (re-encode exact, copy .mkv) + JSON/CSV sidecars; stopgap page until T11.5 |

## Phase 12: Corkbored blocks (our own library)

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T12.1 | Corkbored block format and local registry | M | T2.3, T2.7c | done | 2026-10-31 Codex; clean-room block format + registry, 9 built-in blocks wrap our templates; fixed preview default length |
| T12.2 | Block authoring kit | S | T12.1 | done | 2026-10-31 Codex; block new/check (overflow, safe areas, contrast) in 3 aspects; prints user/ id |
| T12.3 | Core block set v1 | L | T12.2, T2.10 | done | 2026-11-01 Codex (4 batches); 31 blocks pass browser checks in both aspects; contact sheet docs/blocks/core-v1.png |
| T12.4 | Data blocks from tables | M | T12.3 | done | 2026-11-01 Codex; number-match P1 at spoken precision; CSV paste UI moved to T12.5 |
| T12.5 | Blocks in the Visuals stage | M | T12.1, T9.8, T12.8b | done | 2026-11-08 Codex + review; offline block suggestions, pick-mode use, chosen still with Edit/Remove, CSV errors inline |
| T12.6 | Make a block from a description | M | T12.2 | done | 2026-11-01 Codex; sandboxed generation, checked before saving; real model run and Library UI await the owner |
| T12.7 | Retire the third-party catalog | S | T12.3, T12.5 | done | 2026-11-08 Codex + review; catalog removed; legacy refs show a placeholder + P1 finding; no local usage (checked read-only) |
| T12.8 | Block library: browse, preview and use blocks app-wide | L | T12.1, T12.3, T9.3 | done | 2026-11-08 Codex + review; #/blocks screen, search/filters, local posters (41 blocks in 9 s); rest split to T12.8b |
| T12.8b | Block library: motion, trials and actions | L | T12.8 | done | 2026-11-08 Codex + review; motion (cold 1.0 s), trials, use in project, pick mode, block-as-picture render |
| T12.8c | Block library: preferences, forks and remaining actions | M | T12.8b | done | 2026-11-08 Codex + review; favourites/recent, Library image picker, add to channel, Describe moved; owner: built-in forks fail the sandbox (see log) |
| T12.9 | Channel and project block presets | M | T12.8, T12.5 | done | 2026-11-08 Codex + review; presets on channels/projects, preset-first picker, provenance + counted slide updates, missing blocks safe |
| T12.9b | Block presets: channel page, promote, ranking | M | T12.9 | done | 2026-11-08 Codex + review; channel Blocks section, promote, pins/presets ranked first (paragraph content wins) |
| T12.10a | Block overlays on any picture: data and render | M | T11.6, T12.5, T2.10 | done | 2026-11-08 Codex + review; slide.overlays, transparent block layers composited by ffmpeg, stored unclipped; ¼ preview checked |
| T12.10b | Block overlays: planning and editing | M | T12.10a, T4.4, T12.8 | done | 2026-11-08 Codex + review; offline overlay planner, Timeline Graphics row (select/nudge/delete/hide/G), Visuals chips; checks split to T12.10c |
| T12.10c | Block overlays: checks | S | T12.10b | done | 2026-11-08 Codex + review; contrast (panel-aware), overlap, safe area, estimated anchors; Fix opens the graphic |
| T12.11 | Block preview player: plays in the app window, expands, scrubs | M | T12.8b | done | 2026-11-08 Codex + review; VP9 webm previews (the app window has no H.264), full length, expanded player with scrub/loop/aspect/show-over; owner: confirm it plays in the desktop app |
| T12.12a | Block themes: tokens per channel or standalone video | M | T12.9b | done | 2026-11-08 Codex + review; Style.block_theme sparse overrides, default→theme→channel→project, CSS tokens incl. fonts/radius/weight/pace, token lint; defaults pixel-identical (69 captures); 6 pre-existing block-check failures noted |
| T12.12b | Block themes: editor and live previews | M | T12.12a, T12.11 | done | 2026-11-08 Codex + review; theme panel on channel + project Look, live six-poster sheet (cold 1.36 s), Preview as on Blocks; review: pending posters, readable token labels |
| T12.13 | Block set v2: ~40 new blocks in five batches | L | T12.12a, T12.11 | done | 2026-11-08 Codex + review; 40 blocks in 5 batches, sheets v2-a to v2-e; motion only checked from still frames |

## Phase 13: styles as starting kits

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T13.1 | Picture kind per paragraph: mixed kinds render | L | T12.10a | done | 2026-11-08 Codex (high) + review; Slide.kind + kinds.kind_for, per-boundary joins, per-kind planning/checks; goldens + 60 cache keys identical; mixed doc/loudmouth/board previews checked |
| T13.2 | Visuals: choose each paragraph's kind | M | T13.1, T9.8 | done | 2026-11-08 Codex + review; kind chip + grouped menu (Visuals, Edit inspector), shift-click ranges, per-paragraph sources/editors, kind settings, inactive_blocks keeps block values; review: row layout, kind colours, menu states |
| T13.3 | Styles as starting kits | M | T13.1, T12.12a, T12.9b | done | 2026-11-08 Codex + review; app/style_kits.py: 9 built-in kits, your kits (save/import/export), saved-format + slide-style adapters, apply with dry-run summary; review: kits no longer reset engines, cadence or knobs |
| T13.4 | Style picker and placement; Design a block | M | T13.2, T13.3, T12.12b | done | 2026-11-08 Codex (high) + review; grouped kit picker with real sample posters/motion; Home compact control, Visuals header + dry-run Apply/Cancel, channel House style, Publish summary, Design a block; review: card sizing, header padding, summary wording |
| T13.5 | Drawn-cut pieces as blocks (pilot: Group Chat) | M | T13.1, T12.13 D | parked | later; owner schedules |

## Phase 14: clips from long recordings

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T14.1 | Local speech-to-text: word-timed transcripts | L | T11.1, T9.12 | done | 2026-11-08 Codex + review; backend only (UI split to T14.1b); no engine installed here; engine adapters for whatever is installed (faster-whisper, whisper.cpp, openai-whisper, mlx-whisper), default + per-run choice; whole or single range; audio-only import; chunked, resumable |
| T14.1b | Speech-to-text: audio import and studio integration | L | T14.1 | done | 2026-11-08 Codex + review; audio import, Settings, setup, API; controls split to T14.1c |
| T14.1c | Transcript controls, model downloads and Voice retime | M | T14.1b | done | 2026-11-08 Codex + review; controls, word edits, resumable replace; downloads and Voice retime split to T14.1d |
| T14.1d | Speech-to-text inference refinements and Voice retime | M | T14.1c | todo | model downloads on click, seam jitter, voiced-interval timing, turn markers, Voice retime of recorded takes |
| T14.2 | Vertical and square output for the render pipeline | L | — | todo | WIDTH/HEIGHT fixed at 1920×1080 today; landscape goldens must stay identical |
| T14.3 | Clip finder: transcript view, select by words, suggestions | M | T14.1, T11.5 | todo | transcript mode (whole, with suggestions) or manual mode (scrub, I/O, transcribe just this clip); LLM ranking opt-in |
| T14.4 | Clip projects: reframe, trim, hook title and graphics | L | T14.2, T14.3, T12.10a | todo | range of the original, never copied; crop keyframes; hook overlay block |
| T14.5 | Captions: burned-in styles plus SRT/VTT | M | T14.1, T14.4 | todo | phrase / word highlight / big word; sidecars for every project |
| T14.6 | Clip descriptions, full-recording links, batch render and upload | M | T14.4, T10.7 | todo | timestamped youtu.be link; batch of cancellable jobs; Shorts tag for 9:16 ≤ 3 min |

## Phase 15: the bundled example, and what building it found

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T15.1 | Bundled example channel and video | S | T9.13, example content | todo | content built (isolated data dir): "The Tube Mail", 37 paragraphs, 14 blocks + 9 lower thirds + board, 23 PD/CC0 pictures, Kokoro narration; bundle 66.9 MB; owner: where to keep the binary (git LFS, plain git, or download) |
| T15.2 | Picture search relevance: subject-aware queries and a relevance gate | M | — | todo | auto-gather picked a car race and business-school campuses for every paragraph; good PD material was one query away |

## Phase 16: local models, first class

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T16.1 | Live progress during model calls | M | — | done | 2026-11-08 Codex + review; live counter checked on Granite (16 tok/s, count matched usage); streamed token counter in a replaceable job status line; LM Studio and Ollama |
| T16.2 | Write sections in order for local models | S | — | done | 2026-11-08 Codex + review; Granite live run had no repeated facts; each section sees what came before; parallel stays for hosted backends |
| T16.3 | A default User-Agent that archives accept | S | — | done | 2026-11-08 Claude; old default got HTTP 403 from Wikimedia on every fresh install |
| T16.4 | Script consistency check | M | — | done | 2026-11-08 Codex + review; works mechanically, but Granite 8B flags nothing (too small to judge); contradictions and impossible visuals as Check findings |
| T16.5 | Speed test and thinking advice in Check LM Studio | S | T16.1 | done | 2026-11-08 Codex + review; Qwen advised thinking off, Granite not; estimate fixed to measured budget; tokens/s and reasoning split from one short prompt; advice only |

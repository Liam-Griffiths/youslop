# Progress

Status values: `todo`, `doing`, `done`, `blocked`. Update the row when you
start and when you finish. Keep the newest note in the Notes column; the
full log lives in the ticket file.

Last updated: 2026-10-31 (Codex gpt-6.1-sol implementing, Claude Opus 5.5 reviewing)

> **Codex limit, 2026-10-31 14:50 PDT:** the 5-hour Codex window hit 99% after T4.2 (weekly 18%).
> Resumed 18:17 PDT at T4.1 after the window reset. Owner checks collected per row below.

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
| T0.10 | Kokoro model with word timings | S | T0.6 | blocked | owner listens to an A/B first |

## Phase 1: doctrine and check

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T1.1 | FrameSpec dataclass | M | T0.5 | done | 2026-10-31 Codex; 119 tests |
| T1.2 | Theme defaults for frame | S | T1.1 | done | 2026-10-31 Codex; 124 tests |
| T1.3 | Prompt block and hook gate | M | T1.1 | done | 2026-10-31 Codex; 145 tests; owner: one real-LLM outline run to eyeball the hook |
| T1.4 | ffmpeg camera vocabulary and title timing | M | T1.1, T0.5 | done | 2026-10-31 Codex; 163 tests; preview checked by Claude, owner: watch a join |
| T1.5 | check.py findings | L | T1.1, T0.6, T0.7 | done | 2026-10-31 Codex; 14 rules, 189 tests; real project: P0 0 / P1 12 / P2 13 |
| T1.6 | Check in the UI, CLI and render gate | S | T1.5 | done | 2026-10-31 Codex; panel checked headless; owner: click through render gate |
| T1.7 | Audio doctrine defaults | S | T1.1 | done | 2026-10-31 Codex; ACCEPTANCE OPEN: gap 9.9 dB not 16-19, dynamic loudnorm lifts gaps; owner decides on linear 2-pass |

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
| T2.7b | Make fetched Hyperframes blocks render offline | S | T2.7 | todo | compatibility only (catalog is temporary, see T12.7) |
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
| T4.3 | Selection and per-kind inspector | M | T4.1, T4.2 | todo | |
| T4.4 | Layers rows | M | T4.3, T0.7 | todo | |
| T4.5 | Drag and resize timing | M | T4.4 | todo | |
| T4.6 | Razor (keeps audio) | M | T4.3, T0.6 | todo | rewritten 2026-10-26: split takes, never delete |
| T4.7 | Variables panel | S | T4.3, T1.1 | todo | |
| T4.8 | Quick wins: search, suggest chapters | S | T4.1 | todo | |
| T4.9 | Keep every take | S | — | done | 2026-10-31 Codex; audited: no take deleted or overwritten; owner: try earlier-takes UI |

## Phase 5: migrations, resume, verify

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T5.1 | Essay captions as a scene | M | T2.4 | todo | |
| T5.2a | Board templates as scenes | M | T2.4, T2.5 | todo | split from T5.2 |
| T5.2b | Diagrams as SVG scenes | M | T5.2a | todo | |
| T5.2c | Custom slides through a scene template | S | T5.2a | todo | |
| T5.2d | Custom slides written as sanitised HTML | M | T5.2c | todo | security-sensitive |
| T5.2e | Real text measurement for scenes | S | T5.2a, T1.5 | todo | |
| T5.3a | Drawn cut to scene: Loudmouth | L | T2.4, T0.6 | todo | first; sets template conventions |
| T5.3b | Drawn cut to scene: Flameboat | L | T5.3a | todo | |
| T5.3c | Drawn cut to scene: Ticker | L | T5.3b | todo | |
| T5.3d | Drawn cut to scene: Group Chat | L | T5.3c | todo | |
| T5.3e | Drawn cut to scene: Casefile | L | T5.3d | todo | last; texture-heavy |
| T5.4 | Thumbnails as a scene | M | T2.4 | todo | |
| T5.5 | 3D stage under CDP | M | T2.1 | todo | |
| T5.6 | Resume a failed render | S | T0.5 | todo | |
| T5.7 | verify.py after render | S | T0.6 | todo | |

## Phase 6: brand rollout

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T6.1 | Instrument design tokens and fonts | S | T0.4 | done | 2026-10-31 Codex; Instrument tokens, Archivo/Space Grotesk switch; owner: pick a face from compare/ shots, check desktop window |
| T6.2 | Mark, favicon and app icon | S | T0.4 | done | 2026-10-31 Codex; cork/post-it mark in header, favicon, icons regenerated; owner: check launcher icon |
| T6.3 | Copy, README and mockup | S | T6.1, T6.2 | todo | |

## Phase 7: camera (piece to camera)

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T7.1 | Camera takes in the data model | M | T0.5, T4.9 | todo | added 2026-10-26 |
| T7.2 | Record on camera in the Record tab | M | T7.1 | todo | desktop camera permissions unverified on Linux |
| T7.3 | Camera paragraphs in the render | M | T7.1, T0.5 | todo | |
| T7.4 | Trims and jump cuts on camera takes | M | T7.3, T4.4 | todo | |
| T7.5 | Cutaways and layouts over camera | M | T7.4, T2.4 | todo | includes the Auto-edit button |
| T7.6 | Camera look and checks | S | T7.3, T1.5 | todo | |
| T7.7 | Talking-head videos end to end | S | T7.2, T7.3, T7.4 | todo | |
| T7.8 | Long-take import (stretch goal) | L | T7.1, T7.2, T7.4 | todo | stretch; opt-in speech recognition |

## Phase 8: content packs

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T8.1 | Pack format and loader | M | T0.2, T2.3 | todo | added 2026-10-26 |
| T8.2 | Packs screen and install from a file | S | T8.1, T6.1 | todo | |
| T8.3 | Pack tooling, format spec and first free pack | S | T8.1, T8.2, T0.7 | todo | step 3 waits on an owner decision |

## Phase 9: studio flow overhaul

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T9.1 | Studio flow map and screen spec | S | T6.1, owner sign-off | todo | mockups: Corkbored studio flow canvas; owner approves first |
| T9.2 | UI screenshot and console harness | S | T0.5 | done | 2026-10-31 Codex; scripts/ui_snapshots.py: 28 routes in 17.6s, exits 1 on console.error |
| T9.3 | New app shell and routes | M | T9.1, T4.1, T6.1 | todo |  |
| T9.4 | Stage model and readiness API | S | T9.1, T1.5 | todo |  |
| T9.5 | Home and start-a-video flow | M | T9.3 | todo |  |
| T9.6 | Plan stage: sources and the outline in chapter columns | M | T9.3, T9.4 | todo |  |
| T9.7 | Script stage redesign | M | T9.3, T9.4 | todo |  |
| T9.8 | Visuals stage: one picker for every source | M | T9.3, T9.4 | todo |  |
| T9.9 | Voice stage redesign | M | T9.3, T4.9 | todo |  |
| T9.10 | Edit stage: the Timeline workspace | M | T9.3, T4.3 | todo |  |
| T9.11 | Review & publish stage | M | T9.3, T3.3 | todo |  |
| T9.12 | Jobs centre and command palette | S | T9.3 | todo |  |
| T9.13 | First-run setup | S | T9.3 | todo |  |

## Phase 10: sponsor segments

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T10.1 | Sponsor segments in the data model and the cut | M | T0.7, T4.2, T2.4 | done | 2026-10-31 Codex; SponsorSlot model, pre/mid/end at paragraph boundaries, music ducks, chapter marker; 425 tests |
| T10.2 | Sponsor library on channels | S | T10.1 | todo | open: house read opt-in or opt-out |
| T10.3 | Sponsor scene templates: short and long | M | T10.1, T2.3 | todo | house_short mockup exists |
| T10.4 | Writing and voicing the read | S | T10.2 | todo |  |
| T10.5 | Placement suggestions and checks | S | T10.1, T1.5 | todo |  |
| T10.6 | Sponsors in the editor | M | T10.1, T9.10 or T4.4 | todo |  |
| T10.7 | Description, chapters and YouTube flags | S | T10.1, T10.2 | todo |  |

## Phase 11: footage (import, clip, label)

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T11.1 | Shoots: import and proxies | M | T0.5 | todo | added 2026-10-31 |
| T11.2 | Shot detection into clips | M | T11.1 | todo |  |
| T11.3 | Quality signals and duplicates | S | T11.2 | todo |  |
| T11.4 | Auto labels for clips | M | T11.2, T3.2 | todo | token budget shown before a run |
| T11.5 | Footage logger UI | M | T11.2, T9.3 | todo |  |
| T11.6 | Clips into the edit | M | T11.4, T9.8 | todo |  |
| T11.7 | Shot list from the script | S | T11.4 | todo |  |
| T11.8 | Export clips | S | T11.2 | todo |  |

## Phase 12: Corkbored blocks (our own library)

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T12.1 | Corkbored block format and local registry | M | T2.3, T2.7c | todo | added 2026-10-31; clean-room, no Hyperframes code |
| T12.2 | Block authoring kit | S | T12.1 | todo | |
| T12.3 | Core block set v1 | L | T12.2 | todo | ~30 blocks, 16:9 and 9:16, four batches |
| T12.4 | Data blocks from tables | M | T12.3 | todo | number-match check |
| T12.5 | Blocks in the Visuals stage | M | T12.1, T9.8 | todo | |
| T12.6 | Make a block from a description | M | T12.2 | todo | model writes a reusable block once |
| T12.7 | Retire the third-party catalog | S | T12.3, T12.5 | todo | owner: third-party blocks are temporary |

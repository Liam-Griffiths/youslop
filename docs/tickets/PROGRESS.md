# Progress

Status values: `todo`, `doing`, `done`, `blocked`. Update the row when you
start and when you finish. Keep the newest note in the Notes column; the
full log lives in the ticket file.

Last updated: 2026-10-31 (Codex gpt-6.1-sol implementing, Claude Opus 5.5 reviewing)

## Phase 0: foundations

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T0.1 | Brand module and env alias helper | M | — | done | 2026-10-31 Codex; 28 unit tests |
| T0.2 | Data folder compatibility | S | T0.1 | done | 2026-10-31 Codex; falls back to the youslop folder |
| T0.3 | Project file and bundle compatibility | S | T0.1 | done | 2026-10-31 Codex; .corkbored export, reads .youslop |
| T0.4 | Mechanical rename | M | T0.1, T0.2, T0.3 | done | 2026-10-31 Codex; owner: eyeball desktop window + temp C icon; GitHub repo rename is manual |
| T0.5 | Test scaffold and graph goldens | M | — | done | 2026-10-31 Codex; 74 unit tests 0.5s, graph goldens, 1 opt-in visual test |
| T0.6 | Word timestamps on takes | M | T0.5 | done | 2026-10-31 Codex; estimates for now, timed path ready for T0.10 |
| T0.7 | Storyboard contract and CLI skeleton | M | T0.5 | todo | |
| T0.8 | Re-measure the render memory cap | S | — | done | 2026-10-31 measured essay 2058 MB, kenburns 1406 MB; cap 2500/1500 |
| T0.9 | CLAUDE.md and repo hygiene | S | T0.7 | todo | |
| T0.10 | Kokoro model with word timings | S | T0.6 | todo | owner listens to an A/B first |

## Phase 1: doctrine and check

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T1.1 | FrameSpec dataclass | M | T0.5 | todo | |
| T1.2 | Theme defaults for frame | S | T1.1 | todo | |
| T1.3 | Prompt block and hook gate | M | T1.1 | todo | |
| T1.4 | ffmpeg camera vocabulary and title timing | M | T1.1, T0.5 | todo | |
| T1.5 | check.py findings | L | T1.1, T0.6, T0.7 | todo | |
| T1.6 | Check in the UI, CLI and render gate | S | T1.5 | todo | |
| T1.7 | Audio doctrine defaults | S | T1.1 | todo | |

## Phase 2: scene engine

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T2.1 | CDP capture mode in the stage runner | L | T0.5 | todo | |
| T2.2 | Scene runtime and vendored GSAP | M | — | todo | |
| T2.3 | scenes.py and Jinja templates | M | T2.1, T2.2 | todo | |
| T2.4 | Render branch point for scenes | M | T2.3 | todo | |
| T2.5 | Migration: outro and chapter cards | M | T2.4 | todo | |
| T2.6 | Migration: intro slates | M | T2.5 | todo | |
| T2.7 | Catalog fetcher | S | T2.3 | todo | |

## Phase 3: review loop and agent surface

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T3.1 | Snapshots and contact sheet | M | T0.7, T1.5 | todo | |
| T3.2 | Claude vision review and REVIEW.md | M | T3.1 | todo | targeted by default (≤12 frames) |
| T3.3 | Fix routing | M | T3.2 | todo | |
| T3.4 | Ask the agent packet | M | T3.1 | todo | |
| T3.5 | CLI full loop, ops.py and SKILL.md | M | T0.7, T1.6, T3.2 | todo | |
| T3.6 | Learning loop: rules, rejected looks, formats | S | T1.1, T3.2 | todo | |

## Phase 4: timeline editor

| Ticket | Title | Size | Depends on | Status | Notes |
|---|---|---|---|---|---|
| T4.1 | Split app.js and timeline.js into files | M | — | todo | |
| T4.2 | Retime fields in the schema | S | T0.6 | todo | |
| T4.3 | Selection and per-kind inspector | M | T4.1, T4.2 | todo | |
| T4.4 | Layers rows | M | T4.3, T0.7 | todo | |
| T4.5 | Drag and resize timing | M | T4.4 | todo | |
| T4.6 | Razor (keeps audio) | M | T4.3, T0.6 | todo | rewritten 2026-10-26: split takes, never delete |
| T4.7 | Variables panel | S | T4.3, T1.1 | todo | |
| T4.8 | Quick wins: search, suggest chapters | S | T4.1 | todo | |
| T4.9 | Keep every take | S | — | todo | owner rule: never delete recorded audio |

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
| T6.1 | Instrument design tokens and fonts | S | T0.4 | todo | |
| T6.2 | Mark, favicon and app icon | S | T0.4 | todo | |
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

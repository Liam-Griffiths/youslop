# Handoff: state of the ticket writing

Written 2026-10-25, updated later the same day. All ticket files for
Phases 0 to 6 now exist (T0.1 to T6.3; T5.3 is split into T5.3a to T5.3e,
one per drawn cut). Nothing is implemented yet and nothing is committed.

## Resume prompt (paste this into a new session)

> Read `docs/tickets/HANDOFF.md`, `docs/tickets/README.md` and
> `docs/tickets/PROGRESS.md` and `docs/tickets/NOTES.md`. If `docs/` is still untracked, commit it as
> "Roadmap and tickets: Corkbored". Then work the first `todo` ticket whose
> dependencies are done (start at `00-foundations/T0.1-brand-module.md`),
> following the procedure in README.md.

## Session log

- **Researched.** Hyperframes (site, README, the `hyperframes`, `media-use`,
  `motion.md` and `review.md` skills, the Studio guide, and the design
  frames), the WeAreNoCode-YouTube-Editor skill, and the youslop codebase.
- **The owner decided:** keep the ffmpeg photographic path. Add an HTML+GSAP
  scene engine through headless Chromium with no Node. Position the product
  as a showrunner first, with editor features on the Timeline. Rebrand to
  **Corkbored**. Use the **Instrument** UI direction.
- **Written:** the roadmap, the ticket README, PROGRESS.md, and 23 tickets
  covering T0.1 to T2.7.
- **Second session (Opus 5.5, same day):** wrote the 24 remaining tickets
  for Phases 3 to 6 (28 files: `03-review-agent` 6, `04-timeline-editor` 8,
  `05-migrations` 11 incl. T5.3a–e, `06-brand-rollout` 3) after re-checking
  anchors with grep. PROGRESS.md rows updated for the T5.3 split.
- **Third session (Opus 5.5, 2026-10-26):** read the code behind every
  ticket and added an `## Implementer notes` section to all 51, aimed at a
  model like Sonnet doing the work: exact functions, stubs, traps, and
  decisions to ask the owner. Shared facts are in `NOTES.md`. Tested the
  CDP pipe capture against this machine's Chromium (prototype in
  `02-scene-engine/reference/cdp_proto.py`), transparent capture, the
  xfade hard-cut expression, and the Hyperframes registry layout.
  Corrected T0.5 step 6 and T2.1's pipe snippet.
- **Owner decisions, 2026-10-26:** T1.7 changes the music default outright
  (no existing projects to protect); T6.1 ships both display faces behind a
  switch; never delete recorded audio (T4.6 rewritten, T4.9 added, README
  rule added); T5.2 split into T5.2a-e. See NOTES.md.
- **Later the same day:** added T0.10 (swap in the published Kokoro export
  that reports word timings; owner A/B listens first) and made T3.2's vision
  review targeted by default (≤ 12 frames: check findings, hook, ending,
  chapter starts; `--full` on request) to keep token use down.
- **Phase 7 added (2026-10-26):** piece to camera, T7.1-T7.7 in
  `07-camera/` (camera takes, recording with a prompter, render, jump cuts,
  cutaways and layouts, look and checks, talking-head videos), plus T7.8
  long-take import as a stretch goal. Marketing
  plan written to `docs/marketing.md`.
- **Not committed:** `docs/roadmap.md` and `docs/tickets/` are untracked.
- **Plan copies:** `docs/roadmap.md` in the repo is the canonical copy. The
  original is at `~/.claude-personal/plans/witty-coalescing-peacock.md`.

## What exists

- `docs/roadmap.md`: the full plan (positioning, brand, engine analysis,
  all six phases with file anchors, verification). Source of truth.
- `docs/tickets/README.md`: how to work a ticket, the rules, the template.
- `docs/tickets/PROGRESS.md`: every ticket in every phase with status.
- Ticket files, fully written, for every row in PROGRESS.md (65 files after the 2026-10-26 changes).

## What to do next (for the agent that picks this up)

1. Commit `docs/` if untracked, then start at `T0.1`.
2. Verified anchors you can rely on (checked 2026-10-25):
   `render.py`: `_render_segment` ~505, `_kenburns` 63, `MOVES` 33,
   `_build_proxy` 1569, `_proxy_key` 1506, `timeline` 1938, `_stage_clips` 251,
   `_build_intro` 790, `_build_outro` 889, `_audio_graph` 972, `render` 1090,
   `preview_segment` 1639, `proxy_segment` 1659, `_render_custom_style` 333,
   `CHUNK_SECONDS` 155, `HOLD_STILL` 326.
   `cuts/kit.py`: `fit` 102, `place` 438, `chapter_screen` 624, eases 139-149.
   `cuts/__init__.py`: `is_cut` 44, `normalise` 66, `cues_for` 79,
   `render_segment` 161, `still` 240.
   `tts.py`: `synthesise` 404, `_finish_chain` 431, `speak_to_file` 452;
   installed kokoro-onnx has `create_timed`.
   `audio.py`: `paragraph_gaps` 31, `_levels` 101, `speech_span` 152,
   `voice_chain` 220, `process_take` 322.
   `llm.py`: `complete_json(..., images=)` 153, `_image_blocks` 236.
   `main.py`: `FastAPI(title=)` 52, `patch_slide` 1074, `split_slide` 1164,
   `upload_take` 1888, `_voice_one` 2045, `start_render` 2459.
   `store.py`: `lock_for` 18, `save` 31, `list_projects` 64, `log` 94.
   `shots.py`: `_render_item` 515, `ensure_clips` 549, `_sweep` 575.
   `themes.py`: `THEMES` 23, `palette` 140, `apply_to_style` 159.
   `titles.py`: `TITLE_SIZE` 113, `_fit_caption` 317, `render_caption` 333,
   `render_chapter` 366. `ffutil.py`: `is_preview` 122, `video_args` 126,
   `encode_frames` 284. `transfer.py`: `EXTENSION` 36, manifest key 92/142.
   `schema.py`: `Take` 51, `Slide` 64, `Style` 172, `Channel` 475,
   `Project` 542, `new_project` 809. `paths.py`: `_platform_data_root` 49.
   `tests/stage/suite.py`: `sheet()` ~187, `ssim()` ~204.
3. Decisions already made by the owner (do not reopen): keep the ffmpeg
   photographic path; add an HTML scene engine through headless Chromium with
   **no Node**; positioning is showrunner first with real editor features;
   name is **Corkbored** (one-word wordmark, no "AI" badge; was Rostrum AI
   until 2026-10-31, owner holds corkbored.com); studio UI
   direction is **Instrument** (near-black, 4px radii, signal orange
   `#FF5A1F`, Inter UI, JetBrains Mono numbers). **Open:** the display face.
   Instrument said Space Grotesk; the approved landing page
   (`static/landing.html`, 2026-10-25) uses condensed Archivo 800 and the
   owner likes it. T6.1 step 0 asks the owner to pick. Tagline is fixed:
   "Idea in. Episode out."

Nothing has been committed yet. `git status` shows `docs/` as new.

**2026-10-26, later:** the owner chose content packs as the way to earn money
later while the app stays free and GPL. Added Phase 8 (`08-packs/`,
T8.1-T8.3): a data-only pack format, a Packs screen with install from a
`.corkboredpack` file, and pack tooling with a free Starter pack. One open
decision: T8.3 step 3 (MIT for the scene runtime files). 68 ticket files.

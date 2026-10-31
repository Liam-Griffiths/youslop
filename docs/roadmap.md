# Youslop → Corkbored: improvement, design and brand plan

## Context

Youslop turns an idea into a narrated, illustrated YouTube video on one machine: Claude researches and writes, archives are searched for pictures, the creator records (or Kokoro reads), Pillow and ffmpeg cut the file, and it uploads to the channel. The competitor, HeyGen's Hyperframes (Apache-2.0, ~72k stars), is a different thing: a renderer where HTML plus a GSAP timeline is seeked frame by frame in headless Chrome, a Studio editor on top of it, a 450-block catalog, and agent skills that teach a disciplined production loop (storylines → SPEC → build → lint → snapshot review → REVIEW note). The WeAreNoCode skill shows what a working editor built on it looks like: numeric pacing budgets, anchored timing checked against the transcript, a hook gate, a banned-looks list, and a learning loop where every note becomes a saved rule.

Hyperframes is better at *rendering and editing*. It does not research, write, narrate, keep a series consistent, make thumbnails, or publish. That is Youslop's whole upper half, and nobody is competing there with a local-first tool.

Decisions taken with the user (binding for this plan):

- **Keep the Pillow/ffmpeg renderer. No Node, no HTML renderer.** Port Hyperframes' and WeAreNoCode's *doctrine* (numbers, checks, review loop, design specs) into the existing planners and drawers.
- **Positioning: showrunner first.** Idea in, published episode out. Then add real editor features to the Timeline so the result is correctable without re-rendering.
- **Rebrand to a serious name.** Proposal below.

## 1. Positioning

**One line:** *Corkbored is the showrunner: it researches, writes, narrates, cuts and publishes a channel's episodes from your own machine, and it shows you its work before it renders.*

What the product is **for**: a solo creator or small team running one or more YouTube channels of explainers, essays, documentaries and storytime formats, who want a consistent series look and a repeatable weekly pipeline without a cloud render bill or uploading their voice anywhere.

How it differs from Hyperframes, stated positively (never "we are not Hyperframes"):

| Corkbored | Hyperframes Studio |
|---|---|
| Starts from an idea; ends on YouTube | Starts from HTML; ends at an MP4 |
| Research with sources, fact-check pass | None |
| Your recorded voice, per paragraph, cleaned | Voice is a media asset you bring |
| Channels: slate, palette, voice, defaults carried episode to episode | Design systems (frame.md), per project |
| Zero cloud, zero Node: Python + ffmpeg + bundled Chromium for 3D | Node 22, Chrome, FFmpeg, optional HeyGen paid media |
| Shows its plan (storyboard, contact sheet, review note) before rendering | Same discipline, through skills |
| Weak today: motion range, element-level editing, lint, agent CLI | Strong |

The last row is the work. Sections 3 onward close it.

## 2. Brand

### Name: **Corkbored**

- A corkboard is where an episode starts: index cards, pins and string, the storyboard wall. That is the first half of the product (idea, research, plan); the rest turns the board into a finished episode. The pun is the point: pin up the idea, skip the boring part.
- The owner holds **corkbored.com** (decided 2026-10-31; replaces the earlier choice, Rostrum AI).
- Risks to manage: spoken aloud it sounds like "corkboard", so buy and redirect corkboard domains where cheap and always write the name in full; "bored" can read as negative to a skimmer, so the copy should wink at it rather than leave it bare. (Earlier candidates: *Rostrum*, *Cutaway*, *Monograph*.)
- Tagline options, pick one: "The showrunner." / "Idea in. Episode out." / "Research, narrate, cut, publish."
- Youslop survives as the repo's origin story in a short "History" section of the README and as the name of one preset look if the user wants the joke kept somewhere.

### Wordmark: "Corkbored"

Set "Corkbored" as one word, no "AI" badge: the name already says what it is, and "AI" in names dates. App title, window title, repo and marketing all read "Corkbored". Slug `corkbored`, env prefix `CORKBORED_`, file extension `.corkbored`.

### Visual identity: three directions

All three share: Inter for UI text, JetBrains Mono for timecodes and counts, one easing family (`cubic-bezier(.16,1,.3,1)`, the expo.out the motion doctrine prefers), and the Corkbored mark (a yellow sticky note with a black play mark, pinned with an orange push pin on cork; flat version for small sizes; files and build script in `docs/brand/`, readable at 16px, drawn in Pillow from the primitives `app/intro.py` already has so the favicon, app icon, slates and about screen share one source). They differ in mood, palette and display face. Fonts named are all open licence and most already ship in `resources/fonts`.

**A. Control Room** (dark, broadcast; evolves what exists)

```
bg        #0B0C10   panel #14161C   raised #1B1E26   line #262A35
ink       #E8E9EE   dim   #9AA0B0   faint  #676D7D
accent    #F2B134   tally amber: record, selection, playhead
signal    #39D98A   good / rendered      alert #E8776A
radius 8px   borders 1px   dense 13px UI text
display   Archivo (semi-condensed, 600)   ui Inter   mono JetBrains Mono
feel      a broadcast gallery at night: tally lights, timecode, matte black
```
Closest to the current `styles.css`, so cheapest. Distinct from Hyperframes' parchment frames. Risk: generic "dark pro tool" if the amber is not used with discipline (one tally colour, never gradients).

**B. Instrument** (near-black, precision, hard edges)

```
bg        #0E0F11   panel #16181C   raised #1D2026   grid #23262C
ink       #F2F2F2   dim   #A0A6AE   faint  #6A7079
accent    #FF5A1F   signal orange: one per screen
cool      #6FB7FF   links, secondary state
radius 4px   borders 1px   uppercase 11px micro-labels, letter-spaced
display   Space Grotesk 500   ui Inter   mono JetBrains Mono (used more: all numbers)
feel      a field instrument: labelled, ruled, nothing decorative
```
Strongest contrast with Hyperframes (theirs is editorial and warm). Reads as serious engineering, suits an "agent-driven" story. Risk: cold; the Record and Script tabs need warmth from content (take waveforms, portraits), not chrome.

**C. Archive** (light, paper, documentary)

```
paper     #F3EDE3   panel #FFFDF8   raised #EAE2D4   rule #D8CFC0
ink       #1B1A17   dim   #5E5A52   faint  #938D82
accent    #8C2F2F   oxblood: selection, record     gold #B8893A: emphasis
radius 6px   borders 1px rules   generous 14px UI text
display   EB Garamond 500 (ships already)   ui Inter   mono JetBrains Mono
feel      a research library: index cards, captions, pencil rules
```
Best fit for the product's soul (research, archives, narration) and the only light option, which helps for a creator's daytime workflow. Risk: Hyperframes' premade frames (Biennale Yellow, Cobalt Grid, Cartesian) all use warm parchment with serif display, so this is the direction most likely to look derivative. If chosen, keep oxblood plus ink only and avoid yellow entirely.

**Chosen: B, Instrument.** C's paper palette may later become a *video* look (a theme in `app/themes.py`), not the UI. The app should look like the instrument that makes the film, not like the film.

First deliverable after plan approval: a side-by-side mockup page (home, Script tab, Render tab with Timeline and Check panel, Settings) in the Instrument tokens, published as an artifact for review before any CSS changes land.

### Landing page (built 2026-10-25, `static/landing.html`)

The public holding page took a different, louder register than the app:
pure black `#050505` (light mode: paper `#F4F2EE`), a wall-sized condensed
wordmark in **Archivo 800 at 62 % width**, the same signal orange, a
self-typing production log in JetBrains Mono, Inter for prose. The owner
liked this and rejected a literal "instrument panel" page.

What this changes for the brand: the display face is now in question.
Instrument specified Space Grotesk 500; the landing page uses condensed
Archivo 800 and it reads as the brand. Options, to be decided in T6.1:
(a) keep the app chrome on Space Grotesk and reserve condensed Archivo for
marketing and the wordmark only; (b) adopt condensed Archivo for app
headings and the wordmark, Inter for everything else, dropping Space
Grotesk. The wordmark should match the landing page either way. The light
palette (paper, near-black, deeper orange `#E84A12`) is a tested starting
point if the app ever gets a light theme. The landing page loads fonts from
Google Fonts; a self-hosted copy must switch to `@font-face` from
`resources/fonts` (Archivo Narrow Bold ships already; Archivo variable or
Archivo Condensed 800 does not).

### Applying the chosen direction

- Tokens replace the `:root` block in `static/styles.css`; everything already reads from the variables, so the swap is one block plus a dark/light pair if C.
- Fonts via `@font-face` from `resources/fonts` (add Space Grotesk or Archivo as needed; both are OFL).
- Slates, end cards and thumbnails do **not** inherit the app palette. Channel themes own the video look.
- Copy voice: plain, confident, short sentences, no slop jokes, no exclamation marks. The README manifesto becomes two sentences about making careful, researched long-form video cheap to make.

### Rename surface (mechanical, backwards compatible)

- App name and window title: `app/desktop.py`, `youslop.spec` → `corkbored.spec`, `build_entry.py`, `README-BUILD.md`.
- Data dir in `app/paths.py`: new default `Corkbored`; on first launch, if the old `Youslop` folder exists and the new one does not, move or symlink and log it.
- Env prefixes `YOUSLOP_*` and `VB_*`: read new `CORKBORED_*` first, fall back to old names for two releases; `.env.example` updated.
- Wordmark and 🪣 in `static/index.html`, guide copy in `static/app.js` (`#/guide`), repo name and Releases URL in `README.md`, `THIRD-PARTY.md`.
- Project files exported by `app/transfer.py` keep their format; only the display name changes.

## 3. Engine: where Pillow stands against HTML, and the hybrid answer

### What Pillow cannot reasonably be brought up to

Hyperframes gets these for free from the browser. Each one is months of work in Pillow and still worse:

| Capability | HTML/Chromium | Pillow today |
|---|---|---|
| Text layout: wrapping, kerning, ligatures, variable fonts, emoji, RTL, mixed weights in one line | CSS, perfect | `ImageDraw.text`, manual wrapping, no kerning, no emoji colour |
| Layout: flex, grid, stacking, overflow, responsive to copy length | CSS | hand-placed pixels per template (`app/intro.py` is 2,816 lines of exactly this) |
| Tweening: eases, staggers, springs, timelines | GSAP, one vendored file | each cut hand-rolls lerps in `app/cuts/kit.py` |
| Effects: blur, backdrop blur, drop shadow, gradients, masks, blend modes | GPU, per frame | `ImageFilter.GaussianBlur` at 1080p is 30–80 ms per call, CPU |
| Vector/SVG icons and logos | native | none (would need cairosvg) |
| 3D | three.js | already done via the stage runner, in Chromium |
| Charts, maps, code highlighting, UI mockups | any JS library | Leaflet already runs in Chromium; everything else is bespoke drawing |
| Reusable blocks | 450-block catalog, plain HTML files | zero; every format is Python |

Per-frame cost is a wash: Pillow compositing at 1080p is 20–60 ms on one core; a Chromium screenshot at 1080p is 30–80 ms. Neither is real-time; both are fine for a seek-and-capture renderer.

Conclusion: do **not** try to make Pillow match. Give each engine the job it is good at.

### The hybrid: two engines, one renderer

1. **Photographic engine (ffmpeg, keep).** Ken Burns over stills and video, grades, vignette, chapter cards, captions. This is where ffmpeg filtergraphs are *faster* than a browser and where `app/render.py` is already mature. Improve it only with the motion vocabulary numbers (section 4).
2. **Scene engine (HTML + GSAP in headless Chromium, new, no Node).** Anything typographic, laid out, animated or generated: the five drawn cuts, intro slates, end cards, diagrams, custom slides, kinetic captions, charts, thumbnails. Built by generalising `app/stage.py`, which already does the hard part.

A segment in `app/render.py` picks its engine by format. `_render_segment` stays the single entry; a new `scene_clip()` branch sits next to `_stage_clips` and returns an mp4 clip exactly as the 3D stage does, so the audio graph, chapter cards, proxies and Timeline need no changes.

### How the scene engine works

Reuse `app/stage.py` as the runner. Today it serves `static/` plus a `job.json` over a private HTTP server, launches system Chromium with `--headless=new --use-angle=...`, and the page POSTs raw RGBA frames to `/frame/<clip>` which are piped into ffmpeg (`_begin`, `_end`). Changes:

- **Capture.** The 3D page reads pixels from its own WebGL canvas. A DOM scene cannot do that, so add Chrome DevTools Protocol capture over `--remote-debugging-pipe` (JSON messages on fds 3 and 4, zero-separated; stdlib `subprocess` with `pass_fds`, no websocket library, no Node). Per frame: `Runtime.evaluate("__seek(i/fps)")` then `Page.captureScreenshot` (JPEG q95 or PNG), decode with Pillow or hand straight to ffmpeg `image2pipe`. Add `--enable-begin-frame-control` with `HeadlessExperimental.beginFrame` later if screenshot timing proves jittery. Keep the existing POST-frame path for the 3D stage untouched.
- **Determinism.** Scenes expose `window.__timelines[id]` (a paused GSAP timeline) and the runner seeks it; CSS transitions and animations are disabled by an injected stylesheet (`*{transition:none!important;animation-play-state:paused!important}`); the lint (section 5) bans `Date.now`, unseeded `Math.random`, `setTimeout`, `repeat:-1`, network fetches, media `play()`. This is Hyperframes' contract and it exists because it is the only way seek-and-capture is stable.
- **Composition contract: adopt Hyperframes' attributes verbatim.** Root element with `data-composition-id`, `data-width`, `data-height`, `data-duration`; timed children `class="clip" data-start data-duration data-track-index`; variables as `data-var-text` / `data-var-src` / `var(--id)`; fonts via `@font-face` to `resources/fonts`; root-relative asset paths. Doing this costs nothing and buys: (a) the catalog blocks are plain HTML/CSS/JS files in an Apache-2.0 repo, so a Python fetcher in `app/scene/registry.py` can pull a block by name from GitHub raw and vendor it into `static/scene/blocks/` with its licence line, no `npx`; (b) a project folder can be opened in Hyperframes Studio by anyone who does have Node, which is the escape hatch for heavy manual editing without us building a Studio clone; (c) their motion and review docs apply to our scenes word for word.
- **GSAP.** Vendor `gsap.min.js` into `static/vendor/gsap/` (free standard licence since the Webflow acquisition; note it in `THIRD-PARTY.md`). Nothing else.
- **Authoring.** Scenes are HTML templates under `static/scene/<format>/` rendered with Jinja2 from the same JSON the cuts' `PLAN` prompts already emit (cues with anchor words and on-screen text). The planner output does not change; only the drawer does. The agent-facing CLI (section 7) can also write a scene file directly, which is the Hyperframes-style "agent writes HTML" path for one-off shots.
- **Preview.** The Timeline's proxy pipeline (`proxy_segment`) renders the scene at quarter size through the same runner, which is a `data-width` change. "Preview this bit" works unchanged. The scene editor tab can additionally show the live HTML in an iframe with a scrub bar driving `__seek`, which is free and is the one place a browser engine beats Pillow for the *editing* experience too.

### Migration order (each step deletes Python)

1. End card (`app/outro.py`) and chapter cards: smallest, proves the pipeline, exercises fonts and variables.
2. Intro slates (`app/intro.py`, 13 Pillow templates → 13 HTML templates sharing one stylesheet). Biggest line-count win.
3. Captions for the essay format (replaces the PNG-per-phrase path in `titles.render_caption`, NEXT_STEPS §8).
4. Diagrams and custom slides (`app/diagram.py`, `app/custom_slide.py`): Claude writes the HTML of the slide instead of a Pillow layout description. This is the single largest quality jump: layout and typography become CSS.
5. Drawn cuts one at a time, Loudmouth (kinetic type) first because it is the most typographic, Casefile last because its corkboard texture is the most Pillow-friendly. `app/cuts/kit.py` stays as the shared *plan* vocabulary; its drawing half retires.
6. Thumbnails (`app/thumbs.py`): render a 1280×720 scene at frame 0.
7. The 3D stage moves onto the same CDP capture when convenient, so there is one runner.

Pillow remains for: image conforming, focal-point analysis, LUT/grade previews, and any place a raster is read rather than drawn.

### Risks and mitigations

- **Chromium must be present.** Today the stage already requires a system Chrome/Chromium (`stage.browser()`), and PyWebView on Linux is WebKitGTK, not Chromium. Options in order: detect system Chrome (today); offer a one-click download of a pinned Chromium build into the data dir (like Playwright does, ~150 MB, Python `urllib`, no Node); as a last resort bundle it in the PyInstaller build. Fall back to the Pillow drawer for a format until it is deleted, and tell the user plainly which engine drew the preview.
- **Capture speed.** 1080p screenshots at 30–80 ms give 12–30 fps capture, roughly the Pillow cuts' speed today. Run two Chromium tabs on independent segments, same as the segment pool. Settled frames (the last 40 % of a finished card) are detected by identical DOM state hash and held by ffmpeg's `loop`, the same trick `HOLD_STILL` uses.
- **Fonts and colour.** Only `@font-face` fonts from `resources/fonts`; set `--force-color-profile=srgb` and tag BT.709 on the way out, as the WeAreNoCode pipeline does.
- **Memory rule.** Heavy renders are felt on this machine; every migration step ships with a preview-scale path first and a full render as an explicit opt-in.

## 4. Technical roadmap

Six phases, each shippable. Sizes: S under a day, M a few days, L a week or more.

### Facts from the code that shape it

- **No word timestamps exist.** `Take` in `app/schema.py` holds only duration and peak. `kit.place()` in `app/cuts/kit.py` times cues by *character offset* within the paragraph. But the installed `kokoro-onnx` has `create_timed()` (phoneme timings) gated on `model.has_timings`, which the stock weights may not expose. `app/audio.py` has an RMS envelope (`_levels`, `speech_span`) good enough for an estimate.
- **Claude vision already works**: `llm.complete_json(..., images=[bytes])`, used by `app/identify.py`.
- **Contact sheet and SSIM already exist** in `tests/stage/suite.py` (`sheet()`, `ssim()`), in the wrong place.
- **`render.timeline()`** already computes segment timing and per-segment `problems[]` without rendering; proxies are quarter-size webm per picture group (`_build_proxy`).
- **A banned default is live**: `kit.chapter_screen` is "fade + slide up 30px"; titles in `_render_segment` are a fixed 0.75s/0.85s fade with `hold = min(6, max(2, dur-1.2))`, not word-count driven.
- `jinja2` is not installed (pure Python, fine to add). `build/ dist/ .idea/` are already gitignored and untracked, just on disk.

### Phase 0: Foundations (rename mechanics, tests, word timing, contract)

| # | Item | Where | Size |
|---|---|---|---|
| 0.1 | `app/brand.py`: `NAME`, `SLUG`, `ENV_PREFIX`, `FILE_EXT`, `env(key)` reading `CORKBORED_*` then `YOUSLOP_*` then `VB_*`. Replace every `os.environ.get("YOUSLOP_…")` in `config.py`, `paths.py`, `research.py`, `ffutil.py`, `__main__.py`, `run.sh`; `settings.Field` gains `aliases` | config/settings/paths | M |
| 0.2 | Data-dir compat in `paths._platform_data_root`: use legacy `Youslop` dir if the new one is absent, log once | paths.py | S |
| 0.3 | File compat: `transfer.py` accepts `.youslop` and manifest key `youslop_project` alongside the new ones; same for `slide_styles.py` bundle key; file pickers in `app.js` accept both | transfer.py, slide_styles.py | S |
| 0.4 | Mechanical rename: spec file, `desktop.py` window/menu, `main.py` FastAPI title, logger names, log file (rotate old once), tempdir prefixes in `stage.py`/`cuts/__init__.py`, `index.html` title/favicon/mark, ~10 strings in `app.js`, `scripts/make_icon.py` (new mark), README family, docker-compose name | many, literal | M |
| 0.5 | Tests scaffold: extract the filtergraph builder from `_render_segment` into `_segment_graph()` so goldens need no ffmpeg; `tests/unit/test_graph_golden.py`, `test_timing.py` (voice offset = `T/2` + `HEAD_PAD`, which `_build_proxy` relies on), `test_place.py`; `tests/visual/test_ssim.py` opt-in via env; move `ssim()` to `tests/_ssim.py`; `requirements-dev.txt` | tests/, render.py | M |
| 0.6 | `Take.words`: TTS via `create_timed` when available (shift by the head `_finish_chain` trims); mic takes via `audio.estimate_words()` from the envelope, tagged `src:"est"` | schema.py, tts.py, audio.py, main.py `_voice_one`/`upload_take` | M |
| 0.7 | `app/storyboard.py`: `build(project)` = timeline + per-paragraph narration/title/chapter/picture/cues/words/style/frame; `apply(project, patch)` through a `_patch_slide_fields()` factored out of `main.patch_slide`. `app/cli.py` skeleton: `list`, `timeline`, `storyboard --json`, in-process under `store.lock_for`. Write `<DATA>/.cache/server.json` from the app so the CLI routes through HTTP when the app is open | new files, main.py | M |
| 0.8 | Memory cap re-measure (NEXT_STEPS 1): opt-in RSS measurement script, then a named constant | render.py `render()` | S |
| 0.9 | `CLAUDE.md` (architecture map, jobs pattern, memory rules, brand module rule, "no Node"); delete `build dist .idea __pycache__` from disk; `docs/roadmap.md` absorbs NEXT_STEPS | root | S |

### Phase 1: Doctrine port and check layer

| # | Item | Where | Size |
|---|---|---|---|
| 1.1 | `FrameSpec` dataclass: `arrive_s 0.45`, `exit_ratio 0.55`, `move_s (0.3,0.6)`, `title_hold_base 0.5`, `title_hold_per_word 0.3`, `last_line_min 2.0`, `title_height_pct (4,9)`, `montage_cut_s (0.13,0.8)`, `shot_avg_s (1.8,3.0)`, `payoff_hold_s (0.3,0.75)`, `transition_types`, `max_gap_s {0-90:15, 90+:20, ever:30}`, `overlays_per_hook 6`, `body_overlays_per_90 7`, `camera {creep (1.10,1.12), punch (1.18,1.25), origin top}`, `anchor_window_s (-0.10,0.60)`, `music_duck_db (-19,-16)`, `voice_lufs -14`, `banned[]`, `rejected_looks[]`, `rules[]`, `design_md`, `frame_md`. On `Channel` and `Project`, copied in `new_project` like `style` | schema.py | M |
| 1.2 | Theme overrides for frame in `themes.THEMES[*]["frame"]`; `apply_to_style` copies it | themes.py | S |
| 1.3 | `FrameSpec.prompt_block(format)` injected into `build_outline` (hook gate: first 3s works muted, first frame a meaningful image, first spoken word clear of any card or sting, `open_loops[{plant_beat, payoff_beat}]` checked in `verify_script`), `plan_visuals`, `plan_cues` after `module.PLAN`, `rewrite_slide`. Each cut's `PLAN` moves its hard-coded pacing into a `PACE` dict the spec fills | script_gen.py, cuts/*.py | M |
| 1.4 | ffmpeg camera vocabulary: `MOVES` becomes `CAMERA_OPS {set, creep, punch, release, reveal}`; `_kenburns()` gains `ease` (expo.out in the zoompan expression) and `origin="top"`; `frame.pick_op(index, prev, is_cut, is_payoff)` enforces never-the-same-device-twice and snap-to-100% on cuts; title timing from spec (`start = offset + arrive_s`, `hold = base + per_word × words`, out = `arrive_s × exit_ratio`); joins via `_join_for()` (hard cut inside a beat, fade on beat change, dip on chapter, named xfade only when the spec lists it) | render.py | M |
| 1.5 | `app/check.py`: pure-Python findings over the storyboard, `P0/P1/P2` with `t`, `slide_id`, `fix` payload. Rules: `empty_first_frame`, `hook_muted`, `first_word_collision`, `dead_stretch`, `gap_scan`, `overlay_budget`, `small_text` (dry-run `kit.fit`/`titles._fit_caption`), `unreadable_line`, `anchor_off` (P2 when `src=="est"`), `same_device_twice`, `last_line_short`, `silent_film`, `banned_used` | new | L |
| 1.6 | Check surfaced: `GET /api/projects/{pid}/check`, `cli check --json` (exit 1 on P0), findings merged into `render.timeline()` problems, Timeline panel with jump-to, `start_render` refuses a P0 unless forced | main.py, timeline.js | S |
| 1.7 | Audio doctrine: `_audio_graph` and `audio.voice_chain` defaults from `frame.music_duck_db`/`voice_lufs`; new-channel `duck_db` default moves from -11 to -17 | render.py, audio.py | S |

### Phase 2: HTML scene engine (Chromium, no Node) and first migrations

| # | Item | Where | Size |
|---|---|---|---|
| 2.1 | CDP capture mode in `stage._run()`: add `--remote-debugging-pipe` to the Chromium `cmd`, `pass_fds=(3,4)` on the `Popen`, a small `_Cdp` class (JSON messages, `\0` terminated, `Target.attachToTarget` flatten). Per frame: `Runtime.evaluate("__seek(t)", awaitPromise)` then `Page.captureScreenshot(png)`, bytes to an ffmpeg `image2pipe` encoder in a new `_begin_png()` beside `_begin()`. `Emulation.setDeviceMetricsOverride(deviceScaleFactor=0.25)` gives proxies for free. Keep the existing push mode for WebGL. Windows: `pass_fds` is POSIX, so fall back to `--remote-debugging-port=0` plus a ~120-line stdlib websocket client, or push-only | stage.py | L |
| 2.2 | Scene runtime: vendor `gsap.min.js` (check licence, record in `THIRD-PARTY.md`); `static/scene/runtime.js` finds `[data-composition-id]` and `.clip[data-start][data-duration]`, registers `window.__timelines`, defines `__seek(t)` (pause and seek every timeline, seek CSS animations and media, await `document.fonts.ready`), applies `data-var-*`; `static/scene/run.html` | static/scene | M |
| 2.3 | `app/scenes.py` + Jinja2: `render_html`, `ensure_clip()` cached under `project/scenes/<sha1>.mp4` exactly like `shots._render_item`; context = frame, palette (`themes.palette`), channel vars. Templates under `static/scene/<format>/` | new | M |
| 2.4 | Branch point: in `_render_segment` before the `custom:` check, `if scenes.handles(fmt): return scenes.render_segment(...)` with the same `lead_in`/`hold` arithmetic as `cuts.render_segment`. `_build_intro`/`_build_outro` route to `scenes.render_card()` when the template is a scene key. Proxies and Timeline unchanged | render.py | M |
| 2.5 | Migration 1: outro twins (`twoup`, `quiet` first) and `chapter.html`; stopgap chapter overlay for board/custom via one extra ffmpeg pass until 5.2 | static/scene/cards | M |
| 2.6 | Migration 2: intro slates, type-led templates first; private server's `translate_path` extended to serve project and channel assets read-only | static/scene/cards, stage.py | M |
| 2.7 | `app/catalog.py`: fetch Hyperframes blocks from raw GitHub into `DATA/assets/catalog/<block>/` with licence recorded, listable by CLI, includable as Jinja partials. No npm | new | S |

### Phase 3: Review loop, agent surface, learning loop

| # | Item | Where | Size |
|---|---|---|---|
| 3.1 | `app/review.py`: `snapshot_times()` (paragraph start and middle, each cut, hook beats at 0/1.5/3s); `grab(t)` from Timeline proxies with `ffmpeg -ss` (never a full render), `cuts.still()` for drawn cuts, one CDP capture for scenes; `sheet()` moved from the 3D suite; phone-width tiles at 360px | new | M |
| 3.2 | Claude vision review via `llm.complete_json(images=...)`: describe each frame as a stranger, P0/P1/P2, weakest shot, fix order text then timing then detail, no score. Writes `review/notes.json` and `REVIEW.md` (choices made, measured vs looked at, weakest shot, warnings kept); `Project.review` summary | review.py, schema.py | M |
| 3.3 | Fix routing: `text` to `rewrite_slide`, `cue` to `plan_cues(only=, instruction=)` (new params), `picture` to a media search hint, `timing` to the Phase 4 retime fields, `title` direct. Review panel on the Render tab with fix, dismiss, keep | review.py, main.py, timeline.js | M |
| 3.4 | "Ask the agent": `POST /agent/ask {t, selection, intent}` packages frame grab + storyboard slice + findings + frame spec into a prompt; copy to clipboard for Claude Code, or ask in-app and show the proposed `storyboard.apply` patch as a diff | review.py, main.py, timeline.js | M |
| 3.5 | CLI full loop and SKILL.md: `new`, `plan`, `research`, `check`, `snapshot`, `review`, `fix`, `render --section <sid>` (full render needs `--full --yes`), `publish`; handler bodies factored into `app/ops.py` so `main.py` and `cli.py` share them. `.claude/skills/corkbored-producer/SKILL.md` with `references/motion.md` generated from `FrameSpec` defaults by `cli doctrine` so numbers cannot drift | cli.py, ops.py, skills/ | M |
| 3.6 | Learning loop: "make this a rule" appends to `FrameSpec.rules` (emitted in every planner prompt), "reject this look" to `rejected_looks` (excluded by `pick_op`, themes, cut pickers), "save as format" snapshots style+frame+look into `Channel.formats[]` selectable at `new_project` | main.py, app.js | S |

### Phase 4: Timeline editor (vanilla JS, no build step)

| # | Item | Where | Size |
|---|---|---|---|
| 4.1 | Split `app.js` by script tags: `core.js` (state, api, route, render), `tabs/script.js`, `media.js`, `record.js`, `thumb.js`, `render.js`, `stage.js`, `home.js`; `timeline.js` into `timeline/{core,draw,inspect,edit,check,review,variables}.js`. All functions are globals called by name, so it is cut and paste | static/ | M |
| 4.2 | Retime fields: `Slide.gap_override`, `title_at`, `title_hold`, `chapter_hold`; cue objects gain optional `at`, honoured by `kit.place` | schema.py, kit.py, audio.py | S |
| 4.3 | Selection and per-kind inspector (`picture`, `paragraph`, `title`, `cue`, `chapter`, `slate`, `music`) saving via `saveSlide`/`saveStyle` | timeline.js | M |
| 4.4 | Layers rows: titles, cues (times from `kit.place` exposed in `render.timeline()`), chapters, music and stings; eye toggles | timeline.js | M |
| 4.5 | Drag and resize for cue, title and gap handles, snapped to 1/fps and word boundaries; paragraph edges stay fixed because the voice is the clock | timeline.js | M |
| 4.6 | Razor: `split_slide` gains `at` mapped to the nearest sentence boundary via `take.words`; key `S` on the Timeline; `C` marks a chapter | main.py, timeline.js | S |
| 4.7 | Variables panel: channel colours, copy, frame numbers; scene templates read them as `data-var-*` | timeline.js | S |
| 4.8 | Quick wins: searchable video list in `renderHome`; `script_gen.suggest_chapters()` from `section`/`beat` boundaries with a button in `paintScript` | app.js, script_gen.py | S |

### Phase 5: Remaining migrations, resume, verify

| # | Item | Where | Size |
|---|---|---|---|
| 5.1 | Essay captions as one scene composition per segment, replacing PNG-per-phrase inputs | static/scene/essay, render.py | M |
| 5.2 | Diagrams and custom slides as scenes; `_render_custom_style` routes to `scenes`; real text-size check via `getBoundingClientRect` over CDP. Removes the 13.5s board preview cost with no Pillow work | static/scene/slides, render.py | L |
| 5.3 | Drawn cuts to scenes, one at a time: Loudmouth, Flameboat, Ticker, Group Chat, Casefile. `kit.place` keeps timing; the cue list becomes `.clip` elements. `cuts.still()` becomes one capture | static/scene/cuts, cuts/ | L each |
| 5.4 | Thumbnails as a 1280×720 scene capture | thumbs.py | M |
| 5.5 | 3D stage gains `__seek(t)` so it can also run under CDP and share compositions with DOM overlays; push mode stays the fast path; solver untouched | static/stage/run.js | M |
| 5.6 | Resume a failed render: stop `rmtree(seg_dir)`, name segments by content key, skip existing, sweep stale | render.py | S |
| 5.7 | `app/verify.py` after encode: black runs, bitrate, A/V delta, clipped words, loudness; shown on the Render tab | new | S |

### Phase 9: Studio flow overhaul (added 2026-10-31)
The owner wants the whole UI and flow overhauled, not restyled. A project
becomes six stages (Plan as a corkboard of beats → Script → Visuals → Voice →
Edit (the Timeline workspace) → Review & publish) inside a new shell with a
stage stepper that says what is left. Footage, Library, Channels, Packs and
Settings are app-level screens. T9.1 is a written flow map plus static
mockups the owner signs off before any code; T9.2 is a headless screenshot
and console harness every later ticket uses. Depends on T4.1 (split JS) and
T6.1 (tokens). Tickets T9.1–T9.13 in `tickets/09-studio-flow/`.

### Phase 10: Sponsor segments (added 2026-10-31)
Sponsor reads as first-class segments: short (5–10 s) or long (30–60 s),
placed pre-roll (after the hook), mid-roll (at a paragraph boundary) or end
(before the outro), each with its own script, voice take and scene template;
later times shift by the segment. Sponsors live on channels; a built-in house
read, "This video was made with Corkbored...", is the first (mockup:
`docs/brand/mockups/sponsor-house-short.mp4`, template
`static/scene/sponsor/house_short.html`). Placement suggestions, check rules,
description blocks and YouTube's paid-promotion flag. Tickets T10.1–T10.7.
Open decision: house read opt-in or opt-out by default (T10.2).

### Phase 11: Footage: import, clip, label (added 2026-10-31)
For videos shot by the user (the owner's example: film a building outside,
the street, inside; come home with 90 minutes). Shoots are imported (linked,
originals never touched) with background proxies; shot detection cuts them
into clips; quality signals hide misfires and group duplicates; a vision
model labels clips from batched contact sheets (plus the user's own
vocabulary; transcripts opt-in); a keyboard logger finishes the job; clips
become a media provider matched to paragraphs and rendered by in/out from the
original; a shot list can be made from the script before filming. Tickets
T11.1–T11.8. Shares opt-in speech recognition with T7.8.

### Risks

- **CDP over pipe is POSIX-only.** Decide the Windows path (port plus stdlib websocket, or push-only) before promising scenes on Windows builds.
- **Screenshot throughput** is well under the 3D path's 40 fps. Scene segments are short and chunkable with the existing `CHUNK_SECONDS` parallelism, but a long all-scene cut must be benchmarked as an explicit opt-in step on this machine.
- **Determinism.** Timelines paused and seeked, CSS animations and media seeked explicitly, fonts awaited, or SSIM tests will flap.
- **Kokoro timings** may be absent for stock weights; anchor findings degrade to P2 on estimates.
- **Licences.** Verify GSAP's current licence and the Hyperframes catalog licence before vendoring or fetching.
- **WebKitGTK playback.** All proxies, including scene proxies, stay webm.
- **CLI vs app writes.** `server.json` routing plus a file lock in `store.save`.

## 5. Verification

- Unit tests run green in under 2s after Phase 0: `pytest tests/unit`.
- Golden filtergraph tests are updated deliberately in Phase 1, never regenerated blindly; one opt-in SSIM test per engine.
- Each scene migration ships with a side-by-side contact sheet of the Pillow and scene versions and a one-paragraph preview before any full render.
- End-to-end: from Claude Code, run `cli new "<idea>" --test` through `plan`, `check`, `snapshot`, `review`, `render --section` on a one-minute test project with the app closed, then the same with the app open.
- Rename: `grep -rniI 'youslop' --exclude-dir=.venv .` lists only compatibility shims; an install with only the legacy data dir starts with its projects intact; an old `.youslop` file imports.

## 6. Order of work

Phase 0 first in full, because 0.1 makes the rebrand one file and 0.5 makes everything after safe. Then Phase 1 and Phase 2 can proceed in parallel branches (doctrine touches planners and ffmpeg; the scene engine touches `stage.py` and new files). Phase 3 needs both. Phase 4 needs 0.6 and 0.7. Phase 5 is a queue, one migration per PR.


## 7. Carried forward from NEXT_STEPS

Migrated 2026-10-31. Ticket Goals define implementation scope; these entries
preserve the earlier queue's motivation and unticketed work.

| Former item | Coverage and remaining work |
|---|---|
| §1 Render memory cap | T0.8: measure peak segment RSS and derive the worker cap (now implemented with `SEGMENT_RSS_MB`). |
| §2 Cheap drawn previews | T5.2a-c migrate board, diagrams and custom slides to scenes; T5.2d-e extend authoring and text measurement. T5.3a-e separately migrate the five drawn cuts. Preview at quarter size rather than drawing every frame at 1080p. |
| §3 Chapter cards | T2.5 supplies scene chapter cards, including board/custom formats that return before the photographic filtergraph. |
| §4 Render tests | T0.5: graph goldens, voice offset `T/2` (+ `HEAD_PAD` first), timing invariants and opt-in SSIM (test scaffold now exists). |
| §5 Standalone videos | No dedicated ticket: support project-local opening stings, offer adoption of channel look/voice/narrator on promotion, and default thumbnails to the video's theme rather than `banner`. |
| §6 Searchable video list | T4.8: search title/idea and filter status on the home list. |
| §7 Propose chapters | T4.8: suggest editable chapter marks from section/beat boundaries. |

### Later work from §8

- Caption rendering: T5.1 replaces per-phrase Pillow PNGs with one timed scene
  per essay segment, reducing disk churn and ffmpeg inputs.
- Large UI/API modules: T4.1 splits tab painters and timeline code into plain
  script files; T3.5 extracts shared API/CLI operations. A broader split of
  the remaining API module has no dedicated ticket.
- Resume failed renders: T5.6 reuses finished segments by content key instead
  of discarding them on restart.

### Open research verification from §9

- No ticket: diagnose SearXNG's `format=json` 403 after restart, record empty
  research/failures in the project's own log, and have the owner verify the
  reported RJ Mitte research omission against reliable sources in a real
  script + Sources run; the earlier incident report remains unverified.

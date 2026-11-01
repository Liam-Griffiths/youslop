# Implementer notes: facts that apply to many tickets

Written 2026-10-26 by Opus 5.5 after reading the code behind every ticket and
testing the riskiest pieces. Each ticket also has its own
`## Implementer notes` section above `## Log`. Read this file once, then the
ticket's notes before its Steps.

**When a ticket's Steps and its notes disagree, the notes are newer and were
checked against the code.** Fix the Steps text to match (README says tickets
are the source of truth for intent), and say so in the Log.

## Before you run anything

- **The data root trap.** `config.DATA` is fixed at import time. This
  checkout has a `projects/` folder, so without an override every script
  and test resolves to the **repo**, and `projects/` holds the owner's own
  stubs. Set `CORKBORED_DATA` (or `YOUSLOP_DATA` before T0.1) **before**
  importing `app` in every script, test and one-off command.
- **The only project with real content is `pf0bf417b`**: essay format, 36
  recorded takes, 12 picture groups, in `~/.local/share/youslop`. Reach it
  with `YOUSLOP_DATA=~/.local/share/youslop`. Read from it freely. Before
  writing anything, copy the project folder into a temp data root.
- **Heavy work is felt on this machine** (Ryzen 7840-class, 8 cores, Radeon
  780M with VA-API). Say before starting anything that renders more than
  one segment, runs the 3D suite, or benchmarks. Preview one segment at
  quarter size; never the whole cut unless the ticket allows it.
- **Scripts that call `render.render` or the drawn cuts need an
  `if __name__ == "__main__":` guard.** Drawn-cut segments render in a
  `spawn` process pool, which re-imports the main script.
- **Never call a real LLM in tests.** Monkeypatch `llm.complete_json`. A
  ticket that needs one real run says so; one one-minute test project is
  the limit.

## Data model traps

- **`Project.to_dict()` and `Channel.to_dict()` are hand-written**, and
  both `from_dict`s exclude nested keys by name. A new nested field must be
  added in three places: the dataclass, `to_dict`, and the `from_dict`
  exclusion set plus constructor argument. Miss one and it is silently not
  saved, or the raw dict is passed to the constructor. Plain scalar fields
  on `Project` still need adding to `to_dict`.
- `Slide.to_dict` is `asdict`; `Slide.from_dict` drops unknown keys. New
  optional `Slide` fields are safe.
- **`Slide.take` is a plain dict**, not a `Take` object. `take["words"]` is
  all the storage word timings need. `Take(...)` is never constructed.
- **The documentary format's key is `"kenburns"`**, not `"documentary"`.
  Formats: `kenburns | essay | board | stage | <cut key> | custom:<id>`.
  Cut keys: `flameboat, casefile, loudmouth, groupchat, ticker`.
- **`Style.duck_db` is dead** and T1.7 removes it. Sidechain ducking was
  removed long ago; the music level is `Style.music_db` (dB under the
  voice; T1.7 moves the default from -22 to -17.5) and the master is
  `loudnorm=I=-14`.
- **Never delete recorded audio** (owner rule, 2026-10-26). Today a new
  recording or re-voice of a paragraph overwrites the previous file
  (`raw/<sid>.webm`, `takes/<track>/<sid>.wav`), and split/rewrite drop the
  take references. T4.9 fixes this with fresh file names and
  `slide.history`; T4.6 (razor) splits takes instead of dropping them. No
  ticket may `unlink` or overwrite a take.
- **`cuts.normalise` strips any cue key the cut's own `normalise` does not
  return**, except `on`. New cue keys (like `at` in T4.2) must be passed
  through there explicitly.

## Timing model (get this right once)

- A picture segment's file is `screen time + T` long, where
  `T = cuts.transition_for(style)` (the crossfade; one frame for cuts and
  stage). Joins overlap by exactly `T`. The voice starts `T/2` into each
  segment file, plus `HEAD_PAD` (0.6 s) on the first.
- `render.timeline()` is in picture time and reports `skip = T/2` per
  segment. To find absolute time `t` inside a proxy file:
  `t - seg["start"] + seg["skip"]` (the front end's `tlFileTime` does the
  same).
- Paragraph screen time = take duration + `audio.paragraph_gaps(project)[i]`.
  That one list drives both the narration bed and picture timing, which is
  why they cannot drift. Change gaps there and nowhere else.
- **Word timestamps are estimates on every take today.** The installed
  `kokoro-v1.0.onnx` reports `has_timings == False` (checked 2026-10-26),
  and hosted voices give none. T0.10 swaps in the published export with
  durations, after which new local-voice takes get `src == "tts"`; mic and
  hosted takes stay estimates. Every rule or tool that uses words must
  treat `src == "est"` as low confidence.

## Concurrency

- `store.lock_for(pid)` is a **`threading.RLock`**: it protects threads in
  one process only. It does nothing against the app when the CLI runs, which
  is why T0.7's `server.json` guard exists.
- Never hold the lock during a render, a Chromium capture or an LLM call.
  Do the slow work, then `with store.lock_for(pid): p = store.load(pid);
  <apply result>; store.save(p)`. Reload inside the lock; the UI saves
  meanwhile.
- `jobs.start(kind, pid, fn)` runs `fn(progress)` on a **daemon thread**. A
  CLI process must call the operation directly, not through `jobs`.
- API requests from loopback skip the access token (`_require_token`,
  main.py ~63).

## Scene engine (Phase 2 and 5), de-risked on 2026-10-26

- `02-scene-engine/reference/cdp_proto.py` is a working, standard-library
  CDP client over `--remote-debugging-pipe`, tested against this machine's
  Chromium 152 (`/usr/bin/chromium`). Results on a trivial page:
  480×270: 18.6 fps; 1920×1080: 15.1 fps; viewport 1920×1080 with
  `deviceScaleFactor` 0.25 gives 480×270 PNGs at 19.6 fps. Repeat captures
  are byte-identical; capture after `__seek(0.5)` equals frame 15 of a run.
- **The fd wiring needs care.** A plain `dup2(r, 3); dup2(w, 4)` in
  `preexec_fn` breaks whenever one source fd is already 3 or 4 (both ends
  land on the read pipe; Chromium logs "Could not write into pipe"). Use
  `fcntl.F_DUPFD` with a floor of 5 first. The prototype does.
- **Transparent capture works**:
  `Emulation.setDefaultBackgroundColorOverride {"color": {"r":0,"g":0,"b":0,"a":0}}`
  after load, `body { background: transparent }`, PNG screenshots are RGBA.
  Carry alpha as PNG-in-MOV; VP9 alpha needs `-c:v libvpx-vp9` before `-i`
  or ffmpeg drops it.
- **The real Hyperframes contract** (checked in their registry): components
  are full HTML files with a `<template>`, declare variables in
  `data-composition-variables`, read them with
  `window.__hyperframes.getVariables()`, register a paused timeline in
  `window.__timelines[id]`, and are mounted by a host `.clip` with
  `data-composition-src` and `data-variable-values`. Their demos use GSAP
  3.14.2. T2.2's notes have a mount shim.
- Registry index: `registry/registry.json` (456 items: blocks, components,
  examples); each item has `registry-item.json` with `files` and a
  `license` string. Details in T2.7's notes.
- `xfade=transition=custom:expr='if(gt(P,0.5),A,B)'` gives a hard cut at the
  exact midpoint of a fixed-length overlap (verified on the installed
  ffmpeg). T1.4 uses it to get cuts without changing the timing model.

## Piece to camera (Phase 7)

Added 2026-10-26 at the owner's request: camera recordings, as sections of a
video or whole videos. The design in one paragraph: a paragraph can be
`on_camera`, and then its take is a video with the voice in it. The voice is
cleaned by the same chain as a mic take (`audio.process_take`), and the
picture is cut at exactly the span that chain kept (`trimmed`), so the
existing timing model (take plus gap) drives camera footage unchanged.
Editing is an edit list on the take (`cuts`, `overlays`), never a re-encode
of the recording.

- **Long-take import is T7.8, a stretch goal.** It splits one long
  recording into paragraph takes using speech recognition (faster-whisper
  recommended), installed **opt-in** like the Kokoro model. This is the one
  exception to T0.6's no-forced-alignment rule, and the app must work
  unchanged without it. Do it after T7.1-T7.7.
- The desktop window's camera and microphone permissions are proven only on
  macOS. On Linux (WebKitGTK) they are written but untested; the system
  browser is the fallback for recording.

## Owner decisions (2026-10-26)

| Ticket | Decision |
|---|---|
| T1.7 | Treat it as if there are no existing projects: change the music default to -17.5 dB under the voice outright and remove `duck_db`. No migration. (Scoped to T1.7; every other ticket keeps the backwards-compatibility rule.) |
| T6.1 | Bring in both display faces (Space Grotesk 500 and condensed Archivo 800) behind a switch, and experiment. Archivo is the default until the owner picks. |
| T4.6 | Never delete recorded audio. The razor splits every take in every voice; T4.9 added so re-recording keeps earlier takes too. |
| T5.2 | Split, because a weaker model would struggle: now T5.2a-e. |
| Phase 7 | Support piece-to-camera, as sections and as whole videos. Start with recording per paragraph, like voice-over but picture and voice together. |
| Phase 8 | Content packs are how Corkbored earns money later; the app stays free and GPL. Packs are data only (themes, scene templates, music, 3D models, fonts), never Python. |
| T8.3 step 3 | **Open.** Whether to put `runtime.js`, `_base.html` and `_base.css` under MIT so pack templates can be licensed freely. Ask the owner before doing it. |

Implementer decision recorded in notes (make it once, then follow): T5.3a
decides where the cut scene branch lives (notes recommend inside
`cuts.render_segment`).

## Tickets whose Steps were corrected on 2026-10-26

- T0.5 step 6: the voice offset is `T/2` (half the transition), not
  `seg_len/2`.
- T2.1: the pipe-wiring snippet had the fd-collision bug; replaced with the
  tested version.
- T0.2's notes and T0.4's notes were adjusted after checking the code
  (checkout data-root rule; `make_icon.py` is macOS-only).
- After the owner's decisions: T1.7 and T4.6 rewritten, T4.9 added, T5.2
  replaced by T5.2a-e, T6.1 steps 0-1 changed to ship both faces.

## Model-specific advice for the implementer

- Each ticket's notes give the exact functions, line numbers (they drift;
  search by name) and stubs. Copy the stubs' shapes; fill the bodies.
- Make the smallest change that satisfies Acceptance. The notes often
  narrow a ticket (for example T1.5 `small_text` for drawn cuts is deferred
  to Phase 5). Narrowing is intended; do not widen it back.
- When a refactor is meant to change nothing (T0.5 `_segment_graph`, T0.7
  `edits.py`, T3.5 `ops.py`, T4.1 the JS split), prove it: capture the
  ffmpeg argv, the HTTP response or the concatenated source before and
  after, and diff. The notes say how for each.
- If a ticket grows past ~600 changed lines, stop, log what is done, and
  open a `b` ticket (README rule). T3.5 is the likely one.

## Scene rendering speed (2026-11-01)

Chromium draws; ffmpeg moves. Never screenshot every frame through CDP for content
that is static between short motions: capture each layer once (cached by content),
and let ffmpeg do holds, fades, rises, wipes and camera moves. Never build one ffmpeg
node per word or letter, and pass generated graphs with `-filter_complex_script`.
Use `app/scene_builder.py` (T2.8) rather than writing another compositor. Measured
cost of getting this wrong: Loudmouth 293 s vs Pillow 4.6 s for one picture.

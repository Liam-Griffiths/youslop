# Tickets: how to work them

This folder is the work queue for the Youslop → Corkbored roadmap in
`docs/roadmap.md`. Read that file's sections 1 to 3 once; it explains why
each ticket exists. Then work tickets one at a time.

## Picking up where we left off

1. Open `PROGRESS.md`. Find the first ticket whose status is `todo` and whose
   `Depends on` tickets are all `done`.
2. Set its status to `doing`, add today's date and your model name.
3. Read `NOTES.md` once per session. Then read the ticket top to bottom,
   including its **Implementer notes** (checked against the code on
   2026-10-26; newer than the Steps where they disagree), then the files
   under **Read first**.
4. Do the steps in order. Do not start the next ticket in the same change.
5. Run the **Verify** block. Paste the real output into the ticket under a
   `## Log` heading with the date. If something failed, say so there.
6. Set the status to `done` (or `blocked` with one line saying why).
7. Commit with the ticket id first in the message, e.g. `T0.1 brand module`.

If a ticket turns out to be wrong about the code, fix the ticket text before
fixing the code, and note it in the log. Tickets are the source of truth for
*intent*; the code is the source of truth for *what exists*.

## Design

UI work follows `docs/design/studio-flow.md` (the design guide) and the
mockup canvases it links. Read it before any Phase 4, 6, 9, 10 or 11 UI ticket.

## Rules that apply to every ticket

- **No Node, no npm, no npx.** Anything that needs a browser runs in the
  system Chromium through `app/stage.py`. Python, ffmpeg, Pillow and vendored
  JS files only.
- **No build step for the front end.** `static/` is plain JS loaded by script
  tags. New files are added to `static/index.html`.
- **Preview one section with cheap settings, never the whole cut.** A full
  render is an explicit, opt-in step and is felt on this machine. Tickets say
  when one is allowed.
- **3D solver rules must hold for any model.** Never tune the solver to the
  test models; add flags, not special cases.
- **Never delete recorded audio.** No ticket may delete, overwrite or
  orphan a recording. A take that is replaced is retired to
  `slide.history` (T4.9) and stays on disk. Owner rule, 2026-10-26.
- **Backwards compatibility.** Old `project.json` files, old `.youslop`
  exports, old env var names and the old data folder must keep working.
  Every ticket that touches schema uses "unknown keys ignored, missing keys
  defaulted", which `from_dict` already does.
- **Tests run in under two seconds** unless marked slow and gated on an env
  var. Golden tests are updated deliberately with a one-line reason, never
  regenerated blindly.
- **Small diffs.** A ticket that is growing past about 600 changed lines
  should be split: finish the part that is done, log it, open a `b` ticket.
- Line numbers in tickets were correct when written and will drift. Search
  for the function name, not the line.

## Ticket anatomy

```
# T2.1 CDP capture mode in the stage runner
Phase 2 · Size L · Depends on: T0.5

## Goal        one sentence, what exists when this is done
## Why         why it matters, in two or three sentences
## Read first  files and functions to read before touching anything
## Steps       numbered, concrete, in order
## Acceptance  bullet list, each checkable
## Verify      commands to run, and what their output must show
## Don't       things that look related but are out of scope
## Implementer notes   code facts, stubs and traps (added 2026-10-26)
## Log         filled in while working
```

Sizes: **S** under a day, **M** a few days, **L** a week or more.

## Commands you will use constantly

```sh
./run.sh                         # run the app from source
.venv/bin/python -m app          # same, without the window
.venv/bin/pytest tests/unit -q   # fast tests (exists after T0.5)
YS_VISUAL=1 .venv/bin/pytest tests/visual -q   # slow, opt-in
.venv/bin/python -m app.cli --help              # exists after T0.7
```

## Folder map

| Folder | Phase | Theme |
|---|---|---|
| `00-foundations` | 0 | rename mechanics, tests, word timing, storyboard contract, CLI skeleton |
| `01-doctrine-check` | 1 | FrameSpec numbers, prompts, ffmpeg camera vocabulary, check layer |
| `02-scene-engine` | 2 | HTML+GSAP scenes in headless Chromium, first migrations |
| `03-review-agent` | 3 | contact sheet, Claude vision review, fix routing, CLI loop, SKILL.md |
| `04-timeline-editor` | 4 | split app.js, selection, layers, drag retime, razor, variables |
| `05-migrations` | 5 | captions, slides, drawn cuts, thumbnails to scenes; resume; verify |
| `06-brand-rollout` | 6 | Instrument tokens, mark and icon, copy, mockup |
| `07-camera` | 7 | piece to camera: camera takes, recording, render, jump cuts, cutaways, talking-head videos |
| `08-packs` | 8 | content packs: the format and loader, the Packs screen, tooling and the first free pack |
| `09-studio-flow` | 9 | the UI and flow overhaul: flow map and mockups, screenshot harness, shell, six stages, jobs, first run |
| `10-sponsors` | 10 | sponsor segments: short and long reads, placement, templates, checks, publishing |
| `12-blocks` | 12 | Corkbored's own blocks: format, authoring kit, core set, data blocks, browser, make-your-own, retiring the third-party catalog, overlays over any picture |
| `11-footage` | 11 | the user's own footage: import, proxies, shot detection, quality, labels, logger, clips into the edit |

Phase 0 is done first in full. Phases 1 and 2 are independent of each other.
Phase 3 needs both. Phase 4 needs T0.6 and T0.7. Phase 5 is a queue. Phase 6
can run any time after T0.1 to T0.4. Phase 7 starts once T4.9 (keep every
take) is done; T7.1 to T7.3 need nothing else from Phases 1 to 5.
Phase 9 starts with T9.1 (owner signs off the mockups) and T9.2 (screenshot
harness), then needs T4.1 and T6.1. Phase 10 can start once T4.2 and T2.4 are
done. Phase 11 needs only T0.5 to start; its UI tickets wait for T9.3.

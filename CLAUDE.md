# Working on Corkbored

Corkbored turns an idea or script into a researched, narrated, illustrated video
on your own machine. Creators review sources, record or generate narration,
and edit pictures and timing before rendering. Channels carry a series' look
and defaults through to publishing.

## Start here

Read the rules in `docs/tickets/README.md` and shared gotchas in
`docs/tickets/NOTES.md`, then the assigned ticket in full, including its
Implementer notes and Read first files. The work queue is
`docs/tickets/PROGRESS.md`; the broader plan is `docs/roadmap.md`.
Search by function name because ticket line numbers drift.
For any UI work, read the design guide `docs/design/studio-flow.md` first.

## Run and test

From the repo root, with the existing virtual environment:

```sh
./run.sh                                      # desktop app
.venv/bin/python -m app                        # server without the window
.venv/bin/pytest tests/unit -q                 # fast unit tests
YS_VISUAL=1 .venv/bin/pytest tests/visual -q    # slow, explicit opt-in
.venv/bin/python -m app.cli --help             # CLI commands
```

Always set `CORKBORED_DATA` (or legacy `YOUSLOP_DATA`) to a temporary directory
before importing app in scripts or tests: `config.DATA` is fixed at import
time, and this checkout's `projects/` contains owner data.
Always set `CORKBORED_DATA` for any script that calls `store.save`.
For example, prefix a test command with `CORKBORED_DATA="$(mktemp -d)"`.
The test suite also isolates data in `tests/conftest.py`.
Never call a real LLM in tests; monkeypatch `llm.complete_json`.

## Architecture: stage → files

- Research → `app/research.py`; scripts and planning → `app/script_gen.py`.
- Assets → `app/media/`; narration → `app/tts.py`; audio cleanup and timing
  → `app/audio.py`.
- Photographic ffmpeg rendering and timeline/proxies → `app/render.py`;
  drawn formats → `app/cuts/`, `app/board.py`, `app/custom_slide.py`.
- 3D Chromium runner → `app/stage.py` + `static/stage/`.
  See `docs/3d-explainer.md` for the model-independent solver pipeline.
- HTML scene rendering is planned in T2.3; its module does not exist yet.
- HTTP API → `app/main.py`; CLI → `app/cli.py`; storyboard contract
  → `app/storyboard.py`; shared slide edits → `app/edits.py`.
- UI tabs and routing → `static/app.js`; timeline → `static/timeline.js`;
  plain script tags → `static/index.html`.
- Storage → `app/store.py`; schema → `app/schema.py`; data paths
  → `app/paths.py`; background jobs → `app/jobs.py`.

## Jobs and writes

`jobs.start(kind, pid, fn)` runs `fn(progress)` on a daemon thread and returns
an ID for UI polling. Pass the callable, not the result of calling it.
Do slow work (LLM, Chromium, render) outside the project lock, then reload
inside the lock before applying the result:

```python
with store.lock_for(pid):
    p = store.load(pid)
    # Apply the completed result to the freshly loaded project.
    store.save(p)
```

The lock is a process-local `threading.RLock`. CLI operations run directly,
not through jobs; CLI writes currently require the app to be closed and check
the server marker. Preserve that guard.

## Non-negotiables

The full rules live in `docs/tickets/README.md`.

- No Node, npm or npx.
- No front-end build step: use plain JS and script tags.
- Preview one section cheaply at quarter size; never render the whole cut
  without explicit authorization. No unsolicited 3D suite or benchmarks.
- 3D solver rules must hold for any model; add flags rather than special cases.

Never delete, overwrite or orphan recorded audio. Preserve old project files,
legacy environment names and data folders. Product names come from
`app/brand.py`; never hard-code "Corkbored" in application code.

# T2.5 owner visual checks

Chromium and loopback sockets are blocked in the implementation sandbox.
`outro_pillow.png` is the settled Pillow frame at t=2, at 480×270. The scene
comparison and visual acceptance remain pending; no Chromium was launched.

Run from the repo root outside the sandbox:

```sh
export CORKBORED_DATA="$(mktemp -d)"
export YOUSLOP_DATA="$CORKBORED_DATA"
.venv/bin/python -m app.cli scene-preview cards/outro_twoup.html --ctx tests/fixtures/ctx_channel.json --t 2.0 --out /tmp/outro.png
.venv/bin/python docs/tickets/02-scene-engine/compare/outro_compare.py
```

The second command writes `outro_scene.png` beside `outro_pillow.png`, using
the same channel, title, spec and t=2. Review both stills and retain the scene
PNG here. Expect a typographic grid with simpler plates and no movement after
landing. Check text fit and that video plates occupy identical rectangles.
Scene plates arrive by `frame.arrive_s`; Pillow retains its existing timing.

For one optional board segment preview at quarter size (no audio, no full cut):

```sh
export CORKBORED_DATA="$(mktemp -d)"
export YOUSLOP_DATA="$CORKBORED_DATA"
.venv/bin/python - <<'PY'
from pathlib import Path
from tests._fixtures import load_project
from app import render
p = load_project()
p.channel_id = ''
p.style.format = 'board'
render._render_segment(p, [(p.slides[0], 4.0)], 4.0, 0,
                       Path('/tmp/t25-board.webm'), chapter=('The next chapter', ''),
                       size=(480, 270), fps=15, crf=28)
print('/tmp/t25-board.webm')
PY
```

Play `/tmp/t25-board.webm`; confirm the outgoing segment ends on an opaque
chapter with stationary type, a fade in and a fade out. The stopgap replaces
the picture during the existing chapter hold; it adds no time or audio.

For channel preview and Timeline acceptance, start the app against temporary
data with `.venv/bin/python -m app`, create a temporary channel, enable its
outro, choose **Two up (scene)**, and run the channel preview. Use that channel
on a temporary project with local fixture takes and build its outro proxy in
Timeline. Confirm both show the same end card and configured duration. Also
select **Quiet (scene)** and check its preview with zero, one and two slots,
subscribe off/on, a handle, and the optional video title. Do not render a full
cut. Custom-slide dispatch and the too-short/no-chapter cases are unit tested.

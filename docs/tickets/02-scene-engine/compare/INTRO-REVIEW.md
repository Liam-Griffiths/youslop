# T2.6 owner visual checks

Chromium and loopback sockets are blocked in the implementation sandbox.
Only the Pillow comparison frame has been generated. Run from the repo root
outside the sandbox:

```sh
export CORKBORED_DATA="$(mktemp -d /tmp/corkbored-t26-review-XXXXXX)"
export YOUSLOP_DATA="$CORKBORED_DATA"
.venv/bin/python docs/tickets/02-scene-engine/compare/intro_compare.py
```

This writes `intro_scene.png` alongside `intro_pillow.png` for Dossier at t=2,
plus `intro_solo.png`, `intro_folio.png`, and `intro_portrait.png`. It captures
stills only, asserts quarter size and a stationary hold after arrival, uses a
temporary channel and a synthetic portrait, and never renders video or audio.
Retain the scene comparison PNGs after review. Check text fit, palette,
readability, and portrait visibility. These are simplified CSS migrations;
Pillow's decorative effects and per-template timing are not reproduced.

For channel preview, sting listening and Timeline acceptance:

```sh
export CORKBORED_DATA="$(mktemp -d /tmp/corkbored-t26-app-XXXXXX)"
export YOUSLOP_DATA="$CORKBORED_DATA"
.venv/bin/python -m app
```

In the temporary app, create a channel, choose **Signal · scene**
(`scene:intro_solo`), and attach a disposable local sting. Run the channel
intro preview and listen for its configured level, window and fade. On a
temporary project attached to the channel, enable the intro and build its
opening proxy in Timeline; confirm the slate appears first. Also select
**Portrait · scene**, upload one portrait in the cast panel, and check it
appears. Check long series names/taglines, optional episode titles, and the
Dossier/Folio choices. Do not render a full cut or use real project data.

The comparison script is the automated browser check; the app steps require
owner visual/listening judgement. They were not executed in the sandbox.

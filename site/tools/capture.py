"""Capture the site's screenshots from the running app, in one command.

Run from the repo root with the app's virtual environment:
    .venv/bin/python site/tools/capture.py path/to/example.corkbored

It imports the bundled example into a fresh temporary data folder (never the
owner's), serves the app with model calls disabled, drives headless Chromium
at 1440x900 with device scale 2, and writes one PNG per feature row into
site/media-src/. Then run site/tools/build_images.py.
"""
import base64
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / 'site' / 'media-src'
DATA = tempfile.mkdtemp(prefix='corkbored-site-capture-')
os.environ.update(CORKBORED_DATA=DATA, YOUSLOP_DATA=DATA, CORKBORED_TOKEN='off')
sys.path[:0] = [str(REPO), str(REPO / 'scripts')]

import ui_snapshots as U  # noqa: E402  (after CORKBORED_DATA is set)
from app.stage import _evaluate, _run_cdp  # noqa: E402

PID = 'pd575fb3a'
WIDTH, HEIGHT, SCALE = 1440, 900, 2
FIT_TRACK = "(()=>{tlFit&&tlFit();document.querySelector('#tl-track').scrollIntoView({block:'end'});scrollBy(0,40);return 1})()"
SETUP_MODELS = ("(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Writing model'));"
                "b&&b.click();return !!b})()")

# name, route, seconds to settle, optional script, crop box in CSS pixels (x0, y0, x1, y1).
SHOTS = [
    ('research', f'#/p/{PID}/plan', 3, None, (0, 52, 1440, 868)),
    ('script', f'#/p/{PID}/script', 3, None, (130, 52, 1300, 868)),
    ('voice', f'#/p/{PID}/voice', 3, None, (0, 52, 1440, 868)),
    ('visuals', f'#/p/{PID}/visuals', 4, None, (140, 52, 1300, 868)),
    ('blocks', '#/blocks', 25, None, (340, 160, 1300, 868)),
    ('timeline', f'#/p/{PID}/edit', 4, FIT_TRACK, (0, 420, 1440, 868)),
    ('models', '#/setup', 2, SETUP_MODELS, (470, 90, 1250, 868)),
]


def main(bundle: str) -> None:
    from app import transfer
    from PIL import Image
    import io
    U.seed()
    transfer.import_(Path(bundle))

    def visit(cdp, session, run):
        cdp.send('Emulation.setDeviceMetricsOverride', {'width': WIDTH, 'height': HEIGHT,
                 'deviceScaleFactor': SCALE, 'mobile': False}, session)
        for name, route, settle, script, box in SHOTS:
            # A hash change alone is a same-document navigation with no load event.
            cdp.clear_events()
            cdp.send('Page.navigate', {'url': 'about:blank'}, session)
            cdp.wait_event('Page.loadEventFired')
            cdp.clear_events()
            cdp.send('Page.navigate', {'url': base + route}, session)
            cdp.wait_event('Page.loadEventFired')
            time.sleep(settle)
            if script:
                _evaluate(cdp, session, script)
                time.sleep(2)
            png = base64.b64decode(cdp.send('Page.captureScreenshot', {'format': 'png'}, session)['data'])
            im = Image.open(io.BytesIO(png)).convert('RGB')
            im.crop(tuple(v * SCALE for v in box)).save(OUT / f'{name}.png', optimize=True)
            print('captured', name)

    with U.server() as base:
        _run_cdp({'items': []}, print, size=(WIDTH, HEIGHT), session_action=visit)
    # The channels row keeps its hand-made capture (a channel with a theme picked).


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    import shutil
    try:
        main(sys.argv[1])
    finally:
        shutil.rmtree(DATA, ignore_errors=True)  # only the temporary folder this run made

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

OPEN_SHOT = ("(()=>{const r=scriptRuns(state.project);scriptOpenShot(r[1][0].id);"
             "location.hash='#/p/%s/script/shots';return 1})()" % PID)
# The Create row shows one example graphic, written by hand into the example
# project (model calls are disabled while capturing; nothing is generated).
EXAMPLE_GRAPHIC = ('<section class="cb-slide"><figure class="cb-row">'
                   '<figure class="cb-card" data-layer="paris" data-start="0.3" data-motion="fly-left">'
                   '<p class="cb-label">Paris · 1934</p><h1 class="cb-number cb-accent">427 km</h1></figure>'
                   '<figure class="cb-card" data-layer="berlin" data-start="1.6" data-motion="fly-right">'
                   '<p class="cb-label">Berlin · 1940</p><h1 class="cb-number">400 km</h1></figure></figure></section>')

# name, route, seconds to settle, optional script, crop box in CSS pixels (x0, y0, x1, y1).
SHOTS = [
    ('home', f'#/p/{PID}/dashboard', 5, None, (0, 112, 1440, 868)),
    ('script', f'#/p/{PID}/script', 3, None, (0, 112, 1440, 868)),
    ('shots', f'#/p/{PID}/script', 3, OPEN_SHOT, (0, 112, 1440, 868)),
    ('create', f'#/p/{PID}/create', 8, None, (0, 112, 1440, 868)),
    ('voice', f'#/p/{PID}/voice', 3, None, (0, 52, 1440, 868)),
    ('blocks', '#/blocks', 25, None, (340, 160, 1300, 868)),
    ('timeline', f'#/p/{PID}/edit', 4, FIT_TRACK, (0, 420, 1440, 868)),
    ('models', '#/setup', 2, SETUP_MODELS, (470, 90, 1250, 868)),
]


def prepare():
    """What the example lacks for these rows: a graphic and a saved source page."""
    import time as clock
    from app import research_docs, store
    with store.lock_for(PID):
        p = store.load(PID)
        p.graphics = [dict(id='gexample', title='Paris and Berlin, side by side', seconds=6.0,
                           brief='The two networks at their peak, Paris landing first.',
                           versions=[dict(html=EXAMPLE_GRAPHIC, note='Example', at=clock.time())],
                           current=0, used_in=[], created_at=clock.time())]
        store.save(p)
    try:  # a real page, saved the way Home saves any link; skipped when offline
        doc = research_docs.fetch_document(PID, 'https://en.wikipedia.org/wiki/Pneumatic_post')
        with store.lock_for(PID):
            p = store.load(PID)
            p.research = dict(p.research or {}, documents=research_docs.documents(p) + [doc])
            store.save(p)
    except Exception as exc:
        print('no source page:', exc)


def main(bundle: str) -> None:
    from app import transfer
    from PIL import Image
    import io
    U.seed()
    transfer.import_(Path(bundle))
    prepare()

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
                time.sleep(3)
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

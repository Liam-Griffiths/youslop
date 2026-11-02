"""UI-only CDP screenshots. Browser execution is reviewer-run; no renders/LLMs.

Run: CORKBORED_DATA=$(mktemp -d) .venv/bin/python scripts/ui_snapshots.py
Always uses a fresh synthetic data root, regardless of the caller's environment.
"""
import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
FORMATS = ('kenburns', 'essay', 'loudmouth', 'stage')
PROJECT_STAGES = ('plan', 'script', 'voice', 'visuals', 'edit', 'publish')
PROJECT_TABS = ('script', 'media', 'record', 'thumb', 'render')


def routes():
    """Actual core.js routes; extend here when Phase 9 adds screens."""
    result = ['#/', '#/library', '#/settings', '#/guide', '#/projects',
              '#/footage', '#/packs', '#/channels', '#/channels/csnapshot',
              '#/channels/csnapshot/setup', '#/c/csnapshot', '#/c/csnapshot/setup']
    for fmt in FORMATS:
        tabs = tuple(dict.fromkeys(PROJECT_STAGES + PROJECT_TABS)) + (
            ('cast', 'stage', 'visuals/cast', 'visuals/stage') if fmt == 'stage' else ())
        tabs += ('visuals/media', 'publish/render', 'publish/thumb')
        result.extend(f'#/p/psnap{fmt}/{tab}' for tab in tabs)
    return result


def output_path(out, route):
    """Stable, flat PNG names with no traversal or ambiguous sanitization."""
    if route == '#/':
        return Path(out) / 'home.png'
    if not re.fullmatch(r'#/\w+(?:/\w+)*', route, flags=re.ASCII):
        raise ValueError(f'Invalid snapshot route: {route}')
    return Path(out) / (route[2:].replace('/', '--') + '.png')


def console_error(event):
    """Extract CDP errors without requiring a browser (ignore log/warn)."""
    params = event.get('params', {})
    if event.get('method') == 'Runtime.consoleAPICalled' and params.get('type') == 'error':
        args = params.get('args', [])
        return 'console.error: ' + ' '.join(str(a.get('description', a.get('value', a.get('type', '?'))))
                                           for a in args)
    if event.get('method') == 'Runtime.exceptionThrown':
        details = params.get('exceptionDetails', {})
        message = details.get('exception', {}).get('description') or details.get('text', 'JavaScript exception')
        return f"exception: {message} ({details.get('url', '')}:{details.get('lineNumber', 0) + 1})"
    return None


def seed():
    from app import channels, config, library, store
    from app.schema import Channel, Project, SponsorSlot
    config.ensure_dirs()
    channels.save(Channel(id='csnapshot', name='Snapshot channel', concept='Synthetic UI fixtures'))
    source = REPO / 'tests/fixtures/project_min'
    for fmt in FORMATS:
        pid = f'psnap{fmt}'
        dest = store.project_dir(pid)
        shutil.copytree(source, dest, dirs_exist_ok=True)
        raw = json.loads((dest / 'project.json').read_text())
        raw.update(id=pid, title=f'Snapshot · {fmt}', channel_id='csnapshot',
                   use_intro=False, use_outro=False)
        raw['style']['format'] = fmt
        # Opening Render automatically builds a narration mix when takes exist.
        # Keep copied fixture files, but seed unvoiced models so capture draws nothing.
        for slide in raw['slides']:
            slide['take'] = {}
        # Plan needs populated chapter columns, sources and hook as well as empty states.
        if fmt == 'essay':
            raw['research'] = {'facts': [{'claim': 'A synthetic archival fact.',
                'source': 'Fixture archive', 'url': 'https://example.test/archive'}]}
            raw['outline'] = {'thesis': 'A synthetic plan for reviewing the studio layout.',
                'hook': {'muted_image': 'The revolving door at morning rush.', 'first_line': 'Watch this door.'},
                'sections': [{'heading': name, 'chapter': chapter, 'kind': kind,
                    'summary': summary, 'words': 100, 'tags': [tag],
                    'sources': ['https://example.test/archive'] if i == 0 else []}
                    for i, (name, chapter, kind, summary, tag) in enumerate([
                        ('Morning rush', 'The door', 'intro', 'The door before the street wakes.', 'footage'),
                        ('After dark', 'The door', 'main', 'The same door stands empty.', 'footage'),
                        ('The vote', 'A block before', 'main', 'The commission considers the tower.', 'archive'),
                        ('Back to the door', 'What now', 'conclusion', 'Return to the opening image.', 'ending')])]}
        project = Project.from_dict(raw)
        if fmt == 'essay':
            project.sponsors = [SponsorSlot(id='snapshot-read', after_slide_id=project.slides[0].id,
                script='Sponsored by Example. Tools for your next project.',
                vars={'name': 'Example', 'learn': 'Tools for your next project.',
                      'made': 'Sponsored by', 'url': 'example.test', 'code': ''})]
        store.save(project)
    library.add((source / 'media/pic.jpg').read_bytes(), 'snapshot.jpg', title='Fixture picture')


@contextmanager
def server():
    import uvicorn
    # Bind once and hand the socket to uvicorn: no free-port race.
    from app.main import app
    def no_llm(*args, **kwargs):
        raise RuntimeError('LLM calls are forbidden in UI snapshots')

    with patch('app.llm.complete', no_llm), patch('app.llm.complete_json', no_llm), socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        instance = uvicorn.Server(uvicorn.Config(app, log_level='warning', lifespan='off'))
        thread = threading.Thread(target=instance.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not instance.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError('UI server failed to start')
                time.sleep(.02)
            yield f'http://127.0.0.1:{sock.getsockname()[1]}/'
        finally:
            instance.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('UI server failed to stop')


def capture(base, out):
    from app.stage import StageError, _evaluate, _run_cdp
    errors, rows = [], []

    def visit(cdp, session, run):
        current = ['startup']
        pending = set()
        activity = [time.monotonic()]
        lock = threading.Lock()

        def event(message):
            if message.get('sessionId') != session:
                return
            method, params = message.get('method'), message.get('params', {})
            with lock:
                if error := console_error(message):
                    errors.append(f'{current[0]}: {error}')
                if method == 'Network.requestWillBeSent':
                    pending.add(params['requestId'])
                    activity[0] = time.monotonic()
                elif method in ('Network.loadingFinished', 'Network.loadingFailed'):
                    pending.discard(params['requestId'])
                    activity[0] = time.monotonic()

        cdp.on_event = event  # Error sink survives the CDP queue's 200-event bound.
        cdp.send('Network.enable', session=session)
        cdp.send('Emulation.setDeviceMetricsOverride', {
            'width': 1600, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False}, session)
        for route in pending_routes[:]:
            cdp.clear_events()
            cdp.send('Page.navigate', {'url': 'about:blank'}, session)
            cdp.wait_event('Page.loadEventFired')
            current[0] = route
            # Fresh document per route: no cached state or previous route's async work.
            cdp.clear_events()
            nav = cdp.send('Page.navigate', {'url': base + route}, session)
            if nav.get('errorText'):
                raise StageError(nav['errorText'])
            cdp.wait_event('Page.loadEventFired')
            _evaluate(cdp, session, 'document.fonts.ready.then(() => true)')
            deadline = time.monotonic() + 8
            while True:
                with lock:
                    idle = not pending and time.monotonic() - activity[0] >= .35
                if idle:
                    break
                if time.monotonic() > deadline:
                    raise StageError(f'{route}: network did not become idle')
                time.sleep(.02)
            _evaluate(cdp, session, 'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            if route == '#/p/psnapessay/render':
                _evaluate(cdp, session, "tlSelectKind('sponsor'); true")
            png = cdp.send('Page.captureScreenshot', {'format': 'png', 'fromSurface': True}, session)
            path = output_path(out, route)
            path.write_bytes(base64.b64decode(png['data']))
            rows.append({'path': str(path), 't': 0, 'why': route})
            print(f'{route} -> {path.name}')
            pending_routes.pop(0)
        cdp.send('Runtime.evaluate', {'expression': 'true'}, session)  # drain earlier events

    # Headless Chromium sometimes stops answering Page.captureScreenshot on a
    # random route (see docs/tickets/NOTES.md). Retrying in the same browser does
    # not help; a fresh browser does. Restart from the stalled route, twice at most.
    pending_routes = routes()
    for restart in range(3):
        try:
            _run_cdp({'items': []}, print, size=(1600, 1000), session_action=visit)
            break
        except StageError as exc:
            if restart == 2 or 'captureScreenshot' not in str(exc):
                raise
            print(f'{pending_routes[0]}: screenshot stalled; restarting Chromium')
    return rows, errors


def compare(rows, previous):
    from tests._ssim import ssim
    for row in rows:
        path = Path(row['path'])
        before = Path(previous) / path.name
        if not before.is_file():
            print(f'NEW {path.name}')
            continue
        score = ssim(before, path, tile=(480, 300))
        print(f'{"CHANGED" if score < .995 else "same"} {path.name}: SSIM {score:.5f}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('ui-snapshots'))
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args(argv)
    if args.compare and args.compare.resolve() == args.out.resolve():
        parser.error('--compare must differ from --out to preserve the baseline')
    started = time.monotonic()
    sys.path.insert(0, str(REPO))
    # Before any app import. Never use the caller's data root, even for seeding.
    with tempfile.TemporaryDirectory(prefix='corkbored-ui-') as data:
        os.environ.update(CORKBORED_DATA=data, YOUSLOP_DATA=data, CORKBORED_TOKEN='off',
                          OPENAI_API_KEY='', ELEVENLABS_API_KEY='')
        try:
            from app import stage
            if not stage.browser():
                raise RuntimeError('Chromium unavailable; browser verification is reviewer-run')
            seed()
            args.out.mkdir(parents=True, exist_ok=True)
            with server() as base:
                rows, errors = capture(base, args.out)
            from app.review import sheet
            sheet(rows, args.out / 'sheet.png')
            (args.out / 'errors.json').write_text(json.dumps(errors, indent=2) + '\n')
            if args.compare:
                compare(rows, args.compare)
            for error in errors:
                print(error, file=sys.stderr)
            print(f'{len(rows)} screenshots; {len(errors)} console errors; {time.monotonic() - started:.2f}s')
            return int(bool(errors))
        except (OSError, RuntimeError) as exc:
            print(f'UI snapshots failed: {exc}', file=sys.stderr)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())

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
PROJECT_STAGES = ('dashboard', 'script', 'voice', 'edit', 'publish')
DASHBOARD_PROJECTS = ('psnapnew', 'psnaphalf', 'psnapdone')
DASHBOARD_SIZES = ((1280, 720), (1920, 1080))
PROJECT_TABS = ('script', 'media', 'record', 'thumb', 'render')


def routes():
    """Actual core.js routes; extend here when Phase 9 adds screens."""
    result = ['#/', '#/setup', '#/library', '#/settings', '#/guide', '#/projects',
              '#/blocks', '#/blocks/number_slam', '#/blocks/search/zzznomatch',
              '#/footage', '#/footage/ssnapshot', '#/footage/saudio', '#/footage/saudio/clips/a1', '#/packs', '#/channels', '#/channels/csnapshot',
              '#/channels/csnapshot/setup', '#/c/csnapshot', '#/c/csnapshot/setup']
    for fmt in FORMATS:
        tabs = tuple(dict.fromkeys(PROJECT_STAGES + PROJECT_TABS)) + (
            ('cast', 'stage', 'visuals/cast', 'visuals/stage') if fmt == 'stage' else ())
        tabs += ('plan', 'visuals', 'script/outline', 'edit/pictures', 'visuals/media', 'publish/render', 'publish/thumb')
        result.extend(f'#/p/psnap{fmt}/{tab}' for tab in tabs)
    result.extend(['#/p/psnapmixed/visuals', '#/p/psnapmixed/edit'])
    result.extend(f'#/p/{pid}/{tab}' for pid in ('psnapclip','psnapmanual')
                  for tab in ('clip','edit','publish','plan','script','voice'))
    result.append('#/p/psnaplong/edit')
    result.append('#/p/psnapinspector/edit')
    result.extend(['#/p/psnapinserts/edit', '#/p/psnapinserts/script'])
    result.extend(f'#/p/{pid}/dashboard' for pid in DASHBOARD_PROJECTS)
    result.extend(f'#/p/psnapwrite{size}/script' for size in ('short', 'long'))
    result.extend(f'#/p/{pid}/script/outline' for pid in ('psnapoutline','psnapbeatonly'))
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


def seed_writing():
    """Manuscript fixtures: no generated media, recordings, or model work."""
    from app import store
    from app.schema import BinItem, Project, Slide
    for size, count in [('short', 2), ('long', 32)]:
        p = Project(id=f'psnapwrite{size}', idea='Synthetic writing workspace', target_minutes=8,
            slides=[Slide(id=f'write{i}', narration='The station wakes before the city. '
                'Light crosses the empty platform as the first train arrives.',
                chapter=f'Chapter {i // 8 + 1}' if i % 8 == 0 else '',
                visual_note='An archive photograph of the platform before sunrise.') for i in range(count)])
        p.style.picture_every = 1 if size == 'short' else 3
        p.research = {'facts': [{'claim': 'The synthetic station opened in 1920.',
            'date': '1920', 'source': 'Fixture archive', 'url': 'https://example.test/archive'}],
            'flags': [{'slide_id': 'write1', 'severity': 'high', 'claim': 'Opening date',
                'issue': 'Confirm the date against the archive.'}]}
        p.research['facts'] += [
            dict(claim='The first train reaches the station at sunrise.', beat='Morning',
                 source='Timetable', date='2026', confidence='high'),
            dict(claim='Synthetic ocean tides peak at noon.', source='Tide archive', confidence='low')]
        p.slides[0].note = 'Private: check the pronunciation before recording.'
        p.slides[0].beat = 'Morning'
        p.bin = [BinItem(id='stationnote', kind='note', title='Station morning',
            note='The platform clock is visible before sunrise.', labels=['station'])]
        if size == 'long':
            p.set_take(p.slides[0], 'mic', {'path': 'takes/synthetic.wav',
                'duration': 5, 'narration': p.slides[0].narration})
        store.save(p)
        if size == 'long':
            p = Project.from_dict({**p.to_dict(), 'id': 'psnapbeatonly'})
            # Legacy scripts link every paragraph to an outline beat, without
            # chapter markers. Exercise fallback placement on the corkboard.
            p.outline = {'thesis': 'The station wakes before the city.',
                'hook': {'first_line': 'Watch the station.', 'muted_image': 'An empty platform.'},
                'sections': [{'id': f'writingbeat{i}', 'heading': f'Station beat {i+1}',
                    'chapter': f'Chapter {i+1}', 'summary': 'The station before sunrise.',
                    'words': 100, 'kind': 'main'} for i in range(4)]}
            for i, slide in enumerate(p.slides):
                slide.chapter = ''
                slide.beat = p.outline['sections'][i // 8]['heading']
            store.save(p)


def seed_outline():
    from app import store
    from app.schema import Project
    p = Project(id='psnapoutline', idea='Synthetic outline-only corkboard')
    p.outline = {'thesis':'Six chapters with wrapping beat headings.',
        'hook':{'first_line':'Watch the station.', 'muted_image':'An empty platform.'},
        'sections':[{'id':f'beat{i}', 'heading':f'A full beat title for chapter {i+1}',
            'summary':'The station opens before sunrise.', 'chapter':f'Chapter {i+1}',
            'words':100, 'kind':'main'} for i in range(6)]}
    store.save(p)


def seed():
    from app import channels, config, library, settings, store, footage, ffutil
    from PIL import Image
    from app.schema import Channel, Project, SponsorSlot, Style
    config.ensure_dirs()
    from app import block_library
    from PIL import ImageDraw
    for ref in ('number_slam', 'map_highlight', 'title_card'):
        for aspect, size in [('16:9', (480, 270)), ('9:16', (270, 480))]:
            path = block_library.poster_path(ref, aspect)
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new('RGB', size, '#16181C')
            draw = ImageDraw.Draw(image)
            draw.rectangle((24, 24, size[0]-24, 28), fill='#FF5A1F')
            draw.text((24, 50), ref.replace('_', ' ').upper(), fill='#F2F2F2')
            draw.text((24, 90), '42,000' if ref == 'number_slam' else 'ILLUSTRATIVE PREVIEW', fill='#A0A6AE')
            image.save(path)
    # A tiny, directly seeded viewing fixture; no original or analysis pipeline.
    shoot = footage.Shoot('ssnapshot', path='/synthetic/Morning shoot',
        files=[footage.SourceFile('f1', duration=4, width=320, height=180)],
        vocabulary=['Entrance', 'Street'], clips=[
            footage.Clip('c1', 'f1', 0, 2, labels=['Entrance'], note='Morning door',
                         duplicate_group='c1', best_take='c1'),
            footage.Clip('c2', 'f1', 2, 4, quality={'usable': False, 'reasons': ['blur']},
                         duplicate_group='c1', best_take='c1')])
    root = footage.shoot_dir(shoot.id)
    (root / 'proxies').mkdir(parents=True)
    (root / 'sprites').mkdir()
    ffutil.run(['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=5:duration=4',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                str(root / 'proxies/f1.mp4')], threads=1)
    Image.new('RGB', (1600, 90), (60, 60, 60)).save(root / 'sprites/f1.jpg')
    (root / 'thumbs').mkdir()
    for n, clip in enumerate(shoot.clips):
        clip.thumbs = []
        for i in range(3):  # The layout real shot detection writes.
            Image.new('RGB', (320, 180), (70 + 40 * n, 70, 90)).save(root / f'thumbs/{clip.id}-{i}.jpg')
            clip.thumbs.append(f'thumbs/{clip.id}-{i}.jpg')
    footage._save(shoot)
    # Audio logger and transcript editing fixture: no engine or inference.
    import wave
    from app import transcripts
    audio_root = footage.shoot_dir('saudio')
    (audio_root / 'sprites').mkdir(parents=True)
    audio = audio_root / 'fixture.wav'
    with wave.open(str(audio), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 64000)
    Image.new('RGB', (1600, 90), (60, 60, 60)).save(audio_root / 'sprites/a1.jpg')
    footage._save(footage.Shoot('saudio', path='/synthetic/Audio interview',
        files=[footage.SourceFile('a1', str(audio), kind='audio', duration=4)],
        clips=[footage.Clip('a1clip', 'a1', 0, 4)]))
    doc = dict(coverage=[[0, 2]], words=[dict(w='Helo.', start=.5, end=1.25, src='stt')], overrides=[])
    transcripts._rebuild(doc)
    transcripts._write(transcripts._path('saudio', 'a1'), doc)
    # Linked clip screens, with words and without a transcript. No clip renders.
    from app import clip_projects
    p = clip_projects.create('saudio', 'a1clip', {})
    p.id = 'psnapclip'
    store.save(p)
    manual = footage.Shoot('smanual', files=[footage.SourceFile('m1', str(audio), kind='audio', duration=4)],
                           clips=[footage.Clip('mclip','m1',0,4)])
    footage._save(manual)
    p = clip_projects.create('smanual', 'mclip', {})
    p.id = 'psnapmanual'
    store.save(p)
    settings.save_file({'setup_complete': 'true'})
    channels.save(Channel(id='csnapshot', name='Snapshot channel', concept='Synthetic UI fixtures',
        style=Style(block_theme={'accent':'#3DFFDC'}),
        blocks=['title_card'], block_presets=[dict(id='snapshot-preset', name='Our chapter card',
            block='title_card', values={'title':'The next chapter'})]))
    # Synthetic cached sheet/grid posters: UI snapshots never start captures.
    theme = block_library.theme_context('channel', 'csnapshot')['theme']
    for ref in block_library.SHEET_BLOCKS:
        for aspect, size in [('16:9', (480,270)), ('9:16', (270,480))]:
            key = block_library.sheet_poster_key(block_library.registry()[ref], theme, aspect,
                                                block_library.SHEET_VALUES.get(ref, {}))
            path = block_library.preview_file(key, 'trial')
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new('RGB', size, theme['bg'])
            draw = ImageDraw.Draw(image)
            draw.rectangle((24,24,size[0]-24,28), fill=theme['accent'])
            draw.text((24,50), ref.replace('_',' ').upper(), fill=theme['ink'])
            image.save(path)
    # Dashboard-only fixtures reference synthetic takes; no media/render is needed.
    from app.schema import BinItem, Slide
    from app.stages import render_signature
    for pid in DASHBOARD_PROJECTS:
        p = Project(id=pid, idea='Explore how a city wakes up.', title=pid,
                    channel_id='csnapshot', target_minutes=2)
        if pid != 'psnapnew':
            p.style.format = 'board'
            p.outline = {'hook': {'first_line': 'Watch this door.'},
                         'sections': [{'heading': 'Morning'}]}
            p.slides = [Slide(id=f'd{i}', narration='The first commuters arrive before sunrise.') for i in range(4)]
            if pid == 'psnaphalf':
                p.outline['hook']['first_line'] = p.slides[0].narration
            for slide in p.slides[:2 if pid == 'psnaphalf' else 4]:
                p.set_take(slide, 'mic', {'path': f'takes/{slide.id}.wav', 'duration': 4})
            p.research = {'facts': [{'claim': 'Synthetic fact'}], 'sources': [{'title': 'Fixture archive'}],
                          'open_questions': ['When did the station open?']}
            p.log = [f'Fixture activity {i + 1}' for i in range(10)]
        if pid == 'psnapdone':
            p.render = {'output': 'out/fixture.mp4', 'stage_signature': render_signature(p)}
        if pid != 'psnapnew':
            p.labels = ['Street', 'Research', 'Morning']
            p.bin = [BinItem(id=f'bin{i}', kind=('note','image','clip','audio','link')[i % 5],
                title=f'Morning reference {i+1}', note='A synthetic research note about the station.',
                labels=[p.labels[i % 3]], url='https://example.test/source' if i % 5 == 4 else '',
                duration=4 if i % 5 in (2,3) else 0) for i in range(12)]
            p.bin[1].title = 'Pneumatic tube entrance at the central station before sunrise'
            p.bin[1].labels = ['Street', 'Morning']
            for item in p.bin:
                if item.kind in {'image','clip'}:
                    thumb = store.project_dir(pid) / 'bin' / 'thumbs' / f'{item.id}.jpg'
                    thumb.parent.mkdir(parents=True, exist_ok=True)
                    item.file = f'bin/{item.id}.jpg'
                    Image.new('RGB', (320,180), '#46505C').save(thumb)
        store.save(p)
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
        if fmt in ('kenburns', 'essay'):
            project.slides[0].overlays = [dict(id='snapshot-graphic', block_id='lower_third_panel',
                vars={'title':'Hannah Chen', 'subtitle':'Ferry operator'}, at=0, dur=3,
                position='bottom_left', by='hand')]
        if fmt == 'essay':
            project.sponsors = [SponsorSlot(id='snapshot-read', after_slide_id=project.slides[0].id,
                script='Sponsored by Example. Tools for your next project.',
                vars={'name': 'Example', 'learn': 'Tools for your next project.',
                      'made': 'Sponsored by', 'url': 'example.test', 'code': ''})]
        store.save(project)
    from app.schema import Slide
    mixed = store.load('psnapkenburns')
    mixed.id, mixed.title = 'psnapmixed', 'Snapshot · mixed pictures'
    mixed.slides[1].kind = 'board'
    mixed.slides[1].board_lead = 'A stored board'
    mixed.slides[1].board_points = ['Keep this text when changing kind.']
    mixed.slides[2].kind = 'casefile'
    mixed.slides.append(Slide(id='s4', narration='A block closes this example.',
        cues={'blocks':[{'block':'title_card','vars':{'title':'The next chapter'}}]}))
    shutil.copytree(source, store.project_dir(mixed.id), dirs_exist_ok=True)
    store.save(mixed)
    # Twenty estimated minutes, without takes, a mix job or a render.
    long = store.load('psnapkenburns')
    long.id, long.title = 'psnaplong', 'Snapshot · twenty minute timeline'
    from app.config import WORDS_PER_MINUTE
    long.slides = [Slide(id=f'long{i}', narration=' '.join(['Timeline'] * WORDS_PER_MINUTE),
        title=f'Section {i+1}: a long title for truncation', gap_override=0,
        candidates=long.slides[0].candidates, chosen_id=long.slides[0].chosen_id)
        for i in range(20)]
    shutil.copytree(source, store.project_dir(long.id), dirs_exist_ok=True)
    store.save(long)
    asset = library.add((source / 'media/pic.jpg').read_bytes(), 'snapshot.jpg', title='Fixture picture')
    inserts = store.load('psnapkenburns')
    inserts.id, inserts.title = 'psnapinserts', 'Snapshot · main-track inserts'
    inserts.bin = [BinItem(id='editphoto', kind='image', title='Station photo',
                          source='library:'+asset['id'], shows='Station entrance', licence='CC0')]
    inserts.slides[0].candidates.append(dict(inserts.slides[0].candidates[0],
        id='archivefixture', provider='commons', title='Station archive', license='Public domain'))
    inserts.slides[1:1] = [
        Slide(id='insertclip', insert=dict(kind='clip', seconds=2, shoot_id='ssnapshot',
            source_id='f1', in_s=0, out_s=2, source_audio=False)),
        Slide(id='insertblock', insert=dict(kind='block', seconds=4, block='title_card', vars={'title':'A pause'})),
        Slide(id='insertpicture', insert=dict(kind='picture', seconds=4, asset_id=asset['id'])),
        Slide(id='insertcard', insert=dict(kind='card', seconds=4, text='The next chapter'))]
    shutil.copytree(source, store.project_dir(inserts.id), dirs_exist_ok=True)
    store.save(inserts)
    # A held paragraph and a cut share one Script description, with local candidates.
    inspector = store.load('psnapkenburns')
    inspector.id, inspector.title = 'psnapinspector', 'Snapshot · picture inspector'
    inspector.style.picture_every = 3
    candidate = inspector.slides[0].candidates[0]
    for i, slide in enumerate(inspector.slides):
        slide.chapter = ''
        slide.visual_note = 'The station before sunrise.'
        slide.picture_mode = ('auto', 'hold', 'cut')[i]
        slide.queries = ['station before sunrise', 'empty platform']
        slide.candidates = [{**candidate, 'id':f'option{j}', 'title':title}
                            for j, title in enumerate(('Station entrance', 'Empty platform', 'First train'))]
        slide.chosen_id = 'option0'
    shutil.copytree(source, store.project_dir(inspector.id), dirs_exist_ok=True)
    store.save(inspector)
    seed_writing()
    seed_outline()


@contextmanager
def server():
    import uvicorn
    # Bind once and hand the socket to uvicorn: no free-port race.
    from app.main import app
    def no_llm(*args, **kwargs):
        raise RuntimeError('LLM calls are forbidden in UI snapshots')

    def missing_engines(*args, **kwargs):
        from app.stt import ENGINES, METADATA
        return {name: dict(installed=False, version='', models=[], device='', notes='', install_url=url,
                           downloads=METADATA[name]['downloads'])
                for name, (_, url) in ENGINES.items()}

    with patch('app.stt.configured', missing_engines), patch('app.ops.initialize', lambda *args: None), patch('app.llm.complete', no_llm), patch('app.llm.complete_json', no_llm), socket.socket() as sock:
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


def capture(base, out, theme="dark"):
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
        cdp.send('Emulation.setEmulatedMedia', {'features': [
            {'name': 'prefers-color-scheme', 'value': theme}]}, session)
        cdp.send('Page.addScriptToEvaluateOnNewDocument', {'source':
            "try { localStorage.setItem('corkbored-theme', " + json.dumps(theme) + "); } catch (e) {}"}, session)
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
            if route == '#/settings':
                _evaluate(cdp, session, """(async () => {
                  const host = document.querySelector('#stt-engines');
                  if (!host.textContent.includes('Not found') ||
                      host.querySelectorAll('a').length < 4 ||
                      !document.querySelector('[id*="stt_hub_cache"]'))
                    throw Error('Speech Settings fields or missing-engine links missing');
                  const button = host.querySelector('[data-stt-download]');
                  if (!button) throw Error('Explicit model download missing');
                  const real = api, requests = [];
                  try {
                    api = async (url, options) => {
                      requests.push({url, options});
                      if (url === '/api/stt/download') return {job:'fake-download'};
                      if (url.endsWith('/cancel')) return {};
                      if (url === '/api/jobs/fake-download') {
                        // Exercise the real Cancel handler while progress is visible.
                        await host.querySelector('[data-download-status] button').onclick();
                        return {state:'cancelled', log:[{m:'4 of 8 bytes'}]};
                      }
                      throw Error('Unexpected download request');
                    };
                    await button.onclick();
                    if (!JSON.parse(requests[0].options.body).confirm ||
                        !requests.some(r=>r.url.endsWith('/cancel')) || button.disabled ||
                        !host.textContent.includes('Download cancelled.'))
                      throw Error('Explicit download/cancellation flow failed');
                  } finally { api = real; }
                  return true;
                })()""")
            if route == '#/p/psnapkenburns/voice':
                _evaluate(cdp, session, """(async () => {
                  const p = structuredClone(state.project), s = p.slides[state.rec.index];
                  s.takes = {mic:{path:'takes/synthetic.wav', duration:2, words:[]}};
                  p.voice_track = 'mic';
                  const panel = document.querySelector('.voice-takes');
                  panel.outerHTML = voiceTakesPanel(p, s);
                  const button = document.querySelector('[data-track=mic][data-path]');
                  if (!button || !button.textContent.includes('Retime words')) throw Error('Retime action missing');
                  const real = api, requests = [];
                  try {
                    api = async (url, options) => {
                      requests.push({url, options});
                      if (url.endsWith('/retime')) return {job:'synthetic-retime'};
                      if (url === '/api/jobs/synthetic-retime') return {state:'cancelled'};
                      throw Error('Unexpected retime request');
                    };
                    await retimeRecordedTake(button);
                    const body = JSON.parse(requests[0].options.body);
                    if (body.track !== 'mic' || body.path !== 'takes/synthetic.wav' || button.disabled)
                      throw Error('Retime selection or cancellation lost');
                    if (!document.querySelector('.voice-takes audio[controls]')) throw Error('Playback control removed');
                  } finally { api = real; }
                  return true;
                })()""")
            if route == '#/footage/saudio/clips/a1':
                _evaluate(cdp, session, """(() => {
                  const host=document.querySelector('#clip-finder'), player=document.querySelector('#cf-player');
                  if(!host || !document.querySelector('#cf-text').hidden) throw Error('Manual clip finder missing');
                  const key=k=>host.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true}));
                  player.currentTime=.2; key('i'); player.currentTime=1.8; key('o');
                  if(Number(document.querySelector('#cf-in').value)!==.2 || Number(document.querySelector('#cf-out').value)!==1.8) throw Error('I/O failed');
                  key('j'); key('k'); key('l'); key(' '); key('k');
                  document.querySelector('#cf-mode').click();
                  document.querySelector('[data-word="0"]').click();
                  if(Number(document.querySelector('#cf-in').value)!==.5) throw Error('Word selection failed');
                  return true;
                })()""")
            if route == '#/footage/saudio':
                _evaluate(cdp, session, """(async () => {
                  const host = document.querySelector('#footage-transcript');
                  if (!host.textContent.includes('No speech-to-text engine installed') ||
                      !document.querySelector('#transcript-estimate').disabled ||
                      !document.querySelector('#footage-player').src.includes('/media/audio/'))
                    throw Error('Audio/missing-engine transcript state missing');
                  const base = '/api/footage/shoots/saudio/transcripts/a1';
                  const before = (await api(base)).words;
                  const form = host.querySelector('form');
                  form.querySelector('input').value = 'Hello.';
                  await form.onsubmit({preventDefault(){}});
                  const after = (await api(base)).words;
                  if (after.length !== before.length || after[0].w !== 'Hello.' ||
                      ['start','end','src'].some(k=>after[0][k] !== before[0][k]))
                    throw Error('Word correction changed timing metadata');
                  // Exercise confirmation with a fake transport; never create a worker.
                  const real = api, requests = [];
                  try {
                    api = async (url, options) => {
                      if (!url.startsWith(base)) return real(url, options);
                      requests.push({url, body:JSON.parse(options.body)});
                      if (url.endsWith('/start')) throw Error('Synthetic start stopped');
                      return {seconds:4, chunks:1, engine:'fake', model:'local', detail:'Runtime unknown'};
                    };
                    const estimate = document.querySelector('#transcript-estimate');
                    for (const scope of ['whole','range','replace']) {
                      document.querySelector('#transcript-scope').value = scope;
                      await estimate.onclick();
                      if (requests.at(-1).url.endsWith('/start')) throw Error('Estimate started inference');
                      const body = requests.at(-1).body;
                      if ((scope === 'range') !== ('start' in body) ||
                          (scope === 'replace') !== !!body.retranscribe) throw Error('Run scope lost');
                    }
                    const confirm = document.querySelector('#transcript-confirm');
                    await confirm.onclick({target:confirm});
                    if (!requests.at(-1).body.confirm) throw Error('Explicit confirmation missing');
                    host.querySelector('fieldset').dispatchEvent(new Event('input'));
                    if (document.querySelector('#transcript-confirm')) throw Error('Stale estimate still confirmable');
                  } finally { api = real; }
                  return true;
                })()""")
            if route.endswith('/publish'):
                _evaluate(cdp, session, """(() => {
                  const body = document.querySelector('#tabbody');
                  if (state.project.kind === 'clip') {
                    const panel = body.querySelector('#clip-publish');
                    if (!panel || !panel.textContent.includes('Source range:') ||
                        !panel.querySelector('#clip-render') ||
                        !panel.querySelector(`a[href="#/p/${state.project.id}/edit"]`) ||
                        body.querySelector('a[href*="/visuals"]'))
                      throw Error('Clip Publish controls missing or link to skipped Visuals stage');
                  } else if (document.querySelector('.style-picker') || !body.textContent.includes('Change in Visuals')) {
                    throw Error('Publish style summary missing');
                  }
                  return true;
                })()""")
            if route.endswith('/clip'):
                _evaluate(cdp, session, """(() => {
                  const panel = document.querySelector('#clip-controls');
                  if (!panel || document.querySelector('.project-tools') ||
                      !panel.querySelector('button[onclick="saveProjectFile()"]'))
                    throw Error('Clip header has an extra tools band or lost project export');
                  if (getComputedStyle(panel.querySelector('h2')).marginTop !== '0px')
                    throw Error('Clip heading has excess top spacing');
                  if (!document.querySelector('.project-meta').textContent.includes(' · Clip · '))
                    throw Error('Clip project kind missing from shell');
                  for (const slide of state.project.slides) {
                    const text = document.querySelector(`[data-clip-paragraph="${slide.id}"] p`).textContent;
                    if (text !== (slide.narration || 'No words in this range'))
                      throw Error('Clip paragraph transcript or empty-range label missing');
                  }
                  return true;
                })()""")
            if route.split('/')[-1] in ('visuals', 'media', 'cast', 'stage'):
                _evaluate(cdp, session, "if (state.tab !== 'edit' || !document.querySelector('#tl-sources')) throw Error('Legacy route lost Edit'); true")
                expected = '3D' if route.split('/')[-1] in ('cast', 'stage') else 'Search'
                _evaluate(cdp, session, "if (tlSourceView.tab !== " + json.dumps(expected) + ") throw Error('Legacy route lost source tab'); true")
            if route == '#/p/psnapkenburns/visuals':
                _evaluate(cdp, session, """(async () => {
                  const before = JSON.stringify(await api('/api/projects/psnapkenburns'));
                  await openStylePicker('project'); await chooseStyleKit('casefile');
                  const dialog = document.querySelector('dialog.style-dialog');
                  if (!dialog.textContent.includes('follow the default') || !dialog.querySelector('[data-apply]')) throw Error('Dry-run summary missing');
                  dialog.querySelector('[data-close]').click();
                  if (before !== JSON.stringify(await api('/api/projects/psnapkenburns'))) throw Error('Cancel mutated project');
                  return true;
                })()""")
            if route == '#/channels/csnapshot/setup':
                _evaluate(cdp, session, """(() => {
                  if (!document.querySelector('.style-picker') || !document.querySelector('#view').textContent.includes('House style')) throw Error('House style missing');
                  const panel = document.querySelector('#block-theme');
                  if (panel.querySelector('#block-token-accent').value.toUpperCase() !== '#3DFFDC' ||
                      panel.querySelector('[data-source=accent]').textContent !== 'channel') throw Error('Channel block theme missing');
                  panel.scrollIntoView(); return true;
                })()""")
            if route == '#/blocks':
                _evaluate(cdp, session, """(async () => {
                  const input = document.querySelector('#blocks-preview-as');
                  input.value = 'channel:csnapshot'; input.dispatchEvent(new Event('change'));
                  await new Promise(r => setTimeout(r, 400));
                  if (!document.querySelector('[data-themed-ref=title_card]')) throw Error('Themed poster missing');
                  return true;
                })()""")
            if route == '#/channels/csnapshot':
                _evaluate(cdp, session, '''(() => {
                  const host = document.querySelector('#channel-blocks');
                  if (!host?.textContent.includes('Our chapter card') ||
                      host.querySelector('[data-kind]')?.dataset.kind !== 'blocks' ||
                      !host.querySelector('#channel-add-block')) throw Error('Channel Blocks section missing');
                  return true;
                })()''')
            if route == '#/p/psnapmixed/visuals':
                _evaluate(cdp, session, """(async () => {
                  const choose = async kind => {
                    await openPictureKind('s2');
                    await document.querySelector(`[data-picture-kind="${kind}"]`).onclick();
                  };
                  await choose('');
                  let saved = await api('/api/projects/psnapmixed');
                  if (saved.slides[1].kind || saved.slides[1].board_lead !== 'A stored board')
                    throw Error('Default kind lost board text');
                  await choose('board');
                  state.project = await api('/api/projects/psnapmixed');
                  if (state.project.slides[1].kind !== 'board') throw Error('Kind did not persist');
                  openEditPictureTools('s1');
                  if (!document.querySelector('.visual-source-body').textContent.includes('Search footage'))
                    throw Error('Photo picker missing');
                  selectVisual('s2');
                  if (!document.querySelector('.visual-source-body').textContent.includes('Edit the board') ||
                      !document.querySelector('#edit-picture-toolbar').textContent.includes('Board 1'))
                    throw Error('Board editor or mix count missing');
                  document.querySelector('#edit-picture-tools').closest('.modal').remove();
                  return true;
                })()""")
            if route == '#/p/psnapmixed/edit':
                _evaluate(cdp, session, "tlSelect(tlItems('paragraph').find(s => s.sid === 's2')); if (!document.querySelector('#tl-inspector [data-kind=board]')) throw Error('Inspector kind missing'); true")
            if route == '#/p/psnapessay/render':
                _evaluate(cdp, session, "tlSelectKind('sponsor'); true")
            if route == '#/p/psnapkenburns/edit':
                _evaluate(cdp, session, "(async () => { tlGraphicBlocks = await api('/api/blocks?overlay=1'); tlSelectKind('overlay'); return true; })()")
            if route == '#/p/psnapdone/dashboard':
                _evaluate(cdp, session, "binView.selected=['bin0']; binPanel(); true")
            png = cdp.send('Page.captureScreenshot', {'format': 'png', 'fromSurface': True}, session)
            path = output_path(out, route)
            path.write_bytes(base64.b64decode(png['data']))
            rows.append({'path': str(path), 't': 0, 'why': route})
            print(f'{route} -> {path.name}')
            if route in ('#/p/psnapoutline/script/outline', '#/p/psnapbeatonly/script/outline'):
                cdp.send('Emulation.setDeviceMetricsOverride', {
                    'width':1280, 'height':720, 'deviceScaleFactor':1, 'mobile':False}, session)
                _evaluate(cdp, session, 'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                path = path.with_name(path.stem + '--1280.png')
                path.write_bytes(base64.b64decode(png['data']))
                rows.append({'path':str(path), 't':0, 'why':route + ' at 1280×720'})
            if route == '#/p/psnapwritelong/script':
                for phase, width, height, expression in [
                    ('review', 1440, 900, 'scriptFocus(false); true'),
                    ('writing', 1280, 720, 'scriptFocus(false); true'),
                    ('focus', 1280, 720, 'scriptFocus(true); true'),
                    ('narrow', 900, 720, 'scriptFocus(false); true')]:
                    cdp.send('Emulation.setDeviceMetricsOverride', {
                        'width':width, 'height':height, 'deviceScaleFactor':1, 'mobile':False}, session)
                    _evaluate(cdp, session, expression)
                    _evaluate(cdp, session, 'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                    if phase == 'writing':
                        _evaluate(cdp, session, """(async () => {
                          scriptLocate('write0');
                          const el = document.querySelector('[data-para="write0"]');
                          const before = el.innerText, take = JSON.stringify(state.project.slides[0].take);
                          const range = document.createRange();
                          range.setStart(el.firstChild, 4); range.collapse(true);
                          getSelection().removeAllRanges(); getSelection().addRange(range);
                          scriptSaveCaret(el, 'write0');
                          document.querySelector('#script-fact-search').focus();
                          scriptInsertFact(0);
                          if (el.innerText !== before.slice(0,4) + state.project.research.facts[0].claim + before.slice(4))
                            throw Error('Fact missed saved caret');
                          await scriptFlush();
                          if (JSON.stringify(state.project.slides[0].take) !== take) throw Error('Insertion changed take');
                          document.execCommand('undo'); scriptInput(el, 'write0'); await scriptFlush();
                          if (el.innerText !== before) throw Error('Fact insertion cannot undo');
                          const note = document.querySelector('#script-note-write0');
                          note.value = 'Private inspector snapshot note'; scriptNoteInput(note, 'write0');
                          await scriptFlush();
                          const saved = await api('/api/projects/' + state.project.id);
                          if (saved.slides[0].note !== note.value || saved.slides[0].narration !== before)
                            throw Error('Private note did not save separately');
                          scriptRenderFacts('ocean');
                          if (!document.querySelector('#script-fact-list').textContent.includes('ocean tides') ||
                              document.querySelector('#script-fact-list').textContent.includes('1920'))
                            throw Error('All facts search failed');
                          scriptRenderFacts('');
                          document.querySelector('.script-main').scrollTop = 0;
                          return true;
                        })()""")
                    if phase == 'review':
                        _evaluate(cdp, session, """(() => {
                          const status = document.querySelector('.script-status').getBoundingClientRect();
                          const jobs = document.querySelector('.jobs-strip').getBoundingClientRect();
                          if (Math.abs(status.bottom - jobs.top) > 2) throw Error('Writing panes do not fill to jobs strip');
                          const tabs = document.querySelector('.stage-subtabs');
                          const tools = document.querySelector('.script-tools');
                          const shot = document.querySelector('.script-shot-heading');
                          if (Math.abs(tabs.getBoundingClientRect().top - tools.getBoundingClientRect().top) > 8 ||
                              shot.getBoundingClientRect().top - document.querySelector('.stage-bar').getBoundingClientRect().bottom > 180)
                            throw Error('Writing toolbar or first shot is too low');
                          document.querySelector('[data-binder-sid="write1"]').click();
                          const text = document.querySelector('[data-para="write1"][contenteditable]');
                          if (document.activeElement !== text || !text.contains(getSelection().anchorNode))
                            throw Error('Binder click did not place narration caret');
                          scriptWorkspaceKey({key:'ArrowUp', ctrlKey:true, preventDefault(){}});
                          if (document.activeElement.dataset.para !== 'write0')
                            throw Error('Previous paragraph did not focus narration');
                          document.querySelector('.script-main').scrollTop = 0;
                          return true;
                        })()""")
                    png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                    extra = path.with_stem(f'{path.stem}--{phase}')
                    extra.write_bytes(base64.b64decode(png['data']))
                    rows.append({'path':str(extra), 't':0, 'why':phase})
                cdp.send('Emulation.setDeviceMetricsOverride', {
                    'width':1600, 'height':1000, 'deviceScaleFactor':1, 'mobile':False}, session)
            if route in [f'#/p/{pid}/dashboard' for pid in DASHBOARD_PROJECTS]:
                for width, height in DASHBOARD_SIZES:
                    cdp.send('Emulation.setDeviceMetricsOverride', {
                        'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False}, session)
                    _evaluate(cdp, session, 'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                    png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                    extra = path.with_stem(f'{path.stem}--{width}x{height}')
                    extra.write_bytes(base64.b64decode(png['data']))
                    rows.append({'path':str(extra), 't':0, 'why':f'{route} at {width}×{height}'})
                cdp.send('Emulation.setDeviceMetricsOverride', {
                    'width':1600, 'height':1000, 'deviceScaleFactor':1, 'mobile':False}, session)
            if route == '#/p/psnapdone/dashboard':
                for phase, expression in [
                    ('bin-multi-select', "binSelect('bin0', {}, binView.items.map(i=>i.id)); binSelect('bin3', {shiftKey:true}, binView.items.map(i=>i.id)); true"),
                    ('bin-vocabulary', "document.querySelector('#bin-edit-labels').click(); true")]:
                    _evaluate(cdp, session, expression)
                    png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                    extra = path.with_stem(f'{path.stem}--{phase}')
                    extra.write_bytes(base64.b64decode(png['data']))
                    rows.append({'path':str(extra), 't':0, 'why':phase})
                _evaluate(cdp, session, "document.querySelector('dialog[open]').close(); true")
            if route == '#/p/psnapinspector/edit':
                for width, height in ((1280, 720), (1440, 900), (1920, 1080)):
                    cdp.send('Emulation.setDeviceMetricsOverride', {
                        'width':width, 'height':height, 'deviceScaleFactor':1, 'mobile':False}, session)
                    _evaluate(cdp, session, "tlSelect(tlItems('picture')[0]); true")
                    _evaluate(cdp, session, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                    _evaluate(cdp, session, """(() => {
                      for (const selector of ['#tl-stage','.tl-pictures','.tl-lane.para','.tl-playhead-handle']) {
                        const r=document.querySelector(selector).getBoundingClientRect();
                        if (r.height <= 0 || r.top < 0 || r.bottom > innerHeight-32) throw Error(selector+' outside viewport');
                      }
                      const tools=document.querySelector('.tl-picture-tools');
                      if (tools.querySelectorAll('[data-candidate]').length !== 3 ||
                          tools.querySelectorAll('[data-picture-mode]').length !== 2 ||
                          !tools.querySelector('[data-candidate][aria-pressed=true]')) throw Error('Picture fixture missing');
                      const side=document.querySelector('.tl-side');
                      const strip=tools.querySelector('.tl-picture-candidates');
                      side.scrollTop+=strip.getBoundingClientRect().top-side.getBoundingClientRect().top;
                      const r=strip.getBoundingClientRect(), bounds=side.getBoundingClientRect();
                      if (Math.min(r.bottom,bounds.bottom)-Math.max(r.top,bounds.top) < 34)
                        throw Error('Candidates cannot be scrolled into view');
                      return true;
                    })()""")
                    png = cdp.send('Page.captureScreenshot', {'format':'png','fromSurface':True}, session)
                    extra = out / f'p--psnapinspector--candidates--{width}.png'
                    extra.write_bytes(base64.b64decode(png['data']))
                    rows.append({'path':str(extra), 't':0, 'why':f'Picture candidates at {width}×{height}'})
                cdp.send('Emulation.setDeviceMetricsOverride', {
                    'width':1600, 'height':1000, 'deviceScaleFactor':1, 'mobile':False}, session)
            if route == '#/p/psnapinserts/edit':
                for width, height in ((1280, 720), (1440, 900), (1920, 1080)):
                    cdp.send('Emulation.setDeviceMetricsOverride', {
                        'width':width, 'height':height, 'deviceScaleFactor':1, 'mobile':False}, session)
                    for tab in ('Materials', 'Library', 'Search', 'Blocks', '3D', 'Graphics'):
                        _evaluate(cdp, session, "tlSelect(tlItems('picture')[0]); tlSourceView.tab=" + json.dumps(tab) + "; tlSourcesPaint(); document.querySelector('.tl-source-results').scrollTop=0; true")
                        _evaluate(cdp, session, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                        _evaluate(cdp, session, """(() => {
                          for (const selector of ['#tl-stage','.tl-pictures','.tl-lane.para','.tl-playhead-handle']) {
                            const r=document.querySelector(selector).getBoundingClientRect();
                            if (r.height <= 0 || r.top < 0 || r.bottom > innerHeight-32) throw Error(selector+' outside viewport');
                          }
                          const panel=document.querySelector('#tl-sources').getBoundingClientRect();
                          for (const tab of document.querySelectorAll('.tl-source-tabs button')) {
                            const r=tab.getBoundingClientRect();
                            if (r.width <= 0 || r.height < 34 || r.left < panel.left || r.right > panel.right ||
                                r.top < panel.top || r.bottom > panel.bottom) throw Error(tab.textContent+' tab clipped');
                          }
                          const results=document.querySelector('.tl-source-results');
                          const r=results.getBoundingClientRect();
                          const items=[...document.querySelectorAll('[data-source-grid] [data-source]')];
                          if (tlSourceView.tab === 'Materials' && !items.length) throw Error('Materials fixture has no sources');
                          if (tlSourceView.tab === 'Search' && (!items.length || !items.every(b=>b.draggable)))
                            throw Error('Archive fixture missing draggable results');
                          if (items.length) {
                            const first=items[0].getBoundingClientRect();
                            const visible=Math.min(first.bottom,r.bottom,panel.bottom)-Math.max(first.top,r.top,panel.top);
                            if (r.height < 32 || visible < 32) throw Error('Sources grid has no usable visible height');
                            if (!['auto','scroll'].includes(getComputedStyle(results).overflowY)) throw Error('Sources cannot scroll');
                            results.scrollTop+=items.at(-1).getBoundingClientRect().top-r.top;
                            const last=items.at(-1).getBoundingClientRect();
                            if (Math.min(last.bottom,r.bottom)-Math.max(last.top,r.top) <= 0)
                              throw Error('Last source cannot be scrolled into view');
                            results.scrollTop=0;
                          }
                          return true;
                        })()""")
                        png = cdp.send('Page.captureScreenshot', {'format':'png','fromSurface':True}, session)
                        extra = out / f'p--psnapinserts--sources-{tab.lower()}--{width}.png'
                        extra.write_bytes(base64.b64decode(png['data']))
                        rows.append({'path':str(extra), 't':0, 'why':f'{tab} at {width}×{height}'})
                    for tool in ('picture', 'cast', 'stage'):
                        expression = "openEditPictureTools(); true" if tool == 'picture' else "openEditStageTools(" + json.dumps(tool) + ")"
                        _evaluate(cdp, session, expression)
                        _evaluate(cdp, session, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                        png = cdp.send('Page.captureScreenshot', {'format':'png','fromSurface':True}, session)
                        extra = out / f'p--psnapinserts--tools-{tool}--{width}.png'
                        extra.write_bytes(base64.b64decode(png['data']))
                        rows.append({'path':str(extra), 't':0, 'why':f'{tool} tools at {width}×{height}'})
                        _evaluate(cdp, session, "document.querySelector('#edit-picture-tools, #edit-stage-tools').closest('.modal').querySelector('[data-close]').click(); true")
                cdp.send('Emulation.setDeviceMetricsOverride', {
                    'width':1600, 'height':1000, 'deviceScaleFactor':1, 'mobile':False}, session)
                for phase, expression in [
                    ('insert-panel', "tlSourceView.tab='Materials'; tlSourcesPaint(); true"),
                    ('insert-inspector', "tlInsertSelect('insertclip'); true"),
                    ('insert-drop', "tlInsertGhost(tlInsertNearest(), 4); true"),
                    ('insert-menu', "tlInsertClearGhost(); tlInsertMenu(); true")]:
                    _evaluate(cdp, session, expression)
                    png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                    extra = out / f'p--psnapinserts--{phase}.png'
                    extra.write_bytes(base64.b64decode(png['data']))
                    rows.append({'path':str(extra), 't':0, 'why':phase})
                _evaluate(cdp, session, "document.querySelector('dialog.tl-insert-dialog [data-close]').click(); true")
            if route == '#/p/psnapkenburns/edit':
                point = _evaluate(cdp, session, """(() => {
                  const rows=tlParas(); tlSectionSet(rows[1].id, rows[2].id);
                  const node=document.querySelector(`[data-para="${rows[1].id}"]`);
                  node.scrollIntoView({block:'center'}); const r=node.getBoundingClientRect();
                  return {x:r.left+8,y:r.top+8};
                })()""")['result']['value']
                for phase in ('section', 'section-ghost'):
                    if phase == 'section-ghost':
                        cdp.send('Input.dispatchMouseEvent', {'type':'mousePressed', **point,
                                 'button':'left', 'buttons':1, 'clickCount':1}, session)
                        cdp.send('Input.dispatchMouseEvent', {'type':'mouseMoved',
                                 'x':point['x']-60, 'y':point['y'], 'buttons':1}, session)
                        _evaluate(cdp, session, "if (!document.querySelector('.tl-section-ghost')) throw Error('Section ghost missing'); true")
                    png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                    path = out / f'p--psnapkenburns--{phase}.png'
                    path.write_bytes(base64.b64decode(png['data']))
                    rows.append({'path':str(path), 't':0, 'why':phase})
                cdp.send('Input.dispatchKeyEvent', {'type':'keyDown', 'key':'Escape', 'windowsVirtualKeyCode':27}, session)
                cdp.send('Input.dispatchMouseEvent', {'type':'mouseReleased', **point, 'button':'left'}, session)
                _evaluate(cdp, session, "if (TL.drag || document.querySelector('.tl-section-ghost')) throw Error('Section cancel failed'); tlSelect(null); true")
                for phase in ('section-copy', 'section-paste'):
                    _evaluate(cdp, session, """(async () => {
                      const rows=tlParas();
                      if (!tlSectionClipboard) {
                        window.__sectionBefore=JSON.stringify(state.project.slides);
                        tlSectionSet(rows[1].id,rows[2].id); tlSectionSave('copy');
                      } else { TL.cur=rows.at(-1).start; tlSectionSave('paste'); }
                      await tlInspectorQueue;
                      if (!tlSectionClipboard) throw Error('Clipboard missing');
                      return true;
                    })()""")
                    png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                    path = out / f'p--psnapkenburns--{phase}.png'
                    path.write_bytes(base64.b64decode(png['data']))
                    rows.append({'path':str(path), 't':0, 'why':phase})
                _evaluate(cdp, session, """(async () => {
                  if (!state.project.slides.some(s=>s.duplicate_of)) throw Error('Paste missing');
                  await restoreProjectEdit('undo');
                  if (JSON.stringify(state.project.slides)!==window.__sectionBefore) throw Error('Paste undo changed source');
                  tlSectionClipboard=null; tlSelect(null); return true;
                })()""")
            if route == '#/':
                _evaluate(cdp, session, """(async () => {
                  if (document.querySelector('#home-format,#saved-format')) throw Error('Duplicate Home picker');
                  await openStylePicker('home'); await chooseStyleKit('casefile');
                  if (state.newKit !== 'casefile' || state.newFormat !== 'casefile') throw Error('Home choice lost');
                  const r = await api('/api/projects',{method:'POST',body:JSON.stringify({idea:'Synthetic city story',kit_id:state.newKit})});
                  const kit = state.styleKits.find(k => k.id === 'casefile');
                  if (r.project.style.format !== 'casefile' || r.project.style.accent !== kit.look.accent) throw Error('Home kit not applied');
                  await openStylePicker('home'); return true;
                })()""")
                png = cdp.send('Page.captureScreenshot', {'format':'png','fromSurface':True}, session)
                picker = out / 'home--styles.png'; picker.write_bytes(base64.b64decode(png['data']))
                rows.append({'path':str(picker),'t':0,'why':'Grouped style picker'})
                _evaluate(cdp, session, "designStyleBlock(); new Promise(r => setTimeout(() => r(true),500))")
                _evaluate(cdp, session, "if (!document.querySelector('.block-create')?.open || document.activeElement.id !== 'block-description') throw Error('Describe flow not focused'); true")
            if route == '#/blocks/number_slam':
                _evaluate(cdp, session, "document.querySelector('#block-expand').focus(); document.querySelector('#block-expand').click(); true")
                _evaluate(cdp, session, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                png = cdp.send('Page.captureScreenshot', {'format':'png', 'fromSurface':True}, session)
                player = out / 'blocks--number_slam--player.png'
                player.write_bytes(base64.b64decode(png['data']))
                rows.append({'path':str(player), 't':0, 'why':'Expanded block player'})
                print(f'Expanded block player -> {player.name}')
                cdp.send('Input.dispatchKeyEvent', {'type':'keyDown', 'key':'Escape', 'code':'Escape', 'windowsVirtualKeyCode':27}, session)
                cdp.send('Input.dispatchKeyEvent', {'type':'keyUp', 'key':'Escape', 'code':'Escape', 'windowsVirtualKeyCode':27}, session)
                _evaluate(cdp, session, "new Promise(r => requestAnimationFrame(r))")
                _evaluate(cdp, session, "(() => { if (document.querySelector('dialog[open]') || document.activeElement.id !== 'block-expand') throw Error('Block player Escape/focus failed'); return true; })()")
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
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark',
                        help='Same synthetic routes in either theme; use separate output folders')
    args = parser.parse_args(argv)
    if args.compare and args.compare.resolve() == args.out.resolve():
        parser.error('--compare must differ from --out to preserve the baseline')
    started = time.monotonic()
    sys.path.insert(0, str(REPO))
    # Before any app import. Never use the caller's data root, even for seeding.
    with tempfile.TemporaryDirectory(prefix='corkbored-ui-') as data:
        os.environ.update(CORKBORED_DATA=data, YOUSLOP_DATA=data, CORKBORED_TOKEN='off',
                          CORKBORED_BLOCK_POSTERS='off',
                          OPENAI_API_KEY='', ELEVENLABS_API_KEY='')
        try:
            from app import stage
            if not stage.browser():
                raise RuntimeError('Chromium unavailable; browser verification is reviewer-run')
            seed()
            from app import settings
            settings.save_file({'theme': args.theme})
            args.out.mkdir(parents=True, exist_ok=True)
            with server() as base:
                rows, errors = capture(base, args.out, args.theme)
            from app import jobs
            assert not any(j['kind'] == 'block posters' for j in jobs.recent()), 'Snapshots started a poster batch'
            from app import block_library
            assert block_library._PREVIEW_RENDERS == 0, 'Snapshots started a motion/trial render'
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

"""Doctrine-selected frames from small segment proxies, never a full render."""
import json
import math
import hashlib
import io
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import audio, board, channels, check, cuts, ffutil, llm, render, scenes, store, storyboard
from .paths import resource_root
from .schema import FrameSpec
from .store import project_dir


def snapshot_times(story: dict, frame: FrameSpec) -> list[dict]:
    """Select at most 48 picture times; findings and hook beats take priority.

    The optional findings and segment cards use the shapes in app.check.
    Dedupe keeps the most important reason within a quarter second. When
    mandatory samples alone exceed the budget, retain them in time order.
    """
    duration = story['project']['duration']
    if duration <= 0:
        return []
    paragraphs = story['paragraphs']
    candidates = []

    def add(t, why, priority, sid=''):
        if not math.isfinite(t):
            return
        t = round(min(max(0, t), max(0, duration - .001)), 3)
        if not sid:
            sid = next((p['id'] for p in paragraphs if p['start'] <= t < p['end']), '')
        candidates.append((priority, t, why, sid))

    for t in (0., 1.5, 3.):
        if t < duration:
            add(t, 'hook', 0)
    for f in story.get('findings', []):
        if f['level'] in ('P0', 'P1'):
            add(f['t'], 'finding: ' + f['code'], 0, f['slide_id'])
    for t in (duration - 2, duration - 1):
        add(t, 'ending', 1)
    add(duration - 1 / 30, 'last frame', 0)
    for seg in story.get('segments', []):
        for card in seg.get('cards', []):
            add(card['start'] + frame.arrive_s, 'chapter', 1, card['slide_id'])
    for p in paragraphs:
        add(p['start'], 'paragraph start', 1, p['id'])
        add((p['start'] + p['end']) / 2, 'paragraph middle', 3, p['id'])
        for cue in p.get('cues', []):
            add(cue['start'], 'cue', 2, p['id'])
    selected = []
    for priority, t, why, sid in sorted(candidates):
        if all(abs(t - row['t']) >= .25 for row in selected):
            selected.append(dict(t=t, why=why, slide_id=sid))
        if len(selected) == 48:
            break
    return sorted(selected, key=lambda row: row['t'])


def _story(project):
    sb = storyboard.build(project)
    sb['findings'] = check.run(project)['findings']
    # Chapter cards land near the preceding segment's end, during its gap.
    groups = render._groups_for_preview(project)
    pictures = [s for s in sb['segments'] if s['type'] == 'picture']
    gaps = audio.gap_map(project)
    frame = project.frame
    for i, seg in enumerate(pictures[:-1]):
        card = render.chapter_card(project, groups[i+1][0][0])
        if card:
            gap = gaps[groups[i][-1][0].id]
            fmt = project.style.format
            drawn = scenes.handles(fmt) or cuts.is_cut(fmt) or fmt == 'board' or fmt.startswith('custom:')
            if drawn:
                hold = max(.9, min(3.2, gap - .12))
            else:
                hold = max(frame.arrive_s, min(gap, frame.arrive_s + frame.title_hold_base_s +
                           frame.title_hold_per_word_s * len(card[0].split())))
            end = seg['start'] + seg['duration'] + seg['skip']
            start = end - hold
            if not drawn:
                start = max(seg['start'] - seg['skip'] + .2, start)
            seg['cards'] = [dict(start=start, slide_id=groups[i+1][0][0].id)]
    return sb


def _grab(project, t, out, size, segments):
    seg = next((s for s in segments if s['start'] <= t < s['start'] + s['duration']), None)
    if seg is None:
        raise ValueError('Snapshot time is outside the cut')
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not seg['ready']:
            render.proxy_ref(project, seg['ref'], download=False)
            seg['ready'] = True
        proxy = project_dir(project.id) / seg['path']
        local = t - seg['start'] + seg.get('skip', 0)
        ffutil.run(['-ss', f'{local:.3f}', '-i', str(proxy), '-frames:v', '1',
                    '-vf', f'scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease,'
                    f'pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2', str(out)])
        if not out.exists():
            raise ffutil.FFError('Proxy contains no frame at the requested time')
        return out, False
    except (ffutil.FFError, OSError, ValueError):
        if seg['type'] != 'picture' or not (cuts.is_cut(project.style.format) or project.style.format == 'board'):
            raise
        paras = seg['paragraphs']
        para = next((p for p in reversed(paras) if p['start'] <= t), paras[0])
        slide = next(s for s in project.slides if s.id == para['id'])
        at = min(1., max(0., (t - para['start']) / max(.001, para['duration'])))
        channel = channels.load_or_none(project.channel_id)
        if cuts.is_cut(project.style.format):
            cuts.still(project, slide, out, channel=channel, at=at,
                       image_for=lambda s: render._chosen(project, s)[0], cache_dir=out.parent)
        else:
            board.still(project, slide, out, channel=channel, at=at,
                        image=render._chosen(project, slide)[0])
        with Image.open(out) as image:
            resized = ImageOps.pad(image.convert('RGB'), size)
        resized.save(out)
        return out, True


def grab(project, t, out: Path, *, size=(640, 360)) -> Path:
    """Grab at absolute picture time; cut/board stills are approximate fallback."""
    return _grab(project, t, out, size, render.timeline(project)['segments'])[0]


def snapshots(project, out_dir=None) -> list[dict]:
    """Write PNGs and a manifest with project-relative, file-route-safe paths."""
    root = project_dir(project.id)
    out_dir = Path(out_dir) if out_dir is not None else root / 'review'
    out_dir.resolve().relative_to(root.resolve())
    sb = _story(project)
    segments = render.timeline(project)['segments']
    rows = []
    for i, row in enumerate(snapshot_times(sb, project.frame)):
        out = out_dir / 'snaps' / f"{i:02d}_{row['t']:07.2f}.png"
        path, approximate = _grab(project, row['t'], out, (640, 360), segments)
        rows.append(dict(row, path=path.relative_to(root).as_posix()))
        if approximate:
            rows[-1]['why'] += ' (approximate still)'
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / 'snaps.json'
    temporary = manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps({'storyboard_hash': _storyboard_hash(project),
                                     'snaps': rows}, indent=2) + '\n', encoding='utf-8')
    temporary.replace(manifest)
    return rows


def sheet(rows, out, *, cols=4, tile_w=360) -> Path:
    """Tile frames with a mono timecode and reason on a strip under each frame.

    The strip sits below the picture, not over it, so lower-third titles and
    captions stay visible to whoever (or whatever) reviews the sheet.
    Row paths are filesystem paths; manifest consumers resolve against the
    project directory before calling this standalone image helper.
    """
    if not rows or cols < 1 or tile_w < 1:
        raise ValueError('A sheet needs rows, positive columns and tile width')
    tile_h = round(tile_w * 9 / 16)
    cell_h = tile_h + 40
    image = Image.new('RGB', (cols * tile_w, math.ceil(len(rows) / cols) * cell_h), '#181818')
    font = ImageFont.truetype(str(resource_root() / 'resources/fonts/JetBrainsMono-Bold.ttf'), 12)
    draw = ImageDraw.Draw(image)
    for i, row in enumerate(rows):
        with Image.open(row['path']) as source:
            tile = ImageOps.pad(source.convert('RGB'), (tile_w, tile_h))
        x, y = (i % cols) * tile_w, (i // cols) * cell_h
        image.paste(tile, (x, y))
        centis = round(row['t'] * 100)
        minutes, rest = divmod(centis, 6000)
        label = f'{minutes:02d}:{rest // 100:02d}.{rest % 100:02d}'
        why = row['why']
        while why and draw.textlength(why, font=font) > tile_w - 12:
            why = why[:-1]
        draw.text((x + 6, y + tile_h + 3), label, font=font, fill='white')
        draw.text((x + 6, y + tile_h + 20), why, font=font, fill='white')
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


SYSTEM = ('You are a stranger watching this on a phone with the sound off. '
          'Describe each frame in one sentence before judging it. '
          'Return JSON only. Never give scores, ratings, grades or stars.')


def _storyboard_hash(project):
    return hashlib.sha1(json.dumps(storyboard.build(project), sort_keys=True).encode()).hexdigest()


def read_snapshots(pid):
    path = project_dir(pid) / 'review/snaps.json'
    if not path.exists():
        return []
    manifest = json.loads(path.read_text(encoding='utf-8'))
    return manifest.get('snaps', []) if isinstance(manifest, dict) else manifest


def select(snaps, findings, mode='targeted') -> list[dict]:
    """Pick nearest available frames; preserve mandatory frames within the budget."""
    if mode not in ('targeted', 'full'):
        raise ValueError('Review mode must be targeted or full')
    if mode == 'full' or not snaps:
        return [dict(row) for row in snaps]
    chosen = []

    def add(t, why, mandatory=False):
        row = min(snaps, key=lambda r: abs(r['t'] - t))
        near = next((r for r in chosen if abs(r['t'] - row['t']) < .5), None)
        if near is not None:
            near['why'] += '; ' + why
            return
        if mandatory or len(chosen) < 12:
            chosen.append(dict(row, why=why + ' · ' + row['why']))

    # Reserve P0 and hook slots before considering optional P1/chapter slots.
    for f in findings:
        if f['level'] == 'P0':
            add(f['t'], 'P0: ' + f['code'], True)
    for t in (0., 1.5, 3.):
        if t <= max(r['t'] for r in snaps):
            add(t, 'hook', True)
    if len(chosen) > 12:
        raise ValueError('More than 12 mandatory P0/hook frames; use --full (mode=full)')
    add(max(r['t'] for r in snaps), 'last frame')
    for f in findings:
        if f['level'] == 'P1':
            add(f['t'], 'P1: ' + f['code'])
    for row in snaps:
        if 'chapter' in row['why']:
            add(row['t'], 'chapter')
    return sorted(chosen, key=lambda r: r['t'])


def _clock(t):
    centis = round(t * 100)
    return f'{centis // 6000:02d}:{centis % 6000 / 100:05.2f}'


def prompt_for(batch, story_slice, frame):
    captions = '\n'.join(f"Image {i+1}: {_clock(r['t'])} (t={r['t']}, {r['why']})"
                         for i, r in enumerate(batch))
    return (captions + '\nReference each image by its numeric seconds t. '
            'Describe what you see before naming a problem. P0 blocks render; '
            'P1 should fix; P2 is taste. Name the weakest shot. Fix text first, '
            'then timing, then detail. Use only the supplied frame times. '
            'Return {"notes":[{"t":0,"severity":"P0|P1|P2","see":"...",'
            '"problem":"...","fix":{"kind":"text|cue|picture|timing|title|look",'
            '"slide_id":"...","hint":"..."}}],"weakest":{"t":0,"why":"..."}}. '
            'No scores anywhere.\nFrameSpec: ' + json.dumps(frame.to_dict()) +
            '\nStoryboard context (do not assume unseen visuals): ' + json.dumps(story_slice))


def _strip_scores(value):
    if isinstance(value, dict):
        clean = {}
        for k, v in value.items():
            if re.search(r'score|rating|grade|stars|/10', k, re.I):
                logging.getLogger(__name__).warning('Dropped review score key: %s', k)
            else:
                clean[k] = _strip_scores(v)
        return clean
    if isinstance(value, list):
        return [_strip_scores(v) for v in value]
    return value


def _jpeg(root, row):
    path = (root / row['path']).resolve()
    path.relative_to(root.resolve())
    with Image.open(path) as source:
        image = source.convert('RGB')
        if image.width > 640:
            image = image.resize((640, max(1, round(image.height * 640 / image.width))))
        data = io.BytesIO()
        image.save(data, format='JPEG', quality=85)
    return data.getvalue()


def _markdown(result, story, measured):
    rows = result['frames']
    lines = ['## What was looked at',
             f"Mode: {result['mode']}; {len(rows)} frames; "
             f"{result['snapshots_not_sent']} snapshots not sent.",
             ', '.join(f"{_clock(r['t'])} ({r['why']})" for r in rows),
             '', '## Choices made',
             f"Format: {story['project']['format']}; theme: {story['style'].get('theme', '')}."]
    moves = sorted({s['camera'] for s in story['segments'] if s.get('camera')})
    lines += ['Camera ops used: ' + (', '.join(moves) or 'none specified') + '.',
              '', '## Measured', ', '.join(f'{k}: {v}' for k, v in measured['counts'].items()),
              '', '## Looked at']
    for level in ('P0', 'P1', 'P2'):
        lines += ['', '### ' + level]
        notes = [n for n in result['notes'] if n['severity'] == level]
        for n in notes:
            fix = n['fix']
            lines.append(f"- {_clock(n['t'])}: {n['see']} — {n['problem']} "
                         f"Fix ({fix.get('kind', '')}, {fix.get('slide_id', '')}): {fix.get('hint', '')}")
        if not notes:
            lines.append('None.')
    weakest = result['weakest']
    lines += ['', '## Weakest shot',
              f"{_clock(weakest['t'])}: {weakest['why']}" if weakest else 'No frames available.',
              '', '## Warnings kept']
    lines += [json.dumps(n, ensure_ascii=False) for n in result['warnings_kept']] or ['None.']
    return '\n'.join(lines) + '\n'


def run(project, progress=lambda msg: None, *, mode='targeted') -> dict:
    if mode not in ('targeted', 'full'):
        raise ValueError('Review mode must be targeted or full')
    root = project_dir(project.id)
    out = root / 'review'
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / 'snaps.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    fresh = (isinstance(manifest, dict) and
             manifest.get('storyboard_hash') == _storyboard_hash(project) and
             all((root / r['path']).is_file() for r in manifest.get('snaps', [])))
    snaps = manifest['snaps'] if fresh else snapshots(project)
    measured = check.run(project)
    selected = select(snaps, measured['findings'], mode)
    progress(f'Review {mode}: {len(selected)} frames: ' +
             '; '.join(f"{_clock(r['t'])} {r['why']}" for r in selected))
    story = storyboard.build(project)
    notes, weakest = [], None
    size = 16 if mode == 'full' else 12
    for offset in range(0, len(selected), size):
        batch = selected[offset:offset+size]
        context = dict(story, paragraphs=[p for p in story['paragraphs']
                       if any(p['start'] <= r['t'] <= p['end'] for r in batch)])
        reply = _strip_scores(llm.complete_json(
            prompt_for(batch, context, project.frame), system=SYSTEM, model=llm.MODEL_UTILITY,
            images=[_jpeg(root, r) for r in batch],
            require=lambda v: isinstance(v, dict) and isinstance(v.get('notes'), list)))
        times = {r['t'] for r in batch}
        for n in reply['notes']:
            if (isinstance(n, dict) and n.get('severity') in ('P0', 'P1', 'P2') and
                    isinstance(n.get('t'), (int, float)) and n['t'] in times and
                    isinstance(n.get('see'), str) and isinstance(n.get('problem'), str) and
                    isinstance(n.get('fix'), dict)):
                row = next(r for r in batch if r['t'] == n['t'])
                notes.append({k: n[k] for k in ('t', 'severity', 'see', 'problem', 'fix')} |
                             {'path': row['path']})
        candidate = reply.get('weakest')
        if (isinstance(candidate, dict) and isinstance(candidate.get('t'), (int, float))
                and candidate['t'] in times and isinstance(candidate.get('why'), str)):
            weakest = candidate
    p0 = [n for n in notes if n['severity'] == 'P0']
    if p0:
        first = min(p0, key=lambda n: n['t'])
        weakest = dict(t=first['t'], why=first['problem'])
    if selected and weakest is None:
        raise ValueError('Review reply did not name a valid weakest shot')
    previous = out / 'notes.json'
    old = json.loads(previous.read_text()) if previous.exists() else {}
    kept = old.get('warnings_kept', []) + [n for n in old.get('notes', []) if n.get('dismissed')]
    result = dict(mode=mode, frames_sent=len(selected), frames=selected,
                  snapshots_not_sent=len(snaps)-len(selected), notes=notes,
                  weakest=weakest, warnings_kept=kept)
    previous.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    (out / 'REVIEW.md').write_text(_markdown(result, story, measured), encoding='utf-8')
    with store.lock_for(project.id):
        current = store.load(project.id)
        current.review = dict(at=datetime.now(timezone.utc).isoformat(),
                              **{level.lower(): sum(n['severity'] == level for n in notes)
                                 for level in ('P0', 'P1', 'P2')},
                              weakest_t=weakest['t'] if weakest else None, path='review/REVIEW.md')
        store.save(current)
    return result

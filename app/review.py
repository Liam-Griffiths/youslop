"""Doctrine-selected frames from small segment proxies, never a full render."""
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import audio, board, channels, check, cuts, ffutil, render, scenes, storyboard
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
    temporary.write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
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

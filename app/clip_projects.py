"""Clip project foundations. All times are absolute seconds in the original.

Source audio is never a take. Section previews read the original directly;
whole-cut studio integration is tracked in T14.4b.
"""
from copy import deepcopy
import uuid

from . import footage, store, transcripts
from .schema import Project, Slide

ASPECTS = {'16:9': 'landscape', '9:16': 'portrait', '1:1': 'square'}
PRESETS = {'centre': .5, 'left third': 1/3, 'right third': 2/3}


def source(project):
    meta = project.clip
    transcripts.source_range(meta['shoot_id'], meta['source_id'], meta['in_s'], meta['out_s'])
    shoot = footage.load(meta['shoot_id'])
    file = next(s for s in shoot.files if s.id == meta['source_id'])
    return file, footage.source_path(shoot, file)


def ranges(project, start=None, end=None):
    """Kept spans after subtracting the stored, non-destructive edit list."""
    meta = project.clip
    a = max(meta['in_s'], start if start is not None else meta['in_s'])
    b = min(meta['out_s'], end if end is not None else meta['out_s'])
    return list(transcripts._gaps(a, b, meta.get('cuts', []))) if b > a else []


def duration(project):
    return sum(b-a for a, b in ranges(project))


def _paragraphs(project):
    meta = project.clip
    doc = transcripts.load(meta['shoot_id'], meta['source_id'])
    # Keep sentence boundaries, including pauses and ranges without words.
    edges = [meta['in_s']] + [s['start'] for s in doc['segments']
                             if meta['in_s'] < s['start'] < meta['out_s']] + [meta['out_s']]
    slides = []
    for a, b in zip(sorted(set(edges)), sorted(set(edges))[1:]):
        if not ranges(project, a, b):
            continue
        old = next((s for s in project.slides if s.candidates and
                    s.candidates[0]['in_s'] < b and s.candidates[0]['out_s'] > a), None)
        slide = deepcopy(old) if old else Slide()
        slide.narration = ' '.join(w['w'] for w in doc['words'] if a <= w['start'] < b
                                  and any(x <= w['start'] < y for x, y in ranges(project, a, b)))
        slide.chosen_id = 'source'
        slide.kind, slide.prefer_kind, slide.picture_mode = 'kenburns', 'video', 'new'
        slide.gap_override = 0
        slide.candidates = [dict(id='source', provider='footage', kind='video',
            shoot_id=meta['shoot_id'], clip_id=meta.get('clip_id', ''),
            source_id=meta['source_id'], in_s=a, out_s=b)]
        slides.append(slide)
    project.slides = slides


def create(shoot_id, clip_id, payload):
    if payload.keys() - {'aspect', 'full_url', 'channel_id'}:
        raise ValueError('Unknown clip project field')
    shoot = footage.load(shoot_id)
    clip = next((c for c in shoot.clips if c.id == clip_id), None)
    if clip is None:
        raise FileNotFoundError('Unknown clip')
    aspect = payload.get('aspect', '9:16')
    if aspect not in ASPECTS:
        raise ValueError('Use 16:9, 9:16 or 1:1')
    if any(not isinstance(payload.get(k, ''), str) for k in ('full_url', 'channel_id')):
        raise ValueError('Channel and full URL must be text')
    transcripts.source_range(shoot_id, clip.file, clip.in_s, clip.out_s)
    project = Project('p' + uuid.uuid4().hex[:8], clip.title, title=clip.title,
        kind='clip', aspect=ASPECTS[aspect], channel_id=payload.get('channel_id', ''),
        use_intro=False, use_outro=False,
        clip=dict(shoot_id=shoot_id, source_id=clip.file, clip_id=clip.id,
                  in_s=clip.in_s, out_s=clip.out_s,
                  aspect=aspect, full_url=payload.get('full_url', ''), hook=clip.hook,
                  cuts=[], reframes={}))
    project.style.picture_every = 1
    _paragraphs(project)
    return store.save(project)


def update(project, payload):
    """Validate before mutation; word trims require covered transcript words."""
    if project.kind != 'clip':
        raise ValueError('Not a clip project')
    if payload.keys() - {'in_s', 'out_s', 'cuts', 'reframes'}:
        raise ValueError('Unknown clip edit field')
    candidate = deepcopy(project)
    meta = candidate.clip
    sid, fid = meta['shoot_id'], meta['source_id']
    a, b = transcripts.source_range(sid, fid, payload.get('in_s', meta['in_s']),
                                     payload.get('out_s', meta['out_s']))
    doc = transcripts.load(sid, fid)
    starts, ends = {w['start'] for w in doc['words']}, {w['end'] for w in doc['words']}
    def word_range(x, y):
        if x not in starts or y not in ends or list(transcripts._gaps(x, y, doc['coverage'])):
            raise ValueError('Select a covered word range')
    if 'in_s' in payload or 'out_s' in payload:
        word_range(a, b)
    cuts = payload.get('cuts', meta['cuts'])
    if not isinstance(cuts, list) or len(cuts) > 100:
        raise ValueError('Use at most 100 cut ranges')
    clean = []
    for span in cuts:
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ValueError('Cut needs start and end')
        x, y = transcripts.source_range(sid, fid, *span)
        if 'cuts' in payload:
            word_range(x, y)
        clean.append([x, y])
    reframes = payload.get('reframes', meta['reframes'])
    if not isinstance(reframes, dict) or any(k not in {s.id for s in project.slides} or
            v not in PRESETS for k, v in reframes.items()):
        raise ValueError('Reframes map paragraph ids to centre, left third or right third')
    meta.update(in_s=a, out_s=b, cuts=transcripts._ranges(clean), reframes=deepcopy(reframes))
    if duration(candidate) <= 0:
        raise ValueError('Keep at least one word range')
    _paragraphs(candidate)
    meta['reframes'] = {k: v for k, v in meta['reframes'].items() if candidate.slide(k)}
    return candidate


def section_graph(project, slide_id):
    """Quarter-size source picture and audio, without legacy narration padding."""
    from . import render
    slide = project.slide(slide_id)
    if slide is None:
        raise ValueError('That paragraph is not in the clip')
    file, path = source(project)
    if file.kind != 'video' or not file.audio:
        raise ValueError('Section preview currently needs video with audio')
    span = slide.candidates[0]
    kept = ranges(project, span['in_s'], span['out_s'])
    if not kept:
        raise ValueError('That paragraph has no remaining source range')
    w, h = render.preview_size(project)
    fps, fade = render.PREVIEW_FPS, 2/render.FPS
    point = PRESETS[project.clip['reframes'].get(slide_id, 'centre')]
    crop, _ = render._cover_crop(path, w, h, [point, .5])
    graph = []
    for i, (a, b) in enumerate(kept):
        graph += [f'[0:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS,'
                  f'{crop},fps={fps},format=yuv420p[v{i}]',
                  f'[0:a]atrim=start={a:.6f}:end={b+(fade if i < len(kept)-1 else 0):.6f},'
                  f'asetpts=PTS-STARTPTS,aresample=48000,'
                  f'apad=whole_dur={b-a+(fade if i < len(kept)-1 else 0):.6f}[a{i}]']
    graph.append(''.join(f'[v{i}]' for i in range(len(kept))) + f'concat=n={len(kept)}:v=1:a=0[vout]')
    last = '[a0]'
    for i in range(1, len(kept)):
        tag = f'[ac{i}]'
        graph.append(f'{last}[a{i}]acrossfade=d={fade:.6f}:c1=tri:c2=tri{tag}')
        last = tag
    graph.append(f'{last}loudnorm=I=-14:TP=-1:LRA=11[aout]')
    return ['-i', str(path)], ';'.join(graph), sum(b-a for a, b in kept)


def preview_section(project, slide_id, progress=lambda m: None):
    from . import block_overlays, render
    inputs, graph, seconds = section_graph(project, slide_id)
    root = store.project_dir(project.id) / 'cache'
    root.mkdir(exist_ok=True)
    # One file per paragraph, replaced on each press, so previews don't pile up.
    out = root / f'clip-section-{slide_id}.mp4'
    pending = root / f'clip-section-{slide_id}-{uuid.uuid4().hex[:8]}.part.mp4'
    script = pending.with_suffix('.ffgraph')
    script.write_text(graph)
    progress('Previewing the original range at quarter size')
    try:
        block_overlays.run_graph([*inputs, '-filter_complex_script', str(script),
            '-map', '[vout]', '-map', '[aout]', '-t', f'{seconds:.6f}',
            '-r', str(render.PREVIEW_FPS), '-c:v', 'libx264', '-crf', str(render.PREVIEW_CRF),
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(pending)])
        pending.replace(out)
    finally:
        script.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
    return dict(path=f'cache/{out.name}', seconds=seconds,
                rendered_at=round(out.stat().st_mtime))

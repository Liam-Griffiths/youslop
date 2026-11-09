"""Source-linked clip playback. No narration takes, padding or picture overlaps."""
import hashlib
import json
import uuid

from . import clip_projects as clips, render, store, transcripts


def spans(project, slide=None):
    slides = [slide] if slide else project.slides
    return [(s, a, b) for s in slides for a, b in clips.ranges(
        project, s.candidates[0]['in_s'], s.candidates[0]['out_s'])]


def graph(project, slide=None, *, size=None, fps=None, sound_only=False, hide=frozenset()):
    if any(s.overlays for s in project.slides):
        raise ValueError('Clip graphics require T14.4c')
    file, path = clips.source(project)
    kept = spans(project, slide)
    if not kept:
        raise ValueError('No remaining source range')
    w, h = size or render.preview_size(project)
    fps = fps or render.PREVIEW_FPS
    inputs, parts = ['-i', str(path)], []
    for i, (s, a, b) in enumerate(kept):
        # Outgoing source handles overlap incoming audio without shortening the cut.
        # Bound fades for tiny kept spans; pad only a handle that reaches EOF.
        fade = min(2/render.FPS, b-a, kept[i+1][2]-kept[i+1][1]) if i+1 < len(kept) else 0
        if not sound_only:
            if file.kind == 'video':
                point = clips.PRESETS[project.clip['reframes'].get(s.id, 'centre')]
                crop, _ = render._cover_crop(path, w, h, [point, .5])
                parts.append(f'[0:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS,'
                             f'{crop},fps={fps},format=yuv420p[v{i}]')
            else:
                parts.append(f'color=c=black:s={w}x{h}:r={fps}:d={b-a:.6f}[v{i}]')
        if file.audio or file.kind == 'audio':
            parts.append(f'[0:a]atrim=start={a:.6f}:end={min(file.duration,b+fade):.6f},'
                         f'asetpts=PTS-STARTPTS,aresample=48000,'
                         f'aformat=channel_layouts=stereo,apad=whole_dur={b-a+fade:.6f},'
                         f'atrim=duration={b-a+fade:.6f}[a{i}]')
        else:
            parts.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={b-a+fade:.6f}[a{i}]')
    if not sound_only:
        parts.append(''.join(f'[v{i}]' for i in range(len(kept))) + f'concat=n={len(kept)}:v=1:a=0[vout]')
    last = '[a0]'
    for i in range(1, len(kept)):
        fade = min(2/render.FPS, kept[i-1][2]-kept[i-1][1], kept[i][2]-kept[i][1])
        parts.append(f'{last}[a{i}]acrossfade=d={fade:.6f}:c1=tri:c2=tri[ac{i}]')
        last = f'[ac{i}]'
    seconds = sum(b-a for _, a, b in kept)
    music = None if 'music' in hide else render.pick_music(project)
    if music:
        inputs += ['-stream_loop', '-1', '-i', str(music)]
    voice = f'loudnorm=I={project.voice.target_lufs}:TP=-1.5:LRA=11' if music else 'anull'
    parts.append(f'{last}{voice}[clipvoice]')
    parts.append(render._audio_graph(project, 0, seconds, bool(music)).replace('[0:a]', '[clipvoice]', 1))
    return inputs, ';'.join(parts), seconds


def key(project, hide=frozenset()):
    file, path = clips.source(project)
    from .scenes import context_base
    music = render.pick_music(project)
    data = [3, project.clip, [(s.id, s.candidates) for s in project.slides],
            str(path), render._stat(path), file.kind, file.audio, render.frame_size(project),
            context_base(project), project.style.music_db, project.voice.target_lufs,
            project.frame.voice_lufs, str(music), render._stat(music), sorted(hide)]
    return hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()[:16]


def state(project, name, hide=frozenset()):
    root = store.project_dir(project.id)/'cache'
    out = root/f'clip-{name}.mp4'
    saved = out.with_suffix('.key')
    have = out.exists() and out.stat().st_size > 0
    ready = have and saved.exists() and saved.read_text() == key(project, hide)
    return dict(path=f'cache/{out.name}', have=have, ready=ready,
                stamp=out.stat().st_mtime_ns if have else 0)


def encode(project, name, progress, *, slide=None, full=False, sound_only=False, hide=frozenset()):
    from .block_overlays import run_graph
    inputs, filters, seconds = graph(project, slide, size=render.frame_size(project) if full else None,
                                     fps=render.FPS if full else None, sound_only=sound_only, hide=hide)
    root = store.project_dir(project.id)/('out' if full else 'cache')
    root.mkdir(exist_ok=True)
    out = root/f'clip-{name}.mp4'
    pending = root/f'clip-{name}-{uuid.uuid4().hex[:8]}.part.mp4'
    script = pending.with_suffix('.ffgraph')
    cache_key = key(project, hide)
    script.write_text(filters)
    progress('Encoding original clip ranges')
    try:
        args = [*inputs, '-filter_complex_script', str(script)]
        if not sound_only:
            args += ['-map', '[vout]', '-c:v', 'libx264', '-crf', str(19 if full else render.PREVIEW_CRF), '-pix_fmt', 'yuv420p']
        run_graph([*args, '-map', '[aout]', '-c:a', 'aac', '-ar', '48000',
                   '-t', f'{seconds:.6f}', '-movflags', '+faststart', str(pending)])
        pending.replace(out)
        if not full:
            out.with_suffix('.key').write_text(cache_key)
    finally:
        script.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
    return dict(path=f'{root.name}/{out.name}', seconds=seconds, rendered_at=out.stat().st_mtime_ns)


def proxy(project, index, progress, hide=frozenset()):
    if not 0 <= index < len(project.slides):
        raise ValueError('That picture is not in the cut')
    slide = project.slides[index]
    name = f'section-{slide.id}'
    cached = state(project, name, hide)
    if cached['ready']:
        return dict(cached, seconds=sum(b-a for _, a, b in spans(project, slide)), rendered_at=cached['stamp'])
    return encode(project, name, progress, slide=slide, hide=hide)


def mix(project, progress=None, hide=frozenset()):
    cached = state(project, 'mix', hide)
    file, _ = clips.source(project)
    music = None if 'music' in hide else render.pick_music(project)
    cached.update(audible=bool(file.audio or file.kind == 'audio' or music), music=music.name if music else '', sting=False, stings=[])
    if progress is not None and cached['audible'] and not cached['ready']:
        encode(project, 'mix', progress, sound_only=True, hide=hide)
        return mix(project, hide=hide)
    return cached


def timeline(project, hide=frozenset()):
    doc = transcripts.load(project.clip['shoot_id'], project.clip['source_id'])
    segments, t = [], 0.
    for i, slide in enumerate(project.slides):
        start, words = t, []
        for _, a, b in spans(project, slide):
            words += [dict(word, start=t+max(a, word['start'])-a, end=t+min(b, word['end'])-a)
                      for word in doc['words'] if a < word['end'] and word['start'] < b]
            t += b-a
        para = dict(id=slide.id, index=i, start=start, duration=t-start, text=slide.narration,
                    title='', chapter='', words=len(words), word_times=words, spoken=t-start,
                    timing={'gap': {'value': 0, 'src': 'user'}}, effective_cues=[],
                    recorded=True, section=slide.section, on_camera=False)
        segments.append(dict(ref=str(i), index=i, n=i+1, group=i, type='picture', lead=slide.id,
            start=start, duration=t-start, skip=0, kind='video', problems=[], paragraphs=[para],
            estimated=False, **state(project, f'section-{slide.id}', hide)))
    w, h = render.preview_size(project)
    return dict(segments=segments, total=t, fps=render.PREVIEW_FPS, width=w, height=h,
        format='kenburns', title_exit=0, last_line_min_s=0, camera_clip=False, estimated=False,
        layers={k: [] for k in ('graphics','sponsors','titles','cues','chapters','music','stings','notes')},
        mix=mix(project, hide=hide), sponsor_suggestions=[])


def full_render(project, progress, preview):
    result = encode(project, 'preview' if preview else 'final', progress, full=not preview)
    out = store.project_dir(project.id)/result['path']
    from .stages import render_signature
    project.render = dict(output=result['path'], duration=result['seconds'], size_mb=round(out.stat().st_size/1e6, 1),
        slides=len(project.slides), pictures=len(project.slides), preview=preview,
        stage_signature=render_signature(project))
    if not preview:
        project.status = 'rendered'
    return project.render

"""Explicit recorded-take retiming. Only word metadata is saved."""
from copy import deepcopy
import math
import tempfile
from pathlib import Path

from . import ffutil, jobs, store, stt
from .stt.seams import clip, join
from .stt.timing import segment_words


def snapshot(pid, sid, track, expected_path):
    project = store.load(pid)
    slide = project.slide(sid)
    if slide is None:
        raise FileNotFoundError('No paragraph')
    take = slide.takes.get(track)
    if not take or take.get('synthetic') or track not in ('mic', 'camera'):
        raise ValueError('Choose a recorded microphone or camera take')
    if take.get('path') != expected_path:
        raise ValueError('Take changed; refresh Voice before retiming')
    root = store.project_dir(pid).resolve()
    path = (root / take['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Recording is unavailable')
    stat = path.stat()
    # Include words to reject concurrent corrections and retiming, not just replacements.
    identity = deepcopy([take, slide.narration, slide.on_camera, project.voice_track,
                         stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
    return path, identity


def retime(pid, sid, track, expected_path, identity, options, progress):
    with store.lock_for(pid):
        path, current = snapshot(pid, sid, track, expected_path)
        if current != identity:
            raise ValueError('Take changed before retiming started')
    with tempfile.TemporaryDirectory(prefix='corkbored-retime-') as temporary:
        wav = Path(temporary) / 'speech.wav'
        progress('Preparing recorded speech')
        ffutil.run(['-i', str(path), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)])
        duration = ffutil.duration(wav)
        result = []
        for start in range(0, math.ceil(duration), 600):
            if start >= duration:
                break
            end = min(start + 600, duration)
            progress('Retiming recorded speech')
            items = []
            for segment in stt.transcribe(path=wav, start=start, end=end, context=True, progress=progress,
                                           cancel=lambda: progress('Retiming recorded speech'), **options):
                for w in segment_words(segment, wav):
                    if w['end'] > w['start']:
                        items.append({**w, 'engine': options['engine'], 'model': options['model']})
            result = join(result, items, start) if result else items
        result = clip(result, 0, duration)
        if not result or any(w['src'] != 'stt' for w in result):
            raise ValueError('Engine returned no real word timings; existing timings kept')
    progress('Saving word timings')  # Cancellation cannot leave partially applied words.
    with store.lock_for(pid):
        _, current = snapshot(pid, sid, track, expected_path)
        if current != identity:
            raise ValueError('Take changed during retiming; existing timings kept')
        project = store.load(pid)
        slide = project.slide(sid)
        slide.takes[track]['words'] = sorted(result, key=lambda w: w['start'])
        store.save(project)
    return {'words': len(result)}


def start_job(pid, sid, track, expected_path, options):
    with store.lock_for(pid):
        _, identity = snapshot(pid, sid, track, expected_path)
        return jobs.start('retime', pid, lambda progress: retime(
            pid, sid, track, expected_path, identity, options, progress), cancellable=True)

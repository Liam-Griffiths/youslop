"""Shoot-owned transcripts: atomic chunks, range replacement and persistent edits."""
import hashlib
import json
import math
import threading
import time
import uuid
from pathlib import Path

from . import ffutil, footage, jobs, stt, words

_WORKERS = {}
_WORKERS_LOCK = threading.Lock()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def _path(shoot_id, source_id):
    return footage.shoot_dir(shoot_id) / 'transcripts' / (footage._key(source_id) + '.json')


def load(shoot_id, source_id):
    path = _path(shoot_id, source_id)
    defaults = dict(coverage=[], words=[], segments=[], overrides=[])
    return {**defaults, **json.loads(path.read_text())} if path.exists() else defaults


def _ranges(ranges):
    merged = []
    for a, b in sorted(ranges):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    return merged


def _gaps(a, b, coverage):
    for x, y in _ranges(coverage):
        if x > a:
            yield a, min(x, b)
        a = max(a, y)
        if a >= b:
            return
    if a < b:
        yield a, b


def _rebuild(doc):
    for w in doc['words']:
        for edit in doc['overrides']:
            if edit['start'] <= (w['start'] + w['end']) / 2 < edit['end']:
                w['w'] = edit['w']
    segments = []
    for w in doc['words']:
        if not segments or segments[-1]['text'].rstrip().endswith(('.', '?', '!')) or w['start'] - segments[-1]['end'] > 1:
            segments.append(dict(start=w['start'], end=w['end'], text=w['w']))
        else:
            segments[-1]['end'] = w['end']
            segments[-1]['text'] += ' ' + w['w']
    doc['segments'] = segments


def override(shoot_id, source_id, start, end, text):
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end and text.strip()):
        raise ValueError('Require a finite word span and nonempty text')
    with footage.lock_for(shoot_id):
        doc = load(shoot_id, source_id)
        if not any(w['start'] == start and w['end'] == end for w in doc['words']):
            raise ValueError('Select one existing word to correct')
        doc['overrides'].append(dict(start=start, end=end, w=text.strip()))
        _rebuild(doc)
        _write(_path(shoot_id, source_id), doc)


def _model_identity(model):
    """Track local files, including in-place edits and directory/symlink targets."""
    path = Path(model).expanduser()
    files = sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path]
    return [[str(p.resolve()), s.st_size, s.st_mtime_ns, s.st_ctime_ns]
            for p in files if p.exists() for s in [p.stat()]]


def _run_plan(root, source_id, signature, chunks, replacement):
    if not replacement:
        return None, dict(chunks=chunks, generation='')
    path = root / f'{footage._key(source_id)}.run.json'
    old = json.loads(path.read_text()) if path.exists() else {}
    if old.get('signature') == signature and not old.get('complete'):
        return path, old
    plan = dict(signature=signature, chunks=chunks, complete=False,
                generation=uuid.uuid4().hex)
    _write(path, plan)
    return path, plan


def transcribe(shoot_id, source_id, *, engine, model, language=None, start=None, end=None,
               retranscribe=False, executable='', device=None, progress=lambda message: None):
    """Synchronous worker for CLI or jobs.start; never mutates a source/take."""
    with _WORKERS_LOCK:
        lock = _WORKERS.setdefault((shoot_id, source_id), threading.Lock())
    with lock:
        shoot = footage.load(shoot_id)
        source = next(s for s in shoot.files if s.id == source_id)
        original = footage.source_path(shoot, source)
        stat = original.stat()
        duration = source.duration or ffutil.duration(original)
        a, b = 0 if start is None else start, duration if end is None else end
        if not all(math.isfinite(x) for x in (a, b, duration)) or not 0 <= a < b <= duration:
            raise ValueError('Require 0 <= start < end <= source duration')
        root = _path(shoot_id, source_id).parent
        root.mkdir(parents=True, exist_ok=True)
        identity = [str(original), stat.st_size, stat.st_mtime_ns]
        doc = load(shoot_id, source_id)
        if doc.get('source_identity', identity) != identity:
            raise ValueError('Source changed; restore the original before resuming its transcript')
        audio_key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
        wav = root / f'{footage._key(source_id)}-{audio_key}.wav'
        progress('Preparing speech audio')
        if not wav.exists():
            temporary = wav.with_suffix('.part.wav')
            ffutil.run(['-i', str(original), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(temporary)])
            temporary.replace(wav)
        ranges = [(a, b)] if retranscribe or start is not None or end is not None else list(_gaps(a, b, doc['coverage']))
        chunks = [(x, min(x + 600, stop)) for begin, stop in ranges
                  for x in (begin + i * 600 for i in range(math.ceil((stop - begin) / 600)))]
        adapter_options = {'executable': executable} if engine == 'whisper.cpp' else {}
        if engine == 'faster-whisper' and device is not None:
            adapter_options['device'] = device
        signature = [identity, engine, model, _model_identity(model), language, adapter_options, a, b, retranscribe]
        plan_path, plan = _run_plan(root, source_id, signature, chunks, retranscribe)
        chunks = plan['chunks']
        elapsed, decoded = 0, 0
        for n, (x, y) in enumerate(chunks, 1):
            progress(f'chunk {n} of {len(chunks)}, about {round(elapsed / decoded * sum(v-u for u,v in chunks[n-1:]) / 60, 1) if decoded else "unknown"} min left')
            key = hashlib.sha256(json.dumps([signature[:6], plan['generation'], x, y]).encode()).hexdigest()[:20]
            cache = root / f'{footage._key(source_id)}.chunks' / f'{key}.json'
            began = time.monotonic()
            cached = cache.exists()
            if cached:
                items = json.loads(cache.read_text())
            else:
                items = []
                for segment in stt.transcribe(engine, wav, model=model, language=language, start=x, end=y,
                                               progress=progress, cancel=lambda: progress('Transcribing speech'), **adapter_options):
                    raw = segment.get('words') or words.spread(segment['text'].split(), [(segment['start'], segment['end'])])
                    for w in raw:
                        mid = (w['start'] + w['end']) / 2
                        if x <= mid < y and w['end'] > w['start']:
                            items.append({**w, 'start': max(x, w['start']), 'end': min(y, w['end']),
                                          'src': 'stt' if segment.get('words') else 'stt-seg',
                                          'p': w.get('p'), 'engine': engine, 'model': model})
                _write(cache, items)
            # Persist before the next cancellation checkpoint; crash after cache is recoverable.
            with footage.lock_for(shoot_id):
                doc = load(shoot_id, source_id)
                doc['words'] = sorted([w for w in doc['words'] if not x <= (w['start'] + w['end']) / 2 < y] + items,
                                      key=lambda w: w['start'])
                doc['coverage'] = _ranges(doc['coverage'] + [[x, y]])
                doc.update(engine=engine, model=model, language=language, duration=duration,
                           created=doc.get('created', time.time()), source_identity=identity)
                if not cached:
                    measured = dict(signature=signature[1:6], audio_seconds=y-x,
                                    wall_seconds=time.monotonic()-began)
                    doc['measurement'] = measured
                _rebuild(doc)
                _write(_path(shoot_id, source_id), doc)
            if not cached:
                elapsed += time.monotonic() - began
                decoded += y - x
        if plan_path is not None:
            plan['complete'] = True
            _write(plan_path, plan)
        progress('Transcript saved')
        return load(shoot_id, source_id)


def start_job(shoot_id, source_id, **options):
    return jobs.start('transcribe', shoot_id,
                      lambda progress: transcribe(shoot_id, source_id, progress=progress, **options), cancellable=True)


def source_range(shoot_id, source_id, start=None, end=None):
    shoot = footage.load(shoot_id)
    source = next((s for s in shoot.files if s.id == source_id), None)
    if source is None:
        raise FileNotFoundError('Unknown source')
    original = footage.source_path(shoot, source)
    if not original.is_file():
        raise FileNotFoundError('Source unavailable')
    a, b = 0 if start is None else start, source.duration if end is None else end
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (a, b))
            or not 0 <= a < b <= source.duration):
        raise ValueError('Require 0 <= start < end <= source duration; process the source first')
    return a, b


def prepare(shoot_id, source_id, options):
    """Validate synchronously before any job is created; no inference or downloads."""
    a, b = source_range(shoot_id, source_id, options.get('start'), options.get('end'))
    resolved = stt.resolve(options)
    ranges = ([(a, b)] if options.get('retranscribe') or options.get('start') is not None
              or options.get('end') is not None else list(_gaps(a, b, load(shoot_id, source_id)['coverage'])))
    signature = [resolved['engine'], resolved['model'], _model_identity(resolved['model']),
                 resolved.get('language'),
                 ({'executable': resolved.get('executable', '')} if resolved['engine'] == 'whisper.cpp'
                  else {'device': resolved['device']} if 'device' in resolved else {})]
    root = _path(shoot_id, source_id).parent
    plan_path = root / f'{footage._key(source_id)}.run.json'
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else {}
    full_signature = plan.get('signature', [])
    if (options.get('retranscribe') and not plan.get('complete') and len(full_signature) == 9
            and full_signature[1:6] == signature and full_signature[6:] == [a, b, True]):
        ranges = [span for span in plan['chunks'] if not (root / f'{footage._key(source_id)}.chunks' /
                  (hashlib.sha256(json.dumps([full_signature[:6], plan['generation'], *span]).encode()).hexdigest()[:20] + '.json')).exists()]
    seconds = sum(y - x for x, y in ranges)
    measurement = load(shoot_id, source_id).get('measurement', {})
    runtime = (seconds * measurement['wall_seconds'] / measurement['audio_seconds']
               if measurement.get('signature') == signature and measurement.get('audio_seconds', 0) > 0 else None)
    return resolved, dict(seconds=seconds, chunks=sum(math.ceil((y-x)/600) for x, y in ranges),
                         runtime_seconds=runtime,
                         detail=('Approximate runtime from the last measured chunk; content and load vary'
                                 if runtime is not None else
                                 'Runtime depends on engine, model and device; no measured estimate yet'),
                         engine=resolved['engine'], model=resolved['model'])

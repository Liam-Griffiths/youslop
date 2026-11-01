"""Camera shoots: read-only sources and resumable, app-owned viewing media."""
from __future__ import annotations

import json
import math
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable

from PIL import Image

from . import ffutil, jobs
from .config import DATA

FOOTAGE_DIR = DATA / 'footage'
_VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi', '.mts', '.m2ts', '.mxf'}
_PROCESS_LOCK = threading.Lock()  # One source at a time, even across background jobs.
Progress = Callable[[str], None]


@dataclass
class SourceFile:
    id: str
    source_path: str = ''              # Original location, retained even for copies.
    filename: str = ''                 # App-owned copy relative to the shoot.
    size: int = 0
    mtime_ns: int = 0
    duration: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    rotation: float = 0.0
    creation_time: str = ''
    gps: str = ''                      # Original ISO6709 tag, without precision loss.
    audio: list[dict] = field(default_factory=list)
    error: str = ''

    @classmethod
    def from_dict(cls, raw: dict) -> SourceFile:
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


@dataclass
class Shoot:
    id: str
    path: str = ''
    copied: bool = False
    added_at: float = 0.0
    files: list[SourceFile] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> Shoot:
        values = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__ and k != 'files'}
        return cls(**values, files=[SourceFile.from_dict(f) for f in raw.get('files', [])])


def _key(value: str) -> str:
    if not value or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789' for c in value):
        raise ValueError('Invalid footage id')
    return value


def shoot_dir(shoot_id: str) -> Path:
    return FOOTAGE_DIR / _key(shoot_id)


def load(shoot_id: str) -> Shoot:
    return Shoot.from_dict(json.loads((shoot_dir(shoot_id) / 'shoot.json').read_text()))


def _save(shoot: Shoot) -> None:
    root = shoot_dir(shoot.id)
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / 'shoot.json.tmp'
    temporary.write_text(json.dumps(shoot.to_dict(), indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(root / 'shoot.json')


def list_shoots() -> list[Shoot]:
    if not FOOTAGE_DIR.exists():
        return []
    return sorted((load(p.parent.name) for p in FOOTAGE_DIR.glob('*/shoot.json')),
                  key=lambda s: s.added_at, reverse=True)


def _probe(source: SourceFile, path: Path) -> None:
    info = ffutil.probe(path)
    streams = info.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'
                  and not s.get('disposition', {}).get('attached_pic')), None)
    if video is None:
        raise ValueError(f'No video stream: {path}')
    fmt = info.get('format', {})
    tags = {k.lower(): v for k, v in {**fmt.get('tags', {}), **video.get('tags', {})}.items()}
    stat = path.stat()
    source.size, source.mtime_ns = stat.st_size, stat.st_mtime_ns
    source.duration = float(fmt.get('duration') or video.get('duration') or 0)
    try:
        source.fps = float(Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate') or '0'))
    except (ValueError, ZeroDivisionError):
        source.fps = 0.0
    source.width, source.height = int(video.get('width', 0)), int(video.get('height', 0))
    source.rotation = float(tags.get('rotate') or 0)
    for side in video.get('side_data_list', []):
        if 'rotation' in side:
            source.rotation = float(side['rotation'])
    source.creation_time = tags.get('creation_time', '')
    source.gps = tags.get('com.apple.quicktime.location.iso6709') or tags.get('location', '')
    source.audio = [{k: s[k] for k in ('codec_name', 'sample_rate', 'channels', 'channel_layout') if k in s}
                    for s in streams if s.get('codec_type') == 'audio']


def source_path(shoot: Shoot, source: SourceFile) -> Path:
    return shoot_dir(shoot.id) / source.filename if source.filename else Path(source.source_path)


def import_shoot(path: str | Path, *, copy: bool = False,
                 progress: Progress = lambda m: None) -> Shoot:
    """Register a folder (recursively) or file. Reimport resumes the same shoot."""
    path = Path(path).expanduser().resolve(strict=True)
    # A source containing our output tree could otherwise ingest its own proxies.
    output_root = FOOTAGE_DIR.resolve()
    if path == output_root or path in output_root.parents or output_root in path.parents:
        raise ValueError('Import a source folder outside the footage output tree')
    with _PROCESS_LOCK:
        existing = next((s for s in list_shoots() if s.path == str(path) and s.copied == copy), None)
        if existing:
            return existing
        paths = sorted(p for p in (path.rglob('*') if path.is_dir() else [path])
                       if p.is_file() and p.suffix.lower() in _VIDEO_EXT)
        if not paths:
            raise ValueError(f'No camera files found: {path}')
        shoot = Shoot('s' + uuid.uuid4().hex[:12], str(path), copy, time.time())
        # Save the complete inventory first, so a failed probe/copy can be resumed.
        shoot.files = [SourceFile('f' + uuid.uuid4().hex[:12], str(p)) for p in paths]
        _save(shoot)
        progress(f'Imported {len(paths)} source file(s): {shoot.id}')
        return shoot


def _proxy(src: Path, out: Path) -> None:
    for gpu in (True, False):
        pre, tail, codec = ffutil.h264(out, crf=25, gpu=gpu)
        # Fit landscape and portrait footage inside 854x480; never upscale.
        vf = "scale=w='min(854,iw)':h='min(480,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1"
        try:
            ffutil.run([*pre, '-i', str(src), '-map', '0:V:0', '-map', '0:a:0?',
                        '-vf', vf + (',' + tail if tail else ''), *codec,
                        '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(out)])
            return
        except ffutil.FFError as exc:
            if not gpu or codec[1] == 'libx264':
                raise
            ffutil.gpu_failed(str(exc))


def _outputs(shoot: Shoot, source: SourceFile) -> tuple[Path, Path]:
    root = shoot_dir(shoot.id)
    key = _key(source.id)
    return root / 'proxies' / f'{key}.mp4', root / 'sprites' / f'{key}.jpg'


def _complete(path: Path) -> bool:
    # Only final names count: ffmpeg always writes a separate temporary file.
    return path.is_file() and path.stat().st_size > 0


def status(shoot_id: str) -> dict:
    shoot = load(shoot_id)
    files = []
    for source in shoot.files:
        proxy, sprite = _outputs(shoot, source)
        files.append({**asdict(source), 'proxy': str(proxy), 'sprite': str(sprite),
                      'ready': _complete(proxy) and _complete(sprite)})
    return {'id': shoot.id, 'path': shoot.path, 'copied': shoot.copied,
            'total': len(files), 'ready': sum(f['ready'] for f in files), 'files': files}


def process_shoot(shoot_id: str, progress: Progress = lambda m: None) -> dict:
    """Synchronous worker; completed outputs survive failures and process exits."""
    with _PROCESS_LOCK:
        shoot = load(shoot_id)
        failures = []
        for i, source in enumerate(shoot.files, 1):
            progress(f'{i}/{len(shoot.files)}: {Path(source.source_path).name}')
            proxy, sprite = _outputs(shoot, source)
            try:
                src = source_path(shoot, source)
                if not source.duration:
                    _probe(source, src)
                    _save(shoot)
                if shoot.copied and not source.filename:
                    dest = shoot_dir(shoot.id) / 'originals' / (source.id + src.suffix.lower())
                    dest.parent.mkdir(exist_ok=True)
                    temporary = dest.with_suffix('.part' + dest.suffix)
                    shutil.copy2(src, temporary)
                    temporary.replace(dest)
                    source.filename = str(dest.relative_to(shoot_dir(shoot.id)))
                    _save(shoot)
                    src = dest
                for out in (proxy, sprite):
                    out.parent.mkdir(exist_ok=True)
                if not _complete(proxy):
                    temporary = proxy.with_suffix('.part.mp4')
                    _proxy(src, temporary)
                    temporary.replace(proxy)
                if not _complete(sprite):
                    temporary = sprite.with_suffix('.part.jpg')
                    frames = max(1, math.ceil(source.duration / 2))
                    rows = math.ceil(frames / 10)
                    ffutil.run(['-i', str(proxy), '-vf',
                                f'fps=1/2:start_time=0:round=up,scale=160:90:force_original_aspect_ratio=decrease,'
                                f'pad=160:90:(ow-iw)/2:(oh-ih)/2,tile=10x{rows}:nb_frames={frames}',
                                '-frames:v', '1', '-update', '1', str(temporary)])
                    # Catch an empty sprite (e.g. an unreadable/empty video).
                    with Image.open(temporary) as img:
                        img.verify()
                    temporary.replace(sprite)
                source.error = ''
            except (OSError, ValueError, ffutil.FFError) as exc:
                source.error = str(exc)
                failures.append(source.id)
                progress(f'Failed: {source.error}')
            _save(shoot)
        if failures:
            raise ffutil.FFError(f'{len(failures)} source file(s) failed; inspect footage status and reimport to retry')
        progress(f'Done: {len(shoot.files)}/{len(shoot.files)} ready')
        return status(shoot.id)


def start_processing(shoot_id: str) -> str:
    """Background entry point for app callers; progress is available in jobs."""
    load(shoot_id)
    return jobs.start('footage', shoot_id, lambda progress: process_shoot(shoot_id, progress))

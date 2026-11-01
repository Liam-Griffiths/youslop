"""Offline clip exports. Originals are inputs only; every output is exclusive."""
from __future__ import annotations

import csv
import json
import io
import math
import re
from pathlib import Path

from . import ffutil, footage


def _reserve(folder: Path, name: str):
    """Exclusive creation also protects existing files and symlinks during races."""
    path = folder / name
    count = 1
    while True:
        try:
            return path, path.open('xb')
        except FileExistsError:
            count += 1
            path = folder / f'{Path(name).stem}-{count}{Path(name).suffix}'


def export_clips(shoot_id: str, clip_ids: list[str], output: str | Path, *,
                 pattern: str = '{label}-{id}', mode: str = 'encode') -> dict:
    """Export selected original spans plus JSON and CSV manifests, never proxies.

    Copy seeks to a preceding keyframe and may differ by a GOP. Encode uses
    accurate input seeking and a duration in seconds, preserving original size.
    """
    if mode not in {'copy', 'encode'}:
        raise ValueError('Mode must be copy or encode')
    if not clip_ids or len(set(clip_ids)) != len(clip_ids):
        raise ValueError('Select distinct clips to export')
    shoot = footage.load(shoot_id)
    clips = {c.id: c for c in shoot.clips}
    sources = {s.id: s for s in shoot.files}
    plans = []
    for cid in clip_ids:
        if cid not in clips:
            raise ValueError(f'Unknown clip: {cid}')
        clip = clips[cid]
        source = sources[clip.file]
        src = footage.source_path(shoot, source).resolve(strict=True)
        if not (math.isfinite(clip.in_s) and math.isfinite(clip.out_s)
                and 0 <= clip.in_s < clip.out_s
                and (not source.duration or clip.out_s <= source.duration + 1e-6)):
            raise ValueError(f'Invalid clip span: {cid}')
        try:
            name = pattern.format(label='-'.join(clip.labels) or 'clip', id=cid,
                                  source=src.stem)
        except (KeyError, ValueError, IndexError, AttributeError) as exc:
            raise ValueError('Use {label}, {id}, or {source} in the naming pattern') from exc
        name = re.sub(r'[^\w.-]+', '-', name, flags=re.UNICODE).strip('.-')[:160]
        if not name:
            raise ValueError('Naming pattern produces an empty filename')
        plans.append((clip, src, name))
    folder = Path(output).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for clip, src, name in plans:
        # Matroska accommodates original codecs in stream-copy mode.
        path, handle = _reserve(folder, name + ('.mkv' if mode == 'copy' else '.mp4'))
        handle.close()
        args = ['-ss', str(clip.in_s), '-i', str(src), '-t', str(clip.out_s - clip.in_s),
                '-map', '0:V:0', '-map', '0:a?', '-map_metadata', '0']
        if mode == 'copy':
            args += ['-c', 'copy', '-avoid_negative_ts', 'make_zero']
        else:
            args += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                     '-c:a', 'aac', '-movflags', '+faststart']
        ffutil.run([*args, str(path)], threads=1)
        rows.append({'clip_id': clip.id, 'filename': path.name, 'labels': clip.labels,
                     'in_s': clip.in_s, 'out_s': clip.out_s, 'source_path': str(src),
                     'mode': mode, 'timing_note': 'May differ by one GOP' if mode == 'copy'
                     else 'Accurate seek; frame precision'})
    json_path, handle = _reserve(folder, 'clips.json')
    with handle:
        handle.write(json.dumps(rows, indent=2, ensure_ascii=False).encode('utf-8'))
    csv_path, handle = _reserve(folder, 'clips.csv')
    with io.TextIOWrapper(handle, encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({**row, 'labels': json.dumps(row['labels'], ensure_ascii=False)} for row in rows)
    return {'clips': rows, 'json': str(json_path), 'csv': str(csv_path)}

"""Original v2 Numbers layouts and read-only, offline narration envelopes."""
import calendar
from datetime import date
from functools import lru_cache
import math
from pathlib import Path
import tempfile
import wave
from array import array
import sys
import subprocess

from . import ffutil
from .take_edits import kept_ranges

IDS = ('counter', 'progress_stat', 'spec_list', 'unit_chart', 'ranking_list',
       'calendar_grid', 'delta_card', 'take_waveform')
DATA_IDS = IDS[:-1]


@lru_cache(maxsize=16)
def _envelope(path, stamp, cuts):
    # Decode only into our own temporary directory; the take is never modified.
    with tempfile.TemporaryDirectory(prefix='block-wave-') as directory:
        out = Path(directory) / 'mono.wav'
        ffutil.run(['-protocol_whitelist', 'file,pipe', '-i', path, '-t', '600', '-vn', '-ac', '1', '-ar', '8000',
                    '-c:a', 'pcm_s16le', str(out)], timeout=30, threads=1)
        with wave.open(str(out), 'rb') as audio:
            samples = array('h', audio.readframes(audio.getnframes()))
        if sys.byteorder != 'little':
            samples.byteswap()
    if cuts:
        samples = array('h', (v for a, b in cuts for v in samples[int(a*8000):int(b*8000)]))
    if not samples:
        raise ValueError('empty narration')
    # RMS per bin, normalised together. Silence stays a flat line.
    bins = [samples[i*len(samples)//96:(i+1)*len(samples)//96] for i in range(96)]
    rms = [math.sqrt(sum(v*v for v in chunk)/max(1, len(chunk))) for chunk in bins]
    peak = max(rms) or 1
    return [v/peak for v in rms]


def waveform(ctx):
    take = ctx.get('take') or {}
    root = (ctx.get('asset_roots') or {}).get('project_root')
    if root and take.get('path') and float(take.get('duration') or 0) <= 600:
        root = Path(root).resolve()
        path = (root / take['path']).resolve()
        if path.is_relative_to(root) and path.is_file():
            try:
                stamp = path.stat()
                cuts = tuple(kept_ranges(take)) if take.get('cuts') else ()
                return _envelope(str(path), (stamp.st_mtime_ns, stamp.st_size), cuts), 'Local narration'
            except (OSError, ValueError, ffutil.FFError, subprocess.TimeoutExpired, wave.Error):
                pass
    return [abs(math.sin(i*.39)*math.sin(i*.13))*.85 for i in range(96)], 'Sample waveform'


def layout(ref, v, ctx):
    portrait = ctx['height'] > ctx['width']
    d = dict(x=130 if portrait else 230, w=756 if portrait else 1460,
             top=610 if portrait else 345, bottom=1390 if portrait else 850,
             header=310 if portrait else 125, footer=1430 if portrait else 890,
             portrait=portrait, rows=[])
    rows = v.get('rows', [])
    counts = {'counter':(1,1), 'progress_stat':(1,1), 'spec_list':(1,5),
              'unit_chart':(1,1), 'ranking_list':(1,5), 'calendar_grid':(0,31), 'delta_card':(2,2)}
    if ref in counts:
        lo, hi = counts[ref]
        if not lo <= len(rows) <= hi:
            raise ValueError(f'rows: {ref} requires {lo}..{hi} rows')
    for i, row in enumerate(rows):
        for key, value in row.items():
            if key == 'label' and (not isinstance(value, str) or not value.strip() or len(value) > 18):
                raise ValueError(f'rows[{i}].label: requires 1..18 characters')
            if key in ('value', 'selected', 'total') and (
                    type(value) not in (int, float) or not math.isfinite(value) or not -999999 <= value <= 999999):
                raise ValueError(f'rows[{i}].{key}: requires a finite number in -999999..999999')
    d['rows'] = [dict(r) for r in rows]
    if ref in ('counter', 'progress_stat'):
        d['value'] = rows[0]['value']
        if ref == 'counter' and round(d['value'], 2) != d['value']:
            raise ValueError('rows.value: counter supports at most two decimal places')
        if ref == 'progress_stat' and not 0 <= d['value'] <= 100:
            raise ValueError('rows.value: percentage must be in 0..100')
    if ref == 'unit_chart':
        selected, total = rows[0]['selected'], rows[0]['total']
        if total != int(total) or selected != int(selected) or not 1 <= total <= 60 or not 0 <= selected <= total:
            raise ValueError('rows: integer 0 <= selected <= total, total in 1..60 required')
        d.update(selected=int(selected), total=int(total), cols=min(10 if portrait else 12, int(total)))
    if ref == 'ranking_list':
        if any(r['value'] < 0 for r in rows):
            raise ValueError('rows.value: rankings require nonnegative values')
        maximum = max(1, max(r['value'] for r in rows))
        d['rows'] = [dict(r, ratio=r['value']/maximum) for r in sorted(rows, key=lambda r:-r['value'])]
    if ref == 'calendar_grid':
        if len(v['period']) != 1:
            raise ValueError('period: requires one date identifying the month')
        month = date.fromisoformat(v['period'][0]['date']).replace(day=1)
        marked = {date.fromisoformat(r['date']) for r in rows}
        if any((day.year, day.month) != (month.year, month.month) for day in marked):
            raise ValueError('rows.date: marked days must belong to month')
        first, days = calendar.monthrange(month.year, month.month)
        d['days'] = [dict(day=i-first+1, marked=date(month.year, month.month, i-first+1) in marked)
                     if first <= i < first+days else dict(day='', marked=False) for i in range(42)]
        d['month'] = f'{calendar.month_name[month.month]} {month.year}'
    if ref == 'delta_card':
        delta = rows[1]['value']-rows[0]['value']
        d.update(delta=f'{delta:+g}' if delta else '0', direction='Increase' if delta > 0 else 'Decrease' if delta < 0 else 'Unchanged')
    if ref == 'take_waveform':
        envelope, d['wave_source'] = waveform(ctx)
        d['points'] = ' '.join(f'{i*d["w"]/95:.2f},{120+(-1 if i%2 else 1)*v*105:.2f}' for i,v in enumerate(envelope))
    d['gap'] = min(145, (d['bottom']-d['top'])/max(1,len(rows)))
    return d

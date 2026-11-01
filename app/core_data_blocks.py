"""Bounded layouts for the eight built-in Numbers and data blocks (no capture)."""
import math

IDS = ('number_slam', 'stat_comparison', 'line_chart', 'bar_chart', 'bar_race',
       'percentage_ring', 'simple_table', 'date_timeline')


def layout(ref, v, width, height, seconds):
    portrait = height > width
    x, w, top = (130, 756, 580) if portrait else (230, 1460, 360)
    d = dict(x=x, w=w, top=top, plot_h=560 if portrait else 420,
             header=340 if portrait else 160, footer=1400 if portrait else 925,
             rows=[], frames=[], periods=[])
    rows = v.get('rows', [])
    limits = {'stat_comparison': (2, 2), 'line_chart': (2, 8), 'bar_chart': (1, 6),
              'bar_race': (2, 5), 'simple_table': (1, 6), 'date_timeline': (2, 5)}
    if ref in limits:
        lo, hi = limits[ref]
        if not lo <= len(rows) <= hi:
            raise ValueError(f'rows: {ref} requires {lo}..{hi} rows')
    for i, row in enumerate(rows):
        fields = {'date': 12, 'label': 48} if ref == 'date_timeline' else {'label': 18}
        if ref == 'simple_table':
            fields['value'] = 18
        for key, limit in fields.items():
            cell = row.get(key)
            if ref == 'simple_table' and key == 'value' and type(cell) in (int, float):
                cell = f'{cell:g}'
            if not isinstance(cell, str) or not cell.strip() or len(cell) > limit:
                raise ValueError(f'rows[{i}].{key}: requires 1..{limit} characters')
        keys = ('first', 'middle', 'last') if ref == 'bar_race' else ('value',)
        if ref not in ('simple_table', 'date_timeline'):
            for key in keys:
                n = row.get(key)
                if type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 999999:
                    raise ValueError(f'rows[{i}].{key}: requires a number in 0..999999')
    if ref in ('number_slam', 'percentage_ring'):
        n = v['value']
        d['frames'] = [n * (1-(1-i/16)**3) for i in range(17)]
        if ref == 'number_slam':
            d['frames'] = [f'{n if n else 0:,.{v["decimals"]}f}' for n in d['frames']]
        d['final'] = f'{n:g}'
    if ref in ('stat_comparison', 'line_chart', 'bar_chart', 'bar_race'):
        keys = ('first', 'middle', 'last') if ref == 'bar_race' else ('value',)
        d['maximum'] = max(1, max(row[k] for row in rows for k in keys))
        d['scale'] = f'0 — {d["maximum"]:g} · {v["unit"]}'
        d['rows'] = [dict(row, ratio=row[keys[-1]]/d['maximum']) for row in rows]
    if ref == 'line_chart':
        d['points'] = ' '.join(f'{i*w/(len(rows)-1):.2f},{d["plot_h"]*(1-r["value"]/d["maximum"]):.2f}'
                               for i, r in enumerate(rows))
    if ref == 'bar_race':
        if len({r['label'] for r in rows}) != len(rows):
            raise ValueError('rows: bar race labels must be unique')
        d['periods'] = [v[k] for k in ('first_period', 'middle_period', 'last_period')]
        rankings = [sorted(range(len(rows)), key=lambda i: (-rows[i][k], i)) for k in keys]
        gap = 110 if portrait else 88
        d['rows'] = []
        for i, row in enumerate(rows):
            rank = [order.index(i) for order in rankings]
            path = [dict(t=0, x=0, y=0)]
            for stage in (1, 2):
                t = seconds*.3*stage
                path += [dict(t=t-.16, x=0, y=(rank[stage-1]-rank[0])*gap),
                         dict(t=t, x=0, y=(rank[stage]-rank[0])*gap, ease='cubic-out')]
            d['rows'].append(dict(label=row['label'], y=top+80+rank[0]*gap, path=path,
                frames=[dict(value=f'{row[k]:g}', width=w*row[k]/d['maximum']) for k in keys]))
    if ref in ('simple_table', 'date_timeline'):
        d['rows'] = rows
    return d

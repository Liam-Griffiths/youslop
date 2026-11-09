"""Deterministic number comparison for data-block checks, with spoken precision."""
from decimal import Decimal, ROUND_HALF_UP
import re

SCALES = {'thousand': Decimal(1000), 'million': Decimal(1000000), 'billion': Decimal(1000000000)}
NUMBER = re.compile(r'(?<![\w.])(?P<about>about\s+|roughly\s+|approximately\s+)?'
                    r'(?P<n>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)'
                    r'(?:\s*(?P<scale>thousand|million|billion)\b)?'
                    r'(?:\s*(?P<pct>%|percent\b))?', re.I)


def extract(text):
    # Citations are attribution, not narrated quantities.
    text = re.sub(r'\[\d+\]|https?://\S+', '', text)
    result = []
    for m in NUMBER.finditer(text):
        raw = m['n'].replace(',', '')
        n = Decimal(raw)
        scale = SCALES.get((m['scale'] or '').lower(), Decimal(1))
        # Spoken figures are rounded to the precision said: "68 percent" covers a
        # shown 67.6, "72.4" must show 72.4.
        precision = Decimal(1).scaleb(n.as_tuple().exponent)
        if m['about'] and '.' not in raw and n:
            # An approximation ending in zero communicates rounding to tens etc.
            precision = Decimal(10) ** (len(raw) - len(raw.rstrip('0')))
        year = (not m['scale'] and not m['pct'] and not m['about'] and ',' not in m['n']
                and '.' not in raw and 1000 <= n <= 2099)
        result.append(dict(value=n*scale, step=precision*scale, year=year,
                           percent=bool(m['pct']), text=m[0]))
    return result


def shown(meta, values, ref):
    numbers, dates, headline = [], [], []
    unit = values.get('unit', values.get('suffix', values.get('column_value', '')))

    def number(value, suffix):
        suffix = suffix or ''
        scale = next((s for k, s in SCALES.items() if re.search(r'\b'+k+r'\b', suffix, re.I)), Decimal(1))
        item = dict(value=Decimal(str(value))*scale,
                    percent='%' in suffix or 'percent' in suffix.lower(), text=f'{value} {suffix}'.strip())
        numbers.append(item)
        return item

    for key, spec in meta['variables'].items():
        if spec['type'] == 'number':
            value = values[key]
            if ref == 'number_slam' and key == 'value':
                value = f'{value:.{values["decimals"]}f}'
            item = number(value, spec.get('unit', '%' if ref == 'percentage_ring' else unit))
            if key == 'value' and ref in ('number_slam', 'percentage_ring'):
                headline.append(item)
        elif spec['type'] == 'table':
            for row in values[key]:
                if ref == 'date_timeline' and not spec.get('columns'):
                    # Legacy timelines allow free-form date labels, not just ISO.
                    dates.extend(n for n in extract(row.get('date', '')) if n['year'])
                for col in spec.get('columns', []):
                    cell = row[col['key']]
                    if col['type'] == 'number':
                        if ref == 'bubble_map' and col['key'] in ('lat','lon'):
                            continue  # Placement coordinates are not shown figures.
                        if ref in ('route_map','place_pin') and col['key'] in ('lat','lon'):
                            cell = round(cell,2)
                        number(cell, col.get('unit', unit))
                    elif col['type'] == 'date':
                        dates.extend(extract(str(cell)[:4]))
                # Legacy untyped simple tables can mix text and numbers.
                if not spec.get('columns') and type(row.get('value')) in (int, float):
                    number(row['value'], unit)
                elif not spec.get('columns') and isinstance(row.get('value'), str):
                    for item in extract(row['value']):
                        if not item['year']:
                            # A textual cell may already carry its own multiplier.
                            suffix = '' if any(k in item['text'].lower() for k in SCALES) else unit
                            n = number(item['value'], suffix)
                            n['percent'] |= item['percent']
    if ref == 'timezone_strip':
        from .place_blocks import clocks
        rows, instant = clocks(values)
        numbers.extend(n for row in rows for n in extract(row['time']))
        numbers.extend(n for n in extract(instant) if not n['year'])
        dates.extend(n for n in extract(instant) if n['year'])
    if ref in ('bar_chart', 'bar_race') and numbers:
        headline = [max(numbers, key=lambda n: n['value'])]
    if ref == 'delta_card':
        number(values['rows'][1]['value'] - values['rows'][0]['value'], unit)
    return numbers, dates, headline


def matches(spoken, value):
    if spoken['percent'] and not value['percent']:
        return False
    if spoken['year']:
        return value['value'] == spoken['value']
    rounded = (value['value'] / spoken['step']).quantize(Decimal(1), rounding=ROUND_HALF_UP) * spoken['step']
    return rounded == spoken['value']

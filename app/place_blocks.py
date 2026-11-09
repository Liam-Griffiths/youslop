"""Offline Places layouts. Geometry is prepared once; motion uses static plates."""
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import paths

IDS = ('route_map', 'bubble_map', 'region_map', 'place_pin', 'distance_card', 'timezone_strip')


def _delta(lon):
    return (lon + 180) % 360 - 180


@lru_cache(maxsize=2)
def _countries(path, stamp):
    return json.loads(path.read_text())['features']


@lru_cache(maxsize=48)
def _outlines(path, stamp, west, south, east, north):
    """Unwrap each ring, repeat around the seam; SVG clips the viewport once."""
    result = []
    for feature in _countries(path, stamp):
        geometry = feature['geometry']
        polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
        pieces = []
        for polygon in polygons:
            for ring in polygon:
                points = [ring[0]]
                for lon, lat in ring[1:]:
                    points.append((points[-1][0] + _delta(lon-points[-1][0]), lat))
                for shift in (-720, -360, 0, 360, 720):
                    if max(p[0] for p in points)+shift < west or min(p[0] for p in points)+shift > east:
                        continue
                    pieces.append('M'+'L'.join(f'{(lon+shift-west)*1000/(east-west):.2f},{(north-lat)*500/(north-south):.2f}' for lon, lat in points)+'Z')
        result.append(dict(feature['properties'], path=''.join(pieces)))
    return result


def _text(value, key, limit=32):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{key}: requires 1..{limit} characters')


def clocks(v):
    if len(v['reference']) != 1:
        raise ValueError('reference: requires one explicit UTC instant')
    raw = v['reference'][0]['utc']
    _text(raw, 'reference.utc', 25)
    try:
        instant = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if instant.utcoffset() is None or instant.utcoffset().total_seconds() != 0:
            raise ValueError()
    except ValueError as exc:
        raise ValueError('reference.utc: requires an ISO timestamp with UTC offset') from exc
    result = []
    for row in v['rows']:
        _text(row['city'], 'rows.city')
        _text(row['zone'], 'rows.zone', 64)
        try:
            local = instant.astimezone(ZoneInfo(row['zone']))
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError('rows.zone: requires an installed IANA timezone') from exc
        day = (local.date()-instant.date()).days
        result.append(dict(row, time=local.strftime('%H:%M'), day={-1:'Previous day',0:'Same day',1:'Next day'}[day]))
    return result, instant.astimezone(timezone.utc).strftime('%d %b %Y · %H:%M UTC')


def _duration(minutes):
    """290 -> "4 h 50 min"; 45 -> "45 min"; 1500 -> "1 d 1 h"."""
    total = round(minutes)
    days, rest = divmod(total, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days:,} d {hours} h" if hours else f"{days:,} d"
    if hours:
        return f"{hours} h {mins} min" if mins else f"{hours} h"
    return f"{mins} min"


def _fit(points, pad=1.5, min_lat=24.0):
    """West, south, east, north framing `points` (lon, lat) at the map's 2:1.

    The map is drawn equirectangular into a 1000x500 box, so a view whose
    longitude span is not twice its latitude span stretches the countries.
    Longitudes are unwrapped from the first point so a route across the date
    line frames the short way. Spread-out points widen to the whole world.
    """
    lon0 = points[0][0]
    lons = [lon0 + _delta(lon - lon0) for lon, _ in points]
    lats = [lat for _, lat in points]
    lat_span = max(min_lat, (max(lats) - min(lats)) * pad)
    lon_span = max(2 * lat_span, (max(lons) - min(lons)) * pad)
    lat_span = lon_span / 2
    if lon_span >= 360 or lat_span >= 180:
        return -180, -90, 180, 90
    lat_c = max(-90 + lat_span / 2, min(90 - lat_span / 2, (max(lats) + min(lats)) / 2))
    lon_c = (max(lons) + min(lons)) / 2
    return lon_c - lon_span / 2, lat_c - lat_span / 2, lon_c + lon_span / 2, lat_c + lat_span / 2


def layout(ref, v, ctx):
    portrait = ctx['height'] > ctx['width']
    d = dict(portrait=portrait, x=130 if portrait else 230, w=756 if portrait else 1460,
             header=310 if portrait else 125, top=590 if portrait else 340,
             footer=1430 if portrait else 888, rows=[])
    rows = v['rows']
    lo, hi = {'route_map':(2,2), 'bubble_map':(1,10), 'region_map':(1,6),
              'place_pin':(1,1), 'distance_card':(1,1), 'timezone_strip':(1,6)}[ref]
    if not lo <= len(rows) <= hi:
        raise ValueError(f'rows: {ref} requires {lo}..{hi} rows')
    if ref == 'timezone_strip':
        d['rows'], d['instant'] = clocks(v)
        return d
    if ref == 'distance_card':
        for key in ('distance','minutes'):
            if not 0 <= rows[0][key] <= 999999 or round(rows[0][key],2) != rows[0][key]:
                raise ValueError(f'rows.{key}: requires 0..999999 with at most two decimals')
        d.update(distance=f'{rows[0]["distance"]:,.2f}'.rstrip('0').rstrip('.'),
                 minutes=f'{rows[0]["minutes"]:,.2f}'.rstrip('0').rstrip('.'),
                 travel=_duration(rows[0]["minutes"]))
        return d
    for row in rows:
        if ref != 'region_map':
            _text(row['label'], 'rows.label')
            if not -90 <= row['lat'] <= 90 or not -180 <= row['lon'] <= 180:
                raise ValueError('rows: latitude/longitude outside geographic bounds')
        if ref in ('bubble_map','region_map') and (not 0 <= row['value'] <= 999999 or round(row['value'],2) != row['value']):
            raise ValueError('rows.value: requires 0..999999 with at most two decimals')
    west, south, east, north = -180, -90, 180, 90
    if ref == 'route_map':
        a, b = rows
        lon_b = a['lon']+_delta(b['lon']-a['lon'])
        center = (a['lon']+lon_b)/2
        if v['view'] == 'region':
            west, south, east, north = _fit([(a['lon'], a['lat']), (b['lon'], b['lat'])])
        else:
            west, east = center-180, center+180
    elif ref == 'bubble_map':
        west, south, east, north = _fit([(r['lon'], r['lat']) for r in rows], pad=1.6)
    path = paths.resource_root()/'static/blocks/_geo/countries-110m.json'
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    countries = _outlines(path, stamp, west, south, east, north)
    d['countries'] = countries
    d.update(map_w=756 if portrait else 940, map_h=378 if portrait else 470,
             key_x=0 if portrait else 980, key_y=410 if portrait else 0)
    maximum = max((r.get('value',0) for r in rows), default=0)
    if ref == 'region_map':
        lookup = {c[k]:c for c in countries for k in ('iso_a3','name') if c[k] != '-99'}
        values = {}
        for row in rows:
            _text(row['country'], 'rows.country', 64)
            country = lookup.get(row['country'])
            if country is None or country['name'] in values:
                raise ValueError('rows.country: requires distinct vendored ISO A3 codes or exact country names')
            values[country['name']] = row['value']
            d['rows'].append(dict(label=country['name'], value=row['value']))
        d['countries'] = [dict(c, ratio=values.get(c['name'],0)/maximum if maximum else 0, has_value=c['name'] in values) for c in countries]
        d.update(maximum=maximum, minimum=0)
    else:
        for row in rows:
            # Unwrap toward the view so a point just across the date line lands inside it.
            lon = row['lon'] + 360 * round(((west+east)/2 - row['lon']) / 360)
            x, y = (lon-west)*1000/(east-west), (north-row['lat'])*500/(north-south)
            d['rows'].append(dict(row, x=x, y=y, radius=30*math.sqrt(row.get('value',0)/maximum) if maximum else 0))
        if ref == 'route_map':
            a, b = d['rows']
            lift = min(140, max(35, abs(a['x']-b['x'])*.2))
            d['arc'] = f'M{a["x"]:.2f},{a["y"]:.2f} Q{(a["x"]+b["x"])/2:.2f},{max(12,min(a["y"],b["y"])-lift):.2f} {b["x"]:.2f},{b["y"]:.2f}'
    if ref == 'bubble_map':
        occupied = []
        for row in d['rows']:
            label_x = max(24, min(976, row['x']))
            candidates = [(max(24,min(976,label_x+dx)), max(28,min(472,row['y']+dy)))
                          for dx in (0,-40,40,-80,80) for dy in (-36,36,-72,72,-108,108,-144,144,-180,180)]
            label_x, label_y = next(((x,y) for x,y in candidates if all(abs(x-a)>32 or abs(y-b)>28 for a,b in occupied)), candidates[-1])
            occupied.append((label_x,label_y))
            row.update(label_x=label_x,label_y=label_y)
    if ref == 'place_pin':
        position = ctx.get('overlay_position', 'bottom_left')
        d.update(x=(ctx['width']-918 if portrait else ctx['width']-1050) if position.endswith('right') else d['x'],
                 w=756 if portrait else 820, top=(350 if portrait else 140) if position.startswith('top') else (1010 if portrait else 560))
    return d

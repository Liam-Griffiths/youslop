"""Places data validation, offline projection and deterministic clock checks."""
from pathlib import Path

import pytest

from app import block_authoring, block_library, blocks, check, place_blocks, scenes


@pytest.mark.parametrize('ref', place_blocks.IDS)
@pytest.mark.parametrize('aspect', ['16:9','9:16'])
def test_places_contract(ref, aspect):
    meta = blocks.discover()[ref]['meta']
    assert meta['default_colors'] == blocks.discover()['title_card']['meta']['default_colors']
    assert block_authoring.check(ref, static_only=True) == []
    template, ctx = blocks.prepare(ref, aspect=aspect, theme={'accent':'#3388CC','radius':12,'pace':1.4})
    html = scenes.render_html(template, ctx)
    assert not scenes.lint(html, asset_root=ctx['block_assets_root'])
    assert 'data-capture="frames"' not in html and ctx['budget'] == 0
    assert not block_authoring.token_lint(Path('static/blocks/route_map/places_base.html').read_text())
    assert ctx['vars']['accent'] == '#3388CC'


@pytest.mark.parametrize('ref,values', [
    ('route_map', {'rows':[]}),
    ('route_map', {'rows':[dict(label='A',lat=91,lon=0),dict(label='B',lat=0,lon=0)]}),
    ('bubble_map', {'rows':[dict(label='X',lat=0,lon=181,value=1)]}),
    ('bubble_map', {'rows':[dict(label='X'*33,lat=0,lon=0,value=1)]}),
    ('bubble_map', {'rows':[dict(label='X',lat=0,lon=0,value=-1)]}),
    ('bubble_map', {'rows':[dict(label='X',lat=0,lon=0,value=1)]*11}),
    ('region_map', {'rows':[dict(country='ZZZ',value=1)]}),
    ('region_map', {'rows':[dict(country='CAN',value=1),dict(country='Canada',value=2)]}),
    ('distance_card', {'rows':[dict(distance=-1,minutes=30)]}),
    ('distance_card', {'rows':[dict(distance=1.001,minutes=30)]}),
    ('timezone_strip', {'reference':[dict(utc='2026-11-08T16:00:00')]}),
    ('timezone_strip', {'rows':[dict(city='Here',zone='Missing/Zone')]}),
])
def test_invalid_places_fail_before_capture(ref, values):
    with pytest.raises(ValueError):
        blocks.prepare(ref, values)


def test_projection_seam_area_scale_and_zero_data():
    _, ctx = blocks.prepare('route_map', {'rows':[dict(label='A',lat=10,lon=170),dict(label='B',lat=10,lon=-170)]})
    a,b = ctx['places']['rows']
    # The short way across the date line: 20 degrees inside a 48-degree view (2:1).
    assert abs(a['x']-b['x']) == pytest.approx(20 * 1000 / 48)
    assert len(ctx['places']['countries']) == 177
    assert any(c['path'] for c in ctx['places']['countries'])
    _, ctx = blocks.prepare('bubble_map', {'rows':[dict(label='A',lat=0,lon=0,value=1),dict(label='B',lat=0,lon=0,value=4)]})
    assert [r['radius'] for r in ctx['places']['rows']] == [15,30]
    _, ctx = blocks.prepare('region_map', {'rows':[dict(country='CAN',value=0)]})
    countries = ctx['places']['countries']
    assert sum(c['has_value'] for c in countries) == 1
    assert next(c for c in countries if c['iso_a3']=='CAN')['ratio'] == 0
    assert ctx['places']['maximum'] == 0


def test_explicit_clocks_dst_fractional_offsets_and_rollover():
    values = dict(reference=[dict(utc='2026-07-01T23:30:00Z')],rows=[dict(city='Vancouver',zone='America/Vancouver'),dict(city='Kathmandu',zone='Asia/Kathmandu')])
    _, ctx = blocks.prepare('timezone_strip',values)
    assert [(r['time'],r['day']) for r in ctx['places']['rows']] == [('16:30','Same day'),('05:15','Next day')]
    values['reference'] = [dict(utc='2026-01-01T01:30:00Z')]
    _, ctx = blocks.prepare('timezone_strip',values)
    assert ctx['places']['rows'][0]['time'] == '17:30'
    assert ctx['places']['rows'][0]['day'] == 'Previous day'


@pytest.mark.parametrize('ref,spoken', [('route_map','At 49.28 degrees.'),('bubble_map','840 trips.'),('region_map','72 percent.'),('place_pin','Longitude -123.12.'),('distance_card','4580 km and 290 min.'),('timezone_strip','At 08:00 in Vancouver.')])
def test_places_number_matching(ref, spoken):
    p = dict(id='p',start=0,narration=spoken,block_cues=[dict(block=ref,vars={})])
    assert check.number_match({'paragraphs':[p]},None,None) == []
    p['narration'] = 'We measured 999999.'
    assert check.number_match({'paragraphs':[p]},None,None)[0].code == 'number_match'


def test_places_signature_tracks_shared_base_and_geo(monkeypatch, tmp_path):
    # Simulate a shared-geometry edit without touching the vendored source.
    root = tmp_path/'blocks'
    for folder in ('bubble_map','route_map','_geo'):
        (root/folder).mkdir(parents=True)
    (root/'bubble_map/block.json').write_text('{}')
    geo = root/'_geo/countries-110m.json'
    geo.write_text('first')
    monkeypatch.setattr(blocks,'BUILTIN_DIR',root)
    item = dict(root=root/'bubble_map',meta=dict(id='bubble_map'))
    first = block_library.signature(item)
    geo.write_text('changed')
    assert first != block_library.signature(item)


def test_dense_bubble_labels_and_large_decimal_figures():
    _, ctx = blocks.prepare('bubble_map', {'rows':[dict(label='City',lat=49,lon=-123,value=999998.99)]*10})
    points = [(r['label_x'],r['label_y']) for r in ctx['places']['rows']]
    assert all(abs(x-a)>32 or abs(y-b)>28 for i,(x,y) in enumerate(points) for a,b in points[:i])
    template, ctx = blocks.prepare('distance_card', {'rows':[dict(distance=999998.99,minutes=999998.99)]})
    assert '999,998.99 km' in scenes.render_html(template,ctx)
    assert ctx['places']['minutes'] == '999,998.99'


def test_bubble_coordinates_are_not_quantity_claims():
    p = dict(id='p',start=0,narration='49 trips.',block_cues=[dict(block='bubble_map',vars={})])
    assert check.number_match({'paragraphs':[p]},None,None)[0].code == 'number_match'
    p.update(narration='In 2025.',block_cues=[dict(block='timezone_strip',vars={})])
    assert check.number_match({'paragraphs':[p]},None,None)[0].code == 'number_match'


def test_fit_keeps_two_to_one_and_frames_points():
    from app import place_blocks
    west, south, east, north = place_blocks._fit([(-123.1, 49.3), (-73.6, 45.5), (-79.4, 43.7)])
    assert east - west == pytest.approx(2 * (north - south))
    assert west < -123.1 and east > -73.6 and south < 43.7 and north > 49.3
    assert place_blocks._fit([(-100, 70), (-100, -60)]) == (-180, -90, 180, 90)


def test_bubble_map_zooms_to_its_points():
    _, ctx = blocks.prepare('bubble_map', {})
    xs = [r['x'] for r in ctx['places']['rows']]
    assert max(xs) - min(xs) > 400          # spread across the map, not one corner


def test_travel_time_reads_as_hours_and_minutes():
    from app import place_blocks
    assert [place_blocks._duration(m) for m in (45, 60, 290, 1500)] == ['45 min', '1 h', '4 h 50 min', '1 d 1 h']

"""V2 Numbers: bounded data, number honesty and read-only local take analysis."""
import math
from pathlib import Path
import struct
import wave

import pytest

from app import block_authoring, blocks, check, number_blocks, scenes


@pytest.mark.parametrize('ref', number_blocks.IDS)
@pytest.mark.parametrize('aspect', ['16:9', '9:16'])
def test_numbers_contract(ref, aspect):
    meta = blocks.discover()[ref]['meta']
    assert meta['default_colors'] == blocks.discover()['title_card']['meta']['default_colors']
    assert block_authoring.check(ref, static_only=True) == []
    template, ctx = blocks.prepare(ref, aspect=aspect, theme={'accent':'#3388CC', 'radius':12, 'pace':1.4})
    html = scenes.render_html(template, ctx)
    assert not scenes.lint(html, asset_root=ctx['block_assets_root'])
    assert not block_authoring.token_lint(Path('static/blocks/counter/numbers_base.html').read_text())
    assert ctx['vars']['accent'] == '#3388CC'
    assert ('data-capture="frames"' in html) == (ref == 'counter')


@pytest.mark.parametrize('ref,values', [
    ('counter', {'rows':[]}), ('counter', {'rows':[{'value':1.123}]}),
    ('progress_stat', {'rows':[{'value':101}]}),
    ('spec_list', {'rows':[{'label':'x'*19,'value':1}]}),
    ('ranking_list', {'rows':[{'label':'Rail','value':-1}]}),
    ('unit_chart', {'rows':[{'selected':2,'total':1}]}),
    ('unit_chart', {'rows':[{'selected':1,'total':61}]}),
    ('unit_chart', {'rows':[{'selected':1.5,'total':12}]}),
    ('calendar_grid', {'period':[]}),
    ('calendar_grid', {'rows':[{'date':'2026-12-01'}]}),
    ('delta_card', {'rows':[{'label':'Before','value':1}]}),
])
def test_invalid_numbers_fail_before_capture(ref, values):
    with pytest.raises(ValueError):
        blocks.prepare(ref, values)


def test_ranking_calendar_and_delta():
    _, ctx = blocks.prepare('ranking_list', {'rows':[{'label':'A','value':0},{'label':'B','value':0}]})
    assert [r['label'] for r in ctx['numbers']['rows']] == ['A', 'B']
    assert all(r['ratio'] == 0 for r in ctx['numbers']['rows'])
    _, ctx = blocks.prepare('calendar_grid', {'period':[{'date':'2024-02-01'}],'rows':[{'date':'2024-02-29'}]})
    days = ctx['numbers']['days']
    assert len(days) == 42 and days[3]['day'] == 1
    assert [c['day'] for c in days if c['marked']] == [29]
    _, ctx = blocks.prepare('delta_card')
    assert (ctx['numbers']['delta'],ctx['numbers']['direction']) == ('-14','Decrease')


@pytest.mark.parametrize('ref,spoken', [
    ('counter','We counted 4280 trips.'), ('progress_stat','68 percent complete.'),
    ('spec_list','The route is 24 km.'), ('unit_chart','1 in 12 trips.'),
    ('ranking_list','Rail carries 840 trips.'), ('calendar_grid','Visits in 2026.'),
    ('delta_card','From 42 to 28 minutes, a change of -14 minutes.'),
])
def test_number_match_uses_new_tables(ref, spoken):
    p = dict(id='p',start=0,narration=spoken,block_cues=[dict(block=ref,vars={})])
    assert check.number_match({'paragraphs':[p]},None,None) == []
    p['narration'] = 'In 2025.' if ref == 'calendar_grid' else 'We measured 999.'
    assert check.number_match({'paragraphs':[p]},None,None)[0].code == 'number_match'


def test_waveform_local_cuts_fallback_and_invalidation(tmp_path):
    path = tmp_path/'take.wav'
    def write(loud):
        with wave.open(str(path),'wb') as audio:
            audio.setparams((1,2,8000,0,'NONE','not compressed'))
            audio.writeframes(b''.join(struct.pack('<h',int(loud*math.sin(i*.1)) if i < 8000 else 0) for i in range(16000)))
    write(12000)
    original = path.read_bytes()
    ctx = scenes.context_base()
    ctx.update(asset_roots={'project_root':str(tmp_path)},take={'path':'take.wav','duration':2})
    _, prepared = blocks.prepare('take_waveform',context=ctx)
    assert prepared['numbers']['wave_source'] == 'Local narration'
    first = prepared['numbers']['points']
    ctx['take']['cuts'] = [{'a':0,'b':1,'by':'hand'}]
    _, prepared = blocks.prepare('take_waveform',context=ctx)
    assert all(float(p.split(',')[1]) == 120 for p in prepared['numbers']['points'].split())
    assert path.read_bytes() == original
    ctx['take'].pop('cuts')
    write(0)
    _, prepared = blocks.prepare('take_waveform',context=ctx)
    assert prepared['numbers']['points'] != first
    ctx['take']['path'] = '../outside.wav'
    _, prepared = blocks.prepare('take_waveform',context=ctx)
    assert prepared['numbers']['wave_source'] == 'Sample waveform'
    assert number_blocks.waveform({}) == number_blocks.waveform({})

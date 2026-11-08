"""Suggestions and per-paragraph application are offline and non-destructive."""
import pytest
import asyncio
import httpx

from app import blocks, catalog, main, store
from app.block_suggest import suggest
from app.schema import Project, Slide


@pytest.mark.parametrize('narration,note,ref', [
    ('There are 42 stations.', '', 'number_slam'),
    ('Ridership rose 7.5 percent.', '', 'percentage_ring'),
    ('There were 42 buses and 21 trains.', '', 'stat_comparison'),
    ('It opened in 1863 and expanded in 1900.', '', 'date_timeline'),
    ('From 2024-01-01 to 2025-03-01.', '', 'date_timeline'),
    ('She said “All aboard”.', '', 'quote_card'),
    ('First write. Then record. Finally publish.', '', 'step_list'),
    ('1. Write. 2. Record. 3. Publish.', '', 'step_list'),
    ('The train reaches Vancouver.', 'Map of the location', 'map_highlight'),
])
def test_rules(narration, note, ref):
    result = suggest(narration, note)
    assert ref in [r['block'] for r in result]
    assert result == suggest(narration, note)
    found = blocks.discover()
    for row in result:
        assert set(row) == {'block', 'vars', 'reason'}
        blocks.validate_vars(found[row['block']]['meta'], row['vars'])


def test_no_signal_and_no_place_guess():
    assert suggest('The train reaches Vancouver.', 'Wide shot') == []
    assert suggest('See [42] for details.') == []
    assert [r['block'] for r in suggest('In 1863 and 1900.')] == ['date_timeline']
    assert [r['block'] for r in suggest('1. Write. 2. Record.')] == ['step_list']


def test_prefills():
    percent = suggest('About 68 percent use transit.')[0]
    assert percent['block'] == 'percentage_ring' and percent['vars']['value'] == 68
    number = suggest('It cost 2.5 million dollars.')[0]
    assert number['block'] == 'number_slam'
    assert number['vars']['value'] == 2.5 and number['vars']['unit'] == 'million'


def test_endpoint_shape_and_remove_preserves_other_cues(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    p = Project(id='psuggest', title='Test', idea='', slides=[Slide(id='s1', narration='42 stations.')])
    p.slides[0].cues = {'ticker': [{'kind': 'text', 'text': 'Keep'}],
                        'blocks': [{'block': 'number_slam', 'vars': {'value': 42}}]}
    p.slides[0].chosen_id = 'candidate-kept'
    store.save(p)
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://127.0.0.1') as client:
            url = '/api/projects/psuggest/slides/s1'
            before = store.load(p.id).to_dict()
            response = await client.get(url + '/block-suggestions')
            assert response.status_code == 200
            assert response.json()[0]['block'] == 'number_slam'
            assert set(response.json()[0]) == {'block', 'vars', 'reason'}
            assert store.load(p.id).to_dict() == before
            assert (await client.get('/api/projects/psuggest/slides/missing/block-suggestions')).status_code == 404
            response = await client.patch(url, json={'cues': {'blocks': []}})
            assert response.status_code == 200
            assert response.json()['cues'] == {'ticker': p.slides[0].cues['ticker']}
            assert response.json()['chosen_id'] == 'candidate-kept'

    asyncio.run(request())


def test_third_party_gate_is_local_and_allowlisted(monkeypatch):
    monkeypatch.setattr(catalog, 'installed', lambda: [{'name': 'local', 'license': 'Apache-2.0', 'third_party': True}])
    monkeypatch.setattr(catalog, 'ui_enabled', lambda: False)
    assert main.third_party_blocks() == []
    monkeypatch.setattr(catalog, 'ui_enabled', lambda: True)
    assert main.third_party_blocks()[0]['third_party'] is True


def test_csv_error_reaches_preview_response():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        main.block_preview('stat_comparison', {'values': {'rows': 'label,value\nRail,wrong'},
                            'aspect': '9:16', 'kind': 'trial', 'session': 'csv-test', 'sequence': 1})
    assert error.value.status_code == 400
    assert 'rows row 1 column value' in error.value.detail


def test_map_and_step_note_are_explicit():
    assert suggest('We travel north.', 'First walk. Then take the train. Finally stop.')[0]['block'] == 'step_list'
    result = suggest('A mountain road.', 'A map of the route')
    assert result[0]['block'] == 'map_highlight'
    assert result[0]['vars']['picture'] == ''  # Never pretend the sample map is this location.



def test_channel_preferences_retain_alternatives_and_provenance():
    from app.schema import Channel
    from app import overlay_plan
    channel = Channel(id='c1',name='Series',blocks=['number_slam'],block_presets=[
        dict(id='percent',name='Our percent',block='percentage_ring',values={'value':12}),
        dict(id='name',name='Our name',block='lower_third_rule',values={'title':'Series name'}),
        dict(id='gone',name='Removed',block='removed',values={})])
    original = suggest('About 68 percent use transit.')
    ranked = suggest('About 68 percent use transit.',channel=channel)
    # Every alternative is still offered (a pinned block is not listed twice).
    assert {r['block'] for r in original} <= {r['block'] for r in ranked}
    # The paragraph's number wins over the preset's saved 12.
    assert ranked[0]['vars']['value'] == 68
    assert ranked[0]['preset'] == {'id':'percent','scope':'channel'}
    assert ranked == suggest('About 68 percent use transit.',channel=channel)
    assert any(r['block'] == 'number_slam' and r['reason'] == 'Pinned to channel' for r in ranked)
    original = overlay_plan.suggest('We met Hannah Chen at the dock.')
    ranked = overlay_plan.suggest('We met Hannah Chen at the dock.',channel=channel)
    assert {r['block_id'] for r in original} <= {r['block_id'] for r in ranked}
    assert ranked[0]['block_id'] == 'lower_third_rule'
    # The detected name labels the graphic, never the preset's saved text.
    assert ranked[0]['vars']['title'] == 'Hannah Chen' and ranked[0]['on'] == 'Hannah Chen'
    assert ranked[0]['preset'] == {'id':'name','scope':'channel'}



def test_channel_overlay_plan_keeps_hand_and_avoids_duplicate_names(project, monkeypatch):
    from app import channels, overlay_plan
    from app.schema import Channel
    channel = Channel(id='c1',name='Series',block_presets=[
        dict(id='name',name='Our name',block='lower_third_rule',values={'title':'Series name'})])
    monkeypatch.setattr(channels,'load_or_none',lambda cid:channel)
    slide = project.slides[0]
    slide.narration = 'We met Hannah Chen. Ridership rose 40 percent.'
    slide.candidates, slide.chosen_id = [dict(id='f',provider='footage')], 'f'
    overlay_plan.apply(project,slide)
    assert [o['block_id'] for o in slide.overlays] == ['lower_third_rule','kinetic_caption_rise']
    assert slide.overlays[0]['preset'] == {'id':'name','scope':'channel'}
    before = slide.to_dict()
    overlay_plan.apply(project,slide)
    assert slide.to_dict() == before

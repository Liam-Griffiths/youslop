"""Variables stay tied to schema fields, scene contexts and lazy proxy keys."""
import pytest
from fastapi import HTTPException

from app import main, render, scenes
from app.schema import Channel, Project
from app.variables import variables


def test_sources_and_reset():
    ch = Channel(id='channel', name='Example')
    p = Project(id='project', idea='', title='Episode')
    assert variables(p)['colors']['accent']['source'] == 'theme'
    ch.style.accent = p.style.accent = '#123456'
    assert variables(p, ch)['colors']['accent']['source'] == 'channel'
    p.style.accent = '#abcdef'
    assert variables(p, ch)['colors']['accent']['source'] == 'project'
    from app.variables import apply
    apply(p, ch, 'project', 'accent', None)
    assert p.style.accent == ch.style.accent
    assert variables(p, ch)['colors']['bg']['editable'] is False
    assert variables(p, ch)['frame']['arrive_s']['source'] == 'default'
    ch.frame.arrive_s = p.frame.arrive_s = 0.7
    assert variables(p, ch)['frame']['arrive_s']['source'] == 'channel'
    p.frame.arrive_s = 0.8
    assert variables(p, ch)['frame']['arrive_s']['source'] == 'project'


@pytest.fixture
def stored(monkeypatch):
    p = Project(id='project', idea='', title='Episode', channel_id='channel')
    ch = Channel(id='channel', name='Example')
    monkeypatch.setattr(main, '_load', lambda pid: p)
    monkeypatch.setattr(main.channels, 'load_or_none', lambda cid: ch)
    saved = []
    monkeypatch.setattr(main.store, 'save', lambda obj: saved.append(obj))
    monkeypatch.setattr(main.channels, 'save', lambda obj: saved.append(obj))
    return p, ch, saved


def test_patch_scene_and_slate_cache(stored):
    p, ch, saved = stored
    old = render._slate_key(p, 'outro')
    before = scenes.context_base(p)
    result = main.patch_variables(p.id, dict(scope='project', key='accent', value='#123456'))
    assert result['colors']['accent'] == dict(value='#123456', source='project', editable=True)
    ctx = scenes.context_base(p)
    assert ctx['palette']['accent'] == ctx['vars']['accent'] == '#123456'
    assert saved == [p]
    assert render._slate_channel(p).style.accent == p.style.accent
    assert render._slate_key(p, 'outro') != old
    for context in (before, ctx):
        context.update(scenes.outro_context(ch), card=ch.outro.to_dict(), kind='outro')
    assert scenes._key('cards/outro_quiet.html', before, 5, (480, 270), 15)[0] != scenes._key('cards/outro_quiet.html', ctx, 5, (480, 270), 15)[0]
    html = scenes.render_html('cards/outro_quiet.html', {**ctx, **scenes.outro_context(ch), 'card': ch.outro.to_dict(), 'kind': 'outro'})
    assert '--brand:#123456' in html and '--accent-2:' in html and '--fg:' in html


def test_copy_and_frame(stored):
    p, ch, saved = stored
    main.patch_variables(p.id, dict(scope='channel', key='subscribe', value='Keep watching'))
    ctx = scenes.context_base(p)
    assert ch.outro.cta == ctx['copy']['subscribe'] == ctx['vars']['copy.subscribe'] == 'Keep watching'
    assert saved == [ch]
    main.patch_variables(p.id, dict(scope='project', key='arrive_s', value=0.9))
    assert scenes.context_base(p)['frame']['arrive_s'] == 0.9
    main.patch_variables(p.id, dict(scope='project', key='arrive_s', value=None))
    assert p.frame.arrive_s == ch.frame.arrive_s


@pytest.mark.parametrize('patch', [
    dict(scope='project', key='bg', value='#123456'),
    dict(scope='project', key='accent', value='red'),
    dict(scope='project', key='arrive_s', value=float('nan')),
    dict(scope='project', key='overlays_per_hook', value=1.5),
    dict(scope='project', key='subscribe', value='wrong owner'),
    dict(scope='bad', key='accent', value='#123456'),
    dict(scope='project', key='unknown', value=1),
])
def test_reject_bad_patch(stored, patch):
    p, ch, saved = stored
    with pytest.raises(HTTPException) as exc:
        main.patch_variables(p.id, patch)
    assert exc.value.status_code == 400
    assert not saved

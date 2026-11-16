"""Themes built in the app: checks, storage, the sample picture and the API."""
import pytest

from app import themes, user_themes


def draft(**changes):
    return {**themes.theme('arcade'), 'label': 'Night Shift', **changes}


def test_clean_keeps_only_valid_choices():
    theme = user_themes.clean(draft(ground='#f4ead8', icons=['key', 'nope', 'key', 'rocket'], pattern='plaid',
                                    grade='sepia', intro='missing', frame={'punch_max': 9}, extra=1))
    assert theme['ground'] == '#F4EAD8' and theme['light'] is True
    assert theme['icons'] == ['key', 'rocket'] and theme['pattern'] == 'icons' and theme['grade'] == 'neutral'
    assert theme['intro'] == themes.THEMES[0]['intro'] and theme['frame'] == {} and 'extra' not in theme
    assert set(themes.THEMES[0]) - {'key'} <= set(theme)
    with pytest.raises(ValueError):
        user_themes.clean(draft(label='  '))
    with pytest.raises(ValueError):
        user_themes.clean(draft(accent='red'))


def test_save_edit_delete_and_listing():
    saved = user_themes.save(draft())
    assert saved['key'].startswith('_mine/') and saved['mine']
    assert themes.theme(saved['key'])['label'] == 'Night Shift' and saved['key'] in themes.theme_keys()
    again = user_themes.save(draft(label='Late Shift'), saved['key'])
    assert again['key'] == saved['key'] and [t['label'] for t in user_themes.all_themes()] == ['Late Shift']
    for bad in ('_mine/../../x', 'archive', '_mine/000000000000'):
        with pytest.raises(ValueError):
            user_themes.save(draft(), bad)
    user_themes.delete(saved['key'])
    assert user_themes.all_themes() == [] and themes.theme(saved['key'])['key'] == 'archive'


@pytest.mark.parametrize('pattern', user_themes.PATTERNS)
def test_sample_draws_every_pattern(pattern):
    png = user_themes.sample(draft(pattern=pattern, label=''), 'Under the Street')
    assert png.startswith(b'\x89PNG') and len(png) > 2000


def test_api_builds_applies_and_reports_uses():
    from app import main

    saved = main.save_theme({'theme': draft()})
    assert any(t['key'] == saved['key'] for t in main.list_themes())
    cid = main.create_channel({'name': 'Theme builder'})['id']
    applied = main.apply_theme(cid, {'key': saved['key'], 'templates': True})
    assert applied['style']['theme'] == saved['key'] and applied['style']['accent'] == saved['accent']
    assert main.theme_uses(saved['key']) == {'channels': ['Theme builder']}
    assert main.theme_sample({'theme': draft(), 'name': 'x'}).media_type == 'image/png'
    assert main.theme_icon('key', '#888888').body.startswith(b'\x89PNG')
    main.delete_theme(saved['key'])
    # The channel still loads, on the default ground, with the colours it took.
    style = main.get_channel(cid)['style']
    assert style['accent'] == saved['accent'] and style['theme'] == 'archive'


def test_theme_carries_how_graphics_are_drawn():
    from app import blocks, main, scenes

    theme = user_themes.clean(draft(blocks={'radius': 14, 'panel_opacity': .6, 'border': 3, 'weight': 'heavy',
                                            'pace': 1.3, 'border_colour': 'red', 'font_display': 'No such font'}))
    assert theme['blocks'] == {'radius': 14, 'panel_opacity': .6, 'border': 3, 'weight': 'heavy'}
    assert user_themes.sample(draft(blocks=theme['blocks'])).startswith(b'\x89PNG')
    saved = main.save_theme({'theme': draft(blocks=theme['blocks'])})
    cid = main.create_channel({'name': 'Rounded'})['id']
    main.patch_channel(cid, {'style': {'block_theme': {'pace': 1.2}}})
    applied = main.apply_theme(cid, {'key': saved['key'], 'templates': False})
    # The theme's choices land on the channel; a setting it does not hold is kept.
    assert applied['style']['block_theme'] == {'pace': 1.2, **theme['blocks']}
    with pytest.raises(Exception):
        main.patch_channel(cid, {'style': {'block_theme': {'border': 99}}})
    restored = main.patch_channel(cid, {'style': {'block_theme': {'pace': 1.2}}})
    assert restored['style']['block_theme'] == {'pace': 1.2}


def test_block_css_only_changes_when_asked():
    from app import blocks, scenes

    ref = next(r for r in blocks.discover() if r.endswith('lower_third_underline'))
    def html(theme):
        template, ctx = blocks.prepare(ref, theme=theme)
        return scenes.env.get_template('_block_theme.html').render(**ctx)
    plain = html({})
    assert 'outline:' not in plain and '--panel:var(--panel-solid)' in plain
    styled = html({'panel_opacity': .5, 'border': 4})
    assert 'var(--panel-solid) 50%,transparent' in styled and 'outline:4px solid var(--line)' in styled

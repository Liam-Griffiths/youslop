"""Block-only inheritance, rendering inputs and selective cache invalidation."""
import pytest

from app import block_authoring, block_library, block_overlays, block_theme, blocks, channels, render, scenes
from app.schema import Channel, Project, new_project
from app.variables import apply, variables


def test_inherit_reset_and_roundtrip(project, monkeypatch):
    channel = Channel(id='theme', name='Theme')
    channel.style.block_theme = dict(accent='#3DFFDC', font_display='EB Garamond', radius=12)
    project.channel_id = channel.id
    monkeypatch.setattr(channels, 'load_or_none', lambda _: channel)
    apply(project, channel, 'project', 'block.accent', '#FF3366')
    tokens = variables(project)['block']
    assert tokens['accent'] == dict(value='#FF3366', source='project', editable=True)
    assert tokens['font_display'] == dict(value='EB Garamond', source='channel', editable=True)
    assert tokens['radius'] == dict(value=12, source='channel', editable=True)
    assert Project.from_dict(project.to_dict()).style.block_theme == project.style.block_theme
    assert Channel.from_dict(channel.to_dict()).style.block_theme == channel.style.block_theme
    assert new_project('Idea', channel=channel).style.block_theme == {}
    assert Project.from_dict({'id': 'old', 'idea': ''}).style.block_theme == {}
    apply(project, channel, 'project', 'block.accent', None)
    assert variables(project)['block']['accent']['source'] == 'channel'
    assert channel.style.block_theme['accent'] == '#3DFFDC'


@pytest.mark.parametrize('key,value', [('font_display', 'remote font'), ('radius', 33),
    ('radius', True), ('pace', float('nan')), ('pace', .6), ('weight', '900'),
    ('bg', ''), ('ink', 'red'), ('unknown', 1)])
def test_invalid(project, key, value):
    with pytest.raises(ValueError):
        apply(project, None, 'project', 'block.' + key, value)
    assert project.style.block_theme == {}


def test_contrast_and_preview(project):
    project.style.block_theme = dict(ink='#111111', bg='#111111', accent='#111111', panel='#111111')
    tokens = variables(project)['block']
    assert 'ink on bg' in tokens['ink']['warning'] and 'ink on panel' in tokens['ink']['warning']
    assert 'accent on bg' in tokens['accent']['warning']
    theme = block_theme.values(project)
    assert any('needs 4.5:1' in e for e in block_authoring.check('title_card', theme=theme, static_only=True))
    item = blocks.discover()['title_card']
    assert block_library.signature(item, theme) != block_library.signature(item)
    theme.update(ink='#FFFFFF', bg='#101010', accent='#FF3366', panel='',
                 font_display='EB Garamond', radius=12, pace=1.3, weight='bold')
    template, ctx = blocks.prepare('title_card', theme=theme)
    html = scenes.render_html(template, ctx)
    assert ctx['vars']['accent'] == '#FF3366'
    assert '--font-display:"EB Garamond"!important' in html
    assert '--radius:12px' in html and '--block-pace:1.3' in html
    assert '--weight-display:700' in html
    assert block_authoring.check('title_card', theme=theme, static_only=True) == []


def test_pack_font_allowlist(monkeypatch):
    from app import packs
    class Pack:
        def fonts(self):
            return [dict(ref='demo/test.ttf')]
    monkeypatch.setattr(packs, 'scan', lambda: [Pack()])
    assert block_theme.validate('font_body', 'pack:demo/test.ttf') == 'pack:demo/test.ttf'
    assert scenes.context_base()['fonts']['pack:demo/test.ttf'] == '/fonts/packs/demo/test.ttf'


@pytest.mark.parametrize('source', ['.x{color:#f00}', '.x{background:rgb(0,0,0)}',
    '.x{border:1px solid white}', '.x{font-family:Inter}', '.x{font:44px Inter}',
    '.x{border-radius:2px}'])
def test_token_lint(source):
    assert block_authoring.token_lint('<style>' + source + '</style>')
    assert not block_authoring.token_lint('<style>.x{color:var(--ink,#fff);font:44px var(--font-body,Inter);border-radius:var(--radius,4px)}</style>')


def test_cache_scope(project, monkeypatch):
    monkeypatch.setattr(render, '_segment_graph', lambda *a, **k: ([], 'null[v]', '[v]'))
    monkeypatch.setattr(render.ffutil, 'h264', lambda *a, **k: ([], '', []))
    channel = Channel(id='theme', name='Theme')
    project.channel_id = channel.id
    monkeypatch.setattr(channels, 'load_or_none', lambda _: channel)
    groups = render._picture_groups(project, render._slide_durations(project, False))
    settings = dict(seg_len=9, op='set', channel=channel, chapter=None, size=(480,270),
                    fps=15, dip_out=False, camera_index=0, last_line=False, crf=18, preset='veryfast')
    def keys():
        return (render._proxy_key(project, groups, 0, channel),
                render._segment_key(project, groups[0], settings))
    slide = groups[0][0][0]
    for mode in ('photo', 'cue', 'overlay'):
        slide.cues = {'blocks': [dict(block='title_card', vars={})]} if mode == 'cue' else {}
        slide.overlays = [dict(id='name', block_id='lower_third_panel', vars={}, at=0., dur=3.,
                               position='bottom_left')] if mode == 'overlay' else []
        before = keys()
        project.style.block_theme['accent'] = '#FF3366'
        after = keys()
        assert (before == after) == (mode == 'photo')
        before = after
        channel.style.block_theme['radius'] = 12
        after = keys()
        assert (before == after) == (mode == 'photo')
        project.style.block_theme.clear()
        channel.style.block_theme.clear()
    item = slide.overlays[0]
    before = block_overlays.clip(project, item, (480,270), 15, channel, prepare_only=True)
    project.style.block_theme['accent'] = '#FF3366'
    assert before != block_overlays.clip(project, item, (480,270), 15, channel, prepare_only=True)

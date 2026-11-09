"""Generic screen contracts, bounded input, syntax safety and number honesty."""
from pathlib import Path

import pytest

from app import block_authoring, block_library, blocks, check, screen_blocks, scenes


@pytest.mark.parametrize('ref', screen_blocks.IDS)
@pytest.mark.parametrize('aspect', ['16:9','9:16'])
def test_screen_contract(ref, aspect):
    meta = blocks.discover()[ref]['meta']
    assert meta['default_colors'] == blocks.discover()['title_card']['meta']['default_colors']
    assert block_authoring.check(ref,static_only=True) == []
    theme = dict(bg='#F5F5F5',ink='#151515',panel='#FFFFFF',line='#CCCCCC',dim='#454545',accent='#993300',accent2='#335588',pace=1.4,radius=12)
    template, ctx = blocks.prepare(ref,aspect=aspect,theme=theme)
    html = scenes.render_html(template,ctx)
    assert not scenes.lint(html,asset_root=ctx['block_assets_root'])
    assert ('data-capture="frames"' in html) == (ref in ('search_box','code_typing'))
    assert ctx['vars']['accent'] == '#993300'
    assert not block_authoring.token_lint(Path('static/blocks/chat_thread/screens_base.html').read_text())


@pytest.mark.parametrize('ref,values', [
    ('chat_thread',{'rows':[]}), ('chat_thread',{'rows':[dict(sender='a',text='b')]*5}),
    ('notification_stack',{'rows':[dict(label='a',text='b'*81)]}),
    ('post_card',{'rows':[dict(label='Readers',value=-1)]}),
    ('post_card',{'rows':[dict(label='Readers',value=1.5)]}),
    ('flow_steps',{'rows':[dict(label='a')]*6}),
    ('code_typing',{'code':'a\n'*5}), ('code_diff',{'before':'a\nb'}),
])
def test_invalid_screens_fail_before_capture(ref, values):
    with pytest.raises(ValueError):
        blocks.prepare(ref,values)


def test_code_tokens_escape_and_counts_are_readable():
    template, ctx = blocks.prepare('code_typing',{'code':'print("<script>") # note'})
    assert ''.join(t['text'] for t in ctx['screens']['tokens']) == 'print("<script>") # note'
    assert {'keyword','literal','note'} <= {t['kind'] for t in ctx['screens']['tokens']}
    html = scenes.render_html(template,ctx)
    assert '&lt;script&gt;' in html
    _, ctx = blocks.prepare('post_card')
    assert ctx['screens']['rows'][0]['display'] == '12,480'
    paragraph = dict(id='p',start=0,narration='We reached 12480 readers.',block_cues=[dict(block='post_card',vars={})])
    assert check.number_match({'paragraphs':[paragraph]},None,None) == []
    paragraph['narration'] = 'We reached 999 readers.'
    assert check.number_match({'paragraphs':[paragraph]},None,None)[0].code == 'number_match'


def test_shared_screen_base_invalidates_posters(monkeypatch, tmp_path):
    item = blocks.discover()['code_diff']
    original = block_library.signature(item)
    monkeypatch.setattr(screen_blocks,'__file__',str(tmp_path/'layout.py'))
    (tmp_path/'layout.py').write_text('changed layout')
    assert block_library.signature(item) != original

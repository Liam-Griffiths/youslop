"""Channel contracts and local media validation without browser or encoding."""
import json
from pathlib import Path

import pytest

from app import blocks, core_channel_blocks as channel, scenes


@pytest.mark.parametrize('ref', channel.IDS)
@pytest.mark.parametrize('aspect', ['16:9', '9:16'])
def test_channel_defaults_and_maximum_copy(ref, aspect):
    meta = blocks.discover()[ref]['meta']
    maximum = json.loads((blocks.BUILTIN_DIR/ref/'sample-max.json').read_text())
    assert set(meta['aspects']) == {'16:9', '9:16'} and meta['budget'] == 0
    for values in ({}, maximum):
        template, ctx = blocks.prepare(ref, values, aspect)
        html = scenes.render_html(template, ctx)
        assert not scenes.lint(html, asset_root=ctx['block_assets_root'])
        assert 'data-capture="frames"' not in html
        assert 'font:44px/62px' in html and 'scrollHeight <= el.clientHeight' in html
        d = ctx['channel_block']
        assert d['x'] >= ctx['width']*.1
        assert d['x']+d['w'] <= ctx['width']*(.85 if aspect=='9:16' else .9)
        assert d['top'] >= ctx['height']*(.15 if aspect=='9:16' else .1)
        if ref == 'sponsor_long':
            slots = d['slots']
            assert len(slots) == (4 if values else 2)
            assert all(Path(s['path']).is_file() for s in slots)
            for a, b in zip(slots, slots[1:]):
                assert a['start']+a['duration'] == pytest.approx(b['start'])
            assert slots[-1]['start']+slots[-1]['duration'] == ctx['duration']


@pytest.mark.parametrize('ref,values,match', [
    ('subscribe_card',dict(avatar='/static/missing.png'),'missing'),
    ('next_video',dict(picture=''),'local'),
    ('next_video',dict(picture='https://example.com/p.png'),'local'),
    ('sponsor_short',dict(logo='/static/missing.png'),'missing'),
    ('sponsor_short',dict(name='x'*65),'maxLength'),
    ('sponsor_short',dict(url='x'*121),'maxLength'),
    ('sponsor_short',dict(code='x'*33),'maxLength'),
    ('sponsor_long',dict(media=[]),'picture slots'),
    ('sponsor_long',dict(media=[dict(src='/static/missing.png')]),'two to four'),
    ('sponsor_long',dict(media=[dict(src='/static/missing.png')]*5),'four slots'),
    ('sponsor_long',dict(media=[dict(src='/static/missing.png')]*2),'missing'),
    ('sponsor_long',dict(media=[dict(src='/static/blocks/sponsor_long/sample.png',kind='video')]*2),'picture slots'),
    ('sponsor_long',dict(media=[dict(src='/static/blocks/sponsor_long/sample.png',focal_x=True)]*2),'focal'),
    ('sponsor_long',dict(media=[dict(src='/static/blocks/sponsor_long/sample.png',caption='x'*121)]*2),'caption'),
])
def test_invalid_channel_inputs_fail_before_capture(ref, values, match, monkeypatch):
    monkeypatch.setattr(blocks.scene_builder, 'render', lambda *a, **k: pytest.fail('builder invoked'))
    with pytest.raises(ValueError, match=match):
        blocks.render(ref, values)


def test_beats_confidence_channel_tokens_and_escaping():
    context = scenes.context_base()
    context['vars'].update(bg='#102030', ink='#ECECEC', accent='#AABBCC')
    context.update(take=dict(words=[dict(w='Fieldwork', start=1, src='est'),
                                    dict(w='Studio', start=1.2, src='est')]),
                   word_offset=.2, beats=dict(link=7.9))
    template, ctx = blocks.prepare('sponsor_short', dict(learn='<script>alert(1)</script>'), seconds=8, context=context)
    assert ctx['beats']['brand'] == 1.2 and ctx['beat_sources']['brand'] == 'est'
    assert ctx['beats']['link'] == 7.9 and ctx['channel_block']['beats']['link'] == 7
    assert ctx['beat_sources']['link'] == 'explicit'
    assert ctx['vars']['bg'] == '#102030' and ctx['vars']['ink'] == '#ECECEC'
    assert '&lt;script&gt;' in scenes.render_html(template, ctx)
    template, ctx = blocks.prepare('subscribe_card', dict(avatar=''), context=context)
    assert ctx['vars']['accent'] == '#AABBCC'
    html = scenes.render_html(template, ctx)
    assert 'data-media=' not in html and 'Subscribe' in html


def test_native_media_changes_invalidate_context(tmp_path):
    picture = tmp_path/'p.png'
    picture.write_bytes(b'one')
    context = scenes.context_base()
    context['asset_roots'] = dict(project_root=str(tmp_path))
    values = dict(picture='/scene/{token}/project/p.png')
    _, first = blocks.prepare('next_video', values, context=context)
    picture.write_bytes(b'changed image')
    _, second = blocks.prepare('next_video', values, context=context)
    assert first['channel_block']['media_versions'] != second['channel_block']['media_versions']

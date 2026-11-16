"""Visibility graphs and cache variants, with no captures or media encodes."""
from copy import deepcopy
import pickle
from types import SimpleNamespace

from app import audio, block_overlays, cuts, layers, main, render, stages, store, undo
from app.schema import Layer
from tests.unit.test_clip_projects import clip_project


def test_ids_alias_precedence_fallback_and_worker_pickle(project):
    project.style.format = 'essay'
    assert 'captions' in layers.visibility(project, {'titles'})
    project.layers = [Layer(id='titles', role='graphics'), Layer(id='words', role='captions')]
    hidden = layers.visibility(project, {'titles'})
    assert hidden.item('graphics') and not hidden.item('captions')
    assert 'captions' in layers.visibility(project, {'role:titles'})
    assert main._preview_hide('titles,words', project) == {'titles', 'words'}
    assert pickle.loads(pickle.dumps(hidden)).item('graphics', 'missing')


def test_per_item_graphics_anchors_titles_and_cache(project, monkeypatch, tmp_path):
    slide = project.slides[0]
    project.layers = [Layer(id='off', hidden=True), Layer(id='on', order=1),
                      Layer(id='off-title', role='titles', hidden=True)]
    slide.take = dict(duration=4, words=[dict(w='name', start=i, end=i+.4) for i in (1,2)])
    slide.overlays = [dict(id=str(i), block_id='lower_third_panel', vars={}, at=0, dur=1,
        on='name', layer=track) for i,track in enumerate(('off','on'))]
    slide.title_layer = 'off-title'
    hidden, before, calls = layers.visibility(project), deepcopy(project.to_dict()), []
    monkeypatch.setattr(block_overlays, 'clip', lambda p,item,*a,**k: calls.append(item) or tmp_path/'plate')
    group = [(slide,4)]
    block_overlays.compose(project, group, ['-i','base'], '[0:v]null[base]', '[base]',
                           (480,270), 15, hide=hidden)
    assert [(c['id'],c['at']) for c in calls] == [('1',2)]
    monkeypatch.setattr(render.titles, 'render_title', lambda *a,**k: None)
    _, graph, _ = render._segment_graph(project,group,5,'set',hide=hidden)
    assert '[ttl' not in graph
    plain = stages.render_signature(project)
    assert not layers.visibility(project, final=True)
    project.hide_in_render = True
    assert stages.render_signature(project) != plain
    assert layers.visibility(project, final=True) == hidden
    project.hide_in_render = False
    groups = render._groups_for_preview(project)
    key = render._proxy_key(project,groups,0,None)
    slide.overlays[1]['layer'] = 'off'
    assert key != render._proxy_key(project,groups,0,None)
    slide.overlays[1]['layer'] = 'on'
    assert project.to_dict() == before


def test_voice_mutes_after_concat_without_timing_or_storage_changes(project, monkeypatch, tmp_path):
    project.layers = [Layer(id='speech', role='voice', hidden=True)]
    before, commands = deepcopy(project.to_dict()), []
    monkeypatch.setattr(audio.ffutil,'run',lambda args,**kw: commands.append(args))
    monkeypatch.setattr(audio.ffutil,'duration',lambda *a: 12)
    audio.build_narration(project,tmp_path/'voice.wav',lead_in=1,hide=layers.visibility(project))
    muted = commands[-1][commands[-1].index('-filter_complex')+1]
    audio.build_narration(project,tmp_path/'default.wav',lead_in=1)
    plain = commands[-1][commands[-1].index('-filter_complex')+1]
    assert muted == plain.replace('a=1[out]', 'a=1[voiced];[voiced]volume=0[out]')
    assert project.to_dict() == before


def test_saved_visibility_and_export_setting_undo_redo(project, monkeypatch, tmp_path):
    monkeypatch.setattr(store,'PROJECTS_DIR',tmp_path)
    store.save(project)
    token = undo.edit_source.set(('hide pictures', ''))
    try:
        main.patch_layer_flags(project.id,'pictures',{'hidden':True})
        main.patch_project(project.id,{'hide_in_render':True})
    finally:
        undo.edit_source.reset(token)
    root = store.project_dir(project.id)
    assert store.load(project.id).hide_in_render
    undo.restore(root,'undo')
    assert not store.load(project.id).hide_in_render
    assert 'pictures' in layers.visibility(store.load(project.id))
    undo.restore(root,'undo')
    assert 'pictures' not in layers.visibility(store.load(project.id))
    undo.restore(root,'redo'); undo.restore(root,'redo')
    assert 'pictures' in layers.visibility(store.load(project.id),final=True)


def test_stings_channel_wrapped_outro_and_assignment_cache(project, monkeypatch, tmp_path):
    from app import channels
    project.channel_id = 'channel'
    project.layers = [Layer(id='off',role='stings',hidden=True),Layer(id='on',role='stings',order=1),
                      Layer(id='bed-off',role='music',hidden=True),Layer(id='bed-on',role='music',order=1)]
    intro, outro = deepcopy(project.intro), deepcopy(project.outro)
    intro.music, intro.music_layer = 'in.wav', 'on'
    outro.sting, outro.sting_layer = 'out.wav', 'off'
    for name in ('in.wav','out.wav'): (tmp_path/name).write_bytes(b'sting')
    monkeypatch.setattr(channels,'load_or_none',lambda ident: SimpleNamespace(id='channel',intro=intro,outro=outro) if ident else None)
    monkeypatch.setattr(channels,'channel_dir',lambda *a: tmp_path)
    assert set(layers.visible_stings(project,render._stings_for(project),())) == {'intro'}
    monkeypatch.setattr(render,'_slate_has',lambda *a: False)
    project.channel_id = ''
    lay = render._layout(project)
    key = render._mix_key(project,lay)
    project.music_layer = 'bed-on'
    assert key != render._mix_key(project,lay)


def test_clip_visibility_preserves_source_spans_and_default_export(clip_project, monkeypatch):
    from app import clip_render
    project, _ = clip_project
    monkeypatch.setattr(render.ffutil,'dimensions',lambda *a:(1920,1080))
    _, original, seconds = clip_render.graph(project)
    project.layers = [Layer(id=r,role=r,hidden=True) for r in ('pictures','voice')]
    _, hidden, kept = clip_render.graph(project)
    assert seconds == kept and '[0:v]' not in hidden and '[0:a]' not in hidden
    assert 'color=c=black' in hidden and 'anullsrc' in hidden
    assert clip_render.graph(project,hide=layers.visibility(project,final=True))[1] == original
    assert not clip_render.mix(project)['audible']
    assert clip_render.state(project,'mix')['path'] != clip_render.state(project,'mix',layers.visibility(project,final=True))['path']


def test_cue_screens_keep_original_spans_and_filter_each_track(project):
    from app.cuts import flameboat_scene
    project.style.format = 'flameboat'
    slide = project.slides[0]
    slide.cues['flameboat'] = [dict(kind='title',text='Hidden',at=0,layer='off'),
                              dict(kind='title',text='Visible',at=2,layer='on')]
    project.layers = [Layer(id='off',role='cues',hidden=True),Layer(id='on',role='cues',order=1)]
    ctx = cuts.make_ctx(project,(480,270),15)
    beat = cuts.beat_for(cuts.flameboat,ctx,slide,4,0,4,scene=True)
    plain = flameboat_scene.context(project,ctx,[beat],[None])['screens']
    shown = flameboat_scene.context(project,ctx,[beat],[None],hide=layers.visibility(project))['screens']
    assert [s['hidden'] for s in shown] == [True,False]
    assert [(s['start'],s['duration']) for s in plain] == [(s['start'],s['duration']) for s in shown]


def test_hidden_sponsor_and_slate_proxies_keep_timeline_spans(project,monkeypatch,tmp_path):
    from app.schema import SponsorSlot
    project.sponsors = [SponsorSlot(id='read',script='Sponsor read',take={'duration':3})]
    project.layers = [Layer(id=r,role=r,hidden=True) for r in ('pictures','sponsors')]
    monkeypatch.setattr(render,'_slate_state',lambda *a: dict(length=4))
    monkeypatch.setattr(render,'_blank_video',lambda out,*a: out.write_bytes(b'blank'))
    monkeypatch.setattr(render,'_sponsor_preview',lambda *a: (_ for _ in ()).throw(AssertionError('visible sponsor prepared')))
    for ref,seconds in [('intro',4),('sponsor:read',3)]:
        result = render.proxy_ref(project,ref)
        assert f'{seconds:.6f}' in result['path'] and result['ready']

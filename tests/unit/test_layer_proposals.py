"""Layer proposals and role movement: synthetic projects, no model or render."""
from copy import deepcopy
import pytest
from app import layer_proposals as proposals, layers, llm, main, store, undo
from app.edits import EditError
from app.schema import Layer, Project, Slide

ENTRIES = [dict(name=name, role=role, why='Keep the edit readable.') for name, role in
           [('Maps', 'graphics'), ('Labels', 'titles'), ('Sound', 'music')]]


@pytest.fixture
def episode(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: deepcopy(ENTRIES))
    p = Project(id='pproposal', idea='A synthetic river', slides=[Slide(id='a',
        narration='The river crosses a map.', title='River', title_at=.5,
        overlays=[dict(id='map', block_id='lower_third_panel', vars={}, at=0, dur=1, on='river')])])
    store.save(p)
    return p


def test_validation_and_failure(episode, monkeypatch):
    assert proposals.validate(ENTRIES + [dict(name='Unknown', role='bogus', why='No')]) == ENTRIES
    for bad in (None, {}, [], ENTRIES[:2], [dict(e, name='x'*25) for e in ENTRIES], ENTRIES*3):
        with pytest.raises(ValueError): proposals.validate(bad)
    def fail(*a, **kw): raise llm.LLMError('offline')
    monkeypatch.setattr(llm, 'complete_json', fail)
    messages = []
    assert proposals.suggest(episode.id, messages.append) == {}
    assert not store.load(episode.id).layer_proposal and 'offline' in messages[-1]


def test_apply_assignments_history_dismiss_and_stale(episode, monkeypatch):
    p = episode
    assert proposals.suggest(p.id, lambda _: None)
    p = store.load(p.id)
    before = p.to_dict()
    token = undo.edit_source.set(('apply layer proposal', 'one'))
    try: main.manage_layers(p.id, dict(op='apply_proposal', proposal=p.layer_proposal['id']))
    finally: undo.edit_source.reset(token)
    fresh = store.load(p.id)
    assert {'pictures', 'voice', 'graphics', 'titles'} <= {t.role for t in fresh.layers}
    for role, owner, key in layers._bindings(fresh):
        assert owner[key] == layers.resolve(fresh.layers, role).id
    assert fresh.slides[0].title_at == .5 and fresh.slides[0].overlays[0]['on'] == 'river'
    assert undo.read(store.project_dir(p.id))['cursor'] == 1
    undo.restore(store.project_dir(p.id), 'undo')
    p = store.load(p.id)
    assert p.layers == [] and p.layer_proposal == before['layer_proposal']
    p.title = 'Creator edit'; store.save(p)
    with pytest.raises(EditError, match='Project changed'):
        main.manage_layers(p.id, dict(op='apply_proposal', proposal=p.layer_proposal['id']))
    main.manage_layers(p.id, dict(op='dismiss_proposal', proposal=p.layer_proposal['id']))
    assert not store.load(p.id).layer_proposal


def test_concurrent_model_edits_and_locks(episode, monkeypatch):
    def reply(*a, **kw):
        # Another thread must be able to acquire the lock during the call.
        import concurrent.futures
        def edit():
            with store.lock_for(episode.id):
                p = store.load(episode.id); p.title = 'Concurrent'; store.save(p)
        with concurrent.futures.ThreadPoolExecutor() as pool: pool.submit(edit).result(timeout=1)
        return ENTRIES
    monkeypatch.setattr(llm, 'complete_json', reply)
    assert not proposals.suggest(episode.id, lambda _: None)
    assert store.load(episode.id).title == 'Concurrent'
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: ENTRIES)
    p = store.load(episode.id); p.layers = [Layer(id='g', locked=True)]; store.save(p)
    proposals.suggest(p.id, lambda _: None)
    p = store.load(p.id)
    with pytest.raises(layers.LockedLayerError):
        main.manage_layers(p.id, dict(op='apply_proposal', proposal=p.layer_proposal['id']))


@pytest.mark.parametrize('role', ['titles', 'cues', 'music', 'stings', 'captions', 'chapters', 'sponsors', 'notes'])
def test_role_moves_pin_reorder_and_keep_content(episode, monkeypatch, role):
    p = episode
    p.layers = [Layer(id='old', role=role), Layer(id='new', role=role, order=1)]
    p.music = 'bed.wav'
    p.style.format = 'flameboat' if role == 'cues' else 'kenburns'
    # Derived/external spans are synthetic; reference/timing semantics remain real.
    item = dict(id='a:0' if role == 'cues' else 'intro' if role == 'stings' else 'a',
                sid='a' if role in {'titles', 'cues'} else '', kind='cue' if role == 'cues' else 'title',
                t0=.5, t1=1.5, cue=0)
    monkeypatch.setattr(layers, 'role_items', lambda *a, **kw: {r: [deepcopy(item)] if r == role else [] for r in layers.LAYER_ROLES})
    for index in (0, 1):
        locked = deepcopy(p); locked.layers[index].locked = True
        with pytest.raises(layers.LockedLayerError):
            layers.manage(locked, dict(op='move_item', role=role, item=item['id'], sid=item['sid'], to='new'))
    store.save(p)
    original = deepcopy(p.slides[0].to_dict())
    token = undo.edit_source.set(('move item to layer', role))
    try: main.manage_layers(p.id, dict(op='move_item', role=role, item=item['id'], sid=item['sid'], to='new'))
    finally: undo.edit_source.reset(token)
    p = store.load(p.id)
    assert undo.read(store.project_dir(p.id))['cursor'] == 1
    undo.restore(store.project_dir(p.id), 'undo')
    assert store.load(p.id).layer_defaults == {}
    undo.restore(store.project_dir(p.id), 'redo')
    p = store.load(p.id)
    if role == 'titles': assert p.slides[0].title_layer == 'new'
    elif role == 'cues': assert p.slides[0].cues['flameboat'][0]['layer'] == 'new'
    elif role == 'music': assert p.music_layer == 'new'
    elif role == 'stings': assert p.layer_defaults['stings:intro'] == 'new'
    else: assert p.layer_defaults[role] == 'new'
    assert all(p.slides[0].to_dict()[k] == original[k] for k in ('take', 'title_at', 'title_hold', 'overlays'))
    ids = [r['id'] for r in layers.rows(p)]
    layers.manage(p, dict(op='reorder', ids=ids[::-1]))
    if role in {'captions', 'chapters', 'sponsors', 'notes'}:
        assert next(r for r in layers.rows(p) if r['items'])['id'] == 'new'
        next(t for t in p.layers if t.id == 'new').hidden = True
        assert layers.visibility(p).item(role)


def test_automatic_cues_and_channel_stings(episode, monkeypatch):
    from types import SimpleNamespace
    from app import cuts, render
    p = episode
    p.style.format = 'flameboat'
    p.layers = [Layer(id='old', role='cues'), Layer(id='new', role='cues', order=1)]
    original = cuts.cues_for(cuts.BY_KEY['flameboat'], p.slides[0])
    item = layers.role_items(p)['cues'][0]
    layers.manage(p, dict(op='move_item', role='cues', item=item['id'], sid='a', to='new'))
    assert p.slides[0].cues['flameboat'] == [dict(c, **({'layer':'new'} if i == 0 else {})) for i,c in enumerate(original)]
    p.slides[0].cues['flameboat'][0].update(on='river', at=.2)
    layers.manage(p, dict(op='move_item', role='cues', item=item['id'], sid='a', to='old'))
    assert p.slides[0].cues['flameboat'][0]['on'] == 'river' and p.slides[0].cues['flameboat'][0]['at'] == .2
    p.channel_id = 'shared'
    p.layers = [Layer(id='old', role='stings'), Layer(id='new', role='stings', order=1)]
    spec = SimpleNamespace(music_layer='old')
    monkeypatch.setattr(render, '_stings_for', lambda *a: {'intro': ('sound.wav', spec)})
    monkeypatch.setattr(layers, 'role_items', lambda *a, **kw: {r: [dict(id='intro', sid='', layer=layers.sting_layer(p, 'intro', spec))] if r == 'stings' else [] for r in layers.LAYER_ROLES})
    layers.manage(p, dict(op='move_item', role='stings', item='intro', sid='', to='new'))
    assert spec.music_layer == 'old' and p.layer_defaults['stings:intro'] == 'new'
    assert layers.sting_layer(p, 'intro', spec) == 'new'


def test_vertical_gestures_and_horizontal_handoff(tmp_path):
    import shutil, subprocess
    from pathlib import Path
    runtime = shutil.which('gjs')
    if not runtime: pytest.skip('GJS unavailable')
    source = Path('static/js/timeline/layer_manager.js').read_text()
    harness = r'''
const check=(v,m)=>{if(!v)throw Error(m);}, handlers={}, calls=[];
const document={addEventListener(k,fn){handlers[k]=fn;},removeEventListener(k){delete handlers[k];}};
const old={dataset:{track:'old',role:'titles'},getBoundingClientRect:()=>({top:0,bottom:30})};
const next={dataset:{track:'next',role:'titles'},getBoundingClientRect:()=>({top:30,bottom:60})};
let horizontal=0, forwarded=0, allowed=true;
const node={dataset:{layer:'titles',item:'0'},style:{},closest:()=>old,
 onpointerdown(){horizontal++;TL.drag={timing:true};node.onpointermove=()=>forwarded++;}};
const track={querySelectorAll:s=>s==='[data-track]'?[old,next]:[node]}, $=()=>track;
const TL={pid:'p',data:{layers:{titles:[{id:'a',sid:'a',kind:'title'}]},project_layers:[{id:'old',role:'titles'}]}};
const tlPause=()=>{},tlSelect=()=>{},tlCanEdit=()=>allowed; tlLayerRequest=payload=>calls.push(payload);
const event=(x,y)=>({button:0,clientX:x,clientY:y,target:{closest:()=>null},preventDefault(){},stopPropagation(){},stopImmediatePropagation(){}});
tlWireLayerMoves();
node.onpointerdown(event(0,10));handlers.pointermove(event(1,40));handlers.pointerup(event(1,40));
check(calls.length===1&&calls[0].to==='next'&&calls[0].role==='titles','vertical drop is one structural save');
node.onpointerdown(event(0,10));handlers.pointermove(event(20,11));
check(horizontal===1&&forwarded===1,'horizontal movement retains timing controls');TL.drag=null;
node.onpointerdown(event(0,10));handlers.pointermove(event(1,40));handlers.keydown({...event(0,0),key:'Escape'});
check(calls.length===1&&!TL.drag&&node.style.transform==='','Escape cancels without saving');
next.dataset.role='music';node.onpointerdown(event(0,10));handlers.pointermove(event(1,40));handlers.pointerup(event(1,40));
check(calls.length===1,'wrong-role drop does not save');allowed=false;
node.onpointerdown(event(0,10));check(!handlers.pointermove,'locked source cannot start a gesture');
print('role gestures passed');
'''
    script = tmp_path/'role-moves.js'; script.write_text(source + harness)
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('operation', ['initialize', 'plan', 'board', 'reimport'])
def test_finished_script_hooks(episode, monkeypatch, operation):
    from app import ops, plan_board, script_gen
    p = episode
    p.has_source = True
    p.outline = {'sections': [dict(heading='River', summary='A map', words=30, kind='main')]}
    p.slides[0].beat = 'River'; store.save(p)
    (store.project_dir(p.id)/'source.txt').write_text('Synthetic source')
    def finish(project, *a, **kw): project.status = 'scripted'
    monkeypatch.setattr(script_gen, 'generate', finish)
    monkeypatch.setattr(script_gen, 'import_script', finish)
    monkeypatch.setattr(ops.media, 'gather', lambda *a, **kw: None)
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, fn: fn(lambda _: None))
    if operation == 'board': plan_board.write(p.id, lambda _: None)
    elif operation == 'reimport': main.reimport_script(p.id, {})
    else: getattr(ops, operation)(p.id, {}, lambda _: None)
    assert store.load(p.id).layer_proposal['entries'] == ENTRIES


def test_delete_empty_default_does_not_require_moving_content(episode):
    p = episode
    p.layers = [Layer(id='empty', role='graphics'), Layer(id='used', role='graphics', order=1)]
    p.slides[0].overlays[0]['layer'] = 'used'
    p.layer_defaults['graphics'] = 'empty'
    layers.manage(p, dict(op='delete', id='empty'))
    assert 'graphics' not in p.layer_defaults and p.slides[0].overlays[0]['layer'] == 'used'

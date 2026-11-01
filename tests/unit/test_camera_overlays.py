"""Camera edit contracts; synthetic media, mocked planning, no downloads."""
from copy import deepcopy
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app import camera_auto, camera_overlays, ffutil, llm, main, render, scenes, store
from app.schema import Slide
from tests.unit.test_camera_render import camera


def setup_camera(project):
    slide = camera(project)
    slide.take.update(duration=5, cuts=[dict(a=3,b=3.5,by='hand')], overlays=[],
                      words=[dict(w='museum',start=1,end=1.5,src='est')])
    slide.candidates = [dict(id='art',local_path='art.png',kind='image',title='museum')]
    from PIL import Image
    Image.new('RGB',(160,90),'red').save(store.project_dir(project.id)/'art.png')
    return slide


def overlay(kind='cutaway', **kwargs):
    return dict(at=1,dur=1,kind=kind,source=dict(candidate_id='art'),by='hand',**kwargs)


def test_clamp_patch_and_cache(project):
    s = setup_camera(project)
    s.take['overlays'] = [overlay()]
    store.save(project)
    groups=[[(s,5)]]
    before=render._proxy_key(project,groups,0,None)
    main.patch_slide(project.id,s.id,{'camera_overlays':[dict(overlay(),at=-1,dur=8)]})
    take=store.load(project.id).slides[0].take
    assert take['overlays'][0]['at'] == 0 and take['overlays'][0]['dur'] == 4.5
    fresh=store.load(project.id)
    assert before != render._proxy_key(fresh,[[(fresh.slides[0],5)]],0,None)
    s.take['overlays']=[overlay()]
    _,graph=render._camera_source(project,s,6,(480,270),15)
    assert 'split=3' in graph  # Return from the cutaway continues the punch alternation.
    with pytest.raises(ValueError):
        camera_overlays.validate(take,[overlay(),overlay()])
    for value in (float('nan'),True,'one'):
        with pytest.raises(ValueError):
            camera_overlays.validate(take,[dict(overlay(),at=value)])


@pytest.mark.parametrize('kind',['cutaway','pip'])
def test_graph_golden(project,monkeypatch,request,kind):
    s=setup_camera(project)
    s.take['overlays']=[overlay(kind)]
    monkeypatch.setattr(ffutil,'dimensions',lambda path:(160,90))
    inputs,graph,last=camera_overlays.compose(project,s,['-i','camera.mp4'],'[0:v]null[base]',
                                             '[base]',(480,270),15)
    actual='\n'.join(inputs)+'\n'+graph+'\n'+last+'\n'
    actual=actual.replace(os.environ['CORKBORED_DATA'],'<DATA>')
    golden=Path('tests/golden')/f'camera_{kind}.txt'
    if request.config.getoption('--update-goldens'):
        golden.write_text(actual)  # New cutaway/PIP references; existing goldens stay unchanged.
    assert actual == golden.read_text()


def test_builder_scene_and_captions(project,monkeypatch,tmp_path):
    s=setup_camera(project)
    s.take['overlays']=[dict(overlay(),source=dict(template='essay/segment.html',context={}))]
    calls=[]
    monkeypatch.setattr(render.ffutil,'dimensions',lambda path:(160,90))
    monkeypatch.setattr(scenes,'_prepare',lambda *a,**k:('key',tmp_path/'scene.html',{}))
    monkeypatch.setattr(render.scenes,'caption_plates',lambda *a,**k:calls.append('captions') or tmp_path/'alpha.mov')
    from app import scene_builder
    monkeypatch.setattr(scene_builder,'render',lambda *a,**k:calls.append('builder'))
    monkeypatch.setattr(scenes,'ensure_clip',lambda *a,**k:pytest.fail('per-frame scene capture'))
    project.style.format='essay'
    inputs,graph,last=render._segment_graph(project,[(s,5)],6,'set',size=(480,270),fps=15)
    assert calls == ['builder','captions'] and 'scene.mp4' in ' '.join(inputs)
    assert 'vcaptions' in graph and 'co0' in graph


def test_auto_batch_idempotent_undo_and_scope(project,monkeypatch):
    s=setup_camera(project)
    s.take['overlays']=[dict(overlay(),at=.1,dur=.3,note='keep exactly')]
    for i in range(2):
        clone=Slide.from_dict(s.to_dict()); clone.id=f'camera{i}'
        clone.takes['camera']['overlays']=[]; clone.take=clone.takes['camera']
        project.slides.append(clone)
    s.take['cutaway_cache']=dict(text=camera_auto.hashlib.sha256(s.narration.encode()).hexdigest(),
        items=[dict(on='museum',candidate_id='art',dur=1)])
    store.save(project)
    original=deepcopy([s.takes['camera'] for s in project.slides if s.on_camera])
    prompts=[]
    def complete(prompt):
        prompts.append(prompt)
        return [dict(id=s.id,cutaways=[dict(on='museum',candidate_id='art',dur=1),
                     dict(on='museum',candidate_id='missing',dur=1)]) for s in project.slides if s.on_camera]
    monkeypatch.setattr(llm,'complete_json',complete)
    monkeypatch.setattr(camera_auto.camera,'suggest_cuts',lambda take:[dict(a=2,b=2.5),dict(a=3,b=3.5)])
    monkeypatch.setattr(camera_auto.media,'download_to',lambda *a,**k:pytest.fail('download'))
    monkeypatch.setattr(camera_auto.check,'run',lambda p:dict(findings=[]))
    preview=camera_auto.edit(project.id,{'suggest':True})
    assert not preview['changed'] and preview['proposals']
    result=camera_auto.edit(project.id,{})
    assert len(result['changed'])==3 and len(prompts)==1
    applied=store.load(project.id)
    assert all(any(c['by']=='auto' for c in s.take['cuts']) for s in applied.slides if s.on_camera)
    assert all(any(o['by']=='auto' for o in s.take['overlays']) for s in applied.slides if s.on_camera)
    assert camera_auto.edit(project.id,{})['changed']==[] and len(prompts)==1
    camera_auto.edit(project.id,dict(sid=s.id,undo=True))
    assert any(c['by']=='auto' for c in store.load(project.id).slides[-1].take['cuts'])
    camera_auto.edit(project.id,dict(undo=True))
    restored=[s.take for s in store.load(project.id).slides if s.on_camera]
    for before,after in zip(original,restored):
        assert before['cuts']==after['cuts'] and before['overlays']==after['overlays']
    camera_auto.edit(project.id,{})
    assert len(prompts)==1  # Undo retains proposals, so redo spends no model tokens.


def test_overlay_js(tmp_path):
    gjs=shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    script=tmp_path/'overlays.js'
    script.write_text(Path('static/js/timeline/camera.js').read_text()+r'''
const q={start:2,word_times:[],camera_edit:{effective_duration:5,overlays:[{at:1,dur:1,kind:'cutaway',by:'auto'}]}};
const el={dataset:{overlay:'0'},style:{},focus(){},setPointerCapture(){},hasPointerCapture(){return false;}};
const row={querySelectorAll:()=>[el]},TL={zoom:10};
const saves=[],tlFps=()=>10,tlPause=()=>{},tlDraw=()=>{},tlSnap=t=>({t});
const document={addEventListener(){},removeEventListener(){}};
const save=p=>saves.push(p);
const event=(x,key='',resize=false)=>({button:0,pointerId:1,clientX:x,key,altKey:true,
 target:{closest:()=>resize},preventDefault(){},stopPropagation(){}});
tlWireCameraOverlays(row,q,save);
el.onpointerdown(event(0));el.onpointermove(event(10));el.onpointerup();
if(saves.length!==1||saves[0].camera_overlays[0].at!==2||saves[0].camera_overlays[0].by!=='hand') throw Error('move');
el.onpointerdown(event(0,'',true));el.onpointermove(event(10));el.onpointerup();
if(saves.length!==2||saves[1].camera_overlays[0].dur!==2) throw Error('resize');
el.onpointerdown(event(0));el.onpointermove(event(20));el.onpointercancel();
if(saves.length!==2) throw Error('cancel saved');
el.onkeydown(event(0,'2'));
if(saves.at(-1).camera_overlays[0].kind!=='pip') throw Error('PIP keyboard');
el.onkeydown(event(0,'Delete'));
if(saves.at(-1).camera_overlays.length) throw Error('delete');
print('Overlay JS: move, resize, cancel, keyboard layout, Delete, hand provenance PASS');
''')
    result=subprocess.run([gjs,str(script)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr

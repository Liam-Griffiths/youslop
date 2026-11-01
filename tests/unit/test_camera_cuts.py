"""Source edit lists, synthetic ffmpeg media and plain JS; no real recordings."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from app import audio, camera, check, ffutil, main, render, store, storyboard
from app.schema import CAMERA_TRACK
from app.take_edits import cut_ranges, kept_ranges, take_duration, take_words, validate_cuts
from tests.unit.test_camera_render import camera as attach_camera


def test_complement_and_words():
    take = dict(duration=5, cuts=[dict(a=3,b=4,by='auto'), dict(a=-1,b=.5,by='hand'),
                                dict(a=1,b=2,by='hand'), dict(a=1.5,b=2.5,by='auto')],
                words=[dict(w=w,start=a,end=b,src='est') for w,a,b in
                       [('gone',.1,.3),('one',.5,.8),('clipped',.9,1.2),('two',2.5,2.9),('three',4,4.5)]])
    original = deepcopy(take)
    assert cut_ranges(take) == [(0,.5),(1,2.5),(3,4)]
    assert kept_ranges(take) == [(.5,1),(2.5,3),(4,5)]
    assert take_duration(take) == 2
    assert [(w['w'],w['start'],w['end']) for w in take_words(take)] == [
        ('one',0,.3),('two',.5,.9),('three',1,1.5)]
    assert take == original


@pytest.mark.parametrize('cuts', [None, [{}], [{'a':False,'b':1,'by':'hand'}],
    [{'a':0,'b':float('nan'),'by':'hand'}], [{'a':0,'b':5,'by':'hand'}],
    [{'a':0,'b':1,'by':'unknown'}], [{'a':-1,'b':1,'by':'auto'}]])
def test_validation(cuts):
    with pytest.raises(ValueError):
        validate_cuts({'duration':5}, cuts)


def test_edit_restore_clocks_and_keys(project):
    slide = attach_camera(project)
    slide.take['duration'] = 5
    slide.take['words'] = [dict(w='kept',start=3,end=3.2,src='est')]
    store.save(project)
    before = render.timeline(project)
    groups = render._picture_groups(project,render._slide_durations(project,True))
    later = render._proxy_key(project,groups,1,None)
    mix = render._mix_key(project,render._layout(project))
    cuts = [dict(a=1,b=2,by='hand')]
    main.patch_slide(project.id,slide.id,{'camera_cuts':cuts,'camera_punch':False})
    edited = store.load(project.id)
    sb = storyboard.build(edited)
    para = sb['paragraphs'][0]
    assert para['take']['duration'] == 4 and para['take']['words'][0]['start'] == 2
    assert check._ctx(sb).words[0][0] == para['start'] + 2
    tl = render.timeline(edited)
    assert tl['segments'][0]['paragraphs'][0]['word_times'][0]['start'] == para['start'] + 2
    assert before['total']-tl['total'] == pytest.approx(1)
    groups = render._picture_groups(edited,render._slide_durations(edited,True))
    assert render._proxy_key(edited,groups,1,None) != later
    assert render._mix_key(edited,render._layout(edited)) != mix
    # Same duration, different cut location must invalidate the audio mix too.
    main.patch_slide(project.id,slide.id,{'camera_cuts':[dict(a=2,b=3,by='auto')]})
    moved = store.load(project.id)
    assert render._mix_key(moved,render._layout(moved)) != render._mix_key(edited,render._layout(edited))
    with pytest.raises(HTTPException):
        main.patch_slide(project.id,slide.id,{'camera_cuts':[dict(a=0,b=5,by='hand')]})
    main.patch_slide(project.id,slide.id,{'camera_cuts':[]})
    restored = store.load(project.id)
    assert render.timeline(restored)['total'] == before['total']
    assert restored.slides[0].take['words'] == slide.take['words']
    assert (store.project_dir(project.id)/'camera.wav').read_bytes() == b'synthetic placeholder'


def test_suggestions_synthetic(tmp_path):
    path = tmp_path/'pauses.wav'
    ffutil.run(['-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=5',
                '-af',"volume=enable='between(t,1,2)+between(t,3,4)':volume=0",str(path)],threads=1)
    take = dict(path=str(path),duration=5)
    found = camera.suggest_cuts(take)
    assert len(found) == 2
    for r, a, b in zip(found, [1.15,3.15], [1.85,3.85]):
        assert r['a'] == pytest.approx(a,abs=.04) and r['b'] == pytest.approx(b,abs=.04)
    assert 'cuts' not in take
    assert len(camera.suggest_cuts({**take,'cuts':[{**found[0],'by':'hand'}]})) == 1


def test_sound_and_picture_ranges_and_duration(project,tmp_path):
    slide = attach_camera(project)
    root = store.project_dir(project.id)
    # Tiny synthetic sources, never process or modify the owner's media.
    ffutil.run(['-f','lavfi','-i','testsrc2=size=160x90:rate=30:duration=4',
                '-c:v','libx264','-preset','ultrafast',str(root/'source.mp4')],threads=1)
    ffutil.run(['-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4',str(root/'source.wav')],threads=1)
    slide.take.update(path='source.wav',video='source.mp4',duration=4,tail=0,
                      cuts=[dict(a=.3,b=.7,by='hand'),dict(a=1.2,b=1.7,by='auto'),dict(a=2.3,b=2.7,by='hand')])
    original = (root/'source.wav').read_bytes(),(root/'source.mp4').read_bytes()
    audio._concat_takes(project,[slide],tmp_path/'bed.wav',head=0,tail=0)
    assert ffutil.duration(tmp_path/'bed.wav') == pytest.approx(take_duration(slide.take)+audio.gap_map(project)[slide.id],abs=.001)
    inputs, graph = render._camera_source(project,slide,4,(480,270),15)
    for a,b in kept_ranges(slide.take):
        assert f':end={b:.6f}' in graph
    punch = (project.frame.punch_min + project.frame.punch_max)/2
    crop = 'crop=' + ':'.join(str(round(v*punch/2)*2) for v in (480,270))
    assert crop in graph
    slide.take['punch'] = False
    assert crop not in render._camera_source(project,slide,4,(480,270),15)[1]
    # Budget rounding uses cumulative time, so repeated joins cannot drift.
    import re
    counts = [int(n) for n in re.findall(r'trim=end_frame=(\d+)',graph)]
    lead = render.cuts.transition_for(project.style)/2 + render.cuts.head_pad_for(project,slide)
    assert sum(counts) == round((lead+take_duration(slide.take))*15)
    assert original == ((root/'source.wav').read_bytes(),(root/'source.mp4').read_bytes())


def test_camera_js(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = Path('static/js/timeline/camera.js').read_text()
    script = tmp_path/'camera.js'
    script.write_text(source + '''
const c={duration:5,words:[],cuts:[{a:0,b:1,by:'auto'},{a:2,b:3,by:'hand'}]};
const p=tlCameraPatch(c,0,.5,'start');
if(p.camera_cuts.length!==2 || p.camera_cuts[1].b!==.5 || c.cuts[0].b!==1) throw Error('trim');
if(tlCameraPatch(c,4,5).camera_cuts[2].by!=='hand') throw Error('hand');

class El {
 constructor(dataset={}) {this.dataset=dataset;this.style={};}
 append(){} remove(){} focus(){} setAttribute(){} setPointerCapture(){} hasPointerCapture(){return false;}
 getBoundingClientRect(){return {left:0,width:100};}
}
const source=new El(), restore=new El({cut:'0'}), trim=new El({trim:'start'});
const controls=Object.fromEntries(['suggest','accept','punch'].map(k=>[k,new El()]));
const row=new El({camera:'a'});
row.querySelector=s=>s==='.tl-camera-source'?source:controls[s.slice(6,-1)];
row.querySelectorAll=s=>s==='[data-cut]'?[restore]:s==='[data-trim]'?[trim]:[];
const $=()=>({querySelectorAll:()=>[row]});
const document={createElement:()=>new El()};
const TL={pid:'test'}, q={id:'a',camera_edit:c};
const tlParas=()=>[q], tlFps=()=>10, tlPause=()=>{}, tlDraw=()=>{}, tlMsg=()=>{};
const tlSnap=t=>({t});
const saves=[];
const tlSaveTiming=(sel,patch)=>saves.push(patch);
let requests=0;
const api=async()=>{requests++;return [{a:3,b:4}];};
function event(x,key='') {return {button:0,pointerId:1,clientX:x,altKey:true,key,target:source,
 preventDefault(){},stopPropagation(){}};}
source.closest=()=>null;
tlWireCamera();
if(requests || saves.length) throw Error('must not analyse or save automatically');
source.onpointerdown(event(20));source.onpointermove(event(80));source.onpointerup(event(80));
if(saves.length) throw Error('selection saved before Delete');
source.onkeydown(event(0,'Delete'));
if(saves.length!==1 || saves[0].camera_cuts.at(-1).a!==1 || saves[0].camera_cuts.at(-1).b!==4) throw Error('range Delete');
source.onpointerdown(event(20));source.onpointercancel();source.onkeydown(event(0,'Delete'));
if(saves.length!==1) throw Error('cancel saved');
restore.onclick();
if(saves.at(-1).camera_cuts.length!==1 || saves.at(-1).camera_cuts[0].a!==2) throw Error('restore');
trim.onkeydown(event(0,'ArrowRight'));
if(saves.at(-1).camera_cuts.at(-1).b!==1.1) throw Error('keyboard trim');
controls.suggest.onclick().then(()=>{
 if(requests!==1 || saves.length!==3) throw Error('suggestion applied automatically');
 controls.accept.onclick();
 if(saves.at(-1).camera_cuts.at(-1).by!=='hand') throw Error('accept provenance');
 print('camera JS passed');
}).catch(e=>{printerr(e);imports.system.exit(1);});

''')
    result = subprocess.run([gjs,str(script)],capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stderr

"""Exercise recorder logic in installed GJS with DOM/devices mocked; no hardware."""
from pathlib import Path

import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_camera_recorder_js(tmp_path):
    checks = r"""
    (async () => {
      const assert = (ok, why) => { if (!ok) throw Error(why); };
      const p = state.project;
      assert(cameraMode(), 'on_camera preselection');
      setRecordMode(false); assert(!cameraMode(), 'explicit voice override');
      setRecordMode(true); assert(cameraMode(), 'camera switch');
      assert($('#tabbody').innerHTML.includes('Read &lt;this&gt;'), 'escaped narration');
      assert($('#tabbody').innerHTML.includes('accept="video/'), 'video input');
      assert($('#tabbody').innerHTML.includes('ondrop='), 'drop handler');
      assert($('#tabbody').innerHTML.includes('Earlier takes'), 'history');
      let constraints;
      const track = {stop(){}, getSettings: () => ({width:640,height:480,frameRate:30})};
      const stream = {getTracks: () => [track], getVideoTracks: () => [track]};
      Object.defineProperty(navigator, 'mediaDevices', {configurable:true, value:{
        getUserMedia: async c => {constraints=c; return stream;}, enumerateDevices: async () => [
          {kind:'videoinput',deviceId:'cam1',label:'Camera one'},
          {kind:'audioinput',deviceId:'mic1',label:'Mic one'}]}});
      window.AudioContext = class {
        createAnalyser(){return {fftSize:1024};} createMediaStreamSource(){return {connect(){}};}
        resume(){return Promise.resolve();} close(){}
      };
      localStorage.setItem('cb_camera','cam1'); localStorage.setItem('vb_mic','mic1');
      await openCamera();
      assert(constraints.video.width.ideal === 1920 && constraints.video.frameRate.ideal === 30, 'video constraints');
      assert(constraints.audio.autoGainControl === false && constraints.audio.deviceId.exact === 'mic1', 'mic constraints');
      assert(document.querySelector('#camera-settings').textContent.includes('Below 720p'), 'resolution warning');
      assert(document.querySelector('#camera-live').srcObject === stream, 'live preview stream');
      window.MediaRecorder = {isTypeSupported: () => true};
      const realTimeout = window.setTimeout;
      let wake;
      window.setTimeout = cb => {wake=cb;};
      const cancelled = toggleCameraRec(); await Promise.resolve();
      assert(cam.countdown === 3, 'three second countdown');
      cameraJump(1); assert(state.rec.index === 0, 'countdown prevents navigation');
      setRecordMode(false); assert(cameraMode(), 'countdown prevents mode switch');
      await toggleCameraRec(); wake(); await cancelled;
      assert(!state.rec.recording, 'cancelled countdown does not record');
      window.setTimeout = cb => {cb();};
      let opts, target;
      window.MediaRecorder = class {
        static isTypeSupported(m){return m === 'video/mp4';}
        constructor(s,o){opts=o; this.state='inactive';} start(){this.state='recording';}
        stop(){this.state='inactive'; this.ondataavailable({data:new Blob(['video'])}); this.onstop();}
      };
      window.XMLHttpRequest = class {
        constructor(){this.upload={};} open(method,url){target=url;}
        send(fd){
          assert(fd.get('file').name === 'take.mp4', 'MP4 extension');
          this.upload.onprogress({lengthComputable:true,loaded:5,total:10});
          assert(cam.progress === 50, 'upload progress');
          this.upload.onload();
          this.status=200; this.responseText=JSON.stringify({slide:{...p.slides[0], takes:{camera:{duration:2,path:'clean.wav',video:'picture.mp4'}}},recorded_seconds:2});
          this.onload();
        }
      };
      await toggleCameraRec();
      assert(state.rec.recording && opts.mimeType === 'video/mp4' && opts.videoBitsPerSecond === 8000000, 'record options');
      cameraJump(1); assert(state.rec.index === 0, 'recording prevents navigation');
      // A route change must still upload to the original paragraph, even after index changes.
      state.rec.index=1; cam.recorder.stop();
      await Promise.resolve(); await Promise.resolve();
      assert(target === '/api/projects/p1/slides/s1/camera', 'captured upload destination');
      assert(p.slides[0].takes.camera.path === 'clean.wav' && !cam.pending, 'saved response');
      assert(!p.voice_track && p.slides[0].take.path === 'clean.wav', 'camera does not select a voice-over track');
      state.rec.index=0; paintRecord();
      const video=$('#camera-review'), audio=$('#camera-audio');
      video.currentTime=1; video.onseeking(); assert(audio.currentTime === 1, 'review seeking');
      video.playbackRate=1.5; video.onratechange(); assert(audio.playbackRate === 1.5, 'review rate');
      video.volume=.4; video.onvolumechange(); assert(audio.volume === .4, 'review volume');
      const before=target; await uploadCamera({size:3*1024**3},'big.mp4',p,p.slides[0]);
      assert(target === before && !cam.busy, 'size guard');
      window.XMLHttpRequest = class {constructor(){this.upload={};}open(){}send(){this.onerror();}};
      await uploadCamera(new Blob(['retry']), 'retry.mp4', p, p.slides[0]);
      assert(cam.pending && !cam.busy, 'failed upload retained for retry');
      const pending = cam.pending;
      await uploadCamera(new Blob(['other']), 'other.mp4', p, p.slides[0]);
      assert(cam.pending === pending, 'failed take cannot be overwritten');
      stopStream(); assert(cam.stream === null && !state.rec.recording, 'cleanup');
      // Voice uses the same list/history shell without touching stored takes.
      state.rec.index=0; cam.pending=null; cam.busy=false;
      cam.overrides['p1/s1']=false;
      window.isSecureContext=false;
      p.voice_tracks={mic:1}; p.voice_track='mic'; p.recorded_seconds=2;
      p.slides[0].takes.mic={path:'mic.wav', duration:2};
      p.slides[0].take=p.slides[0].takes.mic;
      const snapshot=JSON.stringify(p);
      paint();
      let html=$('#tabbody').innerHTML;
      assert(html.includes('voice-list') && html.includes('voice-takes'), 'three columns in voice mode');
      assert(html.includes('old.wav') && html.includes('mic.wav'), 'current and historical playback');
      assert(html.includes('Use this take') && html.includes('Microphone setup'), 'restore and mic drawer controls');
      assert(html.includes('Read &lt;this&gt;'), 'voice escapes narration');
      assert(JSON.stringify(p) === snapshot, 'painting cannot mutate takes');
      state.rec.recording=true;
      selectVoiceParagraph(1); assert(state.rec.index === 0, 'voice list locks while recording');
      jumpNextUnrecorded(); assert(state.rec.index === 0, 'blank navigation locks while recording');
      await restoreEarlierTake(0); assert(JSON.stringify(p) === snapshot, 'restore locks while recording');
      state.rec.recording=false;
      for (let i=2;i<40;i++) p.slides.push({id:'s'+i,narration:'Paragraph '+i,takes:{}});
      paint(); html=$('#tabbody').innerHTML;
      assert((html.match(/onclick="selectVoiceParagraph/g)||[]).length === 40, 'all forty paragraphs visible');
      assert((html.match(/<audio controls/g)||[]).length === 3, 'only selected paragraph loads players');
      window.setTimeout=realTimeout;
      return 'camera checks passed';
    })()
    """
    bootstrap = r"""
      const window = globalThis, navigator = {}, location = {href:'http://localhost/',protocol:'http:',hostname:'localhost'};
      window.isSecureContext = true;
      const nodes = {};
      const $ = s => nodes[s] ||= {innerHTML:'',style:{},currentTime:0,paused:true,
        play(){this.paused=false;return Promise.resolve();},pause(){this.paused=true;}};
      const document = {querySelector:$,getElementById:s=>$('#'+s)};
      const saved = new Map();
      const localStorage = {getItem:k=>saved.get(k) ?? null,setItem:(k,v)=>saved.set(k,String(v)),removeItem:k=>saved.delete(k)};
      window.setTimeout = () => {}; window.setInterval = () => 1; window.clearInterval = () => {};
      window.Blob = class {constructor(chunks,opts){this.size=chunks.reduce((n,c)=>n+(c.size ?? c.length),0);this.type=opts?.type;}};
      window.FormData = class {constructor(){this.data={};}append(k,v,name){v.name=name;this.data[k]=v;}get(k){return this.data[k];}};

      const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
      const state = {tab:'record', rec:{index:0}, mic:{}, project:{id:'p1',slides:[
        {id:'s1',narration:'Read <this>',on_camera:true,history:[{path:'old.wav',track:'mic'}]},
        {id:'s2',narration:'Next',takes:{}}]}};
      const TRACK_ORDER=['mic','kokoro','elevenlabs','openai'];
      function toast(){} function fmtTime(s){return String(s);}
    """
    # Load the real voice hooks as well as camera functions; stub only unrelated UI.
    sources = (ROOT / 'static/js/tabs/record.js').read_text() + '\n' + (ROOT / 'static/js/tabs/camera.js').read_text()
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS is needed for the plain JS recorder test')
    script = tmp_path / 'camera-test.mjs'
    script.write_text(bootstrap + sources + '\nmeter = () => {}; const paint = paintRecord; paintRecord = () => { if (cameraMode()) paint(); };\n' +
                      'const outcome = await ' + checks.strip() + ';\nprint(outcome);')
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'camera checks passed'

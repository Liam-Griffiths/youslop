// Camera recording is separate from the voice recorder; both use the level meter.
const cam = { stream: null, busy: false, countdown: 0, token: 0, devices: [],
  recorder: null, pending: null, progress: 0, processing: false, overrides: {} };
function cameraMode() {
  const p = state.project, s = p?.slides[state.rec.index];
  if (!s) return false;
  return cam.overrides[p.id + '/' + s.id] ?? (s.on_camera ||
    localStorage.getItem('cb_record_mode_' + p.id) === 'camera');
}
function recordModeSwitch() {
  return `<div class="row" style="margin-top:14px">
    <button class="btn sm ${cameraMode() ? 'ghost' : 'selected'}" onclick="setRecordMode(false)">Voice</button>
    <button class="btn sm ${cameraMode() ? 'selected' : 'ghost'}" onclick="setRecordMode(true)">On camera</button></div>`;
}
function setRecordMode(on) {
  if (cameraLocked()) return;
  stopStream();
  const p = state.project, s = p.slides[state.rec.index];
  cam.overrides[p.id + '/' + s.id] = on;
  localStorage.setItem('cb_record_mode_' + p.id, on ? 'camera' : 'voice');
  paintRecord();
}
function cameraLocked() { return state.rec.recording || cam.busy || !!cam.countdown; }
function cameraJump(n) {
  if (cameraLocked()) return;
  state.rec.index = Math.max(0, Math.min(n, state.project.slides.length - 1));
  paintRecord();
}
function paintCameraRecord() {
  const p = state.project, s = p.slides[state.rec.index], take = s.takes?.camera;
  const locked = cameraLocked() ? 'disabled' : '';
  const options = (kind, key) => `<option value="">default</option>` + cam.devices
    .filter(d => d.kind === kind).map(d => `<option value="${esc(d.deviceId)}"
      ${localStorage.getItem(key) === d.deviceId ? 'selected' : ''}>${esc(d.label || kind)}</option>`).join('');
  $('#tabbody').innerHTML = `${recordModeSwitch()}
    <div class="row" style="margin:12px 0">
      <label>Camera <select ${locked} onchange="chooseCameraDevice('cb_camera',this.value)">${options('videoinput', 'cb_camera')}</select></label>
      <label>Microphone <select ${locked} onchange="chooseCameraDevice('vb_mic',this.value)">${options('audioinput', 'vb_mic')}</select></label>
      <button class="btn sm" ${locked} onclick="openCamera()">open camera</button>
    </div>
    <div class="camera-frame">
      <video id="camera-live" autoplay muted playsinline></video>
      <div class="camera-thirds"></div><div class="camera-headroom"></div>
      <div id="camera-prompter" class="camera-prompter" style="font-size:${localStorage.getItem('cb_prompt_font') || 30}px">${esc(s.narration)}</div>
      <strong id="camera-countdown" class="camera-countdown">${cam.countdown || ''}</strong>
    </div>
    <div id="camera-settings" class="mono"></div>
    <div class="row" style="margin-top:10px">
      <label>Type size <input aria-label="Prompter font size" type="range" min="20" max="60" value="${localStorage.getItem('cb_prompt_font') || 30}"
        oninput="localStorage.setItem('cb_prompt_font',this.value);$('#camera-prompter').style.fontSize=this.value+'px'"></label>
      <label>Scroll speed <input aria-label="Prompter scroll speed" type="range" min="0" max="100" value="${localStorage.getItem('cb_prompt_speed') ?? 20}"
        oninput="localStorage.setItem('cb_prompt_speed',this.value)"> px/s</label>
    </div>
    <div class="rec-bar">
      <button id="recbtn" class="btn rec ${state.rec.recording ? 'armed' : ''}" ${cam.busy ? 'disabled' : ''} onclick="toggleRec()">${state.rec.recording ? '■ Stop' : cam.countdown ? 'Cancel countdown' : '● Record'}</button>
      <span id="timer" class="timer">0:00</span><div class="level"><i id="level"></i></div>
      <label>Import / drop video <input type="file" accept="video/*,.mkv" ${locked} onchange="importCamera(this.files[0])"></label>
    </div>
    <div class="camera-drop" ondragover="event.preventDefault()" ondrop="event.preventDefault();importCamera(event.dataTransfer.files[0])">Drop a phone or camera clip here</div>
    ${cam.busy ? `<progress id="camera-progress" max="100" value="${cam.progress}"></progress><span id="camera-upload-status">${cam.processing ? 'Processing picture and voice…' : 'Uploading…'}</span>` : ''}
    ${cam.pending ? '<button class="btn sm" onclick="retryCameraUpload()">retry saved upload</button>' : ''}
    ${take ? `<div class="panel" style="margin-top:12px">
      <video id="camera-review" controls playsinline preload="metadata" style="width:100%"></video>
      <audio id="camera-audio" preload="metadata"></audio>
      <div class="row"><button class="btn sm" onclick="reviewCamera()">review cleaned take</button>
      <span>Kept automatically</span><button class="btn sm" ${locked} onclick="toggleCameraRec()">Retake</button></div>
      ${take.sync_warning ? '<p>Audio/video offset exceeds 100 ms — check sync.</p>' : ''}
    </div>` : ''}
    <div class="rec-nav"><button class="btn sm" ${locked} onclick="cameraJump(${state.rec.index - 1})">← previous</button>
      <span>paragraph ${state.rec.index + 1} of ${p.slides.length}</span>
      <button class="btn sm" ${locked} onclick="cameraJump(${state.rec.index + 1})">next →</button></div>
    ${(s.history || []).length ? `<details><summary>Earlier takes (${s.history.length})</summary>${s.history.map((t,n) => `<div class="row">
      <span>${esc(t.track || 'mic')} · ${esc(t.reason || '')}</span>
      <audio controls preload="none" src="/api/projects/${p.id}/file/${esc(t.path)}"></audio>
      <button class="btn sm" ${locked} onclick="restoreEarlierTake(${n})">use this</button></div>`).join('')}</details>` : ''}
    <p>If this desktop cannot record video, open this project in your system browser:
      <a href="${esc(location.href)}" target="_blank" rel="noopener">open in browser</a></p>`;
  if (cam.stream) attachCameraPreview();
  if (take) setupCameraReview(p, take);
}
function attachCameraPreview() {
  const el = $('#camera-live');
  if (!el) return;
  el.srcObject = cam.stream;
  el.play().catch(() => {});
  const t = cam.stream.getVideoTracks()[0].getSettings();
  $('#camera-settings').textContent = `${t.width || '?'} × ${t.height || '?'} · ${t.frameRate?.toFixed(1) || '?'} fps`
    + (Math.min(t.width || 0, t.height || 0) < 720 ? ' · Below 720p: choose a higher resolution camera.' : '');
}
async function openCamera() {
  if (cam.stream || cam.busy) return;
  const project = state.project;
  cam.busy = true;
  const token = ++cam.token;
  try {
    if (!micAvailable()) throw new Error('Camera access needs localhost or HTTPS.');
    const clean = !!voiceOf().browser_cleanup;
    const audio = { echoCancellation: clean, noiseSuppression: clean, autoGainControl: false, channelCount: 1, sampleRate: 48000 };
    const video = { width: {ideal: 1920}, height: {ideal: 1080}, frameRate: {ideal: 30} };
    if (localStorage.getItem('vb_mic')) audio.deviceId = {exact: localStorage.getItem('vb_mic')};
    if (localStorage.getItem('cb_camera')) video.deviceId = {exact: localStorage.getItem('cb_camera')};
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({audio, video}); }
    catch (e) {
      if (e.name !== 'OverconstrainedError' && e.name !== 'NotFoundError') throw e;
      delete audio.deviceId; delete video.deviceId;
      localStorage.removeItem('vb_mic'); localStorage.removeItem('cb_camera');
      stream = await navigator.mediaDevices.getUserMedia({audio, video});
    }
    if (token !== cam.token) { stream.getTracks().forEach(t => t.stop()); return; }
    // Close an existing voice monitor before sharing its analyser/meter slots.
    stopStream();
    cam.stream = state.rec.stream = stream;
    const ctx = state.rec.ctx = new AudioContext();
    state.rec.analyser = ctx.createAnalyser();
    state.rec.analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(state.rec.analyser);
    await ctx.resume();
    meter();
    cam.devices = await navigator.mediaDevices.enumerateDevices();
    if (cam.stream !== stream || state.project !== project) return;
    stream.getVideoTracks()[0].onended = () => { stopStream(); if (state.tab === 'record') paintRecord(); };
  } catch (e) { stopStream(); toast('Camera blocked: ' + e.message + ' Try opening this project in your system browser.', true); }
  finally { cam.busy = false; if (state.tab === 'record') paintRecord(); }
}
async function chooseCameraDevice(key, value) {
  if (cameraLocked()) return;
  localStorage.setItem(key, value);
  stopStream();
  await openCamera();
}
function stopCamera() {
  ++cam.token;
  cam.countdown = 0;
  if (cam.recorder?.state === 'recording') cam.recorder.stop();
  if (cam.stream) cam.stream.getTracks().forEach(t => t.stop());
  cam.stream = null;
}
async function toggleCameraRec() {
  if (cam.busy) return;
  if (cam.pending) return toast('Retry the saved camera upload before recording again.', true);
  if (cam.countdown) { ++cam.token; cam.countdown = 0; paintRecord(); return; }
  if (cam.recorder?.state === 'recording') { cam.recorder.stop(); return; }
  await openCamera();
  if (!cam.stream || !cameraMode() || state.tab !== 'record') return;
  const mime = typeof MediaRecorder === 'undefined' ? '' : ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/mp4']
    .find(t => MediaRecorder.isTypeSupported(t));
  if (!mime) return toast('Video recording is unavailable. Open this project in your system browser, or import a clip.', true);
  $('#camera-review')?.pause(); $('#camera-audio')?.pause();
  const token = ++cam.token, p = state.project, slide = p.slides[state.rec.index];
  try {
    for (let n = 3; n; n--) {
      cam.countdown = n; paintRecord();
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (token !== cam.token) return;
    }
    cam.countdown = 0;
    const chunks = [], rec = new MediaRecorder(cam.stream, {mimeType: mime, videoBitsPerSecond: 8_000_000});
    let size = 0;
    rec.ondataavailable = e => {
      if (e.data.size) { chunks.push(e.data); size += e.data.size; }
      if (size >= 2 * 1024 ** 3 && rec.state === 'recording') rec.stop();
    };
    rec.onerror = e => toast('Camera recording failed: ' + (e.error?.message || 'device error'), true);
    rec.onstop = () => {
      state.rec.recording = false; clearInterval(state.rec.tick); cam.recorder = null;
      uploadCamera(new Blob(chunks, {type: mime}), mime.includes('mp4') ? 'take.mp4' : 'take.webm', p, slide);
    };
    rec.start(1000);
    cam.recorder = state.rec.recorder = rec;
    state.rec.recording = true; state.rec.t0 = Date.now();
    paintRecord();
    state.rec.tick = setInterval(() => {
      if ($('#timer')) $('#timer').textContent = fmtTime((Date.now() - state.rec.t0) / 1000);
      const prompt = $('#camera-prompter');
      if (prompt) prompt.scrollTop += +(localStorage.getItem('cb_prompt_speed') ?? 20) / 5;
    }, 200);
  } catch (e) { cam.countdown = 0; toast(e.message, true); paintRecord(); }
}
function importCamera(file) {
  if (!file || cameraLocked()) return;
  uploadCamera(file, file.name, state.project, state.project.slides[state.rec.index]);
}
function retryCameraUpload() {
  if (cam.pending && !cameraLocked()) uploadCamera(...cam.pending);
}
async function uploadCamera(blob, name, p, slide) {
  if (cam.pending && cam.pending[0] !== blob) return toast('Retry the saved camera upload before importing another clip.', true);
  if (!blob.size || blob.size > 2 * 1024 ** 3) {
    if (state.project === p && state.tab === 'record') paintRecord();
    return toast('Choose a nonempty video no larger than 2 GB.', true);
  }
  cam.pending = [blob, name, p, slide]; cam.busy = true; cam.progress = 0; cam.processing = false;
  if (state.project === p && state.tab === 'record') paintRecord();
  try {
    const fd = new FormData(); fd.append('file', blob, name);
    // XHR exposes upload progress; fetch does not provide it for FormData.
    const result = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/projects/${p.id}/slides/${slide.id}/camera`);
      xhr.upload.onprogress = e => {
        cam.progress = e.lengthComputable ? e.loaded / e.total * 100 : 0;
        if ($('#camera-progress')) $('#camera-progress').value = cam.progress;
      };
      xhr.upload.onload = () => { cam.processing = true; if ($('#camera-upload-status')) $('#camera-upload-status').textContent = 'Processing picture and voice…'; };
      xhr.onload = () => {
        let data;
        try { data = JSON.parse(xhr.responseText); } catch { return reject(new Error('Invalid upload response')); }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.detail || `Upload failed (${xhr.status})`));
      };
      xhr.onerror = () => reject(new Error('Upload connection lost. Retry the saved upload.'));
      xhr.send(fd);
    });
    Object.assign(slide, result.slide); p.recorded_seconds = result.recorded_seconds;
    cam.pending = null;
    if (state.project === p) syncVoiceCounts();
    toast('Camera take kept. Review the cleaned picture and voice below.');
  } catch (e) { toast(e.message, true); }
  finally {
    cam.busy = false;
    if (state.project === p && state.tab === 'record') paintRecord();
  }
}
function setupCameraReview(p, take) {
  const video = $('#camera-review'), audio = $('#camera-audio');
  video.src = `/api/projects/${p.id}/file/${take.video}`;
  audio.src = `/api/projects/${p.id}/file/${take.path}`;
  // Picture is silent and includes trailing gap footage; stop at the voice end.
  const sync = () => { audio.currentTime = Math.min(video.currentTime, take.duration); };
  video.onplay = () => { sync(); audio.play().catch(() => video.pause()); };
  video.onpause = () => audio.pause();
  video.onseeking = sync;
  video.onwaiting = () => audio.pause();
  video.onplaying = () => { sync(); audio.play().catch(() => video.pause()); };
  video.onratechange = () => { audio.playbackRate = video.playbackRate; };
  video.onvolumechange = () => { audio.volume = video.volume; audio.muted = video.muted; };
  video.ontimeupdate = () => {
    if (video.currentTime >= take.duration) video.pause();
    else if (Math.abs(audio.currentTime - video.currentTime) > .1) sync();
  };
  audio.onended = () => video.pause();
}
function reviewCamera() { $('#camera-review')?.play().catch(e => toast(e.message, true)); }

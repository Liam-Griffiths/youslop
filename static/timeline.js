// The timeline on the Render tab: the whole cut laid out in time, scrubbed a
// frame at a time and played from small proxies.
//
// A proxy is one picture's segment at quarter size and half rate, drawn by the
// real renderer (see render.proxy_segment) and kept until the script changes.
// The opening slate and end card are proxied the same way. Nothing is drawn
// until it is asked for: the entry under the playhead, and the next two while
// playing. So a first scrub into an undrawn picture waits a few seconds; every
// visit after that is instant.
//
// Positions are the finished video's, slate and end card included.
//
// Sound is one file for the whole cut (render.build_mix: narration, the slate's
// sting and the music bed under the voice, through the same graph the
// finished render mixes with). It is the clock; the picture proxies play
// silently against it, which is also why a cut between two pictures has no gap
// in the sound. With nothing to hear, a wall clock stands in.
//
// `render()` repaints the whole page whenever a job ends, so this state and
// its media elements live out here and are re-attached on every mount.
const TL = {
  pid: '', data: null, host: null,
  cur: 0, playing: false, speed: 1, loop: false, zoom: 10,
  vids: null, active: 0, seg: -1,
  queue: [], pending: new Set(), failed: new Set(), running: false, drawing: '',
  raf: 0, wait: '', lastPara: '', scrubbing: false,
  audio: null, mixStamp: 0, mixBusy: false, mixFailed: false,
  wall: { base: 0, t0: 0 },
};

const tlFps = () => (TL.data && TL.data.fps) || 15;
const tlSegs = () => (TL.data && TL.data.segments) || [];
const tlParas = () => tlSegs().flatMap((s) => s.paragraphs.map((q) => ({ ...q, seg: s.index })));
const tlKey = (s) => `${s.ref}:${s.stamp}`;
const tlLabel = (s) => (s.type === 'intro' ? 'slate' : s.type === 'outro' ? 'end'
  : String(s.n).padStart(2, '0'));
const tlName = (s) => (s.type === 'intro' ? 'the opening slate' : s.type === 'outro'
  ? 'the end card' : `picture ${s.n}`);
const tlHasSound = () => !!(TL.data && TL.data.mix.audible && TL.mixStamp && TL.audio
  && TL.audio.getAttribute('src'));

function tlClock(t) {
  t = Math.max(0, t);
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, '0')}`;
}

function tlSegAt(t) {
  const segs = tlSegs();
  for (let i = segs.length - 1; i >= 0; i--) if (t >= segs[i].start - 1e-6) return segs[i];
  return segs[0];
}

// ----------------------------------------------------------------- mounting
async function tlMount() {
  const host = $('#tl');
  if (!host) return;
  const p = state.project;
  if (!TL.vids) {
    TL.vids = [0, 1].map(() => {
      const v = document.createElement('video');
      v.playsInline = true; v.preload = 'auto'; v.muted = true; v.dataset.seg = '';
      return v;
    });
  }
  if (!TL.audio) { TL.audio = new Audio(); TL.audio.preload = 'auto'; }
  if (TL.pid !== p.id) {
    tlPause();
    Object.assign(TL, { pid: p.id, data: null, cur: 0, seg: -1, queue: [], failed: new Set(),
                        pending: new Set(), wait: '', lastPara: '', mixStamp: 0, mixFailed: false });
    TL.vids.forEach((v) => { v.removeAttribute('src'); v.dataset.seg = ''; v.load(); });
    TL.audio.removeAttribute('src'); TL.audio.load();
  }
  TL.host = host;
  host.innerHTML = `
    <div class="tl-head">
      <h3>Timeline</h3>
      <span class="mono tl-note" id="tl-note"></span>
      <div class="spacer"></div>
      <label class="row" style="gap:6px"><span class="mono tl-note">speed</span>
        <select id="tl-speed" style="width:auto">
          ${[0.5, 1, 1.5, 2].map((x) => `<option value="${x}" ${x === TL.speed ? 'selected' : ''}>${x}×</option>`).join('')}
        </select></label>
      <label class="row" style="gap:6px;cursor:pointer" title="keep replaying the entry under the playhead">
        <input type="checkbox" id="tl-loop" style="width:auto" ${TL.loop ? 'checked' : ''}>
        <span class="mono tl-note">loop picture</span></label>
      <button class="btn sm ghost" id="tl-all"
        title="draw every picture's proxy now instead of as you reach it">draw all</button>
    </div>
    <div class="tl-main">
      <div class="tl-stage" id="tl-stage">
        <div class="tl-msg" id="tl-msg"></div>
      </div>
      <div class="tl-inspector" id="tl-inspector"></div>
    </div>
    <div class="tl-transport">
      <button class="btn sm ghost" id="tl-prev" title="previous paragraph (Shift+←)">|◂</button>
      <button class="btn sm ghost" id="tl-back" title="back one frame (←)">◂</button>
      <button class="btn sm primary tl-play" id="tl-play" title="play / pause (Space)">▶</button>
      <button class="btn sm ghost" id="tl-fwd" title="forward one frame (→)">▸</button>
      <button class="btn sm ghost" id="tl-next" title="next paragraph (Shift+→)">▸|</button>
      <span class="mono tl-clock" id="tl-clock"></span>
      <div class="spacer"></div>
      <label class="row" style="gap:6px"><span class="mono tl-note">zoom</span>
        <input type="range" id="tl-zoom" min="2" max="60" step="1" value="${TL.zoom}" style="width:130px"></label>
    </div>
    <div class="tl-scroll" id="tl-scroll"><div class="tl-track" id="tl-track"></div></div>
    <div class="tl-problems" id="tl-problems"></div>`;
  const stage = $('#tl-stage');
  TL.vids.forEach((v, i) => { v.className = i === TL.active ? 'on' : ''; stage.prepend(v); });

  $('#tl-speed').onchange = (e) => { TL.speed = +e.target.value; tlRate(); };
  $('#tl-loop').onchange = (e) => { TL.loop = e.target.checked; };
  $('#tl-all').onclick = tlDrawAll;
  $('#tl-play').onclick = tlToggle;
  $('#tl-back').onclick = () => tlStep(-1);
  $('#tl-fwd').onclick = () => tlStep(1);
  $('#tl-prev').onclick = () => tlPara(-1);
  $('#tl-next').onclick = () => tlPara(1);
  $('#tl-zoom').oninput = (e) => { TL.zoom = +e.target.value; tlDraw(); };
  tlWireScrub();
  TL.vids.forEach((v) => { v.onerror = () => tlVideoFailed(v); });

  if (!TL.data) $('#tl-note').textContent = 'laying out the cut…';
  await tlRefresh();
}

// Re-read the layout. After an edit the changed entries come back not-ready,
// and the one under the playhead is redrawn straight away. Opening the tab
// draws nothing by itself: that waits for a play, a click or an edit.
async function tlRefresh(redrawCurrent = false) {
  if (!TL.host || !document.body.contains(TL.host)) return;
  let data;
  try { data = await api(`/api/projects/${state.project.id}/timeline`); }
  catch (e) { const n = $('#tl-note'); if (n) n.textContent = e.message; return; }
  TL.data = data;
  TL.vids.forEach((v) => {
    const ref = v.dataset.seg.split(':')[0];
    if (v.dataset.seg && !data.segments.some((s) => s.ref === ref)) v.dataset.seg = '';
  });
  TL.cur = Math.min(TL.cur, Math.max(0, data.total - 1 / data.fps));
  tlDraw();
  tlSeek(TL.cur, { ensure: redrawCurrent });
  if (redrawCurrent) {
    const seg = tlSegAt(TL.cur);
    if (seg && !seg.ready) { TL.failed.delete(seg.ref); tlEnsure([seg.ref], true); }
  }
  tlEnsureMix();
}

// ------------------------------------------------------------------- sound
// The mix is rebuilt whenever anything it is made of changed (a take, the bed,
// the levels, a slate length that has just been learned). Audio only, so it is
// quick, and it is asked for on its own without waiting for a play.
async function tlEnsureMix() {
  const d = TL.data;
  if (!d) return;
  const mix = d.mix;
  const src = `/api/projects/${state.project.id}/file/${mix.path}?v=${mix.stamp}`;
  if (mix.audible && mix.have && TL.audio.getAttribute('src') !== src && mix.stamp !== TL.mixStamp) {
    // Something to play now, possibly an older mix; a fresh one follows.
    TL.mixStamp = mix.stamp;
    TL.audio.src = src;
    TL.audio.load();
    tlRate();
  }
  tlPaintNote();
  if (!mix.audible || mix.ready || TL.mixBusy || TL.mixFailed) return;
  TL.mixBusy = true;
  const pid = state.project.id;
  tlPaintNote();
  try {
    const r = await api(`/api/projects/${pid}/timeline/mix`, { method: 'POST' });
    const j = await tlWaitJob(r.job);
    if (TL.pid !== pid) return;
    if (j.state === 'error') throw new Error(j.error);
    TL.mixBusy = false;
    await tlRefresh();            // picks the new file up and re-checks it is current
    return;
  } catch (e) {
    TL.mixFailed = true;
    toast(`Sound: ${e.message}`, true);
  }
  TL.mixBusy = false;
  tlPaintNote();
}

function tlRate() {
  if (TL.audio) TL.audio.playbackRate = TL.speed;
  if (TL.vids) TL.vids.forEach((v) => { v.playbackRate = TL.speed; });
}

// ------------------------------------------------------------------ drawing
function tlStepFor(zoom) {
  for (const s of [1, 2, 5, 10, 15, 30, 60, 120, 300, 600]) if (s * zoom >= 64) return s;
  return 900;
}

function tlThumb(seg) {
  const s = state.project.slides.find((x) => x.id === seg.lead);
  const c = s && s.candidates.find((x) => x.id === s.chosen_id);
  return c ? thumbUrl(c) : '';
}

function tlPaintNote() {
  const note = $('#tl-note');
  const d = TL.data;
  if (!note || !d) return;
  const pics = d.segments.filter((s) => s.type === 'picture').length;
  const mix = d.mix;
  const sound = !mix.audible ? 'silent: nothing recorded yet and no bed'
    : TL.mixBusy ? 'mixing the sound…'
    : TL.mixFailed ? 'sound failed to mix'
    : (mix.music ? `with the “${mix.music.replace(/\.[^.]+$/, '')}” bed` : 'narration only, no music bed')
      + (mix.sting ? (mix.stings && mix.stings.length > 1 ? ' and both stings' : ' and the ' + ((mix.stings || [''])[0] === 'outro' ? 'end card' : 'slate') + ' sting') : '');
  note.textContent = `${fmtTime(d.total)} · ${pics} pictures · ${d.width}×${d.height} at ${d.fps}fps · ${sound}`
    + (d.estimated ? ' · some lengths estimated' : '')
    + (d.camera_clip ? ' · the camera clip is not shown here' : '');
}

function tlDraw() {
  const track = $('#tl-track');
  if (!track || !TL.data) return;
  const d = TL.data, z = TL.zoom;
  tlPaintNote();
  track.style.width = `${Math.ceil(d.total * z) + 24}px`;
  const step = tlStepFor(z);
  let ticks = '';
  for (let t = 0; t <= d.total; t += step) {
    ticks += `<i style="left:${t * z}px"><b>${fmtTime(t)}</b></i>`;
  }
  const pics = d.segments.map((s) => {
    const img = s.type === 'picture' ? tlThumb(s) : '';
    const bad = s.problems.some((x) => x.startsWith('no picture'));
    return `<div class="tl-pic ${s.type !== 'picture' ? 'slate' : ''} ${s.ready ? 'ready' : s.have ? 'stale' : ''}
        ${bad ? 'bad' : ''}" data-seg="${s.index}"
        style="left:${s.start * z}px;width:${Math.max(2, s.duration * z - 2)}px;
        ${img ? `background-image:url('${esc(img)}')` : ''}">
        <span class="tl-tag">${tlLabel(s)}${s.problems.length ? ' ⚠' : ''}${s.estimated ? ' ~' : ''}</span>
        <i class="tl-dot" title="${s.ready ? 'proxy drawn' : s.have ? 'out of date' : 'not drawn yet'}"></i>
      </div>`;
  }).join('');
  const paras = tlParas().map((q) => `
      <div class="tl-para ${q.recorded ? '' : 'est'} ${q.chapter ? 'chap' : ''}" data-para="${q.id}"
        style="left:${q.start * z}px;width:${Math.max(2, q.duration * z - 2)}px"
        title="${esc(q.text.slice(0, 140))}">
        ${q.chapter ? '<span class="tl-flag">⚑</span>' : ''}<span>${esc(q.text)}</span>
      </div>`).join('');
  track.innerHTML = `
    <div class="tl-ruler">${ticks}</div>
    <div class="tl-lane"><em>pictures</em>${pics}</div>
    <div class="tl-lane para"><em>voice</em>${paras}</div>
    <div class="tl-head-line" id="tl-line"><b></b></div>`;
  tlPaintProblems();
  TL.lastPara = '';
  tlPaintHead();
}

function tlPaintProblems() {
  const box = $('#tl-problems');
  if (!box || !TL.data) return;
  const rows = [];
  for (const s of TL.data.segments) for (const m of s.problems) rows.push([s, m]);
  box.innerHTML = rows.length
    ? `<span class="mono tl-note">worth a look before rendering:</span>` + rows.slice(0, 12).map(([s, m]) =>
        `<button class="tl-chip" onclick="tlSeek(${s.start},{ensure:true})">
          ${tlLabel(s)} · ${esc(m)}</button>`).join('')
      + (rows.length > 12 ? `<span class="mono tl-note">+${rows.length - 12} more</span>` : '')
    : `<span class="mono tl-note">every picture has a picture and a recording.</span>`;
}

// The cheap repaint: playhead, clock, play button, which paragraph is selected.
function tlPaintHead() {
  const d = TL.data;
  if (!d || !$('#tl-line')) return;
  $('#tl-line').style.left = `${TL.cur * TL.zoom}px`;
  $('#tl-clock').textContent =
    `${tlClock(TL.cur)} / ${tlClock(d.total)}  ·  frame ${Math.round(TL.cur * d.fps)}`;
  $('#tl-play').textContent = TL.playing ? '❚❚' : '▶';
  const seg = tlSegAt(TL.cur);
  // Which paragraph is under the playhead: the last one that has started, within
  // a picture; the slate and end card have no paragraph and are inspected alone.
  let id = '', para = null;
  if (seg.type === 'picture') {
    para = [...seg.paragraphs].reverse().find((q) => TL.cur >= q.start - 1e-6) || seg.paragraphs[0];
    id = para.id;
  } else id = seg.ref;
  if (id !== TL.lastPara) {
    TL.lastPara = id;
    document.querySelectorAll('#tl-track .tl-para.sel').forEach((e) => e.classList.remove('sel'));
    if (para) {
      const el = document.querySelector(`#tl-track [data-para="${para.id}"]`);
      if (el) el.classList.add('sel');
      tlInspect({ ...para, seg: seg.index });
    } else tlInspectSlate(seg);
  }
  // Keep the playhead on screen while it plays or is stepped.
  const sc = $('#tl-scroll'), x = TL.cur * TL.zoom;
  if (sc && !TL.scrubbing && (x < sc.scrollLeft + 20 || x > sc.scrollLeft + sc.clientWidth - 40)) {
    sc.scrollLeft = Math.max(0, x - sc.clientWidth * 0.3);
  }
}

function tlPaintStatus() {
  document.querySelectorAll('#tl-track .tl-pic').forEach((el) => {
    const s = tlSegs()[+el.dataset.seg];
    if (!s) return;
    el.classList.toggle('ready', s.ready);
    el.classList.toggle('stale', !s.ready && s.have);
    el.classList.toggle('drawing', TL.drawing === s.ref);
  });
}

// ---------------------------------------------------------------- inspector
function tlInspect(para) {
  const box = $('#tl-inspector');
  if (!box) return;
  const p = state.project;
  const s = p.slides.find((x) => x.id === para.id);
  if (!s) { box.innerHTML = ''; return; }
  const seg = tlSegs()[para.seg];
  const fmt = p.style.format;
  const cut = isCut(fmt);
  box.innerHTML = `
    <div class="mono tl-note">paragraph ${String(para.index + 1).padStart(2, '0')} ·
      ${tlName(seg)} ·
      ${tlClock(para.start)} → ${tlClock(para.start + para.duration)}
      ${para.recorded ? '' : '· <span style="color:var(--accent)">estimated, not recorded</span>'}</div>
    ${s.chapter ? `<div class="pill" style="margin:6px 0 0">⚑ chapter: ${esc(s.chapter)}</div>` : ''}
    <div class="tl-text">${esc(s.narration)}</div>
    ${seg.problems.length ? `<div class="tl-warn">${seg.problems.map((m) => '⚠ ' + esc(m)).join('<br>')}</div>` : ''}
    <div class="tl-actions">
      <button class="btn sm" onclick="tlEditText('${s.id}')">edit the words</button>
      <button class="btn sm" onclick="tlEditPicture('${seg.lead}')">change the picture</button>
      ${fmt === 'board' ? `<button class="btn sm" onclick="tlModal(() => openBoardEditor('${s.id}'))">edit the board</button>` : ''}
      ${cut ? `<button class="btn sm" onclick="tlModal(() => openCueEditor('${s.id}'))">edit the cues</button>` : ''}
      <button class="btn sm" onclick="tlOpenTab('record','${s.id}')">${para.recorded ? 're-record / re-read' : 'record this'}</button>
    </div>
    <div class="tl-links mono">open in
      <a onclick="tlOpenTab('script','${s.id}')">script</a> ·
      <a onclick="tlOpenTab('media','${s.id}')">media</a> ·
      <a onclick="tlOpenTab('record','${s.id}')">record</a></div>`;
}

// The slate and end card belong to the channel (or, standalone, to the panels
// further down this page), so that is where editing them goes.
function tlInspectSlate(seg) {
  const box = $('#tl-inspector');
  if (!box) return;
  const p = state.project;
  const intro = seg.type === 'intro';
  const where = p.channel_id
    ? `<button class="btn sm" onclick="go('#/c/${p.channel_id}')">edit it on the channel page</button>`
    : `<button class="btn sm" onclick="document.getElementById('opening-panel')?.scrollIntoView({block:'center'})">edit it below</button>`;
  box.innerHTML = `
    <div class="mono tl-note">${intro ? 'opening slate' : 'end card'} ·
      ${tlClock(seg.start)} → ${tlClock(seg.start + seg.duration)}
      ${seg.estimated ? '· <span style="color:var(--accent)">length estimated until drawn</span>' : ''}</div>
    <div class="tl-text">${intro
      ? 'The video opens on this slate, with its own sting if it has one. The music bed holds off until it is over.'
      : 'The video closes on this card. The music bed fades out over it.'}</div>
    <div class="tl-actions">${where}</div>`;
}

// Open a tab with one paragraph scrolled into view (or, on Record, selected).
function tlOpenTab(tab, sid) {
  const i = state.project.slides.findIndex((x) => x.id === sid);
  state.focusSlide = sid;
  if (tab === 'record' && i >= 0) { state.rec = state.rec || {}; state.rec.index = i; }
  go(`#/p/${state.project.id}/${tab}`);
}

// Run one of the app's own editor modals, and refresh the cut when it closes.
function tlModal(open) {
  tlPause();
  const before = new Set(document.querySelectorAll('.modal'));
  open();
  const fresh = [...document.querySelectorAll('.modal')].filter((m) => !before.has(m));
  const watcher = new MutationObserver(() => {
    if (fresh.length && fresh.some((m) => document.body.contains(m))) return;
    watcher.disconnect();
    tlRefreshProject();
  });
  watcher.observe(document.body, { childList: true });
}

async function tlRefreshProject() {
  try { state.project = await api(`/api/projects/${state.project.id}`); } catch { /* keep */ }
  TL.lastPara = '';
  TL.mixFailed = false;
  await tlRefresh(true);
}

function tlEditPicture(leadId) { tlModal(() => openMediaSearch(leadId)); }

function tlEditText(sid) {
  tlPause();
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box" style="width:min(640px,100%)">
      <div class="row" style="margin-bottom:12px">
        <strong>Edit the words</strong>
        <span class="mono tl-note">paragraph ${state.project.slides.indexOf(s) + 1}</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="tx-cancel">cancel</button>
        <button class="btn sm primary" id="tx-save">save</button>
      </div>
      <textarea id="tx-text" rows="8" style="width:100%">${esc(s.narration)}</textarea>
      <label class="field" style="margin-top:10px"><span>On-screen title (optional)</span>
        <input type="text" id="tx-title" value="${esc(s.title)}"></label>
      ${s.take ? `<div class="pill warn" style="margin-top:10px">
        This paragraph is recorded. Changing the words leaves the recording as it
        was — record it again to match.</div>` : ''}
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector('#tx-cancel').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  wrap.querySelector('#tx-save').onclick = async () => {
    const r = await saveSlide(sid, {
      narration: wrap.querySelector('#tx-text').value,
      title: wrap.querySelector('#tx-title').value,
    });
    close();
    if (r) await tlRefreshProject();
  };
  wrap.querySelector('#tx-text').focus();
}

// ------------------------------------------------------------------ playback
const tlActive = () => TL.vids[TL.active];
const tlStandby = () => TL.vids[1 - TL.active];

function tlSrc(seg) {
  return `/api/projects/${state.project.id}/file/${seg.path}?v=${seg.stamp}`;
}

function tlMsg(text) {
  const m = $('#tl-msg');
  if (!m) return;
  m.textContent = text || '';
  m.style.display = text ? 'flex' : 'none';
}

// Put segment `seg` into video `v`, resolving when its first frame can be sought.
function tlLoad(v, seg) {
  const want = tlKey(seg);
  if (v.dataset.seg === want) return Promise.resolve();
  v.dataset.seg = want;
  v.src = tlSrc(seg);
  return new Promise((res) => {
    const done = () => { v.removeEventListener('loadedmetadata', done); res(); };
    v.addEventListener('loadedmetadata', done);
    v.load();
  });
}

function tlSeekVideo(v, time) {
  return new Promise((res) => {
    if (Math.abs(v.currentTime - time) < 1e-3 && v.readyState >= 2) return res();
    const done = () => { v.removeEventListener('seeked', done); res(); };
    v.addEventListener('seeked', done);
    v.currentTime = time;
  });
}

function tlShow(i) {
  TL.active = i;
  TL.vids.forEach((v, n) => v.classList.toggle('on', n === i));
}

// The clock the player runs on: the sound when there is some, else the wall.
function tlNow() {
  if (tlHasSound()) return TL.audio.currentTime;
  return TL.wall.base + ((performance.now() - TL.wall.t0) / 1000) * TL.speed;
}

function tlSetClock(t) {
  TL.wall = { base: t, t0: performance.now() };
  if (tlHasSound()) {
    try { TL.audio.currentTime = t; } catch { /* not seekable yet */ }
  }
}

// Where in the segment's file picture-time `t` falls. Half a frame in, so a seek
// lands inside the frame rather than on the edge between two.
const tlFileTime = (seg, t) => seg.skip + (t - seg.start) + 0.5 / tlFps();

let tlSeekToken = 0;
async function tlSeek(t, opts = {}) {
  const d = TL.data;
  if (!d || !d.segments.length) return;
  const fps = d.fps;
  t = Math.max(0, Math.min(d.total - 1 / fps, t));
  t = Math.round(t * fps) / fps;
  TL.cur = t;
  const seg = tlSegAt(t);
  TL.seg = seg.index;
  tlSetClock(t);
  tlPaintHead();
  if (!seg.have) {
    const failed = TL.failed.has(seg.ref);
    tlMsg(failed ? `${tlName(seg)} could not be drawn.`
      : opts.ensure === false || TL.scrubbing ? `${tlName(seg)} is not drawn yet. Press play to draw it.`
      : `Drawing ${tlName(seg)}…`);
    if (opts.ensure !== false && !TL.scrubbing) tlEnsure([seg.ref], true);
    return;
  }
  const token = ++tlSeekToken;
  // The slot holding this entry is reused when it can be: stepping through
  // one picture is just seeking, not reloading.
  let v = tlActive();
  if (v.dataset.seg !== tlKey(seg)) {
    const other = tlStandby();
    if (other.dataset.seg === tlKey(seg)) { tlShow(1 - TL.active); v = tlActive(); }
    else { await tlLoad(v, seg); if (token !== tlSeekToken) return; }
  }
  await tlSeekVideo(v, tlFileTime(seg, t));
  if (token !== tlSeekToken) return;
  tlMsg(seg.ready ? '' : (TL.pending.has(seg.ref) ? `${tlName(seg)} is out of date — redrawing…` : ''));
  if (!seg.ready && !TL.scrubbing && opts.ensure !== false) tlEnsure([seg.ref], true);
  if (TL.playing && !opts.noplay) tlResume();
}

function tlStep(n) {
  tlPause();
  tlSeek(TL.cur + n / tlFps());
}

function tlPara(dir) {
  const ps = tlParas();
  if (!ps.length) return;
  tlPause();
  if (dir < 0) {
    const back = ps.filter((q) => q.start < TL.cur - 0.4);
    tlSeek(back.length ? back[back.length - 1].start : 0);
  } else {
    const nxt = ps.find((q) => q.start > TL.cur + 1e-3);
    tlSeek(nxt ? nxt.start : TL.data.total);
  }
}

function tlToggle() { TL.playing ? tlPause() : tlPlay(); }

async function tlPlay() {
  if (!TL.data) return;
  if (TL.cur >= TL.data.total - 2 / tlFps()) TL.cur = 0;
  TL.playing = true;
  tlPaintHead();
  await tlSeek(TL.cur, { noplay: true });
  const seg = tlSegAt(TL.cur);
  if (!seg.have) { TL.wait = seg.ref; return; }          // resumes when it is drawn
  tlResume();
}

// Start (or continue) everything from the current position: sound, picture, and
// the loop that keeps the picture on the clock.
function tlResume() {
  if (!TL.playing) return;
  TL.wait = '';
  tlRate();
  tlSetClock(TL.cur);
  const v = tlActive();
  v.play().catch(() => {});
  if (tlHasSound()) TL.audio.play().catch(() => {});
  tlAhead();
  cancelAnimationFrame(TL.raf);
  TL.raf = requestAnimationFrame(tlTick);
}

function tlPause() {
  TL.playing = false;
  TL.wait = '';
  cancelAnimationFrame(TL.raf);
  if (TL.vids) TL.vids.forEach((v) => v.pause());
  if (TL.audio) TL.audio.pause();
  if (TL.host) tlPaintHead();
}

// While playing, the next two entries are drawn behind it and the next one is
// loaded into the idle video so the cut to it is a swap, not a load.
function tlAhead() {
  const n = TL.seg + 1, segs = tlSegs();
  tlEnsure([n, n + 1].filter((i) => i < segs.length).map((i) => segs[i].ref));
  const nx = segs[n];
  if (nx && nx.have) {
    const v = tlStandby();
    if (v.dataset.seg !== tlKey(nx)) {
      tlLoad(v, nx).then(() => { if (v.dataset.seg === tlKey(nx)) v.currentTime = nx.skip; });
    }
  }
}

function tlTick() {
  if (!TL.playing) return;
  const d = TL.data;
  let t = tlNow();
  let seg = tlSegs()[TL.seg];
  if (TL.loop && t >= seg.start + seg.duration - 0.5 / d.fps) {
    t = seg.start;
    tlSetClock(t);
    tlActive().currentTime = tlFileTime(seg, t);
  }
  if (t >= d.total - 0.5 / d.fps) {
    tlPause();
    TL.cur = d.total - 1 / d.fps;
    tlPaintHead();
    return;
  }
  TL.cur = t;
  if (t >= seg.start + seg.duration || t < seg.start) {
    seg = tlSegAt(t);
    if (!tlEnter(seg)) return;               // not drawn: waiting for it
  } else {
    // Hold the picture on the clock. A little drift is nothing; a lot is a seek.
    const v = tlActive();
    const want = tlFileTime(seg, t) - 0.5 / d.fps;
    if (Math.abs(v.currentTime - want) > 0.3) v.currentTime = want;
  }
  tlPaintHead();
  TL.raf = requestAnimationFrame(tlTick);
}

// Move playback onto `seg`: swap to the preloaded video if it is there. Returns
// false (and waits for the draw) if the entry has no proxy yet.
function tlEnter(seg) {
  TL.seg = seg.index;
  if (!seg.have) {
    TL.vids.forEach((v) => v.pause());
    if (TL.audio) TL.audio.pause();
    TL.wait = seg.ref;
    tlMsg(`Drawing ${tlName(seg)}…`);
    tlPaintHead();
    tlEnsure([seg.ref], true);
    return false;
  }
  const idle = tlStandby();
  const old = tlActive();
  if (idle.dataset.seg === tlKey(seg)) {
    idle.currentTime = tlFileTime(seg, TL.cur) - 0.5 / tlFps();
    idle.playbackRate = TL.speed;
    idle.play().catch(() => {});
    tlShow(1 - TL.active);
    old.pause();
  } else {
    tlLoad(old, seg).then(() => {
      old.currentTime = tlFileTime(seg, TL.cur) - 0.5 / tlFps();
      old.playbackRate = TL.speed;
      if (TL.playing) old.play().catch(() => {});
    });
  }
  tlAhead();
  return true;
}

function tlVideoFailed(v) {
  if (!v.getAttribute('src')) return;
  tlMsg("This window can't play the preview video. The finished render can still be opened from the folder.");
  tlPause();
}

// ------------------------------------------------------------- proxy drawing
function tlEnsure(refs, urgent = false) {
  const segs = tlSegs();
  for (const ref of refs) {
    const s = segs.find((x) => x.ref === ref);
    if (!s || s.ready || TL.pending.has(ref) || TL.failed.has(ref)) continue;
    TL.pending.add(ref);
    urgent ? TL.queue.unshift(ref) : TL.queue.push(ref);
  }
  tlPump();
}

async function tlPump() {
  if (TL.running || !TL.queue.length) return;
  TL.running = true;
  const pid = state.project.id;
  while (TL.queue.length && TL.pid === pid) {
    const ref = TL.queue.shift();
    TL.drawing = ref;
    tlPaintStatus();
    let learned = false;
    try {
      const r = await api(`/api/projects/${pid}/timeline/proxy`,
        { method: 'POST', body: JSON.stringify({ refs: [ref] }) });
      const j = await tlWaitJob(r.job);
      if (TL.pid !== pid) break;
      if (j.state === 'error') throw new Error(j.error);
      const out = (j.result.segments || [])[0];
      const seg = tlSegs().find((x) => x.ref === ref);
      if (seg && out) {
        seg.ready = true; seg.have = true; seg.stamp = out.rendered_at;
        // A slate's real length is only known now; the layout may have moved.
        learned = seg.type !== 'picture' && seg.estimated;
      }
    } catch (e) {
      TL.failed.add(ref);
      toast(`${ref === 'intro' ? 'Slate' : ref === 'outro' ? 'End card' : 'Picture ' + (+ref + 1)}: ${e.message}`, true);
      learned = ref === 'intro' || ref === 'outro';
    }
    TL.pending.delete(ref);
    TL.drawing = '';
    if (learned) {
      // New lengths move everything after the slate, and the sound with it.
      await tlRefresh();
      tlPaintStatus();
      continue;
    }
    tlPaintStatus();
    const cur = tlSegAt(TL.cur);
    if (cur && cur.ref === ref) {
      tlMsg('');
      const wasWaiting = TL.wait === ref;
      await tlSeek(TL.cur, { ensure: false, noplay: true });
      if (wasWaiting && TL.playing) tlResume();
    }
    if (!TL.queue.length) tlDraw();
  }
  TL.running = false;
}

async function tlWaitJob(id) {
  for (;;) {
    await new Promise((r) => setTimeout(r, 600));
    const j = await api(`/api/jobs/${id}`);
    if (j.state !== 'running') return j;
  }
}

function tlDrawAll() {
  const segs = tlSegs().filter((s) => !s.ready);
  if (!segs.length) { toast('every picture is already drawn'); return; }
  if (!confirm(`Draw ${segs.length} entr${segs.length > 1 ? 'ies' : 'y'} (pictures, slate and end card) at `
    + `${TL.data.width}×${TL.data.height}? It runs one after another in the background and uses a good `
    + 'share of this computer while it does.')) return;
  tlEnsure(segs.map((s) => s.ref));
}

// -------------------------------------------------------------- interaction
function tlWireScrub() {
  const track = $('#tl-track');
  if (!track) return;
  const at = (e) => {
    const r = track.getBoundingClientRect();
    return Math.max(0, (e.clientX - r.left) / TL.zoom);
  };
  track.onpointerdown = (e) => {
    if (e.button !== 0) return;
    track.setPointerCapture(e.pointerId);
    TL.scrubbing = true;
    if (TL.playing) tlPause();
    tlSeek(at(e), { ensure: false });
  };
  track.onpointermove = (e) => { if (TL.scrubbing) tlSeek(at(e), { ensure: false }); };
  const up = () => {
    if (!TL.scrubbing) return;
    TL.scrubbing = false;
    tlSeek(TL.cur);          // now that it has stopped, draw what is needed
  };
  track.onpointerup = up;
  track.onpointercancel = up;
}

document.addEventListener('keydown', (e) => {
  if (!TL.host || !document.body.contains(TL.host) || !TL.data) return;
  const tag = (e.target.tagName || '').toLowerCase();
  if (['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable) return;
  if (document.querySelector('.modal') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;
  if (k === ' ') tlToggle();
  else if (k === 'ArrowLeft') e.shiftKey ? tlPara(-1) : tlStep(-1);
  else if (k === 'ArrowRight') e.shiftKey ? tlPara(1) : tlStep(1);
  else if (k === 'Home') { tlPause(); tlSeek(0); }
  else if (k === 'End') { tlPause(); tlSeek(TL.data.total); }
  else if (k === 'l' || k === 'L') { TL.loop = !TL.loop; const c = $('#tl-loop'); if (c) c.checked = TL.loop; }
  else return;
  e.preventDefault();
});

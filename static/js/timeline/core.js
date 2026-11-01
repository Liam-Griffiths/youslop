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
      <button class="btn sm tl-play" id="tl-play" title="play / pause (Space)">▶</button>
      <button class="btn sm ghost" id="tl-fwd" title="forward one frame (→)">▸</button>
      <button class="btn sm ghost" id="tl-next" title="next paragraph (Shift+→)">▸|</button>
      <span class="mono tl-clock" id="tl-clock"></span>
      <div class="spacer"></div>
      <label class="row" style="gap:6px"><span class="mono tl-note">zoom</span>
        <input type="range" id="tl-zoom" min="2" max="60" step="1" value="${TL.zoom}" style="width:130px"></label>
    </div>
    <div class="tl-scroll" id="tl-scroll"><div class="tl-track" id="tl-track"></div></div>
    <div class="tl-problems" id="tl-problems"></div>
    <div class="tl-problems" id="tl-review"></div>`;
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

let tlSeekToken = 0;

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

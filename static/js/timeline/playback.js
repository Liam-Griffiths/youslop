
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

// Where in the segment's file picture-time `t` falls. Half a frame in, so a seek
// lands inside the frame rather than on the edge between two.
const tlFileTime = (seg, t) => seg.skip + (t - seg.start) + 0.5 / tlFps();
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

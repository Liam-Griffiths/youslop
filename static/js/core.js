/* Corkbored — local single-page client. */

const $ = (sel, root = document) => root.querySelector(sel);
const view = $('#view');

const state = {
  mode: 'idea',
  project: null,
  channel: null,
  tab: 'script',
  job: null,       // {id, since, kind}
  templates: null, // slate templates, fetched once
  thumbStyles: null, // thumbnail styles, fetched once
  tts: null,       // the local voice engine's status and voice list, fetched once
  poll: null,
  rec: { index: 0, recording: false, stream: null, recorder: null, chunks: [], t0: 0, tick: null, ctx: null },
  // the mic & voice panel: its modal, the last test read and what the A/B is on
  mic: { el: null, report: null, busy: false, measuring: false, counting: 0,
         tick: null, rec: null, ab: '', trim: 0 },
};

// ------------------------------------------------------------------- plumbing
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    const detail = data && data.detail;
    const err = new Error((typeof detail === 'string' ? detail : detail && detail.message)
      || `HTTP ${res.status}`);
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(msg, bad = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, bad ? 6000 : 3000);
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function go(hash) { location.hash = hash; }

// The standalone videos live in a section of the home page rather than on a
// page of their own; from anywhere else this goes there and scrolls to them.
function goStandalone() {
  const land = () => requestAnimationFrame(() =>
    $('#standalone')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  if ((location.hash || '#/') === '#/') { land(); return; }
  state.afterHome = land;
  go('#/');
}

// Existing views call this after refreshing the cached channel list.
function paintSidebar() { paintAppNav(); }

// Channels change rarely enough that one fetch per route is wasted work —
// cached here and refreshed only when a page already needed the list anyway
// (home, or after creating/renaming one) or it has never been loaded.
async function ensureChannelsLoaded() {
  if (!state.channels) {
    try { state.channels = await api('/api/channels'); }
    catch { state.channels = []; }
  }
  paintSidebar();
}

// ----------------------------------------------------------------- settings
// Replaces hand-editing .env: everything app/settings.py knows how to
// configure, grouped and labelled. A secret field never carries its real
// value back from the server — only whether one is set — so saving must only
// ever send fields the user actually touched this session, tracked here by
// id; resending the whole form on every save would blank out every secret
// the user didn't mean to change.
const settingsDirty = new Set();

const loadingLine = () => 'Loading…';

// ---------------------------------------------------------------------- jobs
function watchJob(id, kind, onDone) {
  state.job = { id, kind, since: 0, lines: [], done: null, tagline: 'Working…' };
  paintJobsStrip();
  clearInterval(state.poll);
  const step = async () => {
    let j;
    try { j = await api(`/api/jobs/${id}?since=${state.job.since}`); }
    catch { return; }
    if (!state.job || state.job.id !== id) return;
    state.job.since = j.log_total;
    state.job.lines.push(...j.log.map((l) => l.m));
    state.job.elapsed = j.elapsed;
    state.job.status = j.status || "";
    paintJob();
    if (j.state !== 'running') {
      clearInterval(state.poll);
      state.job.done = j.state;
      paintJobsStrip();
      if (j.state === 'error') toast(j.error || 'Job failed', true);
      if (state.project) {
        state.project = await api(`/api/projects/${state.project.id}`);
        render();
      } else if (state.channel) {
        state.channel = await api(`/api/channels/${state.channel.id}`);
        paintChannel();
      }
      if (onDone) onDone(j);
    }
  };
  state.poll = setInterval(step, 1200);
  step();
}

function paintJob() {
  paintJobsStrip();
  paintPublishProgress();
  if (!state.job) return;
  const box = $('#joblog');
  if (box) {
    box.textContent = state.job.lines.join('\n');
    box.scrollTop = box.scrollHeight;
  }
  const status = $('#jobstatus');
  if (status) { status.textContent = state.job.status || ''; status.hidden = !state.job.status; }
  const el = $('#jobstate');
  if (el) el.textContent = state.job.done ? state.job.done : `${state.job.elapsed || 0}s`;
  // The rendering placeholder says what the renderer last said, so a slate that
  // takes four seconds is visibly doing something rather than just sitting.
  const line = $('#renderline');
  if (line) {
    const last = (state.job.lines || []).slice(-1)[0];
    line.textContent = last || `${state.job.tagline} ${state.job.elapsed || 0}s`;
  }
}

function jobPanel() {
  if (!state.job) return '';
  const running = !state.job.done;
  return `<div class="panel" style="margin-bottom:18px">
    <div class="row" style="margin-bottom:10px">
      ${running ? '<span class="spin"></span>' : ''}
      <strong>${esc(state.job.kind)}</strong>
      <span class="mono" id="jobstate" style="color:var(--ink-faint)"></span>
      <div class="spacer"></div>
      ${running ? '' : `<button class="btn sm ghost" onclick="state.job=null;render()">dismiss</button>`}
    </div>
    <div class="joblog" id="joblog"></div>
    <div class="sub mono" id="jobstatus" hidden></div>
  </div>`;
}

// ------------------------------------------------------------------ routing
async function route() {
  const hash = canonicalHash(location.hash || '#/');
  if (hash !== (location.hash || '#/')) { location.replace(hash); return; }
  resetShell();
  if (typeof footageStop === 'function') footageStop();
  const proj = hash.match(/^#\/p\/([^/]+)(?:\/(\w+))?(?:\/(\w+))?/);
  const chan = hash.match(/^#\/channels\/([^/]+)(?:\/(\w+))?/);
  const lib = hash === '#/library';
  const settingsPage = hash === '#/settings';
  const guidePage = hash === '#/guide';
  stopStream();
  if (typeof tlPause === 'function' && !(proj && proj[2] === 'edit')) tlPause();
  // Every format picker (home, channel, project) paints from this, so it is
  // loaded once here rather than awaited in three places.
  await ensureSlideStyles();
  await ensureStyleKits();

  if (hash === '#/setup') {
    state.project = null; state.channel = null;
    await renderSetup();
  } else if (hash === '#/channels') {
    state.project = null; state.channel = null;
    await ensureChannelsLoaded();
    paintChannelsIndex();
  } else if (hash === '#/packs') {
    state.project = null; state.channel = null;
    view.innerHTML = '<h1>Packs</h1><div id="packs-screen"></div>';
    await renderPacks();
  } else if (hash === '#/blocks' || hash.startsWith('#/blocks/')) {
    if (state.project) state.blocksProjectId = state.project.id;
    state.project = null; state.channel = null;
    await renderBlocks(hash.slice(9));
  } else if (hash.startsWith('#/footage')) {
    state.project = null; state.channel = null;
    if (hash.split('/')[3] === 'clips') await renderClipFinder(hash.split('/')[2], hash.split('/')[4]);
    else await renderFootage(hash.split('/')[2]);
  } else if (guidePage) {
    state.project = null;
    state.channel = null;
    renderGuide();
  } else if (settingsPage) {
    state.project = null;
    state.channel = null;
    await renderSettings();
  } else if (lib) {
    state.project = null;
    state.channel = null;
    await renderLibrary();
  } else if (proj) {
    state.channel = null;
    state.stage = proj[2] || 'plan';
    state.subtab = proj[3] || '';
    state.tab = stageTab(state.stage, state.subtab);
    if (!state.thumbStyles) {
      try { state.thumbStyles = await api('/api/thumbs/templates'); }
      catch { state.thumbStyles = []; }
    }
    if (!state.boardTemplates) {
      try {
        const b = await api('/api/board/templates');
        state.boardTemplates = b.templates;
        state.boardHands = b.hands;
      } catch { state.boardTemplates = []; }
      try { state.diagramKinds = (await api('/api/diagram/kinds')).kinds; }
      catch { state.diagramKinds = []; }
    }
    if (!state.cuts) {
      try { state.cuts = await api('/api/cuts'); } catch { state.cuts = []; }
    }
    if (!state.project || state.project.id !== proj[1]) {
      state.project = null;
      view.innerHTML = `<div class="empty-note">${loadingLine()}</div>`;
      try { state.project = await api(`/api/projects/${proj[1]}`); }
      catch (e) { view.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; return; }
      const live = (state.project.jobs || [])[0];
      if (live) watchJob(live.id, live.kind);
    }
    if ([state.project.style.format,...state.project.slides.map(s => s.kind || '')].some(k => k.startsWith('custom:')))
      await ensureSlideStyles();
    await loadStageStates(state.project);
    await render();
  } else if (chan) {
    state.project = null;
    state.channelTab = chan[2] === 'setup' ? 'setup' : 'videos';
    if (!state.templates) {
      try { state.templates = await api('/api/intro/templates'); }
      catch { state.templates = []; }
    }
    if (!state.endTemplates) {
      try { state.endTemplates = await api('/api/outro/templates'); }
      catch { state.endTemplates = []; }
    }
    if (!state.themes) {
      try { state.themes = await api('/api/themes'); }
      catch { state.themes = []; }
    }
    if (!state.thumbStyles) {
      try { state.thumbStyles = await api('/api/thumbs/templates'); }
      catch { state.thumbStyles = []; }
    }
    if (!state.channel || state.channel.id !== chan[1]) {
      state.channel = null;
      view.innerHTML = `<div class="empty-note">${loadingLine()}</div>`;
      try { state.channel = await api(`/api/channels/${chan[1]}`); }
      catch (e) { view.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; return; }
      const live = (state.channel.jobs || [])[0];
      if (live) watchJob(live.id, live.kind, refreshChannel);
    }
    paintChannel();
  } else {
    state.project = null;
    state.channel = null;
    await renderHome();
  }
  await ensureChannelsLoaded();
  paintJobsStrip();
  if (state.project) paintProjectShell();
  else await loadShellStatus();
}

// ------------------------------------------------------------ focal picker
// A point that must stay on screen. The crop is centred on it and the Ken
// Burns move is clamped so a slow zoom can never wander off a subject's face.
function openFocal(src, current, onSave) {
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:12px">
        <strong>Keep this on screen</strong>
        <div class="spacer"></div>
        <span class="mono" style="color:var(--ink-faint)">click the subject's face</span>
      </div>
      <div class="focal-stage" id="fstage">
        <img id="fimg" src="${src}">
        <div class="focal-dot" id="fdot" hidden></div>
      </div>
      <div class="row" style="margin-top:14px">
        <span class="mono" id="fread" style="color:var(--ink-faint)">no point set</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="fclear">clear</button>
        <button class="btn sm ghost" id="fcancel">cancel</button>
        <button class="btn sm primary" id="fsave">save</button>
      </div>
    </div>`;
  document.body.appendChild(wrap);

  const img = wrap.querySelector('#fimg');
  const dot = wrap.querySelector('#fdot');
  const read = wrap.querySelector('#fread');
  let point = (current && current.length === 2) ? [...current] : null;

  // The image is letterboxed inside the stage (object-fit: contain), so clicks
  // have to be mapped through the displayed rect, not the element box.
  const fit = () => {
    const r = img.getBoundingClientRect();
    const s = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight);
    const dw = img.naturalWidth * s, dh = img.naturalHeight * s;
    return { r, dw, dh, ox: (r.width - dw) / 2, oy: (r.height - dh) / 2 };
  };

  const paint = () => {
    if (!point || !img.naturalWidth) { dot.hidden = true; read.textContent = 'no point set'; return; }
    const { dw, dh, ox, oy } = fit();
    dot.hidden = false;
    dot.style.left = `${ox + point[0] * dw}px`;
    dot.style.top = `${oy + point[1] * dh}px`;
    read.textContent = `focus at ${(point[0] * 100).toFixed(0)}% , ${(point[1] * 100).toFixed(0)}%`;
  };

  img.onload = paint;
  if (img.complete) paint();
  window.addEventListener('resize', paint);

  wrap.querySelector('#fstage').onclick = (ev) => {
    const { r, dw, dh, ox, oy } = fit();
    const x = (ev.clientX - r.left - ox) / dw;
    const y = (ev.clientY - r.top - oy) / dh;
    point = [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
    paint();
  };

  const close = () => { window.removeEventListener('resize', paint); wrap.remove(); };
  wrap.querySelector('#fclear').onclick = () => { point = null; paint(); };
  wrap.querySelector('#fcancel').onclick = close;
  wrap.querySelector('#fsave').onclick = () => { close(); onSave(point || []); };
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
}

const FORMAT_INFO = [
  { key: 'kenburns', label: 'Documentary', blurb: 'The picture fills the frame and drifts.' },
  { key: 'essay', label: 'Video essay', blurb: 'The picture sits in a slide, narration on screen.' },
  { key: 'board', label: 'Handwritten board', blurb: 'White marker on slate, written as you talk.' },
  { key: 'flameboat', label: 'Flameboat', blurb: 'Rapid-fire tech explainer: B-roll, code, terminals, memes, hard cuts.' },
  { key: 'casefile', label: 'Casefile', blurb: 'True crime on a lamp-lit corkboard, pinned up as you talk.' },
  { key: 'loudmouth', label: 'Loudmouth', blurb: 'Kinetic type: every word slams in as it is said.' },
  { key: 'groupchat', label: 'Group Chat', blurb: 'Storytime: the message thread, cutting away to the scene and back.' },
  { key: 'ticker', label: 'Ticker', blurb: 'A markets terminal: rolling figures, drawn charts, bars.' },
  { key: 'stage', label: '3D explainer', blurb: 'Narration over 3D models: orbits, close-ups, reveals.' },
];

// The drawn cuts (app/cuts/): each paragraph is a run of cues the writer
// placed on its words, so they get a cue editor where the board gets a board
// editor, and they join on hard cuts rather than the crossfade.
const CUT_KEYS = ['flameboat', 'casefile', 'loudmouth', 'groupchat', 'ticker'];
const isCut = (fmt) => CUT_KEYS.includes(fmt || '');
const cutInfo = (fmt) => (state.cuts || []).find((c) => c.key === fmt);

// Saved slide styles sit in this same picker — a design kept from the slide
// editor is a way to stage a video, exactly like the three built-in formats,
// so it belongs beside them rather than in a list of its own. Loaded once and
// cached on `state`; `ensureSlideStyles()` is what route handlers await before
// painting a picker.
async function ensureSlideStyles() {
  if (!state.slideStyles) {
    try { state.slideStyles = await api('/api/slide-styles'); }
    catch { state.slideStyles = []; }
  }
  return state.slideStyles;
}

async function exportSlideStyle(id, name) {
  try {
    const res = await fetch(`/api/slide-styles/${id}/export`);
    if (!res.ok) throw new Error((await res.json()).detail || 'export failed');
    const blob = await res.blob();
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'style';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${slug}.corkbored-style.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  } catch (e) { toast(e.message, true); }
}

async function importSlideStyle(file) {
  if (!file) return;
  try {
    const text = await file.text();
    let data;
    try { data = JSON.parse(text); }
    catch { throw new Error('that file is not valid JSON'); }
    const r = await api('/api/slide-styles/import',
      { method: 'POST', body: JSON.stringify(data) });
    state.slideStyles = null;
    await ensureSlideStyles();
    toast(`imported — “${r.name}” is now a video style`);
    document.querySelector('dialog.style-dialog')?.close();
    route();
  } catch (e) { toast(e.message, true); }
}

async function deleteSlideStyle(id) {
  if (!confirm('Delete this slide style? Videos already using it keep their look '
    + 'until you pick another.')) return;
  try {
    await api(`/api/slide-styles/${id}`, { method: 'DELETE' });
    state.slideStyles = null;
    await ensureSlideStyles();
    toast('style deleted');
    document.querySelector('dialog.style-dialog')?.close();
    route();
  } catch (e) { toast(e.message, true); }
}

// ----------------------------------------------------------------- project
async function render() {
  const p = state.project;
  if (!p) return;
  state.stage = state.stage || 'plan';
  state.tab = stageTab(state.stage, state.subtab);
  const tabs = state.stage === 'visuals'
    ? [['media', 'Picture picker'], ...(p.slides.some(s => pictureKind(s,p) === 'stage') || isStage(p.style.format) ? [['cast', 'Cast'], ['stage', 'Stage']] : [])]
    : [];
  if (tabs.length && !tabs.some(([id]) => id === state.tab)) state.tab = tabs[0][0];
  // Stage contents are replaced below; give back any slot the last stage borrowed.
  restoreShellInspector();
  paintProjectShell();
  view.innerHTML = `
    <div class="row project-tools">
      <span class="sub">${esc(p.subtitle || p.outline.thesis || '')}</span>
      <div class="spacer"></div>
      <button class="btn ghost sm" onclick="saveProjectFile()"
        title="everything in this video as one file, to open on another computer">save project file…</button>
    </div>
    ${tabs.length > 1 && (state.stage !== 'visuals' || state.tab !== 'media') ? `<nav class="tabs stage-subtabs" aria-label="${esc(state.stage)} tools">
      ${tabs.map(([id, label]) => `<a class="tab ${state.tab === id ? 'active' : ''}"
        ${state.tab === id ? 'aria-current="page"' : ''}
        href="#/p/${p.id}/${state.stage}/${id}">${label}</a>`).join('')}
    </nav>` : ''}
    ${jobPanel()}<div id="tabbody"></div>`;
  await ({ plan: paintPlan, script: paintScript, media: paintMedia, cast: paintCast, stage: paintStage,
    record: paintRecord, thumb: paintThumb, render: paintRender, edit: paintEdit }[state.tab] || paintScript)();
  paintJob();
  if (state.stage !== 'edit' && typeof tlPause === 'function') tlPause();
  focusPendingSlide();
}

// Arriving from the timeline (or anywhere else) with one paragraph in mind:
// scroll its card into view and flash it.
function focusPendingSlide() {
  const sid = state.focusSlide;
  if (!sid) return;
  state.focusSlide = '';
  const el = document.querySelector(`#tabbody [data-sid="${sid}"]`);
  if (!el) return;
  el.scrollIntoView({ block: 'center' });
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 1800);
}

// ------------------------------------------------------------------- media
function thumbUrl(c) {
  // A local video's own file can't sit in an <img> tag — a generated
  // establishing shot carries a project-relative poster frame in `thumb` for
  // exactly this (see app/maps.py), the same convention `local_path` uses.
  if (c.local_path && c.kind === 'video' && c.thumb) {
    return `/api/projects/${state.project.id}/file/${c.thumb}`;
  }
  if (c.local_path) return `/api/projects/${state.project.id}/file/${c.local_path}`;
  // A library hit already lives on this server — no hotlink wall to route
  // around, and /api/thumb only proxies http(s) URLs anyway.
  if (['library', 'footage'].includes(c.provider)) return c.thumb || c.url;
  return `/api/thumb?url=${encodeURIComponent(c.thumb || c.url)}`;
}

// The actual playable file for a video candidate: the downloaded local copy
// once there is one, otherwise the provider's own direct file link (Pexels
// and Pixabay both hand back a real .mp4 URL, not a page to scrape).
function videoUrl(c) {
  if (c.local_path) return `/api/projects/${state.project.id}/file/${c.local_path}`;
  return c.provider === 'footage' ? `${c.url}#t=${c.in_s},${c.out_s}` : c.url;
}

// ------------------------------------------------------------ playing video
// Everything the app renders is played back in its own window, and on Linux
// that window is WebKitGTK decoding through GStreamer — which, on a desktop
// with only the base and "good" plugin sets, has no H.264 decoder at all. The
// previews dodge it by being VP9/Opus in WebM, but the finished render is
// H.264 because YouTube wants it that way, so it can still come up as a
// broken play button on a perfectly good file. When that happens the player
// says so, gives the one command that fixes it, and offers the folder.
async function ensurePlayback() {
  if (!state.playback) {
    state.playback = await api('/api/playback').catch(() => ({}));
  }
  return state.playback;
}

// `file` is {scope, id, rel} — what /api/reveal needs to show it on disk.
function videoTag(src, file, attrs = 'controls preload="metadata"') {
  return `<video ${attrs} src="${esc(src)}"
    data-file="${esc(encodeURIComponent(JSON.stringify(file || {})))}"
    onerror="videoFailed(this)"></video>`;
}

async function videoFailed(el) {
  if (el.dataset.helped) return;          // one note per player, not one per retry
  el.dataset.helped = '1';
  const pb = await ensurePlayback();
  let file = {};
  try { file = JSON.parse(decodeURIComponent(el.dataset.file || '%7B%7D')); } catch { /* none */ }
  const codec = pb.h264 === false;
  const mp4 = /\.mp4(\?|$)/.test(el.getAttribute('src') || '');
  el.insertAdjacentHTML('afterend', `
    <div class="playback-help">
      <strong>This window can't play that video.</strong>
      <div class="mono">${codec && mp4
        ? `The file is fine — nothing on this machine can decode H.264 inside
           the app window${pb.distro ? ` (${esc(pb.distro)})` : ''}. The decoders
           live in GStreamer's libav plugin, which most desktops don't install.`
        : `The file is on disk and the renderer finished it; the window just
           won't play it back.`}</div>
      ${pb.command ? `
        <div class="row" style="margin-top:10px">
          <code class="cmd">${esc(pb.command)}</code>
          <button class="btn sm ghost" onclick="copyText('${esc(encodeURIComponent(pb.command))}')">copy</button>
        </div>` : ''}
      ${pb.note ? `<div class="mono" style="color:var(--ink-faint);margin-top:8px">${esc(pb.note)}</div>` : ''}
      ${file.id ? `
        <div class="row" style="margin-top:10px">
          <button class="btn sm" onclick="revealFile('${esc(file.scope || 'project')}','${esc(file.id)}','${esc(encodeURIComponent(file.rel || ''))}')">
            open the folder</button>
          <span class="mono" style="color:var(--ink-faint)">and play it in your own player</span>
        </div>` : ''}
    </div>`);
}

// Show a file where it lives. The button exists whether or not playback
// failed — "where did that render go" is a fair question on its own.
async function revealFile(scope, id, rel) {
  try {
    const r = await api('/api/reveal', {
      method: 'POST',
      body: JSON.stringify({ scope, id, rel: decodeURIComponent(rel) }),
    });
    toast(r.opened ? `Opened ${r.folder}` : r.folder);
  } catch (e) { toast(e.message, true); }
}

function copyText(encoded) {
  const text = decodeURIComponent(encoded);
  navigator.clipboard.writeText(text)
    .then(() => toast('Copied to clipboard'))
    .catch(() => toast('Failed to copy', true));
}

// The modal both video previews play in — opens over whatever picker or grid
// it was clicked from, closes on Escape/backdrop-click, and pauses itself on
// close rather than playing on in a detached element.
function openVideoModal(head, videoTag) {
  const wrap = document.createElement('div');
  wrap.className = 'modal clip-modal';
  wrap.innerHTML = `
    <div class="modal-box" style="width:min(900px,100%)">
      <div class="row" style="margin-bottom:10px">
        ${head}
        <div class="spacer"></div>
        <button class="btn sm ghost" id="vclose">close</button>
      </div>
      ${videoTag}
    </div>`;
  document.body.appendChild(wrap);
  const video = wrap.querySelector('video');
  const close = () => { video.pause(); wrap.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  wrap.querySelector('#vclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
}

// A quick look at a clip before committing to it.
function playClip(c) {
  openVideoModal(
    `<strong>${esc(c.title || 'clip')}</strong>
     <span class="mono" style="color:var(--ink-faint)">${esc(c.provider)}${c.duration ? ` · ${fmtTime(c.duration)}` : ''}</span>`,
    videoTag(videoUrl(c),
             // A candidate still being auditioned may only exist on the
             // archive's server; there is no folder to open until it is
             // downloaded, and the note alone is the useful half.
             c.local_path ? { scope: 'project', id: state.project.id, rel: c.local_path } : {},
             `controls autoplay playsinline poster="${esc(thumbUrl(c))}"`));
}

function playClipFor(sid, cid) {
  const s = state.project.slides.find((x) => x.id === sid);
  const c = s && s.candidates.find((x) => x.id === cid);
  if (c) playClip(c);
}

// A play button laid over a video thumbnail, wired so a click previews the
// clip instead of triggering whatever select/choose handler sits on the
// thumbnail underneath it. Looks the candidate up by id at click time rather
// than carrying it inline, so there's no JSON-in-an-attribute to escape.
function playBtn(sid, c) {
  if (c.kind !== 'video') return '';
  return `<button class="play-btn" title="preview"
            onclick="event.stopPropagation();playClipFor('${sid}','${c.id}')"></button>`;
}

// One picture's segment, rendered at half size on demand: the real framing,
// drift, titles and narration, in seconds rather than the whole-video render
// it used to take to see any of it.
async function previewBit(sid) {
  const r = await api(`/api/projects/${state.project.id}/slides/${sid}/preview`,
                      { method: 'POST' });
  watchJob(r.job, 'segment preview', (j) => {
    if (j.state === 'done' && j.result) playSegmentPreview(j.result);
  });
  render();
}

function playSegmentPreview(seg) {
  const p = state.project;
  openVideoModal(
    `<strong>Picture ${seg.picture} of ${seg.pictures}</strong>
     <span class="mono" style="color:var(--ink-faint)">
       ${seg.paragraphs} paragraph${seg.paragraphs > 1 ? 's' : ''} ·
       ${fmtTime(seg.seconds)} · rough ${seg.width}×${seg.height} at
       ${seg.fps}fps — the cut itself renders at 1920×1080</span>`,
    videoTag(`/api/projects/${p.id}/file/${seg.path}?v=${seg.rendered_at}`,
             { scope: 'project', id: p.id, rel: seg.path },
             'controls autoplay playsinline'));
}

// A location, generated rather than searched for — sometimes seeing where
// somewhere is says more than a photo of it would. See app/maps.py. The
// widget IS the zoom control: whatever zoom it's sitting at when you click
// is the zoom the render happens at, same Web Mercator convention maps.py
// already uses server-side, so there's no separate zoom slider to keep in
// sync with it.
const MAP_TILE_URLS = {
  street: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  satellite: 'https://server.arcgisonline.com/ArcGIS/rest/services/'
             + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',
  terrain: 'https://server.arcgisonline.com/ArcGIS/rest/services/'
           + 'World_Terrain_Base/MapServer/tile/{z}/{y}/{x}',
  labels: 'https://server.arcgisonline.com/ArcGIS/rest/services/'
          + 'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
};
const MAP_TILE_ATTR = {
  street: '&copy; OpenStreetMap contributors',
  satellite: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
  terrain: 'Terrain &copy; Esri, USGS, NOAA',
};
// "hybrid" isn't a tile source of its own — the preview stacks the same two
// layers app/maps.py composites server-side onto each generated tile.
const MAP_LAYERS_FOR = {
  satellite: ['satellite'], street: ['street'], terrain: ['terrain'],
  hybrid: ['satellite', 'labels'],
};

// ------------------------------------------------------- custom slide design
// The open-ended sibling of the diagram editor: no fixed layout, just
// elements on a canvas. Describing what you want in words is the main way in
// — Claude writes the spec — and every element stays editable afterwards, so
// a design you half-like is a starting point rather than a take-it-or-leave-it.
const CUSTOM_ANIMS = ['fade', 'rise', 'fly-left', 'fly-right', 'pop', 'none'];
const CUSTOM_FONTS = ['hand', 'sans', 'serif', 'mono', 'display'];
const CUSTOM_SIZES = ['sm', 'md', 'lg', 'xl', 'xxl'];

let thumbTimer = null;
let thumbPending = {};

const TRACK_ORDER = ['mic', 'kokoro', 'elevenlabs', 'openai'];

// -------------------------------------------------------------- mic & voice
// Setting up the microphone is its own job, and it is the one that decides how
// the finished video sounds. Room tone, distance and gain cannot be fixed
// afterwards by any amount of processing, so this panel measures them off a
// short test read, says what is wrong in words, and only then hands over the
// chain that cleans the rest.

const VOICE_KNOBS = [
  { k: 'de_room', label: 'De-room', min: 0, max: 1, step: 0.05,
    fmt: (v) => `${Math.round(v * 100)}%`,
    hint: 'holds down everything that is not the direct sound — the reflections '
        + 'between words and the tail after each one. The single control that '
        + 'makes a live room sound smaller.' },
  { k: 'warmth', label: 'Warmth', min: -6, max: 6, step: 0.1,
    fmt: (v) => `${v > 0 ? '+' : ''}${v.toFixed(1)} dB`,
    hint: 'body at 180Hz — the chest in a voice.' },
  { k: 'box_cut', label: 'Box', min: 0, max: 8, step: 0.1,
    fmt: (v) => `−${v.toFixed(1)} dB`,
    hint: 'out at 430Hz, where a small room piles up its honk. Boxiness reads '
        + 'as "recorded across a desk" long before it reads as an echo.' },
  { k: 'presence', label: 'Presence', min: -4, max: 6, step: 0.1,
    fmt: (v) => `${v > 0 ? '+' : ''}${v.toFixed(1)} dB`,
    hint: 'consonants at 3.1kHz. Too much and the room comes up with them.' },
  { k: 'air', label: 'Air', min: -3, max: 6, step: 0.1,
    fmt: (v) => `${v > 0 ? '+' : ''}${v.toFixed(1)} dB`,
    hint: 'the shelf above 9.5kHz that most of "expensive microphone" lives in.' },
  { k: 'denoise', label: 'Denoise', min: 0, max: 1, step: 0.05,
    fmt: (v) => `${Math.round(v * 100)}%`,
    hint: 'steady noise only — a fan, a fridge, the computer. Past about 70% it '
        + 'starts to sound underwater.' },
  { k: 'compression', label: 'Levelling', min: 0, max: 1, step: 0.05,
    fmt: (v) => `${Math.round(v * 100)}%`,
    hint: 'holds the read even, so the quiet end of a sentence still carries '
        + 'under the music.' },
  { k: 'sibilance', label: 'De-ess', min: 0, max: 1, step: 0.05,
    fmt: (v) => `${Math.round(v * 100)}%`,
    hint: 'pays for the presence lift by holding the s sounds down.' },
  { k: 'low_cut', label: 'Low cut', min: 40, max: 160, step: 5,
    fmt: (v) => `${Math.round(v)} Hz`,
    hint: 'desk rumble and room boom under the voice. Higher for a lighter '
        + 'voice, lower if it starts sounding thin.' },
];

const PRESET_BLURB = {
  warm: 'close podcast read',
  neutral: 'straight, minimal colour',
  bright: 'forward and crisp',
  live: 'for a room that cannot be fixed',
};

const VERDICT_BLURB = {
  dry: 'close and dead — nothing to fix',
  controlled: 'a good room to read in',
  live: 'the walls are in the recording',
  echoey: 'the room is louder than your voice',
};

// Save the change and rebuild the test recording through it, in one trip.
let micPreviewTimer;

// A standalone video's own sting for its title card or its end card. The two
// specs name their fields differently (`music_*` on the slate, `sting_*` on
// the end card), so one table maps either onto the same controls.
const STING_FIELDS = {
  intro: { file: 'music', name: 'music_filename', db: 'music_db', start: 'music_start',
           fade: 'music_fade', dur: 'music_duration' },
  outro: { file: 'sting', name: 'sting_filename', db: 'sting_db', start: 'sting_start',
           fade: 'sting_fade', dur: 'sting_duration' },
};

async function saveStyle(patch, repaint = true) {
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ style: patch }) });
  if (repaint) render();
}
const pickProjectFormat = (key) => saveStyle({ format: key });

async function saveProject(patch, quiet = false) {
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify(patch) });
  if (!quiet) toast('saved');
}


// ------------------------------------------------------------- 3D models
// The 3D explainer's models (docs/3d-explainer.md). The shared library is
// where a model is *understood* — front, true size, look — once, on the
// intake screen; a video's Cast is just which of them it can put on stage.
// three.js is only loaded when one of these screens is opened.
const isStage = (fmt) => (fmt || '') === 'stage';

// What each intake limit code means for the shots (static/stage/intake.js).
const LIMIT_TEXT = {
  baked_light: 'Its light is baked into the scan\u2019s photos, so the stage will not relight it.',
  bare_scan: 'No textures: give it a flat colour under Look, or it reads as grey clay.',
  stand_inside: 'Shots stand inside it, at eye height.',
  level_camera: 'The camera stays level; a tilted camera makes the walls lean.',
  holes: 'The scan has holes; they will show as window light, not black.',
  subject_is_a_part: 'The subject is one part of it, to be marked before shots are planned.',
  edge: 'It ends at an edge, and shots keep that edge out of frame.',
  no_low_angles: 'An aerial scan melts near the ground, so the camera always looks down at least 20\u00b0.',
  one_direction: 'It is built to be seen from one side; shots stand where the missing walls would be.',
};


// ---------------------------------------------------------------- the stage
// A 3D explainer's shot list (app/shots.py, docs/3d-explainer.md steps 7-9).
// Every paragraph whose visual line is a 3D beat has a shot: the planner's
// intent, solved and checked by the stage in a headless browser. A shot that
// failed its checks is flagged amber; the creator fixes it by changing the
// intent, or by setting it from the view in the preview — which locks it, so
// planning again never overwrites it.
const SHOT_STATE = {
  ok: ['on', 'checked'], flagged: ['warn', 'flagged'], stale: ['warn', 'out of date'],
  unsolved: ['', 'not solved'], no_model: ['warn', 'no model'],
};
const SHOT_OPTS = {
  move: ['static', 'orbit', 'push', 'pull', 'crane', 'reveal', 'pan', 'turn'],
  framing: ['wide', 'medium', 'tight'],
  side: ['auto', 'front', 'three_quarter', 'left', 'right', 'rear', 'above', 'low'],
  join: ['cut', 'match', 'continuous', 'dip'],
};

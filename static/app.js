/* Youslop — local single-page client. */

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

// ------------------------------------------------------------------ sidebar
// The channel list is fetched once and kept in state.channels — every page
// that already loads channels (home, a project, a channel) refreshes it, and
// paintSidebar() just reads whatever is there, so the sidebar never needs a
// request of its own and never goes stale by more than one navigation.
function toggleSidebar() {
  $('#sidebar').classList.toggle('open');
}

function paintSidebar() {
  const hash = location.hash || '#/';
  const chanId = (hash.match(/^#\/c\/([^/]+)/) || [])[1];
  const onLibrary = hash === '#/library';
  const onSettings = hash === '#/settings';
  const onGuide = hash === '#/guide';

  $('.sidebar-link[data-route="guide"]')?.classList.toggle('active', onGuide);
  $('.sidebar-link[data-route="library"]')?.classList.toggle('active', onLibrary);
  $('.sidebar-link[data-route="settings"]')?.classList.toggle('active', onSettings);

  // Videos in no channel have no page of their own to link to, so the
  // sidebar points at their section on the home page. The count comes from
  // whatever the last projects fetch saw — it is a signpost, not a total.
  const solo = $('#solo-count');
  if (solo) solo.textContent = state.soloCount != null ? state.soloCount : '';

  const box = $('#sidebar-channels');
  if (!box) return;
  const chans = state.channels || [];
  box.innerHTML = chans.length
    ? chans.map((c) => `
        <a class="sidebar-link ${c.id === chanId ? 'active' : ''}"
           onclick="go('#/c/${c.id}')" title="${esc(c.name)}">
          <span class="sidebar-icon">◆</span>${esc(c.name)}</a>`).join('')
    : `<span class="sidebar-link" style="color:var(--ink-faint);cursor:default">
         no channels yet</span>`;

  // A narrow-viewport sidebar is an overlay the user opened on purpose;
  // close it once they've actually gone somewhere.
  if (window.innerWidth <= 860) $('#sidebar').classList.remove('open');
}

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

function settingsFieldRow(f) {
  const id = `set_${f.key}`;
  const placeholder = f.secret
    ? (f.set ? '•••••••••••••• (set — leave blank to keep)' : 'not set')
    : '';
  const value = f.secret ? '' : esc(f.value || '');
  const badge = f.locked
    ? `<span class="pill warn" style="margin-left:6px" title="A real environment variable (${esc(f.env)}) is set outside Youslop and overrides this">locked by environment</span>`
    : f.set ? `<span class="pill on" style="margin-left:6px">set</span>` : '';
  // A field with a fixed, correct set of answers gets a <select> instead of
  // free text — which model, which backend, how hard it thinks are all
  // typo-prone as text and every wrong value fails the same way: a rejected
  // API call three steps later with no hint why.
  // An unset select shows what it would actually resolve to (f.default),
  // not just whichever option happens to be listed first.
  const effective = f.value || f.default;
  const control = f.options.length
    ? `<select id="${id}" ${f.locked ? 'disabled' : ''}
         onchange="settingsDirty.add('${f.key}')">
         ${f.options.map((o) => `<option value="${esc(o.value)}"
           ${o.value === effective ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}
       </select>`
    : `<input id="${id}" type="${f.secret ? 'password' : 'text'}"
         value="${value}" placeholder="${esc(placeholder)}"
         ${f.locked ? 'disabled' : ''}
         oninput="settingsDirty.add('${f.key}')">`;
  return `
    <label class="field">
      <span>${esc(f.label)} ${badge}</span>
      ${control}
      ${f.help ? `<div class="mono" style="color:var(--ink-faint);margin-top:5px;font-size:12px">${esc(f.help)}</div>` : ''}
    </label>`;
}

async function renderSettings() {
  view.innerHTML = `<div class="empty-note">${slopLine()}</div>`;
  let data;
  try { data = await api('/api/settings'); }
  catch (e) { view.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; return; }
  settingsDirty.clear();

  const groups = [];
  for (const f of data.fields) {
    let g = groups.find((x) => x.name === f.group);
    if (!g) { g = { name: f.group, fields: [] }; groups.push(g); }
    g.fields.push(f);
  }

  view.innerHTML = `
    <h1>Settings</h1>
    <p class="sub">What used to live in a <span class="mono">.env</span> file you hand-edited.
      Changes take effect the next time Youslop starts.</p>
    <p class="mono" style="color:var(--ink-faint);margin:-8px 0 22px">
      Data folder: ${esc(data.data_dir)}</p>

    <div id="settings-groups">
      ${groups.map((g) => `
        <h2 style="font-size:15px;margin:26px 0 10px">${esc(g.name)}</h2>
        <div class="panel">
          ${g.fields.map(settingsFieldRow).join('')}
        </div>`).join('')}
    </div>

    <div class="row" style="margin-top:22px;position:sticky;bottom:18px">
      <button class="btn primary" onclick="saveSettingsForm()">save</button>
      <span class="mono" id="settings-state" style="color:var(--ink-faint)"></span>
    </div>`;
}

async function saveSettingsForm() {
  const payload = {};
  for (const key of settingsDirty) {
    const el = $(`#set_${key}`);
    if (el) payload[key] = el.value;
  }
  if (!Object.keys(payload).length) return toast('Nothing changed');
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(payload) });
    toast('Saved — takes effect next launch');
    await renderSettings();
  } catch (e) { toast(e.message, true); }
}

// One of these per loading spinner, not per repaint — picked once when a wait
// starts and held steady, so it reads as a little personality rather than a
// flicker. Kept to kitchen metaphors (the good half of "slop"): a process word,
// not a judgement on what comes out the other end.
const SLOP_LINES = [
  'Stirring the pot…', 'Reducing to a slurry…', 'Simmering the archives…',
  'Skimming the good bits off the top…', 'Filling the bucket…',
  'Slopping it together…', 'Working the vat…', 'Straining out the good stuff…',
  'Boiling it down…', 'Giving it a good stir…',
];
const slopLine = () => SLOP_LINES[Math.floor(Math.random() * SLOP_LINES.length)];

// ---------------------------------------------------------------------- jobs
function watchJob(id, kind, onDone) {
  state.job = { id, kind, since: 0, lines: [], done: null, tagline: slopLine() };
  clearInterval(state.poll);
  const step = async () => {
    let j;
    try { j = await api(`/api/jobs/${id}?since=${state.job.since}`); }
    catch { return; }
    if (!state.job || state.job.id !== id) return;
    state.job.since = j.log_total;
    state.job.lines.push(...j.log.map((l) => l.m));
    state.job.elapsed = j.elapsed;
    paintJob();
    if (j.state !== 'running') {
      clearInterval(state.poll);
      state.job.done = j.state;
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
  if (!state.job) return;
  const box = $('#joblog');
  if (box) {
    box.textContent = state.job.lines.join('\n');
    box.scrollTop = box.scrollHeight;
  }
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
  </div>`;
}

// ------------------------------------------------------------------ routing
async function route() {
  const hash = location.hash || '#/';
  const proj = hash.match(/^#\/p\/([^/]+)(?:\/(\w+))?/);
  const chan = hash.match(/^#\/c\/([^/]+)(?:\/(\w+))?/);
  const lib = hash === '#/library';
  const settingsPage = hash === '#/settings';
  const guidePage = hash === '#/guide';
  stopStream();
  if (typeof tlPause === 'function' && !(proj && proj[2] === 'render')) tlPause();
  // Every format picker (home, channel, project) paints from this, so it is
  // loaded once here rather than awaited in three places.
  await ensureSlideStyles();

  if (guidePage) {
    state.project = null;
    state.channel = null;
    state.job = null;
    renderGuide();
  } else if (settingsPage) {
    state.project = null;
    state.channel = null;
    state.job = null;
    await renderSettings();
  } else if (lib) {
    state.project = null;
    state.channel = null;
    state.job = null;
    await renderLibrary();
  } else if (proj) {
    state.channel = null;
    state.tab = proj[2] || 'script';
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
      view.innerHTML = `<div class="empty-note">${slopLine()}</div>`;
      try { state.project = await api(`/api/projects/${proj[1]}`); }
      catch (e) { view.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; return; }
      const live = (state.project.jobs || [])[0];
      if (live) watchJob(live.id, live.kind);
    }
    render();
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
      view.innerHTML = `<div class="empty-note">${slopLine()}</div>`;
      try { state.channel = await api(`/api/channels/${chan[1]}`); }
      catch (e) { view.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; return; }
      const live = (state.channel.jobs || [])[0];
      if (live) watchJob(live.id, live.kind, refreshChannel);
    }
    paintChannel();
  } else {
    state.project = null;
    state.channel = null;
    state.job = null;
    await renderHome();
  }
  await ensureChannelsLoaded();
}

window.addEventListener('hashchange', route);

// ------------------------------------------------------------------- guide
// The whole flow on one page, for someone who has never made a video here.
// Static on purpose: it names the buttons as they are labelled elsewhere in
// this file, so a renamed button wants its mention here renamed too.
function renderGuide() {
  $('#topbar-right').innerHTML = '';
  const step = (n, title, body) => `
    <div class="guide-step">
      <div class="guide-num">${n}</div>
      <div class="guide-body"><h3>${title}</h3>${body}</div>
    </div>`;

  view.innerHTML = `
    <h1>How it works</h1>
    <p class="sub">From an idea to a finished video in five tabs. Claude writes it, the
      archives supply the pictures, you (or the AI narrator) read it, and Youslop cuts it.</p>

    <div class="panel guide-before">
      <h3>Before you start</h3>
      <p>Youslop needs Claude to write scripts. Either have the
        <a href="https://claude.com/claude-code" target="_blank">Claude Code CLI</a> installed
        and signed in, or add an Anthropic API key in
        <a href="#/settings">Settings</a>.</p>
      <p>To have the script read for you instead of recording it yourself, the AI narrator
        needs two voice files. The Record tab tells you where to put them the first time you
        open it.</p>
    </div>

    <div class="guide-steps">
      ${step(1, 'Start a video', `
        <p>Open <a href="#/">New video</a> and choose how to begin:</p>
        <ul>
          <li><b>Start from an idea</b>: describe the story in a sentence or two. The more
            specific, the better the script.</li>
          <li><b>Paste a script</b>: bring your own words. <i>Faithful</i> keeps them as they
            are; <i>Adapted</i> smooths written prose into something that reads aloud well.</li>
        </ul>
        <p>Pick a target length, a tone and a video style, then press <b>Write the script</b>
          (or <b>Break it into a video</b>). It takes a few minutes: Claude writes the script,
          and the archives are searched for a picture for each paragraph.</p>`)}

      ${step(2, 'Read the script', `
        <p>The <b>Script</b> tab shows the video one paragraph at a time. Each paragraph
          becomes one recording and, by default, one picture.</p>
        <ul>
          <li><b>rewrite</b> a paragraph with an instruction, or <b>split</b> or
            <b>delete</b> it.</li>
          <li><b>check facts</b> checks the script against the research Claude did while
            writing it, and flags anything it doesn't support. Worth running after you
            edit.</li>
          <li><b>rewrite whole script</b> starts the writing over. For a pasted script,
            <b>re-split</b> breaks it into paragraphs again instead.</li>
        </ul>`)}

      ${step(3, 'Choose the pictures', `
        <p>The <b>Media</b> tab shows the picture chosen for each paragraph and the
          alternatives found. Click an alternative to use it instead.</p>
        <ul>
          <li><b>search for a picture…</b> to look for something else, or
            <b>get a map…</b> for a place.</li>
          <li>For a paragraph with no good photograph, have Claude draw a diagram or a
            custom slide instead.</li>
          <li><b>picture every</b> holds each picture across several paragraphs. Useful when
            the archives are thin on a subject.</li>
        </ul>`)}

      ${step(4, 'Record the narration', `
        <p>On the <b>Record</b> tab, choose who reads it:</p>
        <ul>
          <li><b>read it yourself</b>: press <b>● Record</b>, read the paragraph on screen,
            press stop. <kbd>space</kbd> records and stops, <kbd>→</kbd> moves to the next
            paragraph, <kbd>p</kbd> plays the take back, <kbd>r</kbd> discards it.
            <b>check the microphone</b> first to hear how your room sounds.</li>
          <li><b>AI voice</b>: pick a voice and a pace, then press <b>read the whole
            script</b>, or <b>read this paragraph</b> for just one. It runs on your computer;
            nothing is sent anywhere.</li>
        </ul>
        <p>The strip of squares at the bottom shows which paragraphs are done.
          <b>jump to next blank</b> takes you to the first one that isn't.</p>`)}

      ${step(5, 'Make a thumbnail', `
        <p>On the <b>Thumbnail</b> tab, <b>choose a picture…</b> for the background and
          type a short headline (a few words, not the title again), or press
          <b>write me some</b> for suggestions.</p>`)}

      ${step(6, 'Render', `
        <p>On the <b>Render</b> tab, adjust the look (style, drift, crossfade, colour grade)
          and the sound (music and how loud it sits under the voice).</p>
        <ul>
          <li><b>Preview cut (no voice)</b> is a quick check of the pictures and timing.</li>
          <li><b>Render the video</b> makes the finished file.</li>
          <li><b>YouTube description</b> writes the description — hook, chapters with
            timestamps and picture credits — ready to paste into YouTube.</li>
        </ul>
        <p>If the video belongs to a channel connected to YouTube, you can upload it from
          here too.</p>`)}
    </div>

    <h2>Channels</h2>
    <div class="panel guide-before">
      <p>A channel is a series. Every video in it shares the same
        opening slate, colours and defaults, so they look like they belong together.</p>
      <p>Make one with <b>new channel</b> on the New video page or the <b>＋</b> in the
        sidebar, then open it to set up its slate, music and the faces in its opening
        titles. Pick the channel when starting a video and it picks up all of that.</p>
      <p>A video doesn't need a channel. Leave it as a
        <i>standalone video</i> to just make one.</p>
    </div>

    <h2>Taking a video to another computer</h2>
    <div class="panel guide-before">
      <p>On the video's page, <b>save project file…</b> puts the whole video in one
        <span class="mono">.youslop</span> file: script, chosen pictures, recordings,
        settings, and its channel, music and style if it has them.</p>
      <p>On the other computer, press <b>open project file…</b> at the top of the
        <a href="#/">New video</a> page and pick that file. If the video is already there,
        you can replace it or keep both.</p>
      <p>The finished video isn't included, to keep the file small. Render again on the
        other computer.</p>
    </div>

    <div class="row" style="margin-top:26px">
      <button class="btn primary" onclick="go('#/')">Make a video</button>
    </div>`;
}

// -------------------------------------------------------------------- home
async function renderHome() {
  const [projects, providers, chans] = await Promise.all([
    api('/api/projects'), api('/api/providers'), api('/api/channels'),
  ]);
  state.channels = chans;
  $('#topbar-right').innerHTML = providers
    .map((p) => `<span class="pill ${p.available ? 'on' : ''}" title="${p.available ? 'ready' : 'no API key'}">
      <span class="dot"></span>${esc(p.name)}</span>`).join('');

  const byChannel = (id) => projects.filter((p) => (p.channel_id || '') === id);
  const loose = byChannel('');
  state.soloCount = loose.length;
  paintSidebar();

  view.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <h1 style="flex:1;min-width:0">Build a video</h1>
      <button class="btn ghost sm" onclick="$('#projfile').click()"
        title="a .youslop file saved from this or another computer">open project file…</button>
      <input type="file" id="projfile" accept=".youslop" style="display:none"
        onchange="openProjectFile(this.files[0]); this.value=''">
    </div>
    <p class="sub">Describe the story. Claude writes the script, the archives supply the pictures,
      you supply the voice. <a href="#/guide">New here? See how it works.</a></p>

    <div class="panel">
      <div class="tabs" style="margin:0 0 18px">
        <div class="tab ${state.mode !== 'script' ? 'active' : ''}"
             onclick="state.mode='idea';renderHome()">Start from an idea</div>
        <div class="tab ${state.mode === 'script' ? 'active' : ''}"
             onclick="state.mode='script';renderHome()">Paste a script</div>
      </div>

      ${state.mode === 'script' ? `
        <label class="field">
          <span>Your script — paste the whole thing, headings and all</span>
          <textarea id="script" rows="12" placeholder="Paste your article or script here. Newsletter furniture (subscribe prompts, image captions, links) is stripped automatically, and the text is split into paragraph-sized takes for recording."></textarea>
        </label>
        <label class="field">
          <span>How closely should it stick to your words?</span>
          <select id="fidelity">
            <option value="faithful">Faithful — keep my words, just split them for reading</option>
            <option value="adapted">Adapted — smooth written prose into speech</option>
          </select>
        </label>
      ` : `
        <label class="field">
          <span>The idea</span>
          <textarea id="idea" rows="4" placeholder="The history of YouTube slop — from Elsagate's knock-off cartoons and robot-voiced Top 10 lists to faceless AI channels uploading a video an hour, and why the algorithm kept rewarding them."></textarea>
        </label>
      `}
      <div class="grid-3">
        <label class="field">
          <span>Channel</span>
          <select id="chan" onchange="channelPicked()">
            <option value="">— standalone video —</option>
            ${chans.map((c) => `<option value="${c.id}" ${c.id === state.presetChannel ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
          </select>
        </label>
        ${state.mode === 'script' ? `
          <label class="field">
            <span>Length comes from your script</span>
            <input type="text" disabled value="measured after import">
          </label>` : `
          <label class="field">
            <span>Target length — <b id="minsLabel">12</b> minutes</span>
            <input type="range" id="mins" min="7" max="22" value="12"
                   oninput="document.getElementById('minsLabel').textContent=this.value">
          </label>`}
        <label class="field">
          <span>Tone</span>
          <select id="tone">
            <option>warm documentary</option>
            <option>cool and analytical</option>
            <option>plain and understated</option>
            <option>tense and propulsive</option>
            <option>wry and literary</option>
          </select>
        </label>
      </div>

      ${state.mode === 'script' ? '' : `
        <label class="field">
          <span>Research</span>
          <select id="research" onchange="state.newResearch=this.value">
            <option value="quick" ${(state.newResearch || 'quick') === 'quick' ? 'selected' : ''}>Quick — one search pass</option>
            <option value="deep" ${state.newResearch === 'deep' ? 'selected' : ''}>Deep — Claude's research mode, several rounds (slower, more Claude calls)</option>
          </select>
        </label>`}

      <label class="field"><span>Video style</span></label>
      ${formatPicker(state.newFormat || 'kenburns', '#E8C36A', 'pickNewFormat')}

      <label class="field">
        <span id="everyLabel">${pictureEveryLabel(state.newPictureEvery || 1)}</span>
        <input type="range" id="every" min="1" max="6" value="${state.newPictureEvery || 1}"
               oninput="state.newPictureEvery=+this.value;
                 document.getElementById('everyLabel').textContent=pictureEveryLabel(+this.value);"></label>
      <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
        1 is a new picture every paragraph. Raise it when the archives for this
        subject are likely to be thin — fewer pictures to find, each held
        longer. Changeable later on the Media tab.</div>

      <div class="row">
        <button class="btn primary" onclick="createProject()">
          ${state.mode === 'script' ? 'Break it into a video' : 'Write the script'}</button>
        <span class="mono" style="color:var(--ink-faint)">takes 1–3 minutes</span>
      </div>
    </div>

    <div class="row" id="standalone" style="margin:34px 0 14px;align-items:baseline;
         scroll-margin-top:16px">
      <h2 style="margin:0">${chans.length ? 'Standalone videos' : 'Your videos'}</h2>
      <span class="mono" style="color:var(--ink-faint)">
        ${loose.length ? `${loose.length} video${loose.length === 1 ? '' : 's'} in no channel` : ''}</span>
    </div>
    ${loose.length === 0 ? '<div class="empty-note">Bucket\'s empty. Go make some slop.</div>'
      : loose.map(projRow).join('')}

    <div class="row" style="margin:34px 0 14px;align-items:baseline">
      <h2 style="margin:0">Channels</h2>
      <span class="mono" style="color:var(--ink-faint)">shared look, shared opening slate</span>
      <div class="spacer"></div>
      <button class="btn sm" onclick="newChannel()">new channel</button>
    </div>
    ${chans.length === 0
      ? `<div class="empty-note">No channels yet. Start one and every video poured from it
           gets the same look and the same animated opening.</div>`
      : chans.map((c) => `
        <div class="proj" onclick="go('#/c/${c.id}')">
          <span class="swatch" style="background:${esc(c.accent)}"></span>
          <div style="flex:1;min-width:0">
            <div class="t">${esc(c.name)}</div>
            <div class="m">${c.videos} video${c.videos === 1 ? '' : 's'}${c.tagline ? ' · ' + esc(c.tagline) : ''}</div>
          </div>
          <span class="pill ${c.intro_ready ? 'on' : 'warn'}">
            ${c.intro_ready ? `slate: ${c.intro_images} cast` : 'no slate yet'}</span>
        </div>`).join('')}

    ${chans.filter((c) => byChannel(c.id).length).map((c) => `
      <h2>${esc(c.name)}</h2>
      ${byChannel(c.id).map(projRow).join('')}`).join('')}
  `;
  if (state.presetChannel) {
    state.presetChannel = null;
    channelPicked();
  }
  if (state.afterHome) {
    const run = state.afterHome;
    state.afterHome = null;
    run();
  }
}

// ------------------------------------------------------------ project files
// One file per video, to carry it to another computer: see app/transfer.py.
async function saveProjectFile() {
  const p = state.project;
  toast('Saving the project file…');
  try {
    // Inside the desktop app the server writes it via a native save dialog;
    // a browser tab gets a 501 and downloads it instead.
    const r = await api(`/api/projects/${p.id}/export`, { method: 'POST' });
    toast(`Saved, ${r.size_mb} MB: ${r.path}`);
  } catch (e) {
    if (e.status === 501) location.href = `/api/projects/${p.id}/export`;
    else if (e.status !== 409) toast(e.message, true);
  }
}

async function openProjectFile(file, onConflict = '') {
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  form.append('on_conflict', onConflict);
  toast(`Opening ${file.name}…`);
  try {
    const r = await api('/api/projects/import', { method: 'POST', body: form });
    const extras = [r.channel && 'its channel', r.style && `the “${r.style}” style`,
      r.music.length && `${r.music.length} music track${r.music.length === 1 ? '' : 's'}`]
      .filter(Boolean);
    toast(`Opened “${r.title}”${extras.length ? `, with ${extras.join(' and ')}` : ''}.`);
    state.channels = null;
    state.project = null;
    go(`#/p/${r.id}`);
  } catch (e) {
    if (e.status === 409 && e.detail && e.detail.already_here) {
      const replace = confirm(`“${e.detail.title}” is already on this computer.\n\n`
        + 'OK replaces it with the version in this file.\n'
        + 'Cancel keeps both, opening the file as a copy.');
      return openProjectFile(file, replace ? 'replace' : 'copy');
    }
    toast(e.message, true);
  }
}

function projRow(p) {
  return `<div class="proj" onclick="go('#/p/${p.id}')">
    ${p.thumb_at
      ? `<img class="proj-thumb" loading="lazy"
             src="/api/projects/${p.id}/file/thumb/thumb.jpg?v=${p.thumb_at}">`
      : '<div class="proj-thumb empty"></div>'}
    <div style="flex:1;min-width:0">
      <div class="t">${esc(p.title || p.idea.slice(0, 70))}</div>
      <div class="m">${p.slides} paragraphs · ${p.recorded}/${p.slides} recorded ·
        ~${fmtTime(p.est_seconds)}</div>
    </div>
    <span class="pill ${p.has_output ? 'on' : ''}">${esc(p.status)}</span>
    <button class="btn sm danger ghost"
      onclick="event.stopPropagation();delProject('${p.id}')">delete</button>
  </div>`;
}

// ------------------------------------------------------------------ library
// A shared store of hand-downloaded stock (Storyblocks Essentials has no API,
// so this is where a manual download earns its keep): tag it once here and
// it turns up in every project's picture search from then on, ranked
// alongside the archives — see thumbUrl() and Library in media/providers.py.
state.library = { items: [], q: '', kind: '', file: null };

async function renderLibrary() {
  const [items, folders] = await Promise.all([
    api('/api/library'), api('/api/library/folders'),
  ]);
  state.library.items = items;
  state.library.folders = folders;
  view.innerHTML = `
    <h1>Library</h1>
    <p class="sub">Your own royalty-free stock — downloaded by hand, tagged here,
      and searched alongside the archives for every slide in every project.</p>

    ${jobPanel()}

    <div class="card" style="margin-bottom:22px">
      <h3>Linked folders</h3>
      <p class="mono" style="color:var(--ink-faint);margin:-4px 0 14px">
        Point this at a folder of your own photos or footage and it is indexed
        in place — nothing is copied, only a small thumbnail per file. Rescan
        any time to pick up what changed.</p>
      ${folders.map((f) => `
        <div class="row" style="margin-bottom:8px;padding:9px 12px;background:#0f1116;
             border:1px solid var(--line-soft);border-radius:8px">
          <div style="flex:1;min-width:0">
            <strong>${esc(f.label || f.path.split('/').pop())}</strong>
            ${f.exists ? '' : '<span class="pill warn" style="margin-left:6px">missing</span>'}
            <div class="mono" style="color:var(--ink-faint);font-size:12px;
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(f.path)}</div>
          </div>
          <span class="mono" style="color:var(--ink-faint)">${f.asset_count} asset${f.asset_count === 1 ? '' : 's'}</span>
          <button class="btn sm ghost" onclick="rescanLibraryFolder('${f.id}')">rescan</button>
          <button class="btn sm ghost" onclick="removeLibraryFolder('${f.id}')">remove</button>
        </div>`).join('') || `<div class="empty-note" style="padding:14px">no folders linked yet</div>`}
      <div class="row" style="margin-top:10px">
        <input type="text" id="libfolderpath" placeholder="/path/to/your/photos"
          style="flex:1;min-width:220px">
        <button class="btn sm ghost" id="libfolderbrowse" onclick="browseForLibraryFolder()">browse…</button>
        <button class="btn sm primary" onclick="addLibraryFolder()">add folder</button>
      </div>
    </div>

    <div class="card" style="margin-bottom:22px">
      <h3>Add a single file</h3>
      <div class="row" style="margin-bottom:10px">
        <label class="btn sm" style="cursor:pointer">choose a file
          <input type="file" id="libfile" accept="image/*,video/*" hidden
            onchange="pickLibraryFile(this.files[0])"></label>
        <span class="mono" id="libfilename" style="color:var(--ink-faint)">no file chosen</span>
      </div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="libtitle" placeholder="title" style="flex:1;min-width:200px">
        <input type="text" id="libtags" placeholder="tags, comma separated" style="flex:1;min-width:200px">
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="libauthor" placeholder="author / photographer" style="flex:1;min-width:160px">
        <input type="text" id="liblicense" placeholder="licence — e.g. “Storyblocks (Essentials)”"
          style="flex:1;min-width:220px">
        <input type="text" id="libsource" placeholder="source page (optional)" style="flex:1;min-width:220px">
      </div>
      <button class="btn sm primary" id="libadd" onclick="uploadLibraryAsset()">add to library</button>
    </div>

    <div class="row" style="margin-bottom:16px">
      <input type="text" id="libq" placeholder="search title or tags…"
        style="flex:1;min-width:220px" value="${esc(state.library.q)}" oninput="filterLibrary()">
      <select id="libkind" style="width:auto" onchange="filterLibrary()">
        <option value="" ${state.library.kind === '' ? 'selected' : ''}>photos & clips</option>
        <option value="image" ${state.library.kind === 'image' ? 'selected' : ''}>photos only</option>
        <option value="video" ${state.library.kind === 'video' ? 'selected' : ''}>clips only</option>
      </select>
      <span class="mono" id="libcount" style="color:var(--ink-faint)"></span>
    </div>
    <div class="lib-grid" id="libgrid"></div>
  `;
  paintLibraryGrid();
}

// --------------------------------------------------------------- folders
async function browseForLibraryFolder() {
  try {
    const r = await api('/api/pick-folder', { method: 'POST' });
    $('#libfolderpath').value = r.path;
  } catch (e) {
    // 501 here just means "not running inside the desktop app" — the text
    // field below is the fallback, not an error worth a toast over.
    if (!String(e.message).includes('501')) toast(e.message, true);
  }
}

async function addLibraryFolder() {
  const path = $('#libfolderpath').value.trim();
  if (!path) return toast('Enter a folder path first.', true);
  try {
    const f = await api('/api/library/folders', {
      method: 'POST', body: JSON.stringify({ path }),
    });
    toast('Folder added — scanning…');
    await renderLibrary();
    await rescanLibraryFolder(f.id);
  } catch (e) { toast(e.message, true); }
}

async function rescanLibraryFolder(folderId) {
  const r = await api(`/api/library/folders/${folderId}/scan`, { method: 'POST' });
  watchJob(r.job, 'library scan', async () => { await renderLibrary(); });
  await renderLibrary();   // paints the now-set state.job so ticks have
                            // #joblog/#jobstate to update in place
}

async function removeLibraryFolder(folderId) {
  if (!confirm('Stop tracking this folder? Its entries leave the library — ' +
               'the files on disk are never touched.')) return;
  await api(`/api/library/folders/${folderId}`, { method: 'DELETE' });
  toast('Folder removed from the library.');
  await renderLibrary();
}

function pickLibraryFile(file) {
  state.library.file = file || null;
  $('#libfilename').textContent = file ? file.name : 'no file chosen';
  if (file && !$('#libtitle').value) {
    $('#libtitle').value = file.name.replace(/\.[a-z0-9]+$/i, '').replace(/[_-]+/g, ' ');
  }
}

async function uploadLibraryAsset() {
  const file = state.library.file;
  if (!file) return toast('Choose a file first.', true);
  const btn = $('#libadd');
  btn.disabled = true;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('title', $('#libtitle').value.trim());
  fd.append('tags', $('#libtags').value.trim());
  fd.append('author', $('#libauthor').value.trim());
  fd.append('license', $('#liblicense').value.trim());
  fd.append('source_page', $('#libsource').value.trim());
  try {
    await api('/api/library', { method: 'POST', body: fd });
    toast('Added to the library.');
    await renderLibrary();
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
  }
}

function filterLibrary() {
  state.library.q = $('#libq').value;
  state.library.kind = $('#libkind').value;
  paintLibraryGrid();
}

function paintLibraryGrid() {
  const grid = $('#libgrid');
  if (!grid) return;
  const q = state.library.q.trim().toLowerCase();
  const kind = state.library.kind;
  const items = state.library.items.filter((a) => {
    if (kind && a.kind !== kind) return false;
    if (!q) return true;
    return a.title.toLowerCase().includes(q) || a.tags.some((t) => t.toLowerCase().includes(q));
  });
  $('#libcount').textContent = `${items.length} asset${items.length === 1 ? '' : 's'}`;
  grid.innerHTML = items.map((a) => `
    <div class="lib-card">
      <div class="lib-thumb">
        <img src="/api/library/thumb/${a.id}" loading="lazy" onerror="this.parentNode.style.opacity=.25">
        ${a.kind === 'video' ? `<span class="kindtag">clip · ${fmtTime(a.duration)}</span>` : ''}
      </div>
      <div class="lib-body">
        <div class="lib-title" title="${esc(a.title)}">${esc(a.title)}</div>
        <div class="lib-meta">${a.width || '?'}×${a.height || '?'}${esc(a.author ? ' · ' + a.author : '')}</div>
        <div class="lib-tags">
          ${a.tags.map((t) => `<span class="pill">${esc(t)}</span>`).join('') || ''}
        </div>
        <div class="row">
          <button class="btn xs ghost" onclick="editLibraryAsset('${a.id}')">edit</button>
          <button class="btn xs ghost danger" onclick="deleteLibraryAsset('${a.id}')">delete</button>
        </div>
      </div>
    </div>`).join('') || '<div class="empty-note">Bucket\'s empty — add your first download above.</div>';
}

function editLibraryAsset(id) {
  const a = state.library.items.find((x) => x.id === id);
  if (!a) return;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:14px">
        <strong>Edit asset</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="ecancel">cancel</button>
      </div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="etitle" placeholder="title" style="flex:1;min-width:200px" value="${esc(a.title)}">
        <input type="text" id="etags" placeholder="tags, comma separated" style="flex:1;min-width:200px"
          value="${esc(a.tags.join(', '))}">
      </div>
      <div class="row" style="margin-bottom:14px">
        <input type="text" id="eauthor" placeholder="author" style="flex:1;min-width:160px" value="${esc(a.author)}">
        <input type="text" id="elicense" placeholder="licence" style="flex:1;min-width:200px" value="${esc(a.license)}">
        <input type="text" id="esource" placeholder="source page" style="flex:1;min-width:200px" value="${esc(a.source_page)}">
      </div>
      <button class="btn sm primary" id="esave">save</button>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  wrap.querySelector('#ecancel').onclick = close;
  wrap.querySelector('#esave').onclick = async () => {
    try {
      await api(`/api/library/${id}`, { method: 'PATCH', body: JSON.stringify({
        title: wrap.querySelector('#etitle').value.trim(),
        tags: wrap.querySelector('#etags').value.split(',').map((t) => t.trim()).filter(Boolean),
        author: wrap.querySelector('#eauthor').value.trim(),
        license: wrap.querySelector('#elicense').value.trim(),
        source_page: wrap.querySelector('#esource').value.trim(),
      }) });
      close();
      await renderLibrary();
    } catch (e) { toast(e.message, true); }
  };
}

async function deleteLibraryAsset(id) {
  if (!confirm('Remove this asset from the library? Projects that already used it keep their own copy.')) return;
  try {
    await api(`/api/library/${id}`, { method: 'DELETE' });
    state.library.items = state.library.items.filter((a) => a.id !== id);
    paintLibraryGrid();
  } catch (e) { toast(e.message, true); }
}

function channelPicked() {
  const c = (state.channels || []).find((x) => x.id === $('#chan').value);
  // Standalone again: back to this form's own defaults rather than whatever
  // the last-picked channel left behind.
  state.newFormat = c ? c.format : 'kenburns';
  state.newPictureEvery = c ? (c.picture_every || 1) : 1;
  const strip = $('#fmtpicker');
  if (strip) strip.querySelectorAll('.tpl').forEach((el) =>
    el.classList.toggle('sel', el.dataset.fmt === state.newFormat));
  const every = $('#every'), label = $('#everyLabel');
  if (every) every.value = state.newPictureEvery;
  if (label) label.textContent = pictureEveryLabel(state.newPictureEvery);
  if (c) toast(`New videos will use “${c.name}”’s look and opening slate.`);
}

function pictureEveryLabel(n) {
  return `New picture every — ${n} ${n === 1 ? 'paragraph' : 'paragraphs'}`;
}

async function createProject() {
  const scripting = state.mode === 'script';
  const body = { tone: $('#tone').value, channel_id: $('#chan').value || '',
                 format: state.newFormat || 'kenburns',
                 picture_every: state.newPictureEvery || 1 };

  if (scripting) {
    const script = $('#script').value.trim();
    if (script.split(/\s+/).length < 120) {
      return toast('Paste a bit more — that is too short to build a video from.', true);
    }
    body.script = script;
    body.fidelity = $('#fidelity').value;
  } else {
    body.idea = $('#idea').value.trim();
    if (body.idea.length < 8) return toast('Give me a sentence or two to work with.', true);
    body.target_minutes = +$('#mins').value;
    body.research_mode = $('#research').value;
  }

  const btn = event.target;
  btn.disabled = true;
  try {
    const r = await api('/api/projects', { method: 'POST', body: JSON.stringify(body) });
    state.project = r.project;
    go(`#/p/${r.project.id}`);
    await route();
    watchJob(r.job, scripting ? 'import' : 'script');
  } catch (e) { toast(e.message, true); btn.disabled = false; }
}

async function newChannel() {
  const name = prompt('Channel name\n(this is the title on the opening slate)', 'Your channel name');
  if (!name) return;
  const concept = prompt('What does this channel cover?\nThis steers the scripts and who appears in the opening titles.',
    '') || '';
  try {
    const c = await api('/api/channels', { method: 'POST', body: JSON.stringify({ name, concept }) });
    state.channels = null;   // the sidebar's cache — force it to pick up the new one
    go(`#/c/${c.id}`);
    await route();
  } catch (e) { toast(e.message, true); }
}

async function delProject(id) {
  if (!confirm('Delete this project and everything in it?')) return;
  await api(`/api/projects/${id}`, { method: 'DELETE' });
  renderHome();
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

async function setSlideFocal(sid, cid) {
  const s = state.project.slides.find((x) => x.id === sid);
  const cand = s.candidates.find((c) => c.id === cid);
  if (!cand) return;
  openFocal(thumbUrl(cand), cand.focal, async (focal) => {
    cand.focal = focal;
    paintMedia();
    await saveSlide(sid, { focal, focal_id: cid });
  });
}

function setCastFocal(i) {
  const c = state.channel;
  const img = (c.intro.images || [])[i];
  if (!img) return toast('Fetch the portraits first.', true);
  const current = (c.intro.focals || [])[i] || [];
  openFocal(`/api/channels/${c.id}/file/${img}?v=${c.updated_at}`, current, (focal) => {
    const focals = [...(c.intro.focals || [])];
    while (focals.length < c.intro.images.length) focals.push([]);
    focals[i] = focal;
    saveIntro({ focals });
  });
}

// ----------------------------------------------------------------- channel
async function refreshChannel() {
  state.channel = await api(`/api/channels/${state.channel.id}`);
  paintChannel();
}

// A 140×78 sketch of the three ways a picture can sit on screen — "I need to
// be able to select templates for videos, with a basic preview" — matching
// the same illustrative-icon pattern tplArt/thumbArt already use elsewhere,
// so this is one more instance of a pattern rather than a new one.
function formatArt(key, accent) {
  const a = esc(accent);
  const svg = {
    kenburns: `<rect width="140" height="78" fill="#1c222c"/>
      <rect x="-6" y="-4" width="152" height="90" fill="#2a3444"/>
      <circle cx="96" cy="26" r="30" fill="#374254" opacity=".6"/>
      <rect x="0" y="54" width="140" height="24" fill="#000" opacity=".38"/>
      <rect x="10" y="60" width="5" height="12" fill="${a}"/>
      <rect x="20" y="61" width="52" height="4" fill="#fff"/>
      <rect x="20" y="68" width="34" height="3" fill="#9aa0b0"/>`,
    essay: `<rect width="140" height="78" fill="#15171c"/>
      <rect x="0" y="0" width="140" height="78" fill="#1e222b"/>
      <rect x="30" y="8" width="80" height="46" fill="#2a3444"/>
      <rect x="30" y="8" width="80" height="46" fill="none" stroke="${a}" stroke-width="3"/>
      <rect x="18" y="60" width="104" height="7" fill="#fff" opacity=".92"/>
      <rect x="30" y="70" width="80" height="5" fill="#fff" opacity=".55"/>`,
    board: `<rect width="140" height="78" fill="#3A4552"/>
      <path d="M12 20h46" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M12 24h30" stroke="${a}" stroke-width="2" stroke-linecap="round"/>
      <path d="M14 38h10M14 50h10M14 62h10" stroke="#aab0bc" stroke-width="2" stroke-linecap="round"/>
      <path d="M30 38h58M30 50h46M30 62h50" stroke="#fff" stroke-width="2.6" stroke-linecap="round" opacity=".9"/>`,
    flameboat: `<rect width="140" height="78" fill="#0E1014"/>
      <rect x="22" y="14" width="96" height="50" rx="4" fill="#151922" stroke="#2A3140"/>
      <circle cx="29" cy="20" r="2" fill="#FF5F57"/><circle cx="35" cy="20" r="2" fill="#FEBC2E"/>
      <circle cx="41" cy="20" r="2" fill="#28C840"/>
      <rect x="28" y="30" width="22" height="4" fill="#FF7AB6"/><rect x="53" y="30" width="30" height="4" fill="#5FD4FF"/>
      <rect x="24" y="39" width="92" height="7" fill="${a}" opacity=".3"/>
      <rect x="34" y="40" width="44" height="4" fill="#E8EAF0"/>
      <rect x="28" y="51" width="36" height="4" fill="#A8E07A"/>`,
    casefile: `<defs><radialGradient id="cfv"><stop offset=".55" stop-color="#000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000" stop-opacity=".7"/></radialGradient></defs>
      <rect width="140" height="78" fill="#5a3a20"/>
      <rect x="18" y="12" width="34" height="40" fill="#efe9dc" transform="rotate(-5 35 32)"/>
      <rect x="22" y="15" width="26" height="25" fill="#3b4a5c" transform="rotate(-5 35 32)"/>
      <rect x="78" y="30" width="44" height="28" fill="#f6f2e6" transform="rotate(4 100 44)"/>
      <rect x="80" y="38" width="38" height="1.5" fill="#d65c5c" transform="rotate(4 100 44)"/>
      <circle cx="35" cy="16" r="2.6" fill="#b21c22"/><circle cx="99" cy="31" r="2.6" fill="#b21c22"/>
      <rect width="140" height="78" fill="url(#cfv)"/>`,
    loudmouth: `<rect width="140" height="78" fill="#0B0B0D"/>
      <text x="16" y="24" font-family="sans-serif" font-size="9" font-weight="700" fill="#8D8A84">you are not</text>
      <text x="14" y="50" font-family="sans-serif" font-size="27" font-weight="900" fill="${a}">behind.</text>
      <text x="122" y="16" font-family="sans-serif" font-size="13" font-weight="900" fill="#F4F1EA"
        transform="rotate(90 122 16)">too late</text>
      <text x="16" y="68" font-family="sans-serif" font-size="13" font-weight="900" fill="#F4F1EA">decide.</text>`,
    groupchat: `<rect width="140" height="78" fill="#1d2433"/>
      <rect x="34" y="4" width="72" height="70" rx="8" fill="#0B0B0F"/>
      <rect x="34" y="4" width="72" height="12" rx="6" fill="#16161C"/>
      <rect x="40" y="22" width="34" height="9" rx="4.5" fill="#26262E"/>
      <rect x="62" y="35" width="38" height="9" rx="4.5" fill="#2E7CF6"/>
      <rect x="40" y="48" width="28" height="9" rx="4.5" fill="#26262E"/>
      <circle cx="46" cy="64" r="1.6" fill="#8C8C99"/><circle cx="51" cy="64" r="1.6" fill="#8C8C99"/>
      <circle cx="56" cy="64" r="1.6" fill="#8C8C99"/>`,
    ticker: `<rect width="140" height="78" fill="#060A12"/>
      <rect width="140" height="8" fill="#0C1220"/>
      <path d="M14 56 L34 48 L52 52 L72 34 L92 38 L112 20 L126 24" stroke="#1FD686" stroke-width="2.4" fill="none"/>
      <path d="M14 56 L34 48 L52 52 L72 34 L92 38 L112 20 L126 24 L126 66 L14 66Z" fill="#1FD686" opacity=".14"/>
      <circle cx="126" cy="24" r="3" fill="#1FD686"/>
      <rect x="14" y="12" width="34" height="3" fill="${a}"/>`,
  }[key] || '<rect width="140" height="78" fill="#14151a"/>';
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">${svg}</svg>`;
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

// `onPick(key)` is called with the chosen key; the caller decides whether
// that means an immediate save-and-repaint (an existing project or channel)
// or just remembering the choice for a form that hasn't been submitted yet
// (the home page, before a project exists to save it to).
function formatPicker(current, accent, onPickName) {
  current = current || 'kenburns';
  const saved = state.slideStyles || [];
  return `<div class="tpl-strip" id="fmtpicker">
    ${FORMAT_INFO.map((f) => `
      <div class="tpl ${f.key === current ? 'sel' : ''}" data-fmt="${f.key}"
           onclick="${onPickName}('${f.key}')">
        ${formatArt(f.key, accent)}
        <div class="tpl-name">${esc(f.label)}</div>
        <div class="tpl-cast">${esc(f.blurb)}</div>
      </div>`).join('')}
    ${saved.map((s) => {
      const key = `custom:${s.id}`;
      return `<div class="tpl ${key === current ? 'sel' : ''}" data-fmt="${esc(key)}"
           onclick="${onPickName}('${esc(key)}')">
        <img class="tpl-art" src="/api/slide-styles/${s.id}/thumb.jpg"
             style="object-fit:cover" loading="lazy">
        <div class="tpl-name">${esc(s.name)}</div>
        <div class="tpl-cast">your style · ${s.slots} slot${s.slots === 1 ? '' : 's'}
          <button class="btn xs ghost" style="margin-left:6px" title="export this style as a file"
            onclick="event.stopPropagation();exportSlideStyle('${s.id}','${esc(s.name).replace(/'/g, "\\'")}')">↓</button>
          <button class="btn xs ghost danger" style="margin-left:4px"
            onclick="event.stopPropagation();deleteSlideStyle('${s.id}')">×</button></div>
      </div>`;
    }).join('')}
    <div class="tpl" id="newstyletile" onclick="openStyleDesigner()"
         title="describe a look and have Claude design it">
      <svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">
        <rect width="140" height="78" fill="#13151c"/>
        <rect x="8" y="8" width="124" height="62" fill="none" stroke="${esc(accent)}"
              stroke-width="2" stroke-dasharray="6 5" opacity=".75"/>
        <path d="M70 28v22M59 39h22" stroke="${esc(accent)}" stroke-width="3"
              stroke-linecap="round"/>
      </svg>
      <div class="tpl-name">Design a style…</div>
      <div class="tpl-cast">describe a look, Claude draws it</div>
    </div>
    <label class="tpl" id="importstyletile" style="cursor:pointer"
           title="add a style someone exported">
      <svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">
        <rect width="140" height="78" fill="#13151c"/>
        <rect x="8" y="8" width="124" height="62" fill="none" stroke="#565c6c"
              stroke-width="2" stroke-dasharray="6 5" opacity=".75"/>
        <path d="M70 24v20M62 34l8 10 8-10M58 56h24" fill="none" stroke="#9aa0b0"
              stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <div class="tpl-name">Import a style…</div>
      <div class="tpl-cast">add a style file someone shared</div>
      <input type="file" accept=".json,application/json" hidden
             onchange="importSlideStyle(this.files[0]);this.value=''">
    </label>
  </div>`;
}

async function exportSlideStyle(id, name) {
  try {
    const res = await fetch(`/api/slide-styles/${id}/export`);
    if (!res.ok) throw new Error((await res.json()).detail || 'export failed');
    const blob = await res.blob();
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'style';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${slug}.youslop-style.json`;
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
    route();
  } catch (e) { toast(e.message, true); }
}

// The home form's own picker: nothing exists to save to yet, so a pick just
// updates state and repaints the strip in place — the surrounding idea/script
// textarea must not be touched, or a half-typed idea would vanish under the
// user's cursor.
function pickNewFormat(key) {
  state.newFormat = key;
  const strip = $('#fmtpicker');
  if (!strip) return;
  strip.querySelectorAll('.tpl').forEach((el) =>
    el.classList.toggle('sel', el.dataset.fmt === key));
}

// A 140×78 sketch of each slate, so the picker shows the shape of the thing
// rather than seven lines of prose. Accent-coloured parts mirror the channel's.
function tplArt(key, accent) {
  const a = esc(accent), ink = '#8d93a2', dim = '#2b2f3a';
  const svg = {
    columns: `<rect width="140" height="78" fill="#0c0d11"/>
      ${[0, 1, 2, 3, 4].map((i) => `<rect x="${2 + i * 27.6}" y="2" width="25" height="74"
        fill="${i % 2 ? '#232732' : '#161a22'}"/>`).join('')}
      <rect x="34" y="36" width="72" height="3" fill="${a}"/>`,
    signal: `<rect width="140" height="78" fill="#0a0b0f"/>
      ${[18, 38, 58].map((y) => `<line x1="0" y1="${y}" x2="140" y2="${y}" stroke="#181c24"/>`).join('')}
      <rect x="16" y="26" width="70" height="12" fill="${ink}"/>
      <rect x="88" y="26" width="6" height="12" fill="${a}"/>
      <rect x="16" y="44" width="44" height="12" fill="${dim}"/>
      <rect x="10" y="20" width="3" height="42" fill="${a}"/>`,
    dossier: `<rect width="140" height="78" fill="#111114"/>
      <rect x="6" y="5" width="128" height="68" fill="none" stroke="${a}" stroke-width="1.5"/>
      <rect x="18" y="18" width="52" height="10" fill="${ink}"/>
      <rect x="70" y="18" width="42" height="10" fill="#17171b" stroke="${a}" stroke-width="1"/>
      ${[40, 48, 56].map((y) => `<rect x="18" y="${y}" width="${58 - (y - 40)}" height="3" fill="${dim}"/>`).join('')}
      <g transform="rotate(-9 104 56)"><rect x="86" y="46" width="36" height="18" fill="none"
        stroke="${a}" stroke-width="2"/></g>`,
    filmstrip: `<rect width="140" height="78" fill="#0a0a0c"/>
      <rect x="0" y="16" width="140" height="46" fill="#12141a"/>
      ${[6, 40, 74, 108].map((x) => `<rect x="${x}" y="19" width="28" height="40" fill="#232732"/>`).join('')}
      ${[4, 24, 44, 64, 84, 104, 124].map((x) => `<rect x="${x}" y="4" width="10" height="6" rx="1.5" fill="#2c303a"/>
        <rect x="${x}" y="68" width="10" height="6" rx="1.5" fill="#2c303a"/>`).join('')}
      <rect x="0" y="14" width="140" height="1.5" fill="${a}"/>`,
    mosaic: `<rect width="140" height="78" fill="#0c0d11"/>
      ${[0, 1, 2].map((r) => [0, 1, 2, 3].map((cc) => `<rect x="${cc * 35 + 1}" y="${r * 26 + 1}"
        width="33" height="24" fill="${(r + cc) % 3 ? '#1c2029' : '#262b36'}"/>`).join('')).join('')}
      <rect x="0" y="30" width="140" height="18" fill="#0a0b0f" opacity=".92"/>
      <rect x="0" y="30" width="140" height="1.5" fill="${a}"/>
      <rect x="0" y="46.5" width="140" height="1.5" fill="${a}"/>
      <rect x="46" y="36" width="48" height="6" fill="${ink}"/>`,
    pulse: `<rect width="140" height="78" fill="#0b0c10"/>
      <rect x="24" y="20" width="92" height="7" fill="${ink}"/>
      <line x1="0" y1="56" x2="140" y2="56" stroke="${a}" stroke-width="1.5"/>
      ${Array.from({ length: 22 }, (_, i) => {
        const h = 3 + 13 * Math.abs(Math.sin(i * 1.1)) * Math.sin(Math.PI * (i + 0.5) / 22);
        return `<rect x="${i * 6.4 + 1}" y="${56 - h}" width="4" height="${h * 2}" fill="${a}" opacity=".62"/>`;
      }).join('')}`,
    atlas: `<rect width="140" height="78" fill="#080a0c"/>
      ${[0, 1, 2].map((i) => `<ellipse cx="46" cy="44" rx="${14 + i * 11}" ry="${10 + i * 8}"
        fill="none" stroke="${i === 2 ? a : '#22262e'}" stroke-width="1"/>`).join('')}
      <line x1="0" y1="34" x2="140" y2="34" stroke="${a}" stroke-width=".8" opacity=".45"/>
      <line x1="92" y1="0" x2="92" y2="78" stroke="${a}" stroke-width=".8" opacity=".45"/>
      <g stroke="${a}" stroke-width="2" fill="none">
        <path d="M78 20h-6v6M106 20h6v6M78 48h-6v-6M106 48h6v-6"/></g>
      <circle cx="92" cy="34" r="3" fill="none" stroke="${a}" stroke-width="1.5"/>`,
    dial: `<rect width="140" height="78" fill="#0a0b0f"/>
      <circle cx="70" cy="39" r="33" fill="#15181f" stroke="${a}" stroke-width="1.4"/>
      ${[0,1,2,3,4,5,6,7,8,9,10,11].map((h) => {
        const r = h * 30 * Math.PI / 180;
        const s = Math.sin(r), c = -Math.cos(r);
        return `<line x1="${70 + s * 29}" y1="${39 + c * 29}"
                      x2="${70 + s * 24}" y2="${39 + c * 24}"
                      stroke="${a}" stroke-width="${h % 3 ? 1.4 : 2.2}"/>`;
      }).join('')}
      <line x1="70" y1="39" x2="${70 - 14}" y2="${39 - 10}" stroke="${a}" stroke-width="2.4"/>
      <line x1="70" y1="39" x2="${70 + 18}" y2="${39 - 11}" stroke="${a}" stroke-width="1.8"/>
      <circle cx="70" cy="39" r="2.2" fill="${a}"/>
      <rect x="57" y="20" width="26" height="3" rx="1" fill="${ink}"/>
      <rect x="52" y="54" width="36" height="2.4" rx="1" fill="${dim}"/>`,
    arcade: `<rect width="140" height="78" fill="#1b0f3a"/>
      ${[0, 1, 2, 3].map((r) => [0, 1, 2, 3, 4].map((c) => `<rect
        x="${c * 30 + (r % 2 ? 6 : -9)}" y="${r * 20 + 4}" width="9" height="7" rx="2"
        fill="${c % 2 ? a : ink}" opacity=".26"/>`).join('')).join('')}
      <rect x="26" y="24" width="86" height="15" fill="${a}" opacity=".9"/>
      <rect x="30" y="27" width="86" height="15" fill="#fff"/>
      <rect x="38" y="46" width="70" height="15" fill="${a}" opacity=".9"/>
      <rect x="42" y="49" width="70" height="15" fill="#fff"/>
      <rect x="46" y="70" width="48" height="3" fill="${a}"/>`,
    gloss: `<rect width="140" height="78" fill="#f6dce6"/>
      <ellipse cx="70" cy="34" rx="58" ry="34" fill="#fdeef4"/>
      ${[[18, 14], [116, 20], [30, 62], [110, 58], [64, 10]].map(([x, y]) =>
        `<path d="M${x} ${y - 5}l1.6 3.4 3.4 1.6-3.4 1.6-1.6 3.4-1.6-3.4-3.4-1.6 3.4-1.6z"
          fill="#fff"/>`).join('')}
      <rect x="34" y="34" width="72" height="10" fill="#3a2a31"/>
      <rect x="46" y="26" width="48" height="2.4" fill="${a}"/>
      <rect x="42" y="50" width="56" height="1.6" fill="${a}"/>`,
    kickoff: `<rect width="140" height="78" fill="#0b2545"/>
      ${[0, 1, 2, 3, 4, 5].map((i) => `<path d="M${i * 26 - 14} 78L${i * 26 + 8} 0h11L${i * 26 - 3} 78z"
        fill="${a}" opacity=".85"/>`).join('')}
      <path d="M0 26l140-16v46L0 66z" fill="#0d1c2e" opacity=".96"/>
      <rect x="0" y="24" width="140" height="2.6" fill="${a}"
        transform="rotate(-6.5 70 39)"/>
      <g transform="rotate(-6.5 70 39)"><rect x="34" y="32" width="58" height="13" fill="#fff"/>
        <rect x="46" y="20" width="34" height="7" fill="${a}"/></g>`,
    stack: `<rect width="140" height="78" fill="#160810"/>
      ${[0, 1, 2, 3].map((r) => `<text x="${-14 + r * 9}" y="${16 + r * 20}"
        font-family="Helvetica" font-weight="bold" font-size="17"
        fill="${r % 2 ? 'none' : a}" stroke="${r % 2 ? a : 'none'}" stroke-width="1"
        opacity=".55" transform="rotate(-9 70 39)">NAME NAME NAME</text>`).join('')}
      <rect x="0" y="28" width="140" height="24" fill="#160810" opacity=".95"/>
      <rect x="0" y="27" width="140" height="1.8" fill="${a}"/>
      <rect x="0" y="52" width="140" height="1.8" fill="${a}"/>
      <rect x="40" y="35" width="60" height="10" fill="#fff"/>`,
    tiles: `<rect width="140" height="78" fill="#efe3cf"/>
      ${[0, 1, 2].map((r) => [0, 1, 2, 3, 4].map((c) => `<rect x="${c * 28 + 1}"
        y="${r * 26 + 1}" width="26" height="24"
        fill="${(r + c) % 2 ? '#e8b7a4' : '#c8d3ac'}"/>`).join('')).join('')}
      <rect x="24" y="20" width="92" height="38" rx="3" fill="#fdfbf6"
        stroke="${a}" stroke-width="1.6"/>
      <rect x="44" y="26" width="52" height="3" fill="${a}"/>
      <rect x="36" y="34" width="68" height="9" fill="#2e241c"/>
      <rect x="48" y="46" width="44" height="7" fill="#2e241c"/>`,
    folio: `<rect width="140" height="78" fill="#cec7b8"/>
      <rect x="9" y="0" width="131" height="78" fill="#eee9de"/>
      <rect x="9" y="0" width="2" height="78" fill="#b4ab98"/>
      <rect x="40" y="14" width="70" height="1.6" fill="${a}"/>
      <rect x="48" y="18" width="54" height="1" fill="${a}" opacity=".7"/>
      <rect x="52" y="26" width="46" height="3" fill="#8d8676"/>
      <rect x="38" y="35" width="74" height="9" fill="#26231f"/>
      <rect x="50" y="48" width="50" height="9" fill="#26231f"/>
      <rect x="52" y="63" width="14" height="1.4" fill="${a}"/>
      <rect x="84" y="63" width="14" height="1.4" fill="${a}"/>
      <path d="M75 60l4 3.7-4 3.7-4-3.7z" fill="${a}"/>`,
  }[key] || '<rect width="140" height="78" fill="#14151a"/>';
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">${svg}</svg>`;
}

// The same 140×78 treatment for the end screens. What each sketch has to show
// is where the plates are, because that is the whole difference between them.
function endArt(key, accent) {
  const a = esc(accent), ink = '#8d93a2', panel = '#1a1e26';
  const plate = (x, y, w, h, r = 2) =>
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${panel}"
       stroke="${a}" stroke-width=".8" stroke-opacity=".55"/>`;
  const svg = {
    twoup: `<rect width="140" height="78" fill="#0c0d11"/>
      <circle cx="26" cy="42" r="11" fill="none" stroke="${a}" stroke-width="1.4"/>
      <rect x="42" y="38" width="24" height="8" rx="4" fill="${a}" opacity=".8"/>
      <rect x="15" y="18" width="46" height="6" fill="${ink}"/>
      ${plate(74, 26, 28, 28)}${plate(106, 26, 28, 28)}
      <rect x="74" y="19" width="60" height="3" fill="${ink}" opacity=".7"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    marquee: `<rect width="140" height="78" fill="#0b0c10"/>
      <rect x="28" y="8" width="84" height="10" fill="${ink}"/>
      <rect x="50" y="23" width="40" height="1.6" fill="${a}"/>
      ${plate(20, 30, 46, 26)}${plate(74, 30, 46, 26)}
      <circle cx="58" cy="66" r="7" fill="none" stroke="${a}" stroke-width="1.2"/>
      <rect x="70" y="62" width="22" height="8" rx="4" fill="${a}" opacity=".8"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    afterglow: `<rect width="140" height="78" fill="#1b1d22"/>
      <ellipse cx="44" cy="26" rx="34" ry="24" fill="#2b2f38"/>
      <ellipse cx="104" cy="46" rx="30" ry="26" fill="#23262e"/>
      <rect y="34" width="140" height="44" fill="#07080b" opacity=".72"/>
      <circle cx="24" cy="34" r="9" fill="none" stroke="${a}" stroke-width="1.3"/>
      <rect x="13" y="52" width="40" height="6" fill="${ink}"/>
      ${plate(74, 30, 28, 28)}${plate(106, 30, 28, 28)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    console: `<rect width="140" height="78" fill="#0a0b0f"/>
      ${[0, 1, 2, 3].map((i) => `<line x1="0" y1="${i * 20 + 9}" x2="140" y2="${i * 20 + 9}"
        stroke="#171b22"/><line x1="${i * 36 + 10}" y1="0" x2="${i * 36 + 10}" y2="78"
        stroke="#171b22"/>`).join('')}
      <rect x="8" y="12" width="4" height="18" fill="${a}"/>
      <rect x="17" y="14" width="52" height="9" fill="${ink}"/>
      <circle cx="122" cy="20" r="10" fill="none" stroke="${a}" stroke-width="1.3"/>
      ${[16, 54, 92].map((x) => plate(x, 40, 32, 28)).join('')}
      ${[16, 54, 92].map((x) => `<path fill="none" stroke="${a}" stroke-width="1.4"
        d="M${x} 46V40h6 M${x + 32} 40h-6 M${x + 32} 40v6
           M${x} 62v6h6 M${x + 32} 68h-6 M${x + 32} 68v-6"/>`).join('')}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    ledger: `<rect width="140" height="78" fill="#eee9de"/>
      <rect x="42" y="7" width="56" height="1.8" fill="${a}" opacity=".8"/>
      <rect x="48" y="13" width="44" height="4" fill="#8d8676"/>
      <rect x="38" y="21" width="64" height="7" fill="#26231f"/>
      <rect x="26" y="34" width="38" height="28" rx="1" fill="#faf7f0" stroke="#c8c0ae"/>
      <rect x="76" y="34" width="38" height="28" rx="1" fill="#faf7f0" stroke="#c8c0ae"/>
      <circle cx="58" cy="70" r="6" fill="#faf7f0" stroke="#a49a86"/>
      <rect x="70" y="68" width="26" height="3" fill="#8d8676"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}" opacity=".75"/>`,
    arcade: `<rect width="140" height="78" fill="#1b0f3a"/>
      ${[0, 1, 2, 3].map((r) => [0, 1, 2, 3, 4].map((c) => `<rect
        x="${c * 30 + (r % 2 ? 6 : -9)}" y="${r * 20 + 4}" width="8" height="6" rx="2"
        fill="${c % 2 ? a : ink}" opacity=".24"/>`).join('')).join('')}
      <rect x="10" y="16" width="46" height="9" fill="${a}" opacity=".9"/>
      <rect x="12" y="14" width="46" height="9" fill="#fff"/>
      <circle cx="22" cy="44" r="10" fill="#241650" stroke="${a}" stroke-width="1.4"/>
      <rect x="36" y="40" width="24" height="8" rx="4" fill="${a}"/>
      ${plate(74, 26, 28, 28)}${plate(106, 26, 28, 28)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    gloss: `<rect width="140" height="78" fill="#f6dce6"/>
      <ellipse cx="70" cy="30" rx="60" ry="32" fill="#fdeef4"/>
      <rect x="46" y="9" width="48" height="7" fill="#3a2a31"/>
      <rect x="54" y="20" width="32" height="2" fill="${a}"/>
      <rect x="30" y="28" width="34" height="30" rx="2" fill="#fffdf9" stroke="${a}"/>
      <rect x="76" y="28" width="34" height="30" rx="2" fill="#fffdf9" stroke="${a}"/>
      <circle cx="62" cy="68" r="7" fill="#fffdf9" stroke="${a}"/>
      <rect x="74" y="66" width="26" height="3" fill="#8a6b76"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}" opacity=".8"/>`,
    sideline: `<rect width="140" height="78" fill="#0b2545"/>
      ${[0, 1, 2, 3, 4, 5].map((i) => `<path d="M${i * 26 - 14} 78L${i * 26 + 8} 0h10L${i * 26 - 4} 78z"
        fill="${a}" opacity=".8"/>`).join('')}
      <path d="M0 22l140-16v48L0 70z" fill="#0d1c2e" opacity=".96"/>
      <rect x="10" y="30" width="42" height="8" fill="#fff"/>
      <circle cx="20" cy="52" r="8" fill="#12263d" stroke="${a}" stroke-width="1.3"/>
      ${plate(74, 24, 28, 28)}${plate(106, 24, 28, 28)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    wordmark: `<rect width="140" height="78" fill="#160810"/>
      ${[0, 1, 2, 3].map((r) => `<text x="${-16 + r * 11}" y="${15 + r * 21}"
        font-family="Helvetica" font-weight="bold" font-size="16"
        fill="${r % 2 ? 'none' : a}" stroke="${r % 2 ? a : 'none'}" stroke-width="1"
        opacity=".28" transform="rotate(-9 70 39)">NAME NAME NAME</text>`).join('')}
      <rect x="0" y="6" width="140" height="20" fill="#160810" opacity=".95"/>
      <rect x="0" y="5" width="140" height="1.6" fill="${a}"/>
      <rect x="0" y="26" width="140" height="1.6" fill="${a}"/>
      <rect x="44" y="11" width="52" height="9" fill="#fff"/>
      ${plate(20, 34, 30, 26)}${plate(55, 34, 30, 26)}${plate(90, 34, 30, 26)}
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
    quiet: `<rect width="140" height="78" fill="#090a0d"/>
      <rect x="60" y="14" width="20" height="1.4" fill="${a}"/>
      <rect x="46" y="21" width="48" height="5" fill="${ink}"/>
      ${plate(38, 34, 28, 26)}${plate(74, 34, 28, 26)}
      <circle cx="70" cy="68" r="6" fill="none" stroke="${a}" stroke-width="1.2"/>
      <rect x="0" y="75" width="86" height="3" fill="${a}"/>`,
  }[key] || '<rect width="140" height="78" fill="#14151a"/>';
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">${svg}</svg>`;
}

// The preview area, in whichever of its three states applies.
//
// `kind` is the job kind the server uses, so a running render can be matched to
// the panel that asked for it: previewing the slate must not put the end
// screen's panel into a spinner. The cache-buster is the rendered file's own
// mtime rather than the channel's updated_at, because rendering a preview does
// not touch the channel record — busting on updated_at hands the browser back
// the file it already has, and a second preview looks identical to the first
// however different the settings were.
function previewStage(c, kind, file, stamp) {
  const job = state.job;
  const running = job && !job.done && job.kind === kind;
  if (running) {
    const line = (job.lines || []).slice(-1)[0] || job.tagline || 'Stirring the pot…';
    return `
      <h3 style="margin-top:24px">Preview</h3>
      <div class="rendering">
        <div class="rendering-art">
          <span class="rendering-bar"></span><span class="rendering-bar"></span>
          <span class="rendering-bar"></span>
        </div>
        <div class="rendering-say">
          <strong>Rendering…</strong>
          <span class="mono" id="renderline">${esc(line)}</span>
        </div>
      </div>`;
  }
  if (!stamp) return '';
  return `
    <h3 style="margin-top:24px">Preview</h3>
    ${videoTag(`/api/channels/${c.id}/file/${file}?v=${stamp}`,
               { scope: 'channel', id: c.id, rel: file })}`;
}

// A theme swatch: the two colours it writes into the channel, its ground, and a
// few of the icons its patterns are tiled from. That is the whole decision.
function themeArt(t) {
  const glyph = (x, y, c) => `<circle cx="${x}" cy="${y}" r="5.5" fill="${c}"
    opacity=".55"/>`;
  return `<svg class="tpl-art" viewBox="0 0 140 78" preserveAspectRatio="none">
    <rect width="140" height="78" fill="${esc(t.ground)}"/>
    ${[18, 46, 74, 102, 126].map((x, i) =>
      glyph(x, 20 + (i % 2) * 12, i % 2 ? esc(t.accent2) : esc(t.accent))).join('')}
    <rect x="0" y="44" width="140" height="34" fill="${esc(t.ground)}" opacity=".55"/>
    <rect x="12" y="52" width="58" height="8" rx="4" fill="${esc(t.accent)}"/>
    <rect x="76" y="52" width="52" height="8" rx="4" fill="${esc(t.accent2)}"/>
    <rect x="12" y="66" width="116" height="4" rx="2" fill="${esc(t.ink)}" opacity=".5"/>
  </svg>`;
}

// Casting a channel in a theme. Two buttons rather than one, because a channel
// that has settled on a slate should be able to take the colours without
// losing it — which is the only question this panel actually has to ask.
function themePanel(c) {
  const list = state.themes || [];
  const cur = c.style.theme || 'archive';
  const t = list.find((x) => x.key === cur) || {};
  const slate = (state.templates || []).find((x) => x.key === c.intro.template);
  const end = (state.endTemplates || []).find((x) => x.key === c.outro.template);
  const thumb = (state.thumbStyles || []).find((x) => x.key === c.thumb_template);
  return `
    <h2>Theme</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:14px">
        <span class="mono" style="color:var(--ink-faint);flex:1;min-width:240px">
          ${esc(t.blurb || 'What kind of channel this is: two colours, a ground, and the icons the patterns are tiled from.')}</span>
      </div>
      <div class="tpl-strip">
        ${list.map((x) => `
          <div class="tpl ${x.key === cur ? 'sel' : ''}"
               onclick="pickTheme('${x.key}')" title="${esc(x.blurb)}">
            ${themeArt(x)}
            <div class="tpl-name">${esc(x.label)}</div>
            <div class="tpl-cast">${esc(x.for)}</div>
          </div>`).join('')}
      </div>
      <div class="mono" style="color:var(--ink-faint);margin:2px 0 14px">
        This channel is currently set in <b>${esc(t.label || cur)}</b> —
        ${esc(slate ? slate.label : c.intro.template)} slate,
        ${esc(thumb ? thumb.label : c.thumb_template)} thumbnail,
        ${c.outro.enabled ? esc(end ? end.label : c.outro.template) + ' end screen'
                          : 'no end screen'}.
        Colours can be edited under House look afterwards; they are the channel's
        from the moment a theme is applied.
      </div>
      <label class="field"><span>Thumbnail style new videos start on</span>
        <select onchange="saveChannel({thumb_template:this.value})">
          ${(state.thumbStyles || []).map((x) =>
            `<option value="${x.key}" ${x.key === c.thumb_template ? 'selected' : ''}
              >${esc(x.label)}</option>`).join('')}
        </select></label>
    </div>`;
}

// The end screen panel. Everything in it is off when the screen is off, because
// a knob that changes nothing is worse than a knob that is not there.
function endScreenPanel(c) {
  const o = c.outro || {};
  const list = state.endTemplates || [];
  const tpl = list.find((t) => t.key === o.template) || list[0] || {};
  const st = c.style;
  if (!o.enabled) {
    return `<h2>End screen</h2>
      <div class="panel">
        <div class="row">
          <div style="flex:1;min-width:240px">
            <strong>No end screen</strong>
            <div class="mono" style="color:var(--ink-faint);margin-top:5px">
              The last 5 to 20 seconds, held for YouTube's own cards and the
              subscribe badge to sit on. Every video in the channel gets it.</div>
          </div>
          <button class="btn sm primary" onclick="saveOutro({enabled:true})">add one</button>
        </div>
      </div>`;
  }
  return `<h2>End screen</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:16px">
        <span class="mono" style="color:var(--ink-faint);flex:1;min-width:220px">
          ${esc(tpl.blurb || '')}</span>
        <div class="spacer"></div>
        <button class="btn sm primary" onclick="previewOutro()">preview</button>
        <button class="btn sm ghost" onclick="saveOutro({enabled:false})">turn off</button>
      </div>

      <div class="tpl-strip">
        ${list.map((t) => `
          <div class="tpl ${t.key === o.template ? 'sel' : ''}"
               onclick="saveOutro({template:'${t.key}'})">
            ${endArt(t.key, st.accent)}
            <div class="tpl-name">${esc(t.label)}</div>
            <div class="tpl-cast">${t.max_slots} plate${t.max_slots > 1 ? 's' : ''}${
              t.wants_backdrop ? ' · last shot' : t.themed ? ' · themed' : ''}</div>
          </div>`).join('')}
      </div>

      <div class="grid-3">
        <label class="field"><span>Length — <b>${o.duration.toFixed(0)}s</b></span>
          <input type="range" min="5" max="20" step="1" value="${o.duration}"
            onchange="saveOutro({duration:+this.value})"></label>
        <label class="field"><span>${esc(tpl.slots_label || 'Plates')} — <b>${o.slots}</b></span>
          <input type="range" min="0" max="${tpl.max_slots || 2}" step="1" value="${o.slots}"
            onchange="saveOutro({slots:+this.value})"></label>
        <label class="field"><span>Settling time — <b>${o.settle.toFixed(2)}s</b></span>
          <input type="range" min="0.25" max="1.6" step="0.05" value="${o.settle}"
            onchange="saveOutro({settle:+this.value})"></label>
        <label class="field"><span>Music fades out over — <b>${o.music_fade.toFixed(0)}s</b></span>
          <input type="range" min="0" max="18" step="1" value="${o.music_fade}"
            onchange="saveOutro({music_fade:+this.value})"></label>
      </div>
      <div class="mono" style="color:var(--ink-faint);margin:-8px 0 16px">
        YouTube will not show an end screen shorter than 5 seconds or longer than
        20. Place the real cards over the plates in Studio.</div>

      <div class="grid-2">
        <label class="field"><span>Closing line</span>
          <input type="text" value="${esc(o.cta)}" placeholder="${esc(tpl.cta || '')}"
            onchange="saveOutro({cta:this.value})"></label>
        <label class="field"><span>Handle — set under the channel name</span>
          <input type="text" value="${esc(o.handle)}" placeholder="@yourchannel"
            onchange="saveOutro({handle:this.value})"></label>
      </div>
      <label class="field"><span>The video's last picture behind it — <b>${
        o.backdrop < 0.02 ? 'off' : Math.round(o.backdrop * 100) + '%'}</b></span>
        <input type="range" min="0" max="1" step="0.05" value="${o.backdrop}"
          onchange="saveOutro({backdrop:+this.value})"></label>
      <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
        ${tpl.wants_backdrop
          ? 'Afterglow holds the last picture whatever this says; the slider only decides how far it comes through.'
          : 'Blurred and knocked well back, so the plates still read over it.'}</div>

      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${o.subscribe ? 'checked' : ''} style="width:auto"
          onchange="saveOutro({subscribe:this.checked})">
        <span>Leave a round plate for the subscribe badge</span>
      </label>
      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${o.countdown ? 'checked' : ''} style="width:auto"
          onchange="saveOutro({countdown:this.checked})">
        <span>Hairline showing how long the card is up</span>
      </label>
      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${o.show_video_title ? 'checked' : ''} style="width:auto"
          onchange="saveOutro({show_video_title:this.checked})">
        <span>Name the video that is ending</span>
      </label>

      ${previewStage(c, 'end screen preview', 'cache/outro_preview.webm', c.outro_preview_at)}
    </div>`;
}

// The host image the essay format pins in a corner. Only worth drawing the
// panel when this channel actually renders in that format — on a documentary
// channel it is a control for something that never appears.
function avatarPanel(c) {
  const a = c.avatar || {};
  if ((c.style.format || 'kenburns') !== 'essay') return '';
  return `<h2>Host</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:${a.path ? '16px' : '0'}">
        <div style="flex:1;min-width:240px">
          <strong>${a.path ? esc(a.filename || 'avatar') : 'No host image'}</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:5px">
            A still — a drawing, a mascot, a cut-out — pinned in one corner of
            every video in this channel. Transparent PNGs sit best.</div>
        </div>
        ${a.path ? `
          <img src="/api/channels/${c.id}/file/${a.path}?v=${c.updated_at}"
               style="height:86px;border-radius:8px;background:#0f1116">
          <button class="btn sm ghost danger" onclick="removeAvatar()">remove</button>`
        : `<label class="btn sm" style="cursor:pointer">choose an image
             <input type="file" accept="image/*" hidden onchange="uploadAvatar(this.files[0])">
           </label>`}
      </div>
      ${!a.path ? '' : `
        <label class="row" style="gap:8px;margin-bottom:12px;cursor:pointer">
          <input type="checkbox" ${a.enabled ? 'checked' : ''} style="width:auto"
            onchange="saveAvatar({enabled:this.checked})">
          <span>Show it on this channel's videos</span>
        </label>
        <div class="grid-2">
          <label class="field" style="margin:0"><span>Corner</span>
            <select onchange="saveAvatar({position:this.value})">
              <option value="bottom_right" ${a.position !== 'bottom_left' ? 'selected' : ''}>bottom right</option>
              <option value="bottom_left" ${a.position === 'bottom_left' ? 'selected' : ''}>bottom left</option>
            </select></label>
          <label class="field" style="margin:0"><span>Size — <b>${Math.round((a.scale || 0.24) * 100)}%</b> of frame height</span>
            <input type="range" min="0.1" max="0.4" step="0.01" value="${a.scale || 0.24}"
              onchange="saveAvatar({scale:+this.value})"></label>
        </div>`}
    </div>`;
}

async function uploadAvatar(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    await api(`/api/channels/${state.channel.id}/avatar`, { method: 'POST', body: fd });
    await refreshChannel();
    toast('host image added');
  } catch (e) { toast(e.message, true); }
}

async function removeAvatar() {
  await api(`/api/channels/${state.channel.id}/avatar`, { method: 'DELETE' });
  await refreshChannel();
}

// Publishing lives one level up from a single video: you connect a channel to
// a real YouTube channel once here, then upload from each video's render tab
// (see uploadPanel() in paintRender()).
function youtubePanel(c) {
  if (!c.youtube_available) {
    return `<h2>YouTube</h2>
      <div class="panel">
        <div class="mono" style="color:var(--ink-faint)">
          Not set up. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env to
          publish straight from here — see the README's "Research and
          accuracy" section for the two-minute Cloud Console setup.
          Rendered videos still work fine without it; upload through
          YouTube Studio instead.</div>
      </div>`;
  }
  const yt = c.youtube || {};
  return `<h2>YouTube</h2>
    <div class="panel">
      <div class="row">
        <div style="flex:1;min-width:240px">
          <strong>${yt.connected ? esc(yt.channel_title || 'Connected') : 'Not connected'}</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:5px">
            ${yt.connected
              ? 'New videos in this channel can be uploaded straight from the render tab.'
              : 'Connect the YouTube channel this series publishes to.'}</div>
        </div>
        ${yt.connected
          ? `${yt.channel_thumb ? `<img src="${esc(yt.channel_thumb)}" style="width:40px;height:40px;border-radius:50%">` : ''}
             <button class="btn sm ghost danger" onclick="disconnectYoutube()">disconnect</button>`
          : `<a class="btn sm primary" href="/api/youtube/oauth/start?channel_id=${c.id}">connect YouTube</a>`}
      </div>
    </div>`;
}

async function disconnectYoutube() {
  if (!confirm('Disconnect this channel from YouTube? Uploading a video will ask you to reconnect.')) return;
  await api(`/api/channels/${state.channel.id}/youtube/disconnect`, { method: 'POST' });
  await refreshChannel();
}

function paintChannel() {
  const c = state.channel;
  if (!c) return;
  if (state.channelTab === 'setup') paintChannelSetup();
  else paintChannelOverview();
}

// The landing page for a channel — what it's hard to find today, buried
// under the whole setup form. Just the videos, front and centre; setup is
// one click away rather than something you scroll past every time.
function paintChannelOverview() {
  const c = state.channel;
  const st = c.style;
  $('#topbar-right').innerHTML =
    `<span class="swatch" style="background:${esc(st.accent)}"></span>`;

  view.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <div style="flex:1;min-width:0">
        <h1>${esc(c.name)}</h1>
        <p class="sub">${esc(c.tagline || c.concept || 'A series.')}</p>
      </div>
      <button class="btn ghost sm" onclick="go('#/c/${c.id}/setup')">channel setup</button>
      <button class="btn ghost sm" onclick="go('#/')">all channels</button>
    </div>
    ${jobPanel()}

    <div class="row" style="margin:20px 0 14px;align-items:baseline">
      <h2 style="margin:0">Videos in this channel</h2>
      <div class="spacer"></div>
      <button class="btn sm primary" onclick="newVideoInChannel('${c.id}')">+ new video</button>
    </div>
    ${(c.videos || []).length === 0
      ? '<div class="empty-note">None yet — pour one in above.</div>'
      : c.videos.map(projRow).join('')}
  `;
  paintJob();
}

function newVideoInChannel(chanId) {
  state.presetChannel = chanId;
  go('#/');
}

function paintChannelSetup() {
  const c = state.channel;
  const st = c.style, intro = c.intro;
  const cast = intro.subjects || [];
  const templates = state.templates || [];
  const tpl = templates.find((t) => t.key === intro.template) || templates[0] || {};
  // Only the cast-led slates wait on portraits; the type-led ones are ready now.
  const castLed = !!tpl.needs_images;
  const ready = !castLed || (intro.images || []).length >= 2;
  $('#topbar-right').innerHTML =
    `<span class="swatch" style="background:${esc(st.accent)}"></span>
     <span class="pill ${ready ? 'on' : 'warn'}">${ready ? 'slate ready' : 'slate incomplete'}</span>`;

  view.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <div style="flex:1;min-width:0">
        <h1>${esc(c.name)} <span class="sub">— setup</span></h1>
        <p class="sub">${esc(c.tagline || c.concept || 'A series.')}</p>
      </div>
      <button class="btn ghost sm" onclick="go('#/c/${c.id}')">← videos</button>
    </div>
    ${jobPanel()}
    ${themePanel(c)}

    <div class="grid-2">
      <div class="panel">
        <h3>Identity</h3>
        <label class="field"><span>Channel name — appears on every slate</span>
          <input type="text" value="${esc(c.name)}" onchange="saveChannel({name:this.value})"></label>
        <label class="field"><span>Tagline — small line above the name</span>
          <input type="text" value="${esc(c.tagline)}" placeholder="optional"
            onchange="saveChannel({tagline:this.value})"></label>
        <label class="field"><span>What this channel covers</span>
          <textarea rows="3" onchange="saveChannel({concept:this.value})"
            placeholder="Steers the scripts and who gets cast in the opening titles."
            >${esc(c.concept)}</textarea></label>
        <label class="field"><span>Default tone for new videos</span>
          <select onchange="saveChannel({tone:this.value})">
            ${['warm documentary', 'cool and analytical', 'plain and understated',
               'tense and propulsive', 'wry and literary'].map((t) =>
              `<option ${t === c.tone ? 'selected' : ''}>${t}</option>`).join('')}
          </select></label>
        <label class="field"><span>Default length — <b>${c.default_minutes}</b> min</span>
          <input type="range" min="7" max="22" value="${c.default_minutes}"
            onchange="saveChannel({default_minutes:+this.value})"></label>
      </div>

      <div class="panel">
        <h3>House look</h3>
        <p class="mono" style="color:var(--ink-faint);margin-top:-4px">
          New videos in this channel start from these.</p>
        <label class="field"><span>Video style</span></label>
        ${formatPicker(st.format || 'kenburns', st.accent, 'pickChannelFormat')}
        ${st.format === 'board' ? boardKnobs(st, 'saveChannelStyle') : ''}
        ${isCut(st.format) ? cutKnobs(st, 'saveChannelStyle') : ''}
        <label class="field"><span>Accent — rules, separators, titles</span>
          <input type="text" value="${esc(st.accent)}" onchange="saveChannelStyle({accent:this.value})"></label>
        <label class="field"><span>Second colour — patterns, shadows, the loud half</span>
          <input type="text" value="${esc(st.accent2 || '')}" placeholder="#7FA6B8"
            onchange="saveChannelStyle({accent2:this.value})"></label>
        <label class="field"><span>Grade</span>
          <select onchange="saveChannelStyle({grade:this.value})">
            ${['warm', 'neutral', 'cool', 'mono'].map((g) =>
              `<option ${g === st.grade ? 'selected' : ''}>${g}</option>`).join('')}
          </select></label>
        <label class="field"><span>Vignette — <b>${st.vignette.toFixed(2)}</b></span>
          <input type="range" min="0" max="0.8" step="0.02" value="${st.vignette}"
            onchange="saveChannelStyle({vignette:+this.value})"></label>
        <label class="field"><span>Crossfade — <b>${st.transition.toFixed(2)}s</b></span>
          <input type="range" min="0" max="1.6" step="0.05" value="${st.transition}"
            onchange="saveChannelStyle({transition:+this.value})"></label>
        <label class="field"><span>Music under voice — <b>${st.music_db.toFixed(0)} dB</b></span>
          <input type="range" min="-40" max="-10" step="1" value="${st.music_db}"
            onchange="saveChannelStyle({music_db:+this.value})"></label>
      </div>
    </div>

    <h2>Opening slate</h2>
    <div class="panel">
      <div class="row" style="margin-bottom:16px">
        <span class="mono" style="color:var(--ink-faint);flex:1;min-width:220px">
          ${esc(tpl.blurb || '')}</span>
        <div class="spacer"></div>
        ${castLed ? `
          <button class="btn sm" onclick="castChannel()">${cast.length ? 're-cast' : 'cast it for me'}</button>
          <button class="btn sm" onclick="fetchPortraits()" ${cast.length ? '' : 'disabled'}>fetch portraits</button>` : ''}
        <button class="btn sm primary" onclick="previewIntro()"
          ${ready ? '' : 'disabled'}>preview</button>
      </div>

      <div class="tpl-strip">
        ${templates.map((t) => `
          <div class="tpl ${t.key === intro.template ? 'sel' : ''}"
               onclick="saveIntro({template:'${t.key}'})">
            ${tplArt(t.key, st.accent)}
            <div class="tpl-name">${esc(t.label)}</div>
            <div class="tpl-cast">${t.needs_images ? 'needs a cast'
              : t.themed ? 'themed' : 'type only'}</div>
          </div>`).join('')}
      </div>

      <div class="grid-3">
        ${tpl.columns_label ? `
          <label class="field"><span>${esc(tpl.columns_label)} — <b>${intro.columns}</b></span>
            <input type="range" min="3" max="8" value="${intro.columns}"
              onchange="saveIntro({columns:+this.value})"></label>` : ''}
        ${tpl.stagger_label ? `
          <label class="field"><span>${esc(tpl.stagger_label)} — <b>${intro.stagger.toFixed(2)}</b></span>
            <input type="range" min="0.03" max="0.28" step="0.005" value="${intro.stagger}"
              onchange="saveIntro({stagger:+this.value})"></label>` : ''}
        <label class="field"><span>Length — <b>${intro.duration.toFixed(1)}s</b></span>
          <input type="range" min="3" max="9" step="0.5" value="${intro.duration}"
            onchange="saveIntro({duration:+this.value})"></label>
        <label class="field"><span>${esc(tpl.fly_label || 'Fly-in time')} — <b>${intro.fly_duration.toFixed(2)}s</b></span>
          <input type="range" min="0.15" max="1.4" step="0.05" value="${intro.fly_duration}"
            onchange="saveIntro({fly_duration:+this.value})"></label>
      </div>

      <div class="panel" style="background:#0f1116;margin:4px 0 18px">
        <div class="row" style="margin-bottom:${intro.music ? '14px' : '0'}">
          <div style="flex:1;min-width:200px">
            <strong>Slate sting</strong>
            <div class="mono" style="color:var(--ink-faint);margin-top:4px">
              ${intro.music
                ? esc(intro.music_filename || 'sting')
                : `Its own music for the ${intro.duration.toFixed(1)} seconds. The main bed waits until the slate is over.`}</div>
          </div>
          ${intro.music ? `
            <audio id="stingaudio" controls style="max-width:280px"
              src="/api/channels/${c.id}/file/${intro.music}?v=${c.updated_at}"></audio>
            <button class="btn sm ghost danger" onclick="removeSting()">remove</button>`
          : `<label class="btn sm" style="cursor:pointer">choose a sting
               <input type="file" accept="audio/*" hidden onchange="uploadSting(this.files[0])">
             </label>`}
        </div>
        ${intro.music ? `
          <div class="row" style="gap:10px;margin-bottom:12px">
            <div class="mono" style="flex:1;min-width:200px;color:var(--ink-faint)">
              ${stingWindowNote(intro)}</div>
            <button class="btn sm ghost" onclick="auditionSting()">hear the window</button>
          </div>
          <label class="field" style="margin:0 0 12px"><span>Start it — <b>${fmtTime(intro.music_start)}${
              intro.music_start > 0 ? ' into the track' : ' — the very top'}</b></span>
            <input type="range" min="0" max="${stingMaxStart(intro).toFixed(1)}" step="0.1"
              value="${Math.min(intro.music_start, stingMaxStart(intro)).toFixed(1)}"
              oninput="scrubSting(+this.value)"
              onchange="saveIntro({music_start:+this.value})"></label>
          <div class="grid-3">
            <label class="field" style="margin:0"><span>Level vs the narration — <b>${intro.music_db.toFixed(0)} dB</b></span>
              <input type="range" min="-20" max="4" step="1" value="${intro.music_db}"
                onchange="saveIntro({music_db:+this.value})"></label>
            <label class="field" style="margin:0"><span>Rings on past the slate — <b>${intro.music_tail.toFixed(1)}s</b></span>
              <input type="range" min="0" max="3" step="0.1" value="${intro.music_tail}"
                onchange="saveIntro({music_tail:+this.value})"></label>
            <label class="field" style="margin:0"><span>Fade out — <b>${
                intro.music_fade < 0.1 ? 'straight cut' : intro.music_fade.toFixed(1) + 's'}</b></span>
              <input type="range" min="0" max="4" step="0.1" value="${intro.music_fade}"
                onchange="saveIntro({music_fade:+this.value})"></label>
          </div>` : ''}
      </div>

      <label class="row" style="gap:8px;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" ${intro.show_video_title ? 'checked' : ''}
          onchange="saveIntro({show_video_title:this.checked})" style="width:auto">
        <span>Show the video's title under the channel name</span>
      </label>

      ${!castLed ? '' : `<h3>Cast — ${intro.template === 'columns' ? 'one face per column'
                                     : intro.template === 'mosaic' ? 'the wall of faces'
                                     : 'the faces on the strip'}</h3>
      <div class="cast">
        ${cast.length === 0
          ? `<div class="empty-note" style="grid-column:1/-1">
               Nobody cast yet. “Cast it for me” asks Claude for faces that fit this channel,
               or type your own below.</div>`
          : cast.map((s, i) => {
              const img = (intro.images || [])[i];
              const f = (intro.focals || [])[i] || [];
              const pos = f.length === 2 ? `${f[0] * 100}% ${f[1] * 100}%` : '50% 28%';
              return `<div class="cast-card">
                ${img ? `<div class="cast-shot" onclick="setCastFocal(${i})"
                              title="click to set the focus point">
                           <img src="/api/channels/${c.id}/file/${img}?v=${c.updated_at}"
                                style="object-position:${pos}">
                           <span class="cast-focus">${f.length === 2 ? '✛ focus' : 'set focus'}</span>
                         </div>`
                      : `<div class="cast-empty" onclick="changeCastImage(${i})"
                              style="cursor:pointer">no portrait — find one</div>`}
                <input type="text" value="${esc(s)}" onchange="editCast(${i}, this.value)">
                <div class="cast-acts">
                  <button class="btn xs ghost" onclick="changeCastImage(${i})"
                    title="choose a different portrait">change</button>
                  <label class="btn xs ghost" style="cursor:pointer"
                    title="use your own image">upload
                    <input type="file" accept="image/*" hidden
                      onchange="uploadCastImage(${i}, this.files[0])"></label>
                  <div class="spacer"></div>
                  <button class="btn xs ghost danger" onclick="removeCast(${i})"
                    title="remove ${esc(s)} from the cast">remove</button>
                </div>
              </div>`;
            }).join('')}
      </div>
      <div class="row" style="margin-top:12px">
        <input type="text" id="newcast" placeholder="add someone — e.g. “Ada Lovelace portrait”"
          style="flex:1" onkeydown="if(event.key==='Enter')addCast(this)">
        <button class="btn sm" onclick="addCast(document.getElementById('newcast'))">add</button>
      </div>`}

      ${previewStage(c, 'intro preview', 'cache/intro_preview.webm', c.preview_at)}
    </div>

    ${endScreenPanel(c)}

    ${avatarPanel(c)}

    ${youtubePanel(c)}

    <div class="row" style="margin-top:30px">
      <div class="spacer"></div>
      <button class="btn sm ghost danger" onclick="delChannel()">delete channel</button>
    </div>
  `;
  paintJob();
}

// A channel response carries no video list and no preview flags — those are
// assembled per request — so they are carried over rather than dropped.
function applyChannel(fresh) {
  state.channel = { ...fresh, videos: state.channel.videos,
    has_preview: state.channel.has_preview,
    has_outro_preview: state.channel.has_outro_preview };
  paintChannel();
}

async function saveChannel(patch) {
  applyChannel(await api(`/api/channels/${state.channel.id}`,
    { method: 'PATCH', body: JSON.stringify(patch) }));
  toast('saved');
}

const saveChannelStyle = (patch) => saveChannel({ style: patch });
const pickChannelFormat = (key) => saveChannelStyle({ format: key });
const saveIntro = (patch) => saveChannel({ intro: patch });
const saveOutro = (patch) => saveChannel({ outro: patch });
const saveAvatar = (patch) => saveChannel({ avatar: patch });

// Renaming only. Emptying the box used to splice `subjects` on its own, which
// left every portrait after it sitting under the wrong name — removal goes
// through the server now, where all four cast arrays move together.
function editCast(i, value) {
  const v = value.trim();
  if (!v) { paintChannel(); return toast('Use “remove” to drop someone.', true); }
  const subjects = [...state.channel.intro.subjects];
  subjects[i] = v;
  saveIntro({ subjects });
}

async function removeCast(i) {
  const who = state.channel.intro.subjects[i] || 'this cast member';
  if (!confirm(`Remove ${who} from the slate?`)) return;
  const r = await api(`/api/channels/${state.channel.id}/cast/${i}`, { method: 'DELETE' });
  applyChannel(r.channel);
  toast('removed');
}

async function uploadCastImage(i, file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    applyChannel(await api(`/api/channels/${state.channel.id}/cast/${i}/upload`,
      { method: 'POST', body: fd }));
    toast('portrait replaced');
  } catch (e) { toast(e.message, true); }
}

// Swap one face without re-casting the whole slate. The search runs against the
// cast member's own name by default, but the box is there because "Paderewski
// portrait photograph" and "Ignacy Jan Paderewski 1900" find different pictures.
async function changeCastImage(i) {
  const c = state.channel;
  const subject = c.intro.subjects[i] || '';
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>A portrait for ${esc(subject)}</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="pclose">close</button>
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="pq" value="${esc(subject)}" style="flex:1"
          placeholder="search for something else">
        <button class="btn sm" id="pgo">search</button>
      </div>
      <div id="presults" class="pick-grid portraits">
        <div class="empty-note" style="grid-column:1/-1">Casting the net…</div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector('#pclose').onclick = close;
  wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });

  const results = wrap.querySelector('#presults');
  const run = async (q) => {
    results.innerHTML = '<div class="empty-note" style="grid-column:1/-1">Casting the net…</div>';
    let found = [];
    try {
      const r = await api(`/api/channels/${c.id}/cast/${i}/options`
        + `?q=${encodeURIComponent(q || '')}`);
      found = r.results || [];
    } catch (e) {
      results.innerHTML = `<div class="empty-note" style="grid-column:1/-1">${esc(e.message)}</div>`;
      return;
    }
    if (!found.length) {
      results.innerHTML = '<div class="empty-note" style="grid-column:1/-1">'
        + 'Nobody answered the casting call. Try a different wording.</div>';
      return;
    }
    results.innerHTML = found.map((cand, n) => `
      <div class="pick" data-n="${n}" title="${esc(cand.title || '')}">
        <img src="${esc(cand.thumb || cand.url)}" loading="lazy">
        <div class="pick-meta mono">${esc(cand.provider || '')}${
          cand.width ? ` · ${cand.width}×${cand.height}` : ''}</div>
      </div>`).join('');
    results.querySelectorAll('.pick').forEach((el) => {
      el.onclick = async () => {
        el.classList.add('busy');
        try {
          applyChannel(await api(`/api/channels/${c.id}/cast/${i}/portrait`, {
            method: 'POST',
            body: JSON.stringify({ candidate: found[+el.dataset.n] }),
          }));
          close();
          toast('portrait replaced');
        } catch (e) { el.classList.remove('busy'); toast(e.message, true); }
      };
    });
  };
  wrap.querySelector('#pgo').onclick = () => run(wrap.querySelector('#pq').value);
  wrap.querySelector('#pq').onkeydown = (e) => {
    if (e.key === 'Enter') run(wrap.querySelector('#pq').value);
  };
  run(subject);
}

function addCast(input) {
  const v = input.value.trim();
  if (!v) return;
  input.value = '';
  saveIntro({ subjects: [...state.channel.intro.subjects, v] });
}

async function pickTheme(key) {
  const t = (state.themes || []).find((x) => x.key === key) || {};
  const takeTemplates = confirm(
    `Cast this channel in ${t.label || key}?\n\n`
    + `OK — take its colours and its templates `
    + `(${t.intro} slate, ${t.thumb} thumbnail, ${t.outro} end screen).\n`
    + `Cancel — take the colours only and keep the templates you have.`);
  state.channel = { ...await api(`/api/channels/${state.channel.id}/theme`, {
    method: 'POST', body: JSON.stringify({ key, templates: takeTemplates }),
  }), videos: state.channel.videos, has_preview: state.channel.has_preview,
    has_outro_preview: state.channel.has_outro_preview };
  paintChannel();
  toast(takeTemplates ? `cast in ${t.label || key}` : `${t.label || key} colours applied`);
}

async function castChannel() {
  const r = await api(`/api/channels/${state.channel.id}/cast`,
    { method: 'POST', body: JSON.stringify({ count: state.channel.intro.columns }) });
  watchJob(r.job, 'cast');
  paintChannel();
}

async function fetchPortraits() {
  const r = await api(`/api/channels/${state.channel.id}/portraits`, { method: 'POST' });
  watchJob(r.job, 'portraits');
  paintChannel();
}

async function previewIntro() {
  const sample = (state.channel.videos || [])[0];
  const r = await api(`/api/channels/${state.channel.id}/preview`, {
    method: 'POST',
    body: JSON.stringify({ title: sample ? sample.title : '' }),
  });
  watchJob(r.job, 'intro preview');
  paintChannel();
  scrollToPreview();
}

async function previewOutro() {
  const sample = (state.channel.videos || [])[0];
  const r = await api(`/api/channels/${state.channel.id}/outro-preview`, {
    method: 'POST',
    body: JSON.stringify({ title: sample ? sample.title : '' }),
  });
  watchJob(r.job, 'end screen preview');
  paintChannel();
  scrollToPreview();
}

// Put the placeholder where it can be seen. A preview started from the top of a
// long channel page otherwise renders somewhere below the fold.
function scrollToPreview() {
  requestAnimationFrame(() => {
    const el = document.querySelector('.rendering');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
}

async function uploadSting(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    await api(`/api/channels/${state.channel.id}/music`, { method: 'POST', body: fd });
    await refreshChannel();
    toast('sting added');
  } catch (e) { toast(e.message, true); }
}

async function removeSting() {
  await api(`/api/channels/${state.channel.id}/music`, { method: 'DELETE' });
  await refreshChannel();
}

// How much of the sting the slate actually uses: the slate's own length plus
// the beat it rings on for over the first slide.
const stingSpan = (intro) => intro.duration + intro.music_tail;

// The last place a window may start. Mirrors the server's clamp, which keeps a
// second of the file in play whatever the slate's length.
const stingMaxStart = (intro) => Math.max(0, (intro.music_duration || 0) - 1);

function stingWindowNote(intro) {
  const span = stingSpan(intro);
  if (!intro.music_duration) return `The slate takes ${span.toFixed(1)}s of it.`;
  const from = Math.min(intro.music_start, stingMaxStart(intro));
  const over = from + span > intro.music_duration + 0.05;
  return `${fmtTime(intro.music_duration)} long — the slate takes ${span.toFixed(1)}s, `
    + `${fmtTime(from)} to ${fmtTime(from + span)}`
    + (over ? '. That runs off the end of the track.' : '.');
}

// Dragging the start slider scrubs the player to that point, so the window can
// be found by ear rather than by arithmetic.
function scrubSting(seconds) {
  const el = document.getElementById('stingaudio');
  if (el) { try { el.currentTime = seconds; } catch (e) { /* not loaded yet */ } }
}

// Play exactly what the slate will use, and stop where it stops.
function auditionSting() {
  const el = document.getElementById('stingaudio');
  const intro = state.channel && state.channel.intro;
  if (!el || !intro) return;
  clearTimeout(window._stingStop);
  const from = Math.min(intro.music_start, stingMaxStart(intro));
  el.currentTime = from;
  el.play().catch(() => {});
  window._stingStop = setTimeout(() => { el.pause(); el.currentTime = from; },
                                 stingSpan(intro) * 1000);
}

async function delChannel() {
  if (!confirm('Delete this channel? Its videos are kept, just unlinked.')) return;
  await api(`/api/channels/${state.channel.id}`, { method: 'DELETE' });
  go('#/');
}

// ----------------------------------------------------------------- project
function render() {
  const p = state.project;
  if (!p) return;
  const recorded = p.recorded_count, total = p.slides.length;
  $('#topbar-right').innerHTML =
    `<span class="mono">${fmtTime(p.recorded_seconds || p.est_seconds)}</span>
     <span class="pill ${p.status === 'rendered' ? 'on' : ''}">${esc(p.status)}</span>`;

  const tabs = [
    ['script', 'Script', total],
    ['media', 'Media', p.slides.filter((s) => s.chosen_id).length],
    ['record', 'Record', `${recorded}/${total}`],
    ['thumb', 'Thumbnail', p.thumb && p.thumb.image ? '✓' : ''],
    ['render', 'Render', ''],
  ];

  view.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <div style="flex:1;min-width:0">
        <h1>${esc(p.title || p.idea.slice(0, 60))}</h1>
        <p class="sub">${esc(p.subtitle || p.outline.thesis || '')}</p>
      </div>
      <button class="btn ghost sm" onclick="saveProjectFile()"
        title="everything in this video as one file, to open on another computer">save project file…</button>
      <button class="btn ghost sm" onclick="go('#/')">all videos</button>
    </div>
    <div class="tabs">
      ${tabs.map(([id, label, count]) => `<div class="tab ${state.tab === id ? 'active' : ''}"
        onclick="go('#/p/${p.id}/${id}')">${label}<span class="count">${count}</span></div>`).join('')}
    </div>
    ${jobPanel()}
    <div id="tabbody"></div>`;

  ({ script: paintScript, media: paintMedia, record: paintRecord,
     thumb: paintThumb, render: paintRender }[state.tab] || paintScript)();
  paintJob();
  if (state.tab !== 'render' && typeof tlPause === 'function') tlPause();
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

// ------------------------------------------------------------------ script
function paintScript() {
  const p = state.project;
  if (!p.slides.length) {
    // A run that died partway leaves its outline and finished sections behind.
    const draft = p.draft || {};
    const written = Object.keys(draft.sections || {}).length;
    const total = (draft.outline && (draft.outline.sections || []).length) || 0;
    $('#tabbody').innerHTML = written
      ? `<div class="empty-note">
           <strong>An unfinished draft is waiting.</strong><br>
           ${written} of ${total} sections were written before the last run stopped
           — ${esc(draft.outline.title || p.idea)}.<br>
           <span class="mono" style="color:var(--ink-faint)">Carrying on writes only
             the ${total - written} that are missing.</span><br><br>
           <button class="btn sm primary" onclick="regenScript()">carry on</button>
           <button class="btn sm ghost" onclick="regenScript(true)">start again</button>
         </div>`
      : `<div class="empty-note">Empty bucket. Someone's got to write this thing.
           <button class="btn sm" onclick="regenScript()">Write one</button></div>`;
    return;
  }
  const words = p.slides.reduce((n, s) => n + s.word_count, 0);
  const research = p.research || {};
  const flagsBySlide = {};
  (research.flags || []).forEach((f) => { flagsBySlide[f.slide_id] = f; });

  let html = sourcesPanel(research);
  html += `<div class="row" style="margin-bottom:16px">
    <span class="mono" style="color:var(--ink-faint)">${words} words · ${p.slides.length} paragraphs ·
      ~${fmtTime(p.est_seconds)} at a documentary pace</span>
    <div class="spacer"></div>
    ${research.facts && research.facts.length
      ? `<button class="btn sm ghost" onclick="runFactcheck()">check facts</button>` : ''}
    ${p.has_source ? `
      <span class="pill">${esc(p.fidelity)} import</span>
      <button class="btn sm" onclick="reimport('${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}')">
        re-split as ${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}</button>
      <button class="btn sm ghost" onclick="reimport('')">re-split again</button>`
    : `<button class="btn sm danger" onclick="regenScript()">rewrite whole script</button>`}
  </div>`;

  let lastBeat = null;
  p.slides.forEach((s, i) => {
    if (s.beat !== lastBeat) {
      lastBeat = s.beat;
      html += `<div class="section-head">
        <span class="kicker">${esc(s.section)}</span>
        <strong>${esc(s.beat || '')}</strong></div>`;
    }
    const flag = flagsBySlide[s.id];
    html += `${s.chapter ? `<div class="chapter-mark">
        <span class="kicker">chapter</span>
        <input type="text" value="${esc(s.chapter)}" aria-label="chapter title"
          onblur="saveChapter('${s.id}',this.value)">
        <button class="btn sm ghost" title="drop the chapter card"
          onclick="saveChapter('${s.id}','')">remove</button>
      </div>` : ''}
    <div class="card slide-card" data-sid="${s.id}">
      <div class="slide-num">${String(i + 1).padStart(2, '0')}${s.take ? '<br>●' : ''}</div>
      <div>
        <textarea rows="3" onblur="saveSlide('${s.id}',{narration:this.value})"
          >${esc(s.narration)}</textarea>
        <div class="slide-meta">
          <input class="title-input" type="text" placeholder="on-screen title (optional)"
            value="${esc(s.title)}" onblur="saveSlide('${s.id}',{title:this.value})">
          <span class="mono" style="color:var(--ink-faint)">${s.word_count}w
            ≈ ${fmtTime(s.word_count / 158 * 60)}</span>
          ${flag ? `<span class="pill warn" title="${esc(flag.claim)}: ${esc(flag.issue)}">
              <span class="dot"></span>${flag.severity === 'high' ? 'unsupported claim' : 'check this'}</span>` : ''}
          <div class="spacer"></div>
          ${s.take ? '<span class="pill on"><span class="dot"></span>recorded</span>' : ''}
          ${s.chapter ? '' : `<button class="btn sm ghost" title="a full-frame card before this paragraph"
            onclick="startChapter('${s.id}')">start a chapter</button>`}
          <button class="btn sm ghost" onclick="rewrite('${s.id}')">rewrite</button>
          <button class="btn sm ghost" onclick="splitSlide('${s.id}')">split</button>
          <button class="btn sm ghost danger" onclick="delSlide('${s.id}')">delete</button>
        </div>
      </div>
    </div>`;
  });
  $('#tabbody').innerHTML = html;
}

// The dossier research.gather() found before a word was written — see
// app/research.py. A video scripted before that existed, or with SEARXNG_URL
// unset, has an empty one and this renders nothing.
function sourcesPanel(research) {
  const facts = research.facts || [];
  if (!facts.length) return '';
  const dotColor = { high: 'var(--good)', medium: 'var(--accent)', low: 'var(--ink-faint)' };
  return `<details class="panel" style="margin-bottom:16px">
    <summary style="cursor:pointer;font-weight:600">
      Sources — ${facts.length} researched fact${facts.length === 1 ? '' : 's'}
      ${research.source_count ? `from ${research.source_count} page(s)` : ''}
    </summary>
    <div style="margin-top:14px;display:flex;flex-direction:column;gap:9px">
      ${facts.map((f) => `
        <div style="font-size:13.5px;line-height:1.5">
          <span class="dot" style="background:${dotColor[f.confidence] || dotColor.medium};
                display:inline-block;margin-right:7px"></span>
          ${esc(f.claim)}${f.date ? ` <span class="mono" style="color:var(--ink-faint)">(${esc(f.date)})</span>` : ''}
          — ${f.url
            ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source || 'source')}</a>`
            : `<span style="color:var(--ink-faint)">${esc(f.source || 'source')}</span>`}
        </div>`).join('')}
    </div>
    ${(research.open_questions || []).length ? `
      <div style="margin-top:14px">
        <strong style="font-size:13px">Left unclear by research</strong>
        <ul style="margin:6px 0 0;padding-left:20px;font-size:13px;color:var(--ink-dim)">
          ${research.open_questions.map((q) => `<li>${esc(q)}</li>`).join('')}
        </ul>
      </div>` : ''}
    ${(research.corrections || []).length ? `
      <div style="margin-top:14px">
        <strong style="font-size:13px;color:var(--bad)">Corrected the original idea</strong>
        <ul style="margin:6px 0 0;padding-left:20px;font-size:13px;color:var(--ink-dim)">
          ${research.corrections.map((c) => `<li>${esc(c)}</li>`).join('')}
        </ul>
      </div>` : ''}
  </details>`;
}

async function runFactcheck() {
  const r = await api(`/api/projects/${state.project.id}/factcheck`, { method: 'POST' });
  watchJob(r.job, 'fact check');
  render();
}

// A chapter card: a full frame of type announcing a section, held in the
// silence before the paragraph that opens it. Marking one also gives that
// paragraph its own picture (see schema.group_slides), so the card lands on
// a cut rather than in the middle of the picture before it.
const chapterCount = (p) => p.slides.filter((s) => (s.chapter || '').trim()).length;

function startChapter(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  saveChapter(sid, s.title || (s.beat || '').slice(0, 60) || 'New chapter');
}

async function saveChapter(sid, text) {
  const s = state.project.slides.find((x) => x.id === sid);
  if ((s.chapter || '') === (text || '')) return;
  await saveSlide(sid, { chapter: text });
  // The run grouping and the pauses both move with it, so repaint rather than
  // leaving the page showing the old shape of the cut.
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}

async function saveSlide(sid, patch) {
  try {
    const s = await api(`/api/projects/${state.project.id}/slides/${sid}`,
      { method: 'PATCH', body: JSON.stringify(patch) });
    Object.assign(state.project.slides.find((x) => x.id === sid), s);
    toast('saved');
    return s;
  } catch (e) { toast(e.message, true); }
}

async function rewrite(sid) {
  const instruction = prompt('How should this paragraph change?\n(blank = tighten and make it more concrete)');
  if (instruction === null) return;
  const r = await api(`/api/projects/${state.project.id}/slides/${sid}/rewrite`,
    { method: 'POST', body: JSON.stringify({ instruction }) });
  watchJob(r.job, 'rewrite');
  render();
}

async function splitSlide(sid) {
  state.project = await api(`/api/projects/${state.project.id}/slides/${sid}/split`,
    { method: 'POST' });
  render();
}

async function delSlide(sid) {
  if (!confirm('Delete this paragraph?')) return;
  await api(`/api/projects/${state.project.id}/slides/${sid}`, { method: 'DELETE' });
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}

async function reimport(fidelity) {
  const label = fidelity || state.project.fidelity;
  if (!confirm(`Re-split your pasted script as "${label}"?\n`
    + 'Recorded takes are kept but will no longer line up with the new paragraphs.')) return;
  const r = await api(`/api/projects/${state.project.id}/reimport`,
    { method: 'POST', body: JSON.stringify(fidelity ? { fidelity } : {}) });
  watchJob(r.job, 're-import');
  render();
}

// `fresh` throws away an unfinished draft instead of carrying it on. Only the
// rewrite of an existing script needs confirming — there is nothing to lose in
// resuming, and a project with no slides has nothing to overwrite.
async function regenScript(fresh) {
  const p = state.project;
  const written = Object.keys((p.draft || {}).sections || {}).length;
  if (p.slides.length
      && !confirm('Rewrite the whole script? Recorded takes will be kept but will no longer match.')) return;
  if (fresh && written
      && !confirm(`Throw away the ${written} section${written === 1 ? '' : 's'} `
                  + 'already written and start from a new outline?')) return;
  const r = await api(`/api/projects/${p.id}/script`,
    { method: 'POST', body: JSON.stringify({ fresh: !!fresh }) });
  watchJob(r.job, 'script');
  render();
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
  if (c.provider === 'library') return c.thumb || c.url;
  return `/api/thumb?url=${encodeURIComponent(c.thumb || c.url)}`;
}

// The actual playable file for a video candidate: the downloaded local copy
// once there is one, otherwise the provider's own direct file link (Pexels
// and Pixabay both hand back a real .mp4 URL, not a page to scrape).
function videoUrl(c) {
  if (c.local_path) return `/api/projects/${state.project.id}/file/${c.local_path}`;
  return c.url;
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

function paintMedia() {
  const p = state.project;
  // Runs come from the server so the browser and the renderer agree about
  // which paragraph starts a picture and which one holds the last.
  const runs = p.picture_runs || p.slides.map((s) => [s.id]);
  const leadOf = {};      // slide id -> the run's first slide (1-based number)
  const numOf = {};
  p.slides.forEach((s, i) => { numOf[s.id] = i + 1; });
  runs.forEach((run) => run.forEach((id) => { leadOf[id] = numOf[run[0]]; }));
  const leads = p.slides.filter((s) => leadOf[s.id] === numOf[s.id]);
  const found = leads.filter((s) => s.chosen_id).length;
  const perPicture = leads.length
    ? (p.est_seconds || 0) / leads.length : 0;
  const every = p.style.picture_every || 1;
  // In the handwritten format the slide is drawn, not photographed: every
  // paragraph gets its own board whether or not it also gets a picture.
  const board = (p.style.format || 'kenburns') === 'board';
  const cut = isCut(p.style.format);

  let html = `<div class="row" style="margin-bottom:16px">
    <span class="mono" style="color:var(--ink-faint)">
      ${found}/${leads.length} pictures found${leads.length < p.slides.length
        ? ` · ${p.slides.length} paragraphs, about ${fmtTime(perPicture)} on each picture` : ''}</span>
    <div class="spacer"></div>
    <label class="row" style="gap:7px">
      <span class="mono" style="color:var(--ink-faint)">picture every</span>
      <select style="width:auto" onchange="savePictureEvery(+this.value)">
        ${[1, 2, 3, 4, 5, 6].map((n) => `<option value="${n}" ${n === every ? 'selected' : ''}>
          ${n === 1 ? 'paragraph' : n + ' paragraphs'}</option>`).join('')}
      </select>
    </label>
    <button class="btn sm" onclick="gatherMedia()">re-search everything</button>
    ${board ? `<button class="btn sm primary" onclick="planBoards(false)">
        write the boards</button>
      <button class="btn sm ghost" onclick="planBoards(true)" title="including the ones you wrote">
        rewrite them all</button>` : ''}
    ${cut ? `<button class="btn sm primary" onclick="planCues(false)">
        write the ${esc((cutInfo(p.style.format) || {}).label || '')} cues</button>
      <button class="btn sm ghost" onclick="planCues(true)" title="including the ones you edited">
        rewrite them all</button>` : ''}
  </div>
  ${cut ? `<div class="mono" style="color:var(--ink-faint);margin:-8px 0 16px">
      Every paragraph is drawn as a run of cues. One with nothing written for
      it is drawn from its own narration; the picture below is used where the
      cut has a place for one.</div>` : ''}
  ${board ? `<div class="mono" style="color:var(--ink-faint);margin:-8px 0 16px">
      Every paragraph is a board. One with nothing written for it still draws
      one, from a line of its own narration.</div>` : ''}`;

  p.slides.forEach((s, i) => {
    const isLead = leadOf[s.id] === i + 1;
    if (!isLead) {
      html += `<div class="card held" data-sid="${s.id}">
        <div class="row">
          <span class="slide-num">${String(i + 1).padStart(2, '0')}</span>
          <span class="mono" style="color:var(--ink-faint)">holds the picture from
            paragraph ${String(leadOf[s.id]).padStart(2, '0')}</span>
          <span style="color:var(--ink-dim);font-size:13px;flex:1;min-width:140px;
                overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            ${esc(s.narration.slice(0, 90))}</span>
          <div class="spacer"></div>
          ${board ? `<button class="btn sm ghost" onclick="openBoardEditor('${s.id}')">
            edit its board…</button>` : ''}
          ${cut ? `<button class="btn sm ghost" onclick="openCueEditor('${s.id}')">
            edit its cues…</button>` : ''}
          <button class="btn sm ghost" onclick="setPictureMode('${s.id}','new')">
            give this one its own picture</button>
        </div>
      </div>`;
      return;
    }
    const chosen = s.candidates.find((c) => c.id === s.chosen_id);
    html += `<div class="card" data-sid="${s.id}">
      <div class="media-row">
        <div>
          ${cut ? `<img class="chosen" src="${cutUrl(s.id, 0.5)}" loading="lazy"
                    style="object-fit:contain;background:#111;cursor:pointer;margin-bottom:8px"
                    title="edit what this paragraph puts on screen"
                    onclick="openCueEditor('${s.id}')">
               <div class="mono" style="color:var(--ink-faint);margin:-2px 0 10px">
                 ${((s.cues || {})[p.style.format] || []).length
                   ? `${s.cues[p.style.format].length} cues written` : 'drawn from the narration'}
                 · <a href="#" onclick="event.preventDefault();openCueEditor('${s.id}')">edit cues…</a></div>` : ''}
          ${board
            ? `<img class="chosen" src="${boardUrl(s.id)}" loading="lazy"
                    style="object-fit:contain;background:#2f3843;cursor:pointer"
                    onclick="openBoardEditor('${s.id}')">
               <div class="mono" style="color:var(--ink-faint);margin-top:6px">
                 ${esc(s.board_template === 'auto' || !s.board_template
                       ? 'template picked from what it says' : s.board_template)}
                 ${chosen ? ' · the picture below is taped onto it' : ''}</div>`
            : chosen
            ? `<div class="chosen-wrap">
                 <img class="chosen" src="${thumbUrl(chosen)}" loading="lazy"
                      style="object-position:${((chosen.focal || [])[0] ?? 0.5) * 100}% ${((chosen.focal || [])[1] ?? 0.5) * 100}%">
                 ${(chosen.focal || []).length === 2
                   ? `<span class="focal-pin" style="left:${chosen.focal[0] * 100}%;top:${chosen.focal[1] * 100}%"></span>` : ''}
                 ${chosen.kind === 'video'
                   ? `<button class="play-btn always" title="play" onclick="playClipFor('${s.id}','${chosen.id}')"></button>` : ''}
               </div>
               <div class="row" style="margin-top:6px">
                 <button class="btn sm ghost" onclick="setSlideFocal('${s.id}','${chosen.id}')">
                   ${(chosen.focal || []).length === 2 ? '✛ focus set' : 'set focus point'}</button>
               </div>
               <div class="mono" style="color:var(--ink-faint);margin-top:6px">
                 ${esc(chosen.provider)} · ${chosen.width}×${chosen.height}
                 ${chosen.source_page ? `· <a href="${esc(chosen.source_page)}" target="_blank">source</a>` : ''}
                 <br>${esc((chosen.license || '').slice(0, 60))}</div>`
            : `<div class="chosen empty" style="cursor:pointer"
                    onclick="openMediaSearch('${s.id}')">nothing picked — search</div>`}
        </div>
        <div>
          <div class="row" style="margin-bottom:8px">
            <span class="slide-num">${String(i + 1).padStart(2, '0')}</span>
            <strong>${esc(s.title || s.beat || '')}</strong>
            <div class="spacer"></div>
            <span class="pill">${esc(s.prefer_kind)}</span>
          </div>
          <div style="color:var(--ink-dim);font-size:13.5px;margin-bottom:10px">
            ${esc(s.narration.slice(0, 190))}${s.narration.length > 190 ? '…' : ''}</div>
          <div class="strip">
            ${s.candidates.slice(0, 12).map((c) => `
              <div class="thumb ${c.id === s.chosen_id ? 'sel' : ''}"
                   onclick="choose('${s.id}','${c.id}')" title="${esc(c.title)}">
                <img src="${thumbUrl(c)}" loading="lazy" onerror="this.parentNode.style.opacity=.25">
                ${c.kind === 'video' ? '<span class="kindtag">clip</span>' : ''}
                ${playBtn(s.id, c)}
                <span class="src">${esc(c.provider)}</span>
              </div>`).join('') || '<div class="empty-note">the well came up dry</div>'}
            ${s.candidates.length > 12
              ? `<div class="thumb more" onclick="openMediaSearch('${s.id}')">
                   +${s.candidates.length - 12}<br>more</div>` : ''}
          </div>
          <div class="row" style="margin-top:10px">
            <button class="btn sm" onclick="previewBit('${s.id}')"
              title="render this bit small and play it">▶ preview this bit</button>
            <button class="btn sm" onclick="openMediaSearch('${s.id}')">search for a picture…</button>
            <button class="btn sm" onclick="toggleKind('${s.id}')">want ${s.prefer_kind === 'image' ? 'a clip' : 'a photo'}</button>
            <button class="btn sm ghost" onclick="openMapPicker('${s.id}')">get a map…</button>
            ${board ? `<button class="btn sm" onclick="openBoardEditor('${s.id}')">
              edit the board…</button>` : ''}
            <button class="btn sm ghost" onclick="openDiagramEditor('${s.id}')">
              ${Object.keys(s.diagram || {}).length ? 'edit the diagram…' : 'draw a diagram…'}</button>
            <button class="btn sm ghost" onclick="openCustomEditor('${s.id}')">
              ${Object.keys(s.custom || {}).length ? 'edit the slide design…' : '✨ design a slide…'}</button>
            ${i > 0 ? `<button class="btn sm ghost" title="use the picture already on screen"
              onclick="setPictureMode('${s.id}','${s.picture_mode === 'new' ? 'auto' : 'hold'}')">
              ${s.picture_mode === 'new' ? 'always its own' : 'hold the last picture'}</button>` : ''}
            <label class="btn sm ghost" style="cursor:pointer">upload
              <input type="file" accept="image/*,video/*" hidden
                onchange="uploadMedia('${s.id}',this.files[0])"></label>
          </div>
        </div>
      </div>
    </div>`;
  });
  $('#tabbody').innerHTML = html;
}

async function savePictureEvery(n) {
  await saveStyle({ picture_every: n });      // saveStyle repaints the tab
  toast(n === 1 ? 'A picture for every paragraph.'
                : `One picture every ${n} paragraphs — fewer to find.`);
}

async function setPictureMode(sid, mode) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (s.picture_mode === mode) mode = 'auto';
  await saveSlide(sid, { picture_mode: mode });
  state.project = await api(`/api/projects/${state.project.id}`);
  paintMedia();
}

async function choose(sid, cid) {
  const s = state.project.slides.find((x) => x.id === sid);
  s.chosen_id = cid;
  paintMedia();
  await saveSlide(sid, { chosen_id: cid });
}

async function toggleKind(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  const kind = s.prefer_kind === 'image' ? 'video' : 'image';
  await saveSlide(sid, { prefer_kind: kind });
  const r = await api(`/api/projects/${state.project.id}/media`,
    { method: 'POST', body: JSON.stringify({ slide_ids: [sid] }) });
  watchJob(r.job, 'media');
  render();
}

// ------------------------------------------------------------ picture search
// The strip under a slide only has room for a dozen options at thumbnail size.
// This opens the full picker: type any term, ask for photos or clips, and judge
// the hits large. Picking saves straight away, so you can keep searching.
function openMediaSearch(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const term = (s.queries || [])[0] || s.visual_note || s.title || s.beat || '';
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>Find a picture</strong>
        <span class="mono" style="color:var(--ink-faint);min-width:0;overflow:hidden;
              text-overflow:ellipsis;white-space:nowrap">${esc(s.title || s.beat || '')}</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="pdone">done</button>
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="pq" style="flex:1;min-width:220px"
          placeholder="search the archives — e.g. “Grytviken whaling station 1914”"
          value="${esc(term)}">
        <select id="pkind" style="width:auto">
          <option value="image" ${s.prefer_kind === 'video' ? '' : 'selected'}>photos</option>
          <option value="video" ${s.prefer_kind === 'video' ? 'selected' : ''}>clips</option>
          <option value="reaction">reaction gif 😄</option>
        </select>
        <button class="btn sm primary" id="pgo">search</button>
      </div>
      <div class="mono" id="pnote" style="color:var(--ink-faint);margin-bottom:10px"></div>
      <div class="pick-grid" id="pres"></div>
    </div>`;
  document.body.appendChild(wrap);

  const q = wrap.querySelector('#pq');
  const kind = wrap.querySelector('#pkind');
  const go = wrap.querySelector('#pgo');
  const note = wrap.querySelector('#pnote');
  const res = wrap.querySelector('#pres');

  const paint = (list, label) => {
    note.textContent = label;
    res.innerHTML = list.map((c) => `
      <div class="pick ${c.id === s.chosen_id ? 'sel' : ''}" data-id="${esc(c.id)}"
           title="${esc(c.title)}">
        <img src="${thumbUrl(c)}" loading="lazy" onerror="this.parentNode.style.opacity=.25">
        ${c.kind === 'video' ? '<span class="kindtag">clip</span>' : ''}
        ${playBtn(sid, c)}
        <div class="pick-meta">
          <span>${esc(c.provider)}</span>
          <span>${c.width || '?'}×${c.height || '?'}</span>
        </div>
      </div>`).join('') || '<div class="empty-note">came back dry — try a looser term</div>';
    res.querySelectorAll('.pick').forEach((el) => {
      el.onclick = () => {
        res.querySelectorAll('.pick').forEach((o) => o.classList.remove('sel'));
        el.classList.add('sel');
        choose(sid, el.dataset.id);
      };
    });
  };

  const run = async () => {
    const query = q.value.trim();
    if (!query) return q.focus();
    go.disabled = q.disabled = true;
    note.textContent = `searching for “${query}”…`;
    res.innerHTML = '';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/search`,
        { method: 'POST', body: JSON.stringify({ query, kind: kind.value }) });
      Object.assign(s, r.slide);
      const hits = r.results || [];
      paint(hits, `${hits.length} for “${query}” · ${r.added} new to this slide`);
    } catch (e) {
      toast(e.message, true);
      note.textContent = e.message || 'that search failed';
    }
    go.disabled = q.disabled = false;
    q.focus();
  };

  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const close = () => { document.removeEventListener('keydown', onKey); wrap.remove(); paintMedia(); };
  document.addEventListener('keydown', onKey);
  wrap.querySelector('#pdone').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  go.onclick = run;
  q.onkeydown = (e) => { if (e.key === 'Enter') run(); };
  kind.onchange = () => {
    q.placeholder = kind.value === 'reaction'
      ? 'the reaction, not the subject — e.g. "mind blown", "facepalm", "slow clap"'
      : 'search the archives — e.g. "Grytviken whaling station 1914"';
    run();
  };

  paint(s.candidates, s.candidates.length
    ? `${s.candidates.length} options already gathered — or search for something else`
    : 'nothing gathered yet for this slide');
  q.focus();
  q.select();
}

async function uploadMedia(sid, file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await api(`/api/projects/${state.project.id}/slides/${sid}/upload`,
      { method: 'POST', body: fd });
    Object.assign(state.project.slides.find((x) => x.id === sid), r.slide);
    paintMedia();
    toast('added');
  } catch (e) { toast(e.message, true); }
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

function openMapPicker(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const place = s.map_place || s.visual_note || s.title || s.beat || '';
  const hasSaved = !!(s.map_lat || s.map_lon);
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:12px">
        <strong>Get a map</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="mclose">cancel</button>
      </div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="mjump" style="flex:1;min-width:220px"
          placeholder="jump to a place — e.g. “Ziguinchor, Senegal”" value="${esc(place)}">
        <button class="btn sm ghost" id="mjumpgo">jump</button>
      </div>
      <div id="mmap" style="height:380px;border-radius:8px;overflow:hidden;margin-bottom:10px"></div>
      <div class="row" style="margin-bottom:10px">
        <select id="mkind" style="width:auto">
          <option value="satellite">satellite</option>
          <option value="hybrid">satellite + labels</option>
          <option value="terrain">terrain</option>
          <option value="street">street map</option>
        </select>
        <select id="mstyle" style="width:auto">
          <option value="still">still</option>
          <option value="establishing">establishing shot — smooth zoom in</option>
          <option value="reveal">reveal — pull back to context</option>
          <option value="pan">pan — drift in from the side</option>
        </select>
        <div class="spacer"></div>
        <button class="btn sm primary" id="mgo" disabled>click the map first</button>
      </div>
      <div class="mono" id="mnote" style="color:var(--ink-faint)">click anywhere on the map to drop the pin — the zoom you're at is the zoom it renders at</div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { map.remove(); wrap.remove(); };
  wrap.querySelector('#mclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const kindSel = wrap.querySelector('#mkind');
  const styleSel = wrap.querySelector('#mstyle');
  const jump = wrap.querySelector('#mjump');
  const note = wrap.querySelector('#mnote');
  const go = wrap.querySelector('#mgo');
  kindSel.value = MAP_LAYERS_FOR[s.map_kind] ? s.map_kind : 'satellite';
  styleSel.value = ['establishing', 'reveal', 'pan'].includes(s.map_style) ? s.map_style : 'still';

  const startLat = hasSaved ? s.map_lat : 20, startLon = hasSaved ? s.map_lon : 0;
  const startZoom = hasSaved ? (s.map_zoom || 13) : 2;
  const map = L.map(wrap.querySelector('#mmap')).setView([startLat, startLon], startZoom);
  let tileLayers = [];
  let marker = hasSaved ? L.marker([s.map_lat, s.map_lon]).addTo(map) : null;

  function setTiles(kind) {
    tileLayers.forEach((l) => map.removeLayer(l));
    tileLayers = MAP_LAYERS_FOR[kind].map((source) => L.tileLayer(MAP_TILE_URLS[source],
      { attribution: MAP_TILE_ATTR[source] || '', maxZoom: 19 }).addTo(map));
  }
  setTiles(kindSel.value);
  kindSel.onchange = () => setTiles(kindSel.value);

  function armGo() {
    go.disabled = false;
    go.textContent = 'get it';
  }
  map.on('click', (e) => {
    if (marker) marker.setLatLng(e.latlng); else marker = L.marker(e.latlng).addTo(map);
    armGo();
  });
  if (marker) armGo();

  jump.onclick = null;
  wrap.querySelector('#mjumpgo').onclick = async () => {
    const q = jump.value.trim();
    if (!q) return jump.focus();
    note.textContent = 'looking it up…';
    try {
      const r = await api(`/api/maps/geocode?q=${encodeURIComponent(q)}`);
      map.setView([r.lat, r.lon], 13);
      note.textContent = 'click to drop the pin here, or pan/zoom first';
    } catch (e) {
      note.textContent = e.message;
    }
  };

  go.onclick = async () => {
    if (!marker) return;
    const { lat, lng } = marker.getLatLng();
    go.disabled = true;
    note.textContent = 'fetching tiles…';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/map`, {
        method: 'POST',
        body: JSON.stringify({
          lat, lon: lng, zoom: map.getZoom(),
          label: jump.value.trim(),
          kind: kindSel.value, style: styleSel.value,
        }),
      });
      Object.assign(s, r.slide);
      paintMedia();
      toast('added');
      close();
    } catch (e) {
      note.textContent = e.message;
      armGo();
    }
  };
  // Leaflet sizes itself off the DOM at construction time; the modal box
  // isn't done laying out yet on that first tick, so the tile grid renders
  // wrong until this nudges it once the box has its real size.
  setTimeout(() => map.invalidateSize(), 0);
}

// ------------------------------------------------------------------- board
// The handwritten format. Everything here is drawn server-side by Pillow and
// shown as a flat png, the same deal the thumbnail gets: one implementation of
// the layout, and what the editor shows is literally a frame of the render.
function boardKnobs(st, saver) {
  const hand = st.board_hand || 'marker';
  // The hands come from the server — it owns which faces are bundled, and a
  // second list here would go stale the first time one changed.
  const hands = state.boardHands || [{ key: 'marker', label: 'Marker', blurb: '' }];
  return `
    <label class="field"><span>Handwriting</span>
      <select onchange="${saver}({board_hand:this.value})">
        ${hands.map((h) => `<option value="${h.key}" ${h.key === hand ? 'selected' : ''}
          >${esc(h.label)}${h.blurb ? ' — ' + esc(h.blurb.split('.')[0].toLowerCase()) : ''}</option>`).join('')}
      </select></label>
    <label class="field"><span>The board</span>
      <input type="text" value="${esc(st.board_ground || '#3A4552')}"
        onchange="${saver}({board_ground:this.value})"></label>
    <label class="field"><span>Surface tooth — <b>${(st.board_grain ?? 0.5).toFixed(2)}</b></span>
      <input type="range" min="0" max="1" step="0.05" value="${st.board_grain ?? 0.5}"
        onchange="${saver}({board_grain:+this.value})"></label>
    <label class="field"><span>How fast a line lands — <b>${(st.board_settle ?? 0.5).toFixed(2)}s</b></span>
      <input type="range" min="0.18" max="1.2" step="0.02" value="${st.board_settle ?? 0.5}"
        onchange="${saver}({board_settle:+this.value})"></label>`;
}

function cutKnobs(st, saver) {
  const info = cutInfo(st.format);
  if (!info) return '';
  return `
    <div class="mono" style="color:var(--ink-faint);margin:-4px 0 12px">
      made for ${esc(info.for.toLowerCase())}</div>
    <label class="field"><span>Look</span>
      <select onchange="${saver}({cut_look:this.value})">
        ${info.looks.map((l) => `<option value="${l.key}" ${l.key === (st.cut_look || '') ? 'selected' : ''}
          >${esc(l.label)}</option>`).join('')}
      </select></label>`;
}

function cutUrl(sid, t = 0.5) {
  return `/api/projects/${state.project.id}/slides/${sid}/cut.png?t=${t}&v=${state.boardV || 0}`;
}

async function planCues(redo) {
  if (redo && !confirm('Rewrite every paragraph\'s cues for this cut, including the ones you edited?')) return;
  const r = await api(`/api/projects/${state.project.id}/cues/plan`,
    { method: 'POST', body: JSON.stringify({ redo: !!redo }) });
  watchJob(r.job, 'media');
  render();
}

// The cue editor: the paragraph's cues for this cut as JSON — the same shape
// the writer produces, which is the honest interface for a list of
// differently-shaped things — with a scrubbable frame redrawn on every save.
function openCueEditor(sid) {
  const p = state.project;
  const s = p.slides.find((x) => x.id === sid);
  const fmt = p.style.format;
  const info = cutInfo(fmt);
  if (!s || !info) return;
  const written = (s.cues || {})[fmt] || [];
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:12px">
        <strong>What this paragraph puts on screen — ${esc(info.label)}</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="cclose">close</button>
      </div>
      <div class="grid-2">
        <div>
          <div class="mono" style="color:var(--ink-faint);margin-bottom:8px">
            kinds: ${esc(info.kinds)}. Each cue's <b>on</b> is the words it lands on.
            ${written.length ? '' : '<br>Nothing written yet — this is drawn from the narration.'}</div>
          <textarea id="ccues" rows="16" spellcheck="false"
            style="font-family:monospace;font-size:12px"
            placeholder='[{"kind": "...", "on": "first words it lands on"}]'
          >${esc(written.length ? JSON.stringify(written, null, 2) : '')}</textarea>
          <div class="row" style="margin-top:10px">
            <button class="btn sm primary" id="csave">save</button>
            <div class="spacer"></div>
            <button class="btn sm ghost" id="cclear" title="go back to drawing it from the narration">
              clear</button>
          </div>
          <div class="mono" style="color:var(--ink-faint);margin-top:10px">
            ${esc(s.narration.slice(0, 260))}</div>
        </div>
        <div>
          <img id="cprev" src="${cutUrl(sid, 0.5)}" style="width:100%;border-radius:8px;background:#111">
          <label class="field" style="margin-top:8px"><span>Scrub through the paragraph</span>
            <input type="range" id="cscrub" min="0" max="1" step="0.02" value="0.5"></label>
          <div class="mono" id="cstate" style="color:var(--ink-faint)"></div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { wrap.remove(); paintMedia(); };
  wrap.querySelector('#cclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  const img = wrap.querySelector('#cprev');
  const scrub = wrap.querySelector('#cscrub');
  scrub.onchange = () => { img.src = cutUrl(sid, scrub.value); };
  const status = wrap.querySelector('#cstate');

  async function send(cues) {
    status.textContent = 'drawing…';
    try {
      const updated = await saveSlide(sid, { cues: { [fmt]: cues } });
      Object.assign(s, updated);
      state.boardV = (state.boardV || 0) + 1;
      img.src = cutUrl(sid, scrub.value);
      status.textContent = 'saved';
    } catch (e) { status.textContent = String(e.message || e); }
  }
  wrap.querySelector('#csave').onclick = () => {
    let cues;
    try { cues = JSON.parse(wrap.querySelector('#ccues').value || '[]'); }
    catch (e) { status.textContent = `That isn't valid JSON: ${e.message}`; return; }
    if (!Array.isArray(cues)) { status.textContent = 'Cues are a list: [ {...}, {...} ]'; return; }
    send(cues);
  };
  wrap.querySelector('#cclear').onclick = () => {
    wrap.querySelector('#ccues').value = '';
    send([]);
  };
}

function boardUrl(sid) {
  return `/api/projects/${state.project.id}/slides/${sid}/board.png?v=${state.boardV || 0}`;
}

function bumpBoards() {
  state.boardV = (state.boardV || 0) + 1;
}

async function planBoards(redo) {
  if (redo && !confirm('Rewrite every board, including the ones you wrote yourself?')) return;
  const r = await api(`/api/projects/${state.project.id}/board/plan`,
    { method: 'POST', body: JSON.stringify({ redo: !!redo }) });
  watchJob(r.job, 'media');
  render();
}

// The board editor: the four fields a template draws from, and the finished
// board redrawn after every change so you are editing the thing itself.
function openBoardEditor(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const tpls = state.boardTemplates || [];
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:12px">
        <strong>What this slide writes</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="bclose">close</button>
      </div>
      <div class="grid-2">
        <div>
          <label class="field"><span>Template</span>
            <select id="btpl">
              <option value="auto">auto — pick from what I write</option>
              ${tpls.map((t) => `<option value="${t.key}"
                ${t.key === s.board_template ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}
            </select></label>
          <div class="mono" id="bblurb" style="color:var(--ink-faint);margin:-8px 0 12px"></div>
          <label class="field"><span>The line it is about</span>
            <input type="text" id="blead" value="${esc(s.board_lead || '')}"
              placeholder="2-7 words, no full stop"></label>
          <label class="field"><span>Lines under it — one per line</span>
            <textarea id="bpoints" rows="6" placeholder="two to six words each
* a line starting with a star is picked out in the accent
this | that pairs up the two columns of a versus board
> a line starting with a chevron is the called-out line of code"
>${esc((s.board_points || []).join('\n'))}</textarea></label>
          <label class="field"><span>Footnote, caption or attribution</span>
            <input type="text" id="bnote" value="${esc(s.board_note || '')}"></label>
          <div class="row">
            <button class="btn sm primary" id="bsave">save</button>
            <button class="btn sm ghost" id="bdiagram">draw a diagram…</button>
            <div class="spacer"></div>
            <button class="btn sm ghost" id="bclear" title="go back to lines pulled out of the narration">
              clear</button>
          </div>
          <div class="mono" style="color:var(--ink-faint);margin-top:10px">
            ${esc(s.narration.slice(0, 220))}</div>
        </div>
        <div>
          <img id="bprev" src="${boardUrl(sid)}"
            style="width:100%;border-radius:8px;background:#2f3843">
          <div class="mono" id="bstate" style="color:var(--ink-faint);margin-top:8px">
            the finished board — it arrives element by element as you talk</div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { wrap.remove(); paintMedia(); };
  wrap.querySelector('#bclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const tpl = wrap.querySelector('#btpl');
  const blurb = wrap.querySelector('#bblurb');
  const showBlurb = () => {
    const t = tpls.find((x) => x.key === tpl.value);
    blurb.textContent = t ? t.blurb : 'Picks the template that fits what you write, '
      + 'and avoids repeating the slide before it.';
  };
  tpl.onchange = () => { showBlurb(); save(); };
  showBlurb();

  async function save() {
    const body = {
      board_template: tpl.value,
      board_lead: wrap.querySelector('#blead').value,
      board_points: wrap.querySelector('#bpoints').value.split('\n'),
      board_note: wrap.querySelector('#bnote').value,
    };
    wrap.querySelector('#bstate').textContent = 'drawing…';
    const updated = await saveSlide(sid, body);
    Object.assign(s, updated);
    bumpBoards();
    wrap.querySelector('#bprev').src = boardUrl(sid);
    wrap.querySelector('#bstate').textContent = 'saved';
  }
  wrap.querySelector('#bsave').onclick = save;
  wrap.querySelector('#bclear').onclick = async () => {
    wrap.querySelector('#blead').value = '';
    wrap.querySelector('#bpoints').value = '';
    wrap.querySelector('#bnote').value = '';
    tpl.value = 'auto';
    await save();
  };
  wrap.querySelector('#bdiagram').onclick = () => { close(); openDiagramEditor(sid); };
}

// ----------------------------------------------------------------- diagrams
// A spec in, a drawing out. The left half is the spec as lines, because typing
// JSON by hand is miserable; the JSON itself is one click away, because that
// is the shape an agent writes and the shape you paste back in.
function diagramToLines(spec) {
  const nodes = (spec.nodes || []).map((n) =>
    `${n.accent ? '*' : ''}${n.label}${n.note ? ' | ' + n.note : ''}${n.group ? ' @' + n.group : ''}`);
  const edges = (spec.edges || []).map((e) =>
    `${e.from} > ${e.to}${e.label ? ' : ' + e.label : ''}${e.dashed ? ' ~' : ''}`);
  return { nodes: nodes.join('\n'), edges: edges.join('\n') };
}

function linesToSpec(kind, title, nodeText, edgeText, note, reveal) {
  const nodes = nodeText.split('\n').map((raw) => raw.trim()).filter(Boolean).map((raw) => {
    const accent = raw.startsWith('*');
    let rest = accent ? raw.slice(1).trim() : raw;
    let group = '';
    const at = rest.lastIndexOf(' @');
    if (at > 0) { group = rest.slice(at + 2).trim(); rest = rest.slice(0, at); }
    const [label, ...note2] = rest.split('|');
    return { id: label.trim(), label: label.trim(), note: note2.join('|').trim(),
             group, accent };
  });
  const edges = edgeText.split('\n').map((raw) => raw.trim()).filter(Boolean).map((raw) => {
    const dashed = raw.endsWith('~');
    let rest = dashed ? raw.slice(0, -1).trim() : raw;
    const [pair, ...label] = rest.split(':');
    const [from, to] = pair.split('>').map((x) => x.trim());
    return { from, to, label: label.join(':').trim(), dashed };
  }).filter((e) => e.from && e.to);
  return { kind, title, nodes, edges, note, reveal };
}

function openDiagramEditor(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const kinds = state.diagramKinds || [];
  const spec = Object.keys(s.diagram || {}).length ? s.diagram
    : { kind: 'flow', title: s.board_lead || s.title || '', nodes: [], edges: [],
        note: '', reveal: 'sequence' };
  const lines = diagramToLines(spec);
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>Draw a diagram</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="djson">show the spec</button>
        <button class="btn sm ghost" id="dclose">close</button>
      </div>
      <div class="grid-2">
        <div style="overflow:auto;max-height:calc(100vh - 160px);padding-right:16px">
          <div class="panel" style="background:#13151c;margin:0 0 16px;padding:14px">
            <div class="row" style="margin-bottom:8px">
              <span style="font-size:13px">✨ Ask Claude to draw this</span>
            </div>
            <textarea id="daskwhat" rows="2" style="margin-bottom:8px"
              placeholder="Leave blank to let Claude read the paragraph and pick a shape, or steer it — “as a cycle”, “put the database in the middle”…"></textarea>
            <button class="btn sm primary" id="dask">draw it for me</button>
            <span class="mono" id="daskstate" style="color:var(--ink-faint);margin-left:8px"></span>
          </div>
          <label class="field"><span>Layout</span>
            <select id="dkind">
              ${kinds.map((k) => `<option value="${k.key}"
                ${k.key === spec.kind ? 'selected' : ''}>${esc(k.label)}</option>`).join('')}
            </select></label>
          <div class="mono" id="dblurb" style="color:var(--ink-faint);margin:-8px 0 12px"></div>
          <label class="field"><span>Heading</span>
            <input type="text" id="dtitle" value="${esc(spec.title || '')}"></label>
          <label class="field"><span>Boxes — one per line</span>
            <textarea id="dnodes" rows="6" placeholder="Browser
Edge cache | 40ms
*Your server | the slow bit
a star picks one out, | adds a note, @ puts it in a column"
>${esc(lines.nodes)}</textarea></label>
          <label class="field"><span>Arrows — “from &gt; to : label”, ~ for dashed (flow only)</span>
            <textarea id="dedges" rows="3" placeholder="Browser > Edge cache : GET /
Edge cache > Your server : miss ~"
>${esc(lines.edges)}</textarea></label>
          <label class="field"><span>Footnote</span>
            <input type="text" id="dnote" value="${esc(spec.note || '')}"></label>
          <div class="row">
            <button class="btn sm primary" id="duse">use it on this slide</button>
            <button class="btn sm ghost" id="dstill">as a still, not a drawing</button>
          </div>
          <div class="mono" id="dstate" style="color:var(--ink-faint);margin-top:10px"></div>
        </div>
        <div style="align-self:start">
          <img id="dprev" style="width:100%;border-radius:8px;background:#2f3843">
          <textarea id="dspec" rows="12" class="mono" style="display:none;margin-top:10px"
            placeholder="paste a spec here"></textarea>
          <div class="row" style="margin-top:8px;display:none" id="dspecrow">
            <button class="btn sm ghost" id="dspecload">load that spec</button>
          </div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const q = (id) => wrap.querySelector(id);
  const close = () => { wrap.remove(); paintMedia(); };
  q('#dclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const showBlurb = () => {
    const k = kinds.find((x) => x.key === q('#dkind').value);
    q('#dblurb').textContent = k ? `${k.blurb} (${k.wants})` : '';
  };
  const current = () => linesToSpec(
    q('#dkind').value, q('#dtitle').value, q('#dnodes').value, q('#dedges').value,
    q('#dnote').value, spec.reveal || 'sequence');

  let timer = null;
  async function redraw() {
    const body = { spec: current(), accent: state.project.style.accent,
                   hand: state.project.style.board_hand || 'marker' };
    q('#dspec').value = JSON.stringify(body.spec, null, 2);
    try {
      const res = await fetch('/api/diagram/preview',
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json()).detail || 'no');
      const blob = await res.blob();
      const old = q('#dprev').src;
      q('#dprev').src = URL.createObjectURL(blob);
      if (old.startsWith('blob:')) URL.revokeObjectURL(old);
      q('#dstate').textContent = '';
    } catch (e) {
      q('#dstate').textContent = e.message;
    }
  }
  const nudge = () => { clearTimeout(timer); timer = setTimeout(redraw, 260); };
  ['#dkind', '#dtitle', '#dnodes', '#dedges', '#dnote'].forEach((id) => {
    q(id).oninput = nudge;
    q(id).onchange = () => { showBlurb(); nudge(); };
  });
  showBlurb();
  redraw();

  q('#djson').onclick = () => {
    const box = q('#dspec'), row = q('#dspecrow');
    const on = box.style.display === 'none';
    box.style.display = row.style.display = on ? '' : 'none';
    q('#djson').textContent = on ? 'hide the spec' : 'show the spec';
  };
  q('#dspecload').onclick = () => {
    let loaded;
    try { loaded = JSON.parse(q('#dspec').value); }
    catch (e) { return (q('#dstate').textContent = 'that is not valid JSON'); }
    q('#dkind').value = loaded.kind || 'flow';
    q('#dtitle').value = loaded.title || '';
    q('#dnote').value = loaded.note || '';
    const l = diagramToLines(loaded);
    q('#dnodes').value = l.nodes;
    q('#dedges').value = l.edges;
    showBlurb();
    redraw();
  };

  async function use(motion) {
    q('#dstate').textContent = 'drawing…';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/diagram`,
        { method: 'POST', body: JSON.stringify({ spec: current(), motion }) });
      Object.assign(s, r.slide);
      bumpBoards();
      toast(motion === 'still' ? 'drawn' : 'drawn — it inks in on screen');
      close();
    } catch (e) {
      q('#dstate').textContent = e.message;
    }
  }
  q('#duse').onclick = () => use('reveal');
  q('#dstill').onclick = () => use('still');

  q('#dask').onclick = async () => {
    const btn = q('#dask');
    btn.disabled = true;
    q('#daskstate').textContent = 'thinking…';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/diagram/generate`,
        { method: 'POST', body: JSON.stringify({ instruction: q('#daskwhat').value.trim() }) });
      let j;
      for (;;) {
        j = await api(`/api/jobs/${r.job}`);
        if (j.state !== 'running') break;
        await new Promise((res) => setTimeout(res, 900));
      }
      if (j.state === 'error') throw new Error(j.error || 'Claude could not draw this one.');
      const loaded = j.result.spec;
      q('#dkind').value = loaded.kind || 'flow';
      q('#dtitle').value = loaded.title || '';
      q('#dnote').value = loaded.note || '';
      const l = diagramToLines(loaded);
      q('#dnodes').value = l.nodes;
      q('#dedges').value = l.edges;
      showBlurb();
      redraw();
      q('#daskstate').textContent = 'drawn from the narration — tweak anything, then use it';
    } catch (e) {
      q('#daskstate').textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  };
}

// ------------------------------------------------------- custom slide design
// The open-ended sibling of the diagram editor: no fixed layout, just
// elements on a canvas. Describing what you want in words is the main way in
// — Claude writes the spec — and every element stays editable afterwards, so
// a design you half-like is a starting point rather than a take-it-or-leave-it.
const CUSTOM_ANIMS = ['fade', 'rise', 'fly-left', 'fly-right', 'pop', 'none'];
const CUSTOM_FONTS = ['hand', 'sans', 'serif', 'mono', 'display'];
const CUSTOM_SIZES = ['sm', 'md', 'lg', 'xl', 'xxl'];

// A spec can legitimately carry a value this build doesn't know about — a
// newer size, an animation added server-side. Keeping it as an option means
// editing some other field can't silently rewrite it to the first one.
function customOptions(list, current) {
  const all = list.includes(current) || !current ? list : [...list, current];
  return all.map((v) => `<option ${v === current ? 'selected' : ''}>${esc(v)}</option>`).join('');
}

function blankCustomElement(type) {
  const base = { type, x: 0.1, y: 0.1, w: 0.4, h: 0.2, order: 0, anim: 'fade', opacity: 1 };
  if (type === 'text') {
    return { ...base, text: 'new text', size: 'lg', align: 'left',
             color: '#ffffff', font: 'hand' };
  }
  if (type === 'image') return { ...base, query: '', fit: 'cover' };
  return { ...base, color: '#E8C36A', fill: true, stroke: 4 };
}

// Opened against one paragraph (from the Media tab) or against nothing at all
// (the Video style picker's "Design a style…"). The editor is the same either
// way; what changes is where Claude's brief comes from — a paragraph to read,
// or only the words you type — and whether the result lands on a slide or in
// the style library.
function openCustomEditor(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  openCustomDesigner({
    sid,
    slide: s,
    projectId: state.project.id,
    accent: state.project.style.accent,
    hand: state.project.style.board_hand || 'marker',
    spec: Object.keys(s.custom || {}).length
      ? JSON.parse(JSON.stringify(s.custom))
      : { background: '', reveal: 'sequence', elements: [] },
  });
}

// No project needed: this is how a style gets made from the home page, before
// there is a video to design it against.
function openStyleDesigner() {
  openCustomDesigner({
    styleMode: true,
    projectId: '',
    accent: (state.project && state.project.style.accent) || '#E8C36A',
    hand: (state.project && state.project.style.board_hand) || 'marker',
    spec: { background: '', reveal: 'sequence', elements: [] },
  });
}

function openCustomDesigner(opts) {
  const styleMode = !!opts.styleMode;
  const s = opts.slide;
  const sid = opts.sid;
  let spec = opts.spec;

  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>${styleMode ? 'Design a video style' : 'Design a slide'}</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="cjson">show the spec</button>
        <button class="btn sm ghost" id="cclose">close</button>
      </div>
      <div class="grid-2">
        <div style="overflow:auto;max-height:calc(100vh - 160px);padding-right:16px">
          <div class="panel" style="background:#13151c;margin:0 0 16px;padding:14px">
            <div class="row" style="margin-bottom:8px">
              <span style="font-size:13px">✨ ${styleMode
                ? 'Describe the look you want' : 'Ask Claude to design this slide'}</span>
            </div>
            <textarea id="caskwhat" rows="2" style="margin-bottom:8px"
              placeholder="${styleMode
                ? 'e.g. “one huge number on near-black with a thin accent rule”, “a full-bleed photo with a quote over a dark scrim”, “three cards across the middle”…'
                : 'Leave blank to let Claude read the paragraph and design something, or steer it — “one huge number over a photo”, “three cards across the middle”, “a quote, big, on black”…'}"></textarea>
            <button class="btn sm primary" id="cask">design it for me</button>
            <span class="mono" id="caskstate" style="color:var(--ink-faint);margin-left:8px"></span>
          </div>
          ${styleMode ? `<div class="mono" style="color:var(--ink-faint);margin-bottom:12px">
            Every paragraph of the video gets this design, with its own words and
            pictures swapped into it. So write the text here as a placeholder
            showing what belongs in each slot, not as anything about one subject.</div>` : ''}
          <div class="row" style="margin-bottom:10px">
            <label class="field" style="flex:1;margin:0"><span>Background</span>
              <input type="text" id="cbg" placeholder="blank = the usual board"
                value="${esc(spec.background || '')}"></label>
          </div>
          <div id="cels"></div>
          <div class="row" style="margin:12px 0">
            <span class="mono" style="color:var(--ink-faint)">add:</span>
            <button class="btn xs ghost" data-add="text">text</button>
            <button class="btn xs ghost" data-add="rect">rect</button>
            <button class="btn xs ghost" data-add="circle">circle</button>
            <button class="btn xs ghost" data-add="line">line</button>
            <button class="btn xs ghost" data-add="image">image</button>
          </div>
          <div class="row">
            ${styleMode ? '' : `
              <button class="btn sm primary" id="cuse">use it on this slide</button>
              <button class="btn sm ghost" id="cstill">as a still, not animated</button>`}
            <button class="btn sm ${styleMode ? 'primary' : 'ghost'}" id="csave"
              title="keep this design as a reusable video style">
              ${styleMode ? 'save this style' : 'save as a style…'}</button>
          </div>
          <div class="mono" id="cstate" style="color:var(--ink-faint);margin-top:10px"></div>
        </div>
        <div style="align-self:start">
          <img id="cprev" style="width:100%;border-radius:8px;background:#2f3843">
          <div class="mono" style="color:var(--ink-faint);margin-top:6px">
            ${styleMode
              ? 'Image slots stay empty here — each paragraph fetches its own picture when the video is written.'
              : 'Image elements only show here once they’ve been fetched — press “use it on this slide” to pull them from the archives.'}</div>
          <textarea id="cspec" rows="14" class="mono" style="display:none;margin-top:10px"></textarea>
          <div class="row" style="margin-top:8px;display:none" id="cspecrow">
            <button class="btn sm ghost" id="cspecload">load that spec</button>
          </div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const q = (id) => wrap.querySelector(id);
  // In style mode there is no Media tab behind this modal to repaint.
  const close = () => { wrap.remove(); if (!styleMode) paintMedia(); };
  q('#cclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const num = (v) => Math.round((+v || 0) * 100) / 100;

  function paintElements() {
    q('#cels').innerHTML = spec.elements.map((el, i) => `
      <div class="panel" style="background:#13151c;margin:0 0 10px;padding:12px">
        <div class="row" style="margin-bottom:8px">
          <strong style="font-size:13px">${i + 1}. ${esc(el.type)}</strong>
          <div class="spacer"></div>
          <button class="btn xs ghost" data-up="${i}" ${i ? '' : 'disabled'}>↑</button>
          <button class="btn xs ghost danger" data-del="${i}">remove</button>
        </div>
        ${el.type === 'text' ? `
          <textarea rows="2" data-f="text" data-i="${i}"
            style="margin-bottom:8px">${esc(el.text || '')}</textarea>
          <div class="row" style="gap:6px;margin-bottom:8px">
            <select data-f="size" data-i="${i}" style="width:auto">
              ${customOptions(CUSTOM_SIZES, el.size)}
            </select>
            <select data-f="font" data-i="${i}" style="width:auto">
              ${customOptions(CUSTOM_FONTS, el.font)}
            </select>
            <select data-f="align" data-i="${i}" style="width:auto">
              ${customOptions(['left', 'center', 'right'], el.align)}
            </select>
            <input type="text" data-f="color" data-i="${i}" value="${esc(el.color || '#ffffff')}"
              style="width:90px">
          </div>` : ''}
        ${el.type === 'image' ? `
          <input type="text" data-f="query" data-i="${i}" placeholder="what to search the archives for"
            value="${esc(el.query || '')}" style="margin-bottom:8px">
          <div class="row" style="gap:6px;margin-bottom:8px">
            <select data-f="fit" data-i="${i}" style="width:auto">
              ${customOptions(['cover', 'contain'], el.fit)}
            </select>
            <span class="mono" style="color:var(--ink-faint)">
              ${el.local_path ? 'fetched' : 'not fetched yet'}</span>
          </div>` : ''}
        ${['rect', 'circle', 'line'].includes(el.type) ? `
          <div class="row" style="gap:6px;margin-bottom:8px">
            <input type="text" data-f="color" data-i="${i}" value="${esc(el.color || '#E8C36A')}"
              style="width:90px">
            <label class="row" style="gap:4px;cursor:pointer">
              <input type="checkbox" data-f="fill" data-i="${i}" style="width:auto"
                ${el.fill ? 'checked' : ''}><span class="mono">filled</span></label>
            <input type="number" data-f="stroke" data-i="${i}" value="${el.stroke || 4}"
              min="1" max="20" style="width:70px" title="stroke width">
          </div>` : ''}
        <div class="row" style="gap:6px">
          ${['x', 'y', 'w', 'h'].map((f) => `
            <label class="mono" style="color:var(--ink-faint)">${f}
              <input type="number" data-f="${f}" data-i="${i}" value="${num(el[f])}"
                step="0.01" min="0" max="1" style="width:74px"></label>`).join('')}
        </div>
        <div class="row" style="gap:6px;margin-top:8px">
          <label class="mono" style="color:var(--ink-faint)">order
            <input type="number" data-f="order" data-i="${i}" value="${el.order || 0}"
              min="0" max="20" style="width:66px"></label>
          <select data-f="anim" data-i="${i}" style="width:auto">
            ${customOptions(CUSTOM_ANIMS, el.anim)}
          </select>
          <label class="mono" style="color:var(--ink-faint)">opacity
            <input type="number" data-f="opacity" data-i="${i}"
              value="${el.opacity === undefined ? 1 : el.opacity}"
              step="0.05" min="0" max="1" style="width:74px"></label>
        </div>
      </div>`).join('') || '<div class="empty-note">No elements yet — ask Claude, or add one below.</div>';

    q('#cels').querySelectorAll('[data-f]').forEach((input) => {
      const i = +input.dataset.i, f = input.dataset.f;
      const handler = () => {
        const el = spec.elements[i];
        if (input.type === 'checkbox') el[f] = input.checked;
        else if (input.type === 'number') el[f] = +input.value;
        else el[f] = input.value;
        if (['fill', 'size', 'font', 'align', 'fit', 'anim'].includes(f)) paintElements();
        nudge();
      };
      input.oninput = handler;
      input.onchange = handler;
    });
    q('#cels').querySelectorAll('[data-del]').forEach((b) => {
      b.onclick = () => { spec.elements.splice(+b.dataset.del, 1); paintElements(); nudge(); };
    });
    q('#cels').querySelectorAll('[data-up]').forEach((b) => {
      b.onclick = () => {
        const i = +b.dataset.up;
        [spec.elements[i - 1], spec.elements[i]] = [spec.elements[i], spec.elements[i - 1]];
        paintElements();
        nudge();
      };
    });
  }

  wrap.querySelectorAll('[data-add]').forEach((b) => {
    b.onclick = () => {
      spec.elements.push(blankCustomElement(b.dataset.add));
      paintElements();
      nudge();
    };
  });
  q('#cbg').oninput = () => { spec.background = q('#cbg').value; nudge(); };

  let timer = null;
  async function redraw() {
    q('#cspec').value = JSON.stringify(spec, null, 2);
    if (!spec.elements.length) { q('#cstate').textContent = ''; return; }
    try {
      const res = await fetch('/api/custom/preview',
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ spec, project_id: opts.projectId || '',
                                 hand: opts.hand }) });
      if (!res.ok) throw new Error((await res.json()).detail || 'no');
      const blob = await res.blob();
      const old = q('#cprev').src;
      q('#cprev').src = URL.createObjectURL(blob);
      if (old.startsWith('blob:')) URL.revokeObjectURL(old);
      q('#cstate').textContent = '';
    } catch (e) {
      q('#cstate').textContent = e.message;
    }
  }
  const nudge = () => { clearTimeout(timer); timer = setTimeout(redraw, 300); };

  q('#cjson').onclick = () => {
    const box = q('#cspec'), row = q('#cspecrow');
    const on = box.style.display === 'none';
    box.style.display = row.style.display = on ? '' : 'none';
    q('#cjson').textContent = on ? 'hide the spec' : 'show the spec';
  };
  q('#cspecload').onclick = () => {
    let loaded;
    try { loaded = JSON.parse(q('#cspec').value); }
    catch { return (q('#cstate').textContent = 'that is not valid JSON'); }
    spec = loaded;
    q('#cbg').value = spec.background || '';
    paintElements();
    redraw();
  };

  async function use(motion) {
    if (!spec.elements.length) return (q('#cstate').textContent = 'nothing to draw yet');
    q('#cstate').textContent = 'drawing…';
    try {
      const r = await api(`/api/projects/${opts.projectId}/slides/${sid}/custom`,
        { method: 'POST', body: JSON.stringify({ spec, motion }) });
      let j;
      for (;;) {
        j = await api(`/api/jobs/${r.job}`);
        if (j.state !== 'running') break;
        q('#cstate').textContent = j.message || 'drawing…';
        await new Promise((res) => setTimeout(res, 900));
      }
      if (j.state === 'error') throw new Error(j.error || 'Could not draw that slide.');
      Object.assign(s, j.result.slide);
      bumpBoards();
      toast(motion === 'still' ? 'designed' : 'designed — it builds on screen');
      close();
    } catch (e) {
      q('#cstate').textContent = e.message;
    }
  }
  if (!styleMode) {
    q('#cuse').onclick = () => use('reveal');
    q('#cstill').onclick = () => use('still');
  }

  q('#csave').onclick = async () => {
    if (!spec.elements.length) return (q('#cstate').textContent = 'nothing to save yet');
    const name = prompt('Name this style\n(it joins Documentary, Video essay and '
      + 'Handwritten board in the Video style picker)', 'My slide style');
    if (!name) return;
    q('#cstate').textContent = 'saving…';
    try {
      await api('/api/slide-styles', { method: 'POST',
        body: JSON.stringify({ spec, name, hand: opts.hand }) });
      state.slideStyles = null;
      await ensureSlideStyles();
      toast(`saved — “${name}” is now a video style`);
      q('#cstate').textContent = '';
      // Made from the picker: close back onto it so the new tile is right there.
      if (styleMode) { close(); route(); }
    } catch (e) {
      q('#cstate').textContent = e.message;
    }
  };

  q('#cask').onclick = async () => {
    const btn = q('#cask');
    btn.disabled = true;
    q('#caskstate').textContent = 'designing…';
    try {
      const brief = q('#caskwhat').value.trim();
      // With no project there is no paragraph to read, so the brief is the
      // whole input and a different endpoint answers it.
      const r = styleMode
        ? await api('/api/slide-styles/design',
            { method: 'POST', body: JSON.stringify({ description: brief,
                                                     accent: opts.accent }) })
        : await api(`/api/projects/${opts.projectId}/slides/${sid}/custom/generate`,
            { method: 'POST', body: JSON.stringify({ instruction: brief }) });
      let j;
      for (;;) {
        j = await api(`/api/jobs/${r.job}`);
        if (j.state !== 'running') break;
        await new Promise((res) => setTimeout(res, 900));
      }
      if (j.state === 'error') throw new Error(j.error || 'Claude could not design this one.');
      spec = j.result.spec;
      q('#cbg').value = spec.background || '';
      paintElements();
      redraw();
      q('#caskstate').textContent = styleMode
        ? 'drawn — tweak anything, then save it as a style'
        : 'designed from the narration — tweak anything, then use it';
    } catch (e) {
      q('#caskstate').textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  };

  paintElements();
  redraw();
}

async function gatherMedia() {
  const r = await api(`/api/projects/${state.project.id}/media`,
    { method: 'POST', body: JSON.stringify({}) });
  watchJob(r.job, 'media');
  render();
}

// --------------------------------------------------------------- thumbnail
// The thumbnail is drawn server-side by Pillow and shown here as a plain jpeg:
// no canvas, no second implementation of the layout to keep in step with the
// renderer. Every change saves, redraws and swaps the preview's src.
function thumbArt(key, accent) {
  const a = esc(accent), ink = '#c9cdd6', dim = '#3a4150', photo = '#2a2f3a';
  const svg = {
    loupe: `<rect width="160" height="90" fill="#16181e"/>
      <circle cx="112" cy="45" r="30" fill="#2a2f3a"/>
      <circle cx="112" cy="45" r="26" fill="${photo}"/>
      ${Array.from({length: 22}, (_, n) => {
        const r = n * 360 / 22 * Math.PI / 180;
        return `<line x1="${112 + Math.cos(r) * 27}" y1="${45 + Math.sin(r) * 27}"
                      x2="${112 + Math.cos(r) * 32}" y2="${45 + Math.sin(r) * 32}"
                      stroke="${a}" stroke-width="2.6"/>`;
      }).join('')}
      <circle cx="112" cy="45" r="27" fill="none" stroke="${a}" stroke-width="2"/>
      <path d="M 96 30 A 22 22 0 0 0 92 48" fill="none" stroke="#fff"
        stroke-width="3" opacity=".45"/>
      <rect x="12" y="24" width="26" height="3" fill="${a}"/>
      <rect x="12" y="34" width="62" height="10" fill="${ink}"/>
      <rect x="12" y="48" width="48" height="10" fill="${ink}"/>
      <rect x="12" y="64" width="20" height="3" fill="${a}"/>`,
    banner: `<rect width="160" height="90" fill="${photo}"/>
      <rect y="46" width="160" height="44" fill="#0c0d11" opacity=".82"/>
      <rect x="10" y="56" width="10" height="4" fill="${a}"/>
      <rect x="26" y="56" width="34" height="3" fill="${ink}" opacity=".55"/>
      <rect x="10" y="65" width="120" height="9" fill="${ink}"/>
      <rect x="10" y="77" width="72" height="9" fill="${ink}"/>`,
    split: `<rect width="160" height="90" fill="#12141a"/>
      <rect x="88" width="72" height="90" fill="${photo}"/>
      <rect x="86" width="3" height="90" fill="${a}"/>
      <rect x="10" y="22" width="8" height="4" fill="${a}"/>
      <rect x="22" y="22" width="30" height="3" fill="${ink}" opacity=".55"/>
      <rect x="10" y="34" width="66" height="9" fill="${ink}"/>
      <rect x="10" y="46" width="52" height="9" fill="${ink}"/>
      <rect x="10" y="62" width="20" height="3" fill="${a}"/>`,
    spotlight: `<rect width="160" height="90" fill="#111318"/>
      <ellipse cx="104" cy="44" rx="34" ry="30" fill="${photo}"/>
      <ellipse cx="104" cy="44" rx="22" ry="19" fill="#4b525f"/>
      <rect x="10" y="12" width="44" height="12" rx="3" fill="${a}"/>
      <rect x="12" y="34" width="86" height="11" fill="${a}" opacity=".85"/>
      <rect x="10" y="32" width="86" height="11" fill="#fff"/>
      <rect x="12" y="50" width="58" height="11" fill="${a}" opacity=".85"/>
      <rect x="10" y="48" width="58" height="11" fill="#fff"/>`,
    medallion: `<rect width="160" height="90" fill="#1b1e25"/>
      <circle cx="116" cy="45" r="33" fill="${photo}" stroke="${a}" stroke-width="3"/>
      <rect x="12" y="26" width="30" height="3" fill="${a}"/>
      <rect x="12" y="36" width="62" height="8" fill="${ink}"/>
      <rect x="12" y="48" width="48" height="8" fill="${ink}"/>
      <rect x="12" y="63" width="20" height="3" fill="${a}"/>`,
    diagonal: `<rect width="160" height="90" fill="#0f1116"/>
      <path d="M74 0H160V90H100Z" fill="${photo}"/>
      <path d="M70 0h6l26 90h-6z" fill="${a}"/>
      <rect x="10" y="24" width="28" height="3" fill="${a}"/>
      <rect x="10" y="34" width="50" height="10" fill="${ink}"/>
      <rect x="10" y="48" width="38" height="10" fill="${ink}"/>`,
    sticker: `<rect width="160" height="90" fill="#1b0f3a"/>
      ${[0, 1, 2, 3, 4].map((r) => [0, 1, 2, 3, 4, 5].map((c) => `<rect
        x="${c * 28 + (r % 2 ? 6 : -8)}" y="${r * 19 + 3}" width="8" height="6" rx="2"
        fill="${c % 2 ? a : ink}" opacity=".24"/>`).join('')).join('')}
      <path d="M86 0h74v90H86z" fill="${photo}" opacity=".9"/>
      <rect x="10" y="12" width="34" height="11" rx="5" fill="${a}"/>
      ${[32, 48, 64].map((y) => `<rect x="7" y="${y - 3}" width="${y === 64 ? 52 : 70}"
        height="18" fill="${a}"/>
        <rect x="10" y="${y}" width="${y === 64 ? 46 : 64}" height="12" fill="#fff"/>`).join('')}`,
    duotone: `<rect width="160" height="90" fill="${a}"/>
      <rect width="160" height="52" fill="#e8663f"/>
      <path d="M0 34l30-14 26 12 30-18 32 16 42-10v34H0z" fill="#c0245a" opacity=".7"/>
      <rect y="52" width="160" height="38" fill="#180a12"/>
      <rect y="50" width="160" height="3" fill="${a}"/>
      <rect x="10" y="8" width="38" height="12" fill="${a}"/>
      <rect x="10" y="60" width="130" height="10" fill="${ink}"/>
      <rect x="10" y="74" width="86" height="10" fill="${ink}"/>`,
    gloss: `<rect width="160" height="90" fill="#f6dce6"/>
      <ellipse cx="112" cy="45" rx="52" ry="44" fill="#fdeef4"/>
      <circle cx="112" cy="45" r="33" fill="${photo}" opacity=".85"/>
      <circle cx="112" cy="45" r="35" fill="none" stroke="${a}" stroke-width="2"/>
      <rect x="12" y="22" width="26" height="4" fill="${a}"/>
      <rect x="12" y="34" width="58" height="10" fill="#3a2a31"/>
      <rect x="12" y="48" width="46" height="10" fill="#3a2a31"/>
      <rect x="12" y="66" width="24" height="2.6" fill="${a}"/>`,
    scoreline: `<rect width="160" height="90" fill="${photo}"/>
      <path d="M0 24l160-18v54L0 78z" fill="#0d1c2e" opacity=".95"/>
      <path d="M0 22l160-18v4L0 26z" fill="${a}"/>
      <path d="M0 60l160-18v4L0 64z" fill="${a}"/>
      <g transform="rotate(-6.5 80 45)">
        <rect x="26" y="16" width="40" height="9" fill="${a}"/>
        <rect x="26" y="32" width="104" height="12" fill="#fff"/>
        <rect x="26" y="48" width="72" height="12" fill="#fff"/></g>`,
    tiles: `<rect width="160" height="90" fill="#1a1c22"/>
      <rect x="90" width="70" height="90" fill="${photo}"/>
      ${[0, 1, 2, 3].map((r) => [0, 1, 2].map((c) => `<rect x="${c * 30 + 1}"
        y="${r * 23 + 1}" width="28" height="21"
        fill="${(r + c) % 2 ? '#2b3340' : '#232a34'}"/>`).join('')).join('')}
      <rect x="8" y="24" width="76" height="42" rx="3" fill="#0f1116"
        stroke="${a}" stroke-width="1.8"/>
      <rect x="28" y="31" width="36" height="4" fill="${a}"/>
      <rect x="16" y="40" width="60" height="9" fill="${ink}"/>
      <rect x="26" y="52" width="40" height="9" fill="${ink}"/>`,
    poster: `<rect width="160" height="90" fill="#eee9de"/>
      <rect x="8" y="7" width="144" height="40" fill="${photo}"/>
      <rect x="8" y="7" width="144" height="40" fill="none" stroke="#26231f" stroke-width="1"/>
      <rect x="56" y="54" width="48" height="3" fill="#26231f" opacity=".5"/>
      <rect x="30" y="62" width="100" height="10" fill="#26231f"/>
      <rect x="44" y="80" width="28" height="1.6" fill="${a}"/>
      <rect x="88" y="80" width="28" height="1.6" fill="${a}"/>
      <path d="M80 77l4 3.8-4 3.8-4-3.8z" fill="${a}"/>`,
  }[key] || '<rect width="160" height="90" fill="#14151a"/>';
  return `<svg class="tpl-art thumb-art" viewBox="0 0 160 90" preserveAspectRatio="none">${svg}</svg>`;
}

let thumbTimer = null;
let thumbPending = {};

async function paintThumb() {
  const p = state.project;
  const t = p.thumb || {};
  const styles = state.thumbStyles || [];
  const meta = styles.find((s) => s.key === t.template) || styles[0] || {};
  const src = t.image ? `/api/projects/${p.id}/file/${t.image}?v=${t.rendered_at || 0}` : '';
  const credit = t.credit || {};

  $('#tabbody').innerHTML = `
    <div class="thumb-wrap">
      <div>
        <div class="thumb-stage">
          ${t.rendered_at
            ? `<img id="thumbimg" src="/api/projects/${p.id}/file/thumb/thumb.jpg?v=${t.rendered_at}">`
            : `<div class="empty-note" id="thumbimg">Cooking up a thumbnail…</div>`}
        </div>
        <div class="row" style="margin-top:10px">
          <span class="mono" id="thumbsize" style="color:var(--ink-faint)">1280×720</span>
          <div class="spacer"></div>
          ${t.image ? `<button class="btn sm ghost" onclick="thumbFocal()">
            ${(t.focal || []).length === 2 ? '✛ focus set' : 'set focus point'}</button>` : ''}
          <a class="btn sm primary" download="thumbnail.jpg"
             href="/api/projects/${p.id}/file/thumb/thumb.jpg?v=${t.rendered_at || 0}">download</a>
        </div>
        <div class="mono thumb-credit">
          ${t.image
            ? `${esc(credit.provider || 'local')}${credit.author ? ' · ' + esc(credit.author) : ''}
               ${credit.source_page ? `· <a href="${esc(credit.source_page)}" target="_blank">source</a>` : ''}
               <br>${esc((credit.license || '').slice(0, 80))}`
            : 'No picture yet — pick one below and it appears here.'}
        </div>
      </div>

      <div>
        <div class="row" style="margin-bottom:10px">
          <strong>Picture</strong>
          <div class="spacer"></div>
          <button class="btn sm" onclick="openThumbPicker()">choose a picture…</button>
          <label class="btn sm ghost" style="cursor:pointer">upload
            <input type="file" accept="image/*" hidden onchange="uploadThumbImage(this.files[0])"></label>
        </div>

        <label class="field"><span>Headline — a few words, not the title again</span>
          <textarea id="thumbhead" rows="2" placeholder="${esc((p.title || p.idea || '').slice(0, 50))}"
            oninput="saveThumb({headline:this.value})">${esc(t.headline || '')}</textarea></label>
        <div class="row" style="margin:-6px 0 14px">
          <input type="text" id="thumbkick" style="flex:1" placeholder="kicker — optional, one or two words"
            value="${esc(t.kicker || '')}" oninput="saveThumb({kicker:this.value})">
          <button class="btn sm" onclick="suggestHeadlines()">write me some</button>
        </div>
        <div id="thumbopts"></div>

        <div class="tpl-strip">
          ${styles.map((s) => `
            <div class="tpl ${s.key === t.template ? 'sel' : ''}"
                 onclick="saveThumb({template:'${s.key}'}, true)">
              ${thumbArt(s.key, t.accent || p.style.accent)}
              <div class="tpl-name">${esc(s.label)}</div>
            </div>`).join('')}
        </div>
        <div class="mono" style="color:var(--ink-faint);margin:-8px 0 16px">
          ${esc(meta.blurb || '')}</div>

        <div class="grid-2">
          <label class="field"><span>Text size — <b>${(t.text_scale || 1).toFixed(2)}×</b></span>
            <input type="range" min="0.7" max="1.35" step="0.05" value="${t.text_scale || 1}"
              onchange="saveThumb({text_scale:+this.value}, true)"></label>
          <label class="field"><span>Picture knocked back — <b>${Math.round((t.dim ?? 0.55) * 100)}%</b></span>
            <input type="range" min="0" max="0.95" step="0.05" value="${t.dim ?? 0.55}"
              onchange="saveThumb({dim:+this.value}, true)"></label>
        </div>
        <div class="row" style="gap:16px;margin-bottom:14px">
          <label class="row" style="gap:7px;cursor:pointer">
            <input type="checkbox" style="width:auto" ${t.uppercase ? 'checked' : ''}
              onchange="saveThumb({uppercase:this.checked}, true)"><span>Set in capitals</span></label>
          ${meta.flip ? `<label class="row" style="gap:7px;cursor:pointer">
            <input type="checkbox" style="width:auto" ${t.flip ? 'checked' : ''}
              onchange="saveThumb({flip:this.checked}, true)"><span>Mirror the layout</span></label>` : ''}
          <div class="spacer"></div>
          <label class="row" style="gap:7px">
            <span class="mono" style="color:var(--ink-faint)">accent</span>
            <input type="text" style="width:110px" value="${esc(t.accent || p.style.accent)}"
              onchange="saveThumb({accent:this.value}, true)"></label>
        </div>
      </div>
    </div>`;

  if (!t.rendered_at) renderThumb();
}

function saveThumb(patch, repaint = false) {
  const p = state.project;
  Object.assign(p.thumb, patch);
  Object.assign(thumbPending, patch);
  if (repaint) paintThumb();
  clearTimeout(thumbTimer);
  thumbTimer = setTimeout(async () => {
    const body = thumbPending;
    thumbPending = {};
    try {
      const r = await api(`/api/projects/${p.id}`,
        { method: 'PATCH', body: JSON.stringify({ thumb: body }) });
      p.thumb = r.thumb;
      await renderThumb();
    } catch (e) { toast(e.message, true); }
  }, 300);
}

async function renderThumb() {
  const p = state.project;
  try {
    const r = await api(`/api/projects/${p.id}/thumb/render`, { method: 'POST' });
    p.thumb = r.thumb;
    const stage = $('.thumb-stage');
    if (!stage) return;
    const url = `/api/projects/${p.id}/file/${r.path}?v=${r.rendered_at}`;
    stage.innerHTML = `<img id="thumbimg" src="${url}">`;
    const size = $('#thumbsize');
    if (size) size.textContent = `1280×720 · ${Math.round(r.bytes / 1024)} KB`;
    const dl = $('a[download="thumbnail.jpg"]');
    if (dl) dl.href = url;
  } catch (e) { toast(e.message, true); }
}

function thumbFocal() {
  const p = state.project, t = p.thumb;
  if (!t.image) return;
  openFocal(`/api/projects/${p.id}/file/${t.image}`, t.focal, (focal) => {
    saveThumb({ focal }, true);
  });
}

async function uploadThumbImage(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await api(`/api/projects/${state.project.id}/thumb/upload`, { method: 'POST', body: fd });
    state.project.thumb = r.thumb;
    paintThumb();
    toast('picture set');
  } catch (e) { toast(e.message, true); }
}

async function suggestHeadlines() {
  const r = await api(`/api/projects/${state.project.id}/thumb/headlines`, { method: 'POST' });
  watchJob(r.job, 'headlines', (done) => {
    const options = ((done && done.result) || {}).options || [];
    const box = $('#thumbopts');
    if (!box || !options.length) return;
    box.innerHTML = `<div class="head-opts">
      ${options.map((o, i) => `<button class="head-opt" onclick="useHeadline(${i})">
          ${o.kicker ? `<span class="mono">${esc(o.kicker)}</span>` : ''}
          <strong>${esc(o.headline)}</strong></button>`).join('')}
    </div>`;
    state.headlines = options;
  });
}

function useHeadline(i) {
  const o = (state.headlines || [])[i];
  if (!o) return;
  saveThumb({ headline: o.headline, kicker: o.kicker || '' }, true);
}

// Every picture in the project, plus the archives, in one panel.
function openThumbPicker() {
  const p = state.project;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  const mine = [];
  p.slides.forEach((s, i) => {
    const c = s.candidates.find((x) => x.id === s.chosen_id);
    if (c && c.kind !== 'video') mine.push({ ...c, _slide: i + 1 });
  });
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>Choose the thumbnail picture</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="tpdone">done</button>
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="tpq" style="flex:1;min-width:220px"
          placeholder="search the archives for something better…"
          value="${esc(p.title || p.idea || '')}">
        <button class="btn sm primary" id="tpgo">search</button>
      </div>
      <div class="mono" id="tpnote" style="color:var(--ink-faint);margin-bottom:10px"></div>
      <div class="pick-grid" id="tpres"></div>
    </div>`;
  document.body.appendChild(wrap);

  const q = wrap.querySelector('#tpq');
  const go = wrap.querySelector('#tpgo');
  const note = wrap.querySelector('#tpnote');
  const res = wrap.querySelector('#tpres');
  let shown = [];

  const paint = (list, label) => {
    shown = list;
    note.textContent = label;
    res.innerHTML = list.map((c, i) => `
      <div class="pick" data-i="${i}" title="${esc(c.title)}">
        <img src="${thumbUrl(c)}" loading="lazy" onerror="this.parentNode.style.opacity=.25">
        <div class="pick-meta">
          <span>${esc(c._slide ? 'slide ' + c._slide : c.provider)}</span>
          <span>${c.width || '?'}×${c.height || '?'}</span>
        </div>
      </div>`).join('') || '<div class="empty-note">nothing to show yet — go fish</div>';
    res.querySelectorAll('.pick').forEach((el) => {
      el.onclick = async () => {
        el.classList.add('sel');
        note.textContent = 'fetching the full-size picture…';
        try {
          const r = await api(`/api/projects/${p.id}/thumb/pick`,
            { method: 'POST', body: JSON.stringify({ candidate: shown[+el.dataset.i] }) });
          p.thumb = r.thumb;
          close();
          toast('picture set');
        } catch (e) { toast(e.message, true); note.textContent = 'that one could not be fetched'; }
      };
    });
  };

  const run = async () => {
    const query = q.value.trim();
    if (!query) return q.focus();
    go.disabled = q.disabled = true;
    note.textContent = `searching for “${query}”…`;
    res.innerHTML = '';
    try {
      const r = await api(`/api/projects/${p.id}/thumb/search`,
        { method: 'POST', body: JSON.stringify({ query }) });
      paint(r.results || [], `${(r.results || []).length} from the archives`);
    } catch (e) { toast(e.message, true); note.textContent = e.message || 'that search failed'; }
    go.disabled = q.disabled = false;
  };

  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const close = () => { document.removeEventListener('keydown', onKey); wrap.remove(); paintThumb(); };
  document.addEventListener('keydown', onKey);
  wrap.querySelector('#tpdone').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  go.onclick = run;
  q.onkeydown = (e) => { if (e.key === 'Enter') run(); };

  paint(mine, mine.length
    ? `${mine.length} already in this video — or search for something else`
    : 'this video has no pictures yet; search the archives');
}

// ------------------------------------------------------------------ record
function paintRecord() {
  const p = state.project;
  const i = Math.min(state.rec.index, p.slides.length - 1);
  state.rec.index = i;
  const s = p.slides[i];
  if (!s) { $('#tabbody').innerHTML = '<div class="empty-note">Nothing to read yet — write a script first.</div>'; return; }
  const ai = (p.narrator || {}).mode === 'ai';
  // The voice being worked on here — the microphone, or the AI engine picked
  // below. Its reads are kept apart from every other voice's, and the video
  // uses whichever one is chosen in the voice bar, which need not be this one.
  const track = ai ? narratorEngine(p) : 'mic';
  const tk = (x) => (x.takes || {})[track];
  const done = p.slides.filter(tk).length;
  const take = tk(s);

  $('#tabbody').innerHTML = `
    <div class="progress-track"><i style="width:${done / p.slides.length * 100}%"></i></div>
    <div class="row mono" style="color:var(--ink-faint);font-size:12.5px">
      <span>${done} of ${p.slides.length} ${ai ? 'read' : 'recorded'} ·
        ${fmtTime(p.recorded_seconds)} in the can</span>
      <div class="spacer"></div>
      <span>paragraph ${i + 1}</span>
    </div>

    ${voiceBar(p, track)}

    <div class="row" style="margin:14px 0 0;gap:6px">
      <button class="btn sm ${ai ? 'ghost' : 'primary'}"
        onclick="setNarrator({mode:'mic'})">read it yourself</button>
      <button class="btn sm ${ai ? 'primary' : 'ghost'}"
        onclick="setNarrator({mode:'ai'})">AI voice</button>
      <span class="mono" style="color:var(--ink-faint)">${ai
        ? (narratorEngine(p) === 'kokoro'
            ? 'A model on this machine reads the script. Nothing leaves the computer.'
            : `${esc(engineInfo(narratorEngine(p)).label || 'A voice service')} reads the script, billed to your account.`)
        : 'You read it into a microphone.'}</span>
    </div>

    ${ai ? aiVoicePanel(p, s) : ''}

    ${ai || micAvailable() ? '' : `
      <div class="panel warn-panel" style="margin-top:14px">
        <strong>This browser will not open a microphone here.</strong>
        <div class="mono" style="margin-top:6px;color:var(--ink-dim)">
          A microphone is only handed to a page on <b>https</b> or on
          <b>localhost</b>, and this page is
          <b>${esc(location.protocol.replace(':', ''))}://${esc(location.hostname)}</b>.
          Everything else on this tab works; only recording is blocked.
        </div>
        <div class="mono" style="margin-top:10px;color:var(--ink-faint)">
          Restart the server with <b>HOST=0.0.0.0 HTTPS=1 ./run.sh</b> and open the
          https address it prints (accept the certificate warning once), or tunnel
          the port so this machine sees it as localhost:<br>
          <b>ssh -N -L 8420:localhost:8420 you@the-mac</b>
        </div>
      </div>`}

    <div class="prompter" style="margin-top:14px"><p>${esc(s.narration)}</p></div>

    ${ai ? '' : `
    <div class="row" style="margin:12px 0 -4px">
      <button class="btn sm" onclick="openMicPanel()"
        ${micAvailable() ? '' : 'disabled'}>mic &amp; voice…</button>
      <span class="mono" style="color:var(--ink-faint)">${esc(voiceSummary())}</span>
    </div>`}

    ${ai ? `
    <div class="rec-bar">
      <button class="btn primary" onclick="voiceOneSlide()">read this paragraph</button>
      ${take ? `<span class="pill on"><span class="dot"></span>${take.duration.toFixed(1)}s${
        take.synthetic ? ` · ${esc(voiceLabel(take.voice))}` : ' · your voice'}</span>` : ''}
    </div>` : `
    <div class="rec-bar">
      <button class="btn rec ${state.rec.recording ? 'armed' : ''}" id="recbtn"
        ${micAvailable() ? '' : 'disabled'} onclick="toggleRec()">
        ${state.rec.recording ? '■ Stop' : '● Record'}</button>
      <span class="timer ${state.rec.recording ? 'live' : ''}" id="timer">0:00</span>
      <div class="level"><i id="level"></i></div>
      ${take ? `<span class="pill on"><span class="dot"></span>${take.duration.toFixed(1)}s</span>` : ''}
      ${!state.rec.stream && micAvailable()
        ? `<button class="btn sm ghost" onclick="openMic()">check the microphone</button>` : ''}
      ${state.mic.report && state.mic.report.analysis.ok
        ? `<span class="pill ${state.mic.report.analysis.room_score >= 50 ? 'on' : 'warn'}"
             title="measured in the mic panel">room: ${esc(state.mic.report.analysis.verdict)}</span>` : ''}
    </div>`}

    <div class="rec-nav">
      <button class="btn sm" onclick="jumpTake(-1)" ${i === 0 ? 'disabled' : ''}>← previous</button>
      <button class="btn sm" onclick="jumpTake(1)" ${i >= p.slides.length - 1 ? 'disabled' : ''}>next →</button>
      ${take ? `<button class="btn sm ghost" onclick="playTake()">play back</button>
                  <button class="btn sm ghost danger" onclick="dropTake()">discard take</button>` : ''}
      <div class="spacer"></div>
      ${done && !ai ? `<button class="btn sm ghost" onclick="recleanTakes()"
        title="run every take through the current voice chain again, from the raw recording"
        >re-clean all takes</button>` : ''}
      <button class="btn sm ghost" onclick="jumpNextUnrecorded()">jump to next blank</button>
    </div>
    ${ai ? '' : `
    <div class="row" style="margin-top:12px;color:var(--ink-faint);font-size:12.5px">
      <kbd>space</kbd> record / stop &nbsp; <kbd>→</kbd> next &nbsp; <kbd>←</kbd> back &nbsp;
      <kbd>p</kbd> play back &nbsp; <kbd>r</kbd> discard
    </div>`}

    <div class="take-map">
      ${p.slides.map((x, n) => `<span class="${tk(x) ? 'done' : ''} ${n === i ? 'cur' : ''}"
        title="${n + 1}" onclick="state.rec.index=${n};paintRecord()"></span>`).join('')}
    </div>
    <audio id="player" style="display:none"></audio>`;

  if (ai) {
    watchSayDraft();
    // The channel's entries apply too, and are only shown as a count here.
    if (p.channel_id && state.channelLexicon === undefined) {
      state.channelLexicon = [];
      api(`/api/channels/${p.channel_id}`).then((c) => {
        state.channelLexicon = c.lexicon || [];
        if (state.tab === 'record') paintRecord();
      }).catch(() => {});
    }
  }

  // If this browser has already been given permission, the device labels are
  // readable now and the picker can appear before the first take.
  if (state.rec.mics === undefined && micAvailable()) {
    state.rec.mics = [];
    listMics().then((mics) => {
      if (mics.some((m) => m.label)) {
        state.rec.mics = mics;
        if (!state.rec.recording && state.tab === 'record') paintRecord();
      }
    });
  }
}

// ------------------------------------------------------------- the AI reader
// Loaded once: whether the local model is installed, and the voices it offers.
function showCommand(platform) {
  const cmdText = $('code#cmd-text');
  const noteEl = $('#cmd-note');
  if (!cmdText) return;

  cmdText.textContent = 'pip install kokoro-onnx soundfile';

  let note = '';
  if (platform === 'windows') {
    note = 'Run in PowerShell or Command Prompt. If using the Youslop desktop app, run this in your system terminal (not within the app).';
  } else {
    note = 'Run in your terminal (bash, zsh, etc.). If using the Youslop desktop app, run this in your system terminal (not within the app).';
  }

  if (noteEl && note) {
    noteEl.textContent = note;
    noteEl.style.display = 'block';
  }
}

function copyInstallCommand() {
  const cmdText = $('code#cmd-text');
  if (!cmdText) return;
  const text = cmdText.textContent;
  navigator.clipboard.writeText(text).then(() => {
    toast('Copied to clipboard');
  }).catch(() => {
    toast('Failed to copy', true);
  });
}

async function loadTTS() {
  if (state.tts) return state.tts;
  state.tts = await api('/api/tts').catch(() => ({ ready: false, voices: [],
    detail: 'Could not reach the voice engine.' }));
  return state.tts;
}

function voiceLabel(id) {
  const lists = [((state.tts || {}).voices || []),
    ...Object.values(state.cloudVoices || {}).filter(Array.isArray)];
  for (const list of lists) {
    const v = list.find((x) => x.id === id);
    if (v) return v.label;
  }
  return id || 'a voice';
}

const narratorEngine = (p) => ((p || state.project).narrator || {}).engine || 'kokoro';
const engineInfo = (key) => (((state.tts || {}).engines) || []).find((e) => e.key === key) || {};

// Which model reads it: this machine, or a hosted voice service. A row of
// switches above the panel for whichever one is chosen.
function aiVoicePanel(p, slide) {
  const t = state.tts;
  if (!t) { loadTTS().then(() => { if (state.tab === 'record') paintRecord(); });
            return '<div class="panel" style="margin-top:14px">Checking the voice engine…</div>'; }
  const engine = narratorEngine(p);
  const engines = t.engines || [{ key: 'kokoro', label: 'On this computer', ready: t.ready }];
  const tabs = `<div class="row" style="margin:14px 0 0;gap:6px;flex-wrap:wrap">
    ${engines.map((e) => `<button class="btn sm ${e.key === engine ? 'primary' : 'ghost'}"
        onclick="setNarrator({engine:'${e.key}'})"
        title="${esc(e.blurb || '')}">${esc(e.label)}${e.ready ? '' : ' · not set up'}</button>`).join('')}
  </div>`;
  return tabs + (engine === 'kokoro' ? localVoicePanel(p, slide)
                                      : cloudVoicePanel(p, engineInfo(engine)));
}

// How far each take is from what the narrator is set to now: read in another
// engine, voice, pace or model means it needs reading again.
function staleTakes(p) {
  const n = p.narrator || {};
  const engine = narratorEngine(p);
  const e = engineInfo(engine);
  const model = engine === 'kokoro' ? '' : (n.model || ((e.models || [])[0] || {}).id || '');
  const lo = (e.speed || [0.5, 1.5])[0], hi = (e.speed || [0.5, 1.5])[1];
  const speed = Math.min(hi, Math.max(lo, n.speed));
  return p.slides.filter((x) => {
    // Only this engine's own reads: another voice's are kept, not stale.
    const tk = (x.takes || {})[engine] || {};
    if (!tk.synthetic) return false;
    return tk.voice !== n.voice
      || Math.abs((tk.speed || 1) - speed) > 0.011 || (tk.model || '') !== model;
  }).length;
}

function cloudVoicePanel(p, e) {
  if (!e.ready) {
    return `<div class="panel warn-panel" style="margin-top:14px">
      <strong>${esc(e.label)} isn't set up yet.</strong>
      <div class="mono" style="margin-top:6px;color:var(--ink-dim)">${esc(e.blurb || '')}</div>
      <div class="row" style="margin-top:10px">
        <a class="btn sm primary" href="#/settings">add your ${esc(e.label)} API key in Settings</a>
        <span class="mono" style="color:var(--ink-faint)">it works as soon as it's saved — no restart</span>
      </div>
    </div>`;
  }
  state.cloudVoices = state.cloudVoices || {};
  const list = state.cloudVoices[e.key];
  if (list === undefined) {
    state.cloudVoices[e.key] = null;
    api(`/api/tts/voices/${e.key}`)
      .then((v) => { state.cloudVoices[e.key] = v; })
      .catch((err) => { state.cloudVoices[e.key] = { error: err.message }; })
      .then(() => { if (state.tab === 'record') paintRecord(); });
  }
  if (!list) return `<div class="panel" style="margin-top:14px">Fetching ${esc(e.label)} voices…</div>`;
  if (list.error) {
    return `<div class="panel warn-panel" style="margin-top:14px">
      <strong>Couldn't list the ${esc(e.label)} voices.</strong>
      <div class="mono" style="margin-top:6px;user-select:text">${esc(list.error)}</div>
      <button class="btn sm" style="margin-top:10px"
        onclick="state.cloudVoices['${e.key}']=undefined;paintRecord()">try again</button>
    </div>`;
  }
  const n = p.narrator || {};
  const read = p.slides.filter((x) => (x.takes || {})[narratorEngine(p)]).length;
  const stale = staleTakes(p);
  const chars = p.slides.reduce((a, x) => a + (x.narration || '').trim().length, 0);
  const groups = {};
  list.forEach((v) => { (groups[v.accent || 'Voices'] = groups[v.accent || 'Voices'] || []).push(v); });
  const [lo, hi] = e.speed || [0.7, 1.2];
  const speed = Math.min(hi, Math.max(lo, n.speed));
  const known = list.some((v) => v.id === n.voice);

  return `<div class="panel" style="margin-top:14px">
    <div class="row" style="margin-bottom:10px">
      <strong>The voice</strong>
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">${read} of ${p.slides.length} read${
        stale ? ` · ${stale} in another voice or setting` : ''}</span>
    </div>
    ${known ? '' : `<div class="mono" style="color:var(--ink-faint);margin-bottom:8px">
      Reading as <b>${esc(n.voice)}</b>, which isn't in this account's list — pick one below.</div>`}
    ${e.key === 'elevenlabs' ? `
      <div class="row" style="gap:10px;margin-bottom:10px">
        <button class="btn sm" onclick="openVoiceLibrary()">browse the ElevenLabs voice library…</button>
        <span class="mono" style="color:var(--ink-faint)">the thousands of voices on their
          website — hear any of them, then add one to your account to read with</span>
      </div>` : ''}
    <div style="max-height:420px;overflow:auto">
    ${Object.entries(groups).map(([group, vs]) => `
      <div class="mono" style="color:var(--ink-faint);margin:8px 0 6px">${esc(group)}</div>
      <div class="voice-grid">
        ${vs.map((v) => `
          <div class="voice-card ${v.id === n.voice ? 'sel' : ''}"
               onclick="setNarrator({voice:'${esc(v.id)}'})">
            <div class="row" style="gap:6px">
              <strong>${esc(v.label)}</strong>
              <div class="spacer"></div>
              <button class="btn xs ghost" onclick="event.stopPropagation();hearVoice('${esc(v.id)}')"
                >hear</button>
            </div>
            <div class="mono voice-note">${esc(v.note || v.sex || '')}</div>
          </div>`).join('')}
      </div>`).join('')}
    </div>

    <div class="grid-2" style="margin-top:14px">
      <label class="field"><span>Model</span>
        <select onchange="setNarrator({model:this.value})">
          ${(e.models || []).map((m, i) => `<option value="${esc(m.id)}"
            ${(n.model || (e.models[0] || {}).id) === m.id ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}
        </select></label>
      <label class="field"><span>Pace — <b>${speed.toFixed(2)}×</b></span>
        <input type="range" min="${lo}" max="${hi}" step="0.01" value="${speed}"
          onchange="setNarrator({speed:+this.value})"></label>
    </div>

    <div class="row" style="margin-top:12px">
      <button class="btn primary" onclick="voiceWholeScript()">
        ${read ? (stale ? `re-read ${stale} paragraph${stale === 1 ? '' : 's'}`
                        : 'read anything still blank') : 'read the whole script'}</button>
      ${read ? `<button class="btn sm ghost" onclick="voiceWholeScript(true)"
        title="re-read every paragraph, including ones already done">read it all again</button>` : ''}
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">the whole script is
        ${chars.toLocaleString()} characters, billed to your ${esc(e.label)} account</span>
    </div>
    <audio id="voiceplayer" style="display:none"></audio>
  </div>

  ${pronunciationPanel(p)}`;
}

// ElevenLabs' shared Voice Library, searched from here. A library voice has to
// be added to the account before the API will read with it, so "use" adds it
// and then picks it — the same thing "Add to my voices" does on their site.
function openVoiceLibrary() {
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box" style="width:min(980px,100%)">
      <div class="row" style="margin-bottom:12px">
        <strong>ElevenLabs voice library</strong>
        <span class="mono" style="color:var(--ink-faint)">English voices, most popular first</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="vlclose">close</button>
      </div>
      <div class="row" style="gap:8px;margin-bottom:12px;flex-wrap:wrap">
        <input type="text" id="vlq" placeholder="deep, documentary, british, calm…" style="flex:1;min-width:200px">
        <select id="vlgender"><option value="">any voice</option><option value="male">male</option>
          <option value="female">female</option><option value="neutral">neutral</option></select>
        <select id="vluse"><option value="narrative_story">Narration &amp; story</option></select>
        <input type="text" id="vlaccent" placeholder="accent (american, british…)" style="width:190px">
        <button class="btn sm primary" id="vlgo">search</button>
      </div>
      <div id="vlresults" class="voice-grid" style="max-height:60vh;overflow:auto">
        <div class="empty-note" style="grid-column:1/-1">Looking…</div>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="btn sm ghost" id="vlmore" style="display:none">more</button>
        <div class="spacer"></div>
        <span class="mono" style="color:var(--ink-faint)">Adding a voice uses one of your
          ElevenLabs plan's custom voice slots, as it does on their site.</span>
      </div>
      <audio id="vlplayer" style="display:none"></audio>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { const el = wrap.querySelector('#vlplayer'); if (el) el.pause(); wrap.remove(); };
  wrap.querySelector('#vlclose').onclick = close;
  wrap.addEventListener('click', (ev) => { if (ev.target === wrap) close(); });
  const results = wrap.querySelector('#vlresults');
  const more = wrap.querySelector('#vlmore');
  let page = 0;
  let found = [];

  const card = (v, n) => `
    <div class="voice-card">
      <div class="row" style="gap:6px">
        <strong>${esc(v.label)}</strong>
        <div class="spacer"></div>
        ${v.preview_url ? `<button class="btn xs ghost" data-hear="${n}">hear</button>` : ''}
        <button class="btn xs" data-use="${n}">use</button>
      </div>
      <div class="mono voice-note">${esc([v.sex, v.age, v.accent, v.use_case].filter(Boolean).join(' · '))}</div>
      ${v.note ? `<div class="mono voice-note" style="margin-top:4px">${esc(v.note)}</div>` : ''}
    </div>`;

  const run = async (append) => {
    if (!append) { page = 0; found = []; results.innerHTML = '<div class="empty-note" style="grid-column:1/-1">Looking…</div>'; }
    const q = new URLSearchParams({
      q: wrap.querySelector('#vlq').value, gender: wrap.querySelector('#vlgender').value,
      use_case: wrap.querySelector('#vluse').value, accent: wrap.querySelector('#vlaccent').value,
      page: String(page) });
    try {
      const r = await api(`/api/tts/library?${q}`);
      const sel = wrap.querySelector('#vluse');
      if (sel.options.length < 2 && r.use_cases) {
        const cur = sel.value;
        sel.innerHTML = r.use_cases.map((u) => `<option value="${esc(u.id)}"
          ${u.id === cur ? 'selected' : ''}>${esc(u.label)}</option>`).join('');
      }
      found = found.concat(r.voices);
      results.innerHTML = found.length ? found.map(card).join('')
        : '<div class="empty-note" style="grid-column:1/-1">Nothing matched. Try fewer words.</div>';
      more.style.display = r.has_more ? '' : 'none';
    } catch (err) {
      results.innerHTML = `<div class="empty-note" style="grid-column:1/-1;user-select:text">${esc(err.message)}</div>`;
    }
  };
  results.addEventListener('click', async (ev) => {
    const hear = ev.target.closest('[data-hear]');
    const use = ev.target.closest('[data-use]');
    if (hear) {
      const el = wrap.querySelector('#vlplayer');
      el.src = found[+hear.dataset.hear].preview_url;
      el.play().catch(() => toast('Could not play that preview.', true));
    } else if (use) {
      const v = found[+use.dataset.use];
      use.disabled = true; use.textContent = 'adding…';
      try {
        const r = await api('/api/tts/library/add', { method: 'POST',
          body: JSON.stringify({ owner: v.owner, id: v.id, name: v.label }) });
        state.cloudVoices.elevenlabs = undefined;     // the account's list changed
        close();
        await setNarrator({ voice: r.voice_id });
        toast(`${v.label} added to your ElevenLabs voices and picked`);
      } catch (err) { toast(err.message, true); use.disabled = false; use.textContent = 'use'; }
    }
  });
  wrap.querySelector('#vlgo').onclick = () => run(false);
  wrap.querySelector('#vlq').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') run(false); });
  more.onclick = () => { page += 1; run(true); };
  run(false);
}

function localVoicePanel(p, slide) {
  const t = state.tts;
  if (!t.ready) {
    const isMissing = t.detail && t.detail.includes('missing');
    let setupGuide = '';
    if (t.detail && t.detail.includes('pip install')) {
      setupGuide = `
        <div style="margin-top:10px">
          <strong style="font-size:13px">Installation:</strong>
          <div style="margin-top:6px;font-size:12px;color:var(--ink-faint)">Copy the command for your system:</div>
          <div class="row" style="margin-top:8px;gap:6px;flex-wrap:wrap">
            <label style="flex:1;min-width:160px">
              <input type="radio" name="platform" value="linux-mac" checked onchange="showCommand(this.value)">
              Linux / macOS
            </label>
            <label style="flex:1;min-width:160px">
              <input type="radio" name="platform" value="windows" onchange="showCommand(this.value)">
              Windows (PowerShell)
            </label>
          </div>
          <div id="install-cmd" style="margin-top:8px;background:#1a1a1a;border:1px solid var(--line);border-radius:4px;padding:8px;position:relative">
            <code style="color:#4af626;font-size:12px;font-family:monospace;display:block;overflow-x:auto;padding-right:50px" id="cmd-text">pip install kokoro-onnx soundfile</code>
            <button class="btn xs ghost" onclick="copyInstallCommand()" style="position:absolute;top:4px;right:4px">copy</button>
          </div>
          <div id="cmd-note" style="margin-top:6px;font-size:12px;color:var(--ink-faint);display:none"></div>
          <script>showCommand('linux-mac')</script>
        </div>
      `;
    } else if (isMissing) {
      // The folder is the per-user data folder in a packaged app, not the
      // source checkout's assets/tts, so it is spelled out rather than left
      // to the README.
      const dir = t.model_path.replace(/[\\/][^\\/]+$/, '');
      const base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0';
      const q = (s) => `"${s}"`;
      // In PowerShell `curl` is Invoke-WebRequest and `mkdir -p` is not a
      // thing; curl.exe ships with Windows 10 and later.
      const win = t.model_path.includes('\\');
      const cmd = [
        win ? `New-Item -ItemType Directory -Force -Path ${q(dir)}` : `mkdir -p ${q(dir)}`,
        `${win ? 'curl.exe' : 'curl'} -L -o ${q(t.model_path)} ${base}/kokoro-v1.0.onnx`,
        `${win ? 'curl.exe' : 'curl'} -L -o ${q(t.voices_path)} ${base}/voices-v1.0.bin`,
      ].join('\n');
      setupGuide = `
        <div style="margin-top:10px;font-size:12px;color:var(--ink-faint)">
          Two model files (~337MB) need to be downloaded into
          <code class="mono" style="user-select:all">${esc(dir)}</code>
        </div>
        <div style="margin-top:8px;background:#1a1a1a;border:1px solid var(--line);border-radius:4px;padding:8px;position:relative">
          <pre style="margin:0;color:#4af626;font-size:12px;font-family:monospace;overflow-x:auto;padding-right:50px" id="weights-cmd">${esc(cmd)}</pre>
          <button class="btn xs ghost" style="position:absolute;top:4px;right:4px"
            onclick="navigator.clipboard.writeText($('#weights-cmd').textContent).then(() => toast('Copied to clipboard'), () => toast('Failed to copy', true))">copy</button>
        </div>
        <div style="margin-top:6px;font-size:12px;color:var(--ink-faint)">Run in a terminal, then restart Youslop.</div>`;
    } else if (t.detail) {
      setupGuide = `<div style="margin-top:10px;font-size:12px;color:var(--ink-faint);user-select:text">${esc(t.detail)}</div>`;
    }
    return `<div class="panel warn-panel" style="margin-top:14px">
      <strong>The local voice model is not ready.</strong>
      ${setupGuide}
    </div>`;
  }
  const n = p.narrator || {};
  const read = p.slides.filter((x) => (x.takes || {})[narratorEngine(p)]).length;
  const stale = staleTakes(p);
  const byAccent = {};
  t.voices.forEach((v) => { (byAccent[v.accent] = byAccent[v.accent] || []).push(v); });

  return `<div class="panel" style="margin-top:14px">
    <div class="row" style="margin-bottom:10px">
      <strong>The voice</strong>
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">${read} of ${p.slides.length} read${
        stale ? ` · ${stale} in an older voice` : ''}</span>
    </div>
    ${Object.entries(byAccent).map(([accent, list]) => `
      <div class="mono" style="color:var(--ink-faint);margin:8px 0 6px">${esc(accent)}</div>
      <div class="voice-grid">
        ${list.map((v) => `
          <div class="voice-card ${v.id === n.voice ? 'sel' : ''}"
               onclick="setNarrator({voice:'${v.id}'})">
            <div class="row" style="gap:6px">
              <strong>${esc(v.label)}</strong>
              <div class="spacer"></div>
              <button class="btn xs ghost" onclick="event.stopPropagation();hearVoice('${v.id}')"
                >hear</button>
            </div>
            <div class="mono voice-note">${esc(v.note)}</div>
          </div>`).join('')}
      </div>`).join('')}

    <label class="field" style="margin:14px 0 4px"><span>Pace — <b>${
      n.speed.toFixed(2)}×</b>${n.speed === 1 ? ' (the model\'s own)' : ''}</span>
      <input type="range" min="0.7" max="1.3" step="0.01" value="${n.speed}"
        onchange="setNarrator({speed:+this.value})"></label>

    <div class="row" style="margin-top:12px">
      <button class="btn primary" onclick="voiceWholeScript()">
        ${read ? (stale ? `re-read ${stale} paragraph${stale === 1 ? '' : 's'}`
                        : 'read anything still blank') : 'read the whole script'}</button>
      ${read ? `<button class="btn sm ghost" onclick="voiceWholeScript(true)"
        title="re-read every paragraph, including ones already done">read it all again</button>` : ''}
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">about ${
        Math.max(1, Math.round(p.slides.length * 3.5 / 60))} min to synthesise</span>
    </div>
    <audio id="voiceplayer" style="display:none"></audio>
  </div>

  ${pronunciationPanel(p)}`;
}

// ------------------------------------------------------- pronunciation guide
// espeak is good at English and unreliable at names: "Elon" reads as ih-LON.
// An entry fixes one name; the whole value is in being able to hear the
// difference before it is baked into twenty minutes of narration.
function pronunciationPanel(p) {
  const lex = p.lexicon || [];
  const chanCount = (state.channelLexicon || []).length;
  return `<div class="panel" style="margin-top:14px">
    <div class="row" style="margin-bottom:4px">
      <strong>How to say things</strong>
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">${lex.length} in this video${
        chanCount ? ` · ${chanCount} from the channel` : ''}</span>
    </div>
    <div class="mono" style="color:var(--ink-faint);margin-bottom:12px">
      Write the respelling in syllables and put the stressed one in CAPITALS —
      <b>ELL-on</b>, <b>rod-REE-gess</b>. Hear it before and after; the guide
      applies to every paragraph when the script is read.
      ${narratorEngine(p) === 'kokoro' ? '' : `<br>${esc(engineInfo(narratorEngine(p)).label)}
        reads words, not phonemes, so it is handed the respelling as a word
        (<b>ELL-on</b> → <b>Ellon</b>). Each “hear” is a small billed request.`}
    </div>

    ${lex.length ? `<div class="say-list">
      ${lex.map((e, n) => `
        <div class="say-row">
          <input type="text" value="${esc(e.term)}" placeholder="in the script"
            onchange="editSay(${n},'term',this.value)">
          <input type="text" value="${esc(e.respell)}" placeholder="ELL-on"
            onchange="editSay(${n},'respell',this.value)">
          <span class="mono say-ipa" title="the phonemes actually used">${esc(e.ipa)}</span>
          <button class="btn xs ghost" onclick="hearSay(${n})">hear</button>
          <button class="btn xs ghost danger" onclick="dropSay(${n})">×</button>
        </div>`).join('')}
    </div>` : ''}

    <div class="say-row" style="margin-top:10px">
      <input type="text" id="sayterm" placeholder="word in the script — e.g. Elon"
        onkeydown="if(event.key==='Enter')addSay()">
      <input type="text" id="sayrespell" placeholder="say it — e.g. ELL-on"
        onkeydown="if(event.key==='Enter')addSay()">
      <span class="mono say-ipa" id="saypreview"></span>
      <button class="btn xs ghost" onclick="hearSayDraft()">hear</button>
      <button class="btn xs" onclick="addSay()">add</button>
    </div>
    <div class="mono" id="saycompare" style="color:var(--ink-faint);margin-top:8px"></div>
    <audio id="sayplayer" style="display:none"></audio>
  </div>`;
}

const sayVoice = () => (state.project.narrator || {}).voice || 'bm_george';

async function saveLexicon(next) {
  try {
    state.project = await api(`/api/projects/${state.project.id}`,
      { method: 'PATCH', body: JSON.stringify({ lexicon: next }) });
    paintRecord();
  } catch (e) { toast(e.message, true); }
}

function editSay(n, field, value) {
  const next = (state.project.lexicon || []).map((e) => ({ ...e }));
  if (!next[n]) return;
  next[n][field] = value.trim();
  // A new respelling replaces the phonemes it resolved to last time.
  if (field === 'respell') next[n].ipa = '';
  saveLexicon(next);
}

function dropSay(n) {
  const next = (state.project.lexicon || []).filter((_, i) => i !== n);
  saveLexicon(next);
}

async function addSay() {
  const term = document.getElementById('sayterm').value.trim();
  const respell = document.getElementById('sayrespell').value.trim();
  if (!term) return toast('Which word?', true);
  if (!respell) return toast('How should it be said? Try ELL-on.', true);
  await saveLexicon([...(state.project.lexicon || []), { term, respell }]);
}

// The before/after, which is the whole point: you cannot correct a
// pronunciation you cannot compare with the one you are getting.
async function saySample(text, respell, ipa) {
  const el = document.getElementById('sayplayer');
  if (!el || !text) return;
  try {
    const r = await fetch(`/api/tts/say-preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, respell: respell || '', ipa: ipa || '',
                             voice: sayVoice(), engine: narratorEngine(),
                             model: (state.project.narrator || {}).model || '' }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'could not say that');
    el.src = URL.createObjectURL(await r.blob());
    el.play().catch(() => {});
  } catch (e) { toast(e.message, true); }
}

function hearSay(n) {
  const e = (state.project.lexicon || [])[n];
  if (e) saySample(e.term, e.respell, e.ipa);
}

function hearSayDraft() {
  saySample(document.getElementById('sayterm').value.trim(),
            document.getElementById('sayrespell').value.trim(), '');
}

// Live, as the respelling is typed: what the model says now, and what this
// entry would make it say. Debounced because each one is an espeak call.
function watchSayDraft() {
  const term = document.getElementById('sayterm');
  const respell = document.getElementById('sayrespell');
  if (!term || !respell || term.dataset.wired) return;
  term.dataset.wired = respell.dataset.wired = '1';
  const run = async () => {
    const t = term.value.trim();
    const out = document.getElementById('saypreview');
    const cmp = document.getElementById('saycompare');
    // The phoneme comparison is the local model's; a hosted voice has none.
    if (!t || narratorEngine() !== 'kokoro') { out.textContent = ''; cmp.textContent = ''; return; }
    try {
      const j = await api(`/api/tts/say?text=${encodeURIComponent(t)}`
        + `&respell=${encodeURIComponent(respell.value.trim())}`
        + `&voice=${sayVoice()}`);
      out.textContent = j.proposed || '';
      cmp.innerHTML = j.proposed
        ? (j.changes
            ? `reads as <b>${esc(j.current)}</b> → would read as <b>${esc(j.proposed)}</b>`
            : `that is already how it reads (<b>${esc(j.current)}</b>) — no entry needed`)
        : `reads as <b>${esc(j.current)}</b>`;
    } catch (e) { out.textContent = ''; }
  };
  let t = null;
  const kick = () => { clearTimeout(t); t = setTimeout(run, 260); };
  term.addEventListener('input', kick);
  respell.addEventListener('input', kick);
}

async function setNarrator(patch) {
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ narrator: patch }) });
  paintRecord();
}

function hearVoice(id) {
  const el = document.getElementById('voiceplayer');
  if (!el) return;
  const engine = narratorEngine();
  const model = (state.project.narrator || {}).model || '';
  el.src = engine === 'kokoro' ? `/api/tts/preview/${id}`
    : `/api/tts/preview/${encodeURIComponent(id)}?engine=${engine}&model=${encodeURIComponent(model)}`;
  el.play().catch(() => toast('Could not play that sample.', true));
}

async function voiceWholeScript(redo) {
  const p = state.project;
  if (redo && !confirm(`Read every paragraph again in ${trackLabel(narratorEngine(p))}, `
      + 'replacing the reads already made in that voice? Your other voices are not touched.')) return;
  if (narratorEngine(p) !== 'kokoro') {
    // A hosted voice is billed by the character: say how many first.
    let est;
    try {
      est = await api(`/api/projects/${p.id}/voice-over`,
        { method: 'POST', body: JSON.stringify({ redo: !!redo, dry_run: true }) });
    } catch (e) { return toast(e.message, true); }
    if (!est.paragraphs) return toast('Everything is already read in this voice.');
    const label = engineInfo(narratorEngine(p)).label || 'the voice service';
    if (!confirm(`Send ${est.paragraphs} paragraph${est.paragraphs === 1 ? '' : 's'} `
      + `(${est.characters.toLocaleString()} characters) to ${label}? `
      + 'It is billed to your account.')) return;
  }
  const r = await api(`/api/projects/${p.id}/voice-over`,
    { method: 'POST', body: JSON.stringify({ redo: !!redo }) });
  watchJob(r.job, 'voice-over');
  paintRecord();
}

async function voiceOneSlide() {
  const p = state.project;
  const s = p.slides[state.rec.index];
  try {
    const r = await api(`/api/projects/${p.id}/slides/${s.id}/voice-over`, { method: 'POST' });
    p.slides[state.rec.index] = r.slide;
    p.recorded_seconds = r.recorded_seconds;
    syncVoiceCounts();
    paintRecord();
    playTake();
  } catch (e) { toast(e.message, true); }
}

function jumpTake(delta) {
  if (state.rec.recording) return;
  const n = state.rec.index + delta;
  if (n < 0 || n >= state.project.slides.length) return;
  state.rec.index = n;
  paintRecord();
}

function jumpNextUnrecorded() {
  const p = state.project;
  const next = p.slides.findIndex((s, n) => n > state.rec.index && !s.take);
  state.rec.index = next >= 0 ? next : p.slides.findIndex((s) => !s.take);
  if (state.rec.index < 0) { state.rec.index = 0; toast('everything is recorded'); }
  paintRecord();
}

// Browsers only expose a microphone to a secure origin — https, or localhost.
// Over plain http to a LAN address `navigator.mediaDevices` is simply not there,
// so this is checked before anything tries to use it.
function micAvailable() {
  return !!(window.isSecureContext && navigator.mediaDevices
            && navigator.mediaDevices.getUserMedia);
}

async function listMics() {
  if (!micAvailable()) return [];
  try {
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'audioinput');
  } catch { return []; }
}

async function ensureMic() {
  if (state.rec.stream) return state.rec.stream;
  if (!micAvailable()) {
    throw new Error('this browser will not open a microphone over an insecure connection');
  }
  const wanted = localStorage.getItem('vb_mic') || '';
  // Raw signal by default: the ffmpeg voice chain does the same work with far
  // better control, and the browser's version is tuned for a call. Automatic
  // gain never comes on — it rides the level mid-sentence, and every take here
  // is loudness-matched afterwards anyway.
  const clean = !!voiceOf().browser_cleanup;
  const audio = {
    echoCancellation: clean, noiseSuppression: clean, autoGainControl: false,
    channelCount: 1, sampleRate: 48000,
  };
  if (wanted) audio.deviceId = { exact: wanted };
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio });
  } catch (e) {
    if (!wanted) throw e;
    // The remembered mic is not on this machine: fall back to the default one.
    localStorage.removeItem('vb_mic');
    delete audio.deviceId;
    stream = await navigator.mediaDevices.getUserMedia({ audio });
  }
  state.rec.stream = stream;
  // Labels are blank until permission is granted, so the picker is filled in
  // once a stream exists rather than on first paint.
  listMics().then((mics) => {
    state.rec.mics = mics;
    // Never mid-take: a repaint would replace the timer and level elements.
    if (!state.rec.recording && state.tab === 'record') paintRecord();
    if (state.mic.el) micRefresh();
  });
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  state.rec.ctx = ctx;
  state.rec.analyser = analyser;
  meter();
  return stream;
}

function meter() {
  const buf = new Uint8Array(state.rec.analyser.fftSize);
  let hold = 0, heldAt = 0;
  const loop = () => {
    if (!state.rec.analyser) return;
    state.rec.analyser.getByteTimeDomainData(buf);
    let peak = 0, sum = 0;
    for (const v of buf) {
      const x = (v - 128) / 128;
      sum += x * x;
      peak = Math.max(peak, Math.abs(x));
    }
    const rms = Math.sqrt(sum / buf.length);
    const now = performance.now();
    if (peak >= hold || now - heldAt > 1100) { hold = peak; heldAt = now; }
    const el = document.getElementById('level');
    if (el) {
      el.style.width = Math.min(100, peak * 145) + '%';
      el.style.background = peak > 0.92 ? 'var(--bad)' : peak > 0.06 ? 'var(--good)' : '#3a4152';
    }
    micMeter(rms, peak, hold);
    requestAnimationFrame(loop);
  };
  loop();
}

// The panel's meter is the same numbers on a dBFS scale, because "somewhere
// near the middle" is not a gain setting anyone can repeat tomorrow.
const dbOf = (x) => (x > 0.00001 ? 20 * Math.log10(x) : -80);
const meterPos = (db) => Math.max(0, Math.min(100, (db + 60) / 60 * 100));

function micMeter(rms, peak, hold) {
  const bar = document.getElementById('micbar');
  if (!bar) return;
  const db = dbOf(rms), pk = dbOf(peak);
  bar.style.width = meterPos(db) + '%';
  bar.style.background = pk > -1.5 ? 'var(--bad)' : db > -12 ? '#d9a05e' : 'var(--good)';
  const mark = document.getElementById('michold');
  if (mark) mark.style.left = meterPos(dbOf(hold)) + '%';
  const read = document.getElementById('micdb');
  if (read) read.textContent = `${db.toFixed(0)} dB rms · peak ${pk.toFixed(0)} dB`;
  const say = document.getElementById('micsay');
  if (say && !state.mic.counting) {
    // Judged on speech, not on the silence between sentences.
    const word = pk > -1.5 ? 'clipping — turn the gain down'
      : db > -10 ? 'hot — back off a little'
      : db > -26 ? 'good level'
      : db > -45 ? 'quiet — closer to the mic, or more gain'
      : 'nothing coming in';
    say.textContent = word;
    say.style.color = pk > -1.5 ? 'var(--bad)' : db > -26 ? 'var(--good)' : 'var(--ink-faint)';
  }
}

async function openMic() {
  try {
    await ensureMic();
    paintRecord();
    toast('Microphone open — say something and watch the level.');
  } catch (e) { toast('Microphone blocked: ' + e.message, true); }
}

async function chooseMic(deviceId) {
  localStorage.setItem('vb_mic', deviceId || '');
  const wasIndex = state.rec.index;
  stopStream();
  try {
    await ensureMic();
    const mic = (state.rec.mics || []).find((m) => m.deviceId === deviceId);
    toast(mic ? `recording from ${mic.label}` : 'using the default microphone');
  } catch (e) { toast('Microphone blocked: ' + e.message, true); }
  state.rec.index = wasIndex;
  paintRecord();
  if (state.mic.el) micRefresh();
}

function stopStream() {
  const r = state.rec;
  if (r.recorder && r.recording) { try { r.recorder.stop(); } catch {} }
  r.recording = false;
  clearInterval(r.tick);
  if (r.stream) r.stream.getTracks().forEach((t) => t.stop());
  if (r.ctx) r.ctx.close();
  r.stream = null; r.ctx = null; r.analyser = null; r.recorder = null;
}

async function toggleRec() {
  const r = state.rec;
  if (r.recording) { r.recorder.stop(); return; }
  let stream;
  try { stream = await ensureMic(); }
  catch (e) { return toast('Microphone blocked: ' + e.message, true); }

  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    .find((t) => MediaRecorder.isTypeSupported(t)) || '';
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 128000 } : {});
  r.chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) r.chunks.push(e.data); };
  rec.onstop = () => uploadTake(new Blob(r.chunks, { type: mime || 'audio/webm' }));
  rec.start();
  r.recorder = rec;
  r.recording = true;
  r.t0 = Date.now();
  clearInterval(r.tick);
  r.tick = setInterval(() => {
    const el = document.getElementById('timer');
    if (el) el.textContent = fmtTime((Date.now() - r.t0) / 1000);
  }, 200);
  paintRecord();
}

async function uploadTake(blob) {
  const r = state.rec;
  r.recording = false;
  clearInterval(r.tick);
  const slide = state.project.slides[r.index];
  paintRecord();
  const fd = new FormData();
  fd.append('file', blob, 'take.webm');
  try {
    const res = await api(`/api/projects/${state.project.id}/slides/${slide.id}/take`,
      { method: 'POST', body: fd });
    Object.assign(slide, res.slide);
    syncVoiceCounts();
    state.project.recorded_seconds = res.recorded_seconds;
    toast(`take saved · ${res.slide.takes.mic.duration.toFixed(1)}s`);
    if (r.index < state.project.slides.length - 1) r.index += 1;
    paintRecord();
  } catch (e) { toast(e.message, true); paintRecord(); }
}

// The voice the record tab is working in: the mic, or the AI engine.
function recTrack() {
  const p = state.project;
  return (p.narrator || {}).mode === 'ai' ? narratorEngine(p) : 'mic';
}

function playTake(track) {
  track = track || recTrack();
  const slide = state.project.slides[state.rec.index];
  if (!(slide.takes || {})[track]) return;
  const el = document.getElementById('player');
  el.src = `/api/projects/${state.project.id}/slides/${slide.id}/take.wav`
    + `?track=${encodeURIComponent(track)}&cb=${Date.now()}`;
  el.play();
}

// Counts the server would send, worked out here after a single-take change
// rather than reloading the project.
function syncVoiceCounts() {
  const p = state.project;
  const counts = {};
  for (const s of p.slides) for (const k of Object.keys(s.takes || {})) counts[k] = (counts[k] || 0) + 1;
  p.voice_tracks = counts;
  if (!p.voice_track) {
    const first = Object.keys(counts)[0];
    if (first) p.voice_track = first;
  }
  for (const s of p.slides) s.take = (s.takes || {})[p.voice_track] || null;
  p.recorded_count = p.slides.filter((s) => s.take).length;
}

const TRACK_ORDER = ['mic', 'kokoro', 'elevenlabs', 'openai'];
const trackLabel = (t) => ({ mic: 'Your mic', kokoro: 'Local voice',
  elevenlabs: 'ElevenLabs', openai: 'OpenAI' })[t] || t;

// Which voice the whole video uses, and every voice there are reads in. Each
// voice's reads are kept side by side, so trying one never loses another;
// the video uses exactly one, chosen here.
function voiceBar(p, working) {
  const counts = p.voice_tracks || {};
  const n = p.slides.length;
  const used = p.voice_track;
  const keys = TRACK_ORDER.filter((t) => counts[t] || t === working || t === used)
    .concat(Object.keys(counts).filter((t) => !TRACK_ORDER.includes(t)));
  const s = p.slides[state.rec.index] || {};
  const usedCount = counts[used] || 0;
  return `
    <div class="panel voice-bar" style="margin-top:14px;padding:12px 14px">
      <div class="row" style="gap:8px;margin-bottom:8px">
        <strong>Voice for this video</strong>
        <span class="mono" style="color:var(--ink-faint)">${used
          ? `${esc(trackLabel(used))} — what the render and the timeline use`
          : 'nothing read yet'}</span>
      </div>
      <div class="row" style="gap:8px;flex-wrap:wrap">
        ${keys.map((t) => {
          const c = counts[t] || 0;
          const here = !!(s.takes || {})[t];
          return `
            <div class="voice-chip ${t === used ? 'sel' : ''}">
              <b>${esc(trackLabel(t))}</b>
              <span class="mono">${c} of ${n}</span>
              ${here ? `<button class="btn sm ghost" title="paragraph ${state.rec.index + 1} in this voice"
                onclick="playTake('${t}')">▸ hear ¶${state.rec.index + 1}</button>` : ''}
              ${t === used
                ? '<span class="pill on">in use</span>'
                : `<button class="btn sm" ${c ? '' : 'disabled'}
                    onclick="useVoiceTrack('${t}')">use for the video</button>`}
            </div>`;
        }).join('')}
      </div>
      ${used && working !== used ? `
        <div class="mono" style="color:var(--ink-faint);margin-top:8px">
          You're working in ${esc(trackLabel(working))} here. The video still uses
          ${esc(trackLabel(used))}, and none of its reads are touched — switch above
          once you've heard enough.</div>` : ''}
      ${used && usedCount < n ? `
        <div class="mono" style="color:var(--warn, #e0a050);margin-top:8px">
          ${n - usedCount} paragraph${n - usedCount === 1 ? ' has' : 's have'} no read in
          ${esc(trackLabel(used))} yet and will be silent in the render.</div>` : ''}
    </div>`;
}

async function useVoiceTrack(track) {
  const p = state.project;
  const n = p.slides.length;
  const c = (p.voice_tracks || {})[track] || 0;
  if (c < n && !confirm(`Only ${c} of ${n} paragraphs are read in ${trackLabel(track)}. `
      + 'The rest will be silent until they are. Use it for the video anyway?\n\n'
      + 'Nothing is deleted — you can switch back at any time.')) return;
  try {
    state.project = await api(`/api/projects/${p.id}/voice-track`,
      { method: 'POST', body: JSON.stringify({ track }) });
    toast(`the video now uses ${trackLabel(track)}`);
    render();
  } catch (e) { toast(e.message, true); }
}

// The takes on disk were cleaned by whichever voice chain was current when they
// were recorded. This re-runs the current one over the raw recordings, so a
// change to the processing reaches a script that is already read.
async function recleanTakes() {
  const p = state.project;
  if (!confirm(`Clean all ${p.recorded_count} takes again from the raw recordings?`
             + '\nNothing is re-recorded; the takes are rebuilt.')) return;
  toast('cleaning takes…');
  try {
    const res = await api(`/api/projects/${p.id}/takes/reprocess`, { method: 'POST' });
    state.project = res.project;
    paintRecord();
    toast(res.failed.length
      ? `${res.reprocessed} cleaned · ${res.failed[0]}`
      : `${res.reprocessed} takes cleaned`, res.failed.length > 0);
  } catch (e) { toast(e.message, true); }
}

async function dropTake() {
  const slide = state.project.slides[state.rec.index];
  const res = await api(`/api/projects/${state.project.id}/slides/${slide.id}/take`
    + `?track=${encodeURIComponent(recTrack())}`, { method: 'DELETE' });
  Object.assign(slide, res.slide);
  syncVoiceCounts();
  paintRecord();
}

document.addEventListener('keydown', (e) => {
  if (state.tab !== 'record' || !state.project) return;
  if (state.mic.el) { if (e.key === 'Escape') closeMicPanel(); return; }
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  const keys = {
    ' ': () => toggleRec(),
    ArrowRight: () => jumpTake(1),
    ArrowLeft: () => jumpTake(-1),
    p: () => playTake(),
    r: () => dropTake(),
  };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
});

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

function voiceOf() { return (state.project && state.project.voice) || {}; }

function voiceSummary() {
  const v = voiceOf();
  const room = state.mic.report && state.mic.report.analysis;
  return `${v.preset || 'warm'} · de-room ${Math.round((v.de_room || 0) * 100)}%`
       + (room && room.ok ? ` · room: ${room.verdict}` : '');
}

// ------------------------------------------------------------------- panel
async function openMicPanel() {
  if (state.mic.el) return;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide mic-panel">
      <div class="row" style="margin-bottom:16px">
        <strong>Microphone &amp; voice</strong>
        <span class="mono" style="color:var(--ink-faint)">
          set it up once — every take on this video is cleaned the same way</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="micclose">done</button>
      </div>
      <div class="mic-cols">
        <div class="mic-col" id="micleft"></div>
        <div class="mic-col" id="micright"></div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  state.mic.el = wrap;
  wrap.querySelector('#micclose').onclick = closeMicPanel;
  wrap.onclick = (e) => { if (e.target === wrap) closeMicPanel(); };

  micRefresh();
  if (micAvailable()) {
    try { await ensureMic(); } catch (e) { toast('Microphone blocked: ' + e.message, true); }
    micRefresh();
  }
}

function closeMicPanel() {
  if (!state.mic.el) return;
  abStop();
  if (state.mic.rec) { try { state.mic.rec.stop(); } catch {} state.mic.rec = null; }
  clearInterval(state.mic.tick);
  state.mic.tick = null;
  state.mic.counting = 0;
  state.mic.el.remove();
  state.mic.el = null;
  paintRecord();
}

function micRefresh() {
  const wrap = state.mic.el;
  if (!wrap) return;
  paintMicDevice();
  paintMicVoice();
}

// ----------------------------------------------------------- left: the mic
function paintMicDevice() {
  const v = voiceOf();
  const mics = state.rec.mics || [];
  const picked = localStorage.getItem('vb_mic') || '';
  state.mic.el.querySelector('#micleft').innerHTML = `
    <div class="kicker">the microphone</div>

    <label class="field" style="margin-top:12px">
      <span>input device</span>
      <select id="micdev" onchange="chooseMic(this.value)"
        ${micAvailable() ? '' : 'disabled'}>
        <option value="">default input</option>
        ${mics.map((m) => `<option value="${esc(m.deviceId)}"
          ${m.deviceId === picked ? 'selected' : ''}
          >${esc(m.label || 'microphone')}</option>`).join('')}
      </select>
    </label>
    ${state.rec.stream || !micAvailable() ? '' : `
      <button class="btn sm" onclick="openMic().then(micRefresh)">open the microphone</button>`}

    <div class="meter-wrap">
      <div class="meter">
        <i id="micbar"></i>
        <b id="michold" ${state.rec.stream ? '' : 'hidden'}></b>
        <u class="meter-zone"></u>
      </div>
      <div class="meter-scale mono">
        <span>−60</span><span>−40</span><span>−24</span><span>−12</span><span>0 dBFS</span>
      </div>
      <div class="row" style="margin-top:6px">
        <span class="mono" id="micdb" style="color:var(--ink-faint)">—</span>
        <div class="spacer"></div>
        <span class="mono" id="micsay" style="color:var(--ink-faint)">
          ${state.rec.stream ? 'say a line at your reading volume' : 'microphone closed'}</span>
      </div>
    </div>

    <label class="row" style="margin:14px 0 4px;cursor:pointer">
      <input type="checkbox" style="width:auto" ${v.browser_cleanup ? 'checked' : ''}
        onchange="setBrowserCleanup(this.checked)">
      <span style="font-size:13px">let the browser clean the signal first</span>
    </label>
    <div class="mono hintline">
      Chrome's own denoiser is built for a call, not a read: it fights the chain
      on the right and smears the top of the voice. Worth trying only if the room
      is genuinely bad.
    </div>

    <div class="row" style="margin-top:18px">
      <button class="btn ${state.mic.report ? '' : 'primary'}" id="mictest"
        ${micAvailable() && !state.mic.counting && !state.mic.measuring ? '' : 'disabled'}
        onclick="micTestRecord()">
        ${state.mic.counting ? `recording… ${state.mic.counting}` :
          state.mic.measuring ? 'measuring…' :
          state.mic.report ? 'record another test' : '● record 8 seconds'}</button>
      <span class="mono" style="color:var(--ink-faint);flex:1;min-width:180px">
        read a couple of sentences the way you read a script</span>
    </div>

    <div id="micreport">${micReportHtml()}</div>`;
}

function micReportHtml() {
  const r = state.mic.report;
  if (!r) {
    return `<div class="mono hintline" style="margin-top:16px">
      Nothing measured yet. The test read tells you how far your voice gets
      clear of the room, which is the one thing no processing can fix later.
    </div>`;
  }
  const a = r.analysis;
  if (!a.ok) {
    return `<div class="panel warn-panel" style="margin-top:16px">
      ${a.notes.map((n) => `<div>${esc(n)}</div>`).join('')}</div>`;
  }
  const score = a.room_score;
  const tone = score >= 70 ? 'good' : score >= 50 ? 'ok' : score >= 30 ? 'warn' : 'bad';
  return `
    <div class="room-head">
      <div>
        <span class="room-verdict ${tone}">${esc(a.verdict)}</span>
        <span class="mono" style="color:var(--ink-faint)">
          — ${esc(VERDICT_BLURB[a.verdict] || '')}</span>
      </div>
    </div>
    <div class="room-bar ${tone}"><i style="width:${score}%"></i></div>
    <div class="room-nums mono">
      <span>voice <b>${a.speech_db} dB</b></span>
      <span>room tone <b>${a.room_db} dB</b></span>
      <span>peak <b>${a.peak_db} dB</b></span>
      <span title="how far your voice gets clear of its own reflections"
        >separation <b>${a.contrast} dB</b></span>
      <span title="how far the take falls in the 200ms after a word ends"
        >decay <b>${a.decay} dB</b></span>
    </div>
    ${a.notes.map((n) => `<div class="room-note mono">${esc(n)}</div>`).join('')}`;
}

async function setBrowserCleanup(on) {
  await saveVoice({ browser_cleanup: !!on }, false);
  stopStream();                       // the constraint only applies to a new stream
  try { await ensureMic(); } catch (e) { toast('Microphone blocked: ' + e.message, true); }
  micRefresh();
  if (state.mic.report) micPreview();
}

// --------------------------------------------------------- right: the voice
function paintMicVoice() {
  const v = voiceOf();
  const has = !!state.mic.report;
  state.mic.el.querySelector('#micright').innerHTML = `
    <div class="kicker">the voice</div>

    <div class="preset-row">
      ${Object.keys(PRESET_BLURB).map((k) => `
        <button class="chip ${v.preset === k ? 'sel' : ''}" onclick="saveVoice({preset:'${k}'})">
          ${k}<em>${esc(PRESET_BLURB[k])}</em></button>`).join('')}
      ${v.preset === 'custom' ? '<span class="chip sel static">custom</span>' : ''}
    </div>

    <div class="knobs" id="micknobs">
      ${VOICE_KNOBS.map((n) => `
        <label class="knob" title="${esc(n.hint)}">
          <span>${n.label}<b id="kv_${n.k}">${n.fmt(+v[n.k])}</b></span>
          <input type="range" min="${n.min}" max="${n.max}" step="${n.step}"
            value="${v[n.k]}" id="kn_${n.k}"
            oninput="micKnobLive('${n.k}', this.value)"
            onchange="saveVoice({${n.k}: +this.value})">
        </label>`).join('')}
    </div>

    <div class="ab-bar">
      <button class="btn sm ${state.mic.ab === 'raw' ? 'primary' : ''}"
        ${has ? '' : 'disabled'} onclick="abPlay('raw')">▶ before</button>
      <button class="btn sm ${state.mic.ab === 'wet' ? 'primary' : ''}"
        ${has ? '' : 'disabled'} onclick="abPlay('wet')">▶ after</button>
      <button class="btn sm ghost" ${has ? '' : 'disabled'} onclick="abStop()">stop</button>
      <span class="mono" id="abnote" style="color:var(--ink-faint);flex:1;min-width:150px">
        ${has ? (state.mic.busy ? 'rebuilding…' : 'switch while it plays — it stays in step')
              : 'record a test above to hear the chain'}</span>
    </div>

    <div class="row" style="margin-top:16px">
      <button class="btn sm ghost" onclick="saveVoiceToChannel()"
        ${state.project.channel_id ? '' : 'disabled'}
        title="every new video on this channel starts from these settings">
        make this the channel default</button>
      <button class="btn sm ghost" onclick="recleanTakes()"
        ${state.project.recorded_count ? '' : 'disabled'}
        title="run the takes already recorded through this chain again">
        re-clean ${state.project.recorded_count} take${state.project.recorded_count === 1 ? '' : 's'}</button>
    </div>
    <div class="mono hintline" style="margin-top:10px">
      Takes are cleaned as they are recorded. Change anything here after reading
      and the takes on disk keep the old chain until they are re-cleaned — the
      raw recordings are kept for exactly that.
    </div>`;
}

// Dragging a slider only moves its own label; the chain is rebuilt on release.
function micKnobLive(key, value) {
  const knob = VOICE_KNOBS.find((n) => n.k === key);
  const el = document.getElementById(`kv_${key}`);
  if (knob && el) el.textContent = knob.fmt(+value);
}

async function saveVoice(patch, preview = true) {
  state.project.voice = { ...voiceOf(), ...patch };   // so the UI answers at once
  if (preview && state.mic.report) return micPreview(patch);
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ voice: patch }) });
  micRefresh();
}

// Save the change and rebuild the test recording through it, in one trip.
let micPreviewTimer;
async function micPreview(patch) {
  clearTimeout(micPreviewTimer);
  state.mic.pending = { ...(state.mic.pending || {}), ...(patch || {}) };
  micPreviewTimer = setTimeout(async () => {
    const body = state.mic.pending || {};
    state.mic.pending = null;
    state.mic.busy = true;
    micRefresh();
    try {
      const r = await api(`/api/projects/${state.project.id}/voice/preview`,
        { method: 'POST', body: JSON.stringify({ voice: body }) });
      applyReport(r);
    } catch (e) { toast(e.message, true); }
    state.mic.busy = false;
    micRefresh();
    abReload();
  }, 260);
}

function applyReport(r) {
  state.mic.report = r;
  state.project.voice = r.voice;
  state.mic.trim = (r.take && r.take.trimmed && r.take.trimmed[0]) || 0;
}

async function saveVoiceToChannel() {
  const cid = state.project.channel_id;
  if (!cid) return;
  await api(`/api/channels/${cid}`,
    { method: 'PATCH', body: JSON.stringify({ voice: voiceOf() }) });
  toast('every new video on this channel starts here now');
}

// ------------------------------------------------------------ the test read
async function micTestRecord() {
  let stream;
  try { stream = await ensureMic(); }
  catch (e) { return toast('Microphone blocked: ' + e.message, true); }
  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    .find((t) => MediaRecorder.isTypeSupported(t)) || '';
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 128000 } : {});
  const chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    clearInterval(state.mic.tick);
    state.mic.counting = 0;
    state.mic.rec = null;
    if (!state.mic.el) return;          // the panel was closed mid-test
    state.mic.measuring = true;
    micRefresh();
    const fd = new FormData();
    fd.append('file', new Blob(chunks, { type: mime || 'audio/webm' }), 'mictest.webm');
    try {
      applyReport(await api(`/api/projects/${state.project.id}/voice/test`,
        { method: 'POST', body: fd }));
    } catch (e) { toast(e.message, true); }
    state.mic.measuring = false;
    micRefresh();
    abReload();
  };
  rec.start();
  state.mic.rec = rec;
  state.mic.counting = 8;
  micRefresh();
  clearInterval(state.mic.tick);
  state.mic.tick = setInterval(() => {
    state.mic.counting -= 1;
    if (state.mic.counting <= 0) { try { rec.stop(); } catch {} return; }
    micRefresh();
  }, 1000);
}

// ------------------------------------------------------------------- the A/B
function abEl(which) {
  let el = document.getElementById(`ab_${which}`);
  if (!el) {
    el = document.createElement('audio');
    el.id = `ab_${which}`;
    el.preload = 'auto';
    document.body.appendChild(el);
  }
  return el;
}

function abPlay(which) {
  const pid = state.project.id;
  const other = which === 'raw' ? 'wet' : 'raw';
  const from = abEl(other), to = abEl(which);
  // The cleaned file starts where the speech does; the raw one still has the
  // silence in front of it. Carrying that offset across is what makes the
  // switch land on the same word rather than half a second past it.
  const trim = state.mic.trim || 0;
  let at = from.currentTime && !from.paused
    ? from.currentTime + (which === 'raw' ? trim : -trim) : 0;
  from.pause();
  if (!to.src) {
    to.src = which === 'raw' ? `/api/projects/${pid}/voice/test.src`
                             : `/api/projects/${pid}/voice/test.wav?cb=${state.mic.report.stamp}`;
  }
  state.mic.ab = which;
  const start = () => { to.currentTime = Math.max(0, Math.min(at, to.duration || at)); to.play(); };
  if (to.readyState >= 1) start(); else to.addEventListener('loadedmetadata', start, { once: true });
  to.onended = () => { state.mic.ab = ''; micRefresh(); };
  micRefresh();
}

function abStop() {
  ['raw', 'wet'].forEach((w) => { const el = document.getElementById(`ab_${w}`); if (el) el.pause(); });
  state.mic.ab = '';
  micRefresh();
}

// After a rebuild the cleaned file is a different file at the same URL.
function abReload() {
  const el = document.getElementById('ab_wet');
  if (!el || !state.mic.report) return;
  const at = el.currentTime, playing = !el.paused;
  el.src = `/api/projects/${state.project.id}/voice/test.wav?cb=${state.mic.report.stamp}`;
  if (playing) el.addEventListener('loadedmetadata', () => {
    el.currentTime = Math.min(at, el.duration || at);
    el.play();
  }, { once: true });
}

// ------------------------------------------------------------------ render
async function paintRender() {
  const p = state.project;
  const st = p.style;
  const missingMedia = p.slides.filter((s) => !s.chosen_id).length;
  const missingTakes = p.slides.length - p.recorded_count;
  const music = await api('/api/music').catch(() => []);
  await ensureChannelsLoaded();          // the panel below files it in one
  // Only a standalone video picks its own slate and end card here; inside a
  // channel those live on the channel page and this page never draws them.
  if (!p.channel_id && !state.templates) {
    [state.templates, state.endTemplates] = await Promise.all([
      api('/api/intro/templates').catch(() => []),
      api('/api/outro/templates').catch(() => []),
    ]);
  }
  if (!state.youtubeCategories) {
    state.youtubeCategories = await api('/api/youtube/status')
      .then((r) => r.categories).catch(() => []);
  }

  $('#tabbody').innerHTML = `
    <div class="panel tl" id="tl"></div>
    <div class="grid-2">
      <div class="panel">
        <h3>Look</h3>
        <label class="field"><span>Video style</span></label>
        ${formatPicker(st.format || 'kenburns', st.accent, 'pickProjectFormat')}
        ${st.format === 'board' ? boardKnobs(st, 'saveStyle') : ''}
        ${isCut(st.format) ? cutKnobs(st, 'saveStyle') : ''}
        <label class="field"><span>Vignette — <b>${st.vignette.toFixed(2)}</b></span>
          <input type="range" min="0" max="0.8" step="0.02" value="${st.vignette}"
            onchange="saveStyle({vignette:+this.value})"></label>
        ${st.format === 'board' ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            The board cut draws every slide itself and ignores the drift, the
            grade and the chapter titles below. Write the boards on the
            pictures tab.</div>`
        : isCut(st.format) ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            This cut draws every frame itself, on hard cuts, and ignores the
            drift, crossfade, grade and chapter titles below. Write its cues
            on the pictures tab.</div>`
        : st.format === 'essay' ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            The essay cut sets the narration on screen in phrases and ignores the
            drift and the chapter titles below.</div>`
        : `<label class="field"><span>Ken Burns drift — <b>${st.ken_burns_amount.toFixed(2)}</b></span>
          <input type="range" min="0" max="0.24" step="0.01" value="${st.ken_burns_amount}"
            onchange="saveStyle({ken_burns:+this.value>0, ken_burns_amount:+this.value})"></label>`}
        <label class="field"><span>Crossfade — <b>${st.transition.toFixed(2)}s</b></span>
          <input type="range" min="0" max="1.6" step="0.05" value="${st.transition}"
            onchange="saveStyle({transition:+this.value})"></label>
        <label class="row" style="gap:8px;cursor:pointer;margin:-4px 0 14px">
          <input type="checkbox" ${st.chapter_cards !== false ? 'checked' : ''} style="width:auto"
            onchange="saveStyle({chapter_cards:this.checked})">
          <span>chapter cards${chapterCount(p) ? ` — ${chapterCount(p)} marked on the script tab` : ''}</span>
        </label>
        ${st.format === 'board' || isCut(st.format) || (st.format || '').startsWith('custom:') ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            This cut draws its own frames, so a chapter still opens a fresh
            slide and a longer pause, but no card is laid over it.</div>` : ''}
        <label class="field"><span>Grade</span>
          <select onchange="saveStyle({grade:this.value})">
            ${['warm', 'neutral', 'cool', 'mono'].map((g) =>
              `<option ${g === st.grade ? 'selected' : ''}>${g}</option>`).join('')}
          </select></label>
        <label class="field"><span>Title accent</span>
          <input type="text" value="${esc(st.accent)}" onchange="saveStyle({accent:this.value})"></label>
      </div>

      <div class="panel">
        <h3>Sound</h3>
        <label class="field"><span>Music bed</span>
          <select onchange="saveProject({music:this.value})">
            <option value="" ${!p.music ? 'selected' : ''}>— none —</option>
            <option value="__auto__" ${p.music === '__auto__' ? 'selected' : ''}>— pick one for me —</option>
            ${music.map((m) => `<option ${m.name === p.music ? 'selected' : ''}
              value="${esc(m.name)}">${esc(m.name)}</option>`).join('')}
          </select></label>
        <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
          ${!p.music
            ? 'No bed: the video plays on the narration alone.'
            : p.music === '__auto__'
              ? (music.length ? 'One of the tracks below, the same one on every re-render.'
                              : 'Nothing in assets/music to pick from yet.')
              : 'Looped if it is shorter than the video, and trimmed to length.'}</div>
        <div class="row" style="gap:10px;margin:0 0 14px">
          ${music.length === 0
            ? `<div class="pill warn">drop mp3s into assets/music to get a bed</div>` : ''}
          <button class="btn sm ghost" onclick="revealFile('music','','')">open the music folder</button>
          <span class="mono" style="color:var(--ink-faint)">add tracks, then reload this page to pick them</span>
        </div>
        <label class="field"><span>Music under voice — <b>${st.music_db.toFixed(0)} dB</b></span>
          <input type="range" min="-40" max="-14" step="1" value="${st.music_db}"
            onchange="saveStyle({music_db:+this.value})"></label>
        <label class="field"><span>Pause between paragraphs — <b>${(st.paragraph_gap ?? 0.42).toFixed(2)}s</b></span>
          <input type="range" min="0.15" max="1.2" step="0.01" value="${st.paragraph_gap ?? 0.42}"
            onchange="saveStyle({paragraph_gap:+this.value})"></label>
        <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
          The pause varies around this: about half of it when a paragraph runs on
          mid-sentence, twice it where a new section starts.</div>
        <div class="mono" style="color:var(--ink-faint)">
          Final mix is mastered to −14 LUFS, which is what YouTube wants.</div>
      </div>
    </div>

    ${openingPanel(p)}

    ${descriptionPanel(p)}

    ${presenterPanel(p)}

    <div class="panel" style="margin-top:18px">
      <div class="row">
        <button class="btn primary" onclick="doRender(false)"
          ${missingTakes === p.slides.length ? 'disabled' : ''}>Render the video</button>
        <button class="btn" onclick="doRender(true)">Preview cut (no voice)</button>
        <div class="spacer"></div>
        ${missingTakes ? `<span class="pill warn">${missingTakes} paragraph${missingTakes > 1 ? 's' : ''} unrecorded</span>` : ''}
        ${missingMedia ? `<span class="pill warn">${missingMedia} without a picture</span>` : ''}
      </div>
      <div class="mono" style="color:var(--ink-faint);margin-top:10px">
        ${missingTakes && missingTakes < p.slides.length
          ? 'Unrecorded paragraphs are skipped entirely in a full render.'
          : 'Preview uses estimated timings so you can check the picture edit before recording.'}
      </div>
    </div>

    ${p.render && p.render.output ? `
      <h2>Last render</h2>
      ${videoTag(`/api/projects/${p.id}/file/${p.render.output}`,
                 { scope: 'project', id: p.id, rel: p.render.output })}
      <div class="row" style="margin-top:12px">
        <span class="mono" style="color:var(--ink-faint)">
          ${fmtTime(p.render.duration)} · ${p.render.size_mb} MB · ${p.render.slides} slides
          ${p.render.preview ? '· preview' : ''}</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" title="show the file on disk"
          onclick="revealFile('project','${p.id}','${esc(encodeURIComponent(p.render.output))}')">
          open the folder</button>
        <a class="btn sm" href="/api/projects/${p.id}/download">download</a>
      </div>
      ${await uploadPanel(p)}` : ''}
  `;
  tlMount();
}

// How this video opens and closes. In a channel both come from the channel,
// which is most of what a channel is for, and this is only the switch for
// using them. Standalone, the video carries its own: the same slates and end
// cards, drawn from its own title, subtitle and colours, minus the ones that
// need a cast of portraits to fill.
// Where this video is filed. Moving it changes where its opening and close
// come from and which channel it uploads to; nothing about the script, the
// pictures or the recordings moves with it.
function channelPicker(p) {
  const chans = state.channels || [];
  return `
    <label class="row" style="gap:8px">
      <span class="mono" style="color:var(--ink-faint)">in</span>
      <select style="width:auto" onchange="saveOpening({channel_id:this.value})">
        <option value="" ${!p.channel_id ? 'selected' : ''}>— no channel —</option>
        ${chans.map((c) => `<option value="${c.id}" ${c.id === p.channel_id ? 'selected' : ''}>
          ${esc(c.name)}</option>`).join('')}
      </select>
    </label>`;
}

function openingPanel(p) {
  if (p.channel_id) {
    return `
      <div class="panel" id="opening-panel" style="margin-top:18px">
        <div class="row">
          <strong>Channel opening and close</strong>
          ${channelPicker(p)}
          <div class="spacer"></div>
          <label class="row" style="gap:8px;cursor:pointer">
            <input type="checkbox" ${p.use_intro ? 'checked' : ''} style="width:auto"
              onchange="saveProject({use_intro:this.checked})">
            <span>open with the channel slate</span>
          </label>
          <label class="row" style="gap:8px;cursor:pointer">
            <input type="checkbox" ${p.use_outro ? 'checked' : ''} style="width:auto"
              onchange="saveProject({use_outro:this.checked})">
            <span>close on the end screen</span>
          </label>
          <a class="btn sm ghost" href="#/c/${p.channel_id}">edit them</a>
        </div>
      </div>`;
  }

  const st = p.style;
  const intro = p.intro || {};
  const outro = p.outro || {};
  const slates = (state.templates || []).filter((t) => !t.needs_images);
  const ends = state.endTemplates || [];
  const openOn = !!intro.template;
  const firstSlate = (slates[0] || {}).key || 'signal';
  return `
    <div class="panel" id="opening-panel" style="margin-top:18px">
      <div class="row">
        <strong>Opening and close</strong>
        ${channelPicker(p)}
        <div class="spacer"></div>
        <label class="row" style="gap:8px;cursor:pointer">
          <input type="checkbox" ${openOn ? 'checked' : ''} style="width:auto"
            onchange="saveOpening({intro:{template:this.checked?'${esc(intro.template || firstSlate)}':''}})">
          <span>open on a title card</span>
        </label>
        <label class="row" style="gap:8px;cursor:pointer">
          <input type="checkbox" ${outro.enabled ? 'checked' : ''} style="width:auto"
            onchange="saveOpening({outro:{enabled:this.checked}})">
          <span>close on an end card</span>
        </label>
      </div>
      ${!openOn && !outro.enabled ? `
        <div class="mono" style="color:var(--ink-faint);margin-top:10px">
          A standalone video starts cold and ends on its last picture unless you
          turn these on. Put it in a channel instead and every video in the
          series opens the same way.</div>` : ''}

      ${openOn ? `
        <div class="row" style="margin:14px 0 8px">
          <span class="mono" style="color:var(--ink-faint);flex:1;min-width:0">
            The title card. Your video's title is the type on it; the subtitle is
            the line above. The slates that need a cast of faces belong to a
            channel and aren't offered here.</span>
          <button class="btn sm" onclick="previewOpening('intro')">preview it</button>
        </div>
        <div class="tpl-strip">
          ${slates.map((t) => `
            <div class="tpl ${t.key === intro.template ? 'sel' : ''}"
                 onclick="saveOpening({intro:{template:'${t.key}'}})">
              ${tplArt(t.key, st.accent)}
              <div class="tpl-name">${esc(t.label)}</div>
            </div>`).join('')}
        </div>
        <div class="grid-3">
          <label class="field"><span>On screen — <b>${(intro.duration || 5).toFixed(1)}s</b></span>
            <input type="range" min="2" max="12" step="0.5" value="${intro.duration || 5}"
              onchange="saveProject({intro:{duration:+this.value}})"></label>
          <label class="field"><span>Beat before the video — <b>${(intro.hold ?? 1).toFixed(1)}s</b></span>
            <input type="range" min="0" max="4" step="0.1" value="${intro.hold ?? 1}"
              onchange="saveProject({intro:{hold:+this.value}})"></label>
        </div>
        ${stingBlock('intro', intro)}` : ''}

      ${outro.enabled ? `
        <div class="row" style="margin:14px 0 8px">
          <span class="mono" style="color:var(--ink-faint);flex:1;min-width:0">
            The end card. The plates are empty on purpose — they are where you
            line up YouTube's own end-screen elements in Studio.</span>
          <button class="btn sm" onclick="previewOpening('outro')">preview it</button>
        </div>
        <div class="tpl-strip">
          ${ends.map((t) => `
            <div class="tpl ${t.key === outro.template ? 'sel' : ''}"
                 onclick="saveOpening({outro:{template:'${t.key}'}})">
              ${endArt(t.key, st.accent)}
              <div class="tpl-name">${esc(t.label)}</div>
            </div>`).join('')}
        </div>
        <div class="grid-3">
          <label class="field"><span>The line on it</span>
            <input type="text" value="${esc(outro.cta || '')}"
              placeholder="${esc((ends.find((t) => t.key === outro.template) || {}).cta || 'More like this')}"
              onchange="saveProject({outro:{cta:this.value}})"></label>
          <label class="field"><span>Your @handle</span>
            <input type="text" value="${esc(outro.handle || '')}" placeholder="@yourchannel"
              onchange="saveProject({outro:{handle:this.value}})"></label>
          <label class="field"><span>On screen — <b>${(outro.duration || 12).toFixed(0)}s</b></span>
            <input type="range" min="5" max="20" step="1" value="${outro.duration || 12}"
              onchange="saveProject({outro:{duration:+this.value}})"></label>
        </div>
        ${stingBlock('outro', outro)}` : ''}
    </div>`;
}

// A standalone video's own sting for its title card or its end card. The two
// specs name their fields differently (`music_*` on the slate, `sting_*` on
// the end card), so one table maps either onto the same controls.
const STING_FIELDS = {
  intro: { file: 'music', name: 'music_filename', db: 'music_db', start: 'music_start',
           fade: 'music_fade', dur: 'music_duration' },
  outro: { file: 'sting', name: 'sting_filename', db: 'sting_db', start: 'sting_start',
           fade: 'sting_fade', dur: 'sting_duration' },
};

function stingSpanOf(role, spec) {
  return role === 'intro' ? (spec.duration || 5) + (spec.music_tail || 0) : (spec.duration || 12);
}

function stingBlock(role, spec) {
  const f = STING_FIELDS[role];
  const p = state.project;
  const has = !!spec[f.file];
  const dur = spec[f.dur] || 0;
  const maxStart = Math.max(0, dur - 1);
  const start = Math.min(spec[f.start] || 0, maxStart);
  const span = stingSpanOf(role, spec);
  const label = role === 'intro' ? 'Opening sting' : 'End card sting';
  const hint = role === 'intro'
    ? 'Its own music for the title card. The music bed waits until the card is over.'
    : 'Plays as the end card comes up and runs while it is on screen.';
  const set = (k, v) => `saveProject({${role}:{${k}:${v}}})`;
  return `
    <div class="panel" style="background:#0f1116;margin:12px 0 4px">
      <div class="row" style="margin-bottom:${has ? '14px' : '0'}">
        <div style="flex:1;min-width:200px">
          <strong>${label}</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:4px">
            ${has ? esc(spec[f.name] || 'sting') : hint}</div>
        </div>
        ${has ? `
          <audio id="sting-${role}" controls style="max-width:280px"
            src="/api/projects/${p.id}/file/${spec[f.file]}?v=${dur}-${esc(spec[f.name] || '')}"></audio>
          <button class="btn sm ghost danger" onclick="removeProjectSting('${role}')">remove</button>`
        : `<label class="btn sm" style="cursor:pointer">choose a sting
             <input type="file" accept="audio/*" hidden
               onchange="uploadProjectSting('${role}', this.files[0])">
           </label>`}
      </div>
      ${has ? `
        <div class="row" style="gap:10px;margin-bottom:12px">
          <div class="mono" style="flex:1;min-width:200px;color:var(--ink-faint)">
            ${fmtTime(dur)} long — it takes ${span.toFixed(1)}s, ${fmtTime(start)} to
            ${fmtTime(start + span)}${start + span > dur + 0.05 ? '. That runs off the end of the track.' : '.'}</div>
          <button class="btn sm ghost" onclick="auditionProjectSting('${role}')">hear the window</button>
        </div>
        <label class="field" style="margin:0 0 12px"><span>Start it — <b>${fmtTime(start)}${
            start > 0 ? ' into the track' : ' — the very top'}</b></span>
          <input type="range" min="0" max="${maxStart.toFixed(1)}" step="0.1" value="${start.toFixed(1)}"
            oninput="scrubProjectSting('${role}', +this.value)"
            onchange="${set(f.start, '+this.value')}"></label>
        <div class="grid-3">
          <label class="field" style="margin:0"><span>Level vs the narration — <b>${(spec[f.db] ?? -4).toFixed(0)} dB</b></span>
            <input type="range" min="-20" max="4" step="1" value="${spec[f.db] ?? -4}"
              onchange="${set(f.db, '+this.value')}"></label>
          ${role === 'intro' ? `
            <label class="field" style="margin:0"><span>Rings on past the card — <b>${(spec.music_tail ?? 1.1).toFixed(1)}s</b></span>
              <input type="range" min="0" max="3" step="0.1" value="${spec.music_tail ?? 1.1}"
                onchange="saveProject({intro:{music_tail:+this.value}})"></label>` : '<div></div>'}
          <label class="field" style="margin:0"><span>Fade out — <b>${
              (spec[f.fade] ?? 1.35) < 0.1 ? 'straight cut' : (spec[f.fade] ?? 1.35).toFixed(1) + 's'}</b></span>
            <input type="range" min="0" max="${role === 'intro' ? 4 : 8}" step="0.1" value="${spec[f.fade] ?? 1.35}"
              onchange="${set(f.fade, '+this.value')}"></label>
        </div>` : ''}
    </div>`;
}

async function uploadProjectSting(role, file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    state.project = await api(`/api/projects/${state.project.id}/sting/${role}`,
      { method: 'POST', body: fd });
    toast('sting added');
    render();
  } catch (e) { toast(e.message, true); }
}

async function removeProjectSting(role) {
  try {
    state.project = await api(`/api/projects/${state.project.id}/sting/${role}`,
      { method: 'DELETE' });
    render();
  } catch (e) { toast(e.message, true); }
}

function scrubProjectSting(role, seconds) {
  const el = document.getElementById(`sting-${role}`);
  if (el) { try { el.currentTime = seconds; } catch (e) { /* not loaded yet */ } }
}

// Play exactly the stretch the card will use, and stop where it stops.
function auditionProjectSting(role) {
  const el = document.getElementById(`sting-${role}`);
  const spec = state.project && state.project[role];
  if (!el || !spec) return;
  const f = STING_FIELDS[role];
  clearTimeout(window._stingStop);
  const from = Math.min(spec[f.start] || 0, Math.max(0, (spec[f.dur] || 0) - 1));
  el.currentTime = from;
  el.play().catch(() => {});
  window._stingStop = setTimeout(() => { el.pause(); el.currentTime = from; },
                                 stingSpanOf(role, spec) * 1000);
}

// Saves that change which controls are on screen, so the tab is repainted.
async function saveOpening(patch) {
  await saveProject(patch);
  render();
}

// The card on its own, full size — a few seconds of frames, so there is
// nothing to gain from rendering it small the way a segment preview does.
async function previewOpening(kind) {
  const r = await api(`/api/projects/${state.project.id}/preview-opening`,
    { method: 'POST', body: JSON.stringify({ kind }) });
  watchJob(r.job, `${kind} preview`, (j) => {
    if (j.state !== 'done' || !j.result) return;
    const card = j.result;
    openVideoModal(
      `<strong>${card.kind === 'outro' ? 'End card' : 'Title card'}</strong>
       <span class="mono" style="color:var(--ink-faint)">${fmtTime(card.seconds)}</span>`,
      videoTag(`/api/projects/${state.project.id}/file/${card.path}?v=${card.rendered_at}`,
               { scope: 'project', id: state.project.id, rel: card.path },
               'controls autoplay playsinline'));
  });
  render();
}

// Publishing itself: connecting a channel to YouTube lives on the channel
// page (youtubePanel()); this is the per-video "send this render" half.
async function uploadPanel(p) {
  if (!p.channel_id) {
    return `<div class="panel" style="margin-top:18px">
      <div class="mono" style="color:var(--ink-faint)">
        This video isn't on a channel, so there's nowhere to publish it to —
        add it to a channel first, or download and upload it by hand.</div>
    </div>`;
  }
  const yt = p.youtube || {};
  if (!yt.connected) {
    return `<div class="panel" style="margin-top:18px">
      <div class="row">
        <div style="flex:1;min-width:200px">
          <strong>Publish to YouTube</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:4px">
            Connect this channel to YouTube to upload straight from here.</div>
        </div>
        <a class="btn sm" href="#/c/${p.channel_id}">connect it</a>
      </div>
    </div>`;
  }

  if (!state.upload || state.upload.pid !== p.id) {
    // The written description if there is one; the bare credits otherwise.
    let description = p.description || '';
    if (!description) {
      try { description = (await api(`/api/projects/${p.id}/credits`)).text || ''; }
      catch { /* the field just starts blank */ }
    }
    state.upload = {
      pid: p.id, title: p.title || p.idea.slice(0, 90), description,
      tags: (p.yt_tags || []).join(', '), category_id: '22', privacy: 'private',
    };
  }
  const u = state.upload;
  const cats = state.youtubeCategories || [];
  const already = (p.render || {}).youtube_url;

  return `<div class="panel" style="margin-top:18px">
    <div class="row" style="margin-bottom:14px">
      <strong>Publish to YouTube</strong>
      <span class="mono" style="color:var(--ink-faint)">— ${esc(yt.channel_title || '')}</span>
      <div class="spacer"></div>
      ${already ? `<a class="pill on" href="${esc(already)}" target="_blank">already uploaded — view it</a>` : ''}
    </div>
    <label class="field"><span>Title</span>
      <input type="text" value="${esc(u.title)}" maxlength="100"
        onchange="state.upload.title=this.value"></label>
    <label class="field"><span>Description</span>
      <textarea rows="5" onchange="state.upload.description=this.value">${esc(u.description)}</textarea></label>
    <div class="grid-3">
      <label class="field" style="margin:0"><span>Tags — comma separated</span>
        <input type="text" value="${esc(u.tags)}" placeholder="history, documentary"
          onchange="state.upload.tags=this.value"></label>
      <label class="field" style="margin:0"><span>Category</span>
        <select onchange="state.upload.category_id=this.value">
          ${cats.map((c) => `<option value="${c.id}" ${c.id === u.category_id ? 'selected' : ''}>
            ${esc(c.label)}</option>`).join('')}
        </select></label>
      <label class="field" style="margin:0"><span>Privacy</span>
        <select onchange="state.upload.privacy=this.value">
          <option value="private" ${u.privacy === 'private' ? 'selected' : ''}>Private</option>
          <option value="unlisted" ${u.privacy === 'unlisted' ? 'selected' : ''}>Unlisted</option>
          <option value="public" ${u.privacy === 'public' ? 'selected' : ''}>Public</option>
        </select></label>
    </div>
    <div class="row" style="margin-top:6px">
      <button class="btn sm primary" onclick="doYoutubeUpload()">
        ${already ? 'upload again' : 'upload to YouTube'}</button>
      ${u.privacy !== 'private' ? `<span class="pill warn">will be ${u.privacy} the moment it finishes</span>` : ''}
    </div>
  </div>`;
}

async function doYoutubeUpload() {
  const u = state.upload;
  if (u.privacy !== 'private'
      && !confirm(`This will be ${u.privacy} on YouTube as soon as it finishes uploading. Continue?`)) {
    return;
  }
  const r = await api(`/api/projects/${state.project.id}/youtube/upload`, {
    method: 'POST',
    body: JSON.stringify({
      title: u.title, description: u.description,
      tags: u.tags.split(',').map((t) => t.trim()).filter(Boolean),
      category_id: u.category_id, privacy: u.privacy,
    }),
  });
  watchJob(r.job, 'youtube upload');
  render();
}

// ------------------------------------------------------------ description
// The YouTube description: Claude writes the hook, the summary and the tags;
// the chapter timestamps come off the timeline and the credits off the
// pictures, so neither is guessed. Editable, and kept on the project.
function descriptionPanel(p) {
  const text = p.description || '';
  const chars = text.length;
  return `
    <div class="panel" style="margin-top:18px">
      <div class="row" style="margin-bottom:10px">
        <strong>YouTube description</strong>
        <span class="mono" style="color:var(--ink-faint)">hook, summary, chapters with
          timestamps, credits and tags</span>
        <div class="spacer"></div>
        <button class="btn sm ${text ? 'ghost' : 'primary'}" onclick="writeDescription()">
          ${text ? 'write it again' : 'write it'}</button>
        ${text ? `<button class="btn sm" onclick="copyDescription()">copy</button>` : ''}
      </div>
      ${text ? `
        <textarea id="desc-text" rows="14" style="width:100%;font-family:var(--mono, monospace);font-size:13px"
          onchange="saveDescription(this.value)">${esc(text)}</textarea>
        <div class="row" style="margin-top:6px">
          <span class="mono" style="color:${chars > 4800 ? 'var(--warn, #e0a050)' : 'var(--ink-faint)'}">
            ${chars.toLocaleString()} / 5,000 characters</span>
          <div class="spacer"></div>
          ${p.recorded_count < p.slides.length ? `<span class="pill warn">${p.slides.length - p.recorded_count}
            paragraph${p.slides.length - p.recorded_count === 1 ? '' : 's'} not recorded — chapter
            times are estimates; write it again after recording</span>` : ''}
        </div>
        <label class="field" style="margin:10px 0 0"><span>Tags — comma separated</span>
          <input type="text" value="${esc((p.yt_tags || []).join(', '))}"
            onchange="saveProject({yt_tags:this.value.split(',').map((t)=>t.trim()).filter(Boolean)})"></label>`
      : `<div class="mono" style="color:var(--ink-faint)">
          Chapters use the paragraphs you've marked as chapters (two or more), or the
          script's outline beats if you haven't. Timestamps are taken from the cut itself.</div>`}
    </div>`;
}

async function writeDescription() {
  const p = state.project;
  if (p.description && !confirm('Write the description again? Your edits to it will be replaced.')) return;
  try {
    const r = await api(`/api/projects/${p.id}/description`, { method: 'POST' });
    watchJob(r.job, 'description', (j) => {
      if (j.state === 'done') { state.upload = null; render(); }
    });
    render();
  } catch (e) { toast(e.message, true); }
}

async function saveDescription(text) {
  await saveProject({ description: text });
  state.upload = null;      // the upload form starts from the saved one
}

async function copyDescription() {
  const el = document.getElementById('desc-text');
  const text = el ? el.value : (state.project.description || '');
  try { await navigator.clipboard.writeText(text); toast('description copied'); }
  catch { if (el) { el.select(); document.execCommand('copy'); toast('description copied'); } }
}

// -------------------------------------------------------- talking-head clip
function presenterPanel(p) {
  const pr = p.presenter || {};
  const has = !!pr.path;
  const src = `/api/projects/${p.id}/file/${pr.path}?v=${p.updated_at}`;
  const max = pr.source_duration || 0;

  if (!has) {
    return `<div class="panel" style="margin-top:18px">
      <div class="row">
        <div style="flex:1;min-width:200px">
          <strong>Talking head</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:4px">
            Optional. A short piece to camera, cut in after the slate — viewers
            settle faster once they have seen your face.</div>
        </div>
        <label class="btn sm" style="cursor:pointer">choose a clip
          <input type="file" accept="video/*" hidden onchange="uploadPresenter(this.files[0])">
        </label>
      </div>
    </div>`;
  }

  return `<div class="panel" style="margin-top:18px">
    <div class="row" style="margin-bottom:14px">
      <strong>Talking head</strong>
      <span class="pill ${pr.enabled ? 'on' : ''}">${pr.duration.toFixed(1)}s on screen</span>
      ${pr.has_audio ? '' : '<span class="pill warn">no audio track</span>'}
      <div class="spacer"></div>
      <label class="row" style="gap:8px;cursor:pointer">
        <input type="checkbox" ${pr.enabled ? 'checked' : ''} style="width:auto"
          onchange="savePresenter({enabled:this.checked})">
        <span>include it</span>
      </label>
    </div>

    <div class="media-row">
      <div>
        ${videoTag(src, { scope: 'project', id: p.id, rel: pr.path },
                   'controls preload="metadata" id="presvid"')}
        <div class="mono" style="color:var(--ink-faint);margin-top:6px">
          ${esc(pr.filename)} · ${pr.width}×${pr.height} · ${max.toFixed(1)}s source</div>
      </div>
      <div>
        <label class="field"><span>Where it goes</span>
          <select onchange="savePresenter({position:this.value})">
            <option value="after_intro" ${pr.position === 'after_intro' ? 'selected' : ''}>
              after the channel slate</option>
            <option value="start" ${pr.position === 'start' ? 'selected' : ''}>
              at the very start, before the slate</option>
            <option value="end" ${pr.position === 'end' ? 'selected' : ''}>
              at the end, as a sign-off</option>
          </select></label>

        <label class="field"><span>Trim the start — <b>${pr.trim_start.toFixed(1)}s</b></span>
          <input type="range" min="0" max="${Math.max(0.1, max - 0.5).toFixed(1)}" step="0.1"
            value="${pr.trim_start}" oninput="scrubPresenter(this.value)"
            onchange="savePresenter({trim_start:+this.value})"></label>
        <label class="field"><span>Trim the end — <b>${pr.trim_end.toFixed(1)}s</b></span>
          <input type="range" min="0" max="${Math.max(0.1, max - 0.5).toFixed(1)}" step="0.1"
            value="${pr.trim_end}" oninput="scrubPresenter(${max} - this.value)"
            onchange="savePresenter({trim_end:+this.value})"></label>

        <div class="row">
          <button class="btn sm ghost" onclick="setPresenterFocal()">
            ${(pr.focal || []).length === 2 ? '✛ focus set' : 'set focus point'}</button>
          <div class="spacer"></div>
          <button class="btn sm ghost danger" onclick="removePresenter()">remove</button>
        </div>
        <div class="mono" style="color:var(--ink-faint);margin-top:10px">
          Your camera audio is levelled to match the narration 
          under it too. It dissolves in and out over ${(p.style.transition).toFixed(2)}s.</div>
      </div>
    </div>
  </div>`;
}

function scrubPresenter(t) {
  const v = document.getElementById('presvid');
  if (v) { v.currentTime = Math.max(0, +t); }
}

async function uploadPresenter(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  toast('uploading…');
  try {
    await api(`/api/projects/${state.project.id}/presenter`, { method: 'POST', body: fd });
    state.project = await api(`/api/projects/${state.project.id}`);
    render();
    toast('clip added');
  } catch (e) { toast(e.message, true); }
}

async function savePresenter(patch) {
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ presenter: patch }) });
  render();
}

async function removePresenter() {
  if (!confirm('Remove the talking-head clip from this video?')) return;
  await api(`/api/projects/${state.project.id}/presenter`, { method: 'DELETE' });
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}

function setPresenterFocal() {
  const p = state.project, pr = p.presenter;
  // Grab a still from the clip so the point can be placed on an actual frame.
  const v = document.getElementById('presvid');
  const canvas = document.createElement('canvas');
  canvas.width = pr.width || 1280;
  canvas.height = pr.height || 720;
  let src;
  try {
    canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height);
    src = canvas.toDataURL('image/jpeg', 0.85);
  } catch { src = ''; }
  if (!src) return toast('Play the clip for a moment first, then set the point.', true);
  openFocal(src, pr.focal, (focal) => savePresenter({ focal }));
}

async function saveStyle(patch) {
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ style: patch }) });
  render();
}
const pickProjectFormat = (key) => saveStyle({ format: key });

async function saveProject(patch) {
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify(patch) });
  toast('saved');
}

async function doRender(preview) {
  const r = await api(`/api/projects/${state.project.id}/render`,
    { method: 'POST', body: JSON.stringify({ preview }) });
  watchJob(r.job, preview ? 'preview render' : 'render');
  render();
}

route();

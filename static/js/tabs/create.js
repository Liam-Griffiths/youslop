/* Create: graphics made with an agent, then placed in shots. A graphic is a
   small HTML fragment in the channel's slide vocabulary (titles, numbers,
   cards, timed reveals); every agent revision is a version you can go back to.
   Previews are quarter-size stills at a few moments; placing renders it once. */
let createView = {pid: null, graphics: [], picked: '', t: 1, playing: 0, pending: null};
const createChats = new Map();
let createBusy = '';
const CREATE_STEPS = [0, .25, .5, .75, 1];

function createFromShot(sid) {
  const p = state.project, {run} = scriptShotOf(sid);
  createView.pending = {brief: run[0]?.visual_note || '', slide: sid};
  go(`#/p/${p.id}/create`);
}

async function paintCreate() {
  const pid = state.project.id;
  if (createView.pid !== pid) createView = {pid, graphics: [], picked: '', t: 1, playing: 0, pending: createView.pending};
  $('#tabbody').innerHTML = '<p class="sub">Loading graphics…</p>';
  try {
    const data = await api(`/api/projects/${pid}/graphics`);
    if (state.project?.id !== pid || state.stage !== 'create') return;
    createView.graphics = data.graphics;
    if (!createView.graphics.some(g => g.id === createView.picked)) createView.picked = createView.graphics.at(-1)?.id || '';
    createShell();
  } catch (e) { $('#tabbody').innerHTML = `<p class="sub">${esc(e.message)}</p>`; }
}
function createGraphic() { return createView.graphics.find(g => g.id === createView.picked); }

function createShell() {
  const g = createGraphic(), pending = createView.pending;
  $('#tabbody').innerHTML = `<div class="create-layout">
    <nav class="create-list" aria-label="Graphics">
      <form class="create-new" onsubmit="event.preventDefault(); createNew()">
        <label class="kicker" for="create-brief">New graphic</label>
        <textarea id="create-brief" rows="3" placeholder="Describe it: a number landing, a comparison, a title card, a timeline…">${esc(pending?.brief || '')}</textarea>
        <button class="btn sm">Make it with the agent</button></form>
      <h2 class="kicker create-list-head">This project · ${createView.graphics.length}</h2>
      ${createView.graphics.map(x => `<button class="create-row" aria-current="${x.id === createView.picked}" onclick="createPick('${x.id}')">
        <span class="create-row-title">${esc(x.title)}</span>
        <span class="mono">${x.versions.length ? `v${x.current + 1}` : 'not made yet'} · ${(+x.seconds).toFixed(1)} s${x.used_in?.length ? ` · in ${x.used_in.length} shot${x.used_in.length === 1 ? '' : 's'}` : ''}</span></button>`).join('')
        || '<p class="sub">Nothing yet. Describe a graphic above and the agent makes a first version.</p>'}
    </nav>
    <section class="create-stage" aria-label="Graphic">${g ? createStage(g) : `<div class="create-empty"><h1>Make a graphic for your video</h1>
      <p>Title cards, big numbers, comparisons, lists and timelines, animated in your channel's style. Describe one on the left, then shape it with the agent and place it in a shot.</p></div>`}</section>
    ${g ? `<aside class="create-agent" aria-label="Graphics agent">${createAgentPanel(g)}</aside>` : ''}
  </div>`;
  createAgentPaint();
}

function createStill(g, f) {
  return `/api/projects/${createView.pid}/graphics/${g.id}/still?v=${g.current}&t=${(f * g.seconds).toFixed(2)}`;
}
function createStage(g) {
  const made = g.versions.length > 0, f = createView.t;
  const runs = scriptRuns(state.project);
  let n = 0;
  const options = runs.map((run, i) => run.filter(s => !s.insert?.kind).map(s => `<option value="${s.id}" ${createView.pending?.slide === s.id ? 'selected' : ''}>Shot ${i + 1} · ¶${++n} · ${esc(s.narration.slice(0, 60))}</option>`).join('')).join('');
  const placed = [...new Set((g.used_in || []).map(sid => scriptShotOf(sid).index).filter(i => i >= 0))].map(i => i + 1);
  return `<div class="create-head">
      <label class="sr-only" for="create-title">Name</label>
      <input id="create-title" class="create-title" value="${esc(g.title)}" onchange="createPatch({title:this.value})">
      <span class="mono sub">HTML · 1920×1080 · channel style</span>
      <span class="spacer"></span>
      <button class="btn sm ghost" onclick="createRemove()">Remove</button></div>
    <div class="create-card">
      ${made ? `<img class="create-preview" src="${createStill(g, f)}" alt="${esc(g.title)} at ${(f * g.seconds).toFixed(1)} seconds">
        <div class="create-frames" role="group" aria-label="Moments">${CREATE_STEPS.map(x => `<button class="create-frame" aria-pressed="${x === f}" onclick="createAt(${x})">
          <img src="${createStill(g, x)}" alt="" loading="lazy"><span class="mono">${(x * g.seconds).toFixed(1)} s</span></button>`).join('')}</div>
        <div class="create-controls">
          <button class="btn sm" onclick="createPlay()">${createView.playing ? 'Stop' : '▶ Step through'}</button>
          <label class="create-seconds">Length <input type="number" min="2" max="20" step="0.5" value="${g.seconds}" onchange="createPatch({seconds:+this.value})"> s</label>
          <span class="spacer"></span>
          <div class="create-versions" role="group" aria-label="Versions">${g.versions.map((v, i) => `<button class="btn xs" aria-pressed="${i === g.current}" title="${esc(v.note || '')}" onclick="createPatch({current:${i}})">v${i + 1}</button>`).join('')}</div>
        </div>`
        : '<div class="create-preview empty">Ask the agent for a first version →</div>'}
    </div>
    <div class="create-cols">
      <section class="create-card" aria-labelledby="create-use"><h2 id="create-use">Use in the video</h2>
        <label class="kicker" for="create-slide">Paragraph it plays over</label>
        <select id="create-slide">${options}</select>
        <p class="sub">It starts with the paragraph and holds on its last frame.${placed.length ? ` In shot${placed.length === 1 ? '' : 's'} ${placed.join(', ')}.` : ''}</p>
        <button class="btn sm" ${made ? '' : 'disabled'} onclick="createPlace()">Place in shot</button></section>
      <section class="create-card" aria-labelledby="create-details"><h2 id="create-details">Details</h2>
        <label class="kicker" for="create-brief-edit">Brief</label>
        <textarea id="create-brief-edit" rows="3" onchange="createPatch({brief:this.value})">${esc(g.brief || '')}</textarea>
        <p class="sub">Rights: yours, made in this project.</p>
        ${made ? `<details><summary>Edit the HTML</summary>
          <textarea id="create-html" rows="8" class="mono">${esc(g.versions[g.current]?.html || '')}</textarea>
          <button class="btn sm" onclick="createPatch({html:$('#create-html').value})">Save as a new version</button></details>` : ''}
      </section>
    </div>`;
}

function createPick(id) { createView.picked = id; createView.t = 1; createStop(); createShell(); }
function createAt(f) { createView.t = f; createStop(); createShell(); }
function createStop() { clearInterval(createView.playing); createView.playing = 0; }
function createPlay() {
  if (createView.playing) { createStop(); return createShell(); }
  let i = 0;
  createView.t = CREATE_STEPS[0];
  createShell();
  createView.playing = setInterval(() => {
    if (state.stage !== 'create' || ++i >= CREATE_STEPS.length) { createStop(); if (state.stage === 'create') createShell(); return; }
    createView.t = CREATE_STEPS[i];
    const g = createGraphic(), img = $('.create-preview');
    if (g && img) img.src = createStill(g, createView.t);
    document.querySelectorAll('.create-frame').forEach((b, k) => b.setAttribute('aria-pressed', String(k === i)));
  }, 700);
  createShell();
}
async function createSend(path, method, body) {
  const pid = createView.pid;
  try {
    const data = await api(`/api/projects/${pid}/graphics${path}`, {method, body: body ? JSON.stringify(body) : undefined});
    if (createView.pid !== pid) return null;
    createView.graphics = data.graphics;
    return data;
  } catch (e) { toast(e.message, true); return null; }
}
async function createNew() {
  const brief = $('#create-brief').value.trim();
  if (!brief) return;
  const data = await createSend('', 'POST', {brief});
  if (!data) return;
  createView.picked = data.graphic.id;
  createView.t = 1;
  createShell();
  createAgentSend('Make this graphic: ' + brief);
}
async function createPatch(patch) {
  const g = createGraphic();
  if (!g) return;
  if (await createSend('/' + g.id, 'PATCH', patch)) createShell();
}
async function createRemove() {
  const g = createGraphic();
  if (!g) return;
  // Shots it was placed in keep their render; only the editable graphic goes.
  if (await createSend('/' + g.id, 'DELETE')) { createView.picked = createView.graphics.at(-1)?.id || ''; createShell(); }
}
async function createPlace() {
  const g = createGraphic(), slide = $('#create-slide')?.value;
  if (!g || !slide) return;
  try {
    const r = await api(`/api/projects/${createView.pid}/graphics/${g.id}/place`, {method: 'POST', body: JSON.stringify({slide})});
    createView.pending = null;
    watchJob(r.job, 'placing a graphic', j => { if (j.state === 'done') toast(`${g.title} placed. It shows in Script › Shots and Edit.`); });
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- the agent
function createChat(pid, id) {
  if (!createChats.has(pid)) {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('corkbored-create-chat-' + pid)) || {}; } catch { /* Storage may be disabled. */ }
    createChats.set(pid, saved && typeof saved === 'object' ? saved : {});
  }
  const chats = createChats.get(pid);
  if (!Array.isArray(chats[id])) chats[id] = [];
  return chats[id];
}
function createChatKeep(pid) {
  const chats = createChats.get(pid) || {};
  Object.values(chats).forEach(c => { if (c.length > 30) c.splice(0, c.length - 30); });
  try { localStorage.setItem('corkbored-create-chat-' + pid, JSON.stringify(chats)); } catch { /* Storage may be disabled. */ }
}
function createAgentPanel(g) {
  return `<div class="shots-agent-head"><h2>Agent</h2><span class="mono">working on ${esc(g.title.slice(0, 28))}</span></div>
    <div class="script-agent-log" id="create-agent-log" aria-live="polite"></div>
    <div class="script-agent-compose">
      <div class="script-agent-chips">
        <button class="btn xs" onclick="createAgentSend('Time the reveals to the narration it plays under.')">Time it to the words</button>
        <button class="btn xs" onclick="createAgentSend('Make it simpler: fewer words, bigger type.')">Simpler</button>
        <button class="btn xs" onclick="createAgentSend('Check every number and claim against the facts.')">Check the facts used</button>
      </div>
      <div class="script-agent-input"><label class="sr-only" for="create-agent-input">Message the graphics agent</label>
        <textarea id="create-agent-input" rows="2" placeholder="Describe a change…"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();createAgentSend();}"></textarea>
        <button class="btn sm" id="create-agent-send" onclick="createAgentSend()">Send</button></div>
    </div>`;
}
function createAgentPaint() {
  const log = $('#create-agent-log'), g = createGraphic();
  if (!log || !g) return;
  const chat = createChat(createView.pid, g.id);
  log.innerHTML = (chat.map(m => m.role === 'user' ? `<div class="agent-msg user">${esc(m.text)}</div>`
      : `<div class="agent-msg${m.error ? ' error' : ''}">${esc(m.text)}</div>${m.version ? `<p class="agent-note">Made v${m.version}.</p>` : ''}`).join('')
    || '<p class="agent-note">Describe what the graphic should show and how it should build. Each change is a new version; earlier ones stay.</p>')
    + (createBusy === g.id ? '<p class="agent-note agent-busy">Designing…</p>' : '');
  const send = $('#create-agent-send');
  if (send) send.disabled = !!createBusy;
  log.scrollTop = log.scrollHeight;
}
async function createAgentSend(text) {
  const g = createGraphic(), pid = createView.pid, input = $('#create-agent-input');
  text = String(text ?? input?.value ?? '').trim();
  if (!g || !text || createBusy) return;
  const chat = createChat(pid, g.id);
  const history = chat.slice(-8).map(m => ({role: m.role, text: m.text}));
  chat.push({role: 'user', text});
  if (input && input.value.trim() === text) input.value = '';
  createBusy = g.id;
  createAgentPaint();
  try {
    const r = await api(`/api/projects/${pid}/graphics/${g.id}/agent`, {method: 'POST', body: JSON.stringify({message: text, history})});
    chat.push({role: 'agent', text: r.reply, version: r.changed ? r.graphic.versions.length : 0});
    const i = createView.graphics.findIndex(x => x.id === g.id);
    if (i >= 0) createView.graphics[i] = r.graphic;
    createView.t = 1;
  } catch (e) {
    chat.push({role: 'agent', text: e.message, error: true});
  } finally {
    createBusy = '';
    createChatKeep(pid);
    if (state.stage === 'create' && createView.pid === pid) createShell();
  }
}

// Script › Shots, steps 2 and 3: the visuals inside one shot and their design,
// plus the shot agent. A visual is a picture run inside the shot: it starts on
// a paragraph (picture_mode "cut" starts one without starting a new shot) and
// takes its kind and media from that paragraph, like everywhere else.
let shotBeatPicked = '';
const shotKindView = new Map();   // lead id -> kind tab the writer is looking at
const SHOT_KINDS = [['photo', 'Photo', 'a still, with a slow move'], ['clip', 'Clip', 'archive or your footage'],
  ['map', 'Map', 'a place or a route'], ['3d', '3D', 'a model and a camera move'],
  ['diagram', 'Diagram', 'drawn and animated'], ['scene', 'Scene', 'a designed slide or block']];

function shotKind(s) {
  if (s.kind === 'stage') return '3d';
  const c = s.candidates?.find(x => x.id === s.chosen_id) || {};
  if (s.cues?.blocks?.length || c.provider === 'custom') return 'scene';
  if (c.provider === 'diagram') return 'diagram';
  if (c.provider === 'maps' || s.prefer_kind === 'map') return 'map';
  return c.kind === 'video' || s.prefer_kind === 'video' ? 'clip' : 'photo';
}
function shotKindLabel(kind) { return SHOT_KINDS.find(k => k[0] === kind)?.[1] || kind; }

function shotBeats(p, row) {
  const leads = new Set((p.picture_runs || p.slides.map(s => [s.id])).map(r => r[0]));
  const beats = [];
  let at = row.start, n = row.first;
  row.run.filter(s => !s.insert?.kind).forEach((s, k) => {
    if (!k || leads.has(s.id)) beats.push({lead: s, paras: [], first: n, start: at, end: at, continues: !leads.has(s.id)});
    const beat = beats.at(-1);
    beat.paras.push(s);
    at += scriptSeconds(s); beat.end = at; n++;
  });
  beats.forEach(b => {
    b.kind = shotKind(b.lead);
    b.chosen = b.lead.candidates?.find(c => c.id === b.lead.chosen_id);
  });
  return beats;
}

// What the visual shows, only when it matches its kind (a map plan over an
// old photo is not a map yet).
function shotBeatTitle(b) {
  const c = b.chosen, provider = c?.provider;
  if (b.kind === 'map') return provider === 'maps' ? (b.lead.map_place || c.title || 'Map') : 'No map made yet';
  if (b.kind === 'diagram') return b.lead.diagram?.title || c?.title || 'Diagram';
  if (b.kind === 'scene') return b.lead.cues?.blocks?.[0]?.block?.replaceAll('_', ' ') || c?.title || 'No scene yet';
  if (b.kind === '3d') return b.lead.shot?.intent?.subject || '3D shot';
  return c && !['maps', 'diagram', 'custom'].includes(provider) ? (c.title || c.provider) : 'Not chosen yet';
}
function shotStrip(p, row, beats, picked) {
  const up = scriptNeighbourShot(row.lead.id, -1), down = scriptNeighbourShot(row.lead.id, 1);
  const spoken = row.run.filter(s => !s.insert?.kind);
  const words = spoken.map((s, k) => {
    const starts = beats.some(b => b.lead.id === s.id);
    return `<div class="shots-word${starts && k ? ' starts' : ''}" data-sid="${s.id}" style="flex:${Math.max(1, scriptSeconds(s)).toFixed(1)} 1 0">
      <div class="shots-word-head">
        <span class="mono shots-para-grip" draggable="true" title="Drag onto a shot in the list to move this paragraph"
          ondragstart="scriptDragStart(event,'${s.id}')" ondragend="scriptDragEnd()">⋮⋮ ¶${row.first + k}</span>
        ${k ? `<button class="btn xs ghost" onclick="shotBreak('${s.id}',${!starts})">${starts ? 'Join the visual before' : 'New visual here'}</button>` : ''}
        <details class="shots-word-menu"><summary aria-label="Paragraph ${row.first + k} actions">⋯</summary><div class="script-menu">
          ${up && k === 0 ? `<button class="btn sm ghost" onclick="scriptMoveToShot('${s.id}',-1)">Move to shot above</button>` : ''}
          ${k ? `<button class="btn sm ghost" onclick="scriptNewShot('${s.id}')">Start a new shot here</button>` : ''}
          ${down && k === spoken.length - 1 ? `<button class="btn sm ghost" onclick="scriptMoveToShot('${s.id}',1)">Move to shot below</button>` : ''}
          <button class="btn sm ghost" onclick="scriptShowInWrite('${s.id}')">Edit the words in Write</button></div></details>
      </div>
      <p>${esc(s.narration)}</p><span class="mono shots-word-voice">${scriptVoice(s)}</span></div>`;
  }).join('');
  const blocks = beats.map((b, i) => `<button class="shots-beat kind-${b.kind}" aria-pressed="${b === picked}"
      style="flex:${Math.max(1, b.end - b.start).toFixed(1)} 1 0" onclick="shotPickBeat('${b.lead.id}')">
      <span class="mono">${i + 1} · ${b.continues ? 'HELD' : shotKindLabel(b.kind).toUpperCase()} · ${fmtTime(b.start)}</span>
      <span class="shots-beat-title">${b.continues ? 'Continues the picture before' : esc(shotBeatTitle(b))}</span></button>`).join('');
  return `<div class="shots-strip"><div class="shots-words">${words}</div><div class="shots-beats">${blocks}</div></div>
    ${beats.length > 1 ? `<button class="btn sm ghost shots-one" onclick="shotOneVisual('${row.lead.id}')">One visual for the whole shot</button>` : ''}`;
}

function shotDesign(p, beat) {
  const s = beat.lead, view = shotKindView.get(s.id) || beat.kind;
  if (beat.continues) return `<p>This paragraph still shows the picture from the shot before. Give it a visual of its own to design it here.</p>
    <button class="btn sm primary" onclick="shotBreak('${s.id}',true)">Start a visual here</button>`;
  if (s.on_camera) return `<p>The camera take supplies this visual. Change its layout in Edit.</p>
    <button class="btn sm" onclick="openVisualEdit('${s.id}')">Open in Edit</button>`;
  const tabs = SHOT_KINDS.map(([id, label, sub]) => `<button role="radio" aria-checked="${id === view}" class="shots-kind"
      onclick="shotPickKind('${s.id}','${id}')"><strong>${label}</strong><span>${sub}</span></button>`).join('');
  const overlays = beat.paras.flatMap(q => (q.overlays || []).map(o => ({q, o})));
  return `<div class="shots-kinds" role="radiogroup" aria-label="Kind of visual">${tabs}
      <button class="btn sm ghost" onclick="openPictureKind('${s.id}')">More styles…</button></div>
    <div class="shots-design">${shotKindPanel(p, s, view)}</div>
    <div class="shots-design-foot">
      ${overlays.map(({q, o}) => `<button class="btn sm" onclick="openGraphicEdit('${q.id}','${esc(o.id)}')">Graphic · ${esc(o.vars?.title || o.block_id)}</button>`).join('')}
      <button class="btn sm ghost" onclick="openGraphicPicker('${s.id}')">Add a graphic over it</button>
      <span class="spacer"></span>
      <button class="btn sm" onclick="previewBit('${s.id}')">Preview with narration · ¼ size</button></div>`;
}

function shotPreview(s, c, empty) {
  return c ? `<img class="shots-picture" src="${esc(thumbUrl(c))}" alt="${esc(c.title || 'Chosen visual')}"
      style="object-position:${(c.focal?.[0] ?? .5) * 100}% ${(c.focal?.[1] ?? .5) * 100}%">`
    : `<div class="shots-picture empty">${esc(empty)}</div>`;
}
function shotCredit(c) {
  return c ? `<p class="mono shots-credit">${esc(c.provider)}${c.license ? ' · ' + esc(c.license) : ''}
    ${c.source_page ? ` · <a href="${esc(c.source_page)}" target="_blank" rel="noopener">Source</a>` : ''}</p>` : '';
}

function shotKindPanel(p, s, view) {
  const c = s.candidates?.find(x => x.id === s.chosen_id);
  if (view === 'photo' || view === 'clip') {
    const clip = view === 'clip';
    const shown = c && !['diagram', 'maps', 'custom'].includes(c.provider) && (c.kind === 'video') === clip ? c : null;
    const options = (s.candidates || []).filter(x => !['diagram', 'maps', 'custom'].includes(x.provider) && (x.kind === 'video') === clip);
    return `<div class="shots-design-preview">${shotPreview(s, shown, clip ? 'No clip chosen yet' : 'No photo chosen yet')}${shotCredit(shown)}
        ${shown && !clip ? `<button class="btn sm ghost" onclick="setSlideFocal('${s.id}','${shown.id}')">${shown.focal?.length === 2 ? 'Focus point set · change' : 'Set the focus point'}</button>` : ''}</div>
      <div class="shots-design-controls">
        <label class="kicker" for="shots-query">Search ${clip ? 'clips' : 'photos'}</label>
        <div class="shots-search"><input id="shots-query" type="search" value="${esc(s.queries?.[0] || s.visual_note || '')}"
          onkeydown="if(event.key==='Enter') shotSearch('${s.id}')"><button class="btn sm" onclick="shotSearch('${s.id}')">Search</button></div>
        <p class="sub" id="shots-search-status" role="status"></p>
        <div class="shots-options">${options.map(x => `<button class="shots-option" aria-pressed="${x.id === s.chosen_id}" onclick="shotChoose('${s.id}','${x.id}')">
          <img src="${esc(thumbUrl(x))}" alt="" loading="lazy"><span>${esc(x.title || x.provider)}</span></button>`).join('')
          || `<p class="sub">No ${clip ? 'clips' : 'photos'} gathered yet. Search, or bring one in.</p>`}</div>
        <div class="shots-row-actions"><button class="btn sm ghost" onclick="openMediaSearch('${s.id}')">Full search</button>
          <button class="btn sm ghost" onclick="pickVisualLibrary('${s.id}')">From Library…</button>
          <label class="btn sm ghost">Upload<input type="file" hidden accept="${clip ? 'video/*' : 'image/*'}" onchange="uploadMedia('${s.id}',this.files[0])"></label></div>
      </div>`;
  }
  if (view === 'map') return `<div class="shots-design-preview">${shotPreview(s, c?.provider === 'maps' ? c : null, 'No map made yet')}</div>
    <div class="shots-design-controls"><p><strong>${esc(s.map_place || 'No place chosen')}</strong></p>
      <p class="sub">${s.map_kind === 'street' ? 'Street map' : 'Satellite'} · ${s.map_style === 'establishing' ? 'establishing move' : 'still'}</p>
      <button class="btn sm primary" onclick="openMapPicker('${s.id}')">${s.map_place ? 'Change the place' : 'Choose the place'}</button></div>`;
  if (view === '3d') return `<div class="shots-design-preview">${shotPreview(s, c, '3D shot')}</div>
    <div class="shots-design-controls"><p class="sub">Models in this project: ${esc((p.cast || []).map(x => x.subject).filter(Boolean).join(', ') || 'none yet')}</p>
      ${s.shot?.intent ? `<button class="btn sm primary" onclick="openShot('${s.id}')">Open the 3D shot</button>` : ''}
      <div class="shots-row-actions"><a class="btn sm" href="#/p/${p.id}/edit/cast">Models and parts</a>
      <a class="btn sm" href="#/p/${p.id}/edit/stage">Shots and solver checks</a></div></div>`;
  if (view === 'diagram') return `<div class="shots-design-preview">${shotPreview(s, c?.provider === 'diagram' ? c : null, 'No diagram drawn yet')}</div>
    <div class="shots-design-controls"><p class="sub">A drawn diagram: boxes, arrows, labels and numbers, built from your description.</p>
      <button class="btn sm primary" onclick="openDiagramEditor('${s.id}')">${s.diagram && Object.keys(s.diagram).length ? 'Edit the diagram' : 'Draw a diagram'}</button></div>`;
  return `<div class="shots-design-preview">${s.cues?.blocks?.length ? visualBlockStill(p, s) : shotPreview(s, c?.provider === 'custom' ? c : null, 'No scene designed yet')}</div>
    <div class="shots-design-controls"><p class="sub">A designed frame: a title card, a number landing, a comparison or a timeline. Make it with the agent in Create, or design it by hand.</p>
      <div class="shots-row-actions"><button class="btn sm primary" onclick="createFromShot('${s.id}')">Make it in Create</button>
      <button class="btn sm" onclick="openCustomEditor('${s.id}')">Design a slide</button>
      <button class="btn sm" onclick="openBlockPicker('${state.project.id}','${s.id}')">Choose a block</button></div></div>`;
}

// ------------------------------------------------------------------ actions
async function shotReload() {
  const pid = state.project.id;
  const p = await api(`/api/projects/${pid}`);
  if (state.project?.id === pid) { state.project = p; paintScriptShots(); }
}
function shotPickBeat(lead) { shotBeatPicked = lead; paintScriptShots(); }
async function shotBreak(sid, start) {
  if (!(await scriptFlush())) return;
  if (await saveSlide(sid, {picture_mode: start ? 'cut' : 'hold'}, {quiet: true})) {
    if (start) shotBeatPicked = sid;
    await shotReload();
  }
}
// Every paragraph after the first holds its picture: the shot has one visual.
async function shotOneVisual(lead) {
  if (!(await scriptFlush())) return;
  const spoken = scriptShotOf(lead).run.filter(s => !s.insert?.kind);
  for (const s of spoken.slice(1)) {
    if (s.picture_mode !== 'hold' && !(await saveSlide(s.id, {picture_mode: 'hold'}, {quiet: true}))) return;
  }
  shotBeatPicked = spoken[0].id;
  await shotReload();
}
function shotKindPatch(p, s, kind) {
  const keep = ['kenburns', 'essay'].includes(s.kind) ? s.kind : ['kenburns', 'essay'].includes(p.style.format) ? '' : 'kenburns';
  const patch = kind === '3d' ? {kind: 'stage'}
    : kind === 'photo' ? {kind: keep, prefer_kind: 'image'} : kind === 'clip' ? {kind: keep, prefer_kind: 'video'}
    : kind === 'map' ? {kind: keep, prefer_kind: 'map'} : null;
  if (patch && s.cues?.blocks?.length) patch.cues = {blocks: [], inactive_blocks: s.cues.blocks};
  return patch && Object.entries(patch).some(([k, v]) => k === 'cues' || (s[k] || '') !== v) ? patch : null;
}
async function shotPickKind(sid, kind) {
  const p = state.project, s = p.slides.find(x => x.id === sid);
  shotKindView.set(sid, kind);
  const patch = s && !s.on_camera ? shotKindPatch(p, s, kind) : null;
  if (patch && !(await saveSlide(sid, patch, {quiet: true}))) return;
  paintScriptShots();
}
async function shotChoose(sid, cid) {
  if (await saveSlide(sid, {chosen_id: cid}, {quiet: true})) paintScriptShots();
}
async function shotSearch(sid, query = null, quiet = false) {
  const p = state.project, s = p.slides.find(x => x.id === sid);
  query = (query ?? $('#shots-query')?.value ?? '').trim();
  if (!s || !query) return;
  const status = $('#shots-search-status');
  if (status && !quiet) status.textContent = 'Searching…';
  try {
    const r = await api(`/api/projects/${p.id}/slides/${sid}/search`, {method: 'POST',
      body: JSON.stringify({query, kind: s.prefer_kind, source: 'archive'})});
    Object.assign(s, r.slide);
    if (!quiet && state.project === p && state.tab === 'shots') paintScriptShots();
  } catch (e) { if (status) status.textContent = e.message; }
}

// --------------------------------------------------------------- the agent
const shotChats = new Map();
let shotAgentBusy = '';
function shotChat(pid, lead) {
  if (!shotChats.has(pid)) {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('corkbored-shot-chat-' + pid)) || {}; } catch { /* Storage may be disabled. */ }
    shotChats.set(pid, saved && typeof saved === 'object' ? saved : {});
  }
  const chats = shotChats.get(pid);
  if (!Array.isArray(chats[lead])) chats[lead] = [];
  return chats[lead];
}
function shotChatKeep(pid) {
  const chats = shotChats.get(pid) || {};
  Object.values(chats).forEach(chat => { if (chat.length > 30) chat.splice(0, chat.length - 30); });
  try { localStorage.setItem('corkbored-shot-chat-' + pid, JSON.stringify(chats)); } catch { /* Storage may be disabled. */ }
}
function shotAgentPanel(row) {
  return `<div class="shots-agent-head"><h2>Shot agent</h2><span class="mono">shot ${row.index + 1}</span></div>
    <div class="script-agent-log" id="shot-agent-log" aria-live="polite"></div>
    <div class="script-agent-compose">
      <div class="script-agent-chips">
        <button class="btn xs" onclick="shotAgentSend('Plan the visuals for this shot: what to show, and where each starts.')">Plan the visuals</button>
        <button class="btn xs" onclick="shotAgentSend('Write a description for this shot.')">Write the description</button>
        <button class="btn xs" onclick="shotAgentSend('What would show these words best, and why?')">What shows this best?</button>
      </div>
      <div class="script-agent-input"><label class="sr-only" for="shot-agent-input">Message the shot agent</label>
        <textarea id="shot-agent-input" rows="2" placeholder="Describe what you want this shot to show…"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();shotAgentSend();}"></textarea>
        <button class="btn sm primary" id="shot-agent-send" onclick="shotAgentSend()">Send</button></div>
    </div>`;
}
function shotAgentMessage(m, i) {
  if (m.role === 'user') return `<div class="agent-msg user">${esc(m.text)}</div>`;
  const desc = m.description ? `<div class="agent-card edit"><span class="kicker">Description</span><p>${esc(m.description)}</p>
    <div class="agent-card-actions">${m.descState === 'used' ? '<span class="agent-note">Used.</span>'
      : `<button class="btn sm primary" onclick="shotAgentUseDescription(${i})">Use this description</button>`}</div></div>` : '';
  const plan = m.visuals?.length ? `<div class="agent-card edit"><span class="kicker">Visuals · ${m.visuals.length}</span>
    <ol class="shots-plan">${m.visuals.map(v => `<li><span class="mono">¶${v.paragraph} · ${esc(shotKindLabel(v.kind))}</span> ${esc(v.query)}${v.why ? `<span class="agent-note"> ${esc(v.why)}</span>` : ''}</li>`).join('')}</ol>
    <div class="agent-card-actions">${m.planState === 'applied' ? '<span class="agent-note">Set up. Undo in the top bar reverses it.</span>'
      : `<button class="btn sm primary" onclick="shotAgentApply(${i})">Set up these visuals</button>`}</div></div>` : '';
  return `<div class="agent-msg${m.error ? ' error' : ''}">${esc(m.text)}</div>${desc}${plan}`;
}
function shotAgentPaint() {
  const log = $('#shot-agent-log');
  if (!log || !state.project) return;
  const pid = state.project.id, lead = scriptShotPicked, chat = shotChat(pid, lead);
  log.innerHTML = (chat.length ? chat.map(shotAgentMessage).join('')
    : '<p class="agent-note">Tell the agent what this shot should show, or ask it to plan the visuals. It suggests; nothing changes until you choose.</p>')
    + (shotAgentBusy === pid + lead ? '<p class="agent-note agent-busy">Thinking about the shot…</p>' : '');
  const send = $('#shot-agent-send');
  if (send) send.disabled = !!shotAgentBusy;
  log.scrollTop = log.scrollHeight;
}
async function shotAgentSend(text) {
  const input = $('#shot-agent-input'), pid = state.project?.id, lead = scriptShotPicked;
  text = String(text ?? input?.value ?? '').trim();
  if (!text || !pid || !lead || shotAgentBusy) return;
  const chat = shotChat(pid, lead);
  const history = chat.slice(-8).map(m => ({role: m.role, text: m.text}));
  chat.push({role: 'user', text});
  if (input && input.value.trim() === text) input.value = '';
  shotAgentBusy = pid + lead;
  shotAgentPaint();
  try {
    const r = await api(`/api/projects/${pid}/script/shot-agent`, {method: 'POST', body: JSON.stringify({message: text, shot: lead, history})});
    chat.push({role: 'agent', text: r.reply, description: r.description || '', visuals: r.visuals || []});
  } catch (e) {
    chat.push({role: 'agent', text: e.message, error: true});
  } finally {
    shotAgentBusy = '';
    shotChatKeep(pid);
    if (state.project?.id === pid && state.tab === 'shots') shotAgentPaint();
  }
}
async function shotAgentUseDescription(i) {
  const pid = state.project.id, lead = scriptShotPicked, m = shotChat(pid, lead)[i];
  if (!m?.description) return;
  m.descState = 'used';
  shotChatKeep(pid);
  await scriptSaveShotNote(lead, m.description);
}
// Apply a plan: visual starts become "cut", the rest of the shot holds, each
// start gets its kind, and photo or clip starts search for the suggestion.
async function shotAgentApply(i) {
  const p = state.project, pid = p.id, lead = scriptShotPicked, m = shotChat(pid, lead)[i];
  if (!m?.visuals?.length || !(await scriptFlush())) return;
  const {run} = scriptShotOf(lead), spoken = run.filter(s => !s.insert?.kind);
  const starts = new Map(m.visuals.map(v => [v.start, v]));
  try {
    const leads = new Set((p.picture_runs || []).map(r => r[0]));
    for (const [k, s] of spoken.entries()) {
      if (!k) {
        // A shot that opens on the previous shot's picture gets its own first.
        if (!leads.has(s.id) && s.picture_mode !== 'new' && !(await saveSlide(s.id, {picture_mode: 'cut'}, {quiet: true}))) throw Error('Could not set the visual breaks.');
        continue;
      }
      const mode = starts.has(s.id) ? 'cut' : 'hold';
      if (s.picture_mode !== mode && !(await saveSlide(s.id, {picture_mode: mode}, {quiet: true}))) throw Error('Could not set the visual breaks.');
    }
    for (const v of m.visuals) {
      const s = p.slides.find(x => x.id === v.start);
      if (!s || s.on_camera) continue;
      shotKindView.set(s.id, v.kind);
      const patch = shotKindPatch(p, s, v.kind);
      if (patch && !(await saveSlide(s.id, patch, {quiet: true}))) throw Error('Could not set a visual kind.');
      if (['photo', 'clip'].includes(v.kind) && v.query) await shotSearch(s.id, v.query, true);
    }
    m.planState = 'applied';
    shotChatKeep(pid);
    shotBeatPicked = m.visuals[0].start;
    toast('Visuals set up for this shot.');
  } catch (e) { toast(e.message, true); }
  if (state.project?.id === pid) await shotReload();
}

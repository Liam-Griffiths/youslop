/* Studio shell; stage contents remain the existing tab implementations. */
const STAGES = [
  ['dashboard', 'Dashboard'], ['script', 'Script'], ['voice', 'Voice'],
  ['edit', 'Edit'], ['publish', 'Publish'],
];
const projectStages = p => p?.kind === 'clip' ? [['clip','Clip'],['edit','Edit'],['publish','Publish']] : STAGES;
const LEGACY_STAGES = {plan: 'script/outline', visuals: 'edit/pictures',
  media: 'edit/pictures', cast: 'edit/cast', stage: 'edit/stage',
  record: 'voice', render: 'edit', thumb: 'publish/thumb'};

function canonicalHash(hash) {
  if (hash === '#/projects') return '#/';
  if (hash.startsWith('#/c/')) return hash.replace('#/c/', '#/channels/');
  const p = hash.match(/^#\/p\/([^/]+)(?:\/(\w+))?(?:\/(\w+))?$/);
  if (!p) return hash;
  const stage = p[2] === 'visuals' && ['cast', 'stage'].includes(p[3]) ? `edit/${p[3]}`
    : LEGACY_STAGES[p[2]] || ([...STAGES, ['clip']].some(([id]) => id === p[2])
      ? [p[2], p[3]].filter(Boolean).join('/') : 'dashboard');
  return `#/p/${p[1]}/${stage}`;
}

function stageTab(stage, subtab) {
  return {clip: 'clip', dashboard: 'dashboard', script: subtab === 'outline' ? 'plan' : 'script',
    voice: 'record', edit: {pictures: 'media', cast: 'cast', stage: 'stage'}[subtab] || 'edit',
    publish: 'render'}[stage] || 'dashboard';
}

function paintAppNav() {
  const hash = location.hash || '#/';
  $('#app-nav').innerHTML = [['', 'Projects'], ['footage', 'Footage'], ['library', 'Library'],
    ['blocks', 'Blocks'], ['channels', 'Channels'], ['packs', 'Packs'], ['settings', 'Settings']].map(([id, name]) => {
      const active = id ? hash.startsWith(`#/${id}`) : hash === '#/' || hash === '#/projects';
      return `<a href="#/${id}" ${active ? 'aria-current="page"' : ''}>${name}</a>`;
    }).join('');
}

// Edit borrows the shell slot inside its player row so the lanes below can
// span the whole window. Restore it before replacing any stage contents.
function restoreShellInspector() {
  const inspector = $('#inspector');
  $('.app-shell').append(inspector);
  $('.app-shell').classList.remove('edit-workspace');
  inspector.replaceChildren();
}

function resetShell() {
  restoreShellInspector();
  $('#app-nav').hidden = false;
  $('#project-bar').hidden = true;
  $('#stage-bar').hidden = true;
  $('.shell-more').open = false;
  $('#topbar-right').innerHTML = '';
  paintAppNav();
}

// Configuration status only: no model requests, downloads or render probes.
async function loadShellStatus() {
  if (!state.shellStatus) state.shellStatus = Promise.all([
    api('/api/llm/status').catch(() => null), api('/api/tts').catch(() => null),
    api('/api/settings').catch(() => null),
  ]);
  const [llm, voice, settings] = await state.shellStatus;
  if (state.project) return;
  const backend = llm ? `Writing · ${llm.label || llm.resolved}${llm.local ? ' (local)' : ''}${llm.resolved === 'cli' && !llm.cli_found ? ' unavailable' : ''}` : 'Writing · unknown';
  $('#topbar-right').textContent = [backend,
    voice ? `Voice · ${voice.ready ? 'ready' : 'not ready'}` : 'Voice · unknown',
    settings ? `Scenes · ${settings.card_engine}` : 'Scenes · unknown'].join(' · ');
}

function paintProjectShell() {
  const p = state.project;
  $('#app-nav').hidden = true;
  const bar = $('#project-bar');
  bar.hidden = false;
  const stages = projectStages(p);
  const i = stages.findIndex(([id]) => id === state.stage);
  const rows = state.stageStates?.pid === p.id ? state.stageStates.items : [];
  const next = state.stage === 'dashboard'
    ? stages.find(([id]) => id !== 'dashboard' && rows.some(r => r.id === id && r.status !== 'ready'))
    : stages[i + 1];
  const channel = (state.channels || []).find(c => c.id === p.channel_id);
  const format = p.kind === 'clip' ? 'Clip' : FORMAT_INFO.find(f => f.key === p.style.format)?.label || p.style.format;
  bar.innerHTML = `<span class="project-title">/ ${esc(p.title || p.idea.slice(0, 60))}</span>
    <span class="project-meta">${esc(channel?.name || (p.channel_id ? 'Channel' : 'Standalone'))} · ${esc(format)} · ${p.aspect === 'portrait' ? '9:16' : p.aspect === 'square' ? '1:1' : '16:9'}</span>
    <button type="button" class="btn sm" onclick="restoreProjectEdit('undo')" aria-keyshortcuts="Control+Z Meta+Z" title="Undo (Ctrl+Z)">Undo</button>
    <button type="button" class="btn sm" onclick="restoreProjectEdit('redo')" aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z" title="Redo (Ctrl+Shift+Z)">Redo</button>
    ${state.tab === 'edit' ? `<button type="button" class="btn sm" onclick="tlPreviewBit()">Preview this bit</button>` : ''}
    ${state.stage === 'voice' ? `<button type="button" class="btn sm" onclick="openMicPanel()">Microphone setup</button>
      <button type="button" class="btn sm" onclick="setNarrator({mode:'ai'})">Draft voice settings</button>` : ''}
    ${next ? `<a class="btn primary" href="#/p/${p.id}/${next[0]}">Next: ${esc(next[1])}</a>` : ''}`;
  $('#topbar-right').innerHTML = '';
  paintStageBar();
}

let projectHistoryBusy = false;
async function restoreProjectEdit(direction) {
  if (!state.project || projectHistoryBusy || state.rec.recording || TL.drag) return;
  projectHistoryBusy = true;
  const pid = state.project.id;
  try {
    await tlInspectorQueue;
    await Promise.allSettled([...studioWrites]);
    if (state.project?.id !== pid) return;
    tlPause();
    const project = await api(`/api/projects/${pid}/${direction}`, {method:'POST'});
    if (state.project?.id !== pid) return;
    state.project = project;
    if (state.tab === 'edit') { await tlRefreshProject(); paintProjectShell(); }
    else await render();
    loadStageStates(state.project);
    toast(`${direction === 'undo' ? 'Undid' : 'Redid'}: ${project.edit_label}`);
  } catch (e) { toast(e.message, true); }
  finally { projectHistoryBusy = false; }
}

document.addEventListener('keydown', e => {
  if (e.defaultPrevented || e.isComposing || e.repeat || !(e.ctrlKey || e.metaKey) || e.altKey
      || e.key.toLowerCase() !== 'z' || !state.project
      || e.target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')) return;
  e.preventDefault();
  restoreProjectEdit(e.shiftKey ? 'redo' : 'undo');
});

function paintStageBar() {
  const p = state.project;
  if (!p) return;
  const bar = $('#stage-bar');
  bar.hidden = false;
  const stages = state.stageStates?.pid === p.id ? state.stageStates.items : [];
  bar.innerHTML = projectStages(p).map(([id, label], i) => {
    const info = stages.find(s => (s.id || s.stage || s.key) === id);
    const active = id === state.stage;
    return `<a class="stage-link ${active ? 'active' : ''} ${info?.status === 'ready' ? 'done' : info?.status === 'warn' ? 'warn' : ''}"
      href="#/p/${p.id}/${id}" ${active ? 'aria-current="step"' : ''}>
      <span>${i + 1} · ${id === 'voice' && p.delivery === 'on_camera' ? 'Camera' : label}</span><span class="stage-state">${esc(info?.reason || '—')}</span></a>`;
  }).join('');
}

async function loadStageStates(project) {
  // T9.4 is optional. Discover it before fetching to avoid a missing-endpoint
  // browser error on older servers. OpenAPI is local and cached once.
  if (!state.apiSchema) state.apiSchema = api('/openapi.json').catch(() => ({}));
  const schema = await state.apiSchema;
  if (!schema.paths?.['/api/projects/{pid}/stages']) return;
  try {
    const result = await api(`/api/projects/${project.id}/stages`);
    if (state.project !== project) return;
    state.stageStates = {pid: project.id, items: Array.isArray(result) ? result : result.stages || []};
    if (state.stage === 'dashboard') {
      paintProjectShell();
      if ($('#tabbody')) paintDashboard();
    } else paintStageBar();
  } catch { /* Plain stage names are also supported on older servers. */ }
}

function paintJobsStrip() {
  const j = state.job;
  const rows = jobsSummary.filter(row => row.state === 'running' && row.id !== j?.id);
  if (j && !j.done) rows.unshift({kind: j.kind, elapsed: j.elapsed || 0,
    last_log_line: j.lines?.at(-1) || '', status: j.status});
  $('#jobs-status').innerHTML = rows.map(row => `<span class="jobs-strip-item">
    <span>${esc(row.kind)} · ${row.elapsed}s · ${esc(row.last_log_line)}</span>
    ${row.status ? `<span class="jobs-live-status">${esc(row.status)}</span>` : ''}
    </span>`).join('') || 'Idle';
}

for (const [id, label] of STAGES) {
  registerCommand({id: `stage-${id}`, label, group: 'Project stages',
    when: () => !!state.project, run: () => go(`#/p/${state.project.id}/${id}`)});
}

function paintChannelsIndex() {
  view.innerHTML = `<div class="row"><h1>Channels</h1><div class="spacer"></div>
    <button class="btn" onclick="newChannel()">New channel</button></div>
    ${(state.channels || []).map(c => `<p><a href="#/channels/${c.id}">${esc(c.name)}</a></p>`).join('')
      || '<p class="sub">No channels yet. Create a channel to keep videos together.</p>'}`;
}

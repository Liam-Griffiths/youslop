/* Studio shell; stage contents remain the existing tab implementations. */
const STAGES = [
  ['dashboard', 'Home'], ['script', 'Script'], ['create', 'Create'], ['voice', 'Voice'],
  ['edit', 'Edit'], ['publish', 'Publish'],
];
const projectStages = p => p?.kind === 'clip' ? [['clip','Clip'],['edit','Edit'],['publish','Publish']] : STAGES;
const LEGACY_STAGES = {plan: 'script/outline', visuals: 'edit/pictures',
  media: 'edit/pictures', cast: 'edit/cast', stage: 'edit/stage',
  record: 'voice', render: 'edit', thumb: 'publish/thumb'};

function canonicalHash(hash) {
  if (hash === '#/projects') return '#/';
  if (hash.startsWith('#/c/')) return hash.replace('#/c/', '#/channels/');
  const p = hash.match(/^#\/p\/([^/]+)(?:\/(\w+))?(?:\/(.*))?$/);
  if (!p) return hash;
  const nested = (p[3] || '').split('/').find(s => ['cast','stage'].includes(s));
  const stage = ['visuals','media'].includes(p[2]) && nested ? `edit/${nested}`
    : LEGACY_STAGES[p[2]] || ([...STAGES, ['clip']].some(([id]) => id === p[2])
      ? [p[2], p[3]].filter(Boolean).join('/') : 'dashboard');
  return `#/p/${p[1]}/${stage}`;
}

function stageTab(stage, subtab) {
  return {clip: 'clip', dashboard: 'dashboard', create: 'create', script: subtab === 'outline' ? 'plan' : subtab === 'shots' ? 'shots' : 'script',
    voice: 'record', edit: 'edit',
    publish: 'render'}[stage] || 'dashboard';
}

// Two groups: where videos live, then what they are made from. Help and
// Settings sit on the right, out of the way of the work.
const APP_NAV = [[['', 'Projects'], ['channels', 'Channels']], [['library', 'Library'], ['footage', 'Footage'], ['blocks', 'Blocks'], ['packs', 'Packs']]];
function paintAppNav() {
  const hash = location.hash || '#/';
  const on = id => id === '' ? hash === '#/' || hash === '#/projects'
    : id === 'channels' ? /^#\/(channels|c\/)/.test(hash) : hash.startsWith(`#/${id}`);
  const link = ([id, name]) => `<a href="#/${id}" ${on(id) ? 'aria-current="page"' : ''}>${name}</a>`;
  $('#app-nav').innerHTML = APP_NAV.map(group => group.map(link).join('')).join('<span class="nav-sep" aria-hidden="true"></span>');
  $('#app-tools').innerHTML = [['guide', 'How it works'], ['settings', 'Settings']].map(link).join('');
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
  $('#edit-picture-tools')?.closest('.modal').remove();
  $('#edit-stage-tools')?.closest('.modal').remove();
  state.editToolsRoute = '';
  restoreShellInspector();
  $('#app-nav').hidden = false;
  $('#app-tools').hidden = false;
  $('.shell-more').hidden = true;
  $('#project-bar').hidden = true;
  $('#stage-bar').hidden = true;
  $('.shell-more').open = false;
  const more = $('#project-more-actions');
  if (more) more.innerHTML = '';
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
  // Say nothing while things work; point at Settings only when writing cannot run.
  const broken = llm && llm.resolved === 'cli' && !llm.cli_found;
  $('#topbar-right').innerHTML = broken
    ? '<a class="pill warn" href="#/settings/writing">Writing model not set up</a>' : '';
}

function paintProjectShell() {
  const p = state.project;
  $('#app-nav').hidden = true;
  $('#app-tools').hidden = true;
  $('.shell-more').hidden = false;
  const bar = $('#project-bar');
  bar.hidden = false;
  const stages = projectStages(p);
  const i = stages.findIndex(([id]) => id === state.stage);
  const rows = state.stageStates?.pid === p.id ? state.stageStates.items : [];
  const next = state.stage === 'dashboard'
    ? stages.find(([id]) => id !== 'dashboard' && rows.some(r => r.id === id && r.status !== 'ready'))
    : stages.slice(i + 1).find(([id]) => id !== 'create');
  const channel = (state.channels || []).find(c => c.id === p.channel_id);
  const format = p.kind === 'clip' ? 'Clip' : FORMAT_INFO.find(f => f.key === p.style.format)?.label || p.style.format;
  const title = p.title || p.idea;
  const meta = `${channel?.name || (p.channel_id ? 'Channel' : 'Standalone')} · ${format} · ${p.aspect === 'portrait' ? '9:16' : p.aspect === 'square' ? '1:1' : '16:9'}`;
  const secondary = state.tab === 'edit'
    ? `<button type="button" class="btn sm project-secondary" onclick="tlPreviewBit()">Preview this bit</button>` : '';
  const more = $('#project-more-actions');
  if (more) more.innerHTML = secondary;
  bar.innerHTML = `<span class="project-title" title="${esc(title)}">/ ${esc(title)}</span>
    <span class="project-meta" title="${esc(meta)}">${esc(meta)}</span>
    <button type="button" class="btn sm" data-project-history="undo" disabled onclick="restoreProjectEdit('undo')" aria-keyshortcuts="Control+Z Meta+Z">Undo</button>
    <button type="button" class="btn sm" data-project-history="redo" disabled onclick="restoreProjectEdit('redo')" aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z">Redo</button>
    ${secondary}
    ${next ? `<a class="btn primary" href="#/p/${p.id}/${next[0]}">Next: ${esc(next[1])}</a>` : ''}`;
  $('#topbar-right').innerHTML = '';
  paintProjectHistory();
  paintStageBar();
}

function paintProjectHistory() {
  const p = state.project;
  const history = state.projectHistory?.pid === p?.id ? state.projectHistory : p?.edit_history;
  document.querySelectorAll('[data-project-history]').forEach(button => {
    const direction = button.dataset.projectHistory, label = history?.[direction];
    button.disabled = !label || projectHistoryBusy;
    const name = direction === 'undo' ? 'Undo' : 'Redo';
    button.title = label ? `${name}: ${label}` : `Nothing to ${direction}`;
  });
}

let projectHistoryBusy = false;
async function restoreProjectEdit(direction) {
  if (!state.project || projectHistoryBusy || state.rec.recording || TL.drag) return;
  projectHistoryBusy = true;
  paintProjectHistory();
  const pid = state.project.id;
  try {
    if (!(await scriptFlush())) return;
    if (typeof outlineFlush === 'function' && !(await outlineFlush())) return;
    await tlInspectorQueue;
    if (typeof binWrites !== 'undefined') await binWrites;
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
  finally { projectHistoryBusy = false; paintProjectHistory(); }
}

document.addEventListener('keydown', e => {
  if (e.defaultPrevented || e.isComposing || e.repeat || !(e.ctrlKey || e.metaKey) || e.altKey
      || e.key.toLowerCase() !== 'z' || !state.project
      || e.target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')) return;
  e.preventDefault();
  restoreProjectEdit(e.shiftKey ? 'redo' : 'undo');
});

// Create is optional and has no server readiness row: say what is there.
function createStageInfo(p) {
  const made = (p.graphics || []).filter(g => g.versions?.length), placed = made.filter(g => g.used_in?.length).length;
  return {status: '', reason: made.length ? `${made.length} graphic${made.length === 1 ? '' : 's'}${placed ? ` · ${placed} placed` : ''}` : 'Optional'};
}
function paintStageBar() {
  const p = state.project;
  if (!p) return;
  const bar = $('#stage-bar');
  bar.hidden = false;
  const stages = state.stageStates?.pid === p.id ? state.stageStates.items : [];
  bar.innerHTML = projectStages(p).map(([id, label], i) => {
    const info = id === 'create' ? createStageInfo(p) : stages.find(s => (s.id || s.stage || s.key) === id);
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
    last_log_line: j.lines?.at(-1) || '', status: j.status, writes: j.writes});
  $('#jobs-status').innerHTML = rows.map(row => `<span class="jobs-strip-item">
    <span>${esc(jobLabel(row))} · ${row.elapsed}s · ${esc(jobProgress(row))}</span>
    ${row.status ? `<span class="jobs-live-status">${esc(row.status)}</span>` : ''}
    </span>`).join('') || 'Idle';
}

for (const [id, label] of STAGES) {
  registerCommand({id: `stage-${id}`, label, group: 'Project stages',
    when: () => !!state.project, run: () => go(`#/p/${state.project.id}/${id}`)});
}

async function paintChannelsIndex() {
  if (!state.themes) { try { state.themes = await api('/api/themes'); } catch { state.themes = []; } }
  const list = state.channels || [];
  const theme = c => (state.themes || []).find(t => t.key === c.theme)?.label || '';
  const format = c => FORMAT_INFO.find(f => f.key === c.format)?.label || '';
  view.innerHTML = `<div class="channels-head"><div><h1>Channels</h1>
      <p class="sub">A channel keeps a series together: its look, voice, opening slate and end screen.</p></div>
      ${list.length ? '<button class="btn primary" onclick="newChannel()">New channel</button>' : ''}</div>
    ${list.length ? `<div class="channel-grid">${list.map(c => `
      <a class="channel-card" href="#/c/${c.id}">
        <div class="channel-card-art">${channelArt(c)}</div>
        <div class="channel-card-body">
          <h2>${esc(c.name)}</h2>
          <p class="sub">${esc(c.tagline || c.concept || 'No description yet.')}</p>
          <p class="channel-meta">${c.videos} video${c.videos === 1 ? '' : 's'}${theme(c) ? ` · ${esc(theme(c))}` : ''}${format(c) ? ` · ${esc(format(c))}` : ''}</p>
          ${c.intro_ready ? '' : '<span class="pill warn">Opening slate needs portraits</span>'}
        </div></a>`).join('')}</div>`
    : `<div class="channel-empty"><h2>No channels yet</h2>
        <p class="sub">Make one when you plan more than one video with the same look. Single videos work without a channel.</p>
        <button class="btn primary" onclick="newChannel()">New channel</button></div>`}`;
}

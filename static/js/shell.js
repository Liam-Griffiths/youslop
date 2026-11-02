/* Studio shell; stage contents remain the existing tab implementations. */
const STAGES = [
  ['plan', 'Plan'], ['script', 'Script'], ['voice', 'Voice'],
  ['visuals', 'Visuals'], ['edit', 'Edit'], ['publish', 'Review & publish'],
];
const LEGACY_STAGES = {media: 'visuals/media', cast: 'visuals/cast', stage: 'visuals/stage',
  record: 'voice', render: 'edit', thumb: 'publish/thumb'};

function canonicalHash(hash) {
  if (hash === '#/projects') return '#/';
  if (hash.startsWith('#/c/')) return hash.replace('#/c/', '#/channels/');
  const p = hash.match(/^#\/p\/([^/]+)(?:\/(\w+))?$/);
  if (!p) return hash;
  const stage = LEGACY_STAGES[p[2]] || (STAGES.some(([id]) => id === p[2]) ? p[2] : 'plan');
  return `#/p/${p[1]}/${stage}`;
}

function stageTab(stage, subtab) {
  return {plan: 'plan', script: 'script', voice: 'record',
    visuals: ['media', 'cast', 'stage'].includes(subtab) ? subtab : 'media',
    edit: 'edit', publish: 'render'}[stage] || 'script';
}

function paintAppNav() {
  const hash = location.hash || '#/';
  $('#app-nav').innerHTML = [['', 'Projects'], ['footage', 'Footage'], ['library', 'Library'],
    ['channels', 'Channels'], ['packs', 'Packs'], ['settings', 'Settings']].map(([id, name]) => {
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
  const backend = llm ? `Claude · ${llm.resolved}${llm.resolved === 'cli' && !llm.cli_found ? ' unavailable' : ''}` : 'Claude · unknown';
  $('#topbar-right').textContent = [backend,
    voice ? `Voice · ${voice.ready ? 'ready' : 'not ready'}` : 'Voice · unknown',
    settings ? `Scenes · ${settings.card_engine}` : 'Scenes · unknown'].join(' · ');
}

function paintProjectShell() {
  const p = state.project;
  $('#app-nav').hidden = true;
  const bar = $('#project-bar');
  bar.hidden = false;
  const i = STAGES.findIndex(([id]) => id === state.stage);
  const next = STAGES[i + 1];
  const channel = (state.channels || []).find(c => c.id === p.channel_id);
  const format = FORMAT_INFO.find(f => f.key === p.style.format)?.label || p.style.format;
  bar.innerHTML = `<span class="project-title">/ ${esc(p.title || p.idea.slice(0, 60))}</span>
    <span class="project-meta">${esc(channel?.name || (p.channel_id ? 'Channel' : 'Standalone'))} · ${esc(format)} · ${p.aspect === 'portrait' ? '9:16' : '16:9'}</span>
    ${state.stage === 'edit' ? `<button type="button" class="btn sm" onclick="tlPreviewBit()">Preview this bit</button>` : ''}
    ${state.stage === 'voice' ? `<button type="button" class="btn sm" onclick="openMicPanel()">Microphone setup</button>
      <button type="button" class="btn sm" onclick="setNarrator({mode:'ai'})">Draft voice settings</button>` : ''}
    ${next ? `<a class="btn primary" href="#/p/${p.id}/${next[0]}">Next: ${esc(next[1])}</a>` : ''}`;
  $('#topbar-right').innerHTML = '';
  paintStageBar();
}

function paintStageBar() {
  const p = state.project;
  if (!p) return;
  const bar = $('#stage-bar');
  bar.hidden = false;
  const stages = state.stageStates?.pid === p.id ? state.stageStates.items : [];
  bar.innerHTML = STAGES.map(([id, label], i) => {
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
    paintStageBar();
  } catch { /* Plain stage names are also supported on older servers. */ }
}

function paintJobsStrip() {
  const j = state.job;
  $('#jobs-status').textContent = j && !j.done
    ? `${j.kind} · ${j.elapsed || 0}s${j.lines?.length ? ' · ' + j.lines.at(-1) : ''}` : 'Idle';
}

function paintChannelsIndex() {
  view.innerHTML = `<div class="row"><h1>Channels</h1><div class="spacer"></div>
    <button class="btn" onclick="newChannel()">New channel</button></div>
    ${(state.channels || []).map(c => `<p><a href="#/channels/${c.id}">${esc(c.name)}</a></p>`).join('')
      || '<p class="sub">No channels yet. Create a channel to keep videos together.</p>'}`;
}

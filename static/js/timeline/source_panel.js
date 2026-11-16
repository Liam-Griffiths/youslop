// The former Add panel lives here; opening it only reads local indexes.
const TL_SOURCE_TABS = ['Materials','Library','Search','Blocks','3D','Graphics'];
let tlSourceView = {pid:'', tab:'Materials', items:[], query:'', choice:null};
async function tlSourcesMount() {
  const pid = TL.pid, panel = document.createElement('aside');
  if (tlSourceView.pid !== pid) tlSourceView = {pid, tab:'Materials', items:[], query:'', choice:null};
  panel.id = 'tl-sources'; panel.setAttribute('aria-label','Sources');
  panel.innerHTML = `<div class="row"><strong>Sources</strong><button type="button" class="btn sm ghost" data-close aria-label="Collapse sources">Close</button></div>
    <div class="tl-source-tabs" role="group" aria-label="Source type">${TL_SOURCE_TABS.map(t => `<button type="button" class="btn sm ghost" data-tab="${t}">${t}</button>`).join('')}</div>
    <label class="sr-only" for="tl-source-query">Find a source</label><input id="tl-source-query" type="search" placeholder="Find a source" value="${esc(tlSourceView.query)}">
    <div class="tl-source-results" tabindex="0" role="region" aria-label="Source results">
      <div class="tl-source-grid" data-source-grid></div><div data-source-tools></div>
      <p class="sub">Drop on a picture to replace; on + to insert; on Graphics to overlay. Double-click to use the selected picture.</p>
      <p data-source-status role="status"></p>
      <button type="button" class="btn sm" data-use>Use on selected picture</button>
    </div>`;
  $('.tl-main').prepend(panel);
  panel.querySelector('[data-close]').onclick = tlSourcesToggle;
  $('#tl-sources-toggle').onclick = tlSourcesToggle;
  TL.host.classList.toggle('sources-collapsed', !!TL.sourcesCollapsed);
  $('#tl-sources-toggle').setAttribute('aria-expanded', String(!TL.sourcesCollapsed));
  panel.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => {
    tlSourceView.tab = b.dataset.tab; tlSourceView.choice = null; tlSourcesPaint();
    panel.querySelector('.tl-source-results').scrollTop = 0;
  });
  $('#tl-source-query').oninput = e => {
    tlSourceView.query = e.target.value; tlSourcesPaint();
    panel.querySelector('.tl-source-results').scrollTop = 0;
  };
  $('#tl-source-query').onkeydown = e => {
    if (e.key === 'Enter' && tlSourceView.tab === 'Search') { e.preventDefault(); tlSourceSearch(); }
  };
  panel.querySelector('[data-use]').onclick = () => tlSourceUse(tlSourceView.choice);
  const view = tlSourceView;
  panel.querySelector('[data-source-status]').textContent = 'Loading…';
  const results = await Promise.allSettled([tlInsertSources(), api(`/api/projects/${pid}/bin`),
    api('/api/models'), api(`/api/projects/${pid}/graphics`)]);
  if (!panel.isConnected || tlSourceView !== view) return;
  const [items, materials, models, graphics] = results.map(r => r.status === 'fulfilled' ? r.value : null);
  view.items = [...(items || []), ...(materials?.items || []).filter(i => ['image','clip'].includes(i.kind)).map(i => ({
    label:i.title, thumb:i.thumb, tab:'Materials', meta:[i.shows,i.origin,i.licence,i.made,i.credit].filter(Boolean).join(' · '),
    payload:{kind:'picture', bin_id:i.id, seconds:4}})),
    ...(models || []).map(m => ({label:m.title, tab:'3D', thumb:`/api/models/${m.id}/thumb.jpg`, payload:{kind:'stage', model_id:m.id, seconds:4}})),
    ...state.project.slides.filter(s => s.shot?.intent).map(s => ({label:s.title || s.visual_note || s.id, tab:'3D', meta:'Existing shot',
      payload:{kind:'stage', source_slide:s.id, seconds:s.insert?.seconds || 4}})),
    ...(graphics?.graphics || []).map(g => ({label:g.title, tab:'Graphics', meta:g.versions?.length ? 'Designed' : 'Design in Create',
      payload:{kind:'graphic', graphic_id:g.id, seconds:g.seconds || 6}}))];
  view.error = results.some(r => r.status === 'rejected') ? 'Some sources failed to load. Reopen Sources to retry.' : '';
  tlSourcesPaint();
}
function tlSourcesToggle() {
  TL.sourcesCollapsed = !TL.sourcesCollapsed;
  TL.host.classList.toggle('sources-collapsed', TL.sourcesCollapsed);
  $('#tl-sources-toggle').setAttribute('aria-expanded', String(!TL.sourcesCollapsed));
  if (TL.sourcesCollapsed) $('#tl-sources-toggle').focus();
  else { $('#tl-sources').remove(); tlSourcesMount(); $('#tl-source-query').focus(); }
}
function tlSourcesPaint() {
  const panel = $('#tl-sources');
  if (!panel) return;
  const v = tlSourceView, tab = v.tab;
  panel.querySelector('[data-use]').textContent = 'Use on selected picture';
  panel.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tab === tab)));
  const tools = panel.querySelector('[data-source-tools]');
  tools.innerHTML = tab === 'Search' ? `<label for="tl-source-kind">Archive type</label>
      <select id="tl-source-kind">${[['image','Photos'],['video','Clips'],['reaction','Reaction GIFs']].map(([k,label]) =>
        `<option value="${k}" ${(v.searchKind || 'image') === k ? 'selected' : ''}>${label}</option>`).join('')}</select>
      <button type="button" class="btn sm" data-search ${v.searching ? 'disabled' : ''}>Search archives</button>`
    : tab === 'Graphics' ? `<a class="btn sm ghost" href="#/p/${TL.pid}/create">Open Create</a>`
    : tab === '3D' ? `<button type="button" class="btn sm ghost" data-intake>Model intake…</button><a class="btn sm ghost" href="#/p/${TL.pid}/edit/cast">Cast and models</a><a class="btn sm ghost" href="#/p/${TL.pid}/edit/stage">Shot planning</a>`
    : tab === 'Blocks' ? '<button type="button" class="btn sm ghost" data-browse>Browse blocks…</button>' : '';
  if (tools.querySelector('[data-search]')) {
    tools.querySelector('[data-search]').onclick = tlSourceSearch;
    tools.querySelector('select').onchange = e => { v.searchKind = e.target.value; };
  }
  if (tools.querySelector('[data-browse]')) tools.querySelector('[data-browse]').onclick = () => tlInsertBlock(tlInsertNearest());
  if (tab === '3D') tools.querySelector('[data-intake]').onclick = () => {
    const id = v.choice?.model_id;
    if (id) openModelIntake(id); else toast('Select a model for intake.', true);
  };
  if (['3D','Graphics'].includes(tab)) {
    tools.insertAdjacentHTML('beforeend', `<label for="tl-source-seconds">Insert length (seconds)</label>
      <input id="tl-source-seconds" type="number" min="0.05" step="0.05" value="${esc(v.choice?.seconds ?? 4)}">
      <button type="button" class="btn sm" data-insert-source>Insert at nearest boundary</button>`);
    const length = tools.querySelector('#tl-source-seconds');
    // The box shows the chosen source's own length (a graphic's is set in
    // Create); editing it changes only that source.
    length.oninput = () => {
      if (v.choice && ['stage','graphic'].includes(v.choice.kind) && Number(length.value) > 0) v.choice.seconds = Number(length.value);
    };
    tools.querySelector('[data-insert-source]').onclick = () => {
      const point = tlInsertNearest();
      if (!v.choice) return toast('Choose a source first.', true);
      if (point && tlCanEdit([], ['pictures'])) tlInsertSave('', {...v.choice, after:point.after});
    };
  }
  const items = tab === 'Search' ? v.archive || tlSourceArchiveItems() : v.items.filter(i => i.tab === tab
    && `${i.label} ${i.meta || ''}`.toLowerCase().includes(v.query.toLowerCase()));
  const grid = panel.querySelector('[data-source-grid]');
  tlInsertSourceList(grid, items, payload => { v.choice = payload; });
  grid.querySelectorAll('[data-source]').forEach(b => {
    const item = items[+b.dataset.source];
    b.draggable = true;
    b.ondblclick = () => tlSourceUse(item.payload);
    b.setAttribute('aria-pressed', String(v.choice === item.payload));
    b.onclick = () => {
      v.choice = item.payload;
      grid.querySelectorAll('button').forEach(n => n.setAttribute('aria-pressed', String(n === b)));
      const length = $('#tl-source-seconds');
      if (length && item.payload.seconds) length.value = item.payload.seconds;
    };
  });
  if (tab === 'Search' && !items.length) grid.innerHTML = '<p>Select a picture, enter a query and search archives. Results can replace pictures or be inserted at +.</p>';
  panel.querySelector('[data-source-status]').textContent = tab === 'Search' ? v.searchStatus || v.error || '' : v.error || '';
}
function tlSourceArchiveItems(sid = null, candidates = null) {
  const p = state.project;
  sid ||= (p.picture_runs || []).find(r => r.includes(TL.selection?.sid))?.[0] || TL.selection?.sid;
  return (candidates || p.slides.find(s => s.id === sid)?.candidates || []).filter(c =>
    !['library','materials','footage','local'].includes(c.provider)).map(c => ({
      label:c.title || c.provider, thumb:thumbUrl(c), meta:[c.provider,c.license].filter(Boolean).join(' · '),
      payload:{kind:'picture', source_slide:sid, candidate_id:c.id, seconds:4}}));
}
async function tlSourceSearch() {
  const v = tlSourceView, pid = TL.pid, sel = tlSourcePicture(), query = v.query.trim();
  if (!sel || !tlCanEdit([sel], ['pictures']) || v.searching) return;
  if (!query) { $('#tl-source-query').focus(); return; }
  const sid = (state.project.picture_runs || []).find(r => r.includes(sel.sid))?.[0] || sel.sid;
  v.searching = true; v.searchStatus = 'Searching archives…'; tlSourcesPaint();
  // Searching explicitly gathers candidates; opening Sources never searches.
  const result = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    if (!tlCanEdit([sel], ['pictures'])) return;
    const r = await api(`/api/projects/${pid}/slides/${sid}/search`, {method:'POST',
      body:JSON.stringify({query, kind:v.searchKind || 'image'})});
    if (TL.pid !== pid || state.project?.id !== pid || tlSourceView !== v) return;
    const s = state.project.slides.find(s => s.id === sid);
    if (s) s.candidates = r.slide.candidates;
    v.archive = tlSourceArchiveItems(sid, r.results); v.choice = null;
    v.searchStatus = `${v.archive.length} results for “${query}”`;
    tlInspector();
  });
  tlInspectorQueue = result.catch(() => {});
  try { await result; } catch (e) { v.searchStatus = e.message; }
  finally { v.searching = false; if (tlSourceView === v && TL.pid === pid) tlSourcesPaint(); }
}
function tlSourcePicture() {
  const sel = TL.selection;
  if (!TL.section && TL.selections?.length === 1 && ['picture','paragraph'].includes(sel?.kind)) return sel;
  toast('Select one picture or paragraph first.', true);
}
function tlSourceUse(payload, selection = null) {
  if (!payload) return toast('Choose a source first.', true);
  payload = structuredClone(payload);
  const sel = selection || tlSourcePicture();
  if (!sel || !tlCanEdit([sel], ['pictures'])) return;
  const pid = TL.pid;
  const result = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    if (!tlCanEdit([sel], ['pictures'])) return;
    try {
      tlPause();
      const s = state.project.slides.find(s => s.id === sel.sid);
      if (!s || s.on_camera) throw Error('Choose a non-camera picture paragraph.');
      if (!['picture','block','clip','stage','graphic'].includes(payload.kind)) throw Error('Choose a picture source.');
      const project = await api(`/api/projects/${pid}/slides/${s.id}/picture-source`, {
        method:'POST', body:JSON.stringify(payload), editLabel:'replace picture', editGesture:crypto.randomUUID()});
      if (TL.pid === pid && state.project?.id === pid) { state.project = project; await tlRefresh(); tlInspector(); }
    } catch (error) { toast(error.message, true); }
  });
  tlInspectorQueue = result.catch(() => {}); return result;
}

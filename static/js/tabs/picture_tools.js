/* Resolve through the same picture-group lead and precedence as app/kinds.py. */
function pictureKind(s, p = state.project) {
  const lead = (p.picture_runs || []).find(r => r.includes(s.id))?.[0];
  s = p.slides.find(q => q.id === lead) || s;
  return s.on_camera ? 'camera' : s.cues?.blocks?.length ? 'block' : s.kind || p.style.format;
}
function pictureKindLabel(kind, s = null) {
  const names = {kenburns:'Documentary photo', essay:'Essay slide', board:'Board', stage:'3D',
    flameboat:'Flameboat', casefile:'Casefile', loudmouth:'Loudmouth', groupchat:'Group Chat', ticker:'Ticker', camera:'Camera', 'custom:graphic':'Create graphic'};
  if (kind === 'block' && !s) return 'Block';
  if (kind === 'block') return 'Block: ' + (s?.cues?.blocks?.[0]?.block || '').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
  return names[kind] || (state.slideStyles || []).find(x => 'custom:'+x.id === kind)?.name || kind;
}
function visualKind(s) { return pictureKind(s); }
function kindControl(s) {
  return `<button type="button" class="btn sm ghost visual-chip visual-kind" data-kind="${esc(pictureKind(s))}"
    aria-label="Kind for ${esc(s.title || s.id)}" onclick="openPictureKind('${s.id}')">${esc(pictureKindLabel(pictureKind(s),s))}</button>`;
}
async function openPictureKind(sid) {
  await ensureSlideStyles();
  const p = state.project;
  sid = (p.picture_runs || []).find(r => r.includes(sid))?.[0] || sid;
  const s = p.slides.find(q => q.id === sid);
  if (!s) return;
  if (state.tab === 'media') {
    state.visualSelection = {pid:p.id,sid};
    delete state.visualSource;
    paintMedia();
  }
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.setAttribute('role','dialog');
  wrap.setAttribute('aria-modal','true');
  wrap.setAttribute('aria-label','Kind of picture');
  const groups = [['Pictures',['kenburns','essay']], ['Drawn',['board','flameboat','casefile','loudmouth','groupchat','ticker']],
    ['3D',['stage']], ['Your styles',(state.slideStyles || []).map(x => 'custom:'+x.id)]];
  const choice = (k, label) => `<button type="button" class="btn sm" data-picture-kind="${esc(k)}" ${s.on_camera ? 'disabled' : ''} aria-pressed="${pictureKind(s) === 'block' ? k === 'block' : (s.kind || '') === k}">${esc(label)}</button>`;
  wrap.innerHTML = `<div class="modal-box"><h2>Kind of picture</h2><p>Shift-click picture groups to select a range.</p>
    ${s.on_camera ? '<p>The camera take supplies this picture. Change its layout in Edit.</p>' : ''}
    ${choice('', 'Style default ('+pictureKindLabel(p.style.format)+')')}
    ${groups.filter(([, keys]) => keys.length).map(([name, keys]) => `<h3>${name}</h3><div class="row">${keys.map(k => choice(k,pictureKindLabel(k))).join('')}</div>`).join('')}
    <h3>Blocks</h3><div class="row">${choice('block','Block…')}</div><p role="status"></p><button type="button" class="btn ghost" data-close>Close</button></div>`;
  document.body.appendChild(wrap);
  wrap.querySelector('[data-close]').onclick = () => wrap.remove();
  wrap.onclick = e => { if (e.target === wrap) wrap.remove(); };
  wrap.onkeydown = e => { if (e.key === 'Escape') wrap.remove(); };
  wrap.querySelectorAll('[data-picture-kind]').forEach(b => b.onclick = async () => {
    try {
      const range = (state.tab !== 'edit' || $('#edit-picture-tools')) && state.visualRange?.pid === p.id && state.visualRange.ids.includes(sid) ? state.visualRange.ids : [sid];
      const ids = [...new Set(range.flatMap(id => (p.picture_runs || []).find(r => r.includes(id)) || [id]))];
      if (b.dataset.pictureKind === 'block') {
        wrap.remove();
        return openBlockPicker(p.id,sid,s.cues?.blocks?.[0] || s.cues?.inactive_blocks?.[0],ids);
      }
      for (const id of ids) {
        const q = p.slides.find(x => x.id === id), patch = {kind:b.dataset.pictureKind};
        if (q.on_camera) continue;
        if (q.cues?.blocks?.length) patch.cues = {blocks:[],inactive_blocks:q.cues.blocks};
        if (!await saveSlide(id,patch)) throw Error('Could not save the kind.');
      }
      wrap.remove();
      state.project = await api(`/api/projects/${p.id}`);
      delete state.visualSource;
      if (state.tab === 'edit') await tlRefreshProject();
      else await render();
    } catch(e) { wrap.querySelector('[role=status]').textContent = e.message; }
  });
  wrap.querySelector('button').focus();
}
function visualFinding(s) {
  const k = pictureKind(s);
  if (isCut(k) && !s.cues?.[k]?.length) return 'P1 · No cues yet. Plan cues or edit this paragraph’s cues.';
  if (k === 'board' && !s.board_lead && !s.board_points?.length) return 'P1 · No board text yet. Plan boards or edit this board.';
  if (['kenburns','essay'].includes(k) && !s.candidates?.some(c => c.id === s.chosen_id && c.local_path)) return 'P1 · Needs a picture.';
  return '';
}
function visualKindSettings(groups) {
  const present = [...new Set(groups.map(g => pictureKind(g.s)))];
  return `<details><summary>Kind settings</summary>${present.map(k => `<h3>${esc(pictureKindLabel(k))}</h3>${k === 'board'
    ? boardKnobs(state.project.style,'saveStyle') : isCut(k) ? cutKnobs({...state.project.style,format:k},'saveStyle')
    : '<p>Controls are edited on each picture.</p>'}`).join('')}</details>`;
}

function visualSources(p, s = null) {
  const tabs = visualFormatSources(p, s);
  return state.visualHasFootage && !(s && pictureKind(s,p) === 'block') && !['Board','Cues','3D','Layout','Your style'].includes(tabs[0]) ? ['Footage', ...tabs.filter(t => t !== 'Footage')] : tabs;
}

function visualFormatSources(p, s = null) {
  const kind = s ? pictureKind(s,p) : p.style.format;
  if (kind.startsWith('custom:')) return ['Your style','Archive','Footage','Library','Scenes','Upload'];
  if (kind === 'block') return ['Scenes','Archive','Footage','Library','Upload'];
  if (kind === 'board') return ['Board','Archive','Library','Scenes','Upload'];
  if (isCut(kind) && s) return ['Cues',...(p.aspect === 'portrait' ? ['Blocks'] : []),'Archive','Library','Scenes','Upload'];
  if (s ? s.on_camera || p.delivery === 'on_camera' && !s.kind : p.delivery === 'on_camera' || p.slides.some(s => s.on_camera))
    return ['Layout', 'Footage', 'Screens', 'Library', 'Scenes', 'Archive', 'Upload'];
  if (isStage(kind)) return ['3D', 'Archive', 'Footage', 'Library', 'Scenes', 'Upload'];
  if (p.aspect === 'portrait') return ['Blocks', 'Archive', 'Library', 'Scenes', 'Upload'];
  if (['kenburns','essay'].includes(kind)) return ['Footage', 'Archive', 'Library', 'Scenes', 'Upload'];
  return ['Archive', 'Library', 'Scenes', 'Upload'];
}

function selectVisual(sid, event = null) {
  const p = state.project, ids = (p.picture_runs || p.slides.map(s => [s.id])).map(r => r[0]);
  const anchor = state.visualSelection?.pid === p.id ? state.visualSelection.sid : sid;
  const a = ids.indexOf(anchor), b = ids.indexOf(sid);
  state.visualRange = {pid:p.id, ids:event?.shiftKey && a >= 0 && b >= 0 ? ids.slice(Math.min(a,b),Math.max(a,b)+1) : [sid]};
  if (state.visualSelection?.sid !== sid) delete state.visualSource;
  state.visualSelection = {pid: state.project.id, sid};
  paintMedia();
}

function selectVisualSource(source) {
  state.visualSource = {pid: state.project.id, source};
  paintMedia();
}

// Shared editors repaint their caller; no standalone Visuals workspace remains.
function paintMedia() {
  if (state.tab === 'shots') return paintScriptShots();
  if (state.tab === 'edit') {
    const toolbar = $('#edit-picture-toolbar');
    if (toolbar) toolbar.innerHTML = editPictureToolbar();
    paintEditPictureTools();
    if ($('#tl-inspector')) return tlInspector();
  }
}
function visualGroups(p = state.project) {
  const byId = Object.fromEntries(p.slides.map((s,i) => [s.id,{s,i}]));
  return (p.picture_runs || p.slides.map(s => [s.id])).filter(r => byId[r[0]]).map(ids => ({
    ids, ...byId[ids[0]], seconds:ids.reduce((n,id) => n+(byId[id]?.s.take?.duration || 0),0)}));
}
function editPictureToolbar() {
  const p = state.project, groups = visualGroups(p);
  const kinds = {};
  groups.forEach(g => { const k = visualKind(g.s); kinds[k] = (kinds[k] || 0) + g.seconds; });
  // Unvoiced projects have no real durations: show counts, never invented timings.
  const total = groups.reduce((n,g) => n + g.seconds, 0);
  if (!total) groups.forEach(g => { const k = visualKind(g.s); kinds[k] = (kinds[k] || 0) + 1; });
  const denominator = total || groups.length || 1;
  const fallbackRule = isStage(p.style.format) ? '3D for how it works, archive for who and when, scenes for numbers.'
    : p.delivery === 'on_camera' ? 'Face for opinion, cutaway when you describe a place or a thing.'
    : p.aspect === 'portrait' ? 'Draw numbers with blocks; keep text clear of the Shorts UI.'
    : p.style.format === 'kenburns' ? 'Footage for what you shot, archive for context, scenes for numbers.'
    : 'Use the format’s drawing; archive for context, scenes for numbers.';
  const rule = state.stageStates?.pid === p.id ? state.stageStates.items.find(s => s.id === 'edit')?.rule || fallbackRule : fallbackRule;
  const has = k => groups.some(g => pictureKind(g.s) === k);
  const mixBar = `<div class="visual-mix-bar" aria-hidden="true">${Object.entries(kinds).map(([k,n]) =>
    `<span class="visual-kind" data-kind="${esc(k)}" style="flex:${n}"></span>`).join('')}</div>`;
  // One menu for everything that acts on the whole video; the selected picture's
  // own tools stay in the inspector.
  return `<details class="tl-more tl-menu tl-whole"><summary class="btn sm ghost">Whole video</summary><div>
    <h4>Pictures</h4>
    <button type="button" class="btn sm ghost" onclick="gatherMedia(visualGroups().filter(g=>!g.s.chosen_id).map(g=>g.s.id))">Fill the empty pictures</button>
    ${state.visualHasFootage ? '<button type="button" class="btn sm ghost" onclick="fillVisualFootage()">Fill the rest from footage</button>' : ''}
    <button type="button" class="btn sm ghost" onclick="gatherMedia()">Search everything again</button>
    ${has('board') ? `<button type="button" class="btn sm ghost" onclick="planBoards(false)">Write the boards</button><button type="button" class="btn sm ghost" onclick="planBoards(true)">Rewrite all boards</button>` : ''}
    ${groups.some(g => isCut(pictureKind(g.s))) ? `<button type="button" class="btn sm ghost" onclick="planCues(false)">Write the cues</button><button type="button" class="btn sm ghost" onclick="planCues(true)">Rewrite all cues</button>` : ''}
    ${isStage(p.style.format) || groups.some(g => isStage(pictureKind(g.s))) ? '<button type="button" class="btn sm ghost" onclick="stagePlan()">Plan all 3D shots</button>' : ''}
    <label class="tl-menu-row"><span>A new picture every</span><select style="width:auto" onchange="savePictureEvery(+this.value)">
      ${[1,2,3,4,5,6].map(n => `<option value="${n}" ${n === (p.style.picture_every || 1) ? 'selected' : ''}>${n === 1 ? 'paragraph' : n+' paragraphs'}</option>`).join('')}</select></label>
    <label class="tl-menu-row" title="When two archive results are equally relevant, take the public domain or CC0 one"><span>Prefer public domain</span><input type="checkbox" style="width:auto"
      ${p.prefer_public_domain ? 'checked' : ''} onchange="saveProject({prefer_public_domain:this.checked})"></label>
    <h4>Look</h4>
    <button type="button" class="btn sm ghost" onclick="openStylePicker('project')">Change style…</button>
    <button type="button" class="btn sm ghost" onclick="openProjectLook()">Look and graphic theme…</button>
    ${visualKindSettings(groups)}
    <h4>Mix</h4>
    <div class="visual-mix">${mixBar}
      <span class="mono">${Object.entries(kinds).map(([k,n]) => `<span class="visual-chip visual-kind" data-kind="${esc(k)}">${esc(pictureKindLabel(k))} ${groups.filter(g => pictureKind(g.s) === k).length} · ${Math.round(100*n/denominator)}%</span>`).join(' · ')}${total ? ' · by voiced duration' : ' · by group count (unvoiced)'}</span>
      <span class="visual-rule">Style rule: ${esc(rule)}</span>
    </div>
    <h4>Also</h4>
    <button type="button" class="btn sm ghost" onclick="tlLayerSuggest(this)">Suggest layers</button>
    ${p.slides.some(s => s.on_camera) ? `<button type="button" class="btn sm ghost" onclick="tlCameraAuto()">Auto-edit camera paragraphs</button>
    <button type="button" class="btn sm ghost" onclick="tlCameraAuto('',true)">Undo auto-edit</button>` : ''}
    <button type="button" class="btn sm ghost" onclick="saveProjectFile()" title="Everything in this video as one file, to open on another computer">Save project file…</button>
    </div></details>`;
}
function openEditPictureTools(sid = '') {
  state.visualSelection = {pid:state.project.id, sid:sid || TL.selection?.sid || tlSegAt(TL.cur)?.lead};
  delete state.visualSource; delete state.visualRange;
  tlModal(() => {
    const wrap = document.createElement('div'); wrap.className = 'modal';
    wrap.setAttribute('role','dialog'); wrap.setAttribute('aria-modal','true'); wrap.setAttribute('aria-label','Picture tools');
    wrap.innerHTML = '<div class="modal-box wide"><div class="edit-tool-head"><h2>Picture tools</h2><button type="button" class="btn sm ghost" data-close>Close</button></div><div id="edit-picture-tools"></div></div>';
    const focus = document.activeElement;
    const close = () => { wrap.remove(); focus?.isConnected && focus.focus(); };
    wrap.querySelector('[data-close]').onclick = close;
    wrap.onclick = e => { if (e.target === wrap) close(); };
    wrap.onkeydown = e => editToolKey(e,wrap,close);
    document.body.appendChild(wrap); paintEditPictureTools(); wrap.querySelector('[data-close]').focus();
  });
}
function selectEditPictureGroups(control) {
  const ids = [...control.selectedOptions].map(o => o.value);
  if (!ids.length) return;
  state.visualRange = {pid:state.project.id,ids};
  state.visualSelection = {pid:state.project.id,sid:ids.at(-1)};
  delete state.visualSource; paintMedia();
}
function paintEditPictureTools() {
  const body = $('#edit-picture-tools');
  if (!body) return;
  const p = state.project, groups = visualGroups(p);
  const group = groups.find(g => g.ids.includes(state.visualSelection?.sid)) || groups[0];
  if (!group) { body.innerHTML = '<p>Write the script to choose pictures.</p>'; return; }
  const tabs = visualSources(p,group.s);
  const source = state.visualSource?.pid === p.id && tabs.includes(state.visualSource.source) ? state.visualSource.source : tabs[0];
  const byId = Object.fromEntries(p.slides.map((s,i) => [s.id,{s,i}]));
  body.innerHTML = `<label>Picture groups · Shift-click for a range<select multiple size="3" onchange="selectEditPictureGroups(this)">${groups.map(g =>
    `<option value="${g.s.id}" ${g === group || state.visualRange?.pid === p.id && state.visualRange.ids.includes(g.s.id) ? 'selected' : ''}>¶${g.i+1} · ${esc(g.s.title || g.s.visual_note || g.s.id)}</option>`).join('')}</select></label>
    ${visualPreview(group,byId)}<div class="visual-source-tabs" role="group" aria-label="Picture tools">
    ${tabs.map(t => `<button type="button" class="btn sm ghost" aria-pressed="${t === source}" onclick="selectVisualSource('${t}')">${t}</button>`).join('')}</div>
    <div class="visual-source-body">${visualSourcePanel(group.s,source)}</div>`;
  loadVisualFootage(p);
  if (['Scenes','Blocks','Screens'].includes(source) || group.s.cues?.blocks?.length) loadVisualBlocks(p,group.s);
}

function visualPreview(g, byId) {
  const p = state.project, s = g.s, c = s.candidates.find(c => c.id === s.chosen_id);
  const kind = pictureKind(s), drawn = isCut(kind) || kind === 'board';
  return `<div class="mono">Picture ${g.i+1} · ¶${g.ids.map(id => byId[id].i+1).join(', ')} · ${g.seconds ? fmtTime(g.seconds)+' from the takes' : 'unvoiced'}</div>
    <h2>${esc(s.title || s.beat || 'Choose a picture')}</h2>${kindControl(s)}
    <p role="status">${esc(visualFinding(s))}</p>
    <div class="visual-frame ${p.aspect === 'portrait' ? 'portrait' : p.aspect === 'square' ? 'square' : ''}">
      ${s.cues?.blocks?.length && !s.on_camera ? visualBlockStill(p, s) : c && !drawn && !s.on_camera ? `<img src="${thumbUrl(c)}" loading="lazy" alt="${esc(c.title || 'Selected picture')}"
        style="object-position:${(c.focal?.[0] ?? .5)*100}% ${(c.focal?.[1] ?? .5)*100}%">`
        : `<p>${s.on_camera ? 'Camera take · layouts and jump cuts in Edit' : drawn ? 'Drawn from the narration · preview on click' : pictureKind(s) === 'stage' ? '3D shot · open the shot editor to inspect' : 'Choose a source to fill this picture.'}</p>`}
      <div class="visual-graphics">${g.ids.map(id => `<span class="visual-graphic-paragraph">${(byId[id].s.overlays || []).map(o => `<button type="button" class="btn sm visual-chip" data-graphic="${esc(o.id)}" onclick="openGraphicEdit('${id}',this.dataset.graphic)">¶${byId[id].i+1} · ${esc(o.vars.title || o.block_id)}</button>`).join('')}</span>`).join('')}</div>
    </div>
    <div class="row">${g.ids.filter(id => !byId[id].s.on_camera && !isCut(pictureKind(byId[id].s))).map(id => `<button type="button" class="btn sm" onclick="openGraphicPicker('${id}')">Add graphic${g.ids.length > 1 ? ' · ¶'+(byId[id].i+1) : ''}</button>`).join('')}<button type="button" class="btn sm" onclick="previewBit('${s.id}')">Preview this bit · ¼ size</button>
      ${c ? `<button type="button" class="btn sm ghost" onclick="setSlideFocal('${s.id}','${c.id}')">${c.focal?.length === 2 ? 'Focus set · change' : 'Set focus point'}</button>
        ${c.kind === 'video' ? `<button type="button" class="btn sm ghost" onclick="playClipFor('${s.id}','${c.id}')">Play source clip</button>` : ''}` : ''}
      <label><input type="checkbox" ${s.locked_media ? 'checked' : ''} onchange="saveSlide('${s.id}',{locked_media:this.checked})"> Keep on re-plan</label></div>
    ${c ? `<p class="mono">${esc(c.provider)} · ${c.width || '?'}×${c.height || '?'} · ${esc(c.license || '')}
      ${c.source_page ? `<a href="${esc(c.source_page)}" target="_blank" rel="noopener">Source</a>` : ''}</p>` : ''}
    <p>${esc(g.ids.map(id => byId[id].s.narration).join(' '))}</p>
    <p class="sub">${esc(s.visual_note || '')}</p>
    ${g.i > 0 ? `<button type="button" class="btn sm ghost" onclick="setPictureMode('${s.id}','${s.picture_mode === 'new' ? 'auto' : 'hold'}')">${s.picture_mode === 'new' ? 'Always its own · use automatic grouping' : 'Hold the last picture'}</button>` : ''}
    ${g.ids.slice(1).map(id => `<div class="row"><span class="mono">¶${byId[id].i+1} holds this picture</span>
      <button type="button" class="btn sm ghost" onclick="setPictureMode('${id}','new')">Give this one its own picture</button>
      ${pictureKind(s) === 'board' ? `<button type="button" class="btn sm ghost" onclick="openBoardEditor('${id}')">Edit its board</button>` : ''}
      ${isCut(pictureKind(s)) ? `<button type="button" class="btn sm ghost" onclick="openCueEditor('${id}')">Edit its cues</button>` : ''}</div>`).join('')}`;
}

function visualSourcePanel(s, source) {
  const p = state.project;
  if (source === 'Your style') return `<h3>${esc(pictureKindLabel(pictureKind(s)))}</h3><button type="button" class="btn sm" onclick="openCustomEditor('${s.id}')">Edit this slide</button>`;
  if (source === 'Board') return `<h3>Board</h3><button type="button" class="btn sm" onclick="openBoardEditor('${s.id}')">Edit the board</button>`;
  if (source === 'Cues') return `<h3>${esc(pictureKindLabel(pictureKind(s)))}</h3><button type="button" class="btn sm" onclick="openCueEditor('${s.id}')">Edit the cues</button>`;
  if (source === 'Footage') {
    suggestVisualFootage(p, s);
    const clips = s.candidates.filter(c => c.provider === 'footage');
    return `<a class="btn sm ghost" href="#/footage">Open footage logger</a>
      <label class="field"><span>Search footage</span><input type="search" id="visual-query" value="${esc(s.visual_note || s.narration || s.title || '')}" onkeydown="if(event.key==='Enter') searchVisual('${s.id}','Footage')"></label>
      <button type="button" class="btn sm" onclick="searchVisual('${s.id}','Footage')">Search</button>
      <div id="visual-search-status" role="status">${esc(state.visualFootageError || '')}</div>
      <div class="visual-results">${clips.map(c => `<button type="button" class="btn ghost" aria-pressed="${c.id === s.chosen_id}" onclick="choose('${s.id}','${c.id}')">
        <img src="${thumbUrl(c)}" loading="lazy" alt=""><span>${esc(c.title)}</span>
        <small class="mono">${c.in_s.toFixed(3)}–${c.out_s.toFixed(3)} s</small>
        <span>${(c.labels || []).map(l => `<span class="visual-chip visual-kind" data-kind="footage">${esc(l)}</span>`).join(' ')}</span>
      </button>`).join('') || '<p>No footage suggestions yet. Search or import a shoot.</p>'}</div>`;
  }
  if (source === '3D') return `<h3>Cast and shot options</h3>${(p.cast || []).map(c => `<p>${esc(c.subject)} · ${esc(c.mode)}</p>`).join('')}
    <a class="btn sm" href="#/p/${p.id}/edit/cast">Edit cast and named parts</a>
    <a class="btn sm" href="#/p/${p.id}/edit/stage">Shots and solver checks</a>
    ${s.shot?.intent ? `<button type="button" class="btn sm ghost" onclick="openShot('${s.id}')">Open this shot</button>` : ''}`;
  if (source === 'Layout') return `<h3>Camera layouts and jump cuts</h3><p>Full face, split, cutaway over voice and picture in picture are edited on the camera lanes. Removed parts stay in the take.</p>
    <button type="button" class="btn sm" onclick="openVisualEdit('${s.id}')">Edit this take’s layout and cutaways</button>`;
  if (['Scenes','Blocks','Screens'].includes(source)) return `<h3>${source}</h3>
    ${!s.on_camera ? visualBlockPanel(p, s) : ''}
    <button type="button" class="btn sm ghost" onclick="openDiagramEditor('${s.id}')">Draw a diagram</button>
    <button type="button" class="btn sm ghost" onclick="openCustomEditor('${s.id}')">Design a slide</button>
    <button type="button" class="btn sm ghost" onclick="openVisualEdit('${s.id}')">Open Edit · variables and timeline</button>
    <a class="btn sm ghost" href="#/blocks">Browse reusable blocks</a>
    ${!s.on_camera ? `<button type="button" class="btn sm" onclick="openBlockPicker('${p.id}','${s.id}')">Choose a block for this paragraph</button>` : ''}
    ${pictureKind(s) === 'board' ? `<button type="button" class="btn sm" onclick="openBoardEditor('${s.id}')">Edit the board</button>` : ''}
    ${isCut(pictureKind(s)) ? `<button type="button" class="btn sm" onclick="openCueEditor('${s.id}')">Edit the cues</button>` : ''}`;
  if (source === 'Upload') return `<label class="field"><span>Upload a picture or clip</span><input type="file" accept="image/*,video/*" onchange="uploadMedia('${s.id}',this.files[0])"></label>`;
  const candidates = s.candidates.filter(c => source === 'Library' ? c.provider === 'library' : !['library', 'footage'].includes(c.provider));
  return `<label class="field"><span>Search ${source.toLowerCase()}</span><input type="search" id="visual-query" value="${esc(s.queries?.[0] || s.visual_note || s.title || '')}" onkeydown="if(event.key==='Enter') searchVisual('${s.id}','${source}')"></label>
    <button type="button" class="btn sm" onclick="searchVisual('${s.id}','${source}')">Search</button>
    ${source === 'Library' ? `<button type="button" class="btn sm" onclick="pickVisualLibrary('${s.id}')">Choose from Library…</button>` : ''}
    <button type="button" class="btn sm ghost" onclick="toggleKind('${s.id}')">Want ${s.prefer_kind === 'image' ? 'a clip' : 'a photo'}</button>
    <button type="button" class="btn sm ghost" onclick="openMediaSearch('${s.id}')">Full search picker</button>
    <button type="button" class="btn sm ghost" onclick="openMapPicker('${s.id}')">Get a map</button>
    <div id="visual-search-status" role="status"></div><div class="visual-results">${candidates.map(c => `<button type="button" class="btn ghost" aria-pressed="${c.id === s.chosen_id}" onclick="choose('${s.id}','${c.id}')">
      <img src="${thumbUrl(c)}" loading="lazy" alt=""><span>${esc(c.title || c.provider)}</span><small class="mono">${esc(c.provider)} · ${c.kind === 'video' ? 'clip' : 'photo'}${c.weak_match ? ' · Weak match' : ''}</small></button>`).join('') || '<p>No gathered matches. Search to find options.</p>'}</div>`;
}

async function searchVisual(sid, source) {
  const p = state.project, query = $('#visual-query').value.trim();
  if (!query) return;
  const status = $('#visual-search-status');
  status.textContent = `Searching ${source.toLowerCase()}…`;
  try {
    const r = await api(`/api/projects/${p.id}/slides/${sid}/search`, {method:'POST', body:JSON.stringify({query,
      kind:p.slides.find(s => s.id === sid).prefer_kind, source:source.toLowerCase()})});
    const slide = p.slides.find(s => s.id === sid);
    if (source === 'Footage') slide.candidates = r.slide.candidates;
    else Object.assign(slide, r.slide);
    if (state.project === p && ['media','edit'].includes(state.tab)) {
      if (state.tab === 'edit') await tlRefresh();
      paintMedia();
    }
  } catch(e) { status.textContent = e.message; }
}

function pickVisualLibrary(sid) {
  const p = state.project, slide = p.slides.find(s => s.id === sid);
  openLocalMediaPicker(slide.prefer_kind === 'video' ? 'video' : 'image', async asset => {
    // The local provider search gathers the selected indexed asset; choose uses
    // the same saved candidate path as every other Visuals Library result.
    const result = await api(`/api/projects/${p.id}/slides/${sid}/search`, {method:'POST',
      body:JSON.stringify({query:asset.title || asset.tags.join(' ') || 'library',kind:asset.kind,source:'library',asset_id:asset.id})});
    Object.assign(slide,result.slide);
    await choose(sid,`lib${asset.id}`);
  });
}

function openVisualEdit(sid) {
  state.focusSlide = sid;
  if (state.tab === 'edit') {
    const item = tlItems('paragraph').find(q => q.sid === sid);
    if (item) { tlSelect(item); tlSeek(item.t0,{ensure:false}); }
    $('#edit-picture-tools')?.closest('.modal').remove();
  } else location.hash = `#/p/${state.project.id}/edit`;
}

// Footage suggestions only read manifests; they never render.
async function loadVisualFootage(p) {
  if (state.visualFootageProject === p) return;
  state.visualFootageProject = p;
  state.visualFootageSuggested = new Set();
  state.visualFootageError = '';
  try {
    const shoots = await api('/api/footage/shoots');
    if (state.project !== p) return;
    state.visualHasFootage = shoots.length > 0;
    if (['media','edit'].includes(state.tab)) paintMedia();
  } catch(e) { state.visualFootageError = e.message; }
}

async function suggestVisualFootage(p, s) {
  const key = JSON.stringify([s.id, s.narration, s.visual_note]);
  if (!state.visualHasFootage || state.visualFootageSuggested.has(key)) return;
  state.visualFootageSuggested.add(key);
  try {
    const r = await api(`/api/projects/${p.id}/slides/${s.id}/search`, {method:'POST',
      body:JSON.stringify({source:'footage', query:[s.narration, s.visual_note, s.title].filter(Boolean).join(' ') || 'footage'})});
    // A suggestion request must never undo a choice made while it was running.
    s.candidates = r.slide.candidates;
    if (state.project === p && ['media','edit'].includes(state.tab)) paintMedia();
  } catch(e) {
    state.visualFootageError = e.message;
    if (state.project === p && ['media','edit'].includes(state.tab)) paintMedia();
  }
}

async function fillVisualFootage() {
  const p = state.project;
  try {
    const r = await api(`/api/projects/${p.id}/footage/fill`, {method:'POST', body:'{}'});
    p.slides = r.slides;
    if (state.project === p) {
      if (state.tab === 'edit') { state.project = await api(`/api/projects/${p.id}`); await tlRefresh(); }
      paintMedia();
    }
  } catch(e) { toast(e.message); }
}

const visualBlockCache = new WeakMap();
let visualBlockSequence = 0;
const visualBlockSession = 'visuals-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
function visualBlockData(p) {
  if (!visualBlockCache.has(p)) visualBlockCache.set(p, {suggestions:new Map(), trials:new Map()});
  return visualBlockCache.get(p);
}
function visualSuggestionKey(s) { return JSON.stringify([s.id,s.narration,s.visual_note]); }
function visualTrialKey(p, s) { return JSON.stringify([p.aspect,s.cues?.blocks?.[0]]); }
function visualBlockStill(p, s) {
  const trial = visualBlockData(p).trials.get(visualTrialKey(p,s));
  return trial?.url ? `<img src="${esc(trial.url)}" alt="${esc(s.cues.blocks[0].block)} trial still">`
    : `<p role="status">${esc(trial?.error || (trial?.disabled ? 'Block preview disabled for snapshots.' : 'Use Preview block still to draw this block.'))}</p>`;
}
function visualBlockPanel(p, s) {
  const data = visualBlockData(p), aspect = p.aspect === 'portrait' ? '9:16' : p.aspect === 'square' ? '1:1' : '16:9';
  const suggestions = data.suggestions.get(visualSuggestionKey(s)) || [];
  const available = (data.items || []).filter(b => b.kind === 'segment' && b.aspects.includes(aspect));
  const presets = (data.presets || []).filter(pr => !pr.missing && available.some(b => b.ref === pr.block));
  available.sort((a,b) => blockPriority(b,presets,p.channel_id) - blockPriority(a,presets,p.channel_id));
  const pinned = available.filter(b => blockPriority(b,presets,p.channel_id)).map(b => b.ref);
  const refs = [...new Set([...pinned,...suggestions.map(b => b.block), ...available.map(b => b.ref)])].slice(0,4);
  const selected = s.cues?.blocks?.[0];
  return `${selected ? `<div class="visual-block-chosen"><h4>Chosen block · ${esc(selected.block)}</h4>${visualBlockStill(p,s)}
      <button type="button" class="btn sm ghost" onclick="openBlockPicker('${p.id}','${s.id}')">Edit</button>
      <button type="button" class="btn sm ghost" onclick="removeVisualBlock('${s.id}')">Remove</button><button type="button" class="btn sm ghost" onclick="loadVisualBlocks(state.project,state.project.slides.find(s=>s.id==='${s.id}'),true)">Preview block still</button></div>` : ''}
    <h4>Suggested blocks</h4><div class="visual-block-strip">${presets.map((pr,i) => `<button type="button" class="btn" data-visual-preset="${i}">${esc(pr.name)} <span class="chip">${esc(pr.badge)}</span></button>`).join('')}${refs.map(ref => {
      const b = available.find(b => b.ref === ref);
      const suggestion = suggestions.find(b => b.block === ref);
      return b ? `<button type="button" class="block-card" data-visual-block="${esc(ref)}">${blockPoster(b,aspect)}
        <strong>${esc(b.name)}</strong><small>${esc(suggestion?.reason || b.category)}</small></button>` : '';
    }).join('')}</div>
    <p role="status">${esc(data.error || '')}</p>
    <button type="button" class="btn sm ghost" onclick="openBlockPicker('${p.id}','${s.id}')">More blocks…</button>`;
}
async function loadVisualBlocks(p, s, preview = false) {
  if (s.on_camera) return;
  const data = visualBlockData(p);
  const repaint = () => {
    if (state.project === p && state.tab === 'edit' && $('#edit-picture-tools')) paintMedia();
  };
  if (!data.loading) {
    data.loading = true;
    Promise.all([api('/api/blocks'), loadBlockPresets({project:p.id,channel:p.channel_id})]).then(async ([items,presets]) => {
      data.presets = presets;
      data.items = items; repaint();

    }).catch(e => { data.error = e.message; repaint(); });
  }
  const key = visualSuggestionKey(s);
  if (!data.suggestions.has(key)) {
    data.suggestions.set(key, []);
    api(`/api/projects/${p.id}/slides/${s.id}/block-suggestions`).then(items => {
      data.suggestions.set(key, items); repaint();
    }).catch(e => { data.error = e.message; repaint(); });
  }
  const cue = s.cues?.blocks?.[0], trialKey = visualTrialKey(p,s);
  if (preview && cue && !data.trials.has(trialKey)) {
    data.trials.set(trialKey, {});
    api(`/api/blocks/${cue.block}/preview`, {method:'POST',body:JSON.stringify({values:cue.vars || {},
      aspect:p.aspect === 'portrait' ? '9:16' : p.aspect === 'square' ? '1:1' : '16:9',kind:'trial',session:visualBlockSession,sequence:++visualBlockSequence})})
      .then(trial => {
        if (trial.stale) data.trials.delete(trialKey); else data.trials.set(trialKey,trial);
        repaint();
      })
      .catch(e => { data.trials.set(trialKey,{error:e.message}); repaint(); });
  }
  const presetChoices = (data.presets || []).filter(pr => !pr.missing && (data.items || []).some(b => b.ref === pr.block && b.kind === 'segment' && b.aspects.includes(p.aspect === 'portrait' ? '9:16' : p.aspect === 'square' ? '1:1' : '16:9')));
  document.querySelectorAll('[data-visual-preset]').forEach(card => { card.onclick = () => {
    const pr = presetChoices[Number(card.dataset.visualPreset)];
    openBlockPicker(p.id,s.id,{block:pr.block,vars:pr.values,preset:{id:pr.id,scope:pr.scope}});
  }; });
  document.querySelectorAll('[data-visual-block]').forEach(card => {
    card.onclick = () => {
      const suggestion = data.suggestions.get(key)?.find(b => b.block === card.dataset.visualBlock);
      openBlockPicker(p.id,s.id,suggestion || {block:card.dataset.visualBlock,vars:{}});
    };
  });
}
async function removeVisualBlock(sid) {
  const p = state.project;
  try {
    const slide = await api(`/api/projects/${p.id}/slides/${sid}`, {method:'PATCH',body:JSON.stringify({cues:{blocks:[]}})});
    if (state.project !== p) return;
    Object.assign(p.slides.find(s => s.id === sid),slide);
    if (state.tab === 'edit') await tlRefresh();
    paintMedia();
  } catch(e) { toast(e.message,true); }
}

// Cast and the complete shot planner/checks live in Edit's Sources > 3D.
async function openEditStageTools(kind) {
  $('#edit-picture-tools')?.closest('.modal').remove();
  $('#edit-stage-tools')?.closest('.modal').remove();
  const wrap = document.createElement('div'); wrap.className = 'modal';
  wrap.dataset.pid = state.project.id; wrap.dataset.tool = kind;
  wrap.setAttribute('role','dialog'); wrap.setAttribute('aria-modal','true');
  wrap.setAttribute('aria-label',kind === 'cast' ? 'Cast and models' : 'Shot planning and checks');
  wrap.innerHTML = `<div class="modal-box wide"><div class="edit-tool-head"><h2>${kind === 'cast' ? 'Cast and models' : 'Shot planning and checks'}</h2><button type="button" class="btn sm ghost" data-close>Close</button></div><div id="edit-stage-tools"></div></div>`;
  const focus = document.activeElement;
  const close = () => { wrap.remove(); focus?.isConnected && focus.focus(); };
  wrap.querySelector('[data-close]').onclick = close;
  wrap.onclick = e => { if (e.target === wrap) close(); };
  wrap.onkeydown = e => editToolKey(e,wrap,close);
  tlPause(); document.body.appendChild(wrap);
  await (kind === 'cast' ? paintCast() : paintStage());
  wrap.querySelector('[data-close]').focus();
}
async function editToolsRoute() {
  const key = `${state.project.id}/${state.stage}/${state.subtab || ''}`;
  const changed = state.editToolsRoute !== key; state.editToolsRoute = key;
  const dialog = $('#edit-stage-tools')?.closest('.modal');
  if (dialog && (state.tab !== 'edit' || dialog.dataset.pid !== state.project.id)) dialog.remove();
  else if (dialog) await (dialog.dataset.tool === 'cast' ? paintCast() : paintStage());
  else if (changed && state.tab === 'edit' && ['cast','stage'].includes(state.subtab)) await openEditStageTools(state.subtab);
  if (state.tab === 'edit') {
    if (state.focusSlide) openVisualEdit(state.focusSlide);
    paintEditPictureTools();
  } else $('#edit-picture-tools')?.closest('.modal').remove();
}

// App confirmations and text entry; migrated tools never use native dialogs.
function pictureDialog(message, value = null) {
  if (value === null) return appConfirm({title: 'Confirm picture change', body: message})
    .then(agreed => agreed || null);
  return appPrompt({title: message, label: 'Name', value, required: true})
    .then(result => result === null ? null : result.trim());
}

function editToolKey(e, wrap, close) { appDialogKey(e, wrap, close); }

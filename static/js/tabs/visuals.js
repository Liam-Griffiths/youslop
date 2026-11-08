/* One selected picture at a time; saved block stills use the quarter-size trial cache. */
function visualKind(s) {
  const c = (s.candidates || []).find(c => c.id === s.chosen_id);
  if (s.on_camera) return 'camera';
  if (s.cues?.blocks?.length) return 'scene';
  if (isStage(state.project.style.format) && /^3D:/i.test(s.visual_note || '')) return '3D';
  if (isCut(state.project.style.format) || state.project.style.format === 'board') return 'drawn';
  if (c?.provider === 'footage') return 'footage';
  if (c?.provider === 'library') return 'library';
  if (['diagram', 'custom', 'block', 'scene'].includes(c?.provider)) return 'scene';
  return c ? 'archive' : 'unpicked';
}

function visualSources(p) {
  const tabs = visualFormatSources(p);
  return state.visualHasFootage ? ['Footage', ...tabs.filter(t => t !== 'Footage')] : tabs;
}

function visualFormatSources(p) {
  if (p.delivery === 'on_camera' || p.slides.some(s => s.on_camera))
    return ['Layout', 'Footage', 'Screens', 'Library', 'Scenes', 'Archive', 'Upload'];
  if (isStage(p.style.format)) return ['3D', 'Archive', 'Footage', 'Library', 'Scenes', 'Upload'];
  if (p.aspect === 'portrait') return ['Blocks', 'Archive', 'Library', 'Scenes', 'Upload'];
  if (p.style.format === 'kenburns') return ['Footage', 'Archive', 'Library', 'Scenes', 'Upload'];
  return ['Archive', 'Library', 'Scenes', 'Upload'];
}

function selectVisual(sid) {
  state.visualSelection = {pid: state.project.id, sid};
  paintMedia();
}

function selectVisualSource(source) {
  state.visualSource = {pid: state.project.id, source};
  paintMedia();
}

function paintMedia() {
  const p = state.project, slides = p.slides;
  loadVisualFootage(p);
  const runs = p.picture_runs || slides.map(s => [s.id]);
  const byId = Object.fromEntries(slides.map((s, i) => [s.id, {s, i}]));
  const groups = runs.filter(r => byId[r[0]]).map(r => ({
    ids: r, ...byId[r[0]], seconds: r.reduce((n, id) => n + (byId[id]?.s.take?.duration || 0), 0),
  }));
  const requested = state.focusSlide || (state.visualSelection?.pid === p.id && state.visualSelection.sid);
  const group = groups.find(g => g.ids.includes(requested)) || groups[0];
  const tabs = visualSources(p);
  const source = state.visualSource?.pid === p.id && tabs.includes(state.visualSource.source)
    ? state.visualSource.source : tabs[0];
  const kinds = {};
  groups.forEach(g => { const k = visualKind(g.s); kinds[k] = (kinds[k] || 0) + g.seconds; });
  // Unvoiced projects have no real durations: show counts, never invented timings.
  const total = groups.reduce((n,g) => n + g.seconds, 0);
  if (!total) groups.forEach(g => { const k = visualKind(g.s); kinds[k] = (kinds[k] || 0) + 1; });
  const denominator = total || groups.length || 1;
  const rule = isStage(p.style.format) ? '3D for how it works, archive for who and when, scenes for numbers.'
    : tabs[0] === 'Layout' ? 'Face for opinion, cutaway when you describe a place or a thing.'
    : p.aspect === 'portrait' ? 'Draw numbers with blocks; keep text clear of the Shorts UI.'
    : p.style.format === 'kenburns' ? 'Footage for what you shot, archive for context, scenes for numbers.'
    : 'Use the format’s drawing; archive for context, scenes for numbers.';
  $('#tabbody').innerHTML = `<div class="visuals-workspace">
    <div class="visual-mix"><span class="micro-label">Visual mix</span>
      <div class="visual-mix-bar" aria-hidden="true">${Object.entries(kinds).map(([k,n]) =>
        `<span class="visual-kind" data-kind="${k}" style="flex:${n}"></span>`).join('')}</div>
      <span class="mono">${Object.entries(kinds).map(([k,n]) => `${k} ${Math.round(100*n/denominator)}%`).join(' · ')}${total ? ' · by voiced duration' : ' · by group count (unvoiced)'}</span>
      <span class="visual-rule">Format rule: ${rule}</span>
    </div>
    <div class="visual-grid">
      <aside class="visual-groups" aria-label="Picture groups"><h2 class="micro-label">Picture groups · ${groups.length}</h2>
        ${groups.map(g => {
          const c = g.s.candidates.find(c => c.id === g.s.chosen_id);
          return `<button type="button" class="btn ghost visual-group" data-sid="${g.s.id}"
            aria-pressed="${g === group}" onclick="selectVisual('${g.s.id}')">
            <span class="mono">${String(g.i + 1).padStart(2,'0')}</span>
            ${c ? `<img src="${thumbUrl(c)}" loading="lazy" alt="">` : '<span class="visual-thumb-empty"></span>'}
            <span class="visual-group-text">${esc(g.s.title || g.s.narration || 'Untitled')}
              <small class="mono">¶${g.i+1}${g.ids.length > 1 ? '–'+(byId[g.ids.at(-1)].i+1) : ''} · ${g.seconds ? fmtTime(g.seconds) : 'unvoiced'}</small></span>
            <span class="visual-chip visual-kind" data-kind="${visualKind(g.s)}">${visualKind(g.s)}</span>
          </button>`;
        }).join('') || '<p>Write the script to choose pictures.</p>'}
        <label class="field"><span>Picture every</span><select onchange="savePictureEvery(+this.value)">
          ${[1,2,3,4,5,6].map(n => `<option value="${n}" ${n === (p.style.picture_every || 1) ? 'selected' : ''}>${n === 1 ? 'paragraph' : n+' paragraphs'}</option>`).join('')}</select></label>
        ${state.visualHasFootage ? '<button type="button" class="btn sm" onclick="fillVisualFootage()">Fill the rest from footage</button>' : ''}
        <button type="button" class="btn sm ghost" onclick="gatherMedia()">Re-search everything</button>
        ${p.style.format === 'board' ? `<button type="button" class="btn sm" onclick="planBoards(false)">Write the boards</button><button type="button" class="btn sm ghost" onclick="planBoards(true)">Rewrite all boards</button>` : ''}
        ${isCut(p.style.format) ? `<button type="button" class="btn sm" onclick="planCues(false)">Write the cues</button><button type="button" class="btn sm ghost" onclick="planCues(true)">Rewrite all cues</button>` : ''}
      </aside>
      <section class="visual-preview" aria-label="Selected picture">${group ? visualPreview(group, byId) : ''}</section>
      <aside class="visual-sources" aria-label="Picture sources"><div class="visual-source-tabs" role="group" aria-label="Choose picture source">
        ${tabs.map(t => `<button type="button" class="btn sm ghost" aria-pressed="${t === source}" onclick="selectVisualSource('${t}')">${t}</button>`).join('')}</div>
        <div class="visual-source-body">${group ? visualSourcePanel(group.s, source) : ''}</div>
      </aside>
    </div>
    <section class="visual-sequence" aria-label="Sequence"><span class="micro-label">The video as it will play${total ? '' : ' · durations available after voice'}</span>
      <div>${groups.map(g => `<button type="button" class="btn sm visual-kind" data-kind="${visualKind(g.s)}" style="flex:${total ? Math.max(g.seconds,.01) : 1}"
        aria-label="Paragraph ${g.i+1}: ${visualKind(g.s)}" aria-pressed="${g === group}" onclick="selectVisual('${g.s.id}')">${g.i+1}</button>`).join('')}</div>
    </section></div>`;
  if (group && (['Scenes','Blocks','Screens'].includes(source) || group.s.cues?.blocks?.length)) loadVisualBlocks(p, group.s);
}

function visualPreview(g, byId) {
  const p = state.project, s = g.s, c = s.candidates.find(c => c.id === s.chosen_id);
  const drawn = isCut(p.style.format) || p.style.format === 'board';
  return `<div class="mono">Picture ${g.i+1} · ¶${g.ids.map(id => byId[id].i+1).join(', ')} · ${g.seconds ? fmtTime(g.seconds)+' from the takes' : 'unvoiced'}</div>
    <h2>${esc(s.title || s.beat || 'Choose a picture')}</h2>
    <div class="visual-frame ${p.aspect === 'portrait' ? 'portrait' : ''}">
      ${s.cues?.blocks?.length && !s.on_camera ? visualBlockStill(p, s) : c && !drawn && !s.on_camera ? `<img src="${thumbUrl(c)}" loading="lazy" alt="${esc(c.title || 'Selected picture')}"
        style="object-position:${(c.focal?.[0] ?? .5)*100}% ${(c.focal?.[1] ?? .5)*100}%">`
        : `<p>${s.on_camera ? 'Camera take · layouts and jump cuts in Edit' : drawn ? 'Drawn from the narration · preview on click' : visualKind(s) === '3D' ? '3D shot · open the shot editor to inspect' : 'Choose a source to fill this picture.'}</p>`}
    </div>
    <div class="row"><button type="button" class="btn sm" onclick="previewBit('${s.id}')">Preview this bit · ¼ size</button>
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
      ${p.style.format === 'board' ? `<button type="button" class="btn sm ghost" onclick="openBoardEditor('${id}')">Edit its board</button>` : ''}
      ${isCut(p.style.format) ? `<button type="button" class="btn sm ghost" onclick="openCueEditor('${id}')">Edit its cues</button>` : ''}</div>`).join('')}`;
}

function visualSourcePanel(s, source) {
  const p = state.project;
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
    <a class="btn sm" href="#/p/${p.id}/visuals/cast">Edit cast and named parts</a>
    <a class="btn sm" href="#/p/${p.id}/visuals/stage">Shots and solver checks</a>
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
    ${p.style.format === 'board' ? `<button type="button" class="btn sm" onclick="openBoardEditor('${s.id}')">Edit the board</button>` : ''}
    ${isCut(p.style.format) ? `<button type="button" class="btn sm" onclick="openCueEditor('${s.id}')">Edit the cues</button>` : ''}`;
  if (source === 'Upload') return `<label class="field"><span>Upload a picture or clip</span><input type="file" accept="image/*,video/*" onchange="uploadMedia('${s.id}',this.files[0])"></label>`;
  const candidates = s.candidates.filter(c => source === 'Library' ? c.provider === 'library' : !['library', 'footage'].includes(c.provider));
  return `<label class="field"><span>Search ${source.toLowerCase()}</span><input type="search" id="visual-query" value="${esc(s.queries?.[0] || s.visual_note || s.title || '')}" onkeydown="if(event.key==='Enter') searchVisual('${s.id}','${source}')"></label>
    <button type="button" class="btn sm" onclick="searchVisual('${s.id}','${source}')">Search</button>
    ${source === 'Library' ? `<button type="button" class="btn sm" onclick="pickVisualLibrary('${s.id}')">Choose from Library…</button>` : ''}
    <button type="button" class="btn sm ghost" onclick="toggleKind('${s.id}')">Want ${s.prefer_kind === 'image' ? 'a clip' : 'a photo'}</button>
    <button type="button" class="btn sm ghost" onclick="openMediaSearch('${s.id}')">Full search picker</button>
    <button type="button" class="btn sm ghost" onclick="openMapPicker('${s.id}')">Get a map</button>
    <div id="visual-search-status" role="status"></div><div class="visual-results">${candidates.map(c => `<button type="button" class="btn ghost" aria-pressed="${c.id === s.chosen_id}" onclick="choose('${s.id}','${c.id}')">
      <img src="${thumbUrl(c)}" loading="lazy" alt=""><span>${esc(c.title || c.provider)}</span><small class="mono">${esc(c.provider)} · ${c.kind === 'video' ? 'clip' : 'photo'}</small></button>`).join('') || '<p>No gathered matches. Search to find options.</p>'}</div>`;
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
    if (state.project === p && state.tab === 'media') paintMedia();
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
  location.hash = `#/p/${state.project.id}/edit`;
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
    if (state.tab === 'media') paintMedia();
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
    if (state.project === p && state.tab === 'media') paintMedia();
  } catch(e) {
    state.visualFootageError = e.message;
    if (state.project === p && state.tab === 'media') paintMedia();
  }
}

async function fillVisualFootage() {
  const p = state.project;
  try {
    const r = await api(`/api/projects/${p.id}/footage/fill`, {method:'POST', body:'{}'});
    p.slides = r.slides;
    if (state.project === p && state.tab === 'media') paintMedia();
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
    : `<p role="status">${esc(trial?.error || (trial?.disabled ? 'Block preview disabled for snapshots.' : 'Loading block still…'))}</p>`;
}
function visualBlockPanel(p, s) {
  const data = visualBlockData(p), aspect = p.aspect === 'portrait' ? '9:16' : '16:9';
  const suggestions = data.suggestions.get(visualSuggestionKey(s)) || [];
  const available = (data.items || []).filter(b => b.kind === 'segment' && b.aspects.includes(aspect));
  const refs = [...new Set([...suggestions.map(b => b.block), ...available.map(b => b.ref)])].slice(0,4);
  const selected = s.cues?.blocks?.[0];
  return `${selected ? `<div class="visual-block-chosen"><h4>Chosen block · ${esc(selected.block)}</h4>${visualBlockStill(p,s)}
      <button type="button" class="btn sm ghost" onclick="openBlockPicker('${p.id}','${s.id}')">Edit</button>
      <button type="button" class="btn sm ghost" onclick="removeVisualBlock('${s.id}')">Remove</button></div>` : ''}
    <h4>Suggested blocks</h4><div class="visual-block-strip">${refs.map(ref => {
      const b = available.find(b => b.ref === ref);
      const suggestion = suggestions.find(b => b.block === ref);
      return b ? `<button type="button" class="block-card" data-visual-block="${esc(ref)}">${blockPoster(b,aspect)}
        <strong>${esc(b.name)}</strong><small>${esc(suggestion?.reason || b.category)}</small></button>` : '';
    }).join('')}</div>
    <p role="status">${esc(data.error || '')}</p>
    <button type="button" class="btn sm ghost" onclick="openBlockPicker('${p.id}','${s.id}')">More blocks…</button>
    ${data.thirdParty?.length ? `<section aria-label="Third-party blocks"><h4>Third-party blocks · installed</h4>
      ${data.thirdParty.map(b => `<p>${esc(b.name)} · third-party · ${esc(b.license || 'Licence not recorded')}</p>`).join('')}</section>` : ''}`;
}
async function loadVisualBlocks(p, s) {
  if (s.on_camera) return;
  const data = visualBlockData(p);
  const repaint = () => {
    if (state.project === p && state.tab === 'media' && $('#tabbody .visuals-workspace')) paintMedia();
  };
  if (!data.loading) {
    data.loading = true;
    Promise.all([api('/api/blocks'), api('/api/blocks/third-party')]).then(async ([items,thirdParty]) => {
      data.items = items; data.thirdParty = thirdParty; repaint();
      // Same one-off poster batch the Blocks screen starts; reload when it ends.
      if (!items.some(b => Object.keys(b.posters || {}).length < b.aspects.length)) return;
      const {job} = await api('/api/blocks/posters', {method:'POST'});
      if (!job) return;
      for (;;) {
        await new Promise(r => setTimeout(r, 2000));
        if (state.project !== p) return;
        if ((await api(`/api/jobs/${job}`)).state !== 'running') break;
      }
      data.items = await api('/api/blocks'); repaint();
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
  if (cue && !data.trials.has(trialKey)) {
    data.trials.set(trialKey, {});
    api(`/api/blocks/${cue.block}/preview`, {method:'POST',body:JSON.stringify({values:cue.vars || {},
      aspect:p.aspect === 'portrait' ? '9:16' : '16:9',kind:'trial',session:visualBlockSession,sequence:++visualBlockSequence})})
      .then(trial => {
        if (trial.stale) data.trials.delete(trialKey); else data.trials.set(trialKey,trial);
        repaint();
      })
      .catch(e => { data.trials.set(trialKey,{error:e.message}); repaint(); });
  }
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
    paintMedia();
  } catch(e) { toast(e.message,true); }
}

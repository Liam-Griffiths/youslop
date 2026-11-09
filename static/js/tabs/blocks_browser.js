/* Shared library and pick browser. Scratch values never save themselves. */
let blocksBrowser = null;
let blockPreviewAs = '';
let themedPosterObserver = null;
let themedPosterQueue = [];
let themedPosterBusy = false;
let themedPosterSequence = 0;
const themedPosterCache = new Map();

async function renderBlocks(path = '', options = {}) {
  themedPosterCache.clear();
  if (options.mode !== 'channel') {
    options.project ||= state.project?.id;
    options.channel ||= state.project?.channel_id;
  }
  if (options.project && options.project !== blocksBrowser?.options.project) blockPreviewAs = `project:${options.project}`;
  else if (options.channel && options.channel !== blocksBrowser?.options.channel) blockPreviewAs = `channel:${options.channel}`;
  const route = location.hash;
  const query = path.startsWith('search/') ? decodeURIComponent(path.slice(7)) : '';
  const selected = query ? '' : decodeURIComponent(path);
  const [items, channels] = await Promise.all([api('/api/blocks' + (options.overlay ? '?overlay=1' : '')), api('/api/channels')]);
  if (location.hash !== route) return;
  if (!options.mode && !location.hash.startsWith('#/blocks')) return;
  const presets = await loadBlockPresets(options, channels);
  if (location.hash !== route) return;
  blocksBrowser = {items, presets, channels, selected, options, trial:options.selection ? {ref:options.selection.block, values:options.selection.vars} : null};
  if (options.selection?.preset && blocksBrowser.trial) blocksBrowser.trial.preset = options.selection.preset;
  // The Edit stage moves #inspector inside the view; take it back before the
  // view is replaced, or the detail panel has nowhere to paint (picker from G).
  if (typeof restoreShellInspector === 'function' && view.contains($('#inspector'))) restoreShellInspector();
  view.innerHTML = `<h1>Blocks</h1><p class="sub">Local blocks for titles, numbers and stories. Built in, from packs, or yours.</p>
    ${options.mode ? '<button type="button" class="btn ghost" id="block-picker-close">Back</button>' : ''}
    <div class="blocks-browser"><aside class="blocks-filters" aria-label="Block filters">
    <label for="blocks-preview-as">Preview as</label><select id="blocks-preview-as"><option value="">Default</option>
      ${channels.map(c => `<option value="channel:${esc(c.id)}">${esc(c.name)}</option>`).join('')}
      ${options.project ? `<option value="project:${esc(options.project)}">This project</option>` : ''}</select>
    <label for="blocks-search">Find a block</label><input type="search" id="blocks-search" value="${esc(query)}" placeholder="Name, tag or variable">
    ${[['category','Category', [...new Set(items.map(b => b.category))].sort()],
       ['aspect','Aspect',['16:9','9:16','1:1']], ['source','Source',['built-in','packs','mine']]].map(([key,label,values]) => `
      <label for="blocks-${key}">${label}</label><select id="blocks-${key}"><option value="">All</option>
      ${values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('')}</select>`).join('')}
    <label><input type="checkbox" id="blocks-data"> Works with data</label>
    <label><input type="checkbox" id="blocks-favourites"> Favourites</label>
    <label><input type="checkbox" id="blocks-presets"> Presets</label>
    <label for="blocks-channel">Pinned to channel</label><select id="blocks-channel"><option value="">All</option>${channels.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select>
    <label for="blocks-sort">Sort</label><select id="blocks-sort"><option value="recommended">Recommended</option><option value="recent">Recently used</option><option value="name">A–Z</option></select>
    <button type="button" class="btn ghost" id="blocks-clear">Clear filters</button></aside>
    <section aria-label="Blocks"><details class="card block-create" ${state.openBlockDescription || state.blockDescription || state.blockResult ? 'open' : ''}><summary>Describe a new block…</summary>
      <label for="block-description">What should it show?</label><textarea id="block-description" maxlength="4000" placeholder="A receipt that prints line by line with a total at the end">${esc(state.blockDescription || '')}</textarea>
      <p class="mono">One-off model call with up to two repairs. Reusing a saved block costs no tokens.</p>
      <button type="button" class="btn" onclick="describeBlock(this)" ${state.job?.kind === 'create block' && !state.job.done ? 'disabled' : ''}>Create block</button>
      <div id="block-result" role="status">${blockCreationResult()}</div></details>
      <p id="blocks-count" class="mono" role="status"></p><div id="blocks-grid" class="blocks-grid"></div></section></div>`;
  $('#blocks-preview-as').value = blockPreviewAs;
  blockPreviewAs = $('#blocks-preview-as').value;
  $('#blocks-preview-as').onchange = e => {
    blockPreviewAs = e.target.value; blockPreviewSequence++;
    themedPosterObserver?.disconnect(); themedPosterQueue = [];
    paintBlocksGrid(); paintBlockDetails();
  };
  if (state.openBlockDescription) { $('#block-description').focus(); state.openBlockDescription = false; }
  $('#block-description').oninput = e => { state.blockDescription = e.target.value; };
  for (const id of ['search','category','aspect','source','data','sort','favourites','channel','presets']) $(`#blocks-${id}`).oninput = paintBlocksGrid;
  $('#blocks-clear').onclick = () => { for (const el of document.querySelectorAll('.blocks-filters input,.blocks-filters select')) {
    if (el.id === 'blocks-preview-as') continue;
    if (el.type === 'checkbox') el.checked = false; else el.value = el.id === 'blocks-sort' ? 'recommended' : '';
  } paintBlocksGrid(); };
  if (options.mode) $('#block-picker-close').onclick = () => { $('#inspector').innerHTML = ''; return options.mode === 'channel' ? refreshChannel() : render(); };
  if (options.mode === 'pick' && options.aspect) $('#blocks-aspect').value = options.aspect;
  paintBlocksGrid();
  paintBlockDetails(options.aspect);
  if (selected) $('#block-play')?.focus();
  const result = await api('/api/blocks/posters', {method:'POST'});
  if (result.job) {
    const browser = blocksBrowser;
    const refresh = async () => {
      if (blocksBrowser !== browser || !$('#blocks-grid')) return;
      browser.items = await api('/api/blocks' + (browser.options.overlay ? '?overlay=1' : ''));
      if (blocksBrowser !== browser || !$('#blocks-grid')) return;
      blockPosterArrived();
      const job = await api(`/api/jobs/${result.job}`);
      if (job.state === 'running') setTimeout(() => refresh().catch(e => toast(e.message, true)), 2000);
    };
    setTimeout(() => refresh().catch(e => toast(e.message, true)), 2000);
  }
}

function paintBlocksGrid() {
  const q = $('#blocks-search').value.toLowerCase();
  const category = $('#blocks-category').value, aspect = $('#blocks-aspect').value, source = $('#blocks-source').value;
  let items = blocksBrowser.items.filter(b => [b.name,b.description,...b.tags,...Object.keys(b.variables),...blocksBrowser.presets.filter(p => p.block === b.ref).map(p => p.name)].join(' ').toLowerCase().includes(q)
    && (!category || b.category === category) && (!aspect || b.aspects.includes(aspect))
    && (!source || b.source === source || source === 'packs' && b.ref.startsWith('pack/'))
    && (!$('#blocks-presets').checked || blocksBrowser.presets.some(p => p.block === b.ref))
    && (!$('#blocks-channel').value || b.channels.includes($('#blocks-channel').value) || blocksBrowser.presets.some(p => p.block === b.ref && p.owner === $('#blocks-channel').value))
    && (!$('#blocks-favourites').checked || b.favourite)
    && (!$('#blocks-data').checked || b.works_with_data));
  if ($('#blocks-sort').value === 'recommended') items.sort((a,b) => blockPriority(b, blocksBrowser.presets, blocksBrowser.options.channel) - blockPriority(a, blocksBrowser.presets, blocksBrowser.options.channel));
  if ($('#blocks-sort').value === 'name') items.sort((a,b) => a.name.localeCompare(b.name));
  if ($('#blocks-sort').value === 'recent') items.sort((a,b) => (b.recent || 0) - (a.recent || 0));
  $('#blocks-count').textContent = `${items.length} blocks`;
  $('#blocks-grid').innerHTML = items.map(b => {
    const a = aspect || b.aspects[0];
    return `<div class="block-card-wrap"><button type="button" class="block-card" data-ref="${esc(b.ref)}" aria-pressed="${b.ref === blocksBrowser.selected}">
      ${blockPoster(b,a)}<strong>${esc(b.name)}</strong><span>${esc(b.description)}</span><span class="mono">${esc(b.source)} · ${esc(b.category)}</span></button>
      <button type="button" class="btn sm block-star" data-star="${esc(b.ref)}" aria-label="Favourite ${esc(b.name)}" aria-pressed="${!!b.favourite}">${b.favourite ? '★' : '☆'}</button>${blocksBrowser.presets.filter(p => p.block === b.ref).map(blockPresetCard).join('')}</div>`;
  }).join('') || '<p>No blocks match. Clear filters, or <button type="button" class="btn ghost" id="block-describe-empty">Describe a block</button>.</p>';
  const missing = blocksBrowser.presets.filter(p => p.missing && (!q || `${p.name} ${p.block}`.toLowerCase().includes(q)));
  $('#blocks-grid').insertAdjacentHTML('beforeend', missing.map(blockPresetCard).join(''));
  document.querySelectorAll('[data-preset-index]').forEach(button => { button.onclick = () => chooseBlockPreset(blocksBrowser.presets[Number(button.dataset.presetIndex)]); });
  $('#block-describe-empty')?.addEventListener('click', () => { $('.block-create').open = true; $('#block-description').focus(); });
  document.querySelectorAll('[data-star]').forEach(button => { button.onclick = () => toggleBlockFavourite(button.dataset.star); });
  const cards = [...document.querySelectorAll('#blocks-grid .block-card')];
  cards.forEach((card,i) => {
    card.onclick = () => {
      if (!blocksBrowser.options.mode) go(`#/blocks/${card.dataset.ref}`);
      else { blocksBrowser.selected = card.dataset.ref; paintBlocksGrid(); paintBlockDetails(); $('#block-play')?.focus(); }
    };
    let hover;
    card.onmouseenter = () => { if (!matchMedia('(prefers-reduced-motion: reduce)').matches)
      hover = setTimeout(() => requestBlockPreview(bForCard(card), aForCard(card), 'motion', {}, card), 400); };
    card.onmouseleave = () => { clearTimeout(hover); stopBlockPreview(card); };
    card.onblur = card.onmouseleave;
    card.onkeydown = e => {
      if (e.code === 'Space') { e.preventDefault(); clearTimeout(hover);
        if (card.dataset.previewActive) stopBlockPreview(card);
        else requestBlockPreview(bForCard(card), aForCard(card), 'motion', {}, card);
        return; }
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const columns = getComputedStyle($('#blocks-grid')).gridTemplateColumns.split(' ').length;
      const step = {ArrowLeft:-1,ArrowRight:1,ArrowUp:-columns,ArrowDown:columns}[e.key];
      cards[Math.max(0,Math.min(cards.length-1,i+step))]?.focus();
    };
  });
  observeThemedPosters();
}

function blockPoster(block, aspect) {
  if (blockPreviewAs) {
    const url = themedPosterCache.get(`${blockPreviewAs}/${block.ref}/${aspect}`);
    // Until the themed poster arrives, show the default one dimmed rather than an empty image.
    const src = url || block.posters[aspect];
    return `<img ${src ? `src="${esc(src)}"` : ''} ${url ? '' : 'class="themed-pending"'} data-themed-ref="${esc(block.ref)}" data-themed-aspect="${esc(aspect)}" alt="${esc(block.name)}, ${esc(aspect)} themed preview">`;
  }
  return block.posters[aspect] ? `<img src="${esc(block.posters[aspect])}" alt="${esc(block.name)}, ${esc(aspect)} preview">`
    : `<span class="block-placeholder" role="img" aria-label="${esc(block.name)}, ${esc(aspect)} preview pending">${esc(block.name)}<small>Poster pending</small></span>`;
}

function paintBlockDetails(aspect) {
  const b = blocksBrowser.items.find(item => item.ref === blocksBrowser.selected);
  const panel = $('#inspector');
  if (!b) { panel.innerHTML = blocksBrowser.selected ? '<p>Block not found. Choose a block from the grid.</p>' : ''; return; }
  blockPreviewSequence++;
  aspect ||= blocksBrowser.options.aspect || b.aspects[0];
  if (!b.aspects.includes(aspect)) aspect = b.aspects[0];
  const saved = blocksBrowser.presets.filter(p => p.block === b.ref && (p.scope === 'project' && p.owner === blocksBrowser.options.project || p.scope === 'channel' && p.owner === blocksBrowser.options.channel));
  const scratch = {...saved.find(p => p.scope === 'channel')?.values, ...saved.find(p => p.scope === 'project')?.values,
    ...(blocksBrowser.trial?.ref === b.ref ? blocksBrowser.trial.values : {})};
  panel.innerHTML = `<div class="block-detail"><h2>${esc(b.name)}</h2><p>${esc(b.description)}</p><button type="button" id="block-trial-image" aria-label="Expand ${esc(b.name)} preview">${blockPoster(b,aspect)}</button>
    <div class="row"><button type="button" class="btn sm" id="block-play">Play · ¼ size</button><button type="button" class="btn sm" id="block-expand">Expand</button>
      ${b.aspects.map(a => `<button type="button" class="btn sm" aria-pressed="${a === aspect}" data-aspect="${esc(a)}">${esc(a)}</button>`).join('')}</div>
    <p id="block-trial-status" role="status" aria-live="polite"></p>
    <h3>Try it</h3><form id="block-trial">${Object.entries(b.variables).map(([key,spec],i) => blockTrialField(key,{...spec,default:scratch[key] ?? spec.default},i)).join('')}
    <button type="button" class="btn sm ghost" id="block-reset">Reset to defaults</button></form>
    ${blocksBrowser.options.mode !== 'channel' ? `<button type="button" class="btn" id="block-use">${blocksBrowser.options.mode === 'pick' ? 'Use here' : state.blocksProjectId ? 'Use in this video' : 'Use in a project…'}</button>` : ''}
    <div class="row"><button type="button" class="btn sm" id="block-pin">Add to channel…</button>
      <button type="button" class="btn sm" id="block-duplicate" ${b.forkable ? '' : 'disabled aria-describedby="block-fork-note"'}>Duplicate as mine</button>
      ${b.forkable ? '' : '<small id="block-fork-note">Built-in blocks use trusted template features that copies cannot keep. Save your values as a preset or describe a new block instead.</small>'}
      <button type="button" class="btn sm" data-star="${esc(b.ref)}" aria-pressed="${!!b.favourite}">${b.favourite ? '★' : '☆'} Favourite</button></div>
    <button type="button" class="btn sm" id="block-save-preset">Save as preset…</button><div id="block-preset-target"></div>
    <div id="block-channel-target"></div>
    <p class="mono block-meta">${esc(blockDuration(b.duration))} · ${esc(b.source)} · ${esc(b.licence)}<br>${esc(b.check_status)}
    ${b.origin ? `<br>Origin: ${esc(Object.entries(b.origin).map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}`).join(' · '))}` : ''}</p>
    <div id="block-project-target"></div>
    </div>`;
  const detail = panel.querySelector('.block-detail');
  const values = () => readBlockTrial(b, detail);
  const refresh = kind => {
    try { requestBlockPreview(b,aspect,kind,values(),detail); }
    catch (e) { blockTrialError(detail, e.message); }
  };
  detail.querySelector('form').onsubmit = e => e.preventDefault();
  let timer;
  detail.querySelector('form').oninput = () => {
    clearTimeout(timer);
    // Invalidate immediately, before the debounce, so old pixels cannot win.
    blockPreviewSequence++;
    blocksBrowser.trial = {...(blocksBrowser.trial?.ref === b.ref ? blocksBrowser.trial : {}),ref:b.ref,values:Object.fromEntries([...detail.querySelectorAll('[data-key]')].map(el => [el.dataset.key,el.value]))};
    detail.querySelectorAll('[data-max]').forEach(input => {
      input.nextElementSibling.textContent = `${input.dataset.max - input.value.length} characters remaining`;
    });
    timer = setTimeout(() => { if (detail.isConnected && !document.querySelector('dialog.block-player[open]')) refresh('trial'); },600);
  };
  $('#block-save-preset').onclick = () => blockPresetTarget(b, aspect, values).catch(e => toast(e.message,true));
  $('#block-reset').onclick = () => { blocksBrowser.trial = {ref:b.ref,values:Object.fromEntries(Object.entries(b.variables).map(([k,v]) => [k,v.default]))}; paintBlockDetails(aspect); const fresh = $('#inspector .block-detail'); requestBlockPreview(b,aspect,'trial',readBlockTrial(b,fresh),fresh); };
  $('#block-play').onclick = () => refresh('motion');
  const expand = () => { try { openBlockPreview(b, aspect, values()); } catch (e) { blockTrialError(detail,e.message); } };
  $('#block-expand').onclick = expand;
  $('#block-trial-image').onclick = expand;
  const use = $('#block-use');
  if (use) use.onclick = async () => {
    try {
      const selection = {block:b.ref, vars:values()};
      if (blocksBrowser.trial?.ref === b.ref && blocksBrowser.trial.preset) selection.preset = blocksBrowser.trial.preset;
      if (blocksBrowser.options.mode === 'pick') await blocksBrowser.options.onUse(selection);
      else await blockProjectTarget(selection);
    } catch (e) { blockTrialError(detail, e.message); }
  };
  detail.querySelector('[data-star]').onclick = () => toggleBlockFavourite(b.ref);
  $('#block-pin').onclick = () => blockChannelTarget(b.ref).catch(e => toast(e.message,true));
  if (b.forkable) $('#block-duplicate').onclick = async e => {
    e.target.disabled = true;
    try {
      const result = await api(`/api/blocks/${b.ref}/duplicate`, {method:'POST'});
      watchJob(result.job, 'duplicate block', async job => {
        if (!job.result?.id) { toast(job.error || 'Block check failed',true); e.target.disabled = false; return; }
        await renderBlocks(job.result.id, blocksBrowser.options);
        $('#blocks-source').value = 'mine'; $('#blocks-channel').value = ''; paintBlocksGrid();
      });
    } catch (error) { toast(error.message,true); e.target.disabled = false; }
  };
  detail.querySelectorAll('[data-pick-local]').forEach(button => { button.onclick = () => {
    const input = detail.querySelector(`#${button.dataset.pickLocal}`);
    openLocalMediaPicker(input.dataset.type === 'clip' ? 'video' : 'image', asset => {
      input.value = `/scene/{token}/library/${asset.id}`;
      input.dispatchEvent(new Event('input', {bubbles:true}));
    });
  }; });
  panel.querySelectorAll('[data-aspect]').forEach(button => { button.onclick = () => paintBlockDetails(button.dataset.aspect); });
  observeThemedPosters();
}

function blockDuration(d) {
  if (!d) return '';
  if (d.mode === 'range') return `${d.min}–${d.max} s · default ${d.default ?? d.min} s`;
  return d.seconds ? `${d.seconds} s` : Object.entries(d).map(([k, v]) => `${k} ${v}`).join(' · ');
}

function blockDefault(spec) {
  const v = spec.default;
  if (Array.isArray(v)) return v.length ? `${v.length} sample row${v.length === 1 ? '' : 's'}` : 'Empty';
  if (v && typeof v === 'object') return Object.keys(v).join(', ');
  return v === '' || v == null ? '—' : String(v);
}

function bForCard(card) { return blocksBrowser.items.find(b => b.ref === card.dataset.ref); }
function aForCard(card) { return $('#blocks-aspect').value || bForCard(card).aspects[0]; }

function blockTrialField(key, spec, i) {
  const id = `block-var-${i}`, v = spec.default;
  const attr = `id="${id}" data-key="${esc(key)}" data-type="${spec.type}"`;
  let field;
  if (spec.type === 'table') field = `<textarea ${attr} placeholder="Paste CSV with column headers">${esc(typeof v === 'string' ? v : JSON.stringify(v,null,2))}</textarea><small>Paste CSV with headers, or edit JSON rows.</small>`;
  else if (spec.type === 'enum') field = `<select ${attr}>${spec.choices.map(c => `<option ${c === v ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>`;
  else field = `<input type="${spec.type === 'number' ? 'number' : 'text'}" ${attr} value="${esc(v)}" ${spec.type === 'number' ? 'step="any"' : ''}
    ${spec.max_length ? `data-max="${spec.max_length}" aria-describedby="${id}-count"` : ''}>
    ${spec.max_length ? `<small id="${id}-count">${spec.max_length - String(v).length} characters remaining</small>` : ''}`;
  return `<label for="${id}">${esc(key)} · ${esc(spec.type)}</label>${field}${['image','clip'].includes(spec.type) ? `<button type="button" class="btn sm" data-pick-local="${id}">Choose from Library…</button>` : ''}<small id="${id}-error" role="status" class="block-field-error"></small>`;
}

function blockTrialError(detail, message) {
  const status = detail.querySelector('#block-trial-status');
  if (status) status.textContent = message;
  detail.querySelectorAll('[data-key]').forEach(field => {
    const error = detail.querySelector(`#${field.id}-error`);
    const relevant = message.startsWith(field.dataset.key) || field.dataset.type === 'table' && message.startsWith('CSV');
    if (error) error.textContent = relevant ? message : '';
    field.setAttribute('aria-invalid', String(relevant));
    if (relevant) field.setAttribute('aria-errormessage', error.id);
  });
}

function readBlockTrial(b, detail) {
  return Object.fromEntries([...detail.querySelectorAll('[data-key]')].map(el => {
    let v = el.value;
    if (el.dataset.type === 'number') v = Number(v);
    if (el.dataset.type === 'table' && v.trim().startsWith('[')) {
      try { v = JSON.parse(v); } catch (e) { throw new Error(`${el.dataset.key}: ${e.message}`); }
    }
    return [el.dataset.key,v];
  }));
}

// One preview request in flight across grid, details and successive browsers.
let blockPreviewSequence = 0, blockPreviewBusy = false, blockPreviewPending = null;
const blockPreviewSession = Math.random().toString(36).slice(2) + Date.now().toString(36);
function stopBlockPreview(target) {
  if (target.dataset.previewActive) blockPreviewSequence++;
  delete target.dataset.previewActive;
  target.querySelector('video')?.pause();
  target.querySelector('video')?.remove();
  target.querySelector('.block-preview-status')?.remove();
}

function previewMessage(target, message, retry) {
  let status = target.querySelector('[role="status"]');
  if (!status) {
    status = document.createElement('span');
    status.className = 'block-preview-status'; status.setAttribute('role','status');
    target.append(status);
  }
  status.textContent = message;
  if (retry) {
    // A card is already a button; its next Space/click retries without nesting buttons.
    if (target.classList.contains('block-card')) status.append(' Press Space to retry.');
    else {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'btn sm'; button.textContent = 'Retry';
      button.onclick = retry; status.append(' ',button);
    }
  }
}

async function requestBlockPreview(b, aspect, kind, values, target, options = {}) {
  options = {...(blockPreviewAs ? {theme_context:browserThemeContext()} : {}),...options};
  const sequence = ++blockPreviewSequence;
  if (target.dataset) target.dataset.previewActive = 'true';
  blockPreviewPending = {b,aspect,kind,values,target,sequence,options};
  if (blockPreviewBusy) return;
  blockPreviewBusy = true;
  while (blockPreviewPending) {
    const request = blockPreviewPending;
    blockPreviewPending = null;
    const {b,aspect,kind,values,target,sequence,options} = request;
    if (!target.isConnected || sequence !== blockPreviewSequence) continue;
    const status = target.querySelector('[role="status"]');
    if (status) status.textContent = 'Rendering preview…';
    else if (target.classList.contains('block-card')) previewMessage(target,'Rendering preview…');
    if (target.classList.contains('block-detail')) blockTrialError(target, 'Refreshing preview…');
    try {
      const result = await api(`/api/blocks/${b.ref}/preview`, {method:'POST',body:JSON.stringify({
        values,aspect,kind,session:blockPreviewSession,sequence,...options})});
      if (sequence !== blockPreviewSequence || !target.isConnected || target.matches(':hover') === false && target.classList.contains('block-card') && document.activeElement !== target) continue;
      if (result.url) {
        const host = target.querySelector('#block-trial-image') || target.querySelector('.block-player-screen') || target;
        host.querySelectorAll('video').forEach(v => v.remove());
        if (kind === 'trial') host.innerHTML = `<img src="${esc(result.url)}" alt="${esc(b.name)}, ${esc(aspect)} trial preview">`;
        else {
          const video = document.createElement('video');
          video.src = result.url; video.muted = true; video.loop = target.querySelector('#block-player-loop')?.checked ?? true; video.controls = target.classList.contains('block-detail'); video.playsInline = true;
          video.setAttribute('aria-label', `${b.name} motion preview`);
          document.querySelectorAll('.block-card video,.block-detail video,.block-player video').forEach(v => v.remove());
          if (host.id === 'block-trial-image' || host.classList.contains('block-player-screen')) host.innerHTML = '';  // The loop replaces the still.
          const retry = () => requestBlockPreview(b,aspect,kind,values,target,options);
          // A decoder can fail once while it warms up (seen in Chromium at half
          // size); reload the same file once before reporting it.
          video.onerror = () => {
            if (!video.dataset.reloaded) { video.dataset.reloaded = '1'; video.load(); video.play().catch(() => {}); return; }
            previewMessage(target,'Cannot play this preview. The file is missing or its video format is unsupported.',retry);
          };
          host.appendChild(video);
          if (target.classList.contains('block-player')) bindBlockPlayer(target,video);
          video.play().catch(() => previewMessage(target,'Playback did not start. Press Play to try again.',retry));
        }
      }
      if (status) status.textContent = result.disabled ? 'Previews disabled for snapshots.' : 'Preview ready.';
      if (result.url) target.querySelector('.block-preview-status')?.remove();
    } catch (e) {
      if (sequence === blockPreviewSequence && target.isConnected) {
        if (target.dataset) delete target.dataset.previewActive;
        if (target.classList.contains('block-detail')) blockTrialError(target,e.message);
        previewMessage(target,e.message,() => requestBlockPreview(b,aspect,kind,values,target,options));
      }
    }
  }
  blockPreviewBusy = false;
}

function openBlockPreview(b, aspect, values, previewOptions = {}) {
  const options = blocksBrowser?.options || {};
  previewOptions = {...(blockPreviewAs ? {theme_context:browserThemeContext()} : {}),...previewOptions};
  const dialog = studioDialog('block-player', `<div class="row"><h2 id="studio-dialog-title">${esc(b.name)}</h2>
    <button type="button" class="btn sm" id="block-player-close">Close</button></div>
    <div class="block-player-screen">${blockPoster(b,aspect)}</div><p role="status" aria-live="polite"></p>
    <div class="row"><button type="button" class="btn sm" id="block-player-play">Pause</button>
    <label for="block-player-scrub">Time</label><input id="block-player-scrub" type="range" min="0" max="15" step="0.01" value="0">
    <output class="mono" id="block-player-time">0.00 / 0.00 s</output>
    <label><input type="checkbox" id="block-player-loop" checked> Loop</label></div>
    <div class="row"><label for="block-player-aspect">Aspect</label><select id="block-player-aspect">
    ${b.aspects.map(a => `<option ${a === aspect ? 'selected' : ''}>${esc(a)}</option>`).join('')}</select>
    ${b.overlay ? `<label for="block-player-background">Show over</label><select id="block-player-background">
      <option value="checker">Neutral checker</option><option value="sample">Sample still</option>
      ${options.project && options.slide ? '<option value="project">Paragraph picture</option>' : ''}</select>` : ''}</div>`,
    () => { blockPreviewSequence++; dialog.querySelector('video')?.pause(); });
  const refresh = () => {
    dialog.querySelector('video')?.pause();
    dialog.querySelector('.block-player-screen').style.aspectRatio = dialog.querySelector('#block-player-aspect').value.replace(':','/');
    requestBlockPreview(b,dialog.querySelector('#block-player-aspect').value,'motion',values,dialog,
      {scale:2,background:dialog.querySelector('#block-player-background')?.value || 'checker',project:options.project,slide:options.slide,...previewOptions});
  };
  dialog.querySelector('#block-player-close').onclick = () => dialog.close();
  dialog.querySelector('#block-player-aspect').onchange = refresh;
  const ground = dialog.querySelector('#block-player-background');
  if (ground) ground.onchange = refresh;
  refresh();
  return dialog;
}

function bindBlockPlayer(dialog, video) {
  const play = dialog.querySelector('#block-player-play');
  const scrub = dialog.querySelector('#block-player-scrub');
  const update = () => {
    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    scrub.max = duration || 15; scrub.value = video.currentTime;
    dialog.querySelector('#block-player-time').textContent = `${video.currentTime.toFixed(2)} / ${duration.toFixed(2)} s`;
    play.textContent = video.paused ? 'Play' : 'Pause';
  };
  play.onclick = () => video.paused ? video.play().catch(() => previewMessage(dialog,'Cannot start playback.')) : video.pause();
  scrub.oninput = () => { video.currentTime = Number(scrub.value); update(); };
  dialog.querySelector('#block-player-loop').onchange = e => { video.loop = e.target.checked; };
  video.ontimeupdate = video.onloadedmetadata = video.onplay = video.onpause = update;
  update();
}

async function applyBlockToSlide(pid, sid, selection) {
  return api(`/api/projects/${pid}/slides/${sid}`, {method:'PATCH',
    body:JSON.stringify({cues:{blocks:[selection]},picture_mode:'new',locked_media:true})});
}

async function blockProjectTarget(selection) {
  const projects = await api('/api/projects');
  projects.sort((a,b) => Number(b.id === state.blocksProjectId) - Number(a.id === state.blocksProjectId));
  const host = $('#block-project-target');
  host.innerHTML = `<label for="block-project">Project</label><select id="block-project"><option value="">Choose project</option>
    ${projects.map(p => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('')}</select><div id="block-slides"></div>`;
  $('#block-project').onchange = async e => {
    try {
      const pid = e.target.value;
      if (!pid) { $('#block-slides').innerHTML = ''; return; }
      const project = await api(`/api/projects/${pid}`);
      if ($('#block-project')?.value !== pid) return;
      $('#block-slides').innerHTML = `<label for="block-slide">Paragraph</label><select id="block-slide">${project.slides.filter(s => !s.on_camera).map((s,i) =>
        `<option value="${esc(s.id)}">${i+1} · ${esc(s.title || s.narration.slice(0,60))}</option>`).join('')}</select><button type="button" class="btn sm" id="block-apply">Apply block</button>`;
      $('#block-apply').onclick = async () => {
        try {
          await applyBlockToSlide(pid,$('#block-slide').value,selection);
          const b = blocksBrowser.items.find(b => b.ref === selection.block);
          if (b) b.recent = Date.now()/1000;
          paintBlocksGrid(); toast('Block applied');
        }
        catch (error) { toast(error.message,true); }
      };
    } catch (error) { toast(error.message,true); }
  };
  if (state.blocksProjectId) { $('#block-project').value = state.blocksProjectId; await $('#block-project').onchange({target:$('#block-project')}); }
}

async function openBlockPicker(pid, sid, selection = null, targets = null) {
  const p = state.project;
  selection ||= p?.slides.find(s => s.id === sid)?.cues?.blocks?.[0];
  await renderBlocks(selection?.block || '', {mode:'pick', project:pid, slide:sid, channel:p?.channel_id, selection, aspect:p?.aspect === 'portrait' ? '9:16' : p?.aspect === 'square' ? '1:1' : '16:9', onUse:async selection => {
    for (const id of targets || [sid]) await applyBlockToSlide(pid,id,selection);
    state.project = await api(`/api/projects/${pid}`);
    await render();
  }});
}

// The poster poll must not repaint the detail panel: that would drop a playing
// loop, a pending trial and focus. Only a still-pending poster is swapped in.
function blockPosterArrived() {
  document.querySelectorAll('#blocks-grid .block-card').forEach(card => {
    const b = bForCard(card), aspect = aForCard(card);
    const pending = card.querySelector('.block-placeholder');
    if (pending && b?.posters[aspect]) pending.outerHTML = blockPoster(b,aspect);
  });
  const b = blocksBrowser?.items.find(item => item.ref === blocksBrowser.selected);
  const pending = $('#block-trial-image .block-placeholder');
  if (!b || !pending) return;
  const aspect = $('#inspector [data-aspect][aria-pressed="true"]')?.dataset.aspect || b.aspects[0];
  if (b.posters[aspect]) pending.outerHTML = blockPoster(b, aspect);
}

async function toggleBlockFavourite(ref) {
  const item = blocksBrowser.items.find(b => b.ref === ref);
  const restoreFocus = document.activeElement?.dataset.star === ref && document.activeElement.closest('#blocks-grid');
  try {
    await api(`/api/blocks/${ref}/favourite`, {method:'POST',body:JSON.stringify({favourite:!item.favourite})});
    item.favourite = !item.favourite;
    paintBlocksGrid();
    if (restoreFocus) [...document.querySelectorAll('#blocks-grid [data-star]')].find(el => el.dataset.star === ref)?.focus();
    const star = $('#inspector [data-star]');
    if (star?.dataset.star === ref) {
      star.setAttribute('aria-pressed', String(item.favourite));
      star.textContent = `${item.favourite ? '★' : '☆'} Favourite`;
    }
  } catch (error) { toast(error.message,true); }
}

async function blockChannelTarget(ref) {
  const channels = await api('/api/channels');
  const host = $('#block-channel-target');
  host.innerHTML = `<label for="block-pin-channel">Channel</label><select id="block-pin-channel"><option value="">Choose channel</option>${channels.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select><button type="button" class="btn sm" id="block-pin-confirm">Add block</button><p role="status"></p>`;
  $('#block-pin-channel').value = blocksBrowser.options.channel || '';
  $('#block-pin-confirm').onclick = async () => {
    const cid = $('#block-pin-channel').value;
    if (!cid) return toast('Choose a channel.',true);
    try {
      await api(`/api/channels/${cid}/blocks`, {method:'POST',body:JSON.stringify({id:ref})});
      const b = blocksBrowser.items.find(b => b.ref === ref);
      if (!b.channels.includes(cid)) b.channels.push(cid);
      paintBlocksGrid(); host.querySelector('[role=status]').textContent = 'Block added to channel.';
    } catch (error) { toast(error.message,true); }
  };
}

async function openChannelBlockBrowser(cid, ref = '') {
  await renderBlocks(ref, {mode:'channel', channel:cid});
}

function blockCreationResult() {
  const r = state.blockResult;
  if (!r) return '';
  const usage = (r.usage || []).map(u => Object.entries(u.usage)
    .filter(([k,v]) => k.endsWith('tokens') && typeof v === 'number')
    .map(([k,v]) => `${v} ${k.replaceAll('_', ' ')}`).join(', ')).filter(Boolean).join('; ');
  return `<p>${esc(r.id ? `Saved ${r.id}` : (r.errors || []).join('; '))}</p>
    <p class="mono">One-off token usage: ${esc(usage || 'not reported by the provider')}</p>`;
}

async function describeBlock(button) {
  state.blockDescription = $('#block-description').value;
  button.disabled = true;
  try {
    const r = await api('/api/blocks/describe', {method:'POST', body:JSON.stringify({description:state.blockDescription})});
    state.blockResult = null;
    $('#block-result').textContent = 'Creating and checking…';
    watchJob(r.job, 'create block', async j => {
      state.blockResult = j.result || {errors:[j.error]};
      if (location.hash.startsWith('#/blocks') || $('#blocks-grid')) {
        const options = blocksBrowser?.options || {};
        await renderBlocks(state.blockResult.id || blocksBrowser?.selected || '', options);
      }
    });
  } catch (e) { toast(e.message, true); button.disabled = false; }
}


async function loadBlockPresets(options, channels = null) {
  channels ||= await api('/api/channels');
  const channelRows = await Promise.all(channels.filter(c => options.project && !options.channel ? false : !options.channel || c.id === options.channel).map(async c =>
    (await api(`/api/channels/${c.id}/block-presets`)).map(p => ({...p,scope:'channel',owner:c.id,badge:c.name}))));
  const project = options.project ? (await api(`/api/projects/${options.project}/block-presets`))
    .map(p => ({...p,scope:'project',owner:options.project,badge:'This project'})) : [];
  return [...project,...channelRows.flat()];
}
function blockPriority(b, presets, channel) {
  const index = presets.findIndex(p => p.block === b.ref);
  return (presets.some(p => p.block === b.ref && p.scope === 'project') ? 3 : 0)
    + (presets.some(p => p.block === b.ref && p.scope === 'channel') ? 2 : 0)
    + (channel && b.channels?.includes(channel) ? 1 + 1/(2+(b.channel_order?.[channel] || 0)) : 0)
    + (index < 0 ? 0 : 1/(2+index));
}
function blockPresetCard(p) {
  const index = blocksBrowser.presets.indexOf(p);
  return `<button type="button" class="btn block-preset" data-preset-index="${index}" ${p.missing ? 'disabled' : ''}>
    ${esc(p.name)} <span class="chip">${esc(p.badge)}</span>${p.missing ? ' · Block missing' : ''}</button>`;
}
function chooseBlockPreset(p) {
  blocksBrowser.selected = p.block;
  blocksBrowser.trial = {ref:p.block,values:p.values,preset:{id:p.id,scope:p.scope}};
  paintBlocksGrid(); paintBlockDetails(blocksBrowser.options.aspect || p.aspect);
  $('#block-play')?.focus();
}
async function blockPresetTarget(b, aspect, values) {
  const browser = blocksBrowser, projects = await api('/api/projects');
  if (blocksBrowser !== browser) return;
  const host = $('#block-preset-target');
  const choices = [
    ...projects.map(p => ({value:`projects/${p.id}`,label:p.title || p.id})),
    ...browser.channels.map(c => ({value:`channels/${c.id}`,label:c.name}))];
  const current = browser.presets.find(p => p.id === browser.trial?.preset?.id && p.scope === browser.trial.preset.scope);
  host.innerHTML = `<label for="preset-name">Preset name</label><input type="text" id="preset-name" maxlength="120" value="${esc(current?.name || b.name)}">
    <label for="preset-scope">Save to</label><select id="preset-scope">${choices.map(c => `<option value="${esc(c.value)}">${esc(c.label)}</option>`).join('')}
    ${browser.options.project && browser.options.channel ? '<option value="both">This project and channel</option>' : ''}</select>
    <button type="button" class="btn sm" id="preset-create">Save preset</button>
    ${current ? '<button type="button" class="btn sm" id="preset-update">Save changes to this preset</button><button type="button" class="btn sm ghost" id="preset-delete">Delete preset</button><button type="button" class="btn sm ghost" id="preset-count">Update slides using this preset…</button><div id="preset-affected"></div><small>Slides keep their copied values until you update them.</small>' : ''}
    ${current?.scope === 'project' && browser.options.channel ? '<button type="button" class="btn sm" id="preset-promote">Promote to channel…</button><div id="preset-promotion"></div>' : ''}
    <p role="status" id="preset-status"></p>`;
  $('#preset-scope').value = browser.options.project ? `projects/${browser.options.project}` : browser.options.channel ? `channels/${browser.options.channel}` : choices[0]?.value;
  const save = async (update = false, remove = false) => {
    try {
      if (remove) {
        const count = await api(`/api/${current.scope === 'project' ? 'projects' : 'channels'}/${current.owner}/block-presets/${current.id}/slides`);
        if (!confirm(`Delete ${current.name}? ${count.slides} slides use this preset. Slides keep their values.`)) return;
      }
      const target = $('#preset-scope').value;
      const targets = update || remove ? [`${current.scope === 'project' ? 'projects' : 'channels'}/${current.owner}`]
        : target === 'both' ? [`projects/${browser.options.project}`,`channels/${browser.options.channel}`] : [target];
      const payload = remove ? null : {name:$('#preset-name').value,block:b.ref,values:values(),aspect};
      for (const dest of targets) await api(`/api/${dest}/block-presets${update || remove ? '/'+current.id : ''}`, {
        method:remove ? 'DELETE' : update ? 'PATCH' : 'POST',
        ...(remove ? {} : {body:JSON.stringify(payload)})});
      browser.presets = await loadBlockPresets(browser.options,browser.channels);
      paintBlocksGrid(); $('#preset-status').textContent = remove ? 'Preset deleted. Slides keep their values.' : 'Preset saved. Slides keep their values.';
    } catch (e) { $('#preset-status').textContent = e.message; }
  };
  $('#preset-create').onclick = () => save();
  if ($('#preset-promote')) $('#preset-promote').onclick = async () => {
    try {
      const url = `/api/projects/${current.owner}/block-presets/${current.id}`;
      const count = await api(url+'/slides');
      $('#preset-promotion').innerHTML = `<p>Copy this preset to the project’s channel. ${count.slides} slides reference the project preset; their values stay unchanged.</p>
        <label><input type="checkbox" id="preset-move"> Move: remove the project preset after copying</label>
        <label><input type="checkbox" id="preset-repoint"> Point ${count.slides} slides at the channel preset</label>
        <button type="button" class="btn sm" id="preset-promote-confirm">Promote preset</button>`;
      $('#preset-promote-confirm').onclick = async () => {
        try {
          await api(url+'/promote',{method:'POST',body:JSON.stringify({move:$('#preset-move').checked,point_slides:$('#preset-repoint').checked})});
          browser.presets = await loadBlockPresets(browser.options,browser.channels);
          paintBlocksGrid(); $('#preset-promotion').textContent = 'Promoted. Slide values kept.';
        } catch (e) { $('#preset-status').textContent = e.message; }
      };
    } catch (e) { $('#preset-status').textContent = e.message; }
  };
  if (current) $('#preset-count').onclick = async () => {
    try {
      const url = `/api/${current.scope === 'project' ? 'projects' : 'channels'}/${current.owner}/block-presets/${current.id}/slides`;
      const count = await api(url);
      $('#preset-affected').innerHTML = `<p>${count.slides} slides use this preset.</p><button type="button" class="btn sm" id="preset-apply-slides" ${count.slides ? '' : 'disabled'}>Update ${count.slides} slides</button>`;
      $('#preset-apply-slides').onclick = async () => {
        try { const result = await api(url,{method:'POST'}); $('#preset-status').textContent = `${result.slides} slides updated`; }
        catch (e) { $('#preset-status').textContent = e.message; }
      };
    } catch (e) { $('#preset-status').textContent = e.message; }
  };
  if (current) { $('#preset-update').onclick = () => save(true); $('#preset-delete').onclick = () => save(false,true); }
}


function browserThemeContext() {
  const [scope,owner] = blockPreviewAs.split(':');
  return {scope,owner};
}

function observeThemedPosters() {
  themedPosterObserver?.disconnect();
  if (!blockPreviewAs) return;
  const browser = blocksBrowser, choice = blockPreviewAs;
  themedPosterObserver = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      themedPosterObserver.unobserve(entry.target);
      if (entry.target.classList.contains('themed-pending') || !entry.target.getAttribute('src')) themedPosterQueue.push({target:entry.target,browser,choice});
    }
    drainThemedPosters();
  });
  document.querySelectorAll('[data-themed-ref]').forEach(img => themedPosterObserver.observe(img));
}

async function drainThemedPosters() {
  if (themedPosterBusy) return;
  themedPosterBusy = true;
  while (themedPosterQueue.length) {
    const {target,browser,choice} = themedPosterQueue.shift();
    if (!target.isConnected || blocksBrowser !== browser || blockPreviewAs !== choice) continue;
    const ref = target.dataset.themedRef, aspect = target.dataset.themedAspect;
    const key = `${choice}/${ref}/${aspect}`;
    try {
      let url = themedPosterCache.get(key);
      if (!url) {
        const [scope,id] = choice.split(':');
        const result = await api('/api/blocks/theme-sheet',{method:'POST',body:JSON.stringify({scope,id,ref,aspect,session:blockPreviewSession+'-posters',sequence:++themedPosterSequence})});
        url = result.posters?.[0]?.url;
        if (url && blocksBrowser === browser) themedPosterCache.set(key,url);
      }
      if (url && target.isConnected && blockPreviewAs === choice) { target.src = url; target.classList.remove('themed-pending'); }
    } catch (e) { if (target.isConnected) target.alt = `Preview unavailable: ${e.message}`; }
  }
  themedPosterBusy = false;
}

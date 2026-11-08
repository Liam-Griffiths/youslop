/* Shared library and pick browser. Scratch values never save themselves. */
let blocksBrowser = null;

async function renderBlocks(path = '', options = {}) {
  const route = location.hash;
  const query = path.startsWith('search/') ? decodeURIComponent(path.slice(7)) : '';
  const selected = query ? '' : decodeURIComponent(path);
  const items = await api('/api/blocks');
  if (location.hash !== route) return;
  if (!options.mode && !location.hash.startsWith('#/blocks')) return;
  blocksBrowser = {items, selected, options};
  view.innerHTML = `<h1>Blocks</h1><p>Local blocks for titles, numbers and stories. Built in, from packs, or yours.</p>
    ${options.mode === 'pick' ? '<button type="button" class="btn ghost" id="block-picker-close">Back to project</button>' : ''}
    <div class="blocks-browser"><aside class="blocks-filters" aria-label="Block filters">
    <label for="blocks-search">Find a block</label><input type="search" id="blocks-search" value="${esc(query)}" placeholder="Name, tag or variable">
    ${[['category','Category', [...new Set(items.map(b => b.category))].sort()],
       ['aspect','Aspect',['16:9','9:16']], ['source','Source',['built-in','packs','mine']]].map(([key,label,values]) => `
      <label for="blocks-${key}">${label}</label><select id="blocks-${key}"><option value="">All</option>
      ${values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('')}</select>`).join('')}
    <label><input type="checkbox" id="blocks-data"> Works with data</label>
    <label for="blocks-sort">Sort</label><select id="blocks-sort"><option value="recommended">Recommended</option><option value="name">A–Z</option></select>
    <button type="button" class="btn ghost" id="blocks-clear">Clear filters</button></aside>
    <section aria-label="Blocks"><p id="blocks-count" class="mono" role="status"></p><div id="blocks-grid" class="blocks-grid"></div></section></div>`;
  for (const id of ['search','category','aspect','source','data','sort']) $(`#blocks-${id}`).oninput = paintBlocksGrid;
  $('#blocks-clear').onclick = () => { for (const el of document.querySelectorAll('.blocks-filters input,.blocks-filters select')) {
    if (el.type === 'checkbox') el.checked = false; else el.value = el.id === 'blocks-sort' ? 'recommended' : '';
  } paintBlocksGrid(); };
  if (options.mode === 'pick') $('#block-picker-close').onclick = () => render();
  paintBlocksGrid();
  paintBlockDetails();
  if (selected) $('#block-play')?.focus();
  const result = await api('/api/blocks/posters', {method:'POST'});
  if (result.job) {
    const browser = blocksBrowser;
    const refresh = async () => {
      if (blocksBrowser !== browser || !$('#blocks-grid')) return;
      browser.items = await api('/api/blocks');
      if (blocksBrowser !== browser || !$('#blocks-grid')) return;
      paintBlocksGrid(); blockPosterArrived();
      const job = await api(`/api/jobs/${result.job}`);
      if (job.state === 'running') setTimeout(() => refresh().catch(e => toast(e.message, true)), 2000);
    };
    setTimeout(() => refresh().catch(e => toast(e.message, true)), 2000);
  }
}

function paintBlocksGrid() {
  const q = $('#blocks-search').value.toLowerCase();
  const category = $('#blocks-category').value, aspect = $('#blocks-aspect').value, source = $('#blocks-source').value;
  let items = blocksBrowser.items.filter(b => [b.name,b.description,...b.tags,...Object.keys(b.variables)].join(' ').toLowerCase().includes(q)
    && (!category || b.category === category) && (!aspect || b.aspects.includes(aspect))
    && (!source || b.source === source || source === 'packs' && b.ref.startsWith('pack/'))
    && (!$('#blocks-data').checked || b.works_with_data));
  if ($('#blocks-sort').value === 'name') items.sort((a,b) => a.name.localeCompare(b.name));
  $('#blocks-count').textContent = `${items.length} blocks`;
  $('#blocks-grid').innerHTML = items.map(b => {
    const a = aspect || b.aspects[0];
    return `<button type="button" class="block-card" data-ref="${esc(b.ref)}" aria-pressed="${b.ref === blocksBrowser.selected}">
      ${blockPoster(b,a)}<strong>${esc(b.name)}</strong><span>${esc(b.description)}</span><span class="mono">${esc(b.source)} · ${esc(b.category)}</span></button>`;
  }).join('') || '<p>No blocks match. Clear filters, or <a href="#/library">describe a block in Library</a>.</p>';
  const cards = [...document.querySelectorAll('#blocks-grid .block-card')];
  cards.forEach((card,i) => {
    card.onclick = () => {
      if (!blocksBrowser.options.mode) go(`#/blocks/${card.dataset.ref}`);
      else { blocksBrowser.selected = card.dataset.ref; paintBlocksGrid(); paintBlockDetails(); $('#block-play')?.focus(); }
    };
    let hover;
    card.onmouseenter = () => { if (!matchMedia('(prefers-reduced-motion: reduce)').matches)
      hover = setTimeout(() => requestBlockPreview(bForCard(card), aForCard(card), 'motion', {}, card), 400); };
    card.onmouseleave = () => { clearTimeout(hover); card.querySelector('video')?.remove(); };
    card.onblur = card.onmouseleave;
    card.onkeydown = e => {
      if (e.code === 'Space') { e.preventDefault(); requestBlockPreview(bForCard(card), aForCard(card), 'motion', {}, card); return; }
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const columns = getComputedStyle($('#blocks-grid')).gridTemplateColumns.split(' ').length;
      const step = {ArrowLeft:-1,ArrowRight:1,ArrowUp:-columns,ArrowDown:columns}[e.key];
      cards[Math.max(0,Math.min(cards.length-1,i+step))]?.focus();
    };
  });
}

function blockPoster(block, aspect) {
  return block.posters[aspect] ? `<img src="${esc(block.posters[aspect])}" alt="${esc(block.name)}, ${esc(aspect)} preview">`
    : `<span class="block-placeholder" role="img" aria-label="${esc(block.name)}, ${esc(aspect)} preview pending">${esc(block.name)}<small>Poster pending</small></span>`;
}

function paintBlockDetails(aspect) {
  const b = blocksBrowser.items.find(item => item.ref === blocksBrowser.selected);
  const panel = $('#inspector');
  if (!b) { panel.innerHTML = blocksBrowser.selected ? '<p>Block not found. Choose a block from the grid.</p>' : ''; return; }
  blockPreviewSequence++;
  aspect ||= b.aspects[0];
  const scratch = blocksBrowser.trial?.ref === b.ref ? blocksBrowser.trial.values : {};
  panel.innerHTML = `<div class="block-detail"><h2>${esc(b.name)}</h2><p>${esc(b.description)}</p><div id="block-trial-image">${blockPoster(b,aspect)}</div>
    <div class="row"><button type="button" class="btn sm" id="block-play">Play · ¼ size</button>
      ${b.aspects.map(a => `<button type="button" class="btn sm" aria-pressed="${a === aspect}" data-aspect="${esc(a)}">${esc(a)}</button>`).join('')}</div>
    <p id="block-trial-status" role="status" aria-live="polite"></p>
    <h3>Try it</h3><form id="block-trial">${Object.entries(b.variables).map(([key,spec],i) => blockTrialField(key,{...spec,default:scratch[key] ?? spec.default},i)).join('')}
    <button type="button" class="btn sm ghost" id="block-reset">Reset to defaults</button></form>
    <button type="button" class="btn" id="block-use">${blocksBrowser.options.mode === 'pick' ? 'Use here' : 'Use in a project…'}</button>
    <p class="mono block-meta">${esc(blockDuration(b.duration))} · ${esc(b.source)} · ${esc(b.licence)}<br>${esc(b.check_status)}
    ${b.origin ? `<br>Origin: ${esc(Object.entries(b.origin).map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}`).join(' · '))}` : ''}</p>
    <div id="block-project-target"></div>
    <a href="#/library">Create a block or add one to a channel in Library</a></div>`;
  const detail = panel.querySelector('.block-detail');
  const values = () => readBlockTrial(b, detail);
  const refresh = kind => {
    try { requestBlockPreview(b,aspect,kind,values(),detail); }
    catch (e) { $('#block-trial-status').textContent = e.message; }
  };
  detail.querySelector('form').onsubmit = e => e.preventDefault();
  let timer;
  detail.querySelector('form').oninput = () => {
    clearTimeout(timer);
    // Invalidate immediately, before the debounce, so old pixels cannot win.
    blockPreviewSequence++;
    blocksBrowser.trial = {ref:b.ref,values:Object.fromEntries([...detail.querySelectorAll('[data-key]')].map(el => [el.dataset.key,el.value]))};
    detail.querySelectorAll('[data-max]').forEach(input => {
      input.nextElementSibling.textContent = `${input.dataset.max - input.value.length} characters remaining`;
    });
    timer = setTimeout(() => { if (detail.isConnected) refresh('trial'); },600);
  };
  $('#block-reset').onclick = () => { blocksBrowser.trial = null; paintBlockDetails(aspect); const fresh = $('#inspector .block-detail'); requestBlockPreview(b,aspect,'trial',readBlockTrial(b,fresh),fresh); };
  $('#block-play').onclick = () => refresh('motion');
  $('#block-use').onclick = async () => {
    try {
      const selection = {block:b.ref, vars:values()};
      if (blocksBrowser.options.mode === 'pick') await blocksBrowser.options.onUse(selection);
      else await blockProjectTarget(selection);
    } catch (e) { toast(e.message,true); }
  };
  panel.querySelectorAll('[data-aspect]').forEach(button => { button.onclick = () => paintBlockDetails(button.dataset.aspect); });
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
  return `<label for="${id}">${esc(key)} · ${esc(spec.type)}</label>${field}`;
}

function readBlockTrial(b, detail) {
  return Object.fromEntries([...detail.querySelectorAll('[data-key]')].map(el => {
    let v = el.value;
    if (el.dataset.type === 'number') v = Number(v);
    if (el.dataset.type === 'table' && v.trim().startsWith('[')) v = JSON.parse(v);
    return [el.dataset.key,v];
  }));
}

// One preview request in flight across grid, details and successive browsers.
let blockPreviewSequence = 0, blockPreviewBusy = false, blockPreviewPending = null;
const blockPreviewSession = Math.random().toString(36).slice(2) + Date.now().toString(36);
async function requestBlockPreview(b, aspect, kind, values, target) {
  const sequence = ++blockPreviewSequence;
  blockPreviewPending = {b,aspect,kind,values,target,sequence};
  if (blockPreviewBusy) return;
  blockPreviewBusy = true;
  while (blockPreviewPending) {
    const request = blockPreviewPending;
    blockPreviewPending = null;
    const {b,aspect,kind,values,target,sequence} = request;
    if (!target.isConnected || sequence !== blockPreviewSequence) continue;
    const status = target.querySelector('[role="status"]');
    if (status) status.textContent = 'Refreshing preview…';
    try {
      const result = await api(`/api/blocks/${b.ref}/preview`, {method:'POST',body:JSON.stringify({
        values,aspect,kind,session:blockPreviewSession,sequence})});
      if (sequence !== blockPreviewSequence || !target.isConnected || target.matches(':hover') === false && target.classList.contains('block-card') && document.activeElement !== target) continue;
      if (result.url) {
        const host = target.querySelector('#block-trial-image') || target;
        host.querySelectorAll('video').forEach(v => v.remove());
        if (kind === 'trial') host.innerHTML = `<img src="${esc(result.url)}" alt="${esc(b.name)}, ${esc(aspect)} trial preview">`;
        else {
          const video = document.createElement('video');
          video.src = result.url; video.muted = true; video.loop = true; video.controls = !target.classList.contains('block-card'); video.playsInline = true;
          video.setAttribute('aria-label', `${b.name} motion preview`);
          document.querySelectorAll('.block-card video,.block-detail video').forEach(v => v.remove());
          if (host.id === 'block-trial-image') host.innerHTML = '';  // The loop replaces the still.
          host.appendChild(video); video.play().catch(() => {});
        }
      }
      if (status) status.textContent = result.disabled ? 'Previews disabled for snapshots.' : 'Preview ready.';
    } catch (e) { if (sequence === blockPreviewSequence && status) status.textContent = e.message; }
  }
  blockPreviewBusy = false;
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
        try { await applyBlockToSlide(pid,$('#block-slide').value,selection); toast('Block applied'); }
        catch (error) { toast(error.message,true); }
      };
    } catch (error) { toast(error.message,true); }
  };
}

async function openBlockPicker(pid, sid) {
  await renderBlocks('', {mode:'pick', onUse:async selection => {
    await applyBlockToSlide(pid,sid,selection);
    state.project = await api(`/api/projects/${pid}`);
    await render();
  }});
}

// The poster poll must not repaint the detail panel: that would drop a playing
// loop, a pending trial and focus. Only a still-pending poster is swapped in.
function blockPosterArrived() {
  const b = blocksBrowser?.items.find(item => item.ref === blocksBrowser.selected);
  const pending = $('#block-trial-image .block-placeholder');
  if (!b || !pending) return;
  const aspect = $('#inspector [data-aspect][aria-pressed="true"]')?.dataset.aspect || b.aspects[0];
  if (b.posters[aspect]) pending.outerHTML = blockPoster(b, aspect);
}

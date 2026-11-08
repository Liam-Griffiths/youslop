/* App-wide block browser. Trial editing and picker actions continue in T12.8b. */
let blocksBrowser = null;

async function renderBlocks(path = '') {
  const query = path.startsWith('search/') ? decodeURIComponent(path.slice(7)) : '';
  const selected = query ? '' : decodeURIComponent(path);
  const items = await api('/api/blocks');
  if (!location.hash.startsWith('#/blocks')) return;
  blocksBrowser = {items, selected};
  view.innerHTML = `<h1>Blocks</h1><p>Local blocks for titles, numbers and stories. Built in, from packs, or yours.</p>
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
  paintBlocksGrid();
  paintBlockDetails();
  const result = await api('/api/blocks/posters', {method:'POST'});
  if (result.job) {
    const browser = blocksBrowser;
    const refresh = async () => {
      if (blocksBrowser !== browser || !$('#blocks-grid')) return;
      browser.items = await api('/api/blocks');
      if (blocksBrowser !== browser || !$('#blocks-grid')) return;
      paintBlocksGrid(); paintBlockDetails();
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
    card.onclick = () => go(`#/blocks/${card.dataset.ref}`);
    card.onkeydown = e => {
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
  aspect ||= b.aspects[0];
  panel.innerHTML = `<div class="block-detail"><h2>${esc(b.name)}</h2><p>${esc(b.description)}</p>${blockPoster(b,aspect)}
    <div class="row">${b.aspects.map(a => `<button type="button" class="btn sm" aria-pressed="${a === aspect}" data-aspect="${esc(a)}">${esc(a)}</button>`).join('')}</div>
    <p>${esc(b.source)} · ${esc(b.licence)}</p><p>${esc(b.check_status)}</p>
    ${b.origin ? `<p>Origin: ${esc(Object.entries(b.origin).map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}`).join(' · '))}</p>` : ''}
    <p class="mono">${esc(blockDuration(b.duration))}</p><h3>Variables</h3>
    <dl>${Object.entries(b.variables).map(([name,spec]) => `<dt>${esc(name)} · ${esc(spec.type)}${spec.max_length ? ` · up to ${spec.max_length}` : ''}</dt><dd>${esc(blockDefault(spec))}</dd>`).join('')}</dl>
    <a href="#/library">Create a block or add one to a channel in Library</a></div>`;
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

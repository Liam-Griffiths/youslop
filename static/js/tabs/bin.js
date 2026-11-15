/* Reusable project bin; files and references stay separate from the edit. */
function binInitial(pid) { return {pid, items:[], labels:[], selected:[], anchor:null, drafts:{}, labelText:'', compose:null, query:'', kind:'', label:'', list:false}; }
let binView = binInitial(null), binWrites = Promise.resolve();
async function paintBin() {
  const pid = state.project.id;
  if (binView.pid !== pid) binView = binInitial(pid);
  try {
    const data = await api(`/api/projects/${pid}/bin`);
    if (state.project?.id !== pid || !$('#project-bin')) return;
    Object.assign(binView, data);
    binShell();
  } catch (e) { toast(e.message, true); }
}
function binShell() {
  const host = $('#project-bin');
  if (!host) return;
  const focused = document.activeElement, focusId = host.contains(focused) ? focused.id : null;
  const caret = focused?.selectionStart;
  host.innerHTML = `<input id="bin-files" type="file" multiple hidden accept="image/*,video/*,audio/*">
    <form id="bin-compose" ${binView.compose ? '' : 'hidden'}><label for="bin-new-title">Title</label><input type="text" id="bin-new-title" value="${esc(binView.compose?.title || '')}"><label for="bin-new-note">Note</label><textarea id="bin-new-note" rows="4">${esc(binView.compose?.note || '')}</textarea><button class="btn">Save note</button><button class="btn" type="button" id="bin-cancel">Cancel</button></form>
    <div class="bin-toolbar"><label class="bin-sr-only" for="bin-search">Search the bin</label><input id="bin-search" type="search" placeholder="Search the bin" value="${esc(binView.query)}">
    <label class="bin-sr-only" for="bin-kind">Kind</label><select id="bin-kind"><option value="">All kinds</option>${['note','image','clip','audio','link'].map(k=>`<option ${binView.kind===k?'selected':''}>${k}</option>`).join('')}</select>
    <label class="bin-sr-only" for="bin-label">Label</label><select id="bin-label"><option value="">All labels</option>${binView.labels.map(l=>`<option ${binView.label===l?'selected':''}>${esc(l)}</option>`).join('')}</select>
    <div class="bin-views" role="group" aria-label="Bin view"><button class="btn sm" id="bin-view-grid" aria-pressed="${!binView.list}">Grid</button><button class="btn sm" id="bin-view-list" aria-pressed="${binView.list}">List</button></div><button type="button" class="btn sm" id="bin-edit-labels">Labels</button></div>
    <p class="bin-hint">Drop files · paste text or a link · Shift selects a range · Ctrl/⌘ toggles items</p>
    <div class="bin-work"><div id="bin-grid"></div><aside id="bin-panel" aria-label="Selected bin item"></aside></div>`;
  $('#bin-add').onclick = () => $('#bin-files').click();
  $('#bin-files').onchange = e => binUpload(e.target.files);
  $('#bin-edit-labels').onclick = () => openLabelsEditor({getLabels:()=>binView.labels, change:payload=>binSend('/labels', 'PATCH', payload)});
  $('#bin-new').onclick = () => { binView.compose = {title:'', note:''}; $('#bin-compose').hidden = false; $('#bin-new-title').focus(); };
  $('#bin-cancel').onclick = () => { binView.compose = null; $('#bin-compose').hidden = true; };
  for (const key of ['title','note']) $('#bin-new-'+key).oninput = e => { binView.compose[key] = e.target.value; };
  $('#bin-compose').onsubmit = async e => { e.preventDefault(); if (await binSend('/note', 'POST', {...binView.compose})) { binView.compose = null; binShell(); } };
  for (const view of ['grid','list']) $('#bin-view-'+view).onclick = () => {
    binView.list = view==='list';
    $('#bin-view-grid').setAttribute('aria-pressed', !binView.list);
    $('#bin-view-list').setAttribute('aria-pressed', binView.list);
    binGrid();
  };
  for (const [id,key] of [['search','query'],['kind','kind'],['label','label']]) $('#bin-'+id).oninput = e => { binView[key] = e.target.value; binGrid(); };
  binGrid(); binPanel();
  if (focusId) {
    const target = document.getElementById(focusId);
    target?.focus();
    if (caret != null && target?.type === 'text') target.setSelectionRange(caret, caret);
  }
}
function binGrid() {
  const host = $('#bin-grid'), q = binView.query.toLowerCase();
  host.className = binView.list ? 'bin-grid bin-list' : 'bin-grid';
  const items = binView.items.filter(i=>(!binView.kind || i.kind===binView.kind) && (!binView.label || i.labels.includes(binView.label)) && `${i.title} ${i.note}`.toLowerCase().includes(q));
  host.innerHTML = items.map(i=>`<button type="button" class="bin-tile" id="bin-tile-${esc(i.id)}" data-item="${esc(i.id)}" aria-pressed="${binView.selected.includes(i.id)}">
    ${i.thumb?`<img loading="lazy" src="${esc(i.thumb)}" alt="">`:`<span class="bin-excerpt">${esc(i.note.slice(0,160) || i.url)}</span>`}
    <span class="kicker">${esc(i.kind)}</span><strong class="bin-title" title="${esc(i.title)}">${esc(i.title)}</strong><span class="bin-labels">${i.labels.map(l=>`<span class="chip">${esc(l)}</span>`).join(' ')}</span>
    <span class="bin-meta mono">${i.duration?fmtTime(i.duration):''} ${i.width?`${i.width}×${i.height}`:''} ${i.size?`${(i.size/1048576).toFixed(2)} MB`:''}</span></button>`).join('') || '<p class="sub">No items match. Add files or a note to this bin.</p>';
  host.querySelectorAll('[data-item]').forEach(button=>button.onclick=e=>binSelect(button.dataset.item, e, items.map(i=>i.id)));
}
function binSelect(id, e, visible) {
  const selected = new Set(binView.selected);
  if (e.shiftKey && visible.includes(binView.anchor)) {
    const a = visible.indexOf(binView.anchor), b = visible.indexOf(id);
    if (!e.ctrlKey && !e.metaKey) selected.clear();
    visible.slice(Math.min(a,b), Math.max(a,b)+1).forEach(i=>selected.add(i));
  } else {
    if (!e.ctrlKey && !e.metaKey) selected.clear();
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    binView.anchor = id;
  }
  binView.selected = [...selected];
  binGrid(); binPanel();
  document.getElementById('bin-tile-'+id)?.focus();
}
function binPanel() {
  const items = binView.items.filter(i=>binView.selected.includes(i.id)), item = items.length===1 ? items[0] : null, panel = $('#bin-panel');
  if (!items.length) { panel.innerHTML = '<p class="sub">Select an item to edit its title, labels and note.</p>'; return; }
  const draft = item ? (binView.drafts[item.id] ||= {}) : {};
  panel.innerHTML = `<p class="sub">${items.length} selected (including any hidden by filters)</p>` + (item ? `<label for="bin-title">Title</label><input type="text" id="bin-title" value="${esc(draft.title ?? item.title)}">` : '') + `
    <label for="bin-item-label">Label selected items</label><input type="text" id="bin-item-label" value="${esc(binView.labelText)}" list="bin-label-options" placeholder="Type a label"><datalist id="bin-label-options">${binView.labels.map(l=>`<option value="${esc(l)}"></option>`).join('')}</datalist>
    <button type="button" class="btn sm" id="bin-label-add">Add label</button><button type="button" class="btn sm" id="bin-label-remove">Remove label</button>
    <div id="bin-label-buttons">${binView.labels.map((l,n)=>{
      const count = items.filter(i=>i.labels.includes(l)).length;
      return `<button type="button" class="btn sm" data-label="${n}" aria-pressed="${count===items.length ? 'true' : count ? 'mixed' : 'false'}">${n<9?n+1+' ':''}${esc(l)}${count && count<items.length ? ' (some)' : ''}</button>`;
    }).join('')}</div>` + (item ? `
    <label for="bin-note">Note</label><textarea id="bin-note" rows="5">${esc(draft.note ?? item.note)}</textarea><button class="btn" id="bin-save">Save changes</button>
    <p class="sub">Source: ${esc(item.source)}</p><p>Used in: ${item.used_in.map(id=>`<a href="#/p/${binView.pid}/edit">${esc(id)}</a>`).join(', ') || 'No paragraphs'}</p>
    ${item.kind==='link'?`<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">Open link</a>`:''}<button class="btn sm" id="bin-delete">Remove item</button>` : '');
  if (item) {
    for (const key of ['title','note']) $('#bin-'+key).oninput = e => { draft[key] = e.target.value; };
    $('#bin-save').onclick = () => binSave(item.id);
    $('#bin-delete').onclick = () => binSend('/'+item.id, 'DELETE');
  }
  $('#bin-item-label').oninput = e => { binView.labelText = e.target.value; };
  $('#bin-item-label').onkeydown = e => { if(e.key==='Enter') { e.preventDefault(); binTypedLabel(e.shiftKey ? 'remove' : 'add'); } };
  $('#bin-label-add').onclick = () => binTypedLabel('add');
  $('#bin-label-remove').onclick = () => binTypedLabel('remove');
  panel.querySelectorAll('[data-label]').forEach(button=>button.onclick=()=>binToggleLabel(Number(button.dataset.label)));
}
async function binSave(id) {
  const view = binView, draft = {...view.drafts[id]};
  if (await binSend('/'+id, 'PATCH', draft)) {
    for (const key of Object.keys(draft)) if (view.drafts[id]?.[key] === draft[key]) delete view.drafts[id][key];
  }
}
function binTypedLabel(action) {
  const label = binView.labelText.trim();
  if (label) return binSend('/selection', 'PATCH', {ids:[...binView.selected], label, action});
}
function binToggleLabel(n) {
  const items = binView.items.filter(i=>binView.selected.includes(i.id)), label = binView.labels[n];
  if (items.length && label) return binSend('/selection', 'PATCH', {ids:items.map(i=>i.id), label, action:'toggle'});
}
function binSend(path, method, payload) {
  const view = binView;
  // Serialize writes so a slow response cannot replace a newer vocabulary or selection.
  const request = async () => {
    try {
      const data = await api(`/api/projects/${view.pid}/bin${path}`, {method, body:payload instanceof FormData?payload:payload?JSON.stringify(payload):undefined, editLabel:'Edit project bin', editGesture:crypto.randomUUID()});
      if (view !== binView || state.project?.id!==view.pid) return true;
      if (path==='/labels' && payload.old===view.label) view.label = payload.action==='delete' ? '' : payload.new;
      Object.assign(view, data);
      view.selected = view.selected.filter(id=>data.items.some(i=>i.id===id));
      if ($('#project-bin')) binShell();
      return true;
    } catch(e) { toast(e.message, true); return false; }
  };
  const result = binWrites.then(request);
  binWrites = result.catch(()=>{});
  return result;
}
function binUpload(files) {
  if (!files.length) return;
  const data = new FormData(); for(const file of files) data.append('files',file);
  return binSend('', 'POST', data);
}
function binActive(e) { return state.stage==='dashboard' && $('#project-bin') && !e.target.closest('input,textarea,select,dialog,[contenteditable="true"]') && !document.querySelector('dialog[open]'); }
document.addEventListener('keydown', e=>{
  if (binActive(e) && !e.ctrlKey && !e.metaKey && !e.altKey && /^[1-9]$/.test(e.key)) { e.preventDefault(); binToggleLabel(Number(e.key)-1); }
});
document.addEventListener('paste', e=>{
  if (!binActive(e)) return;
  const text = e.clipboardData.getData('text/plain').trim();
  if (!text) return;
  e.preventDefault();
  const link = /^https?:\/\/\S+$/.test(text);
  binSend(link?'/link':'/note', 'POST', link?{url:text}:{title:text.split('\n')[0].slice(0,100),note:text});
});
for (const type of ['dragenter','dragover','dragleave','drop']) document.addEventListener(type, e=>{
  const dashboard = e.target.closest('.dashboard-layout');
  if (!dashboard || !e.dataTransfer?.types.includes('Files')) return;
  e.preventDefault();
  dashboard.classList.toggle('bin-dragging', type==='dragenter' || type==='dragover');
  if (type==='drop') binUpload(e.dataTransfer.files);
});

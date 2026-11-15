/* Reusable project bin; files and references stay separate from the edit. */
let binView = {pid:null, items:[], labels:[], selected:null, query:'', kind:'', label:'', list:false};
async function paintBin() {
  const pid = state.project.id;
  if (binView.pid !== pid) binView = {pid, items:[], labels:[], selected:null, query:'', kind:'', label:'', list:false};
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
  host.innerHTML = `<input id="bin-files" type="file" multiple hidden accept="image/*,video/*,audio/*">
    <form id="bin-compose" hidden><label for="bin-new-title">Title</label><input type="text" id="bin-new-title"><label for="bin-new-note">Note</label><textarea id="bin-new-note" rows="4"></textarea><button class="btn">Save note</button><button class="btn" type="button" id="bin-cancel">Cancel</button></form>
    <div class="bin-toolbar"><label class="bin-sr-only" for="bin-search">Search the bin</label><input id="bin-search" type="search" placeholder="Search the bin" value="${esc(binView.query)}">
    <label class="bin-sr-only" for="bin-kind">Kind</label><select id="bin-kind"><option value="">All kinds</option>${['note','image','clip','audio','link'].map(k=>`<option ${binView.kind===k?'selected':''}>${k}</option>`).join('')}</select>
    <label class="bin-sr-only" for="bin-label">Label</label><select id="bin-label"><option value="">All labels</option>${binView.labels.map(l=>`<option ${binView.label===l?'selected':''}>${esc(l)}</option>`).join('')}</select>
    <div class="bin-views" role="group" aria-label="Bin view"><button class="btn sm" id="bin-view-grid" aria-pressed="${!binView.list}">Grid</button><button class="btn sm" id="bin-view-list" aria-pressed="${binView.list}">List</button></div></div>
    <p class="bin-hint">Drop files here · paste text or a link</p>
    <div class="bin-work"><div id="bin-grid"></div><aside id="bin-panel" aria-label="Selected bin item"></aside></div>`;
  $('#bin-add').onclick = () => $('#bin-files').click();
  $('#bin-files').onchange = e => binUpload(e.target.files);
  $('#bin-new').onclick = () => { $('#bin-compose').hidden = false; $('#bin-new-title').focus(); };
  $('#bin-cancel').onclick = () => { $('#bin-compose').hidden = true; };
  $('#bin-compose').onsubmit = e => { e.preventDefault(); binSend('/note', 'POST', {title:$('#bin-new-title').value, note:$('#bin-new-note').value}); };
  for (const view of ['grid','list']) $('#bin-view-'+view).onclick = () => {
    binView.list = view==='list';
    $('#bin-view-grid').setAttribute('aria-pressed', !binView.list);
    $('#bin-view-list').setAttribute('aria-pressed', binView.list);
    binGrid();
  };
  for (const [id,key] of [['search','query'],['kind','kind'],['label','label']]) $('#bin-'+id).oninput = e => { binView[key] = e.target.value; binGrid(); };
  binGrid(); binPanel();
}
function binGrid() {
  const host = $('#bin-grid'), q = binView.query.toLowerCase();
  host.className = binView.list ? 'bin-grid bin-list' : 'bin-grid';
  const items = binView.items.filter(i=>(!binView.kind || i.kind===binView.kind) && (!binView.label || i.labels.includes(binView.label)) && `${i.title} ${i.note}`.toLowerCase().includes(q));
  host.innerHTML = items.map(i=>`<button type="button" class="bin-tile" data-item="${esc(i.id)}" aria-pressed="${i.id===binView.selected}">
    ${i.thumb?`<img loading="lazy" src="${esc(i.thumb)}" alt="">`:`<span class="bin-excerpt">${esc(i.note.slice(0,160) || i.url)}</span>`}
    <span class="kicker">${esc(i.kind)}</span><strong class="bin-title" title="${esc(i.title)}">${esc(i.title)}</strong><span class="bin-labels">${i.labels.map(l=>`<span class="chip">${esc(l)}</span>`).join(' ')}</span>
    <span class="bin-meta mono">${i.duration?fmtTime(i.duration):''} ${i.width?`${i.width}×${i.height}`:''} ${i.size?`${(i.size/1048576).toFixed(2)} MB`:''}</span></button>`).join('') || '<p class="sub">No items match. Add files or a note to this bin.</p>';
  host.querySelectorAll('[data-item]').forEach(button=>button.onclick=()=>{binView.selected=button.dataset.item; binGrid(); binPanel(); $('#bin-panel').tabIndex=-1; $('#bin-panel').focus();});
}
function binPanel() {
  const item = binView.items.find(i=>i.id===binView.selected), panel = $('#bin-panel');
  if (!item) { panel.innerHTML = '<p class="sub">Select an item to edit its title, labels and note.</p>'; return; }
  panel.innerHTML = `<label for="bin-title">Title</label><input type="text" id="bin-title" value="${esc(item.title)}">
    <label for="bin-item-label">Add a label</label><input type="text" id="bin-item-label" list="bin-label-options" placeholder="Type and press Enter"><datalist id="bin-label-options">${binView.labels.map(l=>`<option value="${esc(l)}"></option>`).join('')}</datalist>
    <div id="bin-label-buttons">${binView.labels.map((l,n)=>`<button type="button" class="btn sm" data-label="${n}" aria-pressed="${item.labels.includes(l)}">${n<9?n+1+' ':''}${esc(l)}</button>`).join('')}</div>
    <label for="bin-note">Note</label><textarea id="bin-note" rows="5">${esc(item.note)}</textarea><button class="btn" id="bin-save">Save changes</button>
    <p class="sub">Source: ${esc(item.source)}</p><p>Used in: ${item.used_in.map(id=>`<a href="#/p/${binView.pid}/edit">${esc(id)}</a>`).join(', ') || 'No paragraphs'}</p>
    ${item.kind==='link'?`<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">Open link</a>`:''}<button class="btn sm" id="bin-delete">Remove item</button>`;
  $('#bin-save').onclick = () => binSave();
  $('#bin-item-label').onkeydown = e => { if(e.key==='Enter' && e.target.value.trim()) { e.preventDefault(); binSave([...item.labels, e.target.value.trim()]); } };
  panel.querySelectorAll('[data-label]').forEach(button=>button.onclick=()=>binToggleLabel(Number(button.dataset.label)));
  $('#bin-delete').onclick = () => binSend('/'+item.id, 'DELETE');
}
function binSave(labels) {
  return binSend('/'+binView.selected, 'PATCH', {title:$('#bin-title').value, note:$('#bin-note').value, ...(labels?{labels}: {})});
}
function binToggleLabel(n) {
  const item = binView.items.find(i=>i.id===binView.selected), label = binView.labels[n];
  if (item && label) return binSave(item.labels.includes(label)?item.labels.filter(l=>l!==label):[...item.labels,label]);
}
async function binSend(path, method, payload) {
  const pid = binView.pid;
  try {
    const data = await api(`/api/projects/${pid}/bin${path}`, {method, body:payload instanceof FormData?payload:payload?JSON.stringify(payload):undefined, editLabel:'Edit project bin', editGesture:crypto.randomUUID()});
    if (state.project?.id!==pid || !$('#project-bin')) return;
    Object.assign(binView, data); binShell();
  } catch(e) { toast(e.message, true); }
}
function binUpload(files) {
  if (!files.length) return;
  const data = new FormData(); for(const file of files) data.append('files',file);
  return binSend('', 'POST', data);
}
function binActive(e) { return state.stage==='dashboard' && $('#project-bin') && !e.target.closest('input,textarea,[contenteditable="true"]'); }
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

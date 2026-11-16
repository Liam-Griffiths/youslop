/* Home > Research documents: PDFs, pasted text, saved web pages and scans.
   The agent reads a document for facts with page references; each fact shows
   the passage behind it. Documents live beside Materials, not inside it. */
let homeDocs = {pid: null, docs: [], picked: '', detail: null, page: 1, adding: ''};

async function paintHomeDocs() {
  const pid = state.project.id;
  if (homeDocs.pid !== pid) homeDocs = {pid, docs: [], picked: '', detail: null, page: 1, adding: ''};
  try {
    const data = await api(`/api/projects/${pid}/documents`);
    if (state.project?.id !== pid) return;
    homeDocs.docs = data.documents;
    if (!homeDocs.docs.some(d => d.id === homeDocs.picked)) homeDocs.picked = homeDocs.docs[0]?.id || '';
    await homeDocLoad();
  } catch (e) { homeDocsShell(e.message); }
}
async function homeDocLoad() {
  const pid = homeDocs.pid, id = homeDocs.picked;
  homeDocs.detail = null;
  if (id) {
    try {
      const detail = await api(`/api/projects/${pid}/documents/${id}`);
      if (homeDocs.pid !== pid || homeDocs.picked !== id) return;
      homeDocs.detail = detail;
      homeDocs.page = Math.min(Math.max(1, homeDocs.page), detail.pages.length || 1);
    } catch (e) { toast(e.message, true); }
  }
  homeDocsShell();
}

const HOME_DOC_KIND = {pdf: 'PDF', text: 'TXT', web: 'WEB', scan: 'SCAN'};
function homeDocsShell(error = '') {
  const host = $('#home-docs');
  if (!host) return;
  const d = homeDocs.detail?.document, add = homeDocs.adding;
  host.innerHTML = `<div class="home-docs">
    <div class="home-doc-list">
      <input id="home-doc-files" type="file" hidden multiple accept=".pdf,.txt,.md,.html,.htm,.csv,image/*" onchange="homeDocUpload(this.files)">
      <button class="home-doc-drop" onclick="$('#home-doc-files').click()">Drop PDFs or files here, or click to choose. The agent reads each one for facts with page references.</button>
      <div class="home-doc-add"><button class="btn sm" aria-expanded="${add === 'text'}" onclick="homeDocAdding('text')">Paste text</button>
        <button class="btn sm" aria-expanded="${add === 'link'}" onclick="homeDocAdding('link')">Save a web page</button></div>
      ${add === 'text' ? `<form class="home-doc-form" onsubmit="event.preventDefault(); homeDocPaste()">
        <label for="home-doc-title">Title</label><input id="home-doc-title" type="text" placeholder="Notes from the museum visit">
        <label for="home-doc-text">Text</label><textarea id="home-doc-text" rows="6" placeholder="Paste what you copied"></textarea>
        <div class="home-doc-add"><button class="btn sm">Add document</button><button class="btn sm ghost" type="button" onclick="homeDocAdding('')">Cancel</button></div></form>` : ''}
      ${add === 'link' ? `<form class="home-doc-form" onsubmit="event.preventDefault(); homeDocLink()">
        <label for="home-doc-url">Web page or PDF link</label><input id="home-doc-url" type="url" placeholder="https://">
        <p class="sub">A copy is saved, so the page can change or vanish without losing your source.</p>
        <div class="home-doc-add"><button class="btn sm">Save it</button><button class="btn sm ghost" type="button" onclick="homeDocAdding('')">Cancel</button></div></form>` : ''}
      <p class="sub" id="home-doc-status" role="status">${esc(error)}</p>
      ${homeDocs.docs.map(x => `<button class="home-doc-row" aria-current="${x.id === homeDocs.picked}" onclick="homeDocPick('${x.id}')">
          <span class="home-doc-icon kind-${esc(x.kind)}" aria-hidden="true">${HOME_DOC_KIND[x.kind] || 'DOC'}</span>
          <span class="home-doc-text"><span class="home-doc-title">${esc(x.title)}</span>
          <span class="mono">${x.pages} page${x.pages === 1 ? '' : 's'} · ${x.facts} fact${x.facts === 1 ? '' : 's'}${x.read_at ? '' : ' · not read yet'}</span></span></button>`).join('')}
    </div>
    <div class="home-doc-view" aria-label="Document">${d ? homeDocView(d) : '<p class="sub">No documents yet. PDFs, pasted text and saved pages appear here.</p>'}</div>
  </div>`;
}
function homeDocView(d) {
  const {pages, facts} = homeDocs.detail, n = homeDocs.page, text = pages[n - 1] || '';
  let html = esc(text);
  // Quotes were checked ignoring case and spacing; highlight them the same way.
  facts.filter(f => f.page === n && f.quote).forEach(f => {
    const words = esc(f.quote).trim().split(/\s+/).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (words.length) html = html.replace(new RegExp(words.join('\\s+'), 'i'), m => `<mark>${m}</mark>`);
  });
  return `<div class="home-doc-head"><strong>${esc(d.title)}</strong>
      <span class="mono sub">${HOME_DOC_KIND[d.kind] || 'DOC'}${d.url ? ` · <a href="${esc(d.url)}" target="_blank" rel="noopener">source link</a>` : ''}</span>
      <span class="spacer"></span>
      ${d.file ? `<a class="btn sm" href="/api/projects/${homeDocs.pid}/documents/${d.id}/file" target="_blank" rel="noopener">Open original</a>` : ''}
      <button class="btn sm" onclick="homeDocRead('${d.id}')">${d.read_at ? 'Read again for facts' : 'Read for facts'}</button>
      <button class="btn sm ghost" onclick="homeDocRemove('${d.id}')">Remove</button></div>
    <div class="home-doc-page">
      <div class="home-doc-pager"><button class="btn xs ghost" ${n <= 1 ? 'disabled' : ''} onclick="homeDocTurn(-1)" aria-label="Previous page">‹</button>
        <span class="mono">Page ${n} of ${pages.length}</span>
        <button class="btn xs ghost" ${n >= pages.length ? 'disabled' : ''} onclick="homeDocTurn(1)" aria-label="Next page">›</button></div>
      <div class="home-doc-body">${html || '<span class="sub">This page has no text.</span>'}</div></div>
    <div class="home-doc-facts"><h3 class="kicker">Facts from this document · ${facts.length}</h3>
      ${facts.map(f => `<button class="home-doc-fact" onclick="homeDocGo(${f.page || 0})">
        <span>${esc(f.claim)}</span><span class="mono">${f.page ? 'p. ' + f.page : 'no page'}${f.confidence ? ' · ' + esc(f.confidence) : ''}</span></button>`).join('')
        || `<p class="sub">${d.read_at ? 'Nothing checkable found.' : 'Not read yet. “Read for facts” asks the agent to pull them out with page references.'}</p>`}</div>`;
}

function homeDocPick(id) { homeDocs.picked = id; homeDocs.page = 1; homeDocLoad(); }
function homeDocTurn(step) { homeDocs.page += step; homeDocsShell(); }
function homeDocGo(page) { if (page) { homeDocs.page = page; homeDocsShell(); $('.home-doc-page')?.scrollIntoView({block: 'nearest'}); } }
function homeDocAdding(kind) {
  homeDocs.adding = homeDocs.adding === kind ? '' : kind;
  homeDocsShell();
  (kind === 'text' ? $('#home-doc-text') : kind === 'link' ? $('#home-doc-url') : null)?.focus();
}
async function homeDocSend(path, options, picking = true) {
  const pid = homeDocs.pid, status = $('#home-doc-status');
  if (status) status.textContent = 'Adding…';
  try {
    const data = await api(`/api/projects/${pid}/documents${path}`, options);
    if (homeDocs.pid !== pid) return;
    const before = new Set(homeDocs.docs.map(d => d.id));
    homeDocs.docs = data.documents;
    homeDocs.adding = '';
    const added = homeDocs.docs.find(d => !before.has(d.id));
    if (picking && added) { homeDocs.picked = added.id; homeDocs.page = 1; }
    if (!homeDocs.docs.some(d => d.id === homeDocs.picked)) homeDocs.picked = homeDocs.docs[0]?.id || '';
    await homeDocLoad();
  } catch (e) { if (status) status.textContent = e.message; else toast(e.message, true); }
}
function homeDocUpload(files) {
  if (!files?.length) return;
  const data = new FormData();
  for (const file of files) data.append('files', file);
  return homeDocSend('', {method: 'POST', body: data});
}
function homeDocPaste() {
  const text = $('#home-doc-text').value;
  if (!text.trim()) return;
  return homeDocSend('/text', {method: 'POST', body: JSON.stringify({title: $('#home-doc-title').value, text})});
}
function homeDocLink() {
  const url = $('#home-doc-url').value.trim();
  if (url) return homeDocSend('/link', {method: 'POST', body: JSON.stringify({url})});
}
async function homeDocRemove(id) {
  // Removed files move to docs/.removed; facts drawn from them stay in research.
  await homeDocSend('/' + id, {method: 'DELETE'}, false);
}
async function homeDocRead(id) {
  const pid = homeDocs.pid;
  try {
    const r = await api(`/api/projects/${pid}/documents/${id}/read`, {method: 'POST'});
    // watchJob reloads the project and repaints Home when the read finishes.
    watchJob(r.job, 'reading a document', j => {
      if (j.state === 'done') toast(`${j.result?.added || 0} new fact${j.result?.added === 1 ? '' : 's'} added to research.`);
    });
  } catch (e) { toast(e.message, true); }
}

for (const type of ['dragover', 'dragleave', 'drop']) document.addEventListener(type, e => {
  const zone = e.target.closest?.('.home-docs');
  if (!zone || !e.dataTransfer?.types.includes('Files')) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  zone.classList.toggle('dragging', type === 'dragover');
  if (type === 'drop') homeDocUpload(e.dataTransfer.files);
}, true);

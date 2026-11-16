// Writing workspace. Drafts keep their project id until the write succeeds.
let scriptActive = '', scriptWrites = Promise.resolve(), scriptTimer, scriptFlushing, scriptComposing = false;
const scriptDrafts = new Map(), scriptNotes = new Map();
let scriptCaret = null, scriptFactsQuery = "";
function scriptPreference(key, fallback) {
  try { return JSON.parse(localStorage.getItem('corkbored-script-' + key)) ?? fallback; } catch { return fallback; }
}
function scriptRemember(key, value) {
  try { localStorage.setItem('corkbored-script-' + key, JSON.stringify(value)); } catch { /* Storage may be disabled. */ }
}
function scriptDetail(key, title, body) {
  return `<details data-script-detail="${key}" ${scriptPreference(key, true) ? 'open' : ''} ontoggle="scriptCollapse(this,'${key}')"><summary>${title}</summary>${body}</details>`;
}
function scriptCollapse(el, key) {
  if (el.closest('[hidden]')) return;
  scriptRemember(key, el.open);
  document.querySelectorAll(`[data-script-detail="${key}"]`).forEach(other => { other.open = el.open; });
}
function scriptVoice(s) {
  return `${s.on_camera ? 'On camera · ' : ''}${s.take ? (s.take.synthetic ? 'Draft voice' : 'Recorded') + (s.take.narration !== s.narration ? ' · Text changed; take out of date' : '') : 'Not voiced'}`;
}
// A shot is the paragraphs that share one shot description. It may hold several
// pictures. "new" on a paragraph forces a break; chapters and inserts always do.
// A paragraph with no description stays with the picture it continues.
// app/script_agent.shots numbers shots the same way.
function scriptRuns(p) {
  const leads = new Set((p.picture_runs || p.slides.map(s => [s.id])).map(run => run[0]));
  const runs = [];
  p.slides.forEach((s, i) => {
    const prev = p.slides[i - 1], note = (s.visual_note || '').trim();
    if (!prev || s.insert?.kind || prev.insert?.kind || (s.chapter || '').trim() || s.picture_mode === 'new'
        || (note ? note !== (prev.visual_note || '').trim() : leads.has(s.id))) runs.push([]);
    runs.at(-1).push(s);
  });
  return runs;
}
// Panels opened inside the page survive repaints: 'desc:<lead>', 'facts:<lead>', 'para:<sid>'.
const scriptOpen = new Set();
function scriptSeconds(s) { return s.insert?.seconds || s.take?.duration || s.word_count / 158 * 60; }
function scriptShotOf(sid, p = state.project) {
  const runs = scriptRuns(p), index = runs.findIndex(run => run.some(s => s.id === sid));
  return {index, run: runs[index] || []};
}
function scriptShotHeader(p, run, index, start, end) {
  const lead = run[0], chosen = lead.candidates?.find(c => c.id === lead.chosen_id);
  const kind = lead.insert?.kind || pictureKind(lead, p);
  const label = lead.insert?.kind ? 'Insert · ' + lead.insert.kind : (lead.visual_note || chosen?.title || pictureKindLabel(kind, lead));
  const facts = lead.insert?.kind ? 0 : scriptShotFactRows(p, run).filter(r => r.rank >= 3).length;
  const pictures = run.filter(s => !s.insert?.kind && (p.picture_runs || []).some(r => r[0] === s.id)).length;
  const toggle = (key, text, icon) => `<button class="btn xs script-shot-toggle" data-toggle="${key}:${lead.id}" aria-expanded="${scriptOpen.has(key + ':' + lead.id)}" onclick="scriptToggle('${key}:${lead.id}')">${icon}${text}</button>`;
  return `<header class="script-shot-heading">
    <button class="script-shot-select" onclick="scriptLocate('${run.find(s => !s.insert)?.id || lead.id}')" aria-label="Shot ${index + 1}: go to its first paragraph">
      <span class="mono script-shot-number">SHOT ${index + 1}</span>
      ${chosen ? `<img src="${esc(thumbUrl(chosen))}" alt="" loading="lazy">` : '<span class="script-shot-thumb" aria-hidden="true"></span>'}
      <span class="script-shot-label">${esc(label)}</span></button>
    <span class="mono script-shot-time">${pictures > 1 ? pictures + ' pictures · ' : ''}${fmtTime(start)}–${fmtTime(end)}</span>
    ${lead.insert?.kind ? '' : toggle('desc', 'Description', '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 15l5-5 4 4 3-3 6 6"/></svg>')}
    ${lead.insert?.kind ? '' : toggle('facts', 'Facts ' + facts, '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z"/></svg>')}
    ${p.visual_flags?.[lead.id] ? `<span class="script-visual-flag">${esc(p.visual_flags[lead.id].text)}</span>` : ''}</header>`;
}
function scriptShotDescription(p, lead, index) {
  if (lead.insert?.kind) return '';
  const chosen = lead.candidates?.find(c => c.id === lead.chosen_id), kind = pictureKind(lead, p);
  return `<div class="script-shot-desc" data-panel="desc:${lead.id}" ${scriptOpen.has('desc:' + lead.id) ? '' : 'hidden'}>
    ${chosen ? `<img src="${esc(thumbUrl(chosen))}" alt="Chosen picture for shot ${index + 1}" loading="lazy">` : '<div class="script-shot-thumb large">No picture chosen yet</div>'}
    <div class="script-shot-desc-body">
      <label class="kicker" for="script-desc-${lead.id}">What we see</label>
      <textarea id="script-desc-${lead.id}" rows="3" placeholder="Describe the picture for this shot"
        onchange="scriptSaveShotNote('${lead.id}',this.value)">${esc(lead.visual_note || '')}</textarea>
      <div class="script-shot-desc-row"><span class="pill">${esc(pictureKindLabel(kind, lead))}</span>
        ${isStage(kind) ? `<button class="btn sm ghost" onclick="reviseVisuals(['${lead.id}'])">Revise visuals</button>` : ''}
        <a href="#/p/${p.id}/edit/pictures">Choose pictures in Edit</a></div>
    </div></div>`;
}
function scriptParagraphDetails(p, s) {
  return `<div class="script-para-details" data-panel="para:${s.id}" ${scriptOpen.has('para:' + s.id) ? '' : 'hidden'}>
    <div class="script-para-fields"><label>Lower-third text<input value="${esc(s.title)}" onblur="scriptSave('${s.id}',{title:this.value})"></label>
    <label>Chapter name<input value="${esc(s.chapter)}" onblur="saveChapter('${s.id}',this.value)"></label></div>
    <div class="script-footer">${s.chapter ? `<button class="btn sm ghost" onclick="saveChapter('${s.id}','')">Remove chapter</button>` : ''}
      <label><input type="checkbox" ${s.on_camera ? 'checked' : ''} onchange="scriptCamera('${s.id}',this.checked)"> On camera</label>
      ${s.duplicate_of ? '<span class="pill">Duplicate paragraph</span>' : ''}
      <span class="mono script-word-count" data-script-count="${s.id}">${s.word_count} words</span></div>
    <label for="script-note-${s.id}">Private note</label>
    <textarea id="script-note-${s.id}" rows="2" oninput="scriptNoteInput(this,'${s.id}')" onblur="scriptFlush()">${esc(scriptNotes.get(s.id)?.text ?? s.note ?? '')}</textarea>
    <div data-findings="${s.id}"></div>
    ${p.has_source && p.fidelity === 'faithful' ? '' : `<button class="btn sm ghost" data-style-slide="${s.id}" hidden onclick="smoothFlaggedLines('${s.id}',this)">Smooth flagged lines</button>`}
    <div class="script-style-proposal" data-style-proposal="${s.id}" aria-live="polite"></div></div>`;
}
function scriptToggle(key, value) {
  const open = value ?? !scriptOpen.has(key);
  open ? scriptOpen.add(key) : scriptOpen.delete(key);
  document.querySelectorAll(`[data-panel="${key}"]`).forEach(el => { el.hidden = !open; });
  document.querySelectorAll(`[data-toggle="${key}"]`).forEach(el => el.setAttribute('aria-expanded', String(open)));
  if (open && key.startsWith('facts:')) scriptRenderShotFacts(key.slice(6));
  if (open && key.startsWith('para:')) scriptCurrent(key.slice(5));
}
function scriptToggleFacts(value) {
  const drawer = $('#script-facts');
  if (!drawer) return;
  const open = value ?? drawer.hidden;
  drawer.hidden = !open;
  $('.script-layout')?.classList.toggle('facts-open', open);
  $('#script-facts-toggle')?.setAttribute('aria-pressed', String(open));
  scriptRemember('all-facts', open);
  if (open) scriptRenderFacts();
}
function scriptShotFactRows(p, run) {
  const spoken = run.filter(s => !s.insert);
  return (p.research?.facts || []).map((fact, index) => ({fact, index,
    rank: Math.max(0, ...spoken.map(s => scriptFactRank(fact, s)))}))
    .sort((a, b) => b.rank - a.rank || a.index - b.index);
}
function scriptRenderShotFacts(lead) {
  const p = state.project, host = document.querySelector(`[data-panel="facts:${lead}"]`);
  const {run} = scriptShotOf(lead, p);
  if (!host || !run.length) return;
  const rows = scriptShotFactRows(p, run).filter(r => r.rank >= 3);
  host.innerHTML = `<div class="script-shot-facts-head"><span class="kicker">Facts for this shot</span>
    <button class="btn xs ghost" onclick="scriptToggleFacts(true)">See all ${(p.research?.facts || []).length}</button></div>
    ${rows.map(({fact: f, index}) => `<div class="script-fact"><p>${esc(f.claim)}</p>
      <span class="mono">${f.date ? esc(f.date) + ' · ' : ''}${f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source || 'Source')}</a>` : esc(f.source || 'Source')} · ${esc(f.confidence || 'medium')}</span>
      <button class="btn sm" onclick="scriptInsertShotFact('${lead}',${index})">Insert</button></div>`).join('')
      || '<p class="sub">No facts match this shot. Search them all in All facts.</p>'}`;
}
// Insert at the caret when it is in this shot, otherwise at the end of the shot.
function scriptInsertShotFact(lead, index) {
  const {run} = scriptShotOf(lead), spoken = run.filter(s => !s.insert);
  if (!spoken.some(s => s.id === scriptActive)) { scriptActive = spoken.at(-1).id; scriptCaret = null; }
  scriptInsertFact(index);
}
function scriptCanMerge(run, prev) {
  const lead = run[0], tail = prev.at(-1);
  return !(lead.chapter || '').trim() && !lead.insert?.kind && !tail.insert?.kind;
}
async function scriptShotPatch(patches, focus, open = '') {
  if (!(await scriptFlush())) return;
  const pid = state.project.id;
  await scriptPauseEditor(async () => {
    for (const [sid, patch] of patches) if (!(await scriptSave(sid, patch))) return;
    if (state.project?.id !== pid) return;
    state.project = await api(`/api/projects/${pid}`);
    if (open) scriptOpen.add(open);
    paintScript(); scriptLocate(focus);
  });
}
function scriptMergeShot(lead) {
  const {index, run} = scriptShotOf(lead), above = scriptRuns(state.project)[index - 1];
  const note = above.at(-1).visual_note || '';
  return scriptShotPatch(run.map((s, k) => [s.id, {visual_note: note, ...(s.picture_mode === 'new' ? {picture_mode: 'auto'} : {})}]), lead);
}
function scriptNewShot(sid) {
  if (scriptShotOf(sid).run[0]?.id === sid) return toast('This paragraph already starts a shot.');
  return scriptShotPatch([[sid, {picture_mode: 'new'}]], sid, 'desc:' + sid);
}
// One description per shot: write it to every paragraph so they stay together.
async function scriptSaveShotNote(lead, value) {
  const patches = scriptShotOf(lead).run.filter(s => (s.visual_note || '') !== value).map(s => [s.id, {visual_note: value}]);
  if (patches.length) return scriptShotPatch(patches, scriptActive || lead, 'desc:' + lead);
}
function scriptCurrent(sid) {
  scriptActive = sid;
  const lead = scriptShotOf(sid).run[0]?.id;
  document.querySelectorAll('.script-card').forEach(el => el.classList.toggle('current', el.dataset.sid === sid));
  document.querySelectorAll('[data-script-shot]').forEach(el => el.classList.toggle('current', el.dataset.scriptShot === lead));
  scriptAgentFocus();
  if (!$('#script-facts')?.hidden) scriptRenderFacts();
  scriptStats();
}
function scriptStats() {
  if (!$('.script-layout')) return;
  let total = 0, current = 0;
  state.project.slides.forEach(s => {
    const text = document.querySelector(`[data-sid="${s.id}"] .script-text`);
    const words = text ? text.innerText.trim().split(/\s+/).filter(Boolean).length : s.word_count;
    total += words;
    if (s.id === scriptActive) current = words;
    const voice = document.querySelector(`[data-sid="${s.id}"] .script-voice`);
    if (voice) voice.textContent = scriptVoice({...s, narration: text.innerText.trim()});
    const count = document.querySelector(`[data-script-count="${s.id}"]`);
    if (count) count.textContent = `${words} words · ${fmtTime(words / 158 * 60)}`;
  });
  $('.script-summary').textContent = `${total} words · ${state.project.slides.filter(s => !s.insert?.kind).length} paragraphs in ${scriptRuns(state.project).length} shots · ~${(total / 158).toFixed(1)} min / ${state.project.target_minutes} min target`;
  $('#script-current-count').textContent = `${current} words here`;
}
function scriptInput(el, sid) {
  scriptDrafts.set(sid, {pid: state.project.id, text: el.innerText});
  clearTimeout(scriptTimer);
  $('#script-save-status').textContent = 'Saving…';
  if (!scriptComposing) scriptTimer = setTimeout(scriptFlush, 600);
  scriptStats();
  if ($('#script-typewriter').checked) {
    const range = window.getSelection()?.rangeCount ? window.getSelection().getRangeAt(0).cloneRange() : null;
    const rect = range?.getBoundingClientRect(), pane = $('.script-main');
    if (rect?.height) pane.scrollTop += rect.top - pane.getBoundingClientRect().top - pane.clientHeight * .4;
  }
}
function scriptFlush() {
  clearTimeout(scriptTimer);
  if (scriptComposing) return Promise.resolve(false);
  if (scriptFlushing) return scriptFlushing;
  scriptFlushing = (async () => {
    await scriptWrites;
    while (scriptDrafts.size || scriptNotes.size) {
      const drafts = scriptDrafts.size ? scriptDrafts : scriptNotes;
      const [sid, draft] = drafts.entries().next().value;
      if (state.project?.id !== draft.pid) return false;
      if (!(await scriptSave(sid, drafts === scriptDrafts ? {narration: draft.text} : {note: draft.text}))) {
        if ($('#script-save-status')) $('#script-save-status').textContent = 'Not saved · retry Save';
        return false;
      }
      if (drafts.get(sid) === draft) drafts.delete(sid);
    }
    if ($('#script-save-status')) $('#script-save-status').textContent = 'Saved';
    return true;
  })().finally(() => { scriptFlushing = null; });
  return scriptFlushing;
}
async function scriptPauseEditor(work) {
  const panes = [$('.script-workspace'), $('#script-toolbar')].filter(Boolean);
  panes.forEach(el => { el.inert = true; });
  try { return await work(); }
  finally { panes.forEach(el => { el.inert = false; }); }
}
function scriptPaste(e) {
  e.preventDefault();
  document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
}
function scriptOpenFind() { $('#script-find').hidden = false; $('#script-find input').focus(); }
function scriptFocus(value) {
  const layout = $('.script-layout');
  layout.classList.toggle('script-focus', value ?? !layout.classList.contains('script-focus'));
  scriptRemember('focus', layout.classList.contains('script-focus'));
}
function scriptWorkspaceKey(e) {
  if (e.isComposing) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
    e.preventDefault(); e.shiftKey ? scriptFocus() : scriptOpenFind();
  } else if ((e.ctrlKey || e.metaKey) && ['ArrowUp','ArrowDown'].includes(e.key)) {
    e.preventDefault();
    const i = state.project.slides.findIndex(s => s.id === scriptActive);
    const s = state.project.slides[i + (e.key === 'ArrowUp' ? -1 : 1)];
    if (s) scriptLocate(s.id);
  } else if (e.key === 'Enter' && e.target.matches('.script-card')) {
    e.preventDefault(); e.target.querySelector('.script-text, a')?.focus();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    if ($('#script-find') && !$('#script-find').hidden) { scriptFind(''); $('#script-find').hidden = true; }
    scriptFocus(false);
  }
}
async function scriptEditorKey(e, sid) {
  if (!e.isComposing && (e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault(); return scriptNewShot(sid);
  }
  if (e.isComposing || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
  const selection = window.getSelection();
  if (!selection?.rangeCount || !selection.isCollapsed) return;
  const tail = selection.getRangeAt(0).cloneRange();
  tail.selectNodeContents(e.currentTarget); tail.setStart(selection.anchorNode, selection.anchorOffset);
  if (e.key === 'Enter' && !tail.toString().length) {
    e.preventDefault();
    if (!(await scriptFlush())) return;
    try {
      const p = await scriptPauseEditor(() => api(`/api/projects/${state.project.id}/slides/${sid}/split`, {method:'POST', body:JSON.stringify({append:true})}));
      const i = p.slides.findIndex(s => s.id === sid);
      state.project = p; paintScript(); scriptLocate(p.slides[i + 1].id);
    } catch (err) { toast(err.message, true); }
  } else if (e.key === 'Backspace' && !e.currentTarget.innerText.trim()) {
    e.preventDefault();
    const slides = state.project.slides, i = slides.findIndex(s => s.id === sid), next = slides[i - 1] || slides[i + 1];
    if (await delSlide(sid) && next) {
      scriptLocate(next.id);
    }
  }
}
async function scriptMoveChapter(ids, target, version = null, pid = state.project.id) {
  const before = state.project?.updated_at;
  if (!(await scriptFlush()) || state.project?.id !== pid) return;
  try {
    if (version !== null && version !== before) throw Error('Script changed; drag the section again.');
    state.project = await api(`/api/projects/${pid}/sections`, {method:'POST', body:JSON.stringify({op:'move', ids, to:target, version:state.project.updated_at})});
    paintScript(); scriptLocate(ids[0]);
  } catch (e) { toast(e.message, true); }
}
function scriptWidth(pane, width) {
  width = Math.max(260, Math.min(520, Number(width) || 340));
  $('.script-layout').style.setProperty('--script-' + pane, width + 'px');
  scriptRemember(pane, width);
}
function scriptResizeKey(e, pane) {
  if (!['ArrowLeft','ArrowRight'].includes(e.key)) return;
  e.preventDefault(); scriptWidth(pane, scriptPreference(pane, 340) + (e.key === 'ArrowRight' ? 20 : -20));
}
function scriptResize(e, pane) {
  const start = e.clientX, width = scriptPreference(pane, 340), el = e.currentTarget;
  el.setPointerCapture(e.pointerId);
  el.onpointermove = move => scriptWidth(pane, width + move.clientX - start);
  el.onpointerup = el.onpointercancel = () => { el.onpointermove = null; };
}
window.addEventListener('beforeunload', e => { if (scriptDrafts.size || scriptNotes.size) { e.preventDefault(); e.returnValue = ''; } });

function scriptNoteInput(el, sid) {
  scriptNotes.set(sid, {pid: state.project.id, text: el.value});
  clearTimeout(scriptTimer);
  $('#script-save-status').textContent = 'Saving…';
  scriptTimer = setTimeout(scriptFlush, 600);
}
// Keep a DOM range for native insertText/undo, including a selected span.
function scriptSaveCaret(el, sid) {
  const selection = window.getSelection();
  if (!selection?.rangeCount) return;
  const range = selection.getRangeAt(0);
  if (el.contains(range.startContainer) && el.contains(range.endContainer))
    scriptCaret = {pid: state.project.id, sid, range: range.cloneRange()};
}
function scriptInsertFact(index) {
  const p = state.project, sid = scriptActive;
  const el = document.querySelector(`[data-para="${sid}"][contenteditable]`);
  const claim = p.research?.facts?.[index]?.claim;
  if (!el || !claim || scriptComposing) return;
  const range = scriptCaret?.pid === p.id && scriptCaret.sid === sid &&
    el.contains(scriptCaret.range.startContainer) && el.contains(scriptCaret.range.endContainer)
    ? scriptCaret.range.cloneRange() : document.createRange();
  if (!(scriptCaret?.pid === p.id && scriptCaret.sid === sid && el.contains(range.startContainer))) {
    range.selectNodeContents(el); range.collapse(false);
  }
  el.focus();
  const selection = window.getSelection();
  selection.removeAllRanges(); selection.addRange(range);
  document.execCommand('insertText', false, String(claim));
  scriptSaveCaret(el, sid);
  scriptInput(el, sid);
}
function scriptTerms(text) {
  const stop = new Set('a an the and or of in on at to for from with is was were are it this that as by before after'.split(' '));
  return new Set((String(text || '').toLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter(t => t.length > 2 && !stop.has(t)));
}
function scriptFactRank(f, s) {
  const linked = [f.slide_id, f.paragraph_id, ...(f.slide_ids || []), ...(f.paragraph_ids || [])].filter(Boolean);
  if (linked.length) return linked.includes(s.id) ? 3000 : 0;
  if (f.beat && s.beat && f.beat === s.beat) return 2000;
  const overlap = (a, b) => [...scriptTerms(a)].filter(t => scriptTerms(b).has(t)).length;
  const beat = overlap(f.claim, s.beat);
  const text = overlap(f.claim, scriptDrafts.get(s.id)?.text ?? s.narration);
  return beat ? 1000 + beat : text;
}
function scriptFactRows(p, s, query = '') {
  const q = query.trim().toLowerCase();
  return (p.research?.facts || []).map((fact, index) => ({fact, index, rank: scriptFactRank(fact, s)}))
    .filter(({fact:f}) => [f.claim, f.source, f.date, f.url].join(' ').toLowerCase().includes(q))
    .sort((a,b) => b.rank - a.rank || a.index - b.index);
}
function scriptRenderFacts(query = scriptFactsQuery) {
  scriptFactsQuery = query;
  const p = state.project, s = p.slides.find(s => s.id === scriptActive);
  const host = $('#script-fact-list');
  if (!host || !s) return;
  const rows = scriptFactRows(p, s, query);
  const row = ({fact:f, index}) => `<div class="script-fact"><p>${esc(f.claim)}</p>
    <span class="mono">${esc(f.confidence || 'medium')} confidence${f.date ? ' · ' + esc(f.date) : ''}</span>
    <div>${f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source || 'Source')}</a>` : esc(f.source || 'Source')}
    ${s.insert?.kind ? '' : `<button class="btn sm" onclick="scriptInsertFact(${index})">Insert</button>`}</div></div>`;
  host.innerHTML = `<h3 class="kicker">Matched facts</h3>${rows.filter(r => r.rank > 0).map(row).join('') || '<p class="sub">No matched facts.</p>'}
    ${scriptDetail('all-facts', 'All facts · ' + rows.length, rows.map(row).join('') || '<p class="sub">No facts match your search.</p>')}
    <h3 class="kicker">From your bin</h3>${(p.bin || []).filter(item => item.kind === 'note' &&
      scriptFactRank({claim:[item.title, item.note, ...(item.labels || [])].join(' ')}, s) > 0)
      .map(item => `<div class="script-fact"><strong>${esc(item.title)}</strong><p>${esc(item.note)}</p>
        <a href="#/p/${p.id}/dashboard" onclick="scriptOpenBinNote('${esc(item.id)}'); return false">Open note in bin</a></div>`).join('') || '<p class="sub">No matching bin notes.</p>'}`;
}

async function scriptOpenBinNote(id) {
  const pid = state.project.id;
  if (!(await scriptFlush()) || state.project.id !== pid) return;
  if (binView.pid !== pid) binView = binInitial(pid);
  binView.selected = [id];
  binView.query = binView.kind = binView.label = '';
  go('#/p/' + pid + '/dashboard');
}

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
function scriptRuns(p) {
  const slides = new Map(p.slides.map(s => [s.id, s]));
  return (p.picture_runs || p.slides.map(s => [s.id])).map(ids => ids.map(id => slides.get(id)));
}
function scriptShotHeader(p, s, index) {
  const chosen = s.candidates?.find(c => c.id === s.chosen_id);
  return `<header class="script-shot-heading" onfocusin="scriptCurrent('${s.id}')">
    <span class="mono">SHOT ${index + 1}</span><span class="pill">${esc(s.insert?.kind || pictureKind(s,p))}</span>
    ${chosen ? `<img src="${esc(thumbUrl(chosen))}" alt="Chosen picture" loading="lazy">` : ''}
    ${s.insert?.kind ? '' : `<textarea class="script-shot-note" rows="1" aria-label="Shot ${index + 1} description" placeholder="Shot description"
      onfocus="scriptShotFit(this)" oninput="scriptShotFit(this)" onblur="this.style.height=''"
      onchange="${isStage(pictureKind(s,p)) ? 'saveVisual' : 'scriptSaveVisual'}('${s.id}',this.value)">${esc(s.visual_note || '')}</textarea>
      ${isStage(pictureKind(s,p)) ? `<button class="btn sm ghost" onclick="reviseVisuals(['${s.id}'])">Revise visuals</button>` : ''}`}
      ${p.visual_flags?.[s.id] ? `<span class="script-visual-flag">${esc(p.visual_flags[s.id].text)}</span>` : ''}</header>`;
}
function scriptShotFit(el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }
function scriptBinder(p) {
  let chapter = 0, seconds = 0;
  const leads = new Map(scriptRuns(p).map((run, i) => [run[0].id, {number: i + 1, size: run.length}]));
  return p.slides.map((s, i) => {
    const shot = leads.get(s.id), single = shot?.size === 1;
    const at = seconds; seconds += s.insert?.seconds || s.take?.duration || s.word_count / 158 * 60;
    return `${s.chapter ? `<div class="binder-chapter" draggable="true" ondragover="event.preventDefault()" ondrop="scriptDrop(event,'${s.id}')" ondragstart="scriptDrag(event,'${s.id}',true)" onkeydown="scriptBinderKey(event,${i},true)" tabindex="0">${esc(s.chapter)}<small class="mono">${++chapter} · ${fmtTime(at)}</small></div>` : ''}
    ${shot && !single ? `<div class="binder-shot" tabindex="0" draggable="true" ondragstart="scriptDrag(event,'${s.id}','shot')" onkeydown="scriptBinderKey(event,${i},'shot')" ondragover="event.preventDefault()" ondrop="scriptDrop(event,'${s.id}')" onclick="scriptLocate('${s.id}')"><span class="mono">SHOT ${shot.number}</span> ${esc((s.narration || '').split(/\s+/).slice(0,6).join(' ') || s.insert?.kind || 'Empty shot')}</div>` : ''}
    <div class="binder-row${single ? ' binder-single-shot' : ''}" data-binder-sid="${s.id}" draggable="true" ondragstart="scriptDrag(event,'${s.id}')" ondragover="event.preventDefault()" ondrop="scriptDrop(event,'${s.id}')" onkeydown="scriptBinderKey(event,${i})" tabindex="0" onfocus="scriptCurrent('${s.id}')" onclick="if (!event.target.closest('details')) scriptLocate('${s.id}')" oncontextmenu="if (this.querySelector('details')) { event.preventDefault(); this.querySelector('details').open=true; }">
    ${single ? `<span class="mono binder-shot-number" aria-label="Shot ${shot.number}">SHOT ${shot.number}</span>` : ''}<span class="binder-label">${s.insert?.kind ? 'Insert · ' + esc(s.insert.kind) : esc((s.narration || '').split(/\s+/).slice(0,6).join(' ') || 'Empty paragraph')}</span><span class="mono" data-binder-count>${s.word_count}</span>
    <span class="script-dot" title="Open findings">·</span>${s.take ? '<svg width="12" height="16" viewBox="0 0 12 16" role="img" aria-label="Has take"><rect x="4" y="1" width="4" height="8" rx="2" fill="currentColor"/><path d="M2 6v2a4 4 0 0 0 8 0V6M6 12v3M3 15h6" fill="none" stroke="currentColor"/></svg>' : ''}${s.insert?.kind ? '' : `<details class="binder-menu"><summary aria-label="Paragraph actions">⋯</summary><div>
      <button class="btn sm ghost" onclick="splitSlide('${s.id}')">Split</button><button class="btn sm ghost" onclick="startChapter('${s.id}')">Start a chapter</button>
      <button class="btn sm ghost" onclick="delSlide('${s.id}')">Delete</button><button class="btn sm ghost" onclick="rewrite('${s.id}')">Rewrite</button></div></details>`}</div>`; }).join('') +
    '<div class="binder-end" ondragover="event.preventDefault()" ondrop="scriptDrop(event,\'\')">End of script</div>';
}
function scriptCurrent(sid) {
  scriptActive = sid;
  document.querySelectorAll('[data-script-inspector]').forEach(el => el.hidden = el.dataset.scriptInspector !== sid);
  document.querySelectorAll('[data-binder-sid]').forEach(el => el.setAttribute('aria-current', String(el.dataset.binderSid === sid)));
  document.querySelectorAll('.script-card').forEach(el => el.classList.toggle('current', el.dataset.sid === sid));
  const inspector = document.querySelector(`[data-script-inspector="${sid}"]`);
  const sources = $('#script-sources');
  if (sources && inspector) {
    inspector.querySelector('h2').after(sources);
    scriptRenderFacts();
  }
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
    const binder = document.querySelector(`[data-binder-sid="${s.id}"]`);
    binder.querySelector('[data-binder-count]').textContent = words;
    if (text) binder.querySelector('.binder-label').textContent = text.innerText.trim().split(/\s+/).slice(0,6).join(' ') || 'Empty paragraph';
    const voice = document.querySelector(`[data-sid="${s.id}"] .script-voice`);
    if (voice) voice.textContent = scriptVoice({...s, narration: text.innerText.trim()});
    const count = document.querySelector(`[data-script-count="${s.id}"]`);
    if (count) count.textContent = `${words} words · ${fmtTime(words / 158 * 60)}`;
  });
  $('.script-summary').textContent = `${total} words · ${state.project.slides.filter(s => !s.insert?.kind).length} paragraphs · ~${(total / 158).toFixed(1)} min / ${state.project.target_minutes} min target`;
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
    $('.script-layout').classList.add('binder-open');
    document.querySelector(`[data-binder-sid="${scriptActive}"]`)?.focus();
  }
}
async function scriptEditorKey(e, sid) {
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
function scriptSection(sid, chapter) {
  const slides = state.project.slides, i = slides.findIndex(s => s.id === sid);
  let end = i + 1;
  if (chapter === 'shot') return scriptRuns(state.project).find(run => run[0].id === sid).map(s => s.id);
  if (chapter) while (end < slides.length && !slides[end].chapter) end++;
  return slides.slice(i, end).map(s => s.id);
}
function scriptDrag(e, sid, chapter = false) {
  e.stopPropagation();
  e.dataTransfer.setData('application/x-corkbored-script', JSON.stringify({pid:state.project.id, ids:scriptSection(sid,chapter), version:state.project.updated_at}));
}
function scriptDrop(e, target) {
  e.preventDefault();
  try { const data = JSON.parse(e.dataTransfer.getData('application/x-corkbored-script')); scriptMoveChapter(data.ids, target, data.version, data.pid); } catch { /* Ignore unrelated drags. */ }
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
function scriptBinderKey(e, i, chapter = false) {
  if (e.target !== e.currentTarget) return;
  if (e.altKey && ['ArrowUp','ArrowDown'].includes(e.key)) {
    e.preventDefault();
    const slides = state.project.slides, ids = scriptSection(slides[i].id, chapter);
    let target = i - 1;
    if (e.key === 'ArrowDown') {
      target = i + ids.length;
      if (chapter && target < slides.length) target += scriptSection(slides[target].id, chapter).length;
      else target++;
    } else if (chapter === 'shot') {
      target = slides.findIndex(s => s.id === scriptRuns(state.project).find(run => run.some(s => s.id === slides[target]?.id))?.[0].id);
    } else if (chapter) while (target > 0 && !slides[target].chapter) target--;
    if (target >= 0) scriptMoveChapter(ids, slides[target]?.id || '').then(() => document.querySelector(`[data-binder-sid="${ids[0]}"]`)?.focus());
  } else if (e.key === 'Enter') {
    e.preventDefault(); scriptLocate(state.project.slides[i].id);
  } else if (!e.ctrlKey && !e.metaKey && !e.altKey && ['j','k','ArrowUp','ArrowDown'].includes(e.key)) {
    e.preventDefault();
    const rows = [...document.querySelectorAll('[data-binder-sid]:not([hidden])')];
    rows[rows.indexOf(e.currentTarget) + (['j','ArrowDown'].includes(e.key) ? 1 : -1)]?.focus();
  }
}
function scriptWidth(pane, width) {
  width = Math.max(180, Math.min(pane === 'binder' ? 360 : 460, Number(width) || 240));
  $('.script-layout').style.setProperty('--script-' + pane, width + 'px');
  scriptRemember(pane, width);
}
function scriptResizeKey(e, pane) {
  if (!['ArrowLeft','ArrowRight'].includes(e.key)) return;
  e.preventDefault(); scriptWidth(pane, scriptPreference(pane, pane === 'binder' ? 240 : 340) + (e.key === 'ArrowRight' ? 20 : -20) * (pane === 'binder' ? 1 : -1));
}
function scriptResize(e, pane) {
  const start = e.clientX, width = scriptPreference(pane, pane === 'binder' ? 240 : 340), el = e.currentTarget;
  el.setPointerCapture(e.pointerId);
  el.onpointermove = move => scriptWidth(pane, width + (move.clientX - start) * (pane === 'binder' ? 1 : -1));
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

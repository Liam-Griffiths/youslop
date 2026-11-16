/* Edit's agent, in the right-hand column beside the inspector. It finds a
   place in the video and proposes graphics, titles and chapter cards there.
   Nothing changes until a card is applied, and every applied card is one
   ordinary, undoable slide edit. */
const editChats = new Map();
let editAgentBusy = '';

function editChat(pid) {
  if (!editChats.has(pid)) {
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem('corkbored-edit-chat-' + pid)) || []; } catch { /* Storage may be disabled. */ }
    editChats.set(pid, Array.isArray(saved) ? saved : []);
  }
  return editChats.get(pid);
}
function editChatKeep(pid) {
  const chat = editChat(pid);
  if (chat.length > 40) chat.splice(0, chat.length - 40);
  try { localStorage.setItem('corkbored-edit-chat-' + pid, JSON.stringify(chat)); } catch { /* Storage may be disabled. */ }
}

// The right column shows either what is selected or the agent.
function tlSideHtml() {
  return `<div class="tl-side-tabs" role="tablist" aria-label="Right panel">
      <button type="button" role="tab" data-side="inspect">Selected</button>
      <button type="button" role="tab" data-side="agent">Agent</button></div>
    <div class="tl-side-pane" data-side-pane="inspect"><div class="tl-inspector" id="tl-inspector"></div><div class="tl-inspector" id="tl-variables"></div></div>
    <div class="tl-side-pane tl-agent" data-side-pane="agent">
      <div class="script-agent-log" id="edit-agent-log" aria-live="polite"></div>
      <div class="script-agent-compose">
        <div class="script-agent-chips">
          <button type="button" class="btn xs" onclick="editAgentSend('Put a title over the picture here that says what this part is about.')">Title here</button>
          <button type="button" class="btn xs" onclick="editAgentSend('Suggest a few graphics that would help across the whole video.')">Suggest graphics</button>
          <button type="button" class="btn xs" onclick="editAgentPrefill('Take me to the part about ')">Find…</button>
          <button type="button" class="btn xs ghost" onclick="editAgentClear()" title="Clear this conversation">Clear</button>
        </div>
        <div class="script-agent-input"><label class="sr-only" for="edit-agent-input">Message the agent</label>
          <textarea id="edit-agent-input" rows="1" placeholder="Find a part, add a title…"
            onkeydown="event.stopPropagation();if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();editAgentSend();}"></textarea>
          <button type="button" class="btn sm" id="edit-agent-send" onclick="editAgentSend()">Send</button></div>
      </div>
    </div>`;
}
function tlSide(which) {
  const box = $('#inspector');
  if (!box) return;
  if (which) { TL.side = which; try { localStorage.setItem('corkbored-edit-side', which); } catch { /* Storage may be disabled. */ } }
  else if (!TL.side) { try { TL.side = localStorage.getItem('corkbored-edit-side'); } catch { /* Storage may be disabled. */ } }
  if (TL.side !== 'agent') TL.side = 'inspect';
  box.querySelectorAll('[data-side]').forEach(b => {
    b.setAttribute('aria-selected', String(b.dataset.side === TL.side));
    b.onclick = () => { tlSide(b.dataset.side); if (b.dataset.side === 'agent') $('#edit-agent-input')?.focus(); };
  });
  box.querySelectorAll('[data-side-pane]').forEach(pane => { pane.hidden = pane.dataset.sidePane !== TL.side; });
  TL.host?.classList.toggle('agent-open', TL.side === 'agent');
  if (TL.side === 'agent') editAgentPaint();
}

const editAgentPara = () => typeof tlParas === 'function' && TL.data
  ? [...tlParas()].reverse().find(q => q.start <= TL.cur && TL.cur < q.start + q.duration) : null;
const editAgentWhere = a => {
  const q = TL.data && tlParas().find(q => q.id === a.sid);
  return `¶${a.paragraph}${q ? ' · ' + fmtTime(q.start) : ''}`;
};
const EDIT_ACTION = {graphic: ['Graphic', 'Add it'], title: ['Title', 'Set the title'], chapter: ['Chapter card', 'Set the chapter'], remove: ['Remove graphic', 'Remove it']};
function editAgentMessage(m, i) {
  if (m.role === 'user') return `<div class="agent-msg user">${esc(m.text)}</div>`;
  const cards = (m.actions || []).map((a, j) => {
    const body = a.type === 'graphic' ? `<p><b>${esc(a.block_name)}</b></p>${Object.values(a.vars || {}).filter(v => typeof v === 'string' && v).map(v => `<p>“${esc(v)}”</p>`).join('')}
        <p class="agent-note">${a.on ? `When the voice says “${esc(a.on)}”` : 'At the start of the paragraph, or at the playhead if it is inside it'} · ${a.dur} s</p>`
      : a.type === 'remove' ? `<p>${esc(a.block_name)}</p>`
      : `<p>“${esc(a.text)}”</p>${a.was ? `<p class="agent-note">Replaces “${esc(a.was)}”</p>` : ''}`;
    return `<div class="agent-card edit"><span class="kicker">${EDIT_ACTION[a.type][0]} · ${editAgentWhere(a)}</span>
      ${body}${a.why ? `<p class="agent-note">${esc(a.why)}</p>` : ''}
      <div class="agent-card-actions">${a.state === 'done' ? '<span class="agent-note">Done. Undo takes it back.</span>'
        : `<button type="button" class="btn sm" onclick="editAgentApply(${i},${j})">${EDIT_ACTION[a.type][1]}</button>`}
        <button type="button" class="btn sm ghost" onclick="editAgentGo('${esc(a.sid)}')">Go there</button></div></div>`;
  }).join('');
  const went = m.goto ? `<p class="agent-note"><button type="button" class="btn xs ghost" onclick="editAgentGo('${esc(m.goto)}')">Playhead → ¶${m.goto_paragraph}</button></p>` : '';
  return `<div class="agent-msg${m.error ? ' error' : ''}">${m.error ? errorMarkup(m.text, {project_id: state.project?.id}) : esc(m.text)}</div>${went}${cards}`;
}
function editAgentPaint() {
  const log = $('#edit-agent-log');
  if (!log || !state.project) return;
  const pid = state.project.id, chat = editChat(pid);
  log.innerHTML = (chat.length ? chat.map(editAgentMessage).join('')
    : '<p class="agent-note">Ask it to find a part of the video, or to put a title, graphic or chapter card somewhere. It suggests; nothing changes until you choose, and Undo takes it back.</p>')
    + (editAgentBusy === pid ? '<p class="agent-note agent-busy">Reading the cut…</p>' : '');
  const send = $('#edit-agent-send');
  if (send) send.disabled = editAgentBusy === pid;
  log.scrollTop = log.scrollHeight;
}
function editAgentPrefill(text) {
  const input = $('#edit-agent-input');
  if (input) { input.value = text; input.focus(); input.setSelectionRange(text.length, text.length); }
}
function editAgentGo(sid) {
  const q = TL.data && tlParas().find(q => q.id === sid);
  if (!q) return toast('That paragraph is no longer in the video.', true);
  tlPause(); tlSeek(q.start, {ensure: true});
  const item = tlItems('paragraph').find(p => p.sid === sid);
  // Keep the conversation in view: select without flipping the column back.
  if (item) tlSelect(item);
}
async function editAgentSend(text) {
  const input = $('#edit-agent-input'), pid = state.project?.id;
  text = String(text ?? input?.value ?? '').trim();
  if (!text || !pid || editAgentBusy) return;
  const chat = editChat(pid);
  const history = chat.slice(-8).map(m => ({role: m.role, text: m.text}));
  chat.push({role: 'user', text});
  if (input && input.value.trim() === text) input.value = '';
  editAgentBusy = pid;
  editAgentPaint();
  try {
    const starts = TL.data ? Object.fromEntries(tlParas().map(q => [q.id, q.start])) : {};
    const r = await api(`/api/projects/${pid}/edit/agent`, {method: 'POST',
      body: JSON.stringify({message: text, history, focus: editAgentPara()?.id || '', starts})});
    chat.push({role: 'agent', text: r.reply, actions: r.actions || [], goto: r.goto || '', goto_paragraph: r.goto_paragraph || 0});
    if (r.goto && state.project?.id === pid && TL.pid === pid) editAgentGo(r.goto);
  } catch (e) {
    chat.push({role: 'agent', text: e.message, error: true});
  } finally {
    editAgentBusy = '';
    editChatKeep(pid);
    if (state.project?.id === pid) editAgentPaint();
  }
}
function editAgentClear() {
  const pid = state.project.id;
  editChat(pid).length = 0;
  editChatKeep(pid);
  editAgentPaint();
}
async function editAgentApply(i, j) {
  const pid = state.project.id, a = editChat(pid)[i]?.actions?.[j];
  if (!a || a.state === 'done' || editAgentBusy) return;
  if (typeof tlCanEdit === 'function' && !tlCanEdit([], [a.type === 'chapter' ? 'chapters' : a.type === 'title' ? 'titles' : 'graphics'])) return;
  editAgentBusy = pid;
  try {
    // Reload first so an edit made while the card sat in the chat is kept.
    const fresh = await api(`/api/projects/${pid}`);
    const slide = fresh.slides.find(s => s.id === a.sid);
    if (!slide) throw Error('That paragraph is no longer in the video.');
    let patch, added = '';
    if (a.type === 'graphic') {
      const here = editAgentPara();
      added = 'graphic-' + crypto.randomUUID();
      patch = {overlays: [...(slide.overlays || []), {id: added, block_id: a.block, vars: a.vars, dur: a.dur, position: a.position, by: 'hand',
        at: !a.on && here?.id === a.sid ? Math.max(0, TL.cur - here.start) : 0, ...(a.on ? {on: a.on} : {})}]};
    } else if (a.type === 'remove') {
      if (!(slide.overlays || []).some(o => o.id === a.graphic)) throw Error('That graphic is already gone.');
      patch = {overlays: slide.overlays.filter(o => o.id !== a.graphic)};
    } else patch = {[a.type]: a.text};
    state.project = fresh;
    const saved = await saveSlide(a.sid, patch, {editLabel: `agent: ${EDIT_ACTION[a.type][0].toLowerCase()}`, editGesture: crypto.randomUUID(), quiet: true});
    if (!saved) return;
    a.state = 'done';
    editChatKeep(pid);
    if (TL.pid !== pid) return;
    await tlRefresh();
    const q = tlParas().find(q => q.id === a.sid);
    const item = added && tlItems('overlay').find(g => g.sid === a.sid && g.id === added);
    if (item) { tlPause(); tlSeek(item.t0, {ensure: true}); tlSelect(item); }
    else if (q) editAgentGo(a.sid);
    toast(a.type === 'graphic' ? 'Graphic added. Adjust it under Selected.' : 'Done.');
  } catch (e) { toast(e.message, true); }
  finally { editAgentBusy = ''; if (state.project?.id === pid) editAgentPaint(); }
}

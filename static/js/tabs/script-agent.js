// Script agent: a chat beside the page. It proposes edits; the writer applies
// them through the ordinary paragraph save, so Undo covers them as well.
const scriptChats = new Map();
let scriptAgentBusy = '';
const SCRIPT_CHAT_KEEP = 40;

function scriptChat(pid = state.project.id) {
  if (!scriptChats.has(pid)) {
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem('corkbored-script-chat-' + pid)) || []; } catch { /* Storage may be disabled. */ }
    scriptChats.set(pid, Array.isArray(saved) ? saved : []);
  }
  return scriptChats.get(pid);
}
function scriptChatKeep(pid) {
  const chat = scriptChat(pid);
  if (chat.length > SCRIPT_CHAT_KEEP) chat.splice(0, chat.length - SCRIPT_CHAT_KEEP);
  try { localStorage.setItem('corkbored-script-chat-' + pid, JSON.stringify(chat)); } catch { /* Storage may be disabled. */ }
}

function scriptAgentPanel(p, castNote = '') {
  return `<div class="script-agent-tabs" role="tablist" aria-label="Agent and check">
      <button role="tab" id="script-tab-agent" aria-controls="script-pane-agent" onclick="scriptAgentTab('agent')">Agent</button>
      <button role="tab" id="script-tab-check" aria-controls="script-pane-check" onclick="scriptAgentTab('check')">Check <span class="mono" id="script-check-count"></span></button>
      <span class="mono script-agent-focus" id="script-agent-focus"></span>
    </div>
    <div class="script-agent-pane" id="script-pane-agent" role="tabpanel" aria-labelledby="script-tab-agent">
      <div class="script-agent-log" id="script-agent-log" aria-live="polite"></div>
      <div class="script-agent-compose">
        <div class="script-agent-chips">
          <button class="btn xs" onclick="scriptAgentAsk('shot','Tighten shot {shot}. Keep every fact.')">Tighten this shot</button>
          <button class="btn xs" onclick="scriptAgentAsk('shot','Check shot {shot} against the facts. Flag anything unsupported.')">Check against facts</button>
          <button class="btn xs" onclick="scriptAgentAsk('','Where should the shot breaks go so each picture carries one idea?')">Suggest shot breaks</button>
          <button class="btn xs" onclick="scriptAgentAsk('','Give me a stronger opening paragraph.')">Stronger opening</button>
        </div>
        <div class="script-agent-input">
          <label class="sr-only" for="script-agent-input">Message the script agent</label>
          <textarea id="script-agent-input" rows="2" placeholder="Ask about the script…" onkeydown="scriptAgentKey(event)"></textarea>
          <button class="btn sm primary" id="script-agent-send" onclick="scriptAgentSend()">Send</button>
        </div>
        <button class="btn xs ghost script-agent-clear" onclick="scriptAgentClear()">Clear conversation</button>
      </div>
    </div>
    <div class="script-agent-pane" id="script-pane-check" role="tabpanel" aria-labelledby="script-tab-check" hidden>
      ${castNote}
      ${p.has_source && p.fidelity === 'faithful' ? '' : '<button class="btn sm" data-style-all disabled onclick="smoothFlaggedLines(null,this)">Smooth flagged lines</button>'}
      <div id="script-check-results" role="status">Loading check…</div>
      <details class="script-camera"><summary>On camera / presenter</summary>${presenterPanel(p)}</details>
    </div>`;
}
function scriptAgentTab(tab) {
  if (!['agent', 'check'].includes(tab)) tab = 'agent';
  ['agent', 'check'].forEach(name => {
    $('#script-tab-' + name)?.setAttribute('aria-selected', String(name === tab));
    const pane = $('#script-pane-' + name);
    if (pane) pane.hidden = name !== tab;
  });
  scriptRemember('agent-tab', tab);
}
function scriptAgentFocus() {
  const el = $('#script-agent-focus'), input = $('#script-agent-input');
  const {index} = scriptShotOf(scriptActive);
  if (el) el.textContent = index >= 0 ? `Looking at shot ${index + 1}` : '';
  if (input) input.placeholder = index >= 0 ? `Ask about shot ${index + 1}, or the whole script…` : 'Ask about the script…';
}

function scriptAgentMessage(m, i) {
  if (m.role === 'user') return `<div class="agent-msg user">${esc(m.text)}</div>`;
  const flags = (m.flags || []).map(f => `<div class="agent-card flag">
      <span class="kicker">No source · ¶${f.paragraph}</span>
      ${f.quote ? `<q>${esc(f.quote)}</q>` : ''}<p>${esc(f.problem)}</p>
      <div class="agent-card-actions"><button class="btn sm" onclick="scriptAgentShow('${esc(f.id)}')">Show in page</button>
      <button class="btn sm ghost" onclick="scriptAgentFacts('${esc(f.id)}')">Open facts</button></div></div>`).join('');
  const edits = (m.edits || []).map((e, j) => {
    if (e.state === 'dismissed') return `<p class="agent-note">Edit to ¶${e.paragraph} dismissed.</p>`;
    if (e.state === 'applied') return `<div class="agent-card applied"><span>Applied to ¶${e.paragraph}.</span>
      <button class="btn sm ghost" onclick="scriptAgentUndo(${i},${j})">Undo</button></div>`;
    return `<div class="agent-card edit"><span class="kicker">Edit · ¶${e.paragraph}</span>
      <del>${esc(e.before)}</del><ins>${esc(e.after)}</ins>${e.why ? `<p class="agent-note">${esc(e.why)}</p>` : ''}
      <div class="agent-card-actions"><button class="btn sm primary" onclick="scriptAgentApply(${i},${j})">Apply</button>
      <button class="btn sm" onclick="scriptAgentShow('${esc(e.id)}')">Show in page</button>
      <button class="btn sm ghost" onclick="scriptAgentDismiss(${i},${j})">Dismiss</button></div></div>`;
  }).join('');
  return `<div class="agent-msg${m.error ? ' error' : ''}">${esc(m.text)}</div>${flags}${edits}`;
}
function scriptAgentPaint() {
  const log = $('#script-agent-log');
  if (!log || !state.project) return;
  const pid = state.project.id, chat = scriptChat(pid);
  log.innerHTML = (chat.length ? chat.map(scriptAgentMessage).join('')
    : `<p class="agent-note">Ask for changes to a shot, a check against your facts, or a second opinion. Edits arrive as suggestions; nothing changes until you apply one.</p>`)
    + (scriptAgentBusy === pid ? '<p class="agent-note agent-busy">Reading the script…</p>' : '');
  const send = $('#script-agent-send');
  if (send) send.disabled = scriptAgentBusy === pid;
  log.scrollTop = log.scrollHeight;
  scriptAgentFocus();
}
function scriptAgentKey(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); scriptAgentSend(); }
}
function scriptAgentAsk(scope, text) {
  const {index} = scriptShotOf(scriptActive);
  scriptAgentSend(scope === 'shot' ? text.replace('{shot}', String(index + 1)) : text);
}
async function scriptAgentSend(text) {
  const input = $('#script-agent-input');
  text = String(text ?? input?.value ?? '').trim();
  const pid = state.project?.id;
  if (!text || !pid || scriptAgentBusy) return;
  if (!(await scriptFlush()) || state.project?.id !== pid) return;
  const chat = scriptChat(pid);
  const history = chat.slice(-8).map(m => ({role: m.role, text: m.text}));
  chat.push({role: 'user', text});
  if (input && input.value.trim() === text) input.value = '';
  scriptAgentBusy = pid;
  scriptAgentPaint();
  try {
    const r = await api(`/api/projects/${pid}/script/agent`, {method: 'POST',
      body: JSON.stringify({message: text, shot: scriptShotOf(scriptActive).run[0]?.id || '', history})});
    chat.push({role: 'agent', text: r.reply, flags: r.flags || [],
      edits: (r.edits || []).map(e => ({...e, state: 'open'}))});
  } catch (e) {
    chat.push({role: 'agent', text: e.message, error: true});
  } finally {
    scriptAgentBusy = '';
    scriptChatKeep(pid);
    if (state.project?.id === pid) scriptAgentPaint();
  }
}
function scriptAgentClear() {
  const pid = state.project.id;
  scriptChat(pid).length = 0;
  scriptChatKeep(pid);
  scriptAgentPaint();
}
function scriptAgentRewrite(sid, n) {
  scriptAgentTab('agent');
  scriptCurrent(sid);
  const input = $('#script-agent-input');
  input.value = `Rewrite ¶${n}: `;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}
function scriptAgentShow(sid) {
  scriptLocate(sid);
  const card = document.querySelector(`.script-card[data-sid="${sid}"]`);
  if (!card) return toast('That paragraph is no longer in the script.', true);
  card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash');
}
function scriptAgentFacts(sid) {
  const lead = scriptShotOf(sid).run[0]?.id;
  if (!lead) return;
  scriptToggle('facts:' + lead, true);
  scriptAgentShow(sid);
}
function scriptAgentSetText(sid, text) {
  const el = document.querySelector(`[data-para="${sid}"]`);
  if (el) el.textContent = text;
  scriptStats(); scriptLoadCheck();
}
async function scriptAgentApply(i, j) {
  const pid = state.project.id, e = scriptChat(pid)[i]?.edits?.[j];
  if (!e || e.state !== 'open' || !(await scriptFlush()) || state.project.id !== pid) return;
  const s = state.project.slides.find(x => x.id === e.id);
  if (!s) return toast('That paragraph is no longer in the script.', true);
  e.prior = s.narration;
  if (!(await scriptSave(e.id, {narration: e.after}))) return;
  e.state = 'applied';
  scriptChatKeep(pid);
  if (state.project.id !== pid) return;
  scriptAgentSetText(e.id, e.after);
  scriptAgentPaint();
}
async function scriptAgentUndo(i, j) {
  const pid = state.project.id, e = scriptChat(pid)[i]?.edits?.[j];
  if (!e || e.state !== 'applied' || !(await scriptFlush()) || state.project.id !== pid) return;
  const s = state.project.slides.find(x => x.id === e.id);
  if (!s || s.narration !== e.after) return toast('That paragraph has changed since; use Undo in the top bar instead.', true);
  if (!(await scriptSave(e.id, {narration: e.prior ?? e.before}))) return;
  e.state = 'open';
  scriptChatKeep(pid);
  scriptAgentSetText(e.id, e.prior ?? e.before);
  scriptAgentPaint();
}
function scriptAgentDismiss(i, j) {
  const pid = state.project.id, e = scriptChat(pid)[i]?.edits?.[j];
  if (!e) return;
  e.state = 'dismissed';
  scriptChatKeep(pid);
  scriptAgentPaint();
}

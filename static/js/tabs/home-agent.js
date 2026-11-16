/* Home's agent: research and planning. Answers from facts, documents and
   materials; proposes notes, open questions and web searches that only happen
   when the writer applies them. */
const homeChats = new Map();
let homeAgentBusy = '';

function homeChat(pid) {
  if (!homeChats.has(pid)) {
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem('corkbored-home-chat-' + pid)) || []; } catch { /* Storage may be disabled. */ }
    homeChats.set(pid, Array.isArray(saved) ? saved : []);
  }
  return homeChats.get(pid);
}
function homeChatKeep(pid) {
  const chat = homeChat(pid);
  if (chat.length > 40) chat.splice(0, chat.length - 40);
  try { localStorage.setItem('corkbored-home-chat-' + pid, JSON.stringify(chat)); } catch { /* Storage may be disabled. */ }
}
function homeAgentPanel() {
  return `<div class="shots-agent-head"><h2>Agent</h2><span class="mono">research · planning</span></div>
    <div class="script-agent-log" id="home-agent-log" aria-live="polite"></div>
    <div class="script-agent-compose">
      <div class="script-agent-chips">
        <button class="btn xs" onclick="homeAgentSend('What is this video still missing: facts, sources, pictures?')">What's missing?</button>
        <button class="btn xs" onclick="homeAgentSend('Which open questions can my documents answer, and what should I search for the rest?')">Answer open questions</button>
        <button class="btn xs" onclick="homeAgentSend('Summarise what my documents say, and what they disagree on.')">Summarise my documents</button>
      </div>
      <div class="script-agent-input"><label class="sr-only" for="home-agent-input">Message the agent</label>
        <textarea id="home-agent-input" rows="2" placeholder="Ask, research or plan…"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();homeAgentSend();}"></textarea>
        <button class="btn sm primary" id="home-agent-send" onclick="homeAgentSend()">Send</button></div>
      <button class="btn xs ghost script-agent-clear" onclick="homeAgentClear()">Clear conversation</button>
    </div>`;
}
const HOME_ACTION = {note: ['Note', 'Keep as a note'], question: ['Open question', 'Track this question'], search: ['Search the web', 'Search and read']};
function homeAgentMessage(m, i) {
  if (m.role === 'user') return `<div class="agent-msg user">${esc(m.text)}</div>`;
  const actions = (m.actions || []).map((a, j) => `<div class="agent-card edit"><span class="kicker">${HOME_ACTION[a.type][0]}</span>
      <p>${esc(a.text)}</p>${a.why ? `<p class="agent-note">${esc(a.why)}</p>` : ''}
      <div class="agent-card-actions">${a.state === 'done' ? `<span class="agent-note">${a.type === 'search' ? 'Searching; pages arrive in Research documents.' : 'Done.'}</span>`
        : a.type === 'search' && m.can_search === false ? '<span class="agent-note">Set up a web search in Settings to run this.</span>'
        : `<button class="btn sm primary" onclick="homeAgentApply(${i},${j})">${HOME_ACTION[a.type][1]}</button>`}</div></div>`).join('');
  return `<div class="agent-msg${m.error ? ' error' : ''}">${esc(m.text)}</div>${actions}`;
}
function homeAgentPaint() {
  const log = $('#home-agent-log');
  if (!log || !state.project) return;
  const pid = state.project.id, chat = homeChat(pid);
  log.innerHTML = (chat.length ? chat.map(homeAgentMessage).join('')
    : '<p class="agent-note">Ask about your research, plan what to gather, or have it search the web. It suggests; nothing is added until you choose.</p>')
    + (homeAgentBusy === pid ? '<p class="agent-note agent-busy">Reading your research…</p>' : '');
  const send = $('#home-agent-send');
  if (send) send.disabled = homeAgentBusy === pid;
  log.scrollTop = log.scrollHeight;
}
async function homeAgentSend(text) {
  const input = $('#home-agent-input'), pid = state.project?.id;
  text = String(text ?? input?.value ?? '').trim();
  if (!text || !pid || homeAgentBusy) return;
  const chat = homeChat(pid);
  const history = chat.slice(-8).map(m => ({role: m.role, text: m.text}));
  chat.push({role: 'user', text});
  if (input && input.value.trim() === text) input.value = '';
  homeAgentBusy = pid;
  homeAgentPaint();
  try {
    const r = await api(`/api/projects/${pid}/home/agent`, {method: 'POST', body: JSON.stringify({message: text, history})});
    chat.push({role: 'agent', text: r.reply, actions: r.actions || [], can_search: r.can_search});
  } catch (e) {
    chat.push({role: 'agent', text: e.message, error: true});
  } finally {
    homeAgentBusy = '';
    homeChatKeep(pid);
    if (state.project?.id === pid) homeAgentPaint();
  }
}
function homeAgentClear() {
  const pid = state.project.id;
  homeChat(pid).length = 0;
  homeChatKeep(pid);
  homeAgentPaint();
}
async function homeAgentApply(i, j) {
  const pid = state.project.id, a = homeChat(pid)[i]?.actions?.[j];
  if (!a || a.state === 'done') return;
  try {
    const r = await api(`/api/projects/${pid}/home/apply`, {method: 'POST', body: JSON.stringify({type: a.type, text: a.text})});
    a.state = 'done';
    homeChatKeep(pid);
    if (r.job) {
      homeAgentPaint();
      watchJob(r.job, 'web research', j => {
        if (j.state === 'done') toast(`${j.result?.documents || 0} page${j.result?.documents === 1 ? '' : 's'} saved, ${j.result?.added || 0} new fact${j.result?.added === 1 ? '' : 's'}.`);
      });
    } else if (state.project?.id === pid) {
      state.project = r;
      if (state.stage === 'dashboard') paintDashboard();
      toast(a.type === 'note' ? 'Kept in Materials.' : 'Added to open questions.');
    }
  } catch (e) { toast(e.message, true); }
}

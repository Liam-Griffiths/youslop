// Script check panel and finding actions.
let scriptCheckVersion = 0;
async function scriptLoadCheck() {
  const pid = state.project.id, version = ++scriptCheckVersion;
  try {
    const result = await api(`/api/projects/${pid}/script-check`);
    if (state.project?.id !== pid || state.tab !== 'script' || version !== scriptCheckVersion) return;
    const findings = result.findings;
    const row = (f, i) => `<div class="script-finding"><span class="script-level ${f.level}">${f.level}</span>
      <span>${esc(f.msg)}</span><button class="btn sm" onclick="scriptFixFinding(${i})">Fix</button>
      <button class="btn sm ghost" onclick="scriptDismiss('${f.id}')">Dismiss</button></div>`;
    state.scriptFindings = findings;
    const styleSlides = new Set(findings.filter(f => f.code === 'script.style').map(f => f.slide_id));
    document.querySelectorAll('[data-style-slide]').forEach(button => {
      button.hidden = !styleSlides.has(button.dataset.styleSlide);
    });
    const smoothAll = $('[data-style-all]');
    if (smoothAll) {
      smoothAll.disabled = !styleSlides.size;
      smoothAll.title = styleSlides.size ? '' : 'No style findings to smooth.';
    }
    const bySlide = new Map();
    findings.forEach((f, i) => {
      if (!bySlide.has(f.slide_id)) bySlide.set(f.slide_id, []);
      bySlide.get(f.slide_id).push(row(f, i));
    });
    document.querySelectorAll('[data-findings]').forEach(el => {
      el.innerHTML = (bySlide.get(el.dataset.findings) || []).join('');
      el.closest('.script-card').classList.toggle('has-finding', !!el.innerHTML);
    });
    $('#script-check-results').innerHTML = `<div class="script-counts mono">${['P0','P1','P2','P3'].map(l => `<span class="${l}">${l} ${result.counts[l]}</span>`).join('')}</div>
      ${findings.map((f, i) => `<div class="script-check-item"><button class="btn sm ghost mono" onclick="scriptLocate('${f.slide_id}')">${f.level} · ${f.slide_id ? '¶' + (state.project.slides.findIndex(s => s.id === f.slide_id) + 1) : 'Script'}</button>${row(f, i)}</div>`).join('') || '<p>No open word findings.</p>'}
      <button class="btn sm ghost" onclick="scriptLoadCheck()">Refresh check</button>
      <h2 class="kicker">Channel rules applied</h2>
      <p>${result.rules.map(esc).join(' · ') || 'No channel rules set.'}</p>
      <p class="sub">Rules guide writing. This check covers empty narration, open-loop payoffs, researched claim flags and advisory narration style; it does not validate arbitrary prose rules.</p>
      <button class="btn sm ghost" onclick="scriptEditRules()">Edit rules</button>`;
  } catch (e) {
    if (version === scriptCheckVersion && $('#script-check-results'))
      $('#script-check-results').innerHTML = '<p>Check unavailable.</p><button class="btn sm" onclick="scriptLoadCheck()">Retry check</button>';
  }
}
function scriptLocate(sid) {
  const el = [...document.querySelectorAll('.script-card')].find(el => el.dataset.sid === sid);
  if (el) { el.focus(); el.scrollIntoView({block: 'center'}); }
}
function scriptFixFinding(i) {
  const f = state.scriptFindings[i];
  if (!f.slide_id) return go(`#/p/${state.project.id}/plan`);
  scriptLocate(f.slide_id);
  document.activeElement.querySelector('textarea')?.focus();
  toast('Edit the narration to address the finding; Check facts refreshes researched claims.');
}
async function scriptDismiss(id) {
  try {
    await api(`/api/projects/${state.project.id}/script-check/${id}/dismiss`, {method: 'POST'});
    scriptLoadCheck();
  } catch (e) { toast(e.message, true); }
}
async function scriptEditRules() {
  const p = state.project;
  try {
    // The channel list contains summaries, without frame/rules.
    const channel = p.channel_id ? await api(`/api/channels/${p.channel_id}`) : null;
    const owner = channel || p;
    const text = prompt(`${channel ? 'Channel' : 'Project'} writing rules, one per line`, (owner.frame?.rules || []).join('\n'));
    if (text === null) return;
    const frame = {...owner.frame, rules: text.split('\n').map(s => s.trim()).filter(Boolean)};
    await api(channel ? `/api/channels/${channel.id}` : `/api/projects/${p.id}`, {method: 'PATCH', body: JSON.stringify({frame})});
    owner.frame = frame;
    if (state.project?.id === p.id) scriptLoadCheck();
  } catch (e) { toast(e.message, true); }
}


async function runFactcheck() {
  const r = await api(`/api/projects/${state.project.id}/factcheck`, { method: 'POST' });
  watchJob(r.job, 'fact check');
  render();
}

// A chapter card: a full frame of type announcing a section, held in the
// silence before the paragraph that opens it. Marking one also gives that
// paragraph its own picture (see schema.group_slides), so the card lands on
// a cut rather than in the middle of the picture before it.
const chapterCount = (p) => p.slides.filter((s) => (s.chapter || '').trim()).length;


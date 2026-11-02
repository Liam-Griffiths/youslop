
// ------------------------------------------------------------------ script
function paintScript() {
  const p = state.project;
  if (!p.slides.length) {
    // A run that died partway leaves its outline and finished sections behind.
    const draft = p.draft || {};
    const written = Object.keys(draft.sections || {}).length;
    const total = (draft.outline && (draft.outline.sections || []).length) || 0;
    if (isStage(p.style.format) && !written) {
      // Story, then cast, then words: the script waits for the cast.
      const outline = p.outline || draft.outline || {};
      $('#tabbody').innerHTML = `<div class="empty-note">
          <strong>${esc(outline.title || p.idea.slice(0, 80))}</strong><br>
          ${(outline.sections || []).map((c, i) => `${i}. ${esc(c.heading || '')}`).join('<br>')}<br><br>
          The script is written after the cast is gathered, so it only describes what the models can show.<br><br>
          <button class="btn sm primary" onclick="go('#/p/${p.id}/cast')">gather the cast</button>
          <button class="btn sm ghost" onclick="castWrite()">write it now</button>
        </div>`;
      return;
    }
    $('#tabbody').innerHTML = written
      ? `<div class="empty-note">
           <strong>An unfinished draft is waiting.</strong><br>
           ${written} of ${total} sections were written before the last run stopped
           — ${esc(draft.outline.title || p.idea)}.<br>
           <span class="mono" style="color:var(--ink-faint)">Carrying on writes only
             the ${total - written} that are missing.</span><br><br>
           <button class="btn sm primary" onclick="regenScript()">Continue draft</button>
           <button class="btn sm ghost" onclick="regenScript(true)">start again</button>
         </div>`
      : `<div class="empty-note">No script yet. Write one from the idea to begin.
           <button class="btn sm" onclick="regenScript()">Write the script</button></div>`;
    return;
  }
  const words = p.slides.reduce((n, s) => n + s.word_count, 0);
  const research = p.research || {};
  let html = `<div class="script-layout"><section class="script-main" aria-label="Script paragraphs">
    <div class="script-heading"><h1>Script</h1>
    <span class="mono script-summary">${words} words · ${p.slides.length} paragraphs · ~${fmtTime(p.est_seconds)}</span>
    <button class="btn sm" onclick="$('#script-find').hidden=false; $('#script-find input').focus()">Find</button></div>
    <div id="script-find" hidden><label>Find in script <input type="search" oninput="scriptFind(this.value)"></label>
      <button class="btn sm ghost" onclick="scriptFind(''); this.previousElementSibling.querySelector('input').value=''; this.parentElement.hidden=true">Close find</button>
      <span id="script-find-count" class="mono" role="status"></span></div>
    <div class="row script-tools">
    <a class="btn sm" href="/projects/${encodeURIComponent(p.id)}/shot-list" target="_blank" rel="noopener">Shot list for the shoot</a>
    <button class="btn sm" onclick="suggestChapters(this)">Suggest chapters</button>
    ${research.facts?.length ? '<button class="btn sm ghost" onclick="runFactcheck()">Check facts</button>' : ''}
    ${p.has_source ? `<span class="pill">${esc(p.fidelity)} import</span>
      <button class="btn sm" onclick="reimport('${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}')">Re-split as ${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}</button>
      <button class="btn sm ghost" onclick="reimport('')">Re-split again</button>`
      : '<button class="btn sm" onclick="regenScript()">Rewrite whole script</button>'}
    </div>${sourcesPanel(research)}<div id="chapter-proposals"></div>
    <p class="sub">J/K or arrows: move · Enter: edit · Esc: leave · Drag chapter handles, or use Alt + arrows.</p>`;
  const stage = isStage(p.style.format), vflags = p.visual_flags || {};
  const nWarn = Object.values(vflags).filter(f => f.level === 'warn').length;
  const nHint = Object.values(vflags).length - nWarn;
  if (stage && (nWarn || nHint)) html += castChangedNote(nWarn, nHint);
  let chapter = 0, seconds = 0;
  p.slides.forEach((s, i) => {
    html += `<div class="script-unit" data-index="${i}">
    ${s.chapter ? `<div class="script-chapter">
      <button type="button" class="btn sm ghost" draggable="true" ondragstart="event.dataTransfer.setData('text/plain','${s.id}')"
        onkeydown="scriptChapterKey(event,${i})" aria-label="Move chapter ${esc(s.chapter)}" title="Drag chapter; Alt + arrows to move">⠿</button>
      <span class="mono">Chapter ${++chapter} · ${fmtTime(seconds)}</span>
      <input type="text" value="${esc(s.chapter)}" aria-label="Chapter title" onblur="saveChapter('${s.id}',this.value)">
      <button class="btn sm ghost" onclick="saveChapter('${s.id}','')">Remove</button></div>` : ''}
    <article class="script-card" data-sid="${s.id}" tabindex="0" aria-label="Paragraph ${i + 1}"
      onkeydown="scriptKey(event,${i})" ondragover="event.preventDefault()"
      ondrop="event.preventDefault(); scriptMoveChapter(event.dataTransfer.getData('text/plain'),'${s.id}')">
      <div class="script-number"><span>${String(i + 1).padStart(2, '0')}</span><span class="script-dot" aria-hidden="true"></span></div>
      <div class="script-content">
        <textarea rows="3" class="script-text" aria-label="Narration, paragraph ${i + 1}" oninput="scriptFit(this)" onblur="scriptSave('${s.id}',{narration:this.value})">${esc(s.narration)}</textarea>
        <div class="script-fields"><label class="kicker" for="picture-${s.id}">Picture</label>
          <input id="picture-${s.id}" type="text" value="${esc(s.visual_note || '')}" placeholder="Picture note" onchange="${stage ? 'saveVisual' : 'scriptSaveVisual'}('${s.id}',this.value)">
          <label class="kicker" for="title-${s.id}">Title</label>
          <input id="title-${s.id}" type="text" value="${esc(s.title)}" placeholder="On-screen title (optional)" onblur="scriptSave('${s.id}',{title:this.value})"></div>
        ${stage && vflags[s.id] ? `<div class="visual-line ${vflags[s.id].level}"><span>${esc(vflags[s.id].text)}</span><button class="btn sm ghost" onclick="reviseVisuals(['${s.id}'])">Rewrite visual</button></div>` : ''}
        <div class="script-inline" data-findings="${s.id}"></div>
        <div class="script-footer"><span class="mono script-word-count">${s.word_count} words · ${fmtTime(s.word_count / 158 * 60)}</span>
          <button class="btn sm ghost" onclick="rewrite('${s.id}')">Rewrite</button>
          <button class="btn sm ghost" onclick="splitSlide('${s.id}')">Split</button>
          ${s.chapter ? '' : `<button class="btn sm ghost" onclick="startChapter('${s.id}')">Start a chapter</button>`}
          <span class="script-voice">${s.on_camera ? 'On camera · ' : ''}${s.take ? (s.take.synthetic ? 'Draft voice' : 'Recorded') : 'Not voiced'}</span>
          <details><summary>More</summary>
            <label><input type="checkbox" ${s.on_camera ? 'checked' : ''} onchange="scriptCamera('${s.id}',this.checked)"> On camera</label>
            <button class="btn sm ghost danger" onclick="delSlide('${s.id}')">Delete paragraph</button></details>
        </div></div></article></div>`;
    seconds += s.take?.duration || s.word_count / 158 * 60;
  });
  html += `<details class="script-camera"><summary>On camera / presenter</summary>${presenterPanel(p)}</details>
    </section><aside class="script-check" aria-label="Script check"><h2 class="kicker">Check · words only</h2>
      <div id="script-check-results" role="status">Loading check…</div></aside></div>`;
  $('#tabbody').innerHTML = html;
  document.querySelectorAll('.script-text').forEach(scriptFit);
  scriptLoadCheck();

}

// The dossier research.gather() found before a word was written — see
// app/research.py. A video scripted before that existed, or with SEARXNG_URL
// unset, has an empty one and this renders nothing.
function sourcesPanel(research) {
  const facts = research.facts || [];
  if (!facts.length) return '';
  const dotColor = { high: 'var(--good)', medium: 'var(--cool)', low: 'var(--ink-faint)' };
  return `<details class="panel" style="margin-bottom:16px">
    <summary style="cursor:pointer;font-weight:600">
      Sources — ${facts.length} researched fact${facts.length === 1 ? '' : 's'}
      ${research.source_count ? `from ${research.source_count} page(s)` : ''}
    </summary>
    <div style="margin-top:14px;display:flex;flex-direction:column;gap:9px">
      ${facts.map((f) => `
        <div style="font-size:13.5px;line-height:1.5">
          <span class="dot" style="background:${dotColor[f.confidence] || dotColor.medium};
                display:inline-block;margin-right:7px"></span>
          ${esc(f.claim)}${f.date ? ` <span class="mono" style="color:var(--ink-faint)">(${esc(f.date)})</span>` : ''}
          — ${f.url
            ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source || 'source')}</a>`
            : `<span style="color:var(--ink-faint)">${esc(f.source || 'source')}</span>`}
        </div>`).join('')}
    </div>
    ${(research.open_questions || []).length ? `
      <div style="margin-top:14px">
        <strong style="font-size:13px">Left unclear by research</strong>
        <ul style="margin:6px 0 0;padding-left:20px;font-size:13px;color:var(--ink-dim)">
          ${research.open_questions.map((q) => `<li>${esc(q)}</li>`).join('')}
        </ul>
      </div>` : ''}
    ${(research.corrections || []).length ? `
      <div style="margin-top:14px">
        <strong style="font-size:13px;color:var(--bad)">Corrected the original idea</strong>
        <ul style="margin:6px 0 0;padding-left:20px;font-size:13px;color:var(--ink-dim)">
          ${research.corrections.map((c) => `<li>${esc(c)}</li>`).join('')}
        </ul>
      </div>` : ''}
  </details>`;
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

function startChapter(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  saveChapter(sid, s.title || (s.beat || '').slice(0, 60) || 'New chapter');
}

async function saveChapter(sid, text) {
  const s = state.project.slides.find((x) => x.id === sid);
  if ((s.chapter || '') === (text || '')) return;
  await saveSlide(sid, { chapter: text });
  // The run grouping and the pauses both move with it, so repaint rather than
  // leaving the page showing the old shape of the cut.
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}

async function saveSlide(sid, patch) {
  try {
    const s = await api(`/api/projects/${state.project.id}/slides/${sid}`,
      { method: 'PATCH', body: JSON.stringify(patch) });
    Object.assign(state.project.slides.find((x) => x.id === sid), s);
    toast('saved');
    return s;
  } catch (e) { toast(e.message, true); }
}

// A 3D explainer's visual line: what the stage shows under this paragraph,
// in the form the writer was told to use ("3D: subject — part — shot" or
// "PHOTO: …"). Flagged when the cast no longer matches it (app/cast.py,
// check_visuals).
function visualLine(s, flag) {
  return `<div class="visual-line ${flag ? flag.level : ''}">
    <span class="kicker">visual</span>
    <input type="text" value="${esc(s.visual_note)}" aria-label="what the stage shows"
      onchange="saveVisual('${s.id}', this.value)">
    ${flag ? `<span class="pill ${flag.level === 'warn' ? 'warn' : ''}" title="${esc(flag.text)}"><span class="dot"></span>${esc(flag.text)}</span>
      <button class="btn xs ghost" onclick="reviseVisuals(['${s.id}'])">rewrite</button>` : ''}
  </div>`;
}
function castChangedNote(nWarn, nHint) {
  return `<div class="card cast-changed">
    <span>${nWarn ? `<strong>${nWarn} visual line${nWarn === 1 ? '' : 's'}</strong> no longer fit${nWarn === 1 ? 's' : ''} the cast` : ''}${nWarn && nHint ? ' · ' : ''}${nHint ? `${nHint} photo beat${nHint === 1 ? '' : 's'} could be 3D now` : ''}.
      The narration is untouched; only the visual lines are rewritten.</span>
    <div class="spacer"></div>
    <button class="btn sm primary" onclick="reviseVisuals()">rewrite ${nWarn + nHint === 1 ? 'it' : 'them'}</button>
  </div>`;
}
// The flags depend on the visual line, so a saved edit reloads the project.
async function saveVisual(sid, value) {
  if (!(await saveSlide(sid, { visual_note: value }))) return;
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}
async function reviseVisuals(ids) {
  try {
    const r = await api(`/api/projects/${state.project.id}/cast/revise`,
      { method: 'POST', body: JSON.stringify(ids ? { slides: ids } : {}) });
    watchJob(r.job, 'visuals');
  } catch (e) { toast(e.message, true); }
}

async function rewrite(sid) {
  const instruction = prompt('How should this paragraph change?\n(blank = tighten and make it more concrete)');
  if (instruction === null) return;
  const r = await api(`/api/projects/${state.project.id}/slides/${sid}/rewrite`,
    { method: 'POST', body: JSON.stringify({ instruction }) });
  watchJob(r.job, 'rewrite');
  render();
}

async function splitSlide(sid) {
  state.project = await api(`/api/projects/${state.project.id}/slides/${sid}/split`,
    { method: 'POST' });
  render();
}

async function delSlide(sid) {
  if (!confirm('Delete this paragraph?')) return;
  await api(`/api/projects/${state.project.id}/slides/${sid}`, { method: 'DELETE' });
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}

async function reimport(fidelity) {
  const label = fidelity || state.project.fidelity;
  if (!confirm(`Re-split your pasted script as "${label}"?\n`
    + 'Recorded takes are kept but will no longer line up with the new paragraphs.')) return;
  const r = await api(`/api/projects/${state.project.id}/reimport`,
    { method: 'POST', body: JSON.stringify(fidelity ? { fidelity } : {}) });
  watchJob(r.job, 're-import');
  render();
}

// `fresh` throws away an unfinished draft instead of carrying it on. Only the
// rewrite of an existing script needs confirming — there is nothing to lose in
// resuming, and a project with no slides has nothing to overwrite.
async function regenScript(fresh) {
  const p = state.project;
  const written = Object.keys((p.draft || {}).sections || {}).length;
  if (p.slides.length
      && !confirm('Rewrite the whole script? Recorded takes will be kept but will no longer match.')) return;
  if (fresh && written
      && !confirm(`Throw away the ${written} section${written === 1 ? '' : 's'} `
                  + 'already written and start from a new outline?')) return;
  const r = await api(`/api/projects/${p.id}/script`,
    { method: 'POST', body: JSON.stringify({ fresh: !!fresh }) });
  watchJob(r.job, 'script');
  render();
}

async function suggestChapters(button) {
  const pid = state.project.id;
  button.disabled = true;
  try {
    const proposals = await api(`/api/projects/${pid}/chapters/suggest`, {method: 'POST'});
    const panel = $('#chapter-proposals');
    if (!panel || state.project.id !== pid) return;
    panel.innerHTML = proposals.length ? `<div class="panel">
      <p>Applying chapters lengthens the video by roughly 5 seconds per chapter and may split picture runs.</p>
      ${proposals.map((p) => `<label class="row"><input type="checkbox" value="${esc(p.sid)}" checked style="width:auto">
        <span class="mono">${fmtTime(p.t)}</span> ${esc(p.text)}</label>`).join('')}
      <button class="btn sm" onclick="applySuggestedChapters(this)">Apply selected chapters</button>
      </div>` : '<p class="empty-note">No new chapter boundaries found.</p>';
  } catch (e) { toast(e.message, true); }
  finally { button.disabled = false; }
}

async function applySuggestedChapters(button) {
  const pid = state.project.id;
  const sids = [...$('#chapter-proposals').querySelectorAll('input:checked')].map((el) => el.value);
  if (!sids.length) return toast('Select a chapter to apply.');
  button.disabled = true;
  try {
    await api(`/api/projects/${pid}/chapters/suggest`, {
      method: 'POST', body: JSON.stringify({apply: true, sids}),
    });
    if (state.project.id !== pid) return;
    state.project = await api(`/api/projects/${pid}`);
    paintScript();
  } catch (e) { toast(e.message, true); button.disabled = false; }
}

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
    const bySlide = new Map();
    findings.forEach((f, i) => {
      if (!bySlide.has(f.slide_id)) bySlide.set(f.slide_id, []);
      bySlide.get(f.slide_id).push(row(f, i));
    });
    document.querySelectorAll('[data-findings]').forEach(el => {
      el.innerHTML = (bySlide.get(el.dataset.findings) || []).join('');
      el.closest('.script-card').classList.toggle('has-finding', !!el.innerHTML);
    });
    $('#script-check-results').innerHTML = `<div class="script-counts mono">${['P0','P1','P2'].map(l => `<span class="${l}">${l} ${result.counts[l]}</span>`).join('')}</div>
      ${findings.map((f, i) => `<div class="script-check-item"><button class="btn sm ghost mono" onclick="scriptLocate('${f.slide_id}')">${f.level} · ${f.slide_id ? '¶' + (state.project.slides.findIndex(s => s.id === f.slide_id) + 1) : 'Script'}</button>${row(f, i)}</div>`).join('') || '<p>No open word findings.</p>'}
      <button class="btn sm ghost" onclick="scriptLoadCheck()">Refresh check</button>
      <h2 class="kicker">Channel rules applied</h2>
      <p>${result.rules.map(esc).join(' · ') || 'No channel rules set.'}</p>
      <p class="sub">Rules guide writing. This check covers empty narration, open-loop payoffs and researched claim flags; it does not validate arbitrary prose rules.</p>
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

async function scriptSave(sid, patch) {
  const s = state.project.slides.find(s => s.id === sid);
  if (Object.entries(patch).every(([key, value]) => s[key] === value)) return;
  const saved = await saveSlide(sid, patch);
  if (saved) {
    const card = [...document.querySelectorAll('.script-card')].find(el => el.dataset.sid === sid);
    if (card) card.querySelector('.script-word-count').textContent = `${saved.word_count} words · ${fmtTime(saved.word_count / 158 * 60)}`;
    const words = state.project.slides.reduce((n, s) => n + s.word_count, 0);
    if ($('.script-summary')) $('.script-summary').textContent = `${words} words · ${state.project.slides.length} paragraphs · ~${fmtTime(words / 158 * 60)}`;
    scriptLoadCheck(); // Save boundary only; never on keystrokes.
  }
}
function scriptSaveVisual(sid, value) { return scriptSave(sid, {visual_note: value}); }
async function scriptCamera(sid, value) {
  await scriptSave(sid, {on_camera: value});
  state.project = await api(`/api/projects/${state.project.id}`);
  paintScript();
}
function scriptFind(value) {
  const query = value.toLocaleLowerCase();
  let count = 0;
  document.querySelectorAll('.script-unit').forEach(el => {
    const s = state.project.slides[Number(el.dataset.index)];
    el.hidden = ![s.narration, s.title, s.visual_note, s.chapter].some(t => (t || '').toLocaleLowerCase().includes(query));
    if (!el.hidden) count++;
  });
  $('#script-find-count').textContent = `${count} paragraphs`;
}
function scriptKey(e, i) {
  if (e.key === 'Escape') {
    e.preventDefault(); e.target.blur(); e.currentTarget.focus(); return;
  }
  if (e.target !== e.currentTarget || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.querySelector('textarea').focus(); return; }
  if (!['j', 'k', 'ArrowDown', 'ArrowUp'].includes(e.key)) return;
  e.preventDefault();
  const cards = [...document.querySelectorAll('.script-unit:not([hidden]) .script-card')];
  const at = cards.indexOf(e.currentTarget) + (['j','ArrowDown'].includes(e.key) ? 1 : -1);
  cards[at]?.focus();
}
async function scriptMoveChapter(source, target) {
  if (!source || source === target) return;
  try {
    state.project = await api(`/api/projects/${state.project.id}/chapters/move`, {method: 'POST', body: JSON.stringify({source, target})});
    paintScript(); scriptLocate(target);
  } catch (e) { toast(e.message, true); }
}
async function scriptChapterKey(e, i) {
  if (!e.altKey || !['ArrowUp','ArrowDown'].includes(e.key)) return;
  e.preventDefault();
  const p = state.project, target = p.slides[i + (e.key === 'ArrowUp' ? -1 : 1)];
  if (target) {
    await scriptMoveChapter(p.slides[i].id, target.id);
    document.activeElement.closest('.script-unit')?.querySelector('[draggable]')?.focus();
  }
}

// Paragraphs show their whole text; the box grows with it instead of scrolling.
function scriptFit(el) {
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 2 + 'px';
}

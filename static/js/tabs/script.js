
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
  const stage = isStage(p.style.format), vflags = p.visual_flags || {}, runs = scriptRuns(p);
  let html = `<div class="script-workspace" onkeydown="scriptWorkspaceKey(event)"><div class="script-tools">
    <button class="btn sm script-binder-toggle" onclick="$('.script-layout').classList.toggle('binder-open')">Binder</button>
    <button class="btn sm" onclick="regenScript()">Rewrite script</button>
    ${p.has_source ? `<span class="pill">${esc(p.fidelity)} import</span>
      <button class="btn sm" onclick="reimport('${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}')">Re-split as ${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}</button>
      <button class="btn sm ghost" onclick="reimport('')">Re-split again</button>` : ''}
    <button class="btn sm" onclick="suggestChapters(this)">Suggest chapters</button>
    <button class="btn sm" onclick="scriptOpenFind()">Find</button>
    <a class="btn sm" href="/projects/${encodeURIComponent(p.id)}/shot-list" target="_blank" rel="noopener">Shot list for the shoot</a>
    </div><div id="script-find" hidden><label>Find in script <input type="search" oninput="scriptFind(this.value)"></label>
    <button class="btn sm ghost" onclick="scriptFind(''); this.previousElementSibling.querySelector('input').value=''; this.parentElement.hidden=true">Close find</button>
    <span id="script-find-count" class="mono" role="status"></span></div><div id="chapter-proposals"></div>
    <div class="script-layout">
    <nav class="script-binder" aria-label="Script binder">${scriptBinder(p)}</nav>
    <div class="script-splitter" role="separator" tabindex="0" aria-label="Binder width" aria-orientation="vertical" onpointerdown="scriptResize(event,'binder')" onkeydown="scriptResizeKey(event,'binder')"></div>
    <section class="script-main" aria-label="Script document"><div class="script-page">`;
  runs.forEach((run, shot) => {
    const lead = run[0];
    html += `${lead.chapter ? `<h2 class="script-chapter">${esc(lead.chapter)}</h2>` : ''}<section class="script-shot" data-script-shot="${lead.id}">
      ${scriptShotHeader(p, lead, shot)}`;
    run.forEach(s => {
      const i = p.slides.indexOf(s);
      html += `<div class="script-unit" data-index="${i}">
        <article class="script-card" data-sid="${s.id}" tabindex="-1" onfocusin="scriptCurrent('${s.id}')" aria-label="Paragraph ${i + 1}">`;
      if (s.insert?.kind) {
        html += `<strong>Insert · ${esc(s.insert.kind)} · ${s.insert.seconds.toFixed(1)} s</strong>
          <p>${esc(s.insert.text || s.insert.block || s.insert.asset_id || s.insert.source_id || '')}</p>
          <a class="btn sm" href="#/p/${p.id}/edit">Edit in timeline</a>`;
      } else {
        html += `<div class="script-text" data-para="${s.id}" contenteditable="plaintext-only" role="textbox" aria-multiline="true" aria-label="Narration, paragraph ${i + 1}"
          oninput="scriptInput(this,'${s.id}')" oncompositionstart="scriptComposing=true; clearTimeout(scriptTimer)" oncompositionend="scriptComposing=false; scriptInput(this,'${s.id}')" onblur="scriptFlush()" onpaste="scriptPaste(event)" onkeydown="scriptEditorKey(event,'${s.id}')">${esc(scriptDrafts.get(s.id)?.text ?? s.narration)}</div>
          <span class="script-voice mono">${scriptVoice(s)}</span>`;
      }
      html += `</article></div>`;
    });
    html += '</section>';
  });
  html += `</div></section><div class="script-splitter" role="separator" tabindex="0" aria-label="Inspector width" aria-orientation="vertical" onpointerdown="scriptResize(event,'inspector')" onkeydown="scriptResizeKey(event,'inspector')"></div>
    <aside class="script-check" aria-label="Paragraph inspector">`;
  p.slides.forEach(s => {
    html += `<div data-script-inspector="${s.id}" hidden><h2 class="kicker">${s.insert?.kind ? 'Insert' : 'Paragraph'} · ${p.slides.indexOf(s) + 1}</h2>`;
    html += `${scriptDetail('title', 'Title and chapter', `<label>Lower-third text<input value="${esc(s.title)}" onblur="scriptSave('${s.id}',{title:this.value})"></label>
        <label>Chapter name<input value="${esc(s.chapter)}" onblur="saveChapter('${s.id}',this.value)"></label>
        ${s.chapter ? `<button class="btn sm ghost" onclick="saveChapter('${s.id}','')">Remove chapter</button>` : ''}`)}`;
    if (!s.insert?.kind) html += `${scriptDetail('findings', 'Findings', `<div data-findings="${s.id}"></div>
        ${p.has_source && p.fidelity === 'faithful' ? '' : `<button class="btn sm ghost" data-style-slide="${s.id}" hidden onclick="smoothFlaggedLines('${s.id}',this)">Smooth flagged lines</button>`}
        <div class="script-style-proposal" data-style-proposal="${s.id}" aria-live="polite"></div>`)}
      <div class="script-footer"><span class="mono script-word-count" data-script-count="${s.id}">${s.word_count} words</span>
        <button class="btn sm ghost" onclick="rewrite('${s.id}')">Rewrite</button><button class="btn sm ghost" onclick="splitSlide('${s.id}')">Split</button>
        <button class="btn sm ghost" onclick="startChapter('${s.id}')">Start a chapter</button>
        ${s.duplicate_of ? '<span class="pill">Duplicate paragraph</span>' : ''}
        <label><input type="checkbox" ${s.on_camera ? 'checked' : ''} onchange="scriptCamera('${s.id}',this.checked)"> On camera</label>
        <button class="btn sm ghost danger" onclick="delSlide('${s.id}')">Delete paragraph</button></div>`;
    html += '</div>';
  });
  const nWarn = Object.values(vflags).filter(f => f.level === 'warn').length;
  if (stage && Object.keys(vflags).length) html += castChangedNote(nWarn, Object.keys(vflags).length - nWarn);
  html += `${sourcesPanel(p.research || {})}
    ${p.research?.facts?.length ? '<button class="btn sm ghost" onclick="runFactcheck()">Check facts</button>' : ''}
    ${p.has_source && p.fidelity === 'faithful' ? '' : '<button class="btn sm" data-style-all disabled onclick="smoothFlaggedLines(null,this)">Smooth flagged lines</button>'}
    ${scriptDetail('check', 'Check · words only', '<div id="script-check-results" role="status">Loading check…</div>')}
    <details class="script-camera"><summary>On camera / presenter</summary>${presenterPanel(p)}</details></aside></div>
    <div class="script-status"><span class="mono script-summary"></span><span class="mono" id="script-current-count"></span>
    <span class="mono" id="script-save-status" role="status">Saved</span><button class="btn sm" onclick="scriptFlush()">Save</button>
    <button class="btn sm" onclick="scriptFocus()">Focus mode</button><label><input type="checkbox" id="script-typewriter" onchange="scriptRemember('typewriter',this.checked)"> Typewriter scrolling</label></div></div>`;
  $('#tabbody').innerHTML = html;
  const toolbar = $('#script-toolbar');
  if (toolbar) toolbar.replaceChildren($('.script-tools'));
  const layout = $('.script-layout');
  for (const pane of ['binder', 'inspector']) scriptWidth(pane, scriptPreference(pane, pane === 'binder' ? 240 : 340));
  layout.classList.toggle('script-focus', scriptPreference('focus', false));
  $('#script-typewriter').checked = scriptPreference('typewriter', false);
  scriptCurrent(p.slides.some(s => s.id === scriptActive) ? scriptActive : p.slides[0].id);
  scriptLoadCheck();
}

// The dossier research.gather() found before a word was written — see
// app/research.py. A video scripted before that existed, or with SEARXNG_URL
// unset, has an empty one and this renders nothing.
function sourcesPanel(research) {
  const facts = research.facts || [];
  if (!facts.length) return '';
  const dotColor = { high: 'var(--good)', medium: 'var(--cool)', low: 'var(--ink-faint)' };
  return `<details id="script-sources" ${scriptPreference('facts', true) ? 'open' : ''} ontoggle="scriptRemember('facts',this.open)" style="margin-bottom:16px">
    <summary style="cursor:pointer;font-weight:600">
      Facts and sources — ${facts.length} researched fact${facts.length === 1 ? '' : 's'}
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

function startChapter(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  saveChapter(sid, s.title || (s.beat || '').slice(0, 60) || 'New chapter');
}

async function saveChapter(sid, text) {
  if (!(await scriptFlush())) return;
  const s = state.project.slides.find((x) => x.id === sid);
  if ((s.chapter || '') === (text || '')) return;
  if (!(await scriptSave(sid, { chapter: text }))) return;
  // The run grouping and the pauses both move with it, so repaint rather than
  // leaving the page showing the old shape of the cut.
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}

async function saveSlide(sid, patch, history = {}, project = state.project) {
  const {quiet, ...requestHistory} = history;
  try {
    const {project_version, ...s} = await api(`/api/projects/${project.id}/slides/${sid}`,
      { method: 'PATCH', body: JSON.stringify(patch), ...requestHistory });
    Object.assign(project.slides.find((x) => x.id === sid), s);
    if (project_version != null) project.updated_at = project_version;
    if (!quiet) toast('saved');
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
  if (!(await scriptFlush())) return;
  if (!(await scriptSave(sid, { visual_note: value }))) return;
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}
async function reviseVisuals(ids) {
  if (!(await scriptFlush())) return;
  try {
    const r = await api(`/api/projects/${state.project.id}/cast/revise`,
      { method: 'POST', body: JSON.stringify(ids ? { slides: ids } : {}) });
    watchJob(r.job, 'visuals');
  } catch (e) { toast(e.message, true); }
}

async function rewrite(sid) {
  if (!(await scriptFlush())) return;
  const instruction = prompt('How should this paragraph change?\n(blank = tighten and make it more concrete)');
  if (instruction === null) return;
  const r = await api(`/api/projects/${state.project.id}/slides/${sid}/rewrite`,
    { method: 'POST', body: JSON.stringify({ instruction }) });
  watchJob(r.job, 'rewrite');
  render();
}

let scriptStyleVersion = 0;
async function smoothFlaggedLines(sid, button) {
  if (!(await scriptFlush())) return;
  const pid = state.project.id, version = ++scriptStyleVersion;
  button.disabled = true;
  const label = button.textContent;
  button.textContent = 'Smoothing flagged lines…';
  try {
    const r = await api(`/api/projects/${pid}/style/revise`, {
      method: 'POST', body: JSON.stringify(sid ? {slides: [sid]} : {}),
    });
    if (state.project?.id !== pid || state.tab !== 'script' || version !== scriptStyleVersion) return;
    watchJob(r.job, 'smooth flagged lines', job => {
      if (job.state !== 'done' || state.project?.id !== pid || state.tab !== 'script' || version !== scriptStyleVersion) return;
      scriptShowStyleProposals(pid, sid, job.result);
    });
  } catch (e) { toast(e.message, true); }
  finally { button.disabled = false; button.textContent = label; }
}

function scriptShowStyleProposals(pid, sid, proposals) {
  document.querySelectorAll('[data-style-proposal]').forEach(el => {
    if (!sid || el.dataset.styleProposal === sid) el.replaceChildren();
  });
  if (!proposals.length) return toast('No safe changes proposed.');
  proposals.forEach(p => {
    const host = [...document.querySelectorAll('[data-style-proposal]')].find(el => el.dataset.styleProposal === p.slide_id);
    if (!host) return;
    host.innerHTML = `<p>${p.reasons.map(esc).join(' ')}</p>
      <div class="mono"><span>Before</span><del>${esc(p.before)}</del>
      <span>After</span><ins>${esc(p.after)}</ins></div>
      <button class="btn sm">Apply</button> <button class="btn sm ghost">Reject</button>`;
    const [apply, reject] = host.querySelectorAll('button');
    reject.onclick = () => host.replaceChildren();
    apply.onclick = async () => {
      if (!(await scriptFlush())) return;
      apply.disabled = true;
      try {
        const {project_version, ...saved} = await scriptPauseEditor(() => api(`/api/projects/${pid}/style/apply`, {method: 'POST', body: JSON.stringify(p)}));
        if (state.project?.id !== pid || state.tab !== 'script') return;
        Object.assign(state.project.slides.find(s => s.id === saved.id), saved);
        if (project_version != null) state.project.updated_at = project_version;
        const text = document.querySelector(`[data-sid="${saved.id}"] .script-text`);
        text.textContent = saved.narration;
        scriptStats();
        host.replaceChildren();
        scriptLoadCheck();
      } catch (e) { toast(e.message, true); apply.disabled = false; }
    };
  });
}

async function splitSlide(sid) {
  if (!(await scriptFlush())) return;
  await scriptPauseEditor(async () => {
    state.project = await api(`/api/projects/${state.project.id}/slides/${sid}/split`,
      { method: 'POST' });
    await render();
  });
}

async function delSlide(sid) {
  if (!(await scriptFlush())) return;
  if (!confirm('Delete this paragraph?')) return;
  return scriptPauseEditor(async () => {
    await api(`/api/projects/${state.project.id}/slides/${sid}`, { method: 'DELETE' });
    state.project = await api(`/api/projects/${state.project.id}`);
    await render();
    return true;
  });
}

async function reimport(fidelity) {
  if (!(await scriptFlush())) return;
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
  if (!(await scriptFlush())) return;
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
  if (!(await scriptFlush())) return;
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
  if (!(await scriptFlush())) return;
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

function scriptSave(sid, patch) {
  const project = state.project;
  const task = scriptWrites.then(async () => {
    const s = project.slides.find(s => s.id === sid);
    if (Object.entries(patch).every(([key, value]) => s[key] === value)) return true;
    const saved = await saveSlide(sid, patch, {quiet: true}, project);
    if (!saved) return false;
    if (state.project === project) { scriptStats(); scriptLoadCheck(); }
    return true;
  });
  scriptWrites = task.catch(() => {});
  return task;
}
function scriptSaveVisual(sid, value) { return scriptSave(sid, {visual_note: value}); }
async function scriptCamera(sid, value) {
  if (!(await scriptFlush())) return;
  if (!(await scriptSave(sid, {on_camera: value}))) return;
  state.project = await api(`/api/projects/${state.project.id}`);
  paintScript();
}
function scriptFind(value) {
  const query = value.toLocaleLowerCase();
  let count = 0;
  document.querySelectorAll('.script-unit').forEach(el => {
    const s = state.project.slides[Number(el.dataset.index)];
    el.hidden = ![(scriptDrafts.get(s.id)?.text ?? s.narration), s.title, s.visual_note, s.chapter, s.insert?.text, s.insert?.kind].some(t => (t || '').toLocaleLowerCase().includes(query));
    if (!el.hidden) count++;
  });
  document.querySelectorAll('[data-script-shot]').forEach(el => { el.hidden = !el.querySelector('.script-unit:not([hidden])'); });
  $('#script-find-count').textContent = `${count} items`;
}


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
  const flagsBySlide = {};
  (research.flags || []).forEach((f) => { flagsBySlide[f.slide_id] = f; });

  let html = sourcesPanel(research);
  html += `<div class="row" style="margin-bottom:16px">
    <span class="mono" style="color:var(--ink-faint)">${words} words · ${p.slides.length} paragraphs ·
      ~${fmtTime(p.est_seconds)} at a documentary pace</span>
    <div class="spacer"></div>
    <a class="btn sm" href="/projects/${encodeURIComponent(p.id)}/shot-list" target="_blank" rel="noopener">Shot list</a>
    <button class="btn sm" onclick="suggestChapters(this)">Suggest chapters</button>
    ${research.facts && research.facts.length
      ? `<button class="btn sm ghost" onclick="runFactcheck()">check facts</button>` : ''}
    ${p.has_source ? `
      <span class="pill">${esc(p.fidelity)} import</span>
      <button class="btn sm" onclick="reimport('${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}')">
        re-split as ${p.fidelity === 'faithful' ? 'adapted' : 'faithful'}</button>
      <button class="btn sm ghost" onclick="reimport('')">re-split again</button>`
    : `<button class="btn sm danger" onclick="regenScript()">rewrite whole script</button>`}
  </div><div id="chapter-proposals"></div>`;

  const stage = isStage(p.style.format), vflags = p.visual_flags || {};
  const nWarn = Object.values(vflags).filter((f) => f.level === 'warn').length;
  const nHint = Object.values(vflags).length - nWarn;
  if (stage && (nWarn || nHint)) html += castChangedNote(nWarn, nHint);

  let lastBeat = null;
  p.slides.forEach((s, i) => {
    if (s.beat !== lastBeat) {
      lastBeat = s.beat;
      html += `<div class="section-head">
        <span class="kicker">${esc(s.section)}</span>
        <strong>${esc(s.beat || '')}</strong></div>`;
    }
    const flag = flagsBySlide[s.id];
    html += `${s.chapter ? `<div class="chapter-mark">
        <span class="kicker">chapter</span>
        <input type="text" value="${esc(s.chapter)}" aria-label="chapter title"
          onblur="saveChapter('${s.id}',this.value)">
        <button class="btn sm ghost" title="drop the chapter card"
          onclick="saveChapter('${s.id}','')">remove</button>
      </div>` : ''}
    <div class="card slide-card" data-sid="${s.id}">
      <div class="slide-num">${String(i + 1).padStart(2, '0')}${s.take ? '<br>●' : ''}</div>
      <div>
        <textarea rows="3" onblur="saveSlide('${s.id}',{narration:this.value})"
          >${esc(s.narration)}</textarea>
        ${stage ? visualLine(s, vflags[s.id]) : ''}
        <div class="slide-meta">
          <input class="title-input" type="text" placeholder="on-screen title (optional)"
            value="${esc(s.title)}" onblur="saveSlide('${s.id}',{title:this.value})">
          <span class="mono" style="color:var(--ink-faint)">${s.word_count}w
            ≈ ${fmtTime(s.word_count / 158 * 60)}</span>
          ${flag ? `<span class="pill warn" title="${esc(flag.claim)}: ${esc(flag.issue)}">
              <span class="dot"></span>${flag.severity === 'high' ? 'unsupported claim' : 'check this'}</span>` : ''}
          <div class="spacer"></div>
          ${s.take ? '<span class="pill on"><span class="dot"></span>recorded</span>' : ''}
          ${s.chapter ? '' : `<button class="btn sm ghost" title="a full-frame card before this paragraph"
            onclick="startChapter('${s.id}')">start a chapter</button>`}
          <button class="btn sm ghost" onclick="rewrite('${s.id}')">rewrite</button>
          <button class="btn sm ghost" onclick="splitSlide('${s.id}')">split</button>
          <button class="btn sm ghost danger" onclick="delSlide('${s.id}')">delete</button>
        </div>
      </div>
    </div>`;
  });
  $('#tabbody').innerHTML = html;
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

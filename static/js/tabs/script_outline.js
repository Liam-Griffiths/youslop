/* Plan: outline sections remain the writer's beats; chapter labels group them. */
let planOutline = null;
let planSelectedSource = null;

async function paintScriptOutline() {
  const pid = state.project.id;
  const outline = await api(`/api/projects/${pid}/plan`);
  if (state.project?.id !== pid || state.tab !== 'plan') return;
  planOutline = outline;
  planSelectedSource = null;
  state.scriptFindings = [];
  planDraw();
  try {
    const result = await api(`/api/projects/${pid}/script-check`);
    if (state.project?.id !== pid || state.tab !== 'plan') return;
    state.scriptFindings = result.findings || [];
    document.querySelectorAll('[data-shot]').forEach(el => {
      const ids = outlineShots()[Number(el.dataset.shot)].map(s => s.id);
      const count = (result.findings || []).filter(f => ids.includes(f.slide_id) && f.state !== 'dismissed').length;
      el.querySelector('[data-outline-findings]').textContent = count ? `● ${count} findings` : 'No findings';
    });
  } catch (e) { toast(e.message, true); }
}

function planSources() {
  const research = (state.project.research?.facts?.length || state.project.research?.sources?.length) ? state.project.research : state.project.draft?.research || {};
  const sources = new Map();
  for (const s of [...(research.sources || []), ...(research.facts || []), ...(planOutline.sources || [])]) {
    const key = s.url || s.source || s.title;
    if (key && !sources.has(key)) sources.set(key, {key, title: s.title || s.source || key, where: s.url || s.where || 'Research note'});
  }
  return [...sources.values()];
}

function planChapters() {
  return [...new Set([...(planOutline.chapters || []), ...(planOutline.sections || []).map(s => s.chapter)])];
}

function planDraw(focusId) {
  const chapters = planChapters(), sources = planSources(), scripted = state.project.slides.length > 0;
  const columns = scripted ? outlineColumns() : chapters.map(name => ({name}));
  planOutline.chapters = chapters;
  const beats = (planOutline.sections ||= []);
  beats.sort((a, b) => chapters.indexOf(a.chapter) - chapters.indexOf(b.chapter));
  const hook = planOutline.hook || {};
  $('#tabbody').innerHTML = `<div class="plan-layout" data-card-size="${scriptPreference('cards', 1)}">
    <details class="plan-sources" ${scriptPreference('outline-sources', false) ? 'open' : ''} ontoggle="scriptRemember('outline-sources',this.open)"><summary>Research sources · ${sources.length}</summary>
      <h2 class="kicker">Research · <span class="mono">${sources.length} sources</span></h2>
      <label for="plan-filter">Filter sources</label>
      <input id="plan-filter" type="search" placeholder="Filter sources" oninput="planFilter(this.value)">
      <p class="sub">Select a source, then cite it on a beat. Drag sources or beat handles; Alt + arrows moves a focused beat.</p>
      <div id="plan-source-list">${sources.map((s, i) => {
        const count = beats.filter(b => (b.sources || []).includes(s.key)).length;
        return `<button type="button" class="btn plan-source ${planSelectedSource === s.key ? 'selected' : ''}" data-source="${i}" aria-pressed="${planSelectedSource === s.key}" onclick="planSelectSource(${i})">
          <strong>${esc(s.title)}</strong><span class="mono">${esc(s.where)}</span>
          <span class="${count ? 'plan-used' : ''}">${count ? `cited in ${count} beats` : 'not used yet'}</span></button>`;
      }).join('') || '<p class="sub">No research sources yet. Add a link or note below.</p>'}</div>
      <details><summary>Add a source: link or note</summary>
        <form onsubmit="planAddSource(event)">
          <label>Title<input type="text" name="title" required></label>
          <label>Link or note<input type="text" name="where" required></label>
          <button class="btn" type="submit">Add source</button>
        </form>
      </details>
    </details>
    <section class="plan-outline" aria-label="Outline">
      <div class="row"><h1>Outline</h1><span class="spacer"></span>
        <label class="outline-size" for="outline-size">Cards S / M / L<input id="outline-size" type="range" min="0" max="2" value="${scriptPreference('cards',1)}" oninput="scriptRemember('cards',Number(this.value)); $('.plan-layout').dataset.cardSize=this.value"></label>
        <span class="mono">${columns.length} chapters · ${scripted ? outlineShots().length + ' shots' : beats.length + ' beats'}</span>
        <button class="btn" onclick="planAddChapter()">Add chapter</button></div>
      <details class="plan-premise" ${scripted ? '' : 'open'}>
      <summary>Thesis &amp; hook</summary>
      <label>Thesis<textarea rows="1" oninput="scriptShotFit(this)" onchange="planOutline.thesis=this.value; planPersist()">${esc(planOutline.thesis || '')}</textarea></label>
      <div class="plan-hook"><span class="kicker">Hook</span>
        <label>First image<input type="text" value="${esc(hook.muted_image || '')}" onchange="planHook('muted_image',this.value)"></label>
        <label>First line<input type="text" value="${esc(hook.first_line || '')}" onchange="planHook('first_line',this.value)"></label>
        <span class="${hook.muted_image ? 'plan-used' : 'sub'}">${hook.muted_image ? 'Works muted: image planned' : 'Works muted: needs an image'}</span></div>
      </details>
      <div class="plan-columns">${columns.map(({name:chapter}, ci) => `<section class="plan-column" data-chapter="${ci}" ondragover="event.preventDefault()" ondrop="outlineDrop(event,${ci})" aria-label="${esc(chapter || 'Unchaptered')}">
        <h2>${esc(chapter || 'Unchaptered')}</h2>
        ${scripted ? outlineCards(ci) : ''}
        ${beats.map((b, i) => b.chapter !== chapter ? '' : `${scripted && outlineBeatMatched(b) ? '<details><summary>Edit written beat · ' + esc(b.heading) + '</summary>' : ''}<article class="plan-beat ${scripted ? 'outline-unwritten' : ''}" tabindex="0" data-beat="${i}" onkeydown="planKey(event,${i})" aria-label="${esc(b.heading)}; Alt and arrows to move">
          <div class="plan-beat-head">
            <button class="plan-handle" type="button" data-handle="${i}" aria-label="Drag beat ${esc(b.heading)}" title="Drag to move">⠿</button>
            <textarea rows="2" class="plan-heading" aria-label="Heading" onchange="planField(${i},'heading',this.value)">${esc(b.heading)}</textarea>
          </div>
          <textarea rows="3" aria-label="Beat" onchange="planField(${i},'summary',this.value)">${esc(b.summary || '')}</textarea>
          <div class="plan-tags"><span>${esc(b.kind)}</span>${(b.tags || []).map(t => `<span>${esc(t)}</span>`).join('')}
            <label class="plan-words"><input type="number" min="1" max="10000" aria-label="Word budget" value="${b.words || 220}" onchange="planField(${i},'words',Number(this.value))">words</label></div>
          ${(b.sources || []).length ? `<div class="plan-citations">${b.sources.map((key, si) => `<button class="btn sm ghost" onclick="planUncite(${i},${si})" title="Remove citation">${esc(sources.find(s => s.key === key)?.title || key)} ×</button>`).join('')}</div>` : ''}
          ${planSelectedSource === null ? '' : `<button class="btn sm ghost" onclick="planCite(${i})">Cite selected source</button>`}
        </article>${scripted && outlineBeatMatched(b) ? '</details>' : ''}`).join('')}
        <button class="btn sm outline-add" onclick="${scripted ? 'outlineAdd' : 'planAddBeat'}(${ci})">${scripted ? 'Add shot' : 'Add beat'}</button>
      </section>`).join('') || '<p class="sub">No outline yet. Add a chapter and a beat to start planning.</p>'}</div>
      <div class="row"><button class="btn${scripted ? '' : ' primary'}" onclick="planWrite()" ${beats.length ? '' : 'disabled'}>${scripted ? 'Rewrite changed beats' : 'Write the script'}</button>${beats.length ? '' : '<span class="sub">Add at least one beat first.</span>'}
        <button class="btn sm" onclick="planPersist()">Save / retry</button><span id="plan-save-status" role="status" aria-live="polite">Saved</span></div>
    </section></div>`;
  $('#tabbody').onpointerdown = planPointer;
  const premise = $('.plan-premise');
  const fitThesis = () => { if (premise.open) premise.querySelectorAll('textarea').forEach(scriptShotFit); };
  premise.ontoggle = fitThesis;
  fitThesis();
  if (focusId) [...document.querySelectorAll('[data-beat]')].find(el => beats[Number(el.dataset.beat)].id === focusId)?.focus();
}

function planFilter(value) {
  document.querySelectorAll('.plan-source').forEach(el => { el.hidden = !el.textContent.toLowerCase().includes(value.toLowerCase()); });
}
function planSelectSource(i) { planSelectedSource = planSources()[i].key; planDraw(); }
function planField(i, key, value) { planOutline.sections[i][key] = value; planPersist(); }
function planHook(key, value) { (planOutline.hook ||= {})[key] = value; planPersist(); }
function planCite(i) {
  if (planSelectedSource === null) return;
  const b = planOutline.sections[i];
  b.sources = [...new Set([...(b.sources || []), planSelectedSource])];
  planDraw(b.id); planPersist();
}
function planUncite(i, si) { planOutline.sections[i].sources.splice(si, 1); planDraw(); planPersist(); }
function planAddSource(e) {
  e.preventDefault();
  const data = new FormData(e.target), where = data.get('where').trim();
  (planOutline.sources ||= []).push({title: data.get('title').trim(), where, url: /^https?:\/\//.test(where) ? where : '', source: where});
  planDraw(); planPersist();
}
function planAddChapter() {
  const dialog = studioDialog('outline-chapter', `<h2 id="studio-dialog-title">Add chapter</h2><form method="dialog"><label for="outline-chapter-name">Chapter name</label><input id="outline-chapter-name" required><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn" value="add">Add chapter</button></form>`);
  dialog.addEventListener('close', () => {
    const name = dialog.querySelector('input').value.trim();
    if (dialog.returnValue !== 'add' || !name) return;
    planOutline.chapters = [...new Set([...planChapters(), name])];
    planDraw(); planPersist();
  });
}
function planAddBeat(ci) {
  const b = {id: crypto.randomUUID(), chapter: planChapters()[ci], kind: 'main', heading: 'New beat', summary: '', words: 220};
  (planOutline.sections ||= []).push(b);
  planDraw(b.id); planPersist();
}
function planMove(i, chapter, before) {
  const beats = planOutline.sections, b = beats[i], target = beats[before];
  if (before === i && b.chapter === chapter) return;
  beats.splice(i, 1); b.chapter = chapter;
  let at = target && target !== b ? beats.indexOf(target) : -1;
  if (at < 0) { at = beats.findLastIndex(s => s.chapter === chapter) + 1; if (!at) at = beats.length; }
  beats.splice(at, 0, b); planDraw(b.id); planPersist();
}
function planKey(e, i) {
  if (!e.altKey || !['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) return;
  e.preventDefault();
  const beats = planOutline.sections, b = beats[i], chapters = planChapters();
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    const ci = chapters.indexOf(b.chapter) + (e.key === 'ArrowLeft' ? -1 : 1);
    if (chapters[ci] !== undefined) planMove(i, chapters[ci]);
  } else {
    const peers = beats.filter(s => s.chapter === b.chapter), pi = peers.indexOf(b), down = e.key === 'ArrowDown';
    if (down && pi < peers.length - 1) planMove(i, b.chapter, beats.indexOf(peers[pi + 2]));
    if (!down && pi > 0) planMove(i, b.chapter, beats.indexOf(peers[pi - 1]));
  }
}
function planPointer(e) {
  const handle = e.target.closest('[data-handle]'), source = e.target.closest('[data-source]');
  if ((!handle && !source) || e.button !== 0) return;
  const x = e.clientX, y = e.clientY;
  const up = ev => {
    document.removeEventListener('pointerup', up);
    if (Math.hypot(ev.clientX - x, ev.clientY - y) < 6) return;
    const target = document.elementFromPoint(ev.clientX, ev.clientY), beat = target?.closest('[data-beat]');
    if (source && beat) { planSelectedSource = planSources()[Number(source.dataset.source)].key; planCite(Number(beat.dataset.beat)); }
    if (handle) {
      const col = target?.closest('[data-chapter]');
      if (col) planMove(Number(handle.dataset.handle), (state.project.slides.length ? outlineColumns().map(c=>c.name) : planChapters())[Number(col.dataset.chapter)], beat ? Number(beat.dataset.beat) : undefined);
    }
  };
  document.addEventListener('pointerup', up, {once: true});
}

// Serialize saves; never let a late response replace newer local edits.
let planSaveQueue = Promise.resolve();
function planPersist() {
  const pid = state.project.id, outline = JSON.parse(JSON.stringify(planOutline));
  if ($('#plan-save-status')) $('#plan-save-status').textContent = 'Saving…';
  planSaveQueue = planSaveQueue.catch(() => {}).then(async () => {
    try {
      await api(`/api/projects/${pid}/plan`, {method: 'PATCH', body: JSON.stringify(outline)});
      const fresh = await api(`/api/projects/${pid}`);
      if (state.project?.id === pid) { state.project.outline = outline; state.project.updated_at = fresh.updated_at; }
      if ($('#plan-save-status')) $('#plan-save-status').textContent = 'Saved';
    } catch (e) {
      if ($('#plan-save-status')) $('#plan-save-status').textContent = 'Save failed';
      toast(e.message, true); throw e;
    }
  });
  planSaveQueue.catch(() => {});
  return planSaveQueue;
}
async function planWrite() {
  const pid = state.project.id;
  try {
    await planPersist();
    if (state.project?.id !== pid) return;
    const r = await api(`/api/projects/${pid}/script`, {method: 'POST', body: JSON.stringify({board: true})});
    watchJob(r.job, 'script');
  } catch (e) { toast(e.message, true); }
}

function outlineShots() { return scriptRuns(state.project); }
function outlineBeatMatched(beat) {
  const ids = beat._script?.ids;
  return state.project.slides.some(s => ids ? ids.includes(s.id) : s.beat === beat.heading);
}
function outlineColumns() {
  const columns = [];
  outlineShots().forEach((run, shot) => {
    const lead = run[0];
    const beat = (planOutline.sections || []).find(b => b.heading === lead.beat);
    const chapter = lead.chapter || beat?.chapter || '';
    let col = columns.find(c => c.name === chapter);
    if (!col) columns.push(col = {name:chapter, shots:[]});
    col.shots.push(shot);
  });
  planChapters().forEach(name => { if (!columns.some(c => c.name === name)) columns.push({name,shots:[]}); });
  return columns;
}
function outlineCards(ci) {
  return outlineColumns()[ci].shots.map(index => {
    const run = outlineShots()[index], s = run[0], insert = s.insert?.kind;
    const words = run.reduce((n,s) => n + s.word_count, 0);
    return `<article class="plan-beat outline-shot" data-shot="${index}" tabindex="0" draggable="true"
      ondragstart="outlineDrag(event,${index})" ondragover="event.preventDefault()" ondrop="outlineDrop(event,${ci},${index})"
      onkeydown="outlineKey(event,${index},${ci})" ondblclick="outlineOpen(${index})" aria-label="Shot ${index+1}; Enter to write; Alt and arrows to move">
      <span class="mono">SHOT ${index+1} · ${esc(insert || pictureKind(s,state.project))}</span>
      <h3>${esc(s.narration?.split('\n')[0] || insert || 'Empty shot')}</h3>
      <p>${esc(s.visual_note || 'No shot description')}</p>
      <span class="mono">${run.filter(s => !s.insert?.kind).length} paragraphs · ${words} words</span>
      <span>${run.map(scriptVoice).filter((v,i,a) => a.indexOf(v) === i).map(esc).join(' · ')}</span>
      <span data-outline-findings class="mono">${(state.scriptFindings || []).some(f => run.some(s => s.id === f.slide_id)) ? '● Findings' : 'No findings'}</span>
      <button class="btn sm ghost" onclick="outlineOpen(${index})">${insert ? 'Open insert' : 'Write'}</button></article>`;
  }).join('');
}
function outlineOpen(index) {
  state.focusSlide = outlineShots()[index][0].id;
  go(`#/p/${state.project.id}/script`);
}
function outlineDrag(e,index) {
  e.stopPropagation();
  e.dataTransfer.setData('application/x-corkbored-outline', JSON.stringify({pid:state.project.id,version:state.project.updated_at,ids:outlineShots()[index].map(s=>s.id)}));
}
async function outlineMove(ids, ci, before, version = state.project.updated_at, pid = state.project.id) {
  const col = outlineColumns()[ci], shots = outlineShots();
  const last = col.shots.at(-1), tail = last === undefined ? null : shots[last].at(-1);
  const at = tail ? state.project.slides.findIndex(s => s.id === tail.id) + 1 : state.project.slides.length;
  const to = before === undefined ? state.project.slides[at]?.id || '' : shots[before][0].id;
  try {
    await planSaveQueue;
    if (state.project?.id !== pid) return;
    const project = await api(`/api/projects/${pid}/sections`, {method:'POST',body:JSON.stringify({op:'move',ids,to,chapter:col.name,version})});
    if (state.project?.id !== pid || state.tab !== 'plan') return;
    state.project = project;
    planDraw();
    document.querySelector(`[data-shot="${outlineShots().findIndex(r=>r.some(s=>s.id===ids[0]))}"]`)?.focus();
  } catch(e) { toast(e.message,true); }
}
function outlineDrop(e,ci,before) {
  e.preventDefault(); e.stopPropagation();
  try { const data=JSON.parse(e.dataTransfer.getData('application/x-corkbored-outline')); outlineMove(data.ids,ci,before,data.version,data.pid); } catch { /* Ignore other drags. */ }
}
function outlineKey(e,index,ci) {
  if (e.target !== e.currentTarget) return;
  if (e.key === 'Enter') { e.preventDefault(); outlineOpen(index); return; }
  if (!e.altKey || !['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) return;
  e.preventDefault();
  const cols=outlineColumns(), peers=cols[ci].shots, at=peers.indexOf(index), ids=outlineShots()[index].map(s=>s.id);
  if (e.key === 'ArrowLeft' && ci) outlineMove(ids,ci-1);
  if (e.key === 'ArrowRight' && ci+1<cols.length) outlineMove(ids,ci+1);
  if (e.key === 'ArrowUp' && at) outlineMove(ids,ci,peers[at-1]);
  if (e.key === 'ArrowDown' && at+1<peers.length) outlineMove(ids,ci,peers[at+2]);
}
async function outlineAdd(ci) {
  const pid=state.project.id, col=outlineColumns()[ci], shots=outlineShots(), last=col.shots.at(-1);
  const tail=last === undefined ? null : shots[last].at(-1);
  const at=tail ? state.project.slides.indexOf(tail)+1 : state.project.slides.length;
  try {
    await planSaveQueue;
    if (state.project?.id !== pid) return;
    const project=await api(`/api/projects/${pid}/sections`, {method:'POST',body:JSON.stringify({op:'add',to:state.project.slides[at]?.id || '',chapter:col.name,version:state.project.updated_at})});
    if (state.project?.id !== pid || state.tab !== 'plan') return;
    state.project=project;
    planDraw();
  } catch(e) { toast(e.message,true); }
}

async function outlineFlush() {
  try { await planSaveQueue; return true; } catch { return false; }
}

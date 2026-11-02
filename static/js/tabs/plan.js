/* Plan: outline sections remain the writer's beats; chapter labels group them. */
let planOutline = null;
let planSelectedSource = null;

async function paintPlan() {
  const pid = state.project.id;
  const outline = await api(`/api/projects/${pid}/plan`);
  if (state.project?.id !== pid || state.stage !== 'plan') return;
  planOutline = outline;
  planSelectedSource = null;
  planDraw();
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
  const chapters = planChapters(), sources = planSources();
  planOutline.chapters = chapters;
  const beats = (planOutline.sections ||= []);
  beats.sort((a, b) => chapters.indexOf(a.chapter) - chapters.indexOf(b.chapter));
  const hook = planOutline.hook || {};
  $('#tabbody').innerHTML = `<div class="plan-layout">
    <aside class="plan-sources" aria-label="Research sources">
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
    </aside>
    <section class="plan-outline" aria-label="Outline">
      <div class="row"><h1>Outline</h1><span class="spacer"></span>
        <span class="mono">${chapters.length} chapters · ${beats.length} beats</span>
        <button class="btn" onclick="planAddChapter()">Add chapter</button></div>
      <label>Thesis<input type="text" value="${esc(planOutline.thesis || '')}" onchange="planOutline.thesis=this.value; planPersist()"></label>
      <div class="plan-columns">${chapters.map((chapter, ci) => `<section class="plan-column" data-chapter="${ci}" aria-label="${esc(chapter)}">
        <h2>${esc(chapter)}</h2>
        ${beats.map((b, i) => b.chapter !== chapter ? '' : `<article class="plan-beat" tabindex="0" data-beat="${i}" onkeydown="planKey(event,${i})" aria-label="${esc(b.heading)}; Alt and arrows to move">
          <div class="plan-beat-head">
            <button class="plan-handle" type="button" data-handle="${i}" aria-label="Drag beat ${esc(b.heading)}" title="Drag to move">⠿</button>
            <input type="text" class="plan-heading" aria-label="Heading" value="${esc(b.heading)}" onchange="planField(${i},'heading',this.value)">
          </div>
          <textarea rows="3" aria-label="Beat" onchange="planField(${i},'summary',this.value)">${esc(b.summary || '')}</textarea>
          <div class="plan-tags"><span>${esc(b.kind)}</span>${(b.tags || []).map(t => `<span>${esc(t)}</span>`).join('')}
            <label class="plan-words"><input type="number" min="1" max="10000" aria-label="Word budget" value="${b.words || 220}" onchange="planField(${i},'words',Number(this.value))">words</label></div>
          ${(b.sources || []).length ? `<div class="plan-citations">${b.sources.map((key, si) => `<button class="btn sm ghost" onclick="planUncite(${i},${si})" title="Remove citation">${esc(sources.find(s => s.key === key)?.title || key)} ×</button>`).join('')}</div>` : ''}
          ${planSelectedSource === null ? '' : `<button class="btn sm ghost" onclick="planCite(${i})">Cite selected source</button>`}
        </article>`).join('')}
        <button class="btn sm ghost" onclick="planAddBeat(${ci})">Add beat</button>
      </section>`).join('') || '<p class="sub">No outline yet. Add a chapter and a beat to start planning.</p>'}</div>
      <div class="plan-hook"><span class="kicker">Hook</span>
        <label>First image<input type="text" value="${esc(hook.muted_image || '')}" onchange="planHook('muted_image',this.value)"></label>
        <label>First line<input type="text" value="${esc(hook.first_line || '')}" onchange="planHook('first_line',this.value)"></label>
        <span class="${hook.muted_image ? 'plan-used' : 'sub'}">${hook.muted_image ? 'Muted image planned' : 'Needs a muted image'}</span></div>
      <div class="row"><button class="btn" onclick="planWrite()" ${beats.length ? '' : 'disabled'}>Write the script from this board</button>
        <span id="plan-save-status" role="status" aria-live="polite">Saved</span></div>
    </section></div>`;
  $('#tabbody').onpointerdown = planPointer;
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
  const name = prompt('Chapter name');
  if (!name?.trim()) return;
  planOutline.chapters = [...new Set([...planChapters(), name.trim()])];
  planDraw(); planPersist();
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
      if (col) planMove(Number(handle.dataset.handle), planChapters()[Number(col.dataset.chapter)], beat ? Number(beat.dataset.beat) : undefined);
    }
  };
  document.addEventListener('pointerup', up, {once: true});
}

// Serialize saves; never let a late response replace newer local edits.
let planSaveQueue = Promise.resolve();
function planPersist() {
  const pid = state.project.id, outline = JSON.parse(JSON.stringify(planOutline));
  planSaveQueue = planSaveQueue.catch(() => {}).then(async () => {
    try {
      await api(`/api/projects/${pid}/plan`, {method: 'PATCH', body: JSON.stringify(outline)});
      if (state.project?.id === pid) state.project.outline = outline;
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

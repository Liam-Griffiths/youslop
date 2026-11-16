// Script › Shots: what we see against what we hear, one shot at a time.
// Write stays the words; descriptions, pictures, facts, merges and moving
// paragraphs between shots happen here. Shots are scriptRuns (one description).
let scriptShotPicked = '';

function scriptOpenShot(lead) { scriptShotPicked = lead; }
function scriptShowInWrite(sid) {
  scriptPendingLocate = sid;
  go(`#/p/${state.project.id}/script/script`);
}

function scriptShotRows(p) {
  let seconds = 0, paragraph = 0;
  return scriptRuns(p).map((run, index) => {
    const start = seconds, first = paragraph + 1;
    run.forEach(s => { seconds += scriptSeconds(s); });
    paragraph += run.filter(s => !s.insert?.kind).length;
    const lead = run[0], chosen = lead.candidates?.find(c => c.id === lead.chosen_id);
    return {run, index, lead, chosen, start, end: seconds, first};
  });
}

function scriptShotThumb(row, size = '') {
  return row.chosen
    ? `<img class="shots-thumb ${size}" src="${esc(thumbUrl(row.chosen))}" alt="" loading="lazy">`
    : `<span class="shots-thumb empty ${size}" aria-hidden="true">${row.lead.insert?.kind ? esc(row.lead.insert.kind) : '?'}</span>`;
}
function scriptShotMeta(row) {
  if (row.lead.insert?.kind) return `Insert · ${row.lead.insert.seconds.toFixed(1)} s`;
  const n = row.run.filter(s => !s.insert?.kind).length;
  return `${n} ¶ · ${fmtTime(row.start)}–${fmtTime(row.end)} · ${row.chosen ? 'picture' : 'no picture'}`;
}

function paintScriptShots() {
  const p = state.project;
  if (!p.slides.length) return paintScript();  // the empty-script prompts live there
  const rows = scriptShotRows(p);
  if (!rows.some(r => r.lead.id === scriptShotPicked)) {
    const fromWrite = scriptShotOf(scriptActive).run[0]?.id;
    scriptShotPicked = rows.some(r => r.lead.id === fromWrite) ? fromWrite : (rows.find(r => !r.lead.insert?.kind) || rows[0]).lead.id;
  }
  const row = rows.find(r => r.lead.id === scriptShotPicked);
  let chapterNo = 0;
  const list = rows.map(r => `${r.lead.chapter ? `<h2 class="kicker shots-chapter">Chapter ${++chapterNo} · ${esc(r.lead.chapter)}</h2>` : ''}
    <button class="shots-row" data-shot="${r.lead.id}" ${r === row ? 'aria-current="true"' : ''}
      onclick="scriptPickShot('${r.lead.id}')" onkeydown="scriptShotListKey(event)"
      ${r.lead.insert?.kind ? '' : `ondragover="scriptShotRowOver(event)" ondragleave="this.classList.remove('drop-into')" ondrop="scriptShotRowDrop(event,'${r.lead.id}')"`}>
      ${scriptShotThumb(r)}
      <span class="shots-row-text"><span class="shots-row-title">${r.index + 1} · ${esc(r.lead.insert?.kind ? (r.lead.insert.text || 'Insert') : (r.lead.visual_note || r.chosen?.title || 'No description yet'))}</span>
      <span class="mono shots-row-meta">${scriptShotMeta(r)}</span></span></button>`).join('');
  $('#tabbody').innerHTML = `<div class="shots-layout">
    <nav class="shots-list" aria-label="Shots">
      <p class="sub shots-hint">A shot is the paragraphs that play over one picture or graphic. Drag a paragraph onto a shot here to move it.</p>
      ${list}</nav>
    <section class="shots-detail" id="shots-detail" aria-label="Shot ${row.index + 1}">${scriptShotDetail(p, row, rows)}</section>
    ${row.lead.insert?.kind ? '' : `<aside class="shots-agent" aria-label="Shot agent">${shotAgentPanel(row)}</aside>`}</div>`;
  shotAgentPaint();
  document.querySelector(`.shots-row[data-shot="${row.lead.id}"]`)?.scrollIntoView({block: 'nearest'});
}

function scriptShotDetail(p, row, rows) {
  const {lead, run, index} = row, prev = rows[index - 1];
  const head = `<header class="shots-head"><h1>Shot ${index + 1}</h1><span class="mono">${scriptShotMeta(row)}</span>
    <span class="spacer"></span>
    ${prev && scriptCanMerge(run, prev.run) ? `<button class="btn sm" onclick="scriptMergeShot('${lead.id}')">Merge with shot above</button>` : ''}
    <button class="btn sm" onclick="scriptShowInWrite('${(run.find(s => !s.insert?.kind) || lead).id}')">Show in Write</button></header>`;
  if (lead.insert?.kind) return `${head}<div class="shots-card"><p><strong>Insert · ${esc(lead.insert.kind)}</strong> · ${lead.insert.seconds.toFixed(1)} s</p>
    <p>${esc(lead.insert.text || lead.insert.block || lead.insert.asset_id || lead.insert.source_id || '')}</p>
    <a class="btn sm" href="#/p/${p.id}/edit">Edit in timeline</a></div>`;
  const beats = shotBeats(p, row);
  const beat = beats.find(b => b.lead.id === shotBeatPicked) || beats[0];
  shotBeatPicked = beat.lead.id;
  return `${head}
    <section class="shots-card" aria-labelledby="shots-describe">
      <div class="shots-step"><span class="mono">1</span><h2 id="shots-describe">Describe it</h2>
        <span class="sub">What the viewer should see and feel. The agent and the tools below work from this.</span></div>
      <label class="sr-only" for="shots-desc">Shot description</label>
      <textarea id="shots-desc" rows="2" placeholder="Describe what this shot shows"
        onchange="scriptSaveShotNote('${lead.id}',this.value)">${esc(lead.visual_note || '')}</textarea>
      ${p.visual_flags?.[lead.id] ? `<p class="script-visual-flag">${esc(p.visual_flags[lead.id].text)}</p>` : ''}
    </section>
    <section class="shots-card" aria-labelledby="shots-beats" data-script-shot="${lead.id}"
      ondragover="scriptDragOver(event)" ondragleave="scriptDragLeave(event)" ondrop="scriptDrop(event)">
      <div class="shots-step"><span class="mono">2</span><h2 id="shots-beats">Visuals against the words</h2>
        <span class="sub">A shot can hold several visuals. Pick one to design it; start a new visual on any paragraph.</span></div>
      ${shotStrip(p, row, beats, beat)}
    </section>
    <section class="shots-card" aria-labelledby="shots-design">
      <div class="shots-step"><span class="mono">3</span><h2 id="shots-design">Design visual ${beats.indexOf(beat) + 1}${beats.length > 1 ? ' of ' + beats.length : ''}</h2>
        <span class="mono sub">${fmtTime(beat.start)}–${fmtTime(beat.end)} · ¶${beat.first}${beat.paras.length > 1 ? '–¶' + (beat.first + beat.paras.length - 1) : ''}</span></div>
      ${shotDesign(p, beat)}
    </section>`;
}
async function scriptPickShot(lead) {
  if (!(await scriptFlush())) return;
  scriptShotPicked = lead;
  paintScriptShots();
  document.querySelector(`.shots-row[data-shot="${lead}"]`)?.focus();
}
function scriptShotListKey(e) {
  if (!['ArrowUp', 'ArrowDown'].includes(e.key)) return;
  e.preventDefault();
  const rows = [...document.querySelectorAll('.shots-row')];
  const next = rows[rows.indexOf(e.currentTarget) + (e.key === 'ArrowUp' ? -1 : 1)];
  if (next) scriptPickShot(next.dataset.shot);
}
function scriptShotRowOver(e) {
  if (!scriptDragging) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  e.currentTarget.classList.add('drop-into');
}
function scriptShotRowDrop(e, lead) {
  if (!scriptDragging) return;
  e.preventDefault();
  const sid = scriptDragging;
  scriptDragEnd();
  e.currentTarget.classList.remove('drop-into');
  scriptMovePara(sid, lead, '');
}

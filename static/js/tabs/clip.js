/* Clip controls edit source ranges; the recording is never a voice take. */
async function saveClip(patch) {
  try {
    state.project = await api(`/api/projects/${state.project.id}/clip`, {method:'PATCH', body:JSON.stringify(patch)});
    await render();
  } catch (error) { toast(error.message, true); }
}

async function paintClip() {
  const p = state.project, c = p.clip;
  const doc = await api(`/api/footage/shoots/${c.shoot_id}/transcripts/${c.source_id}`);
  if (state.project !== p || state.stage !== 'clip') return;
  const words = doc.words.filter(w => c.in_s <= w.start && w.end <= c.out_s);
  $('#tabbody').innerHTML = `<section class="panel" id="clip-controls"><div class="row"><h2>Clip</h2>
    <div class="spacer"></div><button class="btn ghost sm" onclick="saveProjectFile()"
      title="everything in this video as one file, to open on another computer">save project file…</button></div>
    ${p.subtitle || p.outline.thesis ? `<p class="sub">${esc(p.subtitle || p.outline.thesis)}</p>` : ''}
    <p>Trim the original range or remove a stretch. ${words.length ? 'Select word boundaries below.' : 'No transcript needed: enter source seconds.'}</p>
    <label for="clip-in">In (source seconds)</label>${clipBoundary('clip-in', c.in_s, words, 'start')}
    <label for="clip-out">Out (source seconds)</label>${clipBoundary('clip-out', c.out_s, words, 'end')}
    <button class="btn" id="clip-trim">Trim to range</button>
    ${words.length ? '<button class="btn" id="clip-cut">Remove range</button>' : ''}
    <p class="mono">Removed: ${c.cuts.map(([a,b]) => `${a}–${b} s`).join(', ') || 'none'}</p>
    <button class="btn ghost" id="clip-restore">Restore removed ranges</button>
    <p>Stored hook: ${esc(c.hook || 'none')}. Hook graphics are not available yet.</p>
    <p><a href="#/footage/${c.shoot_id}/clips/${c.source_id}">Back to source</a></p></section>
    ${p.slides.map((s,i) => `<section class="panel" data-clip-paragraph="${s.id}"><h3>Paragraph ${i+1}</h3><p>${esc(s.narration || 'No words in this range')}</p>
      <label for="clip-crop-${i}">Crop position</label><select id="clip-crop-${i}" data-crop="${s.id}">
      ${['centre','left third','right third'].map(v => `<option ${v === (c.reframes[s.id] || 'centre') ? 'selected' : ''}>${v}</option>`).join('')}</select>
      <button class="btn" onclick="previewBit('${s.id}')">Preview this bit · ¼ size</button></section>`).join('')}`;
  const range = () => ({in_s:Number($('#clip-in').value), out_s:Number($('#clip-out').value)});
  $('#clip-trim').onclick = () => saveClip(range());
  if ($('#clip-cut')) $('#clip-cut').onclick = () => { const r = range(); saveClip({cuts:[...c.cuts,[r.in_s,r.out_s]]}); };
  $('#clip-restore').onclick = () => saveClip({cuts:[]});
  document.querySelectorAll('[data-crop]').forEach(el => { el.onchange = () => saveClip({reframes:{...c.reframes,[el.dataset.crop]:el.value}}); });
}

function clipBoundary(id, value, words, edge) {
  return words.length ? `<select id="${id}">${[...new Set([value,...words.map(w => w[edge])])].sort((a,b)=>a-b).map(t => `<option value="${t}" ${t === value ? 'selected' : ''}>${t.toFixed(2)} s · ${esc(words.find(w => w[edge] === t)?.w || 'current boundary')}</option>`).join('')}</select>`
    : `<input type="number" id="${id}" step="0.01" min="0" value="${value}">`;
}

async function paintClipPublish() {
  const p = state.project;
  $('#tabbody').innerHTML = `<section class="panel" id="clip-publish"><h2>Publish clip</h2>
    <p class="mono">Source range: ${p.clip.in_s.toFixed(2)}–${p.clip.out_s.toFixed(2)} s · ${esc(p.clip.aspect)}</p>
    <p>Renders the original sound and current static crop. Hook and other graphics are not available yet.</p>
    <button type="button" class="btn primary" id="clip-render" onclick="doRender(false)">Render the clip</button>
    <p><a href="#/p/${p.id}/edit">Review the cut</a></p></section>${finishedVideo(p, {segments:[]})}`;
}

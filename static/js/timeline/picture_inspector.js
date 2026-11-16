// Picture tools share Visuals' editors; Script owns the shot grouping rules.
function tlPictureContext(sel) {
  if (!['picture','paragraph'].includes(sel?.kind)) return null;
  const p = state.project, run = (p.picture_runs || []).find(r => r.includes(sel.sid)) || [sel.sid];
  const lead = p.slides.find(s => s.id === run[0]);
  if (!lead || lead.insert?.kind) return null;
  return {lead, members:run.map(id => p.slides.find(s => s.id === id)).filter(Boolean),
    shot:scriptRuns(p).find(r => r.some(s => s.id === sel.sid)) || [lead]};
}

function tlPictureFields({lead:s, members, shot}) {
  const c = s.candidates?.find(c => c.id === s.chosen_id), kind = pictureKind(s);
  const drawn = isCut(kind) || kind === 'board' || kind === 'stage' || s.on_camera;
  const modes = [['auto','Auto · automatic grouping'], ['hold','Hold · previous picture'],
    ['cut','Cut · new picture, same Script shot'], ['new','New · new picture and Script shot']];
  return `<section class="tl-picture-tools" aria-label="Picture tools">
    <h3>Picture · ¶${state.project.slides.indexOf(s)+1}</h3><button type="button" class="btn sm" onclick="openEditPictureTools('${s.id}')">More picture tools…</button>
    <div class="tl-picture-preview">${kind === 'block' ? visualBlockStill(state.project,s)
      : c && !drawn ? `<img src="${esc(thumbUrl(c))}" alt="${esc(c.title || 'Selected picture')}"
        style="object-position:${(c.focal?.[0] ?? .5)*100}% ${(c.focal?.[1] ?? .5)*100}%">`
      : `<p>${esc(s.on_camera ? 'Camera take' : drawn ? pictureKindLabel(kind) + ' · use the player to preview' : 'Choose a picture below.')}</p>`}</div>
    <div class="tl-picture-candidates" role="group" aria-label="Picture candidates">${(s.candidates || []).map(c =>
      `<button type="button" class="btn" id="tl-picture-candidate-${esc(c.id)}" data-candidate="${esc(c.id)}" aria-label="Use ${esc(c.title || c.provider || 'candidate')}"
        aria-pressed="${s.chosen_id === c.id}" ${s.on_camera ? 'disabled' : ''}>
        <img src="${esc(thumbUrl(c))}" alt="" loading="lazy"><span>${esc(c.title || c.provider)}</span></button>`).join('') || '<p>No candidates gathered yet.</p>'}</div>
    ${c ? `<p class="tl-note">${esc([c.provider,c.license].filter(Boolean).join(' · '))}</p>` : ''}
    <label for="tl-picture-note">Shot description · shared with Script</label>
    <textarea id="tl-picture-note" rows="3" maxlength="400">${esc(shot[0].visual_note || '')}</textarea>
    <label for="tl-picture-queries">Search queries · one per line, up to four</label>
    <textarea id="tl-picture-queries" rows="2">${esc((s.queries || []).join('\n'))}</textarea>
    <div class="tl-actions"><button type="button" class="btn sm" data-picture-search ${s.on_camera ? 'disabled' : ''}>Search again</button>
      <button type="button" class="btn sm" data-picture-upload ${s.on_camera ? 'disabled' : ''}>Upload</button>
      <input type="file" data-picture-file hidden accept="image/*,video/*">
      <button type="button" class="btn sm" data-picture-map ${s.on_camera ? 'disabled' : ''}>${s.prefer_kind === 'map' ? 'Edit map' : 'Use a map'}</button>
      ${c ? '<button type="button" class="btn sm" data-picture-focus>Set focus point</button>' : ''}
      ${c?.kind === 'video' ? '<button type="button" class="btn sm" data-picture-play>Play source clip</button>' : ''}</div>
    <label class="tl-picture-lock"><input type="checkbox" data-picture-lock ${s.locked_media ? 'checked' : ''}> Keep picture on re-plan</label>
    ${members.map(m => `<label for="tl-picture-mode-${esc(m.id)}">¶${state.project.slides.indexOf(m)+1} · picture mode${m.id !== s.id ? ' (holds this picture)' : ''}</label>
      <select id="tl-picture-mode-${esc(m.id)}" data-picture-mode="${esc(m.id)}">${modes.map(([value,label]) =>
        `<option value="${value}" ${(m.picture_mode || 'auto') === value ? 'selected' : ''}>${label}</option>`).join('')}</select>`).join('')}
  </section>`;
}

// One queue and gesture for all paragraphs in a shot; one Undo restores them.
function tlPictureEdit(sel, makePatches, label = 'edit picture') {
  if (!tlCanEdit([sel], ['pictures'])) return Promise.resolve(false);
  const pid = TL.pid;
  const result = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return false;
    if (!tlCanEdit([sel], ['pictures'])) return false;
    try {
      const p = state.project, history = {quiet:true, editLabel:label, editGesture:crypto.randomUUID()};
      for (const [sid,patch] of await makePatches()) {
        if (!await saveSlide(sid, patch, history, p)) throw Error('Could not save the picture.');
      }
      if (TL.pid !== pid || state.project?.id !== pid) return false;
      state.project = await api(`/api/projects/${pid}`);
      await tlRefresh();
      // Holding a former lead removes its segment. Follow its new group.
      if (!TL.selection && sel.kind === 'picture') {
        const lead = tlPictureContext(sel)?.lead.id;
        TL.selection = tlItems('picture').find(s => s.sid === lead) || null;
        TL.selections = TL.selection ? [TL.selection] : [];
      }
      const active = document.activeElement, id = active?.id;
      const restore = active?.closest('#tl-inspector');
      const caret = active?.selectionStart, end = active?.selectionEnd;
      tlInspector();
      const next = id && document.getElementById(id);
      if (next && restore) {
        next.focus();
        if (caret != null && next.setSelectionRange) next.setSelectionRange(caret,end);
      }
      return true;
    } catch (e) { tlMsg(e.message); return false; }
  });
  tlInspectorQueue = result.catch(() => {});
  return result;
}

function tlPictureWire(sel, context, body) {
  const {lead:s} = context, q = selector => body.querySelector(selector);
  const edit = (patch, label) => tlPictureEdit(sel, () => [[s.id,patch]], label);
  const modal = open => { if (tlCanEdit([sel], ['pictures'])) return tlModal(open); };
  const kind = q('.visual-kind');
  if (kind) { kind.id = 'tl-picture-kind'; kind.onclick = () => modal(() => openPictureKind(s.id)); }
  const choose = cid => edit({chosen_id:cid, locked_media:true}, 'choose picture');
  body.querySelectorAll('[data-candidate]').forEach(b => b.onclick = () => choose(b.dataset.candidate));
  q('#tl-picture-note').onchange = e => {
    const value = e.target.value;
    tlPictureEdit(sel, () => (tlPictureContext(sel)?.shot || []).map(m => [m.id,{visual_note:value}]), 'edit shot description');
  };
  q('#tl-picture-queries').onchange = e => edit({queries:tlPictureQueries(e.target.value)}, 'edit picture queries');
  const search = async () => {
    if (s.on_camera) return;
    const queries = tlPictureQueries(q('#tl-picture-queries').value);
    if (await edit({queries}, 'edit picture queries'))
      openMediaSearch(s.id, queries[0] || null, choose, () => tlRefreshProject());
  };
  q('[data-picture-search]').onclick = search;
  if (q('#tl-picture')) q('#tl-picture').onclick = search;
  q('[data-picture-upload]').onclick = () => {
    if (tlCanEdit([sel], ['pictures'])) q('[data-picture-file]').click();
  };
  q('[data-picture-file]').onchange = e => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData(); fd.append('file',file);
    // Upload through the same queue, so it cannot race a candidate or mode edit.
    const pid = TL.pid;
    tlPictureEdit(sel, async () => {
      await api(`/api/projects/${pid}/slides/${s.id}/upload`, {method:'POST', body:fd,
        editLabel:'upload picture', editGesture:crypto.randomUUID()});
      return [];
    }, 'upload picture');
  };
  q('[data-picture-map]').onclick = () => modal(() => openMapPicker(s.id));
  if (q('[data-picture-focus]')) q('[data-picture-focus]').onclick = () => modal(() => setSlideFocal(s.id,s.chosen_id));
  if (q('[data-picture-play]')) q('[data-picture-play]').onclick = () => playClipFor(s.id,s.chosen_id);
  q('[data-picture-lock]').onchange = e => edit({locked_media:e.target.checked}, 'lock picture');
  body.querySelectorAll('[data-picture-mode]').forEach(el => el.onchange = () => {
    const {pictureMode:sid} = el.dataset, picture_mode = el.value;
    tlPictureEdit(sel, () => [[sid,{picture_mode}]], 'change picture mode');
  });
}

function tlPictureQueries(value) { return value.split('\n').map(q => q.trim()).filter(Boolean).slice(0,4); }

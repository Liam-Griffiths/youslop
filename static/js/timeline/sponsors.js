// Slot data works without a channel library. sponsor_id is reserved for T10.2.
function tlSponsorItems() {
  return (state.project.sponsors || []).map((slot) => {
    const item = TL.data.layers?.sponsors?.find((s) => s.id === slot.id);
    return item || {kind: 'sponsor', id: slot.id, sid: '', t0: 0, t1: 0};
  });
}

function tlSponsorFields(slot) {
  const suggestions = TL.data.sponsor_suggestions || [];
  const input = (key, label, value, max) => `<label for="sp-${key}">${label}</label>
    <input type="text" id="sp-${key}" data-sp="${key}" maxlength="${max}" value="${esc(value || '')}">`;
  return `<label for="sp-slot">Sponsor read</label><select id="sp-slot">
      ${(state.project.sponsors || []).map((s) => `<option value="${esc(s.id)}" ${s.id === slot.id ? 'selected' : ''}>${esc(s.vars.name || 'Unnamed sponsor')}${s.enabled ? '' : ' · off'}</option>`).join('')}</select>
    <p class="tl-note">Enter sponsor details here. Channel library linking will be added later.</p>
    ${input('name', 'Sponsor name', slot.vars.name, 64)}
    <label for="sp-variant">Variant</label><select id="sp-variant" data-sp="variant">
      ${['short', 'long'].map((v) => `<option ${slot.variant === v ? 'selected' : ''}>${v}</option>`).join('')}</select>
    <label for="sp-placement">Placement</label><select id="sp-placement" data-sp="placement">
      ${[['pre', 'After hook'], ['mid', 'Paragraph boundary'], ['end', 'Before outro']].map(([v, label]) => `<option value="${v}" ${slot.placement === v ? 'selected' : ''}>${label}</option>`).join('')}</select>
    <label for="sp-boundary">After paragraph</label><select id="sp-boundary" data-sp="after_slide_id" ${slot.placement !== 'mid' ? 'disabled' : ''}>
      <option value="">Use time anchor / choose boundary</option>
      ${state.project.slides.map((s, i) => `<option value="${esc(s.id)}" ${slot.after_slide_id === s.id ? 'selected' : ''}>${i + 1} · ${esc(s.narration.slice(0, 48))}</option>`).join('')}</select>
    <div class="tl-actions">${suggestions.map((s) => `<button class="btn sm" data-sp-suggest="${s.placement}">Suggested ${s.placement} · ¶${state.project.slides.findIndex((q) => q.id === s.after_slide_id) + 1}</button>`).join('')}</div>
    <label for="sp-script">Read copy</label><textarea id="sp-script" data-sp="script" maxlength="10000" rows="5">${esc(slot.script)}</textarea>
    ${input('learn', 'On-screen copy', slot.vars.learn, 120)}
    ${input('url', 'URL shown in the read', slot.vars.url, 120)}
    ${input('code', 'Offer code', slot.vars.code, 32)}
    ${input('made', 'Lead-in line (the card already says "Sponsored by")', slot.vars.made, 64)}
    <label><input type="checkbox" data-sp="paid" ${slot.paid ? 'checked' : ''}> Paid promotion</label>
    <p class="tl-note">Take: ${slot.take ? esc(slot.take.path || 'Recorded') : 'Not recorded · estimated duration'}. Editing copy keeps every take.</p>
    <button class="btn sm" id="sp-preview">Preview read · quarter size</button>
    <button class="btn sm ghost" id="sp-toggle">${slot.enabled ? 'Turn off' : 'Turn on'}</button>
    <div id="sp-preview-result" role="status"></div>`;
}

function tlSponsorWire(slot) {
  $('#sp-slot').onchange = (e) => tlSelect(tlSponsorItems().find((s) => s.id === e.target.value));
  document.querySelectorAll('[data-sp]').forEach((el) => {
    el.onchange = () => {
      const key = el.dataset.sp, value = el.type === 'checkbox' ? el.checked : el.value;
      const patch = ['name', 'learn', 'url', 'code', 'made'].includes(key) ? {vars: {[key]: value}} : {[key]: value};
      if (key === 'placement' && value === 'mid' && !slot.after_slide_id) {
        patch.after_slide_id = TL.data.sponsor_suggestions?.find((s) => s.placement === 'mid')?.after_slide_id || state.project.slides[0]?.id || '';
      }
      tlSponsorSave(slot.id, patch);
    };
  });
  document.querySelectorAll('[data-sp-suggest]').forEach((el) => {
    el.onclick = () => {
      const s = TL.data.sponsor_suggestions.find((s) => s.placement === el.dataset.spSuggest);
      tlSponsorSave(slot.id, {placement: s.placement, after_slide_id: s.after_slide_id});
    };
  });
  $('#sp-toggle').onclick = () => tlSponsorSave(slot.id, {enabled: !slot.enabled});
  $('#sp-preview').onclick = () => tlSponsorPreview(slot.id);
}

function tlSponsorSave(id, patch) {
  const pid = TL.pid;
  tlInspectorQueue = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    try {
      tlPause();
      const project = await api(`/api/projects/${pid}/sponsors${id ? '/' + encodeURIComponent(id) : ''}`,
        {method: id ? 'PATCH' : 'POST', body: JSON.stringify(patch)});
      if (TL.pid !== pid || state.project?.id !== pid) return;
      state.project = project;
      id = id || state.project.sponsors.at(-1).id;
      TL.mixFailed = false;
      // Saving never starts a picture render. Preview is an explicit action.
      await tlRefresh();
      tlSelect(tlSponsorItems().find((s) => s.id === id));
    } catch (e) { tlMsg(e.message); }
  });
  return tlInspectorQueue;
}

function tlSponsorAdd() {
  const boundary = TL.data.sponsor_suggestions?.find((s) => s.placement === 'mid');
  if (!state.project.slides.length) { tlMsg('Add a paragraph before placing a sponsor.'); return; }
  tlSponsorSave('', {placement: 'mid', after_slide_id: boundary?.after_slide_id || state.project.slides[0].id,
    vars: {name: '', learn: '', url: '', code: '', made: 'This video is supported by'}, script: ''});
}

async function tlSponsorPreview(id) {
  const pid = TL.pid;
  await tlInspectorQueue;
  const box = $('#sp-preview-result');
  if (!box || TL.pid !== pid) return;
  tlPause();
  box.textContent = 'Drawing one sponsor read…';
  try {
    const result = await api(`/api/projects/${pid}/sponsors/${encodeURIComponent(id)}/preview`, {method: 'POST'});
    const job = await tlWaitJob(result.job);
    if (!box.isConnected || TL.pid !== pid) return;
    if (job.state === 'error') throw new Error(job.error);
    const video = document.createElement('video');
    video.controls = true; video.playsInline = true; video.style.width = '100%';
    video.src = `/api/projects/${pid}/file/${job.result.path}?v=${job.result.rendered_at}`;
    box.replaceChildren(video);
  } catch (e) { if (box.isConnected) box.textContent = e.message; }
}

// Always snap to a paragraph end, even when another sponsor shifts that end.
// Persist the paragraph id, never a time from the sponsored cut.
function tlWireSponsorDrag() {
  const track = $('#tl-track');
  track.querySelectorAll('[data-layer="sponsors"]').forEach((el) => {
    el.classList.add('editable');
    let moved = false;
    const click = el.onclick;
    el.onclick = (e) => { if (moved) { e.stopPropagation(); moved = false; } else click(e); };
    el.onpointerdown = (e) => {
      e.stopPropagation();
      if (e.button !== 0 || TL.drag) return;
      const sel = TL.data.layers.sponsors[+el.dataset.item];
      const boundaries = tlParas().map((q) => ({id: q.id, t: q.start + q.duration}));
      if (!boundaries.length) return;
      tlPause(); tlSelect(sel); el.setPointerCapture(e.pointerId);
      const x0 = e.clientX, left = el.style.left;
      let boundary;
      moved = false; TL.drag = {sel};
      el.onpointermove = (event) => {
        if (Math.abs(event.clientX - x0) < 4 && !moved) return;
        moved = true;
        const t = sel.t0 + (event.clientX - x0) / TL.zoom;
        boundary = boundaries.reduce((a, b) => Math.abs(a.t - t) <= Math.abs(b.t - t) ? a : b);
        el.style.left = `${boundary.t * TL.zoom}px`;
        el.title = `After paragraph ${state.project.slides.findIndex((s) => s.id === boundary.id) + 1}`;
      };
      const finish = (cancel) => {
        el.onpointermove = null; el.onpointerup = null; el.onpointercancel = null;
        TL.drag = null; el.style.left = left;
        if (moved && !cancel) tlSponsorSave(sel.id, {placement: 'mid', after_slide_id: boundary.id});
      };
      el.onpointerup = () => finish(false);
      el.onpointercancel = () => finish(true);
    };
  });
}


async function stage3d() {
  if (!window.Stage3D) await import('/static/stage/viewer.js');
  return window.Stage3D;
}

// Width × height × length in metres, from what the server keeps: the file's
// own measurement, the confirmed scale, and the heading (a quarter turn swaps
// width and length).
function modelSize(m) {
  if (!m.measured) return null;
  const [x, y, z] = m.measured, k = m.scale || 1;
  const side = Math.round((m.heading || 0) / 90) % 2 !== 0;
  return { width: (side ? z : x) * k, height: y * k, length: (side ? x : z) * k };
}
const fmtMetres = (v) => (v >= 10 ? v.toFixed(1) : v >= 1 ? v.toFixed(2) : v.toFixed(3));
const sizeText = (sz) => sz ? `${fmtMetres(sz.width)} × ${fmtMetres(sz.height)} × ${fmtMetres(sz.length)} m` : 'not measured yet';

function licencePill(m) {
  const src = m.source || {};
  if (src.kind === 'CC0') return '<span class="pill">CC0 · no credit needed</span>';
  if (src.kind === 'CC-BY') return '<span class="pill on">CC-BY · credit in description</span>';
  if (src.kind === 'CC-BY-NC') return '<span class="pill warn" title="non-commercial: not for a monetised channel">CC-BY-NC · not for monetised videos</span>';
  return `<span class="pill warn" title="not a Creative Commons licence: read its terms before publishing">${esc(src.licence || 'licence unknown')} · check the terms</span>`;
}

function modelCard(m, actions) {
  const sz = modelSize(m);
  return `<div class="lib-card">
    <div class="lib-thumb" style="cursor:pointer" onclick="openModelIntake('${m.id}')" title="open">
      <img src="/api/models/${m.id}/thumb.jpg?v=${Math.round((m.thumb_at || 0))}" loading="lazy"
           onerror="this.style.opacity=0">
      <span class="kindtag">${m.confirmed ? '3D · confirmed' : '3D · needs confirming'}</span>
    </div>
    <div class="lib-body">
      <div class="lib-title" title="${esc(m.title)}">${esc(m.title)}</div>
      <div class="lib-meta">${esc(sizeText(sz))}${m.source && m.source.author ? ' · ' + esc(m.source.author) : ''}</div>
      <div class="lib-tags">${licencePill(m)}</div>
      <div class="row">${actions}</div>
    </div>
  </div>`;
}

// ------------------------------------------------------------ the library
async function paintModelLibrary() {
  const box = $('#models3d');
  if (!box) return;
  let models = [];
  try { models = await api('/api/models'); } catch (e) { toast(e.message, true); }
  state.models = models;
  box.innerHTML = `
    <h3>3D models</h3>
    <p class="mono" style="color:var(--ink-faint);margin:-4px 0 14px">
      For 3D explainers. Each model is understood once here — which way is the
      front, how big it really is — and every video that uses it inherits that.
      GLB files only.</p>
    <div class="row" style="margin-bottom:14px">
      <label class="btn sm primary" style="cursor:pointer">add a .glb model
        <input type="file" accept=".glb,model/gltf-binary" hidden
          onchange="uploadModel(this.files[0], false);this.value=''"></label>
    </div>
    <div class="lib-grid">
      ${models.map((m) => modelCard(m, `
        <button class="btn xs ghost" onclick="openModelIntake('${m.id}')">${m.confirmed ? 'open' : 'confirm…'}</button>
        <button class="btn xs ghost danger" onclick="deleteModel('${m.id}')">delete</button>`)).join('')
        || '<div class="empty-note">No 3D models yet.</div>'}
    </div>`;
}

async function uploadModel(file, toCast) {
  if (!file) return;
  if (!/\.glb$/i.test(file.name)) return toast('Only .glb files can be added.', true);
  toast(`Adding ${file.name}…`);
  const fd = new FormData();
  fd.append('file', file);
  try {
    const m = await api('/api/models', { method: 'POST', body: fd });
    if (toCast && state.project) {
      state.project = await api(`/api/projects/${state.project.id}/cast`,
        { method: 'POST', body: JSON.stringify({ model: m.id }) });
    }
    refreshModelViews();
    openModelIntake(m.id);        // a new model is understood straight away
  } catch (e) { toast(e.message, true); }
}

async function deleteModel(mid) {
  if (!confirm('Delete this model from the library?')) return;
  try {
    await api(`/api/models/${mid}`, { method: 'DELETE' });
    refreshModelViews();
  } catch (e) { toast(e.message, true); }
}

async function refreshModelViews() {
  if ($('#models3d')) paintModelLibrary();
  if (state.project && state.tab === 'cast') {
    // a model just confirmed changes the cast's "ready" count: fetch it fresh
    try { state.project = await api(`/api/projects/${state.project.id}`); } catch { /* keep what we have */ }
    render();
  }
}

// ---------------------------------------------------------------- the cast
// Story, then cast, then words (docs/3d-explainer.md, "Creating a video").
// The brief proposes the subjects the story needs; here the creator gives
// each a model — from the library, or uploaded — or says "photos instead",
// in their own time; then writes the script, which is told what the models
// can show.
async function paintCast() {
  const p = state.project, body = $('#tabbody');
  let models = [];
  try { models = await api('/api/models'); } catch (e) { toast(e.message, true); }
  state.models = models;
  const byId = Object.fromEntries(models.map((m) => [m.id, m]));
  const subs = p.cast || [], sum = p.cast_summary || { subjects: 0, ready: 0, photos: 0, needing: [] };
  const outline = p.outline || (p.draft && p.draft.outline) || {};
  const chapters = outline.sections || [];
  const planning = (p.jobs || []).some((j) => j.kind === 'brief' || j.kind === 'cast') && !subs.length;
  const used = new Set(subs.map((x) => x.model).filter(Boolean));
  const roleSel = (x) => `<select onchange="castEdit('${x.id}', {role: this.value})" style="width:auto">
      ${['hero', 'comparison', 'supporting', 'cameo'].map((r) => `<option ${r === x.role ? 'selected' : ''}>${r}</option>`).join('')}</select>`;
  const slot = (x) => {
    if (x.mode === 'photos') return `<span class="pill">photos and cards instead</span>
      <button class="btn xs ghost" onclick="castEdit('${x.id}', {mode: 'model'})">use a model</button>`;
    const m = x.model && byId[x.model];
    if (m) return `<img src="/api/models/${m.id}/thumb.jpg?v=${Math.round(m.thumb_at || 0)}" style="width:96px;height:54px;object-fit:cover;border-radius:5px" onerror="this.style.opacity=0">
      <span>${esc(m.identity && m.identity.name || m.title)}</span>
      ${m.confirmed ? '<span class="pill on">ready</span>' : '<span class="pill warn">needs confirming</span>'}
      <button class="btn xs ${m.confirmed ? 'ghost' : 'primary'}" onclick="openModelIntake('${m.id}')">${m.confirmed ? 'open' : 'confirm…'}</button>
      <button class="btn xs ghost" onclick="castEdit('${x.id}', {model: ''})">unlink</button>`;
    const spare = models.filter((mm) => !used.has(mm.id));
    return `<span class="pill warn">needs a model</span>
      ${spare.length ? `<select onchange="if(this.value) castEdit('${x.id}', {model: this.value})" style="width:auto">
        <option value="">from the library…</option>${spare.map((mm) => `<option value="${mm.id}">${esc(mm.identity && mm.identity.name || mm.title)}</option>`).join('')}</select>` : ''}
      <label class="btn xs" style="cursor:pointer">upload .glb
        <input type="file" accept=".glb,model/gltf-binary" hidden onchange="uploadForSubject('${x.id}', this.files[0]);this.value=''"></label>
      <button class="btn xs ghost" onclick="castEdit('${x.id}', {mode: 'photos'})">photos instead</button>`;
  };
  const gaps = sum.needing.length, unconfirmed = subs.filter((x) => x.mode === 'model' && x.model && byId[x.model] && !byId[x.model].confirmed).length;
  body.innerHTML = `
    <div class="card" style="margin-bottom:18px">
      <h3>${esc(outline.title || p.title || p.idea.slice(0, 80))}</h3>
      ${outline.thesis ? `<p class="mi-p" style="font-size:13.5px">${esc(outline.thesis)}</p>` : ''}
      ${chapters.length ? `<ol class="cast-chapters" start="0">${chapters.map((c) => `<li>${esc(c.heading || '')}</li>`).join('')}</ol>`
        : planning ? '<p class="mi-p">Researching and outlining the story…</p>' : ''}
    </div>
    <div class="card" style="margin-bottom:18px">
      <div class="row" style="margin-bottom:6px">
        <h3 style="margin:0">Cast</h3><div class="spacer"></div>
        ${subs.length ? `<span class="mono" style="color:var(--ink-faint)">${sum.ready} of ${sum.subjects - sum.photos} ready${sum.photos ? ` · ${sum.photos} photos only` : ''}</span>` : ''}
      </div>
      <p class="mono" style="color:var(--ink-faint);margin:0 0 12px">
        The subjects this story needs as 3D models. Give each one a model, in
        your own time, or say photos instead. The script is written once
        they are gathered, and only describes what the models can show.</p>
      ${planning ? '<div class="empty-note">Planning the cast…</div>' : subs.map((x) => `
        <div class="cast-row">
          <div class="cast-head">
            <input type="text" value="${esc(x.subject)}" onchange="castEdit('${x.id}', {subject: this.value})">
            ${roleSel(x)}
            ${(x.chapters || []).map((c) => `<span class="pill" title="${esc((chapters[c] || {}).heading || '')}">ch ${c}</span>`).join('')}
            <div class="spacer"></div>
            <button class="btn xs ghost danger" onclick="castRemove('${x.id}')">×</button>
          </div>
          ${x.why ? `<div class="mi-p">${esc(x.why)}</div>` : ''}
          <div class="row cast-slot">${slot(x)}</div>
        </div>`).join('') || '<div class="empty-note">No subjects yet.</div>'}
      <div class="row" style="margin-top:12px">
        <input type="text" id="newsubject" placeholder="add a subject, e.g. Concorde" style="flex:1;min-width:200px"
          onkeydown="if(event.key==='Enter') castAdd()">
        <button class="btn sm ghost" onclick="castAdd()">add</button>
        <button class="btn sm ghost" onclick="castPropose()" title="ask again; subjects with a model are kept">propose again</button>
      </div>
    </div>
    <div class="card">
      ${p.slides.length
        ? castScriptRow(p)
        : `<div class="row"><button class="btn primary" onclick="castWrite()" ${planning || !subs.length ? 'disabled' : ''}>Write the script</button>
            <span class="mono" style="color:var(--ink-faint)">${gaps || unconfirmed
              ? `${gaps ? `${gaps} subject${gaps === 1 ? '' : 's'} without a model` : ''}${gaps && unconfirmed ? ' · ' : ''}${unconfirmed ? `${unconfirmed} to confirm` : ''} — you can still write it`
              : 'every subject is ready'}</span></div>`}
    </div>`;
}

// Once the script exists, the Cast tab says whether its visual lines still
// fit the cast, and offers to rewrite the ones that don't.
function castScriptRow(p) {
  const fl = Object.values(p.visual_flags || {}), w = fl.filter((f) => f.level === 'warn').length, h = fl.length - w;
  const what = [w ? `${w} visual line${w === 1 ? '' : 's'} no longer fit` : '', h ? `${h} could be 3D now` : ''].filter(Boolean).join(' · ');
  return `<div class="row"><span>The script is written (${p.slides.length} paragraphs).</span>
      ${what ? `<span class="pill ${w ? 'warn' : ''}"><span class="dot"></span>${what}</span>` : ''}
      <div class="spacer"></div>
      ${fl.length ? '<button class="btn sm primary" onclick="reviseVisuals()">rewrite the visuals</button>' : ''}
      <button class="btn sm ghost" onclick="go('#/p/${p.id}/script')">go to the script</button></div>`;
}

async function castEdit(sid, patch) {
  try {
    state.project = await api(`/api/projects/${state.project.id}/cast/${sid}`, { method: 'PATCH', body: JSON.stringify(patch) });
    render();
  } catch (e) { toast(e.message, true); }
}
async function castRemove(sid) {
  try { state.project = await api(`/api/projects/${state.project.id}/cast/${sid}`, { method: 'DELETE' }); render(); }
  catch (e) { toast(e.message, true); }
}
async function castAdd() {
  const name = ($('#newsubject').value || '').trim();
  if (!name) return;
  try {
    state.project = await api(`/api/projects/${state.project.id}/cast`, { method: 'POST', body: JSON.stringify({ subject: name }) });
    render();
  } catch (e) { toast(e.message, true); }
}
async function castPropose() {
  try { const r = await api(`/api/projects/${state.project.id}/cast/propose`, { method: 'POST' }); watchJob(r.job, 'cast'); }
  catch (e) { toast(e.message, true); }
}
async function uploadForSubject(sid, file) {
  if (!file) return;
  if (!/\.glb$/i.test(file.name)) return toast('Only .glb files can be added.', true);
  toast(`Adding ${file.name}…`);
  const fd = new FormData(); fd.append('file', file);
  try {
    const m = await api('/api/models', { method: 'POST', body: fd });
    state.project = await api(`/api/projects/${state.project.id}/cast/${sid}`, { method: 'PATCH', body: JSON.stringify({ model: m.id }) });
    render();
    openModelIntake(m.id);          // understood straight away
  } catch (e) { toast(e.message, true); }
}
// Writing with gaps is allowed: subjects without a model are written as
// photo-and-card beats. It says so first.
async function castWrite() {
  const sum = state.project.cast_summary || { needing: [] };
  if (sum.needing.length && !confirm(`${sum.needing.join(', ')} ${sum.needing.length === 1 ? 'has' : 'have'} no model yet, `
      + 'so the script will show them with photos and cards. Write it anyway?')) return;
  try {
    const r = await api(`/api/projects/${state.project.id}/script`, { method: 'POST', body: '{}' });
    go(`#/p/${state.project.id}/script`);
    watchJob(r.job, 'script');
  } catch (e) { toast(e.message, true); }
}

function intakeFacts(m, a, kind) {
  if (!a) return '<p class="mi-p">Measuring\u2026</p>';
  const k = m.scale || 1, bits = [];
  bits.push(a.scan ? (a.bare ? 'A scan with no textures' : 'A photogrammetry scan') : 'A built model');
  bits.push(a.light === 'baked' ? 'light baked in' : 'lit by the stage');
  bits.push(`${(a.triangles || 0).toLocaleString()} triangles`);
  const main = (a.materials || []).find((x) => x.tex && !x.tiled);
  if (main && main.texels_per_unit) {
    const cm = 100 / (main.texels_per_unit / k);
    bits.push(`main texture ${cm >= 100 ? (cm / 100).toFixed(1) + ' m' : cm >= 10 ? Math.round(cm) + ' cm' : cm.toFixed(1) + ' cm'} per texel at this size`);
  }
  let room = '';
  if ((kind === 'interior' || kind === 'set') && a.floor_y != null && a.ceiling_y != null) {
    const h = (a.ceiling_y - a.floor_y) * k;
    const odd = h < 2.2 || h > 6;
    room = `<p class="mi-p">Floor to ceiling: <b>${h.toFixed(2)} m</b> at this size.
      ${odd ? `<span style="color:#d9a05e">Rooms are usually 2.4\u20135 m, so the size is probably off.</span>
        <button class="btn xs ghost" onclick="miRoomHeight(3.5)">make it 3.5 m</button>` : ''}</p>`;
  }
  const limits = (window.Stage3D ? window.Stage3D.limitsFor({ ...a, kind }) : a.limits || [])
    .map((c) => LIMIT_TEXT[c] ? `<li>${esc(LIMIT_TEXT[c])}${c === 'one_direction' && a.centre_probe && a.centre_probe.open_sides.length
      ? ` <span class="mono" style="color:var(--ink-faint)">(open: ${esc(a.centre_probe.open_sides.join(', '))})</span>` : ''}</li>` : '').join('');
  return `<p class="mi-p">${esc(bits.join(' \u00b7 '))}.</p>${room}
    ${limits ? `<ul class="mi-limits">${limits}</ul>` : '<p class="mi-p">No special limits: shots can circle it freely.</p>'}`;
}

// ------------------------------------------------------------ intake screen
// Where a model is understood: turned until its front faces the arrow, sized
// against the 1.8 m figure, tinted if it is a bare scan. Changes show live in
// the viewer and are saved on "confirm".
async function openModelIntake(mid) {
  let m;
  try { m = await api(`/api/models/${mid}`); } catch (e) { return toast(e.message, true); }
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>${esc(m.title)}</strong>
        ${m.confirmed ? '<span class="pill on">confirmed</span>' : '<span class="pill warn">needs confirming</span>'}
        <div class="spacer"></div>
        <button class="btn sm ghost" id="mi-close">close</button>
      </div>
      <div class="model-intake">
        <div class="model-view" id="mi-view"><div class="empty-note" style="padding:40px">loading the model…</div></div>
        <div class="model-side" id="mi-side"></div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  let ctl = null;
  const close = () => { if (ctl) ctl.dispose(); wrap.remove(); refreshModelViews(); };
  $('#mi-close', wrap).onclick = close;
  wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) close(); });

  const draft = { title: m.title, heading: m.heading || 0, scale: m.scale || 1,
                  size_axis: m.size_axis || 'width', tint: m.tint || '', kind: m.kind || '',
                  regions: JSON.parse(JSON.stringify(m.regions || [])) };
  let regionSel = -1;
  const kindNow = () => draft.kind || (m.analysis && m.analysis.kind_auto) || 'object';
  const roomAnalysis = () => (m.analysis && (kindNow() === 'interior' || kindNow() === 'set') ? m.analysis : null);
  let asking = false;

  const regionsList = () => (draft.regions || []).map((r, i) => `
    <div class="row" style="gap:6px;margin-bottom:4px">
      <input type="text" value="${esc(r.label)}" style="flex:1;min-width:0;${i === regionSel ? 'border-color:#ffb347' : ''}"
        oninput="miRegionLabel(${i}, this.value)" onfocus="miRegionSelect(${i})">
      <button class="btn xs ghost danger" onclick="miRegionDelete(${i})">\u00d7</button>
    </div>`).join('') || '<p class="mi-p">No regions yet.</p>';
  const syncRegions = () => { if (ctl) ctl.setRegions(draft.regions, regionSel); };
  window.miRegionAdd = () => {
    if (!ctl) return;
    draft.regions = [...(draft.regions || []), ctl.newRegion(`region ${(draft.regions || []).length + 1}`)];
    regionSel = draft.regions.length - 1; syncRegions(); paintSide();
  };
  window.miRegionSelect = (i) => { if (regionSel === i) return; regionSel = i; syncRegions(); paintSide(); const el = $('#mi-regions', wrap).querySelectorAll('input')[i]; if (el) el.focus(); };
  window.miRegionDelete = (i) => { draft.regions.splice(i, 1); regionSel = -1; syncRegions(); paintSide(); };
  window.miRegionLabel = (i, v) => { if (draft.regions[i]) draft.regions[i].label = v.slice(0, 60); };
  window.miRegionMode = (mode) => { if (ctl) ctl.regionMode(mode); };

  // What one size suggestion implies the scale should be (file units -> metres).
  const impliedScale = (sz) => {
    const a = m.analysis || {}, id = m.identity || {};
    if (sz.measure === 'room_height') return a.floor_y != null && a.ceiling_y != null ? sz.metres / (a.ceiling_y - a.floor_y) : null;
    if (sz.measure === 'subject_x' || sz.measure === 'subject_z') {
      const b = id.subject && id.subject.box; if (!b) return null;
      const units = sz.measure === 'subject_x' ? b[2] - b[0] : b[3] - b[1];
      return units > 0 ? sz.metres / units : null;
    }
    if (sz.measure === 'subject_height') {
      const b = id.subject && id.subject.box; if (!b || !ctl) return null;
      const units = ctl.regionHeight(b);
      return units > 0 ? sz.metres / units : null;
    }
    if (!ctl) return null;
    const now = ctl.size()[sz.measure];
    return now > 0 ? draft.scale * sz.metres / now : null;
  };

  // Claude's suggestions, each applied by its own click. Nothing is saved
  // until "confirm model".
  const identityBlock = () => {
    const id = m.identity;
    if (asking) return '<p class="mi-p">Asking Claude what it is\u2026 (up to a minute)</p>';
    if (!id) return `<button class="btn sm" onclick="miIdentify()" ${m.analysis ? '' : 'disabled'}>ask Claude what it is</button>`;
    const rows = [];
    rows.push(`<p class="mi-p"><b>${esc(id.name || 'not sure')}</b> <span class="mono">(${esc(id.confidence)} confidence)</span>
      ${id.name && id.name !== draft.title ? `<button class="btn xs ghost" onclick="miUse('title')">use as title</button>` : ''}<br>${esc(id.what || '')}</p>`);
    if (id.front_view) {
      const v = ((window.Stage3D && window.Stage3D.OBJECT_VIEWS) || []).find((x) => x.id === id.front_view);
      const want = v ? ((360 - v.az) % 360) : null;
      if (want != null) rows.push(`<p class="mi-p">Its front faces view ${esc(id.front_view)}.
        ${want !== draft.heading ? `<button class="btn xs ghost" onclick="miUse('front')">turn it to face the arrow</button>` : '\u2713 facing the arrow'}</p>`);
    }
    const scales = [];
    for (const [i, sz] of (id.sizes || []).entries()) {
      const k = impliedScale(sz); if (k) scales.push(k);
      rows.push(`<p class="mi-p">${esc(sz.feature)}: <b>${sz.metres} m</b> <span class="mono">(${esc(sz.how_sure)})</span>
        ${k ? `<button class="btn xs ghost" onclick="miUse('size', ${i})">set size from this</button>` : ''}</p>`);
    }
    if (scales.length === 2) {
      const off = Math.abs(scales[0] - scales[1]) / Math.min(...scales);
      if (off > 0.05) rows.push(`<p class="mi-p" style="color:#d9a05e">These two sizes disagree by ${Math.round(off * 100)}%:
        the model may be stylised, or one figure is off. Pick the one that matters most for your shots.</p>`);
    }
    if (id.subject) rows.push(`<p class="mi-p">Subject: <b>${esc(id.subject.name)}</b>${id.subject.refined ? ' <span class="mono">(placed from a closer look)</span>' : ''}${id.north && id.north !== 'unknown' ? ` \u00b7 north is ${esc(id.north)}` : ''}
      ${(draft.regions || m.regions || []).some((r) => r.label === id.subject.name) ? ' \u2713 marked'
        : `<button class="btn xs ghost" onclick="miUse('subject')">mark it</button>`}</p>`);
    const parts = Object.keys(id.parts || {});
    if (parts.length) rows.push(`<p class="mi-p">${parts.length} part names${id.parts_from_pictures ? ' (from pictures)' : ''}: ${esc(Object.values(id.parts).join(', '))}
      ${draft.parts_labels ? ' \u2713' : `<button class="btn xs ghost" onclick="miUse('parts')">use them</button>`}</p>`);
    rows.push(`<button class="btn xs ghost" onclick="miIdentify()">ask again</button>`);
    return rows.join('');
  };

  window.miIdentify = async () => {
    if (!ctl || asking) return;
    asking = true; paintSide();
    try {
      const { views, meta } = await ctl.idViews(kindNow(), m.analysis);
      const fd = new FormData();
      views.forEach((v, i) => fd.append('views', v.blob, `view${i}.jpg`));
      fd.append('captions', JSON.stringify(views.map((v) => v.caption)));
      fd.append('meta', JSON.stringify(meta));
      fd.append('kind', kindNow());
      m = await api(`/api/models/${mid}/identify`, { method: 'POST', body: fd });
      // A site's subject: a second, closer look draws its box tight (coarse
      // to fine). The first answer, from the whole tile, is only roughly right.
      const sub = m.identity && m.identity.subject;
      if (sub && /site$/.test(kindNow())) {
        paintSide();
        const z = await ctl.zoomView(sub.box), f2 = new FormData();
        f2.append('views', z.blob, 'zoom.jpg');
        f2.append('captions', JSON.stringify([z.caption]));
        f2.append('meta', JSON.stringify({ grid: z.grid }));
        f2.append('kind', kindNow()); f2.append('mode', 'refine');
        m = await api(`/api/models/${mid}/identify`, { method: 'POST', body: f2 });
      }
      // An object's named parts: highlighted pictures plus where each sits,
      // measured against the front Claude just found (or the one confirmed).
      if (kindNow() === 'object' && (m.parts || []).length) {
        paintSide();
        const fv = window.Stage3D.OBJECT_VIEWS.find((x) => x.id === (m.identity || {}).front_view);
        const heading = fv ? (360 - fv.az) % 360 : draft.heading;
        const { sheets, table } = await ctl.partSheets(m.parts.slice(0, 24).map((p) => p.node), heading);
        if (sheets.length) {
          const f3 = new FormData();
          sheets.forEach((v, i) => f3.append('views', v.blob, `parts${i}.jpg`));
          f3.append('captions', JSON.stringify(sheets.map((v) => v.caption)));
          f3.append('meta', JSON.stringify({ table }));
          f3.append('kind', 'object'); f3.append('mode', 'parts');
          m = await api(`/api/models/${mid}/identify`, { method: 'POST', body: f3 });
        }
      }
    } catch (e) { toast(e.message, true); }
    asking = false; paintSide();
    if (ctl) { if (roomAnalysis()) ctl.inside(m.analysis); }
  };

  window.miUse = (what, i) => {
    const id = m.identity || {};
    if (what === 'title') draft.title = id.name;
    if (what === 'front') {
      const v = window.Stage3D.OBJECT_VIEWS.find((x) => x.id === id.front_view);
      if (v) { draft.heading = (360 - v.az) % 360; ctl && ctl.update(live()); }
    }
    if (what === 'size') {
      const sz = id.sizes[i], k = impliedScale(sz);
      if (k) {
        draft.scale = k;
        if (['width', 'length', 'height'].includes(sz.measure)) draft.size_axis = sz.measure;
        ctl && ctl.update(live());
        if (roomAnalysis()) ctl.inside(m.analysis);
      }
    }
    if (what === 'subject' && id.subject) {
      const b = id.subject.box, mm = (id.meta && id.meta.min) || [0, 0, 0], su = (id.meta && id.meta.size_units) || [0, 1, 0];
      draft.regions = [...(draft.regions || m.regions || []).filter((r) => r.label !== id.subject.name),
        { label: id.subject.name, box: [[b[0], mm[1], b[1]], [b[2], mm[1] + su[1], b[3]]] }];
      if (id.north && id.north !== 'unknown') draft.north = id.north;
      regionSel = draft.regions.length - 1; syncRegions();
    }
    if (what === 'parts') draft.parts_labels = { ...(id.parts || {}) };
    paintSide();
  };
  const live = () => ({ ...m, ...draft });

  const paintSide = () => {
    const src = m.source || {}, st = m.stats || {};
    const sz = ctl ? ctl.size() : modelSize(live());
    const axis = draft.size_axis;
    $('#mi-side', wrap).innerHTML = `
      <label class="mono mi-k">title</label>
      <input type="text" id="mi-title" value="${esc(draft.title)}">

      <div class="mi-sec">
        <div class="mi-h">What it is</div>
        <select id="mi-kind" style="width:100%;margin-bottom:8px">
          ${Object.entries((window.Stage3D && window.Stage3D.KINDS) || { object: 'Object' }).map(([k, label]) =>
            `<option value="${k}" ${k === kindNow() ? 'selected' : ''}>${esc(label)}${m.analysis && m.analysis.kind_auto === k ? '  (detected)' : ''}</option>`).join('')}
        </select>
        ${intakeFacts(live(), m.analysis, kindNow())}
        <div id="mi-identity">${identityBlock()}</div>
      </div>

      <div class="mi-sec">
        <div class="mi-h">1 · Front</div>
        <p class="mi-p">The arrow on the floor marks the front. Turn the model
          until its nose faces the arrow.</p>
        <div class="row">
          <button class="btn sm ghost" onclick="miTurn(90)">turn left</button>
          <button class="btn sm ghost" onclick="miTurn(-90)">turn right</button>
          <button class="btn sm ghost" onclick="miTurn(180)">about face</button>
          <span class="mono" style="color:var(--ink-faint)">${draft.heading}°</span>
        </div>
      </div>

      <div class="mi-sec">
        <div class="mi-h">2 · True size</div>
        <p class="mi-p">Files arrive at any scale. The grey figure is 1.8 m tall.
          Now: <b>${esc(sizeText(sz))}</b> <span class="mono" style="color:var(--ink-faint)">(width × height × length)</span></p>
        <div class="row">
          <select id="mi-axis" style="width:auto">
            ${['width', 'length', 'height'].map((a) => `<option value="${a}" ${a === axis ? 'selected' : ''}>real ${a}</option>`).join('')}
          </select>
          <input type="number" id="mi-metres" min="0.001" step="any" style="width:110px"
            value="${sz ? +sz[axis].toFixed(3) : ''}">
          <span class="mono">m</span>
          <button class="btn sm ghost" onclick="miApplySize()">apply</button>
        </div>
        <p class="mi-p" style="margin-top:6px">e.g. a wingspan is the width; a car's length is the length.</p>
      </div>

      <div class="mi-sec">
        <div class="mi-h">3 · Look</div>
        <p class="mi-p">${st.textures ? `${st.textures} texture${st.textures === 1 ? '' : 's'} — the model brings its own colours.`
          : 'No textures: a bare scan. Give it one flat colour so it does not read as grey clay.'}</p>
        <div class="row">
          <label class="row" style="gap:6px"><input type="checkbox" id="mi-tinton" ${draft.tint ? 'checked' : ''}
            onchange="miTint()"> flat colour</label>
          <input type="color" id="mi-tint" value="${esc(draft.tint || '#e8dcc2')}" oninput="miTint()"
            ${draft.tint ? '' : 'disabled'}>
        </div>
      </div>

      <div class="mi-sec">
        <div class="mi-h">4 \u00b7 Regions</div>
        <p class="mi-p">Boxes around the things a shot can aim at \u2014 an engine, a doorway, a landmark.
          ${m.parts.length ? '' : 'This model has no named parts, so regions are how its parts exist. '}Select one to move or size it.</p>
        <div id="mi-regions">${regionsList()}</div>
        <div class="row" style="margin-top:6px">
          <button class="btn sm ghost" onclick="miRegionAdd()">add region</button>
          ${regionSel >= 0 ? `<button class="btn sm ghost" onclick="miRegionMode('move')">move</button>
            <button class="btn sm ghost" onclick="miRegionMode('size')">size</button>` : ''}
        </div>
      </div>

      <div class="mi-sec">
        <div class="mi-h">Source</div>
        <p class="mi-p">${esc(src.author || 'author unknown')}${src.url ? ` · <span class="mono">${esc(src.url.replace(/^https?:\/\//, '').slice(0, 48))}</span>` : ''}</p>
        <div class="row" style="margin-bottom:6px">${licencePill(m)}</div>
        <p class="mi-p">${(st.triangles || 0).toLocaleString()} triangles ·
          ${m.parts.length ? `${m.parts.length} named parts: ${esc(m.parts.map((x) => x.label).join(', '))}`
            : 'no named parts (an unsplit scan) — parts will be marked as regions'}</p>
      </div>

      <div class="row" style="margin-top:14px">
        <button class="btn primary" id="mi-confirm">${m.read_only ? 'Copy to my library' : m.confirmed ? 'save' : 'confirm model'}</button>
        <span class="mono" style="color:var(--ink-faint)">${m.read_only ? 'Pack model · read-only' : 'saves front, size and look'}</span>
      </div>`;
    $('#mi-title', wrap).oninput = (e) => { draft.title = e.target.value; };
    $('#mi-axis', wrap).onchange = (e) => { draft.size_axis = e.target.value; paintSide(); };
    $('#mi-kind', wrap).onchange = (e) => {
      draft.kind = e.target.value === (m.analysis && m.analysis.kind_auto) ? '' : e.target.value;
      if (ctl && m.analysis && (kindNow() === 'interior' || kindNow() === 'set')) ctl.inside(m.analysis);
      paintSide();
    };
    $('#mi-confirm', wrap).onclick = save;
    if (m.read_only) wrap.querySelectorAll('#mi-side input, #mi-side select, #mi-side button:not(#mi-confirm)').forEach((el) => { el.disabled = true; });
  };

  window.miTurn = (deg) => { draft.heading = ((draft.heading + deg) % 360 + 360) % 360; ctl && ctl.update(live()); paintSide(); };
  window.miTint = () => {
    const on = $('#mi-tinton', wrap).checked;
    $('#mi-tint', wrap).disabled = !on;
    draft.tint = on ? $('#mi-tint', wrap).value : '';
    ctl && ctl.update(live());
  };
  // Set the scale from a plausible room height, when the file's units are off.
  window.miRoomHeight = (metres) => {
    const a = m.analysis;
    if (!ctl || !a || a.floor_y == null || a.ceiling_y == null) return;
    draft.scale = metres / (a.ceiling_y - a.floor_y);
    ctl.update(live()); ctl.inside(a); paintSide();
  };
  window.miApplySize = () => {
    const want = parseFloat($('#mi-metres', wrap).value);
    if (!ctl || !(want > 0)) return toast('Type the real size in metres.', true);
    const now = ctl.size()[draft.size_axis];
    if (!(now > 0)) return toast('That dimension measures zero — try another.', true);
    draft.scale = draft.scale * (want / now);
    ctl.update(live());
    paintSide();
  };

  async function save() {
    const btn = $('#mi-confirm', wrap);
    btn.disabled = true;
    try {
      if (m.read_only) {
        const copy = await api(`/api/models/${mid}/copy`, { method: 'POST' });
        close(); openModelIntake(copy.id); return;
      }
      m = await api(`/api/models/${mid}`, { method: 'PATCH', body: JSON.stringify({
        ...draft, measured: ctl ? ctl.measured() : m.measured, confirmed: true }) });

      if (ctl) await fetch(`/api/models/${mid}/thumb`, { method: 'POST', body: await ctl.snapshot(640, 360, roomAnalysis()) });
      toast(`${m.title} confirmed`);
      close();
    } catch (e) { toast(e.message, true); btn.disabled = false; }
  }

  paintSide();
  try {
    const S3 = await stage3d();
    if (!document.body.contains(wrap)) return;
    ctl = await S3.mount($('#mi-view', wrap), live(), { accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#E8C36A' });
    if (!document.body.contains(wrap)) { ctl.dispose(); return; }
    // First sight (or an analysis from an older intake): work out what kind of
    // model this is, keep the measurement and a thumbnail straight away.
    const stale = !m.analysis || m.analysis.version !== S3.VERSION;
    if (!m.read_only && (stale || !m.measured)) {
      paintSide();
      await new Promise((ok) => setTimeout(ok, 30));          // let "Measuring…" paint
      const patch = { measured: ctl.measured() };
      if (stale) patch.analysis = ctl.analyse();
      m = await api(`/api/models/${mid}`, { method: 'PATCH', body: JSON.stringify(patch) });
      if (!document.body.contains(wrap)) return;
      if (roomAnalysis()) ctl.inside(m.analysis);
      await fetch(`/api/models/${mid}/thumb`, { method: 'POST', body: await ctl.snapshot(640, 360, roomAnalysis()) });
    } else if (roomAnalysis()) ctl.inside(m.analysis);
    ctl.setRegions(draft.regions, regionSel);
    ctl.onRegions((list) => {          // geometry from the handles, labels from the list
      draft.regions = list.map((r, i) => ({ ...r, label: (draft.regions[i] || r).label }));
    });
    paintSide();
  } catch (e) {
    $('#mi-view', wrap).innerHTML = `<div class="empty-note" style="padding:40px">${esc(e.message || String(e))}</div>`;
  }
}

async function paintStage() {
  const p = state.project, body = $('#tabbody');
  const st = p.stage || { shots: {}, counts: {}, total: 0 };
  if (!state.models) { try { state.models = await api('/api/models'); } catch (e) { state.models = []; } }
  const byModel = Object.fromEntries((state.models || []).map((m) => [m.id, m]));
  const subs = (p.cast || []).filter((x) => x.mode === 'model' && x.model);
  const busy = (p.jobs || []).some((j) => j.kind === 'shots');
  const rows = p.slides.filter((s) => st.shots[s.id]);
  const c = st.counts || {};
  if (!p.slides.length) {
    body.innerHTML = '<div class="empty-note">The shots are planned once the script is written.</div>';
    return;
  }
  const opt = (k, v) => SHOT_OPTS[k].map((o) => `<option ${o === v ? 'selected' : ''}>${o}</option>`).join('');
  const partsOf = (sid) => {
    const x = subs.find((y) => y.id === sid), m = x && byModel[x.model];
    if (!m) return [];
    const named = (m.identity && m.identity.parts) || {};
    return [...new Set([...Object.values(named), ...(m.parts || []).filter((q) => !(q.node in named)).map((q) => q.label),
      ...(m.regions || []).map((r) => r.label)].filter(Boolean))];
  };
  const thumb = (s, j, at) => `<img loading="lazy" src="/api/projects/${p.id}/file/stage/thumbs/${s.id}_${j}.jpg?v=${Math.round(at || 0)}"
      style="width:128px;height:72px;object-fit:cover;border-radius:4px;background:#111" onerror="this.style.visibility='hidden'">`;
  body.innerHTML = `
    <div class="card" style="margin-bottom:18px">
      <div class="row">
        <h3 style="margin:0">Shots</h3>
        <span class="mono" style="color:var(--ink-faint)">${st.total} 3D shot${st.total === 1 ? '' : 's'}
          · ${c.ok || 0} checked${c.flagged ? ` · ${c.flagged} flagged` : ''}${c.stale ? ` · ${c.stale} out of date` : ''}${c.unsolved ? ` · ${c.unsolved} not solved` : ''}</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" onclick="stageSolve()" ${busy || !st.total ? 'disabled' : ''}
          title="solve the shots that are new or out of date, without asking Claude">solve what changed</button>
        <button class="btn sm primary" onclick="stagePlan()" ${busy || !st.total ? 'disabled' : ''}>${c.ok || c.flagged ? 'plan again' : 'plan the shots'}</button>
      </div>
      <p class="mono" style="color:var(--ink-faint);margin:8px 0 0">
        Claude directs each 3D paragraph (subject, part, move, framing, side, join); the stage works out the
        camera and checks it. Flagged shots failed a check and will render as they are unless you change
        them. A shot you set from the view is locked, and planning again leaves it alone.</p>
    </div>
    ${rows.map((s, n) => {
      const sh = s.shot || {}, it = sh.intent || {}, sol = sh.solved || {}, row = st.shots[s.id];
      const [cls, word] = SHOT_STATE[row.state] || ['', row.state];
      const first = (it.subjects || [])[0];
      const parts = partsOf(first);
      return `<div class="card shot-row" data-sid="${s.id}" style="margin-bottom:12px">
        <div class="row" style="align-items:flex-start;gap:14px">
          <div style="display:flex;gap:4px;cursor:pointer" onclick="openShot('${s.id}')" title="preview">
            ${sol.shot ? [0, 1, 2].map((j) => thumb(s, j, sol.thumbs_at || sol.at)).join('') : '<div class="empty-note" style="width:392px;height:72px;padding:24px 0">no shot yet</div>'}
          </div>
          <div style="flex:1;min-width:0">
            <div class="row">
              <span class="mono" style="color:var(--ink-faint)">${n + 1} · ${row.secs.toFixed(1)} s</span>
              <span class="pill ${cls}"><span class="dot"></span>${word}</span>
              ${sh.locked ? '<span class="pill">locked</span>' : ''}
              <div class="spacer"></div>
              <button class="btn xs ghost" onclick="openShot('${s.id}')">preview</button>
              <button class="btn xs ghost" onclick="stageSolve(['${s.id}'])" ${busy || sh.locked ? 'disabled' : ''}>solve</button>
              <button class="btn xs ghost" onclick="stageEdit('${s.id}', {locked: ${!sh.locked}})">${sh.locked ? 'unlock' : 'lock'}</button>
            </div>
            <div class="mi-p" style="margin:6px 0" title="${esc(s.narration)}">${esc(s.narration.slice(0, 160))}${s.narration.length > 160 ? '…' : ''}</div>
            <div class="mono" style="color:var(--ink-faint);margin-bottom:6px">${esc(s.visual_note)}</div>
            <div class="row" style="flex-wrap:wrap;gap:6px">
              <select style="width:auto" onchange="stageEdit('${s.id}', {intent: {subjects: [this.value], part: ''}})">
                ${subs.map((x) => `<option value="${x.id}" ${x.id === first ? 'selected' : ''}>${esc(x.subject)}</option>`).join('')}
              </select>
              ${(it.subjects || []).length > 1 ? `<span class="pill">+ ${(it.subjects || []).slice(1).map((id) => esc((subs.find((x) => x.id === id) || {}).subject || id)).join(', ')}</span>` : ''}
              <select style="width:auto" onchange="stageEdit('${s.id}', {intent: {part: this.value}})">
                <option value="">whole</option>${parts.map((q) => `<option ${q === it.part ? 'selected' : ''}>${esc(q)}</option>`).join('')}
              </select>
              ${['move', 'framing', 'side', 'join'].map((k) => `<select style="width:auto" title="${k}"
                onchange="stageEdit('${s.id}', {intent: {${k}: this.value}})">${opt(k, it[k])}</select>`).join('')}
            </div>
            ${sol.flag || sol.error ? `<div class="mi-p" style="color:var(--warn,#d9a441);margin-top:6px">${esc(sol.error || sol.flag)}</div>` : ''}
            ${(sol.notes || []).length ? `<div class="mono" style="color:var(--ink-faint);margin-top:4px">${sol.notes.map(esc).join(' · ')}</div>` : ''}
          </div>
        </div>
      </div>`;
    }).join('') || '<div class="empty-note">No paragraph has a 3D visual line. Visual lines that start “3D:” become shots here.</div>'}`;
}

async function stagePlan() {
  try { const r = await api(`/api/projects/${state.project.id}/stage/plan`, { method: 'POST', body: '{}' }); watchJob(r.job, 'shots'); }
  catch (e) { toast(e.message, true); }
}
async function stageSolve(slides) {
  try {
    const r = await api(`/api/projects/${state.project.id}/stage/solve`, { method: 'POST', body: JSON.stringify(slides ? { slides } : {}) });
    watchJob(r.job, 'shots');
  } catch (e) { toast(e.message, true); }
}
async function stageEdit(sid, patch) {
  try {
    state.project = await api(`/api/projects/${state.project.id}/stage/${sid}`, { method: 'PATCH', body: JSON.stringify(patch) });
    render();
    // A changed intent is solved straight away, on its own.
    if (patch.intent) stageSolve([sid]);
  } catch (e) { toast(e.message, true); }
}

// The preview: the shot played live in its scene, and a free camera to set
// it by hand. Nothing is rendered; this is the editor's own WebGL.
async function openShot(sid) {
  const pid = state.project.id;
  let data;
  try { data = await api(`/api/projects/${pid}/stage/${sid}/scene`); } catch (e) { return toast(e.message, true); }
  if (!window.StageEditor) await import('/static/stage/editor.js');
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:10px">
        <strong>Shot preview</strong>
        <span class="mono" style="color:var(--ink-faint)">${esc((data.solved && data.solved.subject) || '')} · ${data.secs.toFixed(1)} s</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="sh-close">close</button>
      </div>
      <div id="sh-view" style="width:100%;background:#111;border-radius:6px;overflow:hidden">
        <div class="empty-note" style="padding:60px">loading the scene…</div></div>
      <div class="row" style="margin-top:10px;gap:8px">
        <button class="btn sm" id="sh-play">play</button>
        <input type="range" id="sh-seek" min="0" max="1000" value="0" style="flex:1">
        <span class="mono" id="sh-t" style="width:80px;text-align:right">0.0 s</span>
      </div>
      <div class="row" style="margin-top:10px;gap:8px;flex-wrap:wrap">
        <button class="btn sm ghost" id="sh-free" title="drag to orbit, right-drag to pan, scroll to move in">free camera</button>
        <button class="btn sm ghost" id="sh-a" disabled>set start here</button>
        <button class="btn sm ghost" id="sh-b" disabled>set end here</button>
        <button class="btn sm primary" id="sh-save" disabled>check and keep</button>
        <span class="mono" id="sh-msg" style="color:var(--ink-faint)"></span>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const msg = (t) => { $('#sh-msg', wrap).textContent = t; };
  let ed = null;
  const close = () => { if (ed) ed.dispose(); wrap.remove(); };
  $('#sh-close', wrap).onclick = close;
  wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) close(); });
  try {
    ed = await window.StageEditor.mount($('#sh-view', wrap), data, {
      onTime: (t, total, playing) => {
        $('#sh-t', wrap).textContent = `${t.toFixed(1)} s`;
        $('#sh-seek', wrap).value = Math.round((t / total) * 1000);
        $('#sh-play', wrap).textContent = playing ? 'pause' : 'play';
      },
    });
  } catch (e) { $('#sh-view', wrap).innerHTML = `<div class="empty-note" style="padding:60px">${esc(e.message)}</div>`; return; }
  if (!ed.hasShot()) msg('No shot yet: use the free camera to set one.');
  let playing = false;
  $('#sh-play', wrap).onclick = () => { playing = $('#sh-play', wrap).textContent === 'play'; playing ? ed.play() : ed.pause(); };
  $('#sh-seek', wrap).oninput = (e) => ed.seek(e.target.value / 1000);
  $('#sh-free', wrap).onclick = () => {
    ed.free(); $('#sh-a', wrap).disabled = false; $('#sh-b', wrap).disabled = false;
    msg('Frame the start and press “set start here”; then the end. One mark makes a still.');
  };
  const marked = () => {
    const m = ed.marks();
    $('#sh-save', wrap).disabled = !(m.a || m.b);
    msg(`${m.a ? 'start set' : 'no start'} · ${m.b ? 'end set' : 'no end'}`);
  };
  $('#sh-a', wrap).onclick = () => { ed.mark('a'); marked(); };
  $('#sh-b', wrap).onclick = () => { ed.mark('b'); marked(); };
  $('#sh-save', wrap).onclick = async () => {
    const shot = ed.fromMarks();
    if (!shot) return;
    msg('checking…');
    const rep = ed.check(shot);
    ed.use(shot);
    try {
      state.project = await api(`/api/projects/${pid}/stage/${sid}/shot`, { method: 'PUT',
        body: JSON.stringify({ shot, checks: rep.checks, secs: data.secs }) });
      msg(rep.ok ? 'kept and locked: every check passes' : `kept and locked, flagged: ${rep.failed.join(', ')}`);
      $('#sh-save', wrap).disabled = true;
      render();
    } catch (e) { toast(e.message, true); }
  };
}

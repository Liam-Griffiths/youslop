/* Starting kits share one picker; applying a project kit always needs a preview. */
async function ensureStyleKits() {
  return state.styleKits = await api('/api/style-kits');
}
function styleName(kind, owner = null) {
  return owner?.style_kit?.default_kind === kind ? owner.style_kit.name
    : (state.styleKits || []).find(k => k.id === kind)?.name || pictureKindLabel(kind);
}
function currentStyleKit(owner) {
  const saved = owner.style_kit;
  return saved?.default_kind === owner.style.format ? saved.id : owner.style.format;
}
function stylePoster(id) {
  return `<img src="/api/style-kits/${encodeURIComponent(id)}/poster" loading="lazy" alt="Sample paragraph preview">`;
}
function stylePicker({current, onPick, context}) {
  const kits = state.styleKits || [];
  return `<div class="style-picker" data-context="${context}">${['Pictures','Drawn','3D','Your styles'].map(group => {
    const items = kits.filter(k => (k.builtin ? ['kenburns','essay'].includes(k.default_kind) ? 'Pictures' : k.default_kind === 'stage' ? '3D' : 'Drawn' : 'Your styles') === group);
    return items.length ? `<h3>${group}</h3><div class="style-grid">${items.map(k => `<div class="style-option">
      <button type="button" class="btn style-card" data-kit="${esc(k.id)}" aria-pressed="${k.id === current}" onclick="${onPick}(this.dataset.kit)">
        ${stylePoster(k.id)}<strong>${esc(k.name)}</strong><span>${esc(k.blurb)}</span><small>Needs: ${esc(k.needs || 'pictures')}</small></button>
      ${k.id.startsWith('custom:') ? `<div class="row"><button type="button" class="btn xs ghost" data-id="${esc(k.id.slice(7))}" onclick="openStyleDesigner(this.dataset.id)">Edit style</button>
        <button type="button" class="btn xs ghost" data-id="${esc(k.id.slice(7))}" data-name="${esc(k.name)}" onclick="exportSlideStyle(this.dataset.id,this.dataset.name)">Export</button>
        <button type="button" class="btn xs ghost" data-id="${esc(k.id.slice(7))}" onclick="deleteSlideStyle(this.dataset.id)">Delete</button></div>` : ''}</div>`).join('')}</div>` : '';
  }).join('')}<div class="row style-actions">
    <button type="button" class="btn ghost" onclick="saveCurrentStyle('${context}')" ${context === 'home' ? 'disabled title="Start a video first, then save its style in Visuals"' : ''}>Save current as a style…</button>
    <button type="button" class="btn ghost" onclick="this.nextElementSibling.click()">Import a style…</button><input type="file" accept=".json,application/json" hidden onchange="importStyleKit(this.files[0],'${context}');this.value=''" >
    <button type="button" class="btn ghost" onclick="designStyleBlock()">Design a block…</button></div></div>`;
}
async function openStylePicker(context) {
  try {
    await ensureStyleKits();
    state.stylePickerContext = context;
    const owner = context === 'project' ? state.project : state.channel;
    const current = context === 'home' ? state.newKit || state.newFormat : currentStyleKit(owner);
    const dialog = studioDialog('style-dialog', `<h2 id="studio-dialog-title">Choose a style</h2>
      ${stylePicker({current,onPick:'chooseStyleKit',context})}<p role="status"></p><button type="button" class="btn ghost" data-close>Cancel</button>`);
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    mountStylePreviews(dialog);
  } catch(e) { toast(e.message,true); }
}
async function chooseStyleKit(id) {
  const context = state.stylePickerContext, dialog = document.querySelector('dialog.style-dialog');
  const kit = state.styleKits.find(k => k.id === id);
  if (context === 'home') { state.newKit = id; pickNewFormat(kit.default_kind); dialog.close(); return; }
  const owner = context === 'project' ? 'projects' : 'channels', target = context === 'project' ? state.project : state.channel;
  try {
    const path = `/api/${owner}/${target.id}/style-kit`;
    const summary = await api(path,{method:'POST',body:JSON.stringify({kit_id:id,dry_run:true})});
    dialog.innerHTML = `<h2 id="studio-dialog-title">Apply ${esc(kit.name)}?</h2><p>${esc(summary.message)}</p>
      <p>Also changes: ${esc(styleChangeLabels(summary))}.</p>
      <p role="status"></p><div class="row"><button type="button" class="btn" data-apply>Apply</button><button type="button" class="btn ghost" data-close>Cancel</button></div>`;
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    dialog.querySelector('[data-apply]').onclick = async e => {
      e.target.disabled = true;
      try {
        await api(path,{method:'POST',body:JSON.stringify({kit_id:id})});
        if (context === 'project') { state.project = await api(`/api/projects/${target.id}`); delete state.visualSource; await loadStageStates(state.project); await render(); }
        else applyChannel(await api(`/api/channels/${target.id}`));
        dialog.close();
      } catch(error) { dialog.querySelector('[role=status]').textContent = error.message; e.target.disabled = false; }
    };
    dialog.querySelector('[data-apply]').focus();
  } catch(e) { dialog.querySelector('[role=status]').textContent = e.message; }
}
async function pickHouseStyle(id) { state.stylePickerContext = 'channel'; await openStylePicker('channel'); if (document.querySelector('dialog.style-dialog')) await chooseStyleKit(id); }
async function saveCurrentStyle(context) {
  const name = prompt('Name this style'); if (!name) return;
  const owner = context === 'project' ? 'projects' : 'channels';
  const id = context === 'project' ? state.project.id : state.channel?.id || $('#chan')?.value;
  try { await api('/api/style-kits',{method:'POST',body:JSON.stringify({name,owner,id})}); document.querySelector('dialog.style-dialog')?.close(); await openStylePicker(context); }
  catch(e) { toast(e.message,true); }
}
async function importStyleKit(file, context = state.stylePickerContext || 'channel') {
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (!data.corkbored_style_kit) return importSlideStyle(file);
    await api('/api/style-kits/import',{method:'POST',body:JSON.stringify(data)});
    document.querySelector('dialog.style-dialog')?.close(); await openStylePicker(context);
  } catch(e) { toast(e.message,true); }
}
function designStyleBlock() {
  document.querySelector('dialog.style-dialog')?.close();
  state.openBlockDescription = true;
  if (state.project) state.blocksProjectId = state.project.id;
  go('#/blocks');
}
function mountStylePreviews(host) {
  host.querySelectorAll('[data-kit]').forEach(card => {
    let timer, video;
    const stop = () => { clearTimeout(timer); video?.remove(); video = null; card.querySelector('img').hidden = false; };
    const play = (force = false) => {
      if (video) { stop(); return; }
      if (!force && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      timer = setTimeout(() => {
        if (!card.isConnected) return;
        video = document.createElement('video'); video.hidden = true; video.muted = true; video.loop = true; video.autoplay = true; video.playsInline = true;
        video.src = `/api/style-kits/${encodeURIComponent(card.dataset.kit)}/motion`;
        const motion = video;
        video.oncanplay = () => { if (video !== motion || !card.isConnected) return; card.querySelector('img').hidden = true; motion.hidden = false; motion.play().catch(stop); };
        video.onerror = stop; card.prepend(video);
      },400);
    };
    card.onmouseenter = () => play(); card.onmouseleave = stop;
    card.onkeydown = e => { if (e.code === 'Space') { e.preventDefault(); play(true); } };
  });
}
function lookControls(st, present, saver) {
  const photos = present.some(k => ['kenburns','essay','camera'].includes(k));
  const color = (key,label) => `<label class="field"><span>${label}</span><span class="row"><input type="color" value="${esc(st[key] || '#7FA6B8')}" onchange="${saver}({${key}:this.value})"><output class="mono">${esc(st[key])}</output></span></label>`;
  const range = (key,label,max,step) => `<label class="field"><span>${label} · ${st[key]}</span><input type="range" min="0" max="${max}" step="${step}" value="${st[key]}" onchange="${saver}({${key}:+this.value})"></label>`;
  return `${color('accent','Accent')}${color('accent2','Second accent')}
    ${present.includes('board') ? boardKnobs(st,saver) : ''}${present.filter(isCut).map(k => `<h3>${esc(pictureKindLabel(k))}</h3>${cutKnobs({...st,format:k},saver)}`).join('')}
    ${photos ? `${present.includes('kenburns') ? `<label class="field"><span>Picture drift · ${st.ken_burns_amount}</span><input type="range" min="0" max=".24" step=".01" value="${st.ken_burns_amount}" onchange="${saver}({ken_burns:+this.value>0,ken_burns_amount:+this.value})"></label>` : ''}
    ${range('vignette','Vignette',.8,.02)}${range('transition','Crossfade · seconds',1.6,.05)}
    <label class="field"><span>Grade</span><select onchange="${saver}({grade:this.value})">${['warm','neutral','cool','mono'].map(g => `<option ${g === st.grade ? 'selected' : ''}>${g}</option>`).join('')}</select></label>
    <label><input type="checkbox" ${st.chapter_cards ? 'checked' : ''} onchange="${saver}({chapter_cards:this.checked})"> Chapter cards</label>` : ''}`;
}
function openProjectLook() {
  const p = state.project, present = [...new Set(p.slides.map(s => pictureKind(s,p)))];
  const dialog = studioDialog('style-dialog', `<h2 id="studio-dialog-title">Look and block theme</h2>${lookControls(p.style,present.length ? present : [p.style.format],'saveVisualLook')}${blockThemePanel()}<button type="button" class="btn ghost" data-close>Close</button>`);
  dialog.querySelector('[data-close]').onclick = () => dialog.close(); mountBlockTheme('project',p.id);
}
async function saveVisualLook(patch) { try { await saveStyle(patch,false); toast('Look saved'); } catch(e) { toast(e.message,true); } }
function renderStyleSummary(p, theme = {}) {
  const kinds = [...new Set(p.slides.map(s => pictureKind(s,p)))];
  return `<section class="panel"><h3>Style: ${esc(styleName(p.style.format,p))}</h3><p>Kinds in use: ${esc(kinds.map(k => pictureKindLabel(k)).join(', ') || 'No pictures yet')}</p>
    <p><span class="swatch" style="background-color:${esc(theme.accent || p.style.accent)}"></span> ${esc(p.style.theme)} · Music bed: ${esc(p.music === '__auto__' ? 'Choose automatically' : p.music || 'None')}</p>
    <a href="#/p/${p.id}/visuals">Change in Visuals</a> · <button type="button" class="btn ghost" onclick="$('#project-sound').open=true;$('#project-sound').scrollIntoView()">Change sound</button></section>`;
}

// Plain names for the stored fields a kit can change; unknown keys are skipped.
function styleChangeLabels(summary) {
  const names = {format:'the default picture', theme:'colour theme', accent:'accent', accent2:'second accent',
    grade:'grade', vignette:'vignette', ken_burns:'drift', ken_burns_amount:'drift', transition:'crossfade',
    title_font:'title font', chapter_cards:'chapter cards', board_hand:'board handwriting', board_ground:'board colour',
    board_grain:'board texture', board_settle:'board timing', cut_look:'drawn look', block_theme:'block theme'};
  const style = summary.changes?.style;
  const keys = style ? Object.keys(style.after || {}).filter(k => JSON.stringify(style.before?.[k]) !== JSON.stringify(style.after[k])) : [];
  const labels = [...new Set(keys.map(k => names[k]).filter(Boolean))];
  if (summary.changes?.blocks || summary.changes?.block_presets) labels.push('pinned blocks');
  return labels.join(', ') || 'nothing else';
}

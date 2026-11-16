// Layer times come from the server. All items use T4.3's selection model.
const TL_LAYER_KINDS = {graphics: 'overlay', sponsors: 'sponsor', titles: 'title', cues: 'cue',
  chapters: 'chapter', music: 'music', stings: 'sting', notes: 'note', media: 'media'};
const tlHideQuery = () => '?hide=' + (state.project.layers || [])
  .filter(row => row.hidden).map(row => encodeURIComponent(row.id)).sort().join(',');

// Keep role selectors and item indexes for the existing inspectors/gestures.
// Project ids identify lanes and collapse preferences, never drop compatibility.
function tlLayerRows(pictures = '', voice = '') {
  const rows = TL.data.project_layers || [];
  return rows.map(row => {
    const role = row.role === 'captions' ? 'titles' : row.role;
    const hidden = !!row.hidden;
    const label = `<span class="tl-layer-label" title="${esc(row.name)}">
      <i class="tl-layer-swatch" aria-hidden="true"></i>
      <span class="tl-layer-tools"><button type="button" class="btn sm ghost" data-eye="${esc(row.id)}"
        aria-label="${hidden ? 'Show' : 'Hide'} ${esc(row.name)} in preview" aria-pressed="${hidden}">${hidden ? '○' : '◉'}</button>
      <button type="button" class="btn sm ghost" data-lock="${esc(row.id)}" aria-pressed="${!!row.locked}"
        title="${row.locked ? 'Unlock' : 'Lock'} ${esc(row.name)}" aria-label="${row.locked ? 'Unlock' : 'Lock'} ${esc(row.name)}">
        <svg aria-hidden="true" width="12" height="14" viewBox="0 0 12 14" fill="none" stroke="currentColor">
          <rect x="1" y="6" width="10" height="7" rx="1" fill="${row.locked ? 'currentColor' : 'none'}"/><path d="${row.locked ? 'M3 6V3a3 3 0 0 1 6 0v3' : 'M3 6V3a3 3 0 0 1 6 0'}"/>
        </svg></button><button type="button" class="btn sm ghost" data-manage="${esc(row.id)}" aria-label="Manage ${esc(row.name)}">⋯</button></span>
      <span class="tl-layer-name">${esc(row.name)}</span></span>`;
    const content = row.role === 'pictures' ? pictures + tlInsertButtons()
      : row.role === 'voice' ? voice + tlGapItems()
      : row.items.map(item => {
        const i = (TL.data.layers?.[role] || []).findIndex(s => s.id === item.id && s.sid === item.sid);
        return `<button type="button" class="btn tl-layer-item ${esc(item.severity || '')} ${item.src === 'user' ? 'user' : ''}" data-layer="${role}" data-item="${i}"
          style="left:${item.t0 * TL.zoom}px;width:${Math.max(2, (item.t1 - item.t0) * TL.zoom - 2)}px"
          title="${esc(`${item.severity ? item.severity + ' · ' : ''}${tlClock(item.t0)}–${tlClock(item.t1)} · ${item.text}`)}">${esc((item.severity ? item.severity + ' · ' : '') + (item.text || item.cue_kind || item.kind))}</button>`;
      }).join('');
    const classes = row.role === 'pictures' ? 'tl-pictures' : row.role === 'voice' ? 'para' : 'tl-layer';
    return `<div class="tl-lane ${classes} ${row.locked ? 'locked' : ''} ${row.role === 'sponsors' ? 'tl-sponsors' : ''} ${hidden ? 'hidden' : ''}" data-track="${esc(row.id)}" data-role="${row.role}"
      style="--track-color:var(--${row.color})">${label}${content}</div>${row.role === 'voice' ? tlCameraRows() : ''}`;
  }).join('');
}

function tlWireLayers() {
  const track = $('#tl-track');
  tlWireLayerManager(track);
  if (TL.lockGuard) track.removeEventListener('pointerdown', TL.lockGuard, true);
  TL.lockGuard = e => {
    if (e.target.closest('[data-lock], [data-eye], .tl-layer-label')) return;
    const lane = e.target.closest('[data-track], [data-camera]');
    const row = (TL.data.project_layers || []).find(row => row.id === lane?.dataset.track);
    const cameraLocked = lane?.dataset.camera && (TL.data.project_layers || []).some(row =>
      row.locked && ['pictures', 'voice'].includes(row.role));
    if (row?.locked || cameraLocked) { e.stopImmediatePropagation(); tlMsg('Unlock the layer before editing.'); }
  };
  track.addEventListener('pointerdown', TL.lockGuard, true);
  track.querySelectorAll('[data-lock]').forEach(el => {
    el.onpointerdown = e => e.stopPropagation();
    el.onclick = e => { e.stopPropagation(); tlLockLayer(el.dataset.lock); };
  });
  const add = $('#tl-add-sponsor');
  if (add) {
    add.onpointerdown = e => e.stopPropagation();
    add.onclick = e => { e.stopPropagation(); tlSponsorAdd(); };
  }
  const graphic = $('#tl-add-graphic');
  if (graphic) graphic.onclick = tlGraphicAdd;
  track.querySelectorAll('[data-eye], [data-layer]').forEach((el) => {
    el.onpointerdown = (e) => e.stopPropagation();
    el.onclick = (e) => {
      e.stopPropagation();
      if (el.dataset.eye) tlHideLayer(el.dataset.eye);
      else tlSelect(TL.data.layers[el.dataset.layer][+el.dataset.item], e.shiftKey || e.ctrlKey || e.metaKey);
    };
    el.ondblclick = (e) => {
      e.stopPropagation();
      if (el.dataset.layer) { tlPause(); tlSeek(TL.data.layers[el.dataset.layer][+el.dataset.item].t0); }
    };
  });
}

function tlCanEdit(items, roles = []) {
  const rows = TL.data?.project_layers || [];
  const blocked = rows.some(row => row.locked && roles.includes(row.role)) || items.some(item => rows.some(row => row.locked && row.items.some(candidate =>
    candidate.id === item.id && candidate.sid === item.sid && candidate.kind === item.kind)));
  if (blocked) tlMsg('Unlock the layer before editing.');
  return !blocked;
}

async function tlLockLayer(ident) {
  const row = TL.data.project_layers.find(row => row.id === ident);
  try {
    state.project = await api(`/api/projects/${TL.pid}/layers/${encodeURIComponent(ident)}`, {
      method:'PATCH', body:JSON.stringify({locked:!row.locked}),
      editLabel:`${row.locked ? 'unlock' : 'lock'} ${row.name}`});
    await tlRefresh();
  } catch (error) { tlMsg(error.message); }
}

async function tlHideLayer(ident) {
  const row = TL.data.project_layers.find(row => row.id === ident);
  try {
    state.project = await api(`/api/projects/${TL.pid}/layers/${encodeURIComponent(ident)}`, {
      method:'PATCH', body:JSON.stringify({hidden:!row.hidden}),
      editLabel:`${row.hidden ? 'show' : 'hide'} ${row.name}`});
    tlPause();
    TL.queue = []; TL.pending.clear(); TL.failed.clear();
    TL.vids.forEach(v => { v.dataset.seg = ''; v.removeAttribute('src'); v.load(); });
    TL.audio.removeAttribute('src'); TL.audio.load(); TL.mixStamp = 0; TL.mixFailed = false;
    await tlRefresh(true);
  } catch (error) { tlMsg(error.message); }
}

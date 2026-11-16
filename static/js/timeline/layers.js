// Layer times come from the server. All items use T4.3's selection model.
const TL_LAYER_KINDS = {graphics: 'overlay', sponsors: 'sponsor', titles: 'title', cues: 'cue',
  chapters: 'chapter', music: 'music', stings: 'sting', notes: 'note'};
const tlHideQuery = () => '?hide=' + Object.keys(TL.hidden).filter((k) => TL.hidden[k]).sort().join(',');

// Keep role selectors and item indexes for the existing inspectors/gestures.
// Project ids identify lanes and collapse preferences, never drop compatibility.
function tlLayerRows(pictures = '', voice = '') {
  const rows = TL.data.project_layers || [];
  const first = role => rows.find(row => row.role === role);
  return rows.filter(row => row.items.length ||
    (['pictures', 'voice'].includes(row.role) && row === first(row.role))).map(row => {
    const role = row.role === 'captions' ? 'titles' : row.role;
    const hidden = !!TL.hidden[role];
    const label = `<span class="tl-layer-label" title="${esc(row.name)}">
      <i class="tl-layer-swatch" aria-hidden="true"></i>
      ${['pictures', 'voice', 'sponsors'].includes(role) ? '' : `<button type="button" class="btn sm ghost" data-eye="${role}"
        aria-label="${hidden ? 'Show' : 'Hide'} ${role} in preview" aria-pressed="${hidden}">${hidden ? '○' : '◉'}</button>`}
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
    return `<div class="tl-lane ${classes} ${row.role === 'sponsors' ? 'tl-sponsors' : ''} ${hidden ? 'hidden' : ''}" data-track="${esc(row.id)}" data-role="${row.role}"
      style="--track-color:var(--${row.color})">${label}${content}</div>${row.role === 'voice' ? tlCameraRows() : ''}`;
  }).join('');
}

function tlWireLayers() {
  const track = $('#tl-track');
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

async function tlHideLayer(row) {
  tlPause();
  TL.hidden[row] = !TL.hidden[row];
  TL.queue = []; TL.pending.clear(); TL.failed.clear();
  TL.vids.forEach((v) => { v.dataset.seg = ''; v.removeAttribute('src'); v.load(); });
  TL.audio.removeAttribute('src'); TL.audio.load(); TL.mixStamp = 0;
  TL.mixFailed = false;
  await tlRefresh(true);
}

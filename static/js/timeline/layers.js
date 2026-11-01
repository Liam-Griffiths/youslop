// Layer times come from the server. All items use T4.3's selection model.
const TL_LAYER_KINDS = {titles: 'title', cues: 'cue', chapters: 'chapter',
  music: 'music', stings: 'sting', notes: 'note', sponsors: 'sponsor'};
const tlHideQuery = () => '?hide=' + Object.keys(TL.hidden).filter((k) => TL.hidden[k]).sort().join(',');

function tlLayerRows() {
  return Object.entries(TL_LAYER_KINDS).map(([row, kind]) => {
    const items = TL.data.layers?.[row] || [];
    if (row === 'sponsors' && !items.length) return '';
    const hidden = !!TL.hidden[row];
    return `<div class="tl-lane tl-layer ${hidden ? 'hidden' : ''}">
      <span class="tl-layer-label">${row === 'sponsors' ? row : `<button type="button" data-eye="${row}"
        aria-label="${hidden ? 'Show' : 'Hide'} ${row} in preview" aria-pressed="${hidden}">${hidden ? '○' : '◉'}</button>${row}`}</span>
      ${items.map((s, i) => `<button type="button" class="tl-layer-item ${esc(s.severity || '')} ${s.src === 'user' ? 'user' : ''}" data-layer="${row}" data-item="${i}"
        style="left:${s.t0 * TL.zoom}px;width:${Math.max(2, (s.t1 - s.t0) * TL.zoom - 2)}px"
        title="${esc(`${s.severity ? s.severity + ' · ' : ''}${tlClock(s.t0)}–${tlClock(s.t1)} · ${s.text}`)}">${esc((s.severity ? s.severity + ' · ' : '') + (s.text || s.cue_kind || kind))}</button>`).join('')}
    </div>`;
  }).join('');
}

function tlWireLayers() {
  const track = $('#tl-track');
  track.querySelectorAll('[data-eye], [data-layer]').forEach((el) => {
    el.onpointerdown = (e) => e.stopPropagation();
    el.onclick = (e) => {
      e.stopPropagation();
      if (el.dataset.eye) tlHideLayer(el.dataset.eye);
      else tlSelect(TL.data.layers[el.dataset.layer][+el.dataset.item]);
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

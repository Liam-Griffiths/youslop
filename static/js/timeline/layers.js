// Layer times come from the server. All items use T4.3's selection model.
const TL_LAYER_KINDS = {graphics: 'overlay', sponsors: 'sponsor', titles: 'title', cues: 'cue',
  chapters: 'chapter', music: 'music', stings: 'sting', notes: 'note'};
const tlHideQuery = () => '?hide=' + Object.keys(TL.hidden).filter((k) => TL.hidden[k]).sort().join(',');

function tlLayerRows() {
  // Essay caption spans already arrive in the titles layer. Display them in
  // their own lane while retaining the title inspector and visibility contract.
  const rows = Object.entries(TL_LAYER_KINDS).flatMap(([row, kind]) => row === 'titles'
    ? [[row, kind, 'titles'], [row, kind, 'captions']] : [[row, kind, row]]);
  return rows.map(([row, kind, label]) => {
    const captions = state.project.style.format === 'essay';
    const items = row === 'titles' && (label === 'captions') !== captions
      ? [] : TL.data.layers?.[row] || [];
    const hidden = !!TL.hidden[row];
    return `<div class="tl-lane tl-layer ${row === 'sponsors' ? 'tl-sponsors' : ''} ${hidden ? 'hidden' : ''}">
      <span class="tl-layer-label">${row === 'sponsors' ? '<button type="button" class="btn sm ghost" id="tl-add-sponsor" aria-label="Add a sponsor">+</button>sponsors' : `<button type="button" class="btn sm ghost" data-eye="${row}"
        aria-label="${hidden ? 'Show' : 'Hide'} ${label} in preview" aria-pressed="${hidden}">${hidden ? '○' : '◉'}</button>${label}`}</span>
      ${items.map((s, i) => `<button type="button" class="btn tl-layer-item ${esc(s.severity || '')} ${s.src === 'user' ? 'user' : ''}" data-layer="${row}" data-item="${i}"
        style="left:${s.t0 * TL.zoom}px;width:${Math.max(2, (s.t1 - s.t0) * TL.zoom - 2)}px"
        title="${esc(`${s.severity ? s.severity + ' · ' : ''}${tlClock(s.t0)}–${tlClock(s.t1)} · ${s.text}`)}">${esc((s.severity ? s.severity + ' · ' : '') + (s.text || s.cue_kind || kind))}</button>`).join('')}
    </div>`;
  }).join('');
}

function tlWireLayers() {
  const track = $('#tl-track');
  $('#tl-add-sponsor').onpointerdown = (e) => e.stopPropagation();
  $('#tl-add-sponsor').onclick = (e) => { e.stopPropagation(); tlSponsorAdd(); };
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

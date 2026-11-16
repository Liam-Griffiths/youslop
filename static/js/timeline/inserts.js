// Main-track boundaries persist slide ids, never times from the rippled cut.
function tlInsertPoints() {
  if (state.project.kind === 'clip') return [];
  const rows = tlParas(), intro = tlSegs().find(s => s.type === 'intro');
  return [{after:'', t:intro ? intro.start + intro.duration : 0}, ...rows.map((q,i) => ({after:q.id,
    t:rows[i+1]?.start ?? tlSectionEnd()}))];
}
const tlInsertNearest = (t = TL.cur) => tlInsertPoints().reduce((a,b) => !a || Math.abs(b.t-t) < Math.abs(a.t-t) ? b : a, null);

function tlInsertButtons() {
  return tlInsertPoints().map((p,i) => `<button type="button" class="tl-insert-plus" data-insert-point="${i}"
    style="left:${p.t * TL.zoom}px" aria-label="Insert at ${tlClock(p.t)}" title="Insert here (. / Insert)">+</button>`).join('');
}

function tlInsertPaint() {
  const point = tlInsertNearest(), points = tlInsertPoints();
  document.querySelectorAll('[data-insert-point]').forEach(button => {
    button.classList.toggle('nearest', points[+button.dataset.insertPoint]?.after === point?.after);
  });
}

function tlWireInserts() {
  const lane = $('#tl-track .tl-pictures');
  if (!lane) return;
  lane.querySelectorAll('[data-insert-point]').forEach(button => {
    let start, moved = false;
    button.onpointerdown = e => {
      e.stopPropagation();
      if (e.button !== 0 || TL.drag) return;
      start = {x:e.clientX, y:e.clientY}; moved = false; button.setPointerCapture(e.pointerId);
    };
    button.onpointermove = e => {
      if (!start || TL.drag) return;
      if (Math.hypot(e.clientX-start.x, e.clientY-start.y) > 3) moved = true;
      if (moved) {
        if (!TL.scrubbing) tlPause();
        TL.scrubbing = true;
        tlSeek(Math.max(0, (e.clientX-$('#tl-track').getBoundingClientRect().left-104)/TL.zoom), {ensure:false});
      }
    };
    const finish = () => {
      if (!start) return;
      start = null;
      if (TL.scrubbing) { TL.scrubbing = false; tlSeek(TL.cur); }
    };
    button.onpointerup = e => { button.onpointermove(e); finish(); };
    button.onpointercancel = button.onlostpointercapture = () => { if (start) { moved = true; finish(); } };
    button.onclick = e => {
      e.stopPropagation();
      if (TL.drag || (e.detail && moved)) return;
      tlInsertMenu(tlInsertPoints()[+button.dataset.insertPoint]);
    };
    button.ondragstart = e => e.preventDefault();
  });
  lane.ondragover = e => {
    if (!TL.insertDrag || TL.insertDrag.pid !== TL.pid || TL.drag) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
    const t = (e.clientX - $('#tl-track').getBoundingClientRect().left - 104) / TL.zoom;
    const node = e.target?.closest?.('[data-seg]'), seg = node && tlSegs()[+node.dataset.seg];
    tlInsertClearGhost();
    if (seg?.type === 'picture' && !e.target.closest('[data-insert-point]')
        && Math.min(Math.abs(t-seg.start), Math.abs(t-seg.start-seg.duration))*TL.zoom > 6) {
      if (typeof tlCanEdit === 'function' && !tlCanEdit([], ['pictures'])) { e.dataTransfer.dropEffect = 'none'; return; }
      TL.insertReplace = tlItems('picture').find(s => s.id === seg.ref);
      node.classList.add('tl-source-replace'); return;
    }
    tlInsertGhost(tlInsertNearest(t), TL.insertDrag.payload.seconds || TL.insertDrag.payload.out_s - TL.insertDrag.payload.in_s);
  };
  lane.ondragleave = e => { if (!lane.contains(e.relatedTarget)) tlInsertClearGhost(); };
  lane.ondrop = e => {
    if (!TL.insertDrag || TL.insertDrag.pid !== TL.pid || (!TL.insertDrop && !TL.insertReplace)) return;
    e.preventDefault(); e.stopPropagation();
    const {payload} = TL.insertDrag, point = TL.insertDrop, replace = TL.insertReplace;
    TL.insertDrag = null; tlInsertClearGhost();
    if (replace) tlSourceUse(payload, replace);
    else if (typeof tlCanEdit !== 'function' || tlCanEdit([], ['pictures'])) tlInsertSave('', {...payload, after:point.after});
  };
}

function tlInsertClearGhost() {
  document.querySelectorAll('.tl-source-replace').forEach(n => n.classList.remove('tl-source-replace'));
  TL.insertReplace = null;
  document.querySelectorAll('.tl-insert-ghost, .tl-insert-ripple').forEach(n => n.remove());
  TL.insertDrop = null;
}

function tlInsertGhost(point, seconds) {
  tlInsertClearGhost();
  if (!point) return;
  TL.insertDrop = point;
  const lane = $('#tl-track .tl-pictures');
  const ghost = document.createElement('div'); ghost.className = 'tl-insert-ghost';
  Object.assign(ghost.style, {left:`${point.t*TL.zoom}px`, width:`${Math.max(18,seconds*TL.zoom)}px`});
  ghost.textContent = `+${seconds.toFixed(1)} s`; lane.append(ghost);
  lane.querySelectorAll('[data-seg]').forEach(node => {
    const seg = tlSegs()[+node.dataset.seg], end = seg.start+seg.duration;
    if (end <= point.t) return;
    const ripple = document.createElement('div'); ripple.className = 'tl-insert-ripple';
    const start = Math.max(seg.start,point.t);
    Object.assign(ripple.style, {left:`${(start+seconds)*TL.zoom}px`, width:`${Math.max(2,(end-start)*TL.zoom-2)}px`});
    lane.append(ripple);
  });
}

function tlInsertDialog(title, html) {
  tlPause();
  const previous = document.activeElement, dialog = document.createElement('dialog');
  dialog.className = 'studio-dialog tl-insert-dialog';
  dialog.setAttribute('aria-label', title);
  dialog.innerHTML = `<h2>${esc(title)}</h2>${html}<p role="status"></p><button type="button" class="btn ghost" data-close>Close</button>`;
  const close = () => { dialog.close(); dialog.remove(); if (previous?.isConnected) previous.focus(); };
  dialog.querySelector('[data-close]').onclick = close;
  dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
  document.body.append(dialog); dialog.showModal();
  return {dialog, close};
}

function tlInsertMenu(point = tlInsertNearest()) {
  if (typeof tlCanEdit === 'function' && !tlCanEdit([], ['pictures'])) return;
  if (!point) return;
  const {dialog, close} = tlInsertDialog(`Insert at ${tlClock(point.t)}`, `<div class="tl-insert-options">${[
    ['clip','Clip from footage'], ['block','Block'], ['picture','Picture from Library'], ['card','Title card']
  ].map(([kind,label]) => `<button type="button" class="btn" data-insert-kind="${kind}">${label}</button>`).join('')}</div>`);
  const buttons = [...dialog.querySelectorAll('[data-insert-kind]')];
  buttons.forEach((button,i) => {
    button.onclick = () => { close(); tlInsertChoose(button.dataset.insertKind, point); };
    button.onkeydown = e => {
      if (['ArrowDown','ArrowUp'].includes(e.key)) {
        e.preventDefault(); buttons[(i+(e.key === 'ArrowDown' ? 1 : buttons.length-1))%buttons.length].focus();
      }
    };
  });
  buttons[0].focus();
}

async function tlInsertChoose(kind, point) {
  if (kind === 'block') return tlInsertBlock(point);
  if (kind === 'card') {
    const {dialog, close} = tlInsertDialog('Title card', `<form><label for="insert-text">Text</label><input id="insert-text" required maxlength="400">
      <label for="insert-seconds">Length (seconds)</label><input id="insert-seconds" type="number" min="0.05" step="0.05" value="4" required>
      <button class="btn" type="submit">Insert card</button></form>`);
    dialog.querySelector('form').onsubmit = async e => {
      e.preventDefault();
      if (await tlInsertSave('', {kind, after:point.after, text:dialog.querySelector('#insert-text').value,
        seconds:Number(dialog.querySelector('#insert-seconds').value)})) close();
    };
    dialog.querySelector('input').focus(); return;
  }
  const {dialog, close} = tlInsertDialog(kind === 'clip' ? 'Clip from footage' : 'Picture from Library',
    '<label for="insert-search">Find a source</label><input type="search" id="insert-search"><div class="tl-insert-options" data-sources>Loading…</div>');
  const items = await tlInsertSources();
  if (!dialog.isConnected) return;
  const paint = () => tlInsertSourceList(dialog.querySelector('[data-sources]'), items.filter(item => item.payload.kind === kind
    && item.label.toLowerCase().includes(dialog.querySelector('input').value.toLowerCase())), async payload => {
      if (await tlInsertSave('', {...payload, after:point.after})) close();
    }, false);
  dialog.querySelector('input').oninput = paint; paint(); dialog.querySelector('input').focus();
}

async function tlInsertBlock(point, selection = null) {
  const p = state.project;
  tlPause();
  try {
    await renderBlocks(selection?.block || '', {mode:'pick', project:p.id, channel:p.channel_id, selection, aspect:tlInsertAspect(), onUse:async selection => {
      if (state.project.id !== p.id) return;
      const id = await tlInsertSave('', {after:point.after, kind:'block', block:selection.block, vars:selection.vars, seconds:4});
      if (id) { await render(); tlInsertSelect(id); }
    }});
  } catch (error) { toast(error.message, true); }
}

function tlInsertSelect(id) {
  const item = tlItems('picture').find(s => s.sid === id);
  if (item) { tlSelect(item); tlSeek(item.t0, {ensure:false}); }
}

function tlInsertSave(id, patch) {
  const pid = TL.pid, gesture = crypto.randomUUID();
  const result = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return false;
    try {
      tlPause();
      const before = new Set(state.project.slides.map(s => s.id));
      const project = await api(`/api/projects/${pid}/inserts${id ? '/' + encodeURIComponent(id) : ''}`, {
        method:patch === null ? 'DELETE' : id ? 'PATCH' : 'POST', ...(patch === null ? {} : {body:JSON.stringify(patch)}),
        editLabel:patch === null ? 'delete insert' : id ? 'change insert' : 'add insert', editGesture:gesture});
      if (TL.pid !== pid || state.project?.id !== pid) return false;
      state.project = project; TL.mixFailed = false;
      const selected = id || project.slides.find(s => !before.has(s.id))?.id;
      if (patch === null) tlSelect(null);
      await tlRefresh();
      if (patch !== null) tlInsertSelect(selected);
      return selected;
    } catch (error) { toast(error.message, true); return false; }
  });
  tlInspectorQueue = result.then(() => {}); return result;
}

function tlInsertKey(e) {
  if (state.project.kind === 'clip' || e.ctrlKey || e.metaKey || e.altKey || e.target?.isContentEditable
      || e.target?.closest?.('input, textarea, select, [contenteditable], [role="textbox"]')) return false;
  if (e.key === '.' || e.key === 'Insert') { tlInsertMenu(); return true; }
  const sel = TL.selection, row = state.project.slides.find(s => s.id === sel?.sid);
  if (!TL.section && TL.selections?.length === 1 && ['paragraph','picture'].includes(sel?.kind) && row?.insert?.kind
      && ['Delete','Backspace'].includes(e.key)) { tlInsertSave(row.id, null); return true; }
  return false;
}

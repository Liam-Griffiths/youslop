let tlSectionClipboard = null; // Detached, project-local snapshot; survives selection and undo.

// Sections are contiguous main-track rows, distinct from individual lane items.
function tlSectionSet(a, b = a) {
  const rows = tlParas(), x = rows.findIndex(q => q.id === a), y = rows.findIndex(q => q.id === b);
  if (x < 0 || y < 0 || state.project.kind === 'clip') return;
  TL.section = {ids:rows.slice(Math.min(x,y), Math.max(x,y)+1).map(q => q.id), version:state.project.updated_at};
  TL.selection = null; TL.selections = []; tlInspector(); tlSelectionPaint(); tlSectionPaint();
}

function tlSectionBounds() {
  const rows = tlParas(), ids = TL.section?.ids || [];
  const first = rows.find(q => q.id === ids[0]), last = rows.find(q => q.id === ids.at(-1));
  if (!first || !last) return null;
  const next = rows[rows.indexOf(last)+1];
  return {a:first.start, b:next?.start ?? tlSectionEnd()};
}

const tlSectionEnd = () => {
  const last = tlSegs().filter(s => ['picture','sponsor'].includes(s.type)).at(-1);
  return last ? last.start+last.duration : 0;
};

function tlSectionPaint() {
  const track = $('#tl-track');
  if (!track) return;
  const sc = $('#tl-scroll');
  if (sc) sc.onscroll = tlSectionPositionTools;
  track.querySelectorAll('.tl-section, .tl-section-tools').forEach(n => n.remove());
  const bounds = tlSectionBounds();
  if (!bounds && (!tlSectionClipboard || tlSectionClipboard.project_id !== TL.pid)) return;
  const band = document.createElement('div'); band.className = 'tl-section';
  if (bounds) Object.assign(band.style, {left:`${104+bounds.a*TL.zoom}px`, width:`${(bounds.b-bounds.a)*TL.zoom}px`});
  if (bounds) track.append(band);
  const tools = document.createElement('div'); tools.className = 'tl-section-tools';
  tools.setAttribute('role', 'toolbar'); tools.setAttribute('aria-label', 'Section commands');
  const copied = tlSectionClipboard?.slides?.length || 0;
  tools.innerHTML = `<span>${bounds ? `${TL.section.ids.length} selected · script order`
    : `${copied} copied · Paste goes at the playhead`}</span>
    <button type="button" class="btn sm" data-section-dir="-1" aria-label="Move section left">←</button>
    <button type="button" class="btn sm" data-section-dir="1" aria-label="Move section right">→</button>
    <button type="button" class="btn sm" data-section-delete>Delete section</button>
    ${['cut','copy','paste','duplicate'].map(op => `<button type="button" class="btn sm" data-section-op="${op}">${op[0].toUpperCase()+op.slice(1)}</button>`).join('')}`;
  tools.querySelectorAll('button').forEach(n => {
    n.disabled = n.dataset.sectionOp === 'paste' ? tlSectionClipboard?.project_id !== TL.pid : !bounds;
  });
  tools.querySelectorAll('[data-section-op]').forEach(n => n.onclick = () => tlSectionSave(n.dataset.sectionOp));
  tools.onpointerdown = e => e.stopPropagation();
  tools.querySelectorAll('[data-section-dir]').forEach(n => n.onclick = () => tlSectionNudge(+n.dataset.sectionDir));
  tools.querySelector('[data-section-delete]').onclick = () => tlSectionSave('delete');
  track.querySelector('.tl-ruler').append(tools);
  tlSectionPositionTools();
}

function tlSectionPositionTools() {
  const sc = $('#tl-scroll'), tools = $('#tl-track')?.querySelector('.tl-section-tools');
  const bounds = tlSectionBounds();
  if (!sc || !tools) return;
  tools.style.maxWidth = `${Math.max(0, sc.clientWidth-8)}px`;
  // The ruler starts after the 104px lane headers; scrollLeft is track-relative.
  const lo = sc.scrollLeft-104+4, hi = lo+sc.clientWidth-8-tools.offsetWidth;
  tools.style.left = `${Math.max(lo, Math.min((bounds?.a ?? TL.cur)*TL.zoom, hi))}px`;
}

function tlSectionNudge(dir) {
  const rows = tlParas(), ids = TL.section.ids, start = rows.findIndex(q => q.id === ids[0]);
  const end = start+ids.length;
  if (dir < 0 && start > 0) tlSectionSave('move', rows[start-1].id);
  if (dir > 0 && end < rows.length) tlSectionSave('move', rows[end+1]?.id || '');
}

function tlSectionSave(op, to = '') {
  const pid = TL.pid, section = TL.section && JSON.parse(JSON.stringify(TL.section));
  if (op === 'paste' ? tlSectionClipboard?.project_id !== pid : !section) return;
  const clipboard = op === 'paste' ? JSON.parse(JSON.stringify(tlSectionClipboard)) : null;
  tlInspectorQueue = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    try {
      tlPause();
      const destination = op === 'paste' ? tlSectionPoint(TL.cur)?.id || '' : to;
      const payload = op === 'paste' ? {version:state.project.updated_at, clipboard} : section;
      const project = await api(`/api/projects/${pid}/sections`, {method:'POST',
        body:JSON.stringify({op, ...payload, to:destination}), editLabel:`${op} section`, editGesture:crypto.randomUUID()});
      if (TL.pid !== pid || state.project?.id !== pid) return;
      const hint = project.section_hint; delete project.section_hint;
      const copied = project.section_clipboard; delete project.section_clipboard;
      if (copied) tlSectionClipboard = JSON.parse(JSON.stringify(copied));
      if (op === 'copy') { tlSectionPaint(); tlMsg('Section copied. Paste at the playhead.'); return; }
      state.project = project; TL.section = null; TL.sectionAnchor = null;
      await tlRefresh();
      if (op === 'move') tlSectionSet(section.ids[0], section.ids.at(-1));
      tlInspector(); if (hint) tlMsg(hint);
    } catch (error) {
      if (TL.pid !== pid) return;
      TL.section = null;
      try {
        const fresh = await api(`/api/projects/${pid}`);
        if (TL.pid !== pid) return;
        state.project = fresh; await tlRefresh();
      } catch { tlDraw(); }
      tlInspector(); tlMsg(error.message);
    }
  });
}

function tlSectionKey(e) {
  if (state.project.kind === 'clip' || e.target?.isContentEditable
      || e.target?.closest?.('input, textarea, select, [contenteditable]')) return false;
  const key = e.key.toLowerCase(), rows = tlParas();
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && ['x','c','v','d'].includes(key)) {
    const op = {x:'cut', c:'copy', v:'paste', d:'duplicate'}[key];
    if (op === 'paste' ? tlSectionClipboard?.project_id !== TL.pid : !TL.section) return false;
    tlSectionSave(op); return true;
  }
  if (!rows.length) return false;
  if ((e.ctrlKey || e.metaKey) && key === 'a') tlSectionSet(rows[0].id, rows.at(-1).id);
  else if (e.ctrlKey || e.metaKey) return false;
  else if (e.altKey && TL.section && ['ArrowLeft','ArrowRight'].includes(e.key)) tlSectionNudge(e.key === 'ArrowLeft' ? -1 : 1);
  else if (e.altKey) return false;
  else if (TL.section && ['Delete','Backspace'].includes(e.key)) tlSectionSave('delete');
  else if (['i','o'].includes(key)) {
    if (e.target.closest('.tl-camera-source')) return false;
    TL.sectionMarks ||= {}; TL.sectionMarks[key] = TL.cur;
    tlMsg(`${key.toUpperCase()} marked at ${tlClock(TL.cur)} · X selects the section.`);
  } else if (key === 'x' && TL.sectionMarks?.i != null && TL.sectionMarks?.o != null) {
    const {i,o} = TL.sectionMarks, nearest = t => tlSectionPoint(t).index;
    const a = nearest(Math.min(i,o)), b = nearest(Math.max(i,o));
    const lo = Math.min(a,rows.length-1), hi = Math.min(rows.length-1, Math.max(lo,b-1));
    tlSectionSet(rows[lo].id, rows[hi].id);
  } else return false;
  return true;
}

function tlSectionPoint(t, exclude = []) {
  const rows = tlParas(), points = rows.map((q,index) => ({t:q.start, id:q.id, index}));
  const last = rows.at(-1);
  if (!last) return null;
  points.push({t:tlSectionEnd(), id:'', index:rows.length});
  return points.filter(p => !exclude.includes(p.id)).reduce((a,b) => Math.abs(a.t-t) <= Math.abs(b.t-t) ? a : b);
}

// Shift makes ranges; only an already-selected section can be moved.
function tlSectionPointer(e) {
  if (state.project.kind === 'clip' || e.button !== 0 || TL.drag || e.ctrlKey || e.metaKey) return false;
  if (e.target.closest('.tl-playhead-handle')) return false;
  const track = $('#tl-track'), ruler = e.target.closest('.tl-ruler');
  if (ruler && !e.shiftKey) return false; // Plain ruler drags scrub live.
  const node = e.target.closest('[data-para], [data-seg]');
  const item = node && tlItemForNode(node);
  if (!ruler && !['paragraph','picture'].includes(item?.kind)) return false;
  const rows = tlParas(), time = ev => (ev.clientX-track.getBoundingClientRect().left-104)/TL.zoom;
  if (!rows.length) return false;
  const initialTime = time(e), sectionBefore = TL.section;
  const before = {selection:TL.selection, selections:TL.selections, anchor:TL.sectionAnchor};
  const itemId = item?.kind === 'picture' ? (rows.find(q => initialTime >= q.start
    && initialTime < q.start+q.duration)?.id || item.sid) : item?.sid;
  const anchor = TL.sectionAnchor || TL.selection?.sid;
  const range = e.shiftKey;
  if (!range && !TL.section?.ids.includes(itemId)) return false;
  let moved = false, to = '', ghost, geometry;
  tlPause(); track.setPointerCapture(e.pointerId);
  TL.drag = {section:true};
  const move = ev => {
    if (!moved && Math.abs(ev.clientX-e.clientX) < 6) return;
    moved = true;
    if (range) {
      const a = !ruler && anchor ? rows.findIndex(q => q.id === anchor) : tlSectionPoint(initialTime).index;
      const b = tlSectionPoint(time(ev)).index;
      const lo = Math.min(a,b,rows.length-1), hi = Math.min(rows.length-1, Math.max(lo, Math.max(a,b)-(ruler ? 1 : 0)));
      tlSectionSet(rows[lo].id, rows[hi].id);
      return;
    }
    const bounds = tlSectionBounds(), length = bounds.b-bounds.a;
    if (!ghost) {
      geometry = [...track.querySelectorAll('[data-seg], [data-para], [data-layer], [data-gap]')]
        .map(n => ({n, left:n.style.left, opacity:n.style.opacity}));
      ghost = document.createElement('div'); ghost.className = 'tl-section-ghost';
      ghost.inert = true; ghost.setAttribute('aria-hidden', 'true');
      ghost.style.top = `${track.querySelector('.tl-ruler').offsetHeight}px`;
      ghost.style.width = `${length*TL.zoom}px`;
      const lanes = document.createElement('div'); lanes.style.marginLeft = `${-bounds.a*TL.zoom}px`;
      track.querySelectorAll('.tl-lane').forEach(lane => {
        const contents = lane.cloneNode(true);
        contents.querySelectorAll('.tl-layer-label, em').forEach(n => n.remove());
        lanes.append(contents);
      });
      ghost.append(lanes); track.append(ghost);
    }
    const point = tlSectionPoint(bounds.a+time(ev)-initialTime, TL.section.ids);
    to = point.id;
    const landing = point.t >= bounds.b ? point.t-length : point.t;
    ghost.style.left = `${104+(bounds.a+time(ev)-initialTime)*TL.zoom}px`;
    for (const g of geometry) {
      const t = parseFloat(g.left)/TL.zoom;
      if (t >= bounds.a-.001 && t < bounds.b-.001) { g.n.style.opacity = '.2'; continue; }
      const closed = t >= bounds.b ? t-length : t;
      g.n.style.left = `${(closed >= landing-.001 ? closed+length : closed)*TL.zoom}px`;
    }
    const band = track.querySelector('.tl-section');
    band.style.left = `${104+landing*TL.zoom}px`;
    tlMsg(`Drop at ${tlClock(point.t)} · reorders the script. Escape cancels.`);
  };
  const finish = cancel => {
    document.removeEventListener('keydown', key, true);
    track.removeEventListener('pointermove', move); track.removeEventListener('pointerup', up);
    track.removeEventListener('pointercancel', abort); track.removeEventListener('lostpointercapture', abort);
    if (track.hasPointerCapture(e.pointerId)) track.releasePointerCapture(e.pointerId);
    TL.drag = null; ghost?.remove();
    geometry?.forEach(g => { g.n.style.left = g.left; g.n.style.opacity = g.opacity; });
    if (cancel) { TL.section = sectionBefore; TL.selection = before.selection; TL.selections = before.selections;
      TL.sectionAnchor = before.anchor; tlInspector(); tlSelectionPaint(); tlSectionPaint(); }
    else if (moved && !range) tlSectionSave('move', to);
    else if (!moved && e.shiftKey && anchor && itemId) tlSectionSet(anchor, itemId);
    else if (!moved) { if (item) tlSelect(item); tlSeek(initialTime); }
  };
  const key = ev => { if (ev.key === 'Escape') {ev.preventDefault(); ev.stopImmediatePropagation(); finish(true);} };
  const up = ev => {move(ev); finish(false);}, abort = () => finish(true);
  track.addEventListener('pointermove', move); track.addEventListener('pointerup', up);
  track.addEventListener('pointercancel', abort); track.addEventListener('lostpointercapture', abort);
  document.addEventListener('keydown', key, true);
  return true;
}

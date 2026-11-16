// View preferences never enter project history; content gestures save once.
const tlSameItem = (a, b) => !!a && !!b && a.kind === b.kind && a.id === b.id && a.sid === b.sid;
const tlMovable = s => ['title', 'cue', 'overlay'].includes(tlTimingKind(s));
const tlDeletable = s => tlMovable(s) || s.kind === 'chapter';

function tlZoomAt(zoom, time = TL.cur, pointer = null) {
  const sc = $('#tl-scroll');
  if (!sc || !TL.data || TL.drag) return;
  const anchor = pointer ?? (104 + time * TL.zoom - sc.scrollLeft);
  TL.zoom = Math.max(.01, Math.min(240, zoom));
  TL.zoomReady = true;
  TL.zooming = true; tlDraw(); TL.zooming = false;
  sc.scrollLeft = Math.max(0, 104 + time * TL.zoom - anchor);
  $('#tl-zoom').value = TL.zoom;
  try { localStorage.setItem(`corkbored-timeline-zoom:${TL.pid}`, String(TL.zoom)); } catch { /* private storage */ }
}

function tlFit() {
  if (!TL.data) return;
  tlZoomAt(($('#tl-scroll').clientWidth - 128) / Math.max(.01, TL.data.total), 0, 104);
}

function tlRestoreZoom() {
  let saved;
  try { saved = Number(localStorage.getItem(`corkbored-timeline-zoom:${TL.pid}`)); } catch { /* fit */ }
  TL.zoom = saved > 0 && Number.isFinite(saved) ? Math.max(.01, Math.min(240, saved))
    : Math.max(.01, Math.min(240, ($('#tl-scroll').clientWidth - 128) / Math.max(.01, TL.data.total)));
  TL.zoomReady = true;
  $('#tl-zoom').value = TL.zoom;
}

function tlWireZoom() {
  const sc = $('#tl-scroll');
  sc.addEventListener('wheel', e => {
    if (!TL.data || TL.drag) return;
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const x = Math.max(104, e.clientX - sc.getBoundingClientRect().left);
      const t = Math.max(0, (sc.scrollLeft + x - 104) / TL.zoom);
      const delta = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? sc.clientWidth : 1);
      tlZoomAt(TL.zoom * Math.exp(-delta * .002), t, x);
    } else if (sc.scrollWidth > sc.clientWidth) {
      e.preventDefault();
      sc.scrollLeft += (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY)
        * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? sc.clientWidth : 1);
    }
  }, {passive:false});
  $('#tl-track').addEventListener('pointermove', e => {
    const t = Math.max(0, Math.min(TL.data?.total || 0,
      (e.clientX - $('#tl-track').getBoundingClientRect().left - 104) / TL.zoom));
    const node = e.target.closest('[data-layer], [data-seg], [data-para]');
    const item = node && tlItemForNode(node);
    $('#tl-hover').textContent = `${tlClock(t)}${item ? ' · ' + (item.text || node.title || item.kind) : ''}`;
  });
}

function tlWireLaneCollapse() {
  $('#tl-track').querySelectorAll('.tl-lane').forEach(lane => {
    const label = lane.querySelector('.tl-layer-label, em');
    if (!label) return;
    const key = lane.dataset.track || label.textContent;
    const name = lane.querySelector('.tl-layer-name')?.textContent || label.textContent;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'tl-collapse';
    const apply = () => {
      const collapsed = !!TL.collapsed[key];
      lane.classList.toggle('collapsed', collapsed);
      button.textContent = collapsed ? '▸' : '▾';
      button.setAttribute('aria-label', `${collapsed ? 'Expand' : 'Collapse'} ${name}`);
      button.setAttribute('aria-expanded', String(!collapsed));
    };
    button.onpointerdown = e => e.stopPropagation();
    button.onclick = e => { e.stopPropagation(); TL.collapsed[key] = !TL.collapsed[key]; apply(); };
    label.prepend(button); apply();
  });
}

function tlItemForNode(el) {
  if (el.dataset.layer) return TL.data.layers[el.dataset.layer][+el.dataset.item];
  if (el.dataset.para) return tlItems('paragraph').find(s => s.id === el.dataset.para);
  const seg = tlSegs()[+el.dataset.seg];
  const kind = seg.type === 'picture' ? 'picture' : seg.type === 'sponsor' ? 'sponsor' : 'slate';
  return tlItems(kind).find(s => s.id === (seg.sponsor || seg.ref));
}

function tlReconcileSelection() {
  if (TL.sectionAnchor && !tlParas().some(q => q.id === TL.sectionAnchor)) TL.sectionAnchor = null;
  if (TL.section && (TL.section.version !== state.project.updated_at
      || TL.section.ids.some(id => !tlParas().some(q => q.id === id)))) TL.section = null;
  TL.selections = (TL.selections || []).flatMap(s => {
    const next = tlItems(s.kind).find(n => tlSameItem(n, s));
    return next ? [next] : [];
  });
  TL.selection = TL.selections.at(-1) || null;
}

function tlMarquee(e) {
  const track = $('#tl-track'), rect = track.getBoundingClientRect();
  const x = e.clientX - rect.left, y = e.clientY - rect.top;
  const before = [...(TL.selections || [])], base = e.shiftKey ? before : [];
  const section = TL.section; TL.section = null;
  if (typeof tlSectionPaint === 'function') tlSectionPaint();
  const box = document.createElement('div'); box.className = 'tl-marquee'; track.append(box);
  track.setPointerCapture(e.pointerId);
  tlPause();
  const move = ev => {
    const a = Math.min(x, ev.clientX - rect.left), b = Math.max(x, ev.clientX - rect.left);
    const c = Math.min(y, ev.clientY - rect.top), d = Math.max(y, ev.clientY - rect.top);
    Object.assign(box.style, {left:`${a}px`, top:`${c}px`, width:`${b-a}px`, height:`${d-c}px`});
    const hits = [...track.querySelectorAll('[data-layer], [data-para], [data-seg]')].filter(node => {
      const r = node.getBoundingClientRect();
      return !node.closest('.collapsed') && r.width && r.height && r.left-rect.left < b && r.right-rect.left > a
        && r.top-rect.top < d && r.bottom-rect.top > c;
    }).map(tlItemForNode).filter(Boolean);
    TL.selections = [...base, ...hits.filter(s => !base.some(n => tlSameItem(n, s)))];
    TL.selection = TL.selections.at(-1) || null; tlSelectionPaint();
  };
  const finish = cancel => {
    document.removeEventListener('keydown', key, true);
    track.removeEventListener('pointermove', move); track.removeEventListener('pointerup', up);
    track.removeEventListener('pointercancel', abort); track.removeEventListener('lostpointercapture', abort);
    if (track.hasPointerCapture(e.pointerId)) track.releasePointerCapture(e.pointerId);
    box.remove(); TL.drag = null;
    if (cancel) { TL.selections = before; TL.selection = before.at(-1) || null; TL.section = section; }
    if (typeof tlSectionPaint === 'function') tlSectionPaint();
    tlInspector(); tlSelectionPaint();
  };
  const key = ev => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopImmediatePropagation(); finish(true); } };
  const up = ev => { move(ev); finish(false); }, abort = () => finish(true);
  TL.drag = {marquee:true};
  track.addEventListener('pointermove', move); track.addEventListener('pointerup', up);
  track.addEventListener('pointercancel', abort); track.addEventListener('lostpointercapture', abort);
  document.addEventListener('keydown', key, true);
}

// Clamp a shared delta once, so items retain their relative spacing.
function tlGroupDelta(items, delta) {
  let lo = -Infinity, hi = Infinity;
  for (const s of items) {
    const q = tlParas().find(q => q.id === s.sid);
    if (!q) return 0;
    lo = Math.max(lo, q.start - s.t0);
    hi = Math.min(hi, q.start + (s.kind === 'overlay' ? Math.max(0, q.duration - (s.t1-s.t0)) : q.spoken) - s.t0);
  }
  return Math.max(lo, Math.min(hi, delta));
}

function tlGroupMove(items, requested) {
  const delta = tlGroupDelta(items, requested);
  if (Math.abs(delta - requested) < 1e-6) return {delta, message:''};
  const limit = items.find(s => Math.abs(tlGroupDelta([s], requested) - delta) < 1e-6);
  const name = limit?.text || limit?.kind || 'Item';
  const edge = requested < delta ? 'start' : 'end';
  const message = Math.abs(delta) < 1e-6
    ? `Can't move further: ‘${name}’ is at the ${edge} of its paragraph.`
    : `Moved by ${delta.toFixed(2)} s; ‘${name}’ reaches the ${edge} of its paragraph.`;
  return {delta, message};
}

function tlGroupDrag(e, el, sel) {
  if (typeof tlCanEdit === 'function' && !tlCanEdit(TL.selections?.length ? TL.selections : [sel])) return true;
  const items = [...(TL.selections || [])];
  if (items.length < 2 || !items.some(s => tlSameItem(s, sel)) || e.target.closest('.tl-resize')) return false;
  if (!items.every(tlMovable)) return true;
  tlPause();
  const track = $('#tl-track'), x = e.clientX;
  const nodes = [...track.querySelectorAll('[data-layer]')].filter(n => items.some(s => tlSameItem(s, tlItemForNode(n))));
  const lefts = nodes.map(n => n.style.left);
  const guide = document.createElement('div'); guide.className = 'tl-snap-guide'; guide.hidden = true; track.append(guide);
  let requested = 0, moved = false;
  TL.drag = {items}; el.setPointerCapture(e.pointerId);
  const move = ev => {
    if (!moved && Math.abs(ev.clientX-x) < 3) return;
    moved = true;
    const q = tlParas().find(q => q.id === sel.sid);
    const words = sel.kind === 'overlay' ? (q.word_times || []).filter(w => w.src && w.src !== 'est').map(w => ({...w,end:w.start})) : q.word_times || [];
    const snap = tlSnap(sel.t0 + (ev.clientX-x)/TL.zoom, words, tlFps(), 6, TL.zoom, ev.altKey);
    requested = snap.t-sel.t0;
    const delta = tlGroupDelta(items, requested);
    nodes.forEach((n,i) => { n.style.left = `${parseFloat(lefts[i])+delta*TL.zoom}px`; });
    guide.hidden = snap.guide === null || Math.abs(delta-(snap.t-sel.t0)) > .001;
    guide.style.left = `${104+(sel.t0+delta)*TL.zoom}px`;
  };
  const finish = cancel => {
    TL.drag = null; document.removeEventListener('keydown', key, true);
    el.onpointermove = el.onpointerup = el.onpointercancel = el.onlostpointercapture = null;
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    guide.remove();
    if (cancel || !moved) nodes.forEach((n,i) => {n.style.left = lefts[i];});
    else tlGroupSave(items, 'move', requested);
  };
  const key = ev => { if (ev.key === 'Escape') {ev.preventDefault(); ev.stopImmediatePropagation(); finish(true);} };
  el.onpointermove = move; el.onpointerup = ev => {move(ev); finish(false);};
  el.onpointercancel = el.onlostpointercapture = () => finish(true);
  document.addEventListener('keydown', key, true);
  return true;
}

function tlGroupPatches(items, action, delta) {
  const patches = new Map();
  for (const s of [...items].sort((a,b) => (b.cue ?? -1)-(a.cue ?? -1))) {
    const slide = state.project.slides.find(n => n.id === s.sid), q = tlParas().find(n => n.id === s.sid);
    const patch = patches.get(s.sid) || {};
    if (s.kind === 'title') Object.assign(patch, action === 'delete' ? {title:''} : {title_at:s.t0-q.start+delta});
    if (s.kind === 'chapter') patch.chapter = '';
    if (s.kind === 'overlay') {
      patch.overlays = (patch.overlays || slide.overlays).flatMap(o => o.id !== s.id ? [o]
        : action === 'delete' ? [] : [{...o, at:s.t0-q.start+delta, on:'', by:'hand'}]);
    }
    if (s.kind === 'cue') {
      const fmt = pictureKind(slide);
      patch.cues ||= {[fmt]:structuredClone(slide.cues?.[fmt]?.length ? slide.cues[fmt] : q.effective_cues)};
      if (action === 'delete') patch.cues[fmt].splice(s.cue, 1);
      else patch.cues[fmt][s.cue].at = s.t0-q.start+delta;
    }
    patches.set(s.sid, patch);
  }
  if (action === 'delete' && [...patches.values()].some(p => p.cues && Object.values(p.cues).some(c => !c.length)))
    throw new Error('A drawn cut needs a cue. Keep at least one cue in each paragraph.');
  return [...patches].map(([sid, patch]) => ({sid, patch}));
}

function tlGroupSave(items, action, delta = 0) {
  if (typeof tlCanEdit === 'function' && !tlCanEdit(items)) return;
  const pid = TL.pid;
  tlInspectorQueue = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    try {
      const live = items.map(s => tlItems(s.kind).find(n => tlSameItem(n, s))).filter(Boolean);
      if (live.length !== items.length) throw new Error('Selection changed; select the items again.');
      const move = action === 'move' ? tlGroupMove(live, delta) : {delta:0, message:''};
      if (action === 'move' && Math.abs(move.delta) < 1e-6) {
        tlDraw();
        if (move.message) tlMsg(move.message);
        return;
      }
      const edits = tlGroupPatches(live, action, move.delta);
      const project = await api(`/api/projects/${pid}/slides-batch`, {method:'PATCH', body:JSON.stringify({edits}),
        editLabel:`${action} ${items.length} items`, editGesture:crypto.randomUUID()});
      if (TL.pid !== pid || state.project?.id !== pid) return;
      state.project = project;
      if (action === 'delete') tlSelect(null);
      await tlRefresh(); tlInspector();
      if (move.message) tlMsg(move.message);
    } catch (error) { tlMsg(error.message); tlDraw(); }
  });
}

function tlMultiInspector(box) {
  const items = [...TL.selections], move = items.every(tlMovable), remove = items.every(tlDeletable);
  box.innerHTML = `<h3>${items.length} items</h3>${move ? '<label for="tl-multi-offset">Move by (seconds)</label><input id="tl-multi-offset" type="number" value="0" step="0.05"><button type="button" class="btn sm" id="tl-multi-move">Move together</button>' : ''}
    ${remove ? '<button type="button" class="btn sm" id="tl-multi-delete">Delete selected items</button>' : '<p>No shared editable fields. Select titles, cues or graphics to move together.</p>'}`;
  if (move) $('#tl-multi-move').onclick = () => {
    const n = Number($('#tl-multi-offset').value);
    if (Number.isFinite(n)) tlGroupSave(items, 'move', n);
  };
  if (remove) $('#tl-multi-delete').onclick = () => tlGroupSave(items, 'delete');
}

function tlErgonomicsKey(e) {
  if (e.key === '\\' && $('#tl-sources')) tlSourcesToggle();
  else if (e.shiftKey && e.key.toLowerCase() === 'z') tlFit();
  else if (['+', '=', '-', '_'].includes(e.key)) tlZoomAt(TL.zoom * (['+', '='].includes(e.key) ? 1.25 : .8));
  else if (['Delete', 'Backspace'].includes(e.key) && TL.selections?.length) {
    if (TL.selections.every(tlDeletable)) tlGroupSave([...TL.selections], 'delete');
    else tlMsg('This selection includes items that cannot be deleted here.');
  } else if (TL.selections?.length > 1 && ['ArrowLeft', 'ArrowRight'].includes(e.key)) {
    if (TL.selections.every(tlMovable)) tlGroupSave([...TL.selections], 'move', (e.key === 'ArrowLeft' ? -1 : 1)*(e.shiftKey ? 10 : 1)/tlFps());
    else return false;
  } else return false;
  return true;
}

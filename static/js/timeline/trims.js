// Main-track trims are distinct from gap handles and section-body drags.
const tlTrimSources = new Map();
function tlTrimRows(sel) {
  if (state.project.kind === 'clip' || !['picture','paragraph'].includes(sel?.kind)) return [];
  if (sel.kind === 'paragraph') return tlParas().filter(q => q.id === sel.sid);
  return tlSegs().find(s => s.ref === sel.id)?.paragraphs || [];
}
function tlTrimLimit(q, edge) {
  if (!q.insert) return [-q.timing.gap.value, 10-q.timing.gap.value];
  const item = q.insert, length = item.seconds;
  if (item.kind !== 'clip') return [.05-length, Infinity];
  const source = tlTrimSources.get(`${item.shoot_id}/${item.source_id}`);
  return [.05-length, edge === 'start' ? item.in_s : (source ?? item.out_s)-item.out_s];
}
function tlTrimPlan(rows, edge, delta, roll) {
  const q = edge === 'start' ? rows[0] : rows.at(-1);
  if (!q || (edge === 'start' && !q.insert)) return {hint:'Speech cannot be trimmed. Use the razor to split it.'};
  if (edge === 'slip') {
    if (q.insert?.kind !== 'clip') return {hint:'Only clip inserts can slip.'};
    const item = q.insert, source = tlTrimSources.get(`${item.shoot_id}/${item.source_id}`) ?? item.out_s;
    delta = Math.max(-item.in_s, Math.min(source-item.out_s, delta));
    return {q, edge, delta, roll:false, changes:[]};
  }
  let [lo,hi] = tlTrimLimit(q, edge), neighbour;
  if (roll) {
    const all = tlParas(), i = all.findIndex(p => p.id === q.id);
    neighbour = all[i+(edge === 'end' ? 1 : -1)];
    if (!neighbour) return {hint:'No neighbour for a roll edit.'};
    const a = edge === 'end' ? q : neighbour, b = edge === 'end' ? neighbour : q;
    if (Math.abs(a.start+a.duration-b.start) > .002) return {hint:'Cannot roll across a sponsor read.'};
    const [nlo,nhi] = tlTrimLimit(neighbour, edge === 'end' ? 'start' : 'end');
    lo = Math.max(lo,-nhi); hi = Math.min(hi,-nlo);
  }
  const wanted = delta;
  delta = Math.max(lo, Math.min(hi, delta));
  const changes = [{q, delta}];
  if (neighbour) changes.push({q:neighbour, delta:-delta});
  return {q, edge, delta, roll, changes, hint:wanted < lo && !q.insert
    ? 'Speech protected · use the razor to split it.' : ''};
}
function tlTrimSave(plan, version = state.project.updated_at) {
  if (!plan.q || Math.abs(plan.delta) < .000001) return;
  if (typeof tlCanEdit === 'function' && !tlCanEdit([], (plan.changes?.length ? plan.changes.map(c => c.q) : [plan.q])
      .map(q => q.insert ? 'pictures' : 'voice'))) return;
  const pid = TL.pid, gesture = crypto.randomUUID();
  tlInspectorQueue = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    try {
      tlPause();
      const project = await api(`/api/projects/${pid}/trim`, {method:'PATCH',
        body:JSON.stringify({sid:plan.q.id, edge:plan.edge, delta:plan.delta, roll:plan.roll, version}),
        editLabel:plan.edge === 'slip' ? 'slip clip' : plan.roll ? 'roll trim' : 'ripple trim', editGesture:gesture});
      if (TL.pid !== pid || state.project?.id !== pid) return;
      state.project = project; TL.mixFailed = false;
      await tlRefresh(); tlInspector();
    } catch (error) {
      if (TL.pid !== pid) return;
      try { state.project = await api(`/api/projects/${pid}`); await tlRefresh(); } catch { tlDraw(); }
      tlMsg(error.message);
    }
  });
}
function tlWireTrims() {
  const track = $('#tl-track');
  if (state.project.kind === 'clip') return;
  tlParas().filter(q => q.insert?.kind === 'clip').forEach(q => {
    const item = q.insert, key = `${item.shoot_id}/${item.source_id}`;
    if (tlTrimSources.has(key)) return;
    tlTrimSources.set(key, null);
    api(`/api/footage/shoots/${encodeURIComponent(item.shoot_id)}`).then(shoot => {
      tlTrimSources.set(key, shoot.files.find(f => f.id === item.source_id)?.duration ?? null);
    }).catch(() => tlTrimSources.delete(key));
  });
  track.querySelectorAll('.tl-pictures [data-seg]').forEach(node => {
    const seg = tlSegs()[+node.dataset.seg];
    if (seg.type !== 'picture') return;
    const sel = tlItems('picture').find(s => s.id === seg.ref), rows = tlTrimRows(sel);
    for (const edge of rows[0]?.insert ? ['start','end'] : ['end']) {
      const handle = document.createElement('span'); handle.className = `tl-trim-edge ${edge}`;
      handle.dataset.trimEdge = edge; handle.title = `Trim ${edge} · Shift rolls · Alt disables snapping`;
      tlResizeHandle(node, handle);
    }
    node.addEventListener('pointerdown', e => {
      const edge = e.target.closest('[data-trim-edge]')?.dataset.trimEdge;
      if (edge || (e.altKey && rows[0]?.insert?.kind === 'clip')) tlTrimPointer(e, node, sel, rows, edge || 'slip');
    });
    node.addEventListener('click', e => { if (node.trimClick) {node.trimClick = false; e.stopImmediatePropagation();} });
  });
}
function tlTrimPointer(e, node, sel, rows, edge) {
  if (e.button !== 0 || TL.drag || e.ctrlKey || e.metaKey) return;
  e.preventDefault(); e.stopPropagation(); tlPause(); tlSelect(sel);
  const track = $('#tl-track'), version = state.project.updated_at, width = track.style.width;
  const geometry = [...track.querySelectorAll('[data-seg], [data-para], [data-layer], [data-gap], [data-insert-point]')]
    .map(n => ({n, left:n.style.left, width:n.style.width}));
  const guide = document.createElement('div'); guide.className = 'tl-snap-guide'; guide.hidden = true; track.append(guide);
  const base = edge === 'start' ? sel.t0 : sel.t1;
  const length = sel.t1-sel.t0; // Picture bounds also include fixed head/tail pads.
  const drag = {trim:true}; TL.drag = drag; node.trimClick = false; node.setPointerCapture(e.pointerId);
  let moved = false, plan, hint;
  const move = ev => {
    if (!moved && Math.abs(ev.clientX-e.clientX) < 3) return;
    moved = true; node.trimClick = true;
    const raw = (ev.clientX-e.clientX)/TL.zoom;
    const points = [...tlParas().flatMap(q => q.word_times || []),
      ...tlSegs().flatMap(s => [{start:s.start,end:s.start+s.duration}]), {start:TL.cur,end:TL.cur}];
    const snap = tlSnap(base+raw, points, tlFps(), 6, TL.zoom, ev.altKey);
    plan = tlTrimPlan(rows, edge, edge === 'slip' ? raw : (snap.t-base)*(edge === 'start' ? -1 : 1), ev.shiftKey || TL.trimRoll);
    if (!plan.q) {tlMsg(plan.hint); return;}
    const map = t => t+plan.changes.reduce((sum,c) => {
      const end = c.q.start+c.q.duration, start = c.q.insert ? c.q.start : end-c.q.timing.gap.value;
      return sum+(t >= end-.000001 ? c.delta : t > start && end > start ? c.delta*(t-start)/(end-start) : 0);
    },0);
    for (const g of geometry) {
      const a = parseFloat(g.left)/TL.zoom, w = parseFloat(g.width);
      g.n.style.left = `${map(a)*TL.zoom}px`;
      if (w) g.n.style.width = `${Math.max(2,(map(a+(w+2)/TL.zoom)-map(a))*TL.zoom-2)}px`;
    }
    const shift = plan.changes.reduce((sum,c) => sum+c.delta,0);
    track.style.width = `${Math.ceil((TL.data.total+shift)*TL.zoom)+24}px`;
    const target = base+plan.delta*(edge === 'start' ? -1 : 1);
    guide.hidden = edge === 'slip' || snap.guide === null || Math.abs(target-snap.t) > .001;
    guide.style.left = `${104+target*TL.zoom}px`;
    (hint ||= tlTrackHint(track)).show(`${(length+(edge === 'slip' ? 0 : plan.delta)).toFixed(2)} s, ${plan.delta >= 0 ? '+' : ''}${plan.delta.toFixed(2)}${edge === 'slip' ? ' source' : ''} · ${plan.hint || (plan.roll ? 'Roll' : 'Ripple')}`, target);
  };
  const finish = cancel => {
    if (TL.drag !== drag) return;
    TL.drag = null;
    document.removeEventListener('keydown', key, true);
    node.onpointermove = node.onpointerup = node.onpointercancel = node.onlostpointercapture = null;
    if (node.hasPointerCapture(e.pointerId)) node.releasePointerCapture(e.pointerId);
    guide.remove(); hint?.remove();
    geometry.forEach(g => {g.n.style.left = g.left; g.n.style.width = g.width;}); track.style.width = width;
    if (!cancel && moved && plan?.q) tlTrimSave(plan, version);
  };
  const key = ev => {if (ev.key === 'Escape') {ev.preventDefault(); ev.stopImmediatePropagation(); finish(true);}};
  node.onpointermove = move; node.onpointerup = ev => {move(ev); finish(false);};
  node.onpointercancel = node.onlostpointercapture = () => finish(true);
  document.addEventListener('keydown', key, true);
}
function tlTrimKey(e) {
  if (TL.drag) return false;
  if (e.ctrlKey || e.metaKey || e.altKey || e.target?.isContentEditable
      || e.target?.closest?.('input, textarea, select, [contenteditable], [role="textbox"]')) return false;
  const start = ['[','{'].includes(e.key), end = [']','}'].includes(e.key);
  if (!start && !end) return false;
  if (TL.section || TL.selections?.length !== 1) return false;
  const rows = tlTrimRows(TL.selection);
  if (!rows.length) return false;
  const base = start ? TL.selection.t0 : TL.selection.t1;
  const delta = e.shiftKey ? (start ? -1 : 1)/tlFps() : (TL.cur-base)*(start ? -1 : 1);
  const plan = tlTrimPlan(rows,start ? 'start' : 'end',delta,!!TL.trimRoll);
  if (plan.hint) tlMsg(plan.hint);
  tlTrimSave(plan); return true;
}

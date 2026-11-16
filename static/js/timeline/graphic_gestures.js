// Separate from paragraph timing drags: graphics may cross paragraph boundaries.
function tlWireGraphics() {
  const track = $('#tl-track');
  const lanes = [...track.querySelectorAll('[data-role="graphics"]')];
  // An empty project has no Graphics lane. The Add graphic button stays a
  // drop target; main-track drops still insert full-frame blocks as before.
  const add = $('#tl-add-graphic');
  if (add && state.project.kind !== 'clip') lanes.push(add);
  lanes.forEach(lane => {
    lane.ondragover = e => {
      if (TL.insertDrag?.pid !== TL.pid || TL.insertDrag.payload.kind !== 'block') return;
      if (TL.data?.project_layers?.find(row => row.id === lane.dataset.track)?.locked) {
        TL.graphicDrop = null; e.dataTransfer.dropEffect = 'none'; return;
      }
      e.preventDefault(); e.stopPropagation(); tlInsertClearGhost();
      const t = lane === add ? TL.cur : (e.clientX-track.getBoundingClientRect().left-104)/TL.zoom;
      try {
        tlGraphicTarget(t);
        const b = tlGraphicBlocks?.find(b => b.ref === TL.insertDrag.payload.block);
        if (!b?.overlay) throw Error();
        e.dataTransfer.dropEffect = 'copy'; TL.graphicDrop = t;
        const ghost = document.createElement('div'); ghost.className = 'tl-insert-ghost';
        ghost.style.left = `${t*TL.zoom}px`; ghost.style.width = `${Math.min(4,b.overlay.max_dur)*TL.zoom}px`;
        ghost.textContent = 'Graphic';
        (lane === add ? track.querySelector('.tl-pictures') : lane).append(ghost);
      } catch { TL.graphicDrop = null; e.dataTransfer.dropEffect = 'none'; }
    };
    lane.ondragleave = e => { if (!lane.contains(e.relatedTarget)) { TL.graphicDrop = null; tlInsertClearGhost(); } };
    lane.ondrop = e => {
      if (TL.insertDrag?.pid !== TL.pid || TL.graphicDrop == null) return;
      e.preventDefault(); e.stopPropagation();
      const {payload} = TL.insertDrag, t = TL.graphicDrop;
      TL.insertDrag = null; TL.graphicDrop = null; tlInsertClearGhost(); tlGraphicDrop(payload,t,lane.dataset.track || '');
    };
  });
  track.querySelectorAll('[data-layer="graphics"]').forEach(node => {
    node.classList.add('editable');
    const sel = tlItemForNode(node), click = node.onclick;
    for (const edge of ['start','end']) {
      const handle = document.createElement('span'); handle.className = `tl-resize ${edge === 'start' ? 'left' : ''}`;
      handle.dataset.graphicEdge = edge; handle.title = `Resize graphic ${edge} · Alt disables snapping`; node.append(handle);
    }
    node.onpointerdown = e => {
      e.stopPropagation();
      if (e.button !== 0 || TL.drag) return;
      node.graphicClick = false;
      if (e.shiftKey || e.ctrlKey || e.metaKey) return;
      if (tlGroupDrag(e,node,sel)) { node.graphicClick = true; return; }
      tlGraphicPointer(e,node,sel,e.target.closest('[data-graphic-edge]')?.dataset.graphicEdge || 'move');
    };
    node.onclick = e => { e.stopPropagation(); if (node.graphicClick) node.graphicClick = false; else click?.(e); };
  });
}
function tlGraphicPointer(e, node, sel, edge) {
  e.preventDefault(); tlPause(); tlSelect(sel);
  const track = $('#tl-track'), q = tlParas().find(q => q.id === sel.sid), item = tlGraphic(sel);
  const left = node.style.left, width = node.style.width, base = edge === 'end' ? sel.t1 : sel.t0;
  const guide = document.createElement('div'); guide.className = 'tl-snap-guide'; guide.hidden = true; track.append(guide);
  const hint = tlTrackHint(track), drag = {graphic:true}; TL.drag = drag; node.graphicClick = false;
  node.setPointerCapture(e.pointerId);
  let moved = false, patch, destination;
  const move = ev => {
    if (!moved && Math.max(Math.abs(ev.clientX-e.clientX), Math.abs((ev.clientY || 0)-(e.clientY || 0))) < 3) return;
    moved = true; node.graphicClick = true;
    destination = edge === 'move' && [...track.querySelectorAll('[data-role="graphics"]')].find(lane => {
      const r = lane.getBoundingClientRect(); return ev.clientY >= r.top && ev.clientY < r.bottom;
    });
    const points = [...tlParas().flatMap(q => (q.word_times || []).filter(w => w.src && w.src !== 'est')),
      ...tlParas().map(q => ({start:q.start,end:q.start+q.duration})), {start:TL.cur,end:TL.cur}];
    const snap = tlSnap(base+(ev.clientX-e.clientX)/TL.zoom, points, tlFps(),6,TL.zoom,ev.altKey);
    let a = sel.t0, b = sel.t1;
    if (edge === 'move') {
      const rows = tlParas(); a = Math.max(rows[0].start,Math.min(rows.at(-1).start+rows.at(-1).duration-.05,snap.t));
      try { const target = tlGraphicTarget(a), next = rows.find(q => q.id === target.sid); b = Math.min(a+item.dur,next.start+next.duration); patch = {time:a}; }
      catch { patch = null; hint.show('Place graphics inside a picture paragraph.',a); return; }
    } else if (edge === 'start') {
      a = Math.max(q.start,sel.t1-tlGraphicMax(sel),Math.min(sel.t1-.05,snap.t));
      patch = {time:a,dur:sel.t1-a};
    } else {
      b = Math.max(a+.05,Math.min(q.start+q.duration,a+tlGraphicMax(sel),snap.t)); patch = {dur:b-a};
    }
    node.style.left = `${a*TL.zoom}px`; node.style.width = `${Math.max(2,(b-a)*TL.zoom-2)}px`;
    const target = edge === 'end' ? b : a;
    guide.hidden = snap.guide === null || Math.abs(target-snap.t) > .001; guide.style.left = `${104+target*TL.zoom}px`;
    hint.show(`${(b-a).toFixed(2)} s · ${tlClock(a)} → ${tlClock(b)}`,target);
  };
  const finish = cancel => {
    if (TL.drag !== drag) return;
    TL.drag = null; document.removeEventListener('keydown',key,true);
    node.onpointermove = node.onpointerup = node.onpointercancel = node.onlostpointercapture = null;
    if (node.hasPointerCapture(e.pointerId)) node.releasePointerCapture(e.pointerId);
    guide.remove(); hint.remove(); node.style.left = left; node.style.width = width;
    if (!cancel && moved && destination && destination.dataset.track !== node.closest('[data-track]').dataset.track)
      tlLayerRequest({op:'move_item', sid:sel.sid, item:sel.id, to:destination.dataset.track}, '', 'move graphic to layer');
    else if (!cancel && moved && patch) tlGraphicCommand(edge === 'move' ? 'move' : 'resize', [sel], patch);
  };
  const key = ev => { if (ev.key === 'Escape') {ev.preventDefault(); ev.stopImmediatePropagation(); finish(true);} };
  node.onpointermove = move; node.onpointerup = ev => {move(ev); finish(false);};
  node.onpointercancel = node.onlostpointercapture = () => finish(true);
  document.addEventListener('keydown',key,true);
}
function tlGraphicTools() {
  const track = $('#tl-track');
  if (!track) return;
  let tools = track.querySelector('.tl-graphic-tools');
  const items = tlGraphicSelection(), sel = items.at(-1);
  if (!sel || TL.drag) { tools?.remove(); return; }
  if (!tools) {
    tools = document.createElement('div'); tools.className = 'tl-graphic-tools';
    tools.setAttribute('role','toolbar'); tools.setAttribute('aria-label','Graphic commands');
    tools.innerHTML = ['Split','Duplicate','Delete','Replace block'].map(label => `<button type="button" class="btn sm">${label}</button>`).join('');
    tools.onpointerdown = e => e.stopPropagation(); tools.onclick = e => e.stopPropagation(); track.append(tools);
  }
  [...tools.querySelectorAll('button')].forEach((button,i) => {
    button.disabled = [0,3].includes(i) && items.length !== 1;
    button.onclick = () => i === 3 ? tlGraphicReplace(sel) : tlGraphicCommand(['split','duplicate','delete'][i],items,TL.playing ? tlNow() : TL.cur);
  });
  const sc = $('#tl-scroll');
  const lane = [...track.querySelectorAll('[data-role="graphics"]')].find(lane =>
    [...lane.querySelectorAll('[data-layer]')].some(node => tlSameItem(sel, tlItemForNode(node))));
  if (!lane || lane.classList.contains('collapsed')) {tools.remove(); return;}
  tools.style.maxWidth = `${sc.clientWidth-112}px`;
  tools.style.left = `${Math.max(sc.scrollLeft+108,Math.min(104+sel.t0*TL.zoom,sc.scrollLeft+sc.clientWidth-tools.offsetWidth-4))}px`;
  tools.style.top = `${Math.max(track.querySelector('.tl-pictures').offsetTop+4,lane.offsetTop-tools.offsetHeight-4)}px`;
}

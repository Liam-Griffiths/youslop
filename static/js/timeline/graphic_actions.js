// Graphic commands share one atomic batch and undo step, including reattachment.
let tlGraphicClipboard = null;
const tlGraphicSelection = () => !TL.section && TL.selections?.length && TL.selections.every(s => s.kind === 'overlay') ? [...TL.selections] : [];
function tlGraphicTarget(t) {
  const q = tlParas().find(q => q.start <= t && t < q.start+q.duration);
  const slide = state.project.slides.find(s => s.id === q?.id);
  if (!slide || slide.on_camera || isCut(pictureKind(slide))) throw Error('Place graphics inside a picture paragraph.');
  return {sid:q.id, at:t-q.start};
}
function tlGraphicBatch(label, build) {
  const pid = TL.pid;
  const result = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return false;
    try {
      tlPause();
      const patches = new Map(), ids = [];
      const list = sid => {
        if (!patches.has(sid)) patches.set(sid, structuredClone(state.project.slides.find(s => s.id === sid).overlays || []));
        return patches.get(sid);
      };
      build(list, ids);
      const edits = [...patches].map(([sid,overlays]) => ({sid,patch:{overlays}}));
      if (!edits.length) return false;
      const project = await api(`/api/projects/${pid}/slides-batch`, {method:'PATCH', body:JSON.stringify({edits}),
        editLabel:label, editGesture:crypto.randomUUID()});
      if (TL.pid !== pid || state.project?.id !== pid) return false;
      state.project = project; TL.mixFailed = false;
      await tlRefresh(true);
      const selected = tlItems('overlay').filter(s => ids.some(key => key.sid === s.sid && key.id === s.id));
      tlSelect(null); selected.forEach((s,i) => tlSelect(s, i > 0));
      return true;
    } catch (error) { tlMsg(error.message); tlDraw(); return false; }
  });
  tlInspectorQueue = result.then(() => {}); return result;
}
function tlGraphicLive(sel) {
  const live = tlItems('overlay').find(s => s.sid === sel.sid && s.id === sel.id);
  if (!live || !tlGraphic(live)) throw Error('Graphic changed; select it again.');
  return live;
}
function tlGraphicSnapshot(items) {
  const a = Math.min(...items.map(s => s.t0));
  return {pid:TL.pid, items:items.map(s => ({offset:s.t0-a, item:structuredClone(tlGraphic(s))}))};
}
function tlGraphicCommand(action, items = tlGraphicSelection(), value = null) {
  if (action === 'copy') {
    if (items.length) { tlGraphicClipboard = tlGraphicSnapshot(items); tlMsg('Graphics copied.'); }
    return;
  }
  const clipboard = action === 'paste' ? tlGraphicClipboard : null;
  if (action === 'paste' ? clipboard?.pid !== TL.pid : !items.length) return;
  return tlGraphicBatch(`${action} graphic${items.length > 1 ? 's' : ''}`, (list, ids) => {
    const live = action === 'paste' ? [] : items.map(tlGraphicLive);
    if (action === 'paste' || action === 'duplicate') {
      const snapshot = clipboard || tlGraphicSnapshot(live);
      const base = action === 'paste' ? value : Math.max(...live.map(s => s.t1));
      snapshot.items.forEach(({offset,item}) => {
        const target = tlGraphicTarget(base+offset), id = 'graphic-'+crypto.randomUUID();
        list(target.sid).push({...item, at:target.at, id, on:'', by:'hand'}); ids.push({sid:target.sid, id});
      });
      return;
    }
    live.forEach(s => {
      const overlays = list(s.sid), index = overlays.findIndex(o => o.id === s.id), item = overlays[index];
      if (action === 'delete') { overlays.splice(index,1); return; }
      if (action === 'split') {
        if (value-s.t0 < .05 || s.t1-value < .05) throw Error('Place the playhead inside the graphic, away from its edges.');
        const first = value-s.t0, id = 'graphic-'+crypto.randomUUID();
        overlays.splice(index,1,{...item, at:s.t0-tlParas().find(q => q.id === s.sid).start, dur:first, on:'', by:'hand'},
          {...item, id, at:value-tlParas().find(q => q.id === s.sid).start, dur:item.dur-first, on:'', by:'hand'});
        ids.push({sid:s.sid, id}, {sid:s.sid, id:s.id});
      } else {
        const changes = typeof value === 'function' ? value(s,item) : value;
        const target = changes.time === undefined ? {sid:s.sid} : tlGraphicTarget(changes.time);
        const {time, ...patch} = changes;
        if (action === 'replace' && !patch.preset) { delete item.preset; delete patch.preset; }
        const updated = {...item, ...patch, ...(target.at === undefined ? {} : {at:target.at}),
          on:action === 'replace' ? item.on || '' : '', by:'hand'};
        if (target.sid === s.sid) overlays[index] = updated;
        else {
          const destination = list(target.sid);
          if (destination.some(o => o.id === updated.id)) updated.id = 'graphic-'+crypto.randomUUID();
          overlays.splice(index,1); destination.push(updated);
        }
        ids.push({sid:target.sid, id:updated.id});
      }
    });
  });
}
function tlGraphicDrop(payload, t, layer = '') {
  return tlGraphicBatch('add graphic', (list, ids) => {
    const b = tlGraphicBlocks?.find(b => b.ref === payload.block);
    if (!b?.overlay) throw Error('Choose an overlay block to drop on Graphics.');
    const target = tlGraphicTarget(t), id = 'graphic-'+crypto.randomUUID();
    list(target.sid).push({id, block_id:b.ref, vars:payload.vars, at:target.at,
      dur:Math.min(payload.seconds || 4,b.overlay.max_dur), position:b.overlay.position[0], by:'hand',
      ...(layer ? {layer} : {})});
    ids.push({sid:target.sid, id});
  });
}
function tlGraphicCompatible(old, next, values) {
  return Object.fromEntries(Object.entries(next.variables).filter(([key,spec]) => {
    const value = values[key];
    return old.variables[key]?.type === spec.type && value !== undefined
      && (!spec.max_length || value.length <= spec.max_length)
      && (!spec.choices || spec.choices.includes(value))
      && (spec.min === undefined || value >= spec.min) && (spec.max === undefined || value <= spec.max)
      && (spec.type !== 'table' || JSON.stringify(old.variables[key]) === JSON.stringify(spec));
  }).map(([key]) => [key,values[key]]));
}
async function tlGraphicReplace(sel) {
  const p = state.project, item = structuredClone(tlGraphic(sel));
  const old = tlGraphicBlocks?.find(b => b.ref === item.block_id);
  if (!old) return;
  tlPause();
  await renderBlocks(item.block_id, {mode:'pick', project:p.id, channel:p.channel_id, overlay:true, aspect:tlInsertAspect(),
    initialValues:b => tlGraphicCompatible(old,b,item.vars), onUse:async selection => {
      if (state.project?.id !== p.id) return;
      const b = blocksBrowser.items.find(b => b.ref === selection.block);
      if (item.dur > b.overlay.max_dur) throw Error('This block cannot keep the graphic’s duration. Choose another block.');
      if (await tlGraphicCommand('replace', [sel], {block_id:b.ref, vars:selection.vars,
        position:b.overlay.position.includes(item.position) ? item.position : b.overlay.position[0], preset:selection.preset || null})) {
        state.graphicFocus = {pid:p.id,sid:sel.sid,id:sel.id}; await render();
      }
    }});
}
function tlGraphicClipboardKey(e) {
  if (TL.section || TL.drag || e.altKey || e.shiftKey || !(e.ctrlKey || e.metaKey)
      || e.target?.isContentEditable || e.target?.closest?.('input, textarea, select, [contenteditable], [role="textbox"]')) return false;
  const items = tlGraphicSelection(), action = {c:'copy',v:'paste',d:'duplicate'}[e.key.toLowerCase()];
  if (!action || !items.length) return false;
  tlGraphicCommand(action, items, TL.playing ? tlNow() : TL.cur); return true;
}

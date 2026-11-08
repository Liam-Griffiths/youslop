/* Paragraph graphics share the block form and the inspector save queue. */
let tlGraphicBlocks = null;
const tlGraphic = sel => state.project.slides.find(s => s.id === sel.sid)?.overlays?.find(o => o.id === sel.id);
const tlGraphicMax = sel => tlGraphicBlocks?.find(b => b.ref === tlGraphic(sel)?.block_id)?.overlay?.max_dur || 30;

function tlGraphicSave(sel, changes) {
  tlSaveTiming(sel, () => {
    const slide = state.project.slides.find(s => s.id === sel.sid);
    return {overlays:(slide.overlays || []).flatMap(o => o.id !== sel.id ? [o]
      : changes === null ? [] : [{...o, ...(typeof changes === 'function' ? changes(o) : changes), by:'hand'}])};
  });
}

async function tlGraphicInspector(sel, body) {
  try {
    tlGraphicBlocks ||= await api('/api/blocks?overlay=1');
    if (!body.isConnected || TL.selection?.id !== sel.id) return;
    const item = tlGraphic(sel), b = tlGraphicBlocks.find(b => b.ref === item?.block_id);
    if (!b) { body.textContent = 'Overlay block unavailable.'; return; }
    body.innerHTML = `<h3>${esc(b.name)}</h3><form id="graphic-form">
      ${Object.entries(b.variables).map(([key,spec],i) => blockTrialField(key,{...spec,default:item.vars[key] ?? spec.default},i)).join('')}
      <label for="graphic-position">Position</label><select id="graphic-position">${b.overlay.position.map(p => `<option ${p === item.position ? 'selected' : ''}>${p}</option>`).join('')}</select>
      <label for="graphic-at">Start (paragraph seconds)</label><input id="graphic-at" type="number" min="0" step="0.05" value="${(sel.t0 - tlParas().find(q => q.id === sel.sid).start).toFixed(3)}">
      <label for="graphic-dur">Duration (seconds)</label><input id="graphic-dur" type="number" min="0.05" max="${b.overlay.max_dur}" step="0.05" value="${item.dur}">
      <label for="graphic-on">On word or phrase (optional)</label><input id="graphic-on" type="text" value="${esc(item.on || '')}">
      <button class="btn sm" type="submit">Save graphic</button></form>
      <button class="btn sm ghost" id="graphic-delete">Delete graphic</button><p role="status" id="graphic-status"></p>`;
    body.querySelectorAll('[data-pick-local]').forEach(button => { button.onclick = () => {
      const input = body.querySelector('#'+button.dataset.pickLocal);
      openLocalMediaPicker(input.dataset.type === 'clip' ? 'video' : 'image', asset => { input.value = `/scene/{token}/library/${asset.id}`; });
    }; });
    body.querySelector('#graphic-at').oninput = () => { body.querySelector('#graphic-on').value = ''; };
    body.querySelector('form').onsubmit = e => {
      e.preventDefault();
      try {
        tlGraphicSave(sel, {vars:readBlockTrial(b,body), position:body.querySelector('#graphic-position').value,
          at:Number(body.querySelector('#graphic-at').value), dur:Number(body.querySelector('#graphic-dur').value),
          on:body.querySelector('#graphic-on').value});
        TL.host.focus();
      } catch (error) { body.querySelector('#graphic-status').textContent = error.message; }
    };
    body.querySelector('#graphic-delete').onclick = () => tlGraphicSave(sel, null);
  } catch (error) { if (body.isConnected) body.textContent = error.message; }
}

async function openGraphicPicker(sid, at = 0) {
  const p = state.project;
  const slide = p.slides.find(s => s.id === sid);
  if (!slide || slide.on_camera || isCut(p.style.format)) return toast('Graphics are available on picture paragraphs.', true);
  tlPause();
  await renderBlocks('', {mode:'pick', project:p.id, slide:sid, channel:p.channel_id, overlay:true, aspect:p.aspect === 'portrait' ? '9:16' : '16:9', onUse:async selection => {
    // Reload before appending so another edit during browsing is kept.
    const fresh = await api(`/api/projects/${p.id}`);
    const member = fresh.slides.find(s => s.id === sid);
    const b = blocksBrowser.items.find(b => b.ref === selection.block);
    const result = await api(`/api/projects/${p.id}/slides/${sid}`, {method:'PATCH', body:JSON.stringify({overlays:[...(member.overlays || []), {
      id:'graphic-'+crypto.randomUUID(), block_id:b.ref, vars:selection.vars, at, dur:Math.min(4,b.overlay.max_dur),
      position:b.overlay.position[0], by:'hand', ...(selection.preset ? {preset:selection.preset} : {})}]})});
    state.project = result.project || await api(`/api/projects/${p.id}`);
    await render();
  }});
}

function openGraphicEdit(sid, id) {
  // Already in Edit (a check's Fix button): the hash would not change, so no
  // route runs; select the graphic directly instead.
  const graphic = TL.host?.isConnected && TL.pid === state.project.id && tlItems('overlay').find(g => g.id === id);
  if (graphic) { tlSelect(graphic); tlSeek(graphic.t0, {ensure:false}); return; }
  state.graphicFocus = {pid:state.project.id, id};
  openVisualEdit(sid);
}

function tlGraphicAdd() {
  const q = [...tlParas()].reverse().find(q => q.start <= TL.cur && TL.cur < q.start + q.duration);
  if (q) openGraphicPicker(q.id, Math.max(0, TL.cur - q.start));
  else tlMsg('Put the playhead inside a paragraph to add a graphic.');
}

function tlGraphicKey(e) {
  if (TL.selection?.kind !== 'overlay') return false;
  const sel = {...TL.selection}, item = tlGraphic(sel);
  if (!item) return false;
  if (e.key === 'Delete' || e.key === 'Backspace') tlGraphicSave(sel, null);
  else if (['ArrowLeft','ArrowRight'].includes(e.key)) {
    const delta = (e.key === 'ArrowLeft' ? -1 : 1) / tlFps();
    const q = tlParas().find(q => q.id === sel.sid);
    tlGraphicSave(sel, o => e.shiftKey ? {dur:Math.max(.05, Math.min(tlGraphicMax(sel), o.dur + delta))}
      : {at:Math.max(0, (o.on ? sel.t0 - q.start : o.at) + delta), on:''});
  } else return false;
  return true;
}

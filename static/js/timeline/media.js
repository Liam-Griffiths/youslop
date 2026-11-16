// Media uses the graphic command queue; edits never request a render.
function tlMediaDrop(payload, time, layer = '') {
  if (!payload) return toast('Choose a source first.', true);
  payload = structuredClone(payload);
  const pid = TL.pid;
  const result = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    try {
      tlPause();
      const target = tlGraphicTarget(time);
      const project = await api(`/api/projects/${pid}/slides/${target.sid}/media-overlay`, {
        method:'POST', body:JSON.stringify({source:payload, at:target.at, layer}),
        editLabel:'place media', editGesture:crypto.randomUUID()});
      if (TL.pid !== pid || state.project?.id !== pid) return;
      state.project = project;
      await tlRefresh(false, true);
      const id = state.project.slides.find(s => s.id === target.sid).overlays.at(-1).id;
      tlSelect(tlItems('media').find(s => s.sid === target.sid && s.id === id));
    } catch (error) { toast(error.message, true); }
  });
  tlInspectorQueue = result.catch(() => {}); return result;
}

const TL_MEDIA_BOXES = {Full:[0,0,1,1], 'Top-right':[.65,.05,.3,.3],
  'Bottom-left':[.05,.65,.3,.3], 'Left half':[0,0,.5,1], 'Right half':[.5,0,.5,1]};
function tlMediaInspector(sel, body) {
  const item = tlGraphic(sel);
  if (!item) return;
  const number = (key, label, value, max = '', min = 0) => `<label for="media-${key}">${label}</label><input class="mono" id="media-${key}" data-media-field="${key}" type="number" min="${min}" max="${max}" step="0.01" value="${value}">`;
  body.innerHTML = `<h3>Media</h3><p class="tl-note">${esc(sel.unavailable || 'Changes appear in the next explicit section preview.')}</p>
    <label for="media-preset">Box preset</label><select id="media-preset"><option value="">Custom</option>${Object.keys(TL_MEDIA_BOXES).map(k => `<option>${k}</option>`).join('')}</select>
    ${'xywh'.split('').map(k => number(k,k.toUpperCase()+' (frame units)',item.box[k],1,k === 'w' || k === 'h' ? .01 : 0)).join('')}
    <label for="media-fit">Fit</label><select id="media-fit"><option ${item.fit === 'cover' ? 'selected' : ''}>cover</option><option ${item.fit === 'contain' ? 'selected' : ''}>contain</option></select>
    ${number('at','Start (paragraph seconds)',item.at)}${number('dur','Duration (seconds)',item.dur,'',.05)}
    ${sel.source_kind === 'video' ? number('in','Source offset (owned clip seconds)',item.in,Math.max(0,sel.source_length-item.dur)) : ''}
    ${number('fade_in','Fade in (seconds)',item.fade_in)}${number('fade_out','Fade out (seconds)',item.fade_out)}${number('volume','Volume (linear, 0–1)',item.volume,1)}
    <button type="button" class="btn sm ghost" data-delete-media>Delete media</button>`;
  body.querySelector('#media-preset').onchange = e => {
    const values = TL_MEDIA_BOXES[e.target.value];
    if (values) tlGraphicCommand('replace',[sel],{box:Object.fromEntries([...'xywh'].map((k,i) => [k,values[i]]))});
  };
  body.querySelector('#media-fit').onchange = e => tlGraphicCommand('replace',[sel],{fit:e.target.value});
  body.querySelectorAll('[data-media-field]').forEach(input => {
    input.onchange = () => {
      if (!input.reportValidity()) return;
      const key = input.dataset.mediaField, value = Number(input.value);
      tlGraphicCommand('replace',[sel],(live, item) => 'xywh'.includes(key)
        ? {box:{...item.box,[key]:value}} : {[key]:value, ...(key === 'at' ? {on:''} : {})});
    };
    input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); input.blur(); } };
  });
  body.querySelector('[data-delete-media]').onclick = () => tlGraphicCommand('delete',[sel]);
  tlItemLayerSelect(sel,body);
}

// Frame-normalized geometry, shared by pointer and keyboard controls.
function tlMediaGeometry(box, corner, dx, dy) {
  const clamp = (n,a,b) => Math.max(a,Math.min(b,n));
  if (!corner) return {...box,x:clamp(box.x+dx,0,1-box.w),y:clamp(box.y+dy,0,1-box.h)};
  const left = corner.includes('w') ? clamp(box.x+dx,0,box.x+box.w-.01) : box.x;
  const top = corner.includes('n') ? clamp(box.y+dy,0,box.y+box.h-.01) : box.y;
  const right = corner.includes('e') ? clamp(box.x+box.w+dx,left+.01,1) : box.x+box.w;
  const bottom = corner.includes('s') ? clamp(box.y+box.h+dy,top+.01,1) : box.y+box.h;
  return {x:left,y:top,w:right-left,h:bottom-top};
}
function tlMediaBox() {
  const stage = $('#tl-stage');
  if (!stage || TL.drag) return;
  let outline = stage.querySelector('.tl-media-box');
  const sel = TL.selections?.length === 1 && TL.selection;
  const item = sel?.kind === 'media' && tlGraphic(sel);
  if (!item || TL.cur < sel.t0 || TL.cur >= sel.t1) { outline?.remove(); return; }
  if (outline?.dataset.id !== item.id) { outline?.remove(); outline = null; }
  const paint = box => { for (const [k,prop] of Object.entries({x:'left',y:'top',w:'width',h:'height'})) outline.style[prop] = `${box[k]*100}%`; };
  if (!outline) {
    outline = document.createElement('div'); outline.className = 'tl-media-box'; outline.dataset.id = item.id;
    outline.tabIndex = 0; outline.setAttribute('role','group'); outline.setAttribute('aria-label','Media box; arrow keys move');
    outline.innerHTML = ['nw','ne','sw','se'].map(c => `<button type="button" class="tl-media-corner ${c}" data-corner="${c}" aria-label="Resize ${c} corner; arrow keys resize"></button>`).join('');
    stage.append(outline);
  }
  paint(item.box);
  outline.onkeydown = e => {
    if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key) || !tlCanEdit([sel])) return;
    e.preventDefault(); e.stopPropagation();
    const step = e.shiftKey ? .1 : .01, corner = e.target.dataset.corner || '';
    tlGraphicCommand('replace',[sel],(live,item) => ({box:tlMediaGeometry(item.box,corner,
      e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0,
      e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0)}));
  };
  outline.onpointerdown = e => {
    if (e.button !== 0 || !tlCanEdit([sel])) return;
    e.preventDefault(); e.stopPropagation(); tlPause();
    const pid = TL.pid, rect = stage.getBoundingClientRect(), corner = e.target.dataset.corner || '';
    const drag = {mediaBox:true}; TL.drag = drag;
    let box = item.box;
    outline.setPointerCapture(e.pointerId);
    outline.onpointermove = ev => { box = tlMediaGeometry(item.box,corner,(ev.clientX-e.clientX)/rect.width,(ev.clientY-e.clientY)/rect.height); paint(box); };
    const finish = cancel => {
      if (TL.drag !== drag) return;
      TL.drag = null; document.removeEventListener('keydown',key,true);
      outline.onpointermove = outline.onpointerup = outline.onpointercancel = outline.onlostpointercapture = null;
      if (outline.hasPointerCapture(e.pointerId)) outline.releasePointerCapture(e.pointerId);
      paint(item.box);
      if (!cancel && TL.pid === pid && JSON.stringify(box) !== JSON.stringify(item.box)) tlGraphicCommand('replace',[sel],{box});
    };
    const key = ev => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopImmediatePropagation(); finish(true); } };
    outline.onpointerup = ev => { outline.onpointermove(ev); finish(false); };
    outline.onpointercancel = outline.onlostpointercapture = () => finish(true);
    document.addEventListener('keydown',key,true);
  };
}

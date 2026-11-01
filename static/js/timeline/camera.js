// Source time stays visible, including removed ranges, so every edit is reversible.
const tlCameraSuggestions = new Map();
function tlCameraRows() {
  return tlParas().filter(q => q.camera_edit).map(q => {
    // Source seconds at the ruler's scale, so pauses read at their real length.
    const c = q.camera_edit, width = Math.max(80, c.duration * TL.zoom);
    const range = (r, i, suggested) => `<button type="button" class="tl-camera-cut ${suggested ? 'suggested' : r.by==='auto' ? 'auto' : ''}"
      data-${suggested ? 'suggestion' : 'cut'}="${i}" style="left:${r.a/c.duration*100}%;width:${(r.b-r.a)/c.duration*100}%"
      title="${suggested ? 'Accept pause' : 'Restore cut'} ${r.a.toFixed(2)}–${r.b.toFixed(2)} seconds"
      aria-label="${suggested ? 'Accept pause' : 'Restore cut'} ${r.a.toFixed(2)}–${r.b.toFixed(2)} seconds">${suggested ? '+' : '×'}</button>`;
    return `<div class="tl-lane tl-camera" data-camera="${esc(q.id)}"><em>camera ${q.index+1} · source</em>
      <div class="tl-camera-source" tabindex="0" role="group" aria-label="Camera source: drag a range then Delete; use I and O to select with keyboard"
        style="left:${q.start*TL.zoom}px;width:${width}px" data-duration="${c.duration}">
        <span>source ${c.duration.toFixed(2)}s · drag a range, then Delete</span>
        ${c.cuts.map((r,i) => range(r,i,false)).join('')}
        ${(tlCameraSuggestions.get(TL.pid+':'+q.id)||[]).map((r,i) => range(r,i,true)).join('')}
        <button type="button" data-trim="start" class="tl-camera-trim start" aria-label="Trim start">[</button>
        <button type="button" data-trim="end" class="tl-camera-trim end" aria-label="Trim end">]</button>
      </div><span class="tl-camera-actions" style="left:${q.start*TL.zoom+width+6}px">
        <button type="button" class="btn sm ghost" data-suggest>Suggest pauses</button><button type="button" class="btn sm ghost" data-accept>Accept all</button>
        <label><input type="checkbox" data-punch ${c.punch ? 'checked' : ''}>Punch</label>
      </span>
      ${(c.overlays||[]).map((o,i)=>`<button class="tl-camera-overlay ${o.by==='auto'?'auto':''}" data-overlay="${i}"
        style="left:${(q.start+o.at)*TL.zoom}px;width:${o.dur*TL.zoom}px" title="Drag / resize · 1 cutaway, 2 PIP, 3 split · P corner · Delete removes">${esc(o.kind)}<span class="tl-resize"></span></button>`).join('')}</div>`;
  }).join('');
}

function tlCameraPatch(c, a, b, trim = '') {
  let cuts = c.cuts.filter(r => !(trim === 'start' && r.a === 0) && !(trim === 'end' && r.b === c.duration));
  if (b > a) cuts = [...cuts, {a, b, by:'hand'}];
  return {camera_cuts:cuts};
}

function tlWireCamera() {
  $('#tl-track').querySelectorAll('[data-camera]').forEach(row => {
    const q = tlParas().find(q => q.id === row.dataset.camera), c = q.camera_edit;
    const source = row.querySelector('.tl-camera-source'), key = TL.pid+':'+q.id;
    const save = patch => { tlCameraSuggestions.delete(key); tlSaveTiming({sid:q.id,id:q.id,kind:'paragraph'}, patch); };
    tlWireCameraOverlays(row, q, save);
    let selection = null, cursor = 0, marker, cancelDrag;
    const paint = () => {
      if (!marker) { marker=document.createElement('i'); marker.className='tl-camera-selection'; source.append(marker); }
      marker.style.left = `${Math.min(...selection)/c.duration*100}%`;
      marker.style.width = `${Math.abs(selection[1]-selection[0])/c.duration*100}%`;
    };
    row.onpointerdown = e => e.stopPropagation();
    row.onclick = e => e.stopPropagation();
    source.onpointerdown = e => {
      if (e.button !== 0 || e.target.closest('[data-cut], [data-suggestion]')) return;
      e.preventDefault(); e.stopPropagation(); tlPause(); source.focus();
      const bounds = source.getBoundingClientRect(), zoom = bounds.width / c.duration;
      const at = ev => Math.max(0, Math.min(c.duration,
        tlSnap((ev.clientX-bounds.left)/zoom, c.words, tlFps(), 6, zoom, ev.altKey).t));
      const trim = e.target.closest('[data-trim]')?.dataset.trim || '';
      const a = at(e); selection=[a,a]; paint();
      source.setPointerCapture(e.pointerId);
      source.onpointermove = ev => { cursor=at(ev); selection=[a,cursor]; paint(); };
      const finish = cancel => {
        cancelDrag=null;
        source.onpointermove=source.onpointerup=source.onpointercancel=source.onlostpointercapture=null;
        if (source.hasPointerCapture(e.pointerId)) source.releasePointerCapture(e.pointerId);
        if (cancel) { selection=null; marker?.remove(); marker=null; }
      };
      cancelDrag=() => finish(true);
      source.onpointercancel=source.onlostpointercapture=() => finish(true);
      source.onpointerup = ev => {
        cursor=at(ev); selection=[a,cursor]; paint(); finish(false);
        if (trim) save(tlCameraPatch(c, trim==='start'?0:cursor, trim==='start'?cursor:c.duration, trim));
      };
    };
    source.onkeydown = e => {
      if (e.target !== source) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') cursor=Math.max(0,Math.min(c.duration,cursor+(e.key==='ArrowLeft'?-1:1)/tlFps()));
      else if (e.key.toLowerCase() === 'i') selection=[cursor,cursor];
      else if (e.key.toLowerCase() === 'o') selection=[selection?.[0]??0,cursor];
      else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selection) save(tlCameraPatch(c, Math.min(...selection), Math.max(...selection)));
      } else if (e.key === 'Escape') { cancelDrag?.(); selection=null; marker?.remove(); marker=null; }
      else return;
      if (selection) paint();
      source.setAttribute('aria-label', `Source cursor ${cursor.toFixed(2)} seconds; I / O select, Delete cuts`);
      e.preventDefault(); e.stopPropagation();
    };
    row.querySelectorAll('[data-trim]').forEach(el => el.onkeydown = e => {
      if (!['ArrowLeft','ArrowRight'].includes(e.key)) return;
      const start=el.dataset.trim==='start';
      const edge=c.cuts.find(r=>start?r.a===0:r.b===c.duration);
      const t=Math.max(0,Math.min(c.duration,(edge?(start?edge.b:edge.a):(start?0:c.duration))
        +(e.key==='ArrowLeft'?-1:1)/tlFps()));
      save(tlCameraPatch(c,start?0:t,start?t:c.duration,start?'start':'end'));
      e.preventDefault(); e.stopPropagation();
    });
    row.querySelectorAll('[data-cut]').forEach(el => el.onclick = () => save({camera_cuts:c.cuts.filter((_,i)=>i!==+el.dataset.cut)}));
    row.querySelectorAll('[data-suggestion]').forEach(el => el.onclick = () => {
      const r = tlCameraSuggestions.get(key)[+el.dataset.suggestion]; save(tlCameraPatch(c,r.a,r.b));
    });
    row.querySelector('[data-suggest]').onclick = async () => {
      const pid=TL.pid;
      try {
        const suggestions=await api(`/api/projects/${pid}/slides/${q.id}/camera-cuts`);
        if (TL.pid!==pid) return;
        tlCameraSuggestions.set(key,suggestions); tlDraw();
        if (!suggestions.length) tlMsg('No internal pauses longer than 0.6 seconds.');
      } catch(e) { tlMsg(e.message); }
    };
    row.querySelector('[data-accept]').onclick = () => save({camera_cuts:[...c.cuts,...(tlCameraSuggestions.get(key)||[]).map(r=>({...r,by:'hand'}))]});
    row.querySelector('[data-punch]').onchange = e => save({camera_punch:e.target.checked});
  });
}

async function tlCameraAuto(sid = '', undo = false, suggest = false) {
  const pid = TL.pid;
  tlPause();
  try {
    const r = await api(`/api/projects/${pid}/camera-auto-edit`, {method:'POST', body:JSON.stringify({sid, undo, suggest})});
    const job = await tlWaitJob(r.job);
    if (TL.pid !== pid) return;
    if (job.state !== 'done') throw Error(job.error);
    if (suggest) {
      const wrap=document.createElement('div'); wrap.className='modal';
      wrap.innerHTML='<div class="modal-box"><strong>Suggested cutaways</strong><ul data-list></ul><button data-apply>Auto-edit · apply this paragraph</button><button data-close>Close</button></div>';
      wrap.querySelector('[data-list]').innerHTML=Object.entries(job.result.proposals).flatMap(([id,items])=>items.map(item=>{
        const candidate=state.project.slides.find(s=>s.id===id)?.candidates.find(c=>c.id===item.candidate_id);
        return `<li>On “${esc(item.on||'')}”: ${esc(candidate?.title||'Unavailable picture')} · ${esc(String(item.dur||3))} s</li>`;
      })).join('') || '<li>No cutaways suggested.</li>';
      wrap.querySelector('[data-apply]').onclick=()=>{wrap.remove();tlCameraAuto(sid);};
      wrap.querySelector('[data-close]').onclick=()=>wrap.remove(); document.body.append(wrap); return;
    }
    await tlRefreshProject();
    const first = tlParas().find(q => job.result.changed.includes(q.id));
    if (first) tlSeek(first.start, {ensure:false});
    tlMsg(`Auto-edit: ${job.result.changed.length} paragraphs changed. Check: ${job.result.check.findings.length} findings.`);
  } catch(e) { tlMsg(e.message); }
}

function tlCameraAdd(sid) {
  const q = tlParas().find(q => q.id === sid), at = Math.max(0, Math.min(q.camera_edit.effective_duration-1/tlFps(), TL.cur-q.start));
  tlModal(() => openMediaSearch(sid, null, async cid => {
    await api(`/api/projects/${TL.pid}/slides/${sid}/camera-overlay-media/${encodeURIComponent(cid)}`, {method:'POST'});
    tlSaveTiming({sid,id:sid,kind:'paragraph'}, {camera_overlays:[...(q.camera_edit.overlays||[]),
      {at,dur:Math.min(3,q.camera_edit.effective_duration-at),kind:'cutaway',source:{candidate_id:cid},by:'hand'}]});
  }));
}

function tlWireCameraOverlays(row, q, save) {
  row.querySelectorAll('[data-overlay]').forEach(el => {
    const index=+el.dataset.overlay, overlays=q.camera_edit.overlays, item=overlays[index];
    const update = patch => save({camera_overlays:overlays.map((o,i)=>i===index?{...o,...patch,by:'hand'}:o)});
    el.onkeydown = e => {
      if (e.key === 'Delete') save({camera_overlays:overlays.filter((_,i)=>i!==index)});
      else if (['1','2','3'].includes(e.key)) update({kind:['cutaway','pip','split'][+e.key-1]});
      else if (e.key.toLowerCase() === 'p') { const corners=['bottom_right','bottom_left','top_left','top_right']; update({position:corners[(corners.indexOf(item.position||'bottom_right')+1)%4]}); }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') update({at:Math.max(0,item.at+(e.key==='ArrowLeft'?-1:1)/tlFps())});
      else return;
      e.preventDefault(); e.stopPropagation();
    };
    el.onpointerdown = e => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation(); tlPause(); el.focus(); el.setPointerCapture(e.pointerId);
      const resize=!!e.target.closest('.tl-resize'), x=e.clientX;
      let value, moved=false;
      el.onpointermove = ev => {
        moved ||= Math.abs(ev.clientX-x)>3;
        const t=tlSnap(q.start+item.at+(resize?item.dur:0)+(ev.clientX-x)/TL.zoom,
          q.word_times||[],tlFps(),6,TL.zoom,ev.altKey).t-q.start;
        value=resize?Math.max(1/tlFps(),Math.min(q.camera_edit.effective_duration-item.at,t-item.at))
          :Math.max(0,Math.min(q.camera_edit.effective_duration-item.dur,t));
        el.style[resize?'width':'left']=`${(resize?value:q.start+value)*TL.zoom}px`;
      };
      const finish=cancel=>{
        el.onpointermove=el.onpointerup=el.onpointercancel=el.onlostpointercapture=null;
        document.removeEventListener('keydown',escape,true);
        if(el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
        if(!cancel && moved) update({[resize?'dur':'at']:value}); else tlDraw();
      };
      const escape=ev=>{if(ev.key==='Escape'){ev.stopPropagation();finish(true);}};
      document.addEventListener('keydown',escape,true);
      el.onpointerup=()=>finish(false); el.onpointercancel=el.onlostpointercapture=()=>finish(true);
    };
  });
}

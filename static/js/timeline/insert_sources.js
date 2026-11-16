const tlInsertAspect = () => ({portrait:'9:16', square:'1:1'}[state.project.aspect] || '16:9');

// Local manifests and Library only. These reads never start analysis or previews.
async function tlInsertSources() {
  const results = await Promise.allSettled([api('/api/footage/shoots'), api('/api/blocks'), api('/api/library')]);
  const [shoots, blocks, assets] = results.map(r => r.status === 'fulfilled' ? r.value : []);
  if (results[1].status === 'fulfilled') tlGraphicBlocks = blocks.filter(b => b.overlay);
  const manifests = await Promise.allSettled(shoots.map(s => api(`/api/footage/shoots/${s.id}`)));
  const items = [];
  manifests.forEach(result => {
    if (result.status !== 'fulfilled') return;
    const shoot = result.value;
    const add = (file,a,b,label) => {
      if (file?.kind !== 'video' || file.error || !(b > a)) return;
      items.push({label, tab:'Materials', payload:{kind:'clip', shoot_id:shoot.id, source_id:file.id, in_s:a, out_s:b, source_audio:false}});
    };
    shoot.clips.filter(c => !c.rejected).forEach(c => add(shoot.files.find(f => f.id === c.file), c.in_s,c.out_s,
      c.title || c.note || `Clip ${c.id}`));
    shoot.files.forEach(f => add(f,0,f.duration,`Source · ${f.source_path?.split('/').at(-1) || f.id}`));
  });
  blocks.filter(b => b.aspects.includes(tlInsertAspect())).sort((a,b) => (b.recent || 0)-(a.recent || 0)).forEach(b => {
    const vars = Object.fromEntries(Object.entries(b.variables).map(([key,spec]) => [key,spec.default]));
    items.push({label:b.name, tab:'Blocks', thumb:b.posters?.[tlInsertAspect()], overlay:!!b.overlay, payload:{kind:'block', block:b.ref, vars, seconds:4}});
  });
  assets.filter(a => ['image','video'].includes(a.kind)).forEach(a => items.push({label:a.title || a.id, tab:'Library', thumb:`/api/library/thumb/${a.id}`,
    payload:{kind:'picture', asset_id:a.id, seconds:4}}));
  if (results.some(r => r.status === 'rejected') || manifests.some(r => r.status === 'rejected'))
    toast('Some sources could not be loaded. Reopen Sources to retry.', true);
  return items;
}

function tlInsertSourceList(box, items, onPick, drag = true) {
  box.innerHTML = items.map((item,i) => `<button type="button" class="btn sm ghost" data-source="${i}" draggable="${drag}">${item.thumb ? `<img src="${esc(item.thumb)}" loading="lazy" alt="">` : ''}<span>${esc(item.label)}</span>${item.meta ? `<small>${esc(item.meta)}</small>` : ''}</button>`).join('')
    || '<p>No sources here. Add footage or files in Library.</p>';
  box.querySelectorAll('[data-source]').forEach(button => {
    const item = items[+button.dataset.source];
    button.onclick = () => onPick(item.payload);
    button.onkeydown = e => {
      const step = {ArrowRight:1, ArrowLeft:-1, ArrowDown:2, ArrowUp:-2}[e.key];
      if (!step && !['Home','End'].includes(e.key)) return;
      e.preventDefault();
      const buttons = [...box.querySelectorAll('[data-source]')], i = buttons.indexOf(button);
      buttons[e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length-1
        : Math.max(0,Math.min(buttons.length-1,i+step))]?.focus();
    };
    if (!drag) return;
    button.ondragstart = e => {
      tlPause(); TL.insertDrag = {pid:TL.pid, payload:structuredClone(item.payload)};
      e.dataTransfer.effectAllowed = 'copy'; e.dataTransfer.setData('text/plain', item.label);
    };
    button.ondragend = () => { TL.insertDrag = null; TL.graphicDrop = null; tlInsertClearGhost(); };
  });
}

function tlInsertPanel() {
  if (state.project.kind === 'clip') return;
  return tlSourcesMount();
}

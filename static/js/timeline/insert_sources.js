const tlInsertAspect = () => ({portrait:'9:16', square:'1:1'}[state.project.aspect] || '16:9');

// Local manifests and Library only. These reads never start analysis or previews.
async function tlInsertSources() {
  const results = await Promise.allSettled([api('/api/footage/shoots'), api('/api/blocks'), api('/api/library')]);
  const [shoots, blocks, assets] = results.map(r => r.status === 'fulfilled' ? r.value : []);
  const manifests = await Promise.allSettled(shoots.map(s => api(`/api/footage/shoots/${s.id}`)));
  const items = [];
  manifests.forEach(result => {
    if (result.status !== 'fulfilled') return;
    const shoot = result.value;
    const add = (file,a,b,label) => {
      if (file?.kind !== 'video' || file.error || !(b > a)) return;
      items.push({label, payload:{kind:'clip', shoot_id:shoot.id, source_id:file.id, in_s:a, out_s:b, source_audio:false}});
    };
    shoot.clips.filter(c => !c.rejected).forEach(c => add(shoot.files.find(f => f.id === c.file), c.in_s,c.out_s,
      c.title || c.note || `Clip ${c.id}`));
    shoot.files.forEach(f => add(f,0,f.duration,`Source · ${f.source_path?.split('/').at(-1) || f.id}`));
  });
  blocks.filter(b => b.aspects.includes(tlInsertAspect())).sort((a,b) => (b.recent || 0)-(a.recent || 0)).forEach(b => {
    const vars = Object.fromEntries(Object.entries(b.variables).map(([key,spec]) => [key,spec.default]));
    items.push({label:b.name, payload:{kind:'block', block:b.ref, vars, seconds:4}});
  });
  assets.filter(a => ['image','video'].includes(a.kind)).forEach(a => items.push({label:a.title || a.id,
    payload:{kind:'picture', asset_id:a.id, seconds:4}}));
  if (results.some(r => r.status === 'rejected') || manifests.some(r => r.status === 'rejected'))
    toast('Some insert sources could not be loaded. Reopen Add to retry.', true);
  return items;
}

function tlInsertSourceList(box, items, onPick, drag = true) {
  box.innerHTML = items.map((item,i) => `<button type="button" class="btn sm ghost" data-source="${i}" draggable="${drag}">${esc(item.label)}</button>`).join('')
    || '<p>No sources here. Add footage or files in Library.</p>';
  box.querySelectorAll('[data-source]').forEach(button => {
    const item = items[+button.dataset.source];
    button.onclick = () => onPick(item.payload);
    if (!drag) return;
    button.ondragstart = e => {
      tlPause(); TL.insertDrag = {pid:TL.pid, payload:structuredClone(item.payload)};
      e.dataTransfer.effectAllowed = 'copy'; e.dataTransfer.setData('text/plain', item.label);
    };
    button.ondragend = () => { TL.insertDrag = null; tlInsertClearGhost(); };
  });
}

function tlInsertPanel() {
  if (state.project.kind === 'clip') return;
  const panel = document.createElement('details'); panel.className = 'tl-insert-add'; panel.id = 'tl-insert-add';
  panel.innerHTML = '<summary>Add</summary><p>Drag onto Pictures, or click to insert nearest the playhead.</p><button type="button" class="btn sm" data-browse>Browse blocks…</button><div data-add-sources></div>';
  $('#inspector').append(panel);
  panel.querySelector('[data-browse]').onclick = () => tlInsertBlock(tlInsertNearest());
  panel.ontoggle = async () => {
    if (!panel.open) return;
    const box = panel.querySelector('[data-add-sources]'); box.textContent = 'Loading…';
    const items = await tlInsertSources();
    if (!panel.isConnected || !panel.open) return;
    box.replaceChildren();
    for (const [kind,label] of [['clip','Recent clips and sources'], ['block','Blocks for this aspect'], ['picture','Library pictures']]) {
      const title = document.createElement('h4'); title.textContent = label;
      const list = document.createElement('div'); list.className = 'tl-insert-options'; box.append(title,list);
      tlInsertSourceList(list, items.filter(i => i.payload.kind === kind).slice(0,12), payload =>
        payload.kind === 'block' ? tlInsertBlock(tlInsertNearest(), payload) : tlInsertSave('', {...payload, after:tlInsertNearest().after}));
    }
  };
}

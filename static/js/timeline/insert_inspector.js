// Inserts use the existing picture/paragraph selections without adding a lane.
function tlInsertInspector(sel, body) {
  const row = state.project.slides.find(s => s.id === sel?.sid);
  if (!['picture','paragraph'].includes(sel?.kind) || !row?.insert?.kind) return false;
  const item = row.insert;
  const number = (key,label,value) => `<label for="insert-${key}">${label}</label><input id="insert-${key}" data-insert-field="${key}" type="number" step="0.05" value="${value}" required>`;
  body.innerHTML = `<h3>Insert · ${esc(item.kind)}</h3><form>
    ${item.kind === 'clip' ? `<p>${esc(item.shoot_id)} · ${esc(item.source_id)} · ${item.seconds.toFixed(2)} s</p>
      ${number('in_s','Source in (seconds)',item.in_s)}${number('out_s','Source out (seconds)',item.out_s)}
      <label for="insert-audio"><input type="checkbox" id="insert-audio" ${item.source_audio ? 'checked' : ''}> Source audio</label>`
      : number('seconds','Length (seconds)',item.seconds)}
    ${item.kind === 'card' ? `<label for="insert-text">Text</label><input id="insert-text" data-insert-field="text" value="${esc(item.text)}" maxlength="400" required>` : ''}
    ${item.kind === 'picture' ? `<p>${item.bin_id ? 'Materials' : 'Library'} · ${esc(item.bin_id || item.asset_id)}</p>` : ''}
    <div data-insert-vars></div><button type="submit" class="btn sm">Save insert</button></form>
    <button type="button" class="btn sm ghost" data-insert-delete>Delete insert</button><p role="status"></p>`;
  const form = body.querySelector('form');
  let block;
  if (item.kind === 'block') {
    form.querySelector('[type=submit]').disabled = true;
    api('/api/blocks').then(blocks => {
      if (!body.isConnected || TL.selection?.sid !== row.id) return;
      block = blocks.find(b => b.ref === item.block);
      if (!block) throw Error('Block unavailable.');
      body.querySelector('[data-insert-vars]').innerHTML = Object.entries(block.variables).map(([key,spec],i) =>
        blockTrialField(key,{...spec,default:item.vars[key] ?? spec.default},i)).join('');
      body.querySelectorAll('[data-pick-local]').forEach(button => { button.onclick = () => {
        const input = body.querySelector('#'+button.dataset.pickLocal);
        openLocalMediaPicker(input.dataset.type === 'clip' ? 'video' : 'image', asset => { input.value = `/scene/{token}/library/${asset.id}`; });
      }; });
      form.querySelector('[type=submit]').disabled = false;
    }).catch(error => { if (body.isConnected) body.querySelector('[role=status]').textContent = error.message; });
  }
  form.onsubmit = async e => {
    e.preventDefault();
    try {
      const patch = Object.fromEntries([...body.querySelectorAll('[data-insert-field]')].map(input =>
        [input.dataset.insertField, input.type === 'number' ? Number(input.value) : input.value]));
      if (item.kind === 'clip') patch.source_audio = body.querySelector('#insert-audio').checked;
      if (block) patch.vars = readBlockTrial(block,body);
      if (await tlInsertSave(row.id,patch)) TL.host.focus();
    } catch (error) { body.querySelector('[role=status]').textContent = error.message; }
  };
  body.querySelector('[data-insert-delete]').onclick = () => tlInsertSave(row.id,null);
  return true;
}

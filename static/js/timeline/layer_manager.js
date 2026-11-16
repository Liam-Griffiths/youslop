// Structural edits use the existing project snapshot history; dialogs stay in-page.
function tlLayerRequest(payload, ident = '', label = 'edit layers') {
  const pid = TL.pid;
  const result = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return false;
    try {
      const project = await api(`/api/projects/${pid}/layers${ident ? '/' + encodeURIComponent(ident) : ''}`, {
        method:ident ? 'PATCH' : 'POST', body:JSON.stringify(payload), editLabel:label});
      if (TL.pid !== pid || state.project?.id !== pid) return false;
      state.project = project;
      const mediaEdit = payload.role === 'media' || TL.selection?.kind === 'media';
      await tlRefresh(!mediaEdit, mediaEdit); tlInspector();
      return true;
    } catch (error) { tlMsg(error.message); return false; }
  });
  tlInspectorQueue = result.then(() => {}); return result;
}

function tlLayerReorder(id, before) {
  const ids = TL.data.project_layers.map(row => row.id).filter(key => key !== id);
  ids.splice(before ? ids.indexOf(before) : ids.length, 0, id);
  return tlLayerRequest({op:'reorder', ids}, '', 'reorder layers');
}

async function tlLayerSuggest(button) {
  const pid = TL.pid;
  if (button) button.disabled = true;
  try {
    const result = await api(`/api/projects/${pid}/layers/suggest`, {method:'POST'});
    if (TL.pid === pid) watchJob(result.job, 'suggest layers');
  } catch (error) { tlMsg(error.message); }
  finally { if (button) button.disabled = false; }
}

function tlWireLayerManager(track) {
  $('#tl-layer-add').onclick = () => tlLayerDialog();
  const proposal = $('#tl-layer-proposal');
  if (proposal) {
    const plan = state.project.layer_proposal;
    proposal.hidden = !plan?.id;
    proposal.innerHTML = plan?.id ? `<h3>Proposed layers</h3>
      ${(() => {
        // Apply replaces layers whose role the proposal covers and keeps the rest.
        const roles = new Set(plan.entries.map(e => e.role)), now = TL.data.project_layers || [];
        const replaced = now.filter(r => roles.has(r.role)).map(r => r.name), kept = now.filter(r => !roles.has(r.role)).map(r => r.name);
        return `<p class="mono">${replaced.length ? `<del>${esc(replaced.join(', '))}</del> → ` : ''}<ins>${esc(plan.entries.map(e => e.name).join(', '))}</ins>${kept.length ? `<br>Kept: ${esc(kept.join(', '))}` : ''}</p>`;
      })()}
      ${plan.entries.map(e => `<p><strong>${esc(e.name)}</strong> · ${esc(e.role)}<br>${esc(e.why)}</p>`).join('')}
      <button type="button" class="btn sm light" data-apply>Apply</button>
      <button type="button" class="btn sm ghost" data-dismiss>Dismiss</button>` : '';
    for (const [selector, op] of [['[data-apply]', 'apply_proposal'], ['[data-dismiss]', 'dismiss_proposal']]) {
      const button = proposal.querySelector(selector);
      if (button) button.onclick = () => tlLayerRequest({op, proposal:plan.id}, '', op === 'apply_proposal' ? 'apply layer proposal' : 'dismiss layer proposal');
    }
  }
  track.querySelectorAll('[data-manage]').forEach(button => {
    button.onpointerdown = e => e.stopPropagation();
    button.onclick = e => { e.stopPropagation(); tlLayerDialog(button.dataset.manage); };
  });
  track.querySelectorAll('.tl-layer-label').forEach(label => {
    const id = label.closest('[data-track]').dataset.track;
    label.ondblclick = e => { if (!e.target.closest('button')) { e.stopPropagation(); tlLayerDialog(id); } };
    label.draggable = true;
    label.ondragstart = e => { e.stopPropagation(); TL.layerDrag = id; e.dataTransfer.setData('text/plain', id); };
    label.ondragend = () => { TL.layerDrag = null; };
    label.ondragover = e => { if (TL.layerDrag && TL.layerDrag !== id) { e.preventDefault(); e.stopPropagation(); } };
    label.ondrop = e => {
      if (!TL.layerDrag || TL.layerDrag === id) return;
      e.preventDefault(); e.stopPropagation();
      tlLayerReorder(TL.layerDrag, id); TL.layerDrag = null;
    };
  });
}

function tlLayerDialog(id = '') {
  const pid = TL.pid;
  const rows = TL.data.project_layers, row = rows.find(r => r.id === id);
  const roles = ['media', 'graphics', 'titles', 'music', 'notes', 'sponsors', 'captions', 'cues', 'chapters', 'stings'];
  const colors = [['accent','Accent'], ['cool','Blue'], ['good','Green'], ['warn','Amber'], ['bad','Red'], ['ink','Ink'], ['ink-2','Secondary ink'], ['dim','Muted']];
  const peers = rows.filter(r => r.role === row?.role && r.id !== id);
  const options = (values, selected) => values.map(([value, name]) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(name)}</option>`).join('');
  const {dialog, close} = tlInsertDialog(row ? `Manage ${row.name}` : 'Add layer', `
    ${row ? `<p><span class="mono">${row.items.length}</span> ${row.items.length === 1 ? 'item' : 'items'} on this layer</p>` : ''}
    <form id="layer-details" class="tl-layer-section">
      <h3>${row ? 'Name and colour' : 'New layer'}</h3>
      <label class="field" for="layer-name"><span>Name</span><input type="text" id="layer-name" required maxlength="24" value="${esc(row?.name || '')}"></label>
      ${row ? `<fieldset class="tl-layer-colors"><legend>Colour</legend><div class="row">
        ${colors.map(([value, name]) => `<label class="tl-layer-color" title="${esc(name)}">
          <input type="radio" name="layer-color" value="${value}" aria-label="${esc(name)}" ${value === row.color ? 'checked' : ''}>
          <span aria-hidden="true" style="--track-color:var(--${value})"></span></label>`).join('')}
        </div></fieldset>` : `<label class="field" for="layer-role"><span>Role</span><select id="layer-role">${options(roles.map(r => [r,r[0].toUpperCase()+r.slice(1)]), 'graphics')}</select></label>`}
    </form>
    ${row ? `<section class="tl-layer-section" aria-labelledby="layer-visibility-title">
      <h3 id="layer-visibility-title">Visibility</h3>
      <label class="tl-layer-toggle"><input type="checkbox" data-toggle="locked" ${row.locked ? 'checked' : ''}>Locked</label>
      <label class="tl-layer-toggle"><input type="checkbox" data-toggle="hidden" aria-describedby="layer-hidden-help" ${row.hidden ? 'checked' : ''}>Hidden</label>
      <p id="layer-hidden-help" class="sub">Hidden layers are left out of previews.</p>
      <label class="tl-layer-toggle"><input type="checkbox" id="layer-render" aria-describedby="layer-render-help" ${state.project.hide_in_render ? 'checked' : ''}>Exclude hidden layers from final renders</label>
      <p id="layer-render-help" class="sub">Applies to all hidden layers in this project; otherwise they appear in final renders.</p>
      </section>
      <section class="tl-layer-section" aria-labelledby="layer-order-title">
      <h3 id="layer-order-title">Order</h3>
      <div class="row"><button type="button" class="btn" data-up ${rows[0] === row ? 'disabled' : ''}>Move up</button>
      <button type="button" class="btn" data-down ${rows.at(-1) === row ? 'disabled' : ''}>Move down</button></div>
      </section>
      ${['pictures','voice'].includes(row.role) ? '<p class="sub">The main track can be renamed and reordered.</p>' : `
      <section class="tl-layer-section" aria-label="Add a similar layer">
      <button type="button" class="btn" data-duplicate>Add an empty layer like this</button>
      </section>
      <section class="tl-layer-section" aria-labelledby="layer-delete-title">
      <h3 id="layer-delete-title">Delete layer</h3>
      <label class="field" for="layer-destination"><span>Move its items to</span><select id="layer-destination"><option value="">Choose a ${esc(row.role)} layer</option>${options(peers.map(r => [r.id,r.name]), '')}</select></label>
      <button type="button" class="btn danger" data-delete>Delete layer</button>
      </section>`}` : ''}
    <div class="tl-layer-footer"><button type="submit" form="layer-details" class="btn primary">${row ? 'Save' : 'Add layer'}</button></div>`);
  dialog.classList.add('tl-layer-dialog');
  const footer = dialog.querySelector('.tl-layer-footer');
  footer.before(dialog.querySelector('[role="status"]'));
  footer.prepend(dialog.querySelector('[data-close]'));
  const send = async (payload, target = '', label = 'edit layers') => {
    if (TL.pid !== pid || state.project?.id !== pid) { close(); return; }
    const controls = [...dialog.querySelectorAll('button, input, select')], disabled = controls.map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    if (await tlLayerRequest(payload, target, label)) close();
    else { dialog.querySelector('[role="status"]').textContent = $('#tl-msg')?.textContent || 'Could not save this layer. Check the destination and locks.';
      controls.forEach((control,i) => { control.disabled = disabled[i]; });
      dialog.querySelectorAll('[data-toggle]').forEach(input => { input.checked = row[input.dataset.toggle]; }); }
  };
  dialog.querySelector('form').onsubmit = e => {
    e.preventDefault(); const name = dialog.querySelector('#layer-name').value.trim();
    send(row ? {name, color:dialog.querySelector('[name="layer-color"]:checked').value}
      : {op:'add', name, role:dialog.querySelector('#layer-role').value}, id, row ? 'rename or recolour layer' : 'add layer');
  };
  dialog.querySelectorAll('[data-toggle]').forEach(input => { input.onchange = () => send({[input.dataset.toggle]:input.checked}, id, `toggle ${input.dataset.toggle} layer`); });
  const render = dialog.querySelector('#layer-render');
  if (render) render.onchange = async e => {
    if (TL.pid !== pid) { close(); return; }
    await $('#tl-hide-render').onchange(e); $('#tl-hide-render').checked = state.project.hide_in_render;
  };
  const wire = (selector, handler) => { const button = dialog.querySelector(selector); if (button) button.onclick = handler; };
  wire('[data-duplicate]', () => send({op:'duplicate', id}, '', 'duplicate empty layer'));
  wire('[data-delete]', () => send({op:'delete', id, move_to:dialog.querySelector('#layer-destination').value}, '', 'delete layer'));
  const reorder = async before => { if (TL.pid !== pid || await tlLayerReorder(id, before)) close(); };
  wire('[data-up]', () => reorder(rows[rows.indexOf(row)-1]?.id));
  wire('[data-down]', () => reorder(rows[rows.indexOf(row)+2]?.id));
  dialog.querySelector('#layer-name').focus();
}

function tlGraphicLayerSelect(sel, body) { tlItemLayerSelect(sel, body); }

function tlItemLayerSelect(sel, body) {
  const current = TL.data.project_layers.find(row => row.items.some(item => item.id === sel.id && item.sid === sel.sid && item.kind === sel.kind));
  if (!current || ['pictures', 'voice'].includes(current.role)) return;
  const rows = TL.data.project_layers.filter(row => row.role === current.role);
  const shared = ['captions', 'chapters', 'sponsors', 'notes'].includes(current.role);
  const wrap = document.createElement('div');
  wrap.innerHTML = `<label for="item-layer">Layer${shared ? ' (all ' + esc(current.role) + ')' : ''}</label><select id="item-layer">${rows.map(row => `<option value="${esc(row.id)}" ${current.id === row.id ? 'selected' : ''} ${row.locked ? 'disabled' : ''}>${esc(row.name)}${row.locked ? ' (locked)' : ''}</option>`).join('')}</select>${shared ? '<p class="tl-note">These items move together.</p>' : ''}`;
  wrap.querySelector('select').disabled = current.locked;
  wrap.querySelector('select').onchange = async e => {
    if (!await tlLayerRequest({op:'move_item', role:current.role, sid:sel.sid, item:sel.id, to:e.target.value}, '', 'move ' + current.role + ' to layer')) e.target.value = current.id;
  };
  body.prepend(wrap);
}

// Classify the gesture before handing horizontal movement to timing controls.
function tlWireLayerMoves() {
  const track = $('#tl-track');
  track.querySelectorAll('[data-layer]:not([data-layer="graphics"]):not([data-layer="media"])').forEach(node => {
    const original = node.onpointerdown;
    node.onpointerdown = e => {
      if (e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey || TL.drag || e.target.closest('.tl-resize')) return original?.(e);
      const pid = TL.pid, sel = TL.data.layers[node.dataset.layer][+node.dataset.item];
      const row = TL.data.project_layers.find(r => r.id === node.closest('[data-track]').dataset.track);
      if (!row || !tlCanEdit([sel])) return;
      e.stopPropagation();
      let vertical = false;
      const cleanup = () => {
        document.removeEventListener('pointermove', move, true);
        document.removeEventListener('pointerup', finish, true);
        document.removeEventListener('pointercancel', cancel, true);
        document.removeEventListener('keydown', key, true);
        node.style.transform = ''; TL.drag = null;
      };
      const move = ev => {
        const dx = ev.clientX-e.clientX, dy = ev.clientY-e.clientY;
        if (!vertical && Math.max(Math.abs(dx), Math.abs(dy)) < 4) return;
        if (!vertical && Math.abs(dx) > Math.abs(dy)) {
          cleanup(); original?.(e); node.onpointermove?.(ev); return;
        }
        if (!vertical) { tlPause(); tlSelect(sel); }
        vertical = true; TL.drag = {layerMove:true};
        node.style.transform = `translateY(${dy}px)`;
        ev.preventDefault(); ev.stopImmediatePropagation();
      };
      const finish = ev => {
        const destination = [...track.querySelectorAll('[data-track]')].find(lane => {
          const r = lane.getBoundingClientRect(); return ev.clientY >= r.top && ev.clientY < r.bottom;
        });
        cleanup();
        if (!vertical || TL.pid !== pid) return;
        ev.preventDefault(); ev.stopImmediatePropagation();
        if (destination?.dataset.role === row.role && destination.dataset.track !== row.id)
          tlLayerRequest({op:'move_item', role:row.role, sid:sel.sid, item:sel.id, to:destination.dataset.track}, '', 'move ' + row.role + ' to layer');
      };
      const cancel = () => cleanup();
      const key = ev => { if (ev.key === 'Escape') { cleanup(); ev.preventDefault(); ev.stopImmediatePropagation(); } };
      document.addEventListener('pointermove', move, true);
      document.addEventListener('pointerup', finish, true);
      document.addEventListener('pointercancel', cancel, true);
      document.addEventListener('keydown', key, true);
    };
  });
}

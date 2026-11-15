/* Vocabulary UI; callers supply current labels and an async mutation callback.
   change({action:'rename'|'reorder'|'delete', ...}) returns false on failure. */
function openLabelsEditor({getLabels, change}) {
  const dialog = studioDialog('labels-editor', `<div class="row"><h2 id="studio-dialog-title">Labels</h2>
    <button type="button" class="btn sm" data-close>Close</button></div>
    <p class="sub">Rename labels, change their number keys, or remove them from all items.</p>
    <div data-label-rows></div><p data-label-status role="status"></p>`);
  const rows = $('[data-label-rows]', dialog), status = $('[data-label-status]', dialog);
  let busy = false;
  const apply = async (payload, index) => {
    if (busy) return;
    busy = true;
    rows.querySelectorAll('button, input').forEach(el => el.disabled = true);
    try {
      if (await change(payload) !== false) {
        paint();
        const inputs = rows.querySelectorAll('input');
        inputs[Math.min(index, inputs.length - 1)]?.focus();
        status.textContent = 'Labels updated.';
      }
    } catch (e) { status.textContent = e.message; }
    finally { busy = false; rows.querySelectorAll('button, input').forEach(el => el.disabled = el.dataset.edge === 'true'); }
  };
  const paint = () => {
    const labels = [...getLabels()];
    rows.innerHTML = labels.map((l, n) => `<form class="label-editor-row" data-row="${n}">
      <label class="bin-sr-only" for="vocabulary-${n}">Label ${n + 1}</label>
      <span class="mono">${n < 9 ? n + 1 : '–'}</span><input id="vocabulary-${n}" type="text" value="${esc(l)}" required>
      <button class="btn sm" type="submit">Rename</button>
      <button class="btn sm" type="button" data-move="-1" data-edge="${n === 0}" ${n === 0 ? 'disabled' : ''} aria-label="Move ${esc(l)} up">Up</button>
      <button class="btn sm" type="button" data-move="1" data-edge="${n === labels.length - 1}" ${n === labels.length - 1 ? 'disabled' : ''} aria-label="Move ${esc(l)} down">Down</button>
      <button class="btn sm" type="button" data-delete aria-label="Delete ${esc(l)}">Delete</button></form>`).join('') || '<p class="sub">Type a label on an item to start your vocabulary.</p>';
    rows.querySelectorAll('[data-row]').forEach(form => {
      const n = Number(form.dataset.row), old = labels[n];
      form.onsubmit = e => { e.preventDefault(); apply({action:'rename', old, new:form.querySelector('input').value}, n); };
      form.querySelectorAll('[data-move]').forEach(button => button.onclick = () => {
        const order = [...labels], to = n + Number(button.dataset.move);
        [order[n], order[to]] = [order[to], order[n]];
        return apply({action:'reorder', labels:order}, to);
      });
      form.querySelector('[data-delete]').onclick = () => {
        if (busy) return;
        const confirm = studioDialog('label-delete', `<h2 id="label-delete-title">Delete label?</h2>
          <p>Remove “${esc(old)}” from the vocabulary and every item?</p>
          <button type="button" class="btn" data-confirm>Delete label</button>
          <button type="button" class="btn" data-cancel>Cancel</button>`);
        confirm.setAttribute('aria-labelledby', 'label-delete-title');
        $('[data-cancel]', confirm).onclick = () => confirm.close();
        $('[data-confirm]', confirm).onclick = () => { confirm.close(); return apply({action:'delete', old}, n); };
        $('[data-cancel]', confirm).focus();
      };
    });
  };
  $('[data-close]', dialog).onclick = () => { if (!busy) dialog.close(); };
  paint();
  rows.querySelector('input')?.focus();
  return dialog;
}

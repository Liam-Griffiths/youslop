/* Shared app dialog lifecycle, including legacy editor keyboard adapters. */
let appDialogId = 0;

function appDialogKey(e, wrap, close) {
  e.stopPropagation();
  if (e.key === 'Escape') { e.preventDefault(); close(); return; }
  if (e.key !== 'Tab') return;
  const controls = [...wrap.querySelectorAll('button, input, select, textarea, a[href], [tabindex="0"]')]
    .filter(el => !el.disabled && el.getClientRects().length);
  const end = controls.at(e.shiftKey ? 0 : -1);
  if (!controls.length || document.activeElement === end || !wrap.contains(document.activeElement)) {
    e.preventDefault();
    (controls.at(e.shiftKey ? -1 : 0) || wrap).focus();
  }
}

function studioDialog(className, content, onClose = () => {}) {
  const opener = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = `studio-dialog ${className}`;
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.tabIndex = -1;
  dialog.innerHTML = content;
  const title = dialog.querySelector('h2');
  if (title) {
    if (!title.id) title.id = `app-dialog-title-${++appDialogId}`;
    dialog.setAttribute('aria-labelledby', title.id);
  } else dialog.setAttribute('aria-label', 'Dialog');
  dialog.addEventListener('keydown', e => appDialogKey(e, dialog, () => dialog.close()));
  dialog.addEventListener('cancel', e => { e.preventDefault(); dialog.close(); });
  dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    try { onClose(); }
    finally {
      dialog.remove();
      if (opener?.isConnected) opener.focus();
    }
  }, {once: true});
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

function appValueDialog({title, body = '', choices, cancel = 'Cancel', label,
  value = '', required = false, danger = false, multiline = false, fields}) {
  return new Promise(resolve => {
    let result = null;
    const inputId = `app-dialog-input-${++appDialogId}`;
    const inputs = fields || (label === undefined ? [] : [{label, value, required, multiline}]);
    const controls = inputs.map((field, index) => {
      const id = `${inputId}-${index}`;
      return `<label class="micro-label" for="${id}">${esc(field.label)}</label>
        ${field.multiline
          ? `<textarea id="${id}" rows="6" ${field.required ? 'required' : ''}>${esc(field.value ?? '')}</textarea>`
          : `<input id="${id}" value="${esc(field.value ?? '')}" ${field.required ? 'required' : ''}>`}`;
    }).join('');
    const primary = Math.max(0, choices.findIndex(choice => choice.primary));
    const buttons = choices.map((choice, index) => {
      const accent = index === primary;
      return `<button type="${inputs.length ? 'submit' : 'button'}"
        class="btn${accent ? ' primary' : ''}${danger ? ' danger' : ''}"
        data-choice="${esc(choice.id)}">${esc(choice.label)}</button>`;
    }).join('');
    const dialog = studioDialog('app-dialog', `<h2>${esc(title)}</h2>
      ${body ? `<p data-body>${esc(body)}</p>` : ''}<form>
      ${controls}
      <div class="row app-dialog-actions"><button type="button" class="btn ghost" data-cancel>${esc(cancel)}</button>
      ${buttons}</div></form>`, () => resolve(result));
    const description = dialog.querySelector('[data-body]');
    if (description) {
      description.id = `${inputId}-body`;
      dialog.setAttribute('aria-describedby', description.id);
    }
    dialog.querySelector('[data-cancel]').onclick = () => dialog.close();
    const elements = [...dialog.querySelectorAll('input, textarea')];
    const input = elements[0];
    if (input) {
      dialog.querySelector('form').onsubmit = e => {
        e.preventDefault();
        result = fields ? Object.fromEntries(fields.map((field, index) => [field.name, elements[index].value])) : input.value;
        dialog.close();
      };
    } else {
      dialog.querySelector('form').onsubmit = e => e.preventDefault();
      dialog.querySelectorAll('[data-choice]').forEach(button => {
        button.onclick = () => { result = button.dataset.choice; dialog.close(); };
      });
    }
    (input || dialog.querySelector('[data-cancel]')).focus();
    input?.select();
  });
}

function appChoose(options) { return appValueDialog(options); }
function appConfirm({title, body, ok = 'Continue', cancel = 'Cancel', danger = false}) {
  return appChoose({title, body, cancel, danger,
    choices: [{id: 'ok', label: ok, primary: true}]}).then(value => value === 'ok');
}
// A single field resolves to text; named fields resolve to an object. Cancel is null.
function appPrompt({title, body, label, value = '', ok = 'Continue', required = false, multiline = false, fields}) {
  return appValueDialog({title, body, label, value, required, multiline, fields,
    choices: [{id: 'ok', label: ok, primary: true}]});
}

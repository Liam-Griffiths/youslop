/* Small command registry shared by the shell and stage actions. */
const commands = new Map();
function registerCommand(command) { commands.set(command.id, command); }

function studioDialog(className, content, onClose = () => {}) {
  const opener = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = `studio-dialog ${className}`;
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-labelledby', 'studio-dialog-title');
  dialog.innerHTML = content;
  dialog.addEventListener('keydown', e => e.stopPropagation());
  dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    onClose();
    dialog.remove();
    if (opener?.isConnected) opener.focus();
  }, {once: true});
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

function commandScore(label, query) {
  let at = 0, score = 0;
  for (const char of query.toLowerCase().replace(/\s/g, '')) {
    const next = label.toLowerCase().indexOf(char, at);
    if (next < 0) return -1;
    score += next - at;
    at = next + 1;
  }
  return score;
}

function openPalette() {
  if (document.querySelector('dialog[open]')) return;
  const dialog = studioDialog('command-palette', `<div class="row">
    <h2 id="studio-dialog-title">Commands</h2><div class="spacer"></div>
    <button type="button" class="btn sm ghost" data-close>Close</button></div>
    <label for="command-query" class="micro-label">Find an action or screen</label>
    <input id="command-query" type="text" role="combobox" aria-autocomplete="list" aria-expanded="true"
      aria-controls="command-results" autocomplete="off" placeholder="Type a command…">
    <div id="command-results" role="listbox" aria-label="Commands"></div>`);
  const input = $('#command-query', dialog), list = $('#command-results', dialog);
  let matches = [], selected = 0;
  const run = async index => {
    const command = matches[index];
    if (!command || (command.when && !command.when())) return;
    dialog.close();
    try { await command.run(); } catch (e) { toast(e.message, true); }
  };
  const paint = () => {
    list.innerHTML = matches.map((c, i) => `<div role="option" id="command-${i}"
      aria-selected="${i === selected}" data-command="${i}">
      <span>${esc(c.label)}</span><span class="mono sub">${esc(c.group || '')}</span></div>`).join('')
      || '<p class="sub">No matching commands.</p>';
    if (matches.length) {
      input.setAttribute('aria-activedescendant', `command-${selected}`);
      $(`#command-${selected}`, list).scrollIntoView({block: 'nearest'});
    } else input.removeAttribute('aria-activedescendant');
  };
  const filter = () => {
    matches = [...commands.values()].filter(c => !c.when || c.when())
      .map(c => ({c, score: commandScore(`${c.label} ${c.group || ''}`, input.value)}))
      .filter(row => row.score >= 0).sort((a, b) => a.score - b.score).map(row => row.c);
    selected = 0;
    paint();
  };
  $('[data-close]', dialog).onclick = () => dialog.close();
  input.oninput = filter;
  input.onkeydown = e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      selected = (selected + (e.key === 'ArrowDown' ? 1 : -1) + matches.length) % (matches.length || 1);
      paint();
    } else if (e.key === 'Enter') { e.preventDefault(); run(selected); }
  };
  list.onclick = e => {
    const row = e.target.closest('[data-command]');
    if (row) run(Number(row.dataset.command));
  };
  filter();
  input.focus();
}

document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    e.stopImmediatePropagation();
    openPalette();
  }
}, true);

for (const [id, label] of [['', 'Home'], ['footage', 'Footage'], ['library', 'Library'],
  ['channels', 'Channels'], ['packs', 'Packs'], ['settings', 'Settings'], ['guide', 'How it works']]) {
  registerCommand({id: `route-${id || 'home'}`, label, group: 'Screens', run: () => go(`#/${id}`)});
}
registerCommand({id: 'new-project', label: 'New project', group: 'Actions', run: () => {
  const start = () => { homeStart('idea'); $('#idea')?.focus(); };
  if ((location.hash || '#/') === '#/') start();
  else { state.afterHome = start; go('#/'); }
}});
registerCommand({id: 'preview-section', label: 'Preview current section', group: 'Edit',
  when: () => !!state.project && state.stage === 'edit' && !!TL.data && !!TL.host?.isConnected,
  run: () => tlPreviewBit()});
registerCommand({id: 'jobs', label: 'Open jobs', group: 'Actions', run: () => openJobs()});

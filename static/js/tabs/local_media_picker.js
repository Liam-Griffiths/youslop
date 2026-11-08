// Shared local Library picker for Visuals and block image/clip variables.
async function openLocalMediaPicker(kind, onPick) {
  const previous = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'studio-dialog local-media-picker';
  dialog.innerHTML = `<h2>Choose from Library</h2><label for="local-media-query">Find ${kind === 'video' ? 'clips' : 'images'}</label>
    <input type="search" id="local-media-query"><div class="pick-grid" role="list"></div>
    <p role="status"></p><button type="button" class="btn ghost">Close</button>`;
  document.body.appendChild(dialog);
  const close = () => { dialog.close(); dialog.remove(); previous?.focus(); };
  dialog.querySelector('button').onclick = close;
  dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
  dialog.showModal();
  const status = dialog.querySelector('[role=status]'), grid = dialog.querySelector('.pick-grid');
  try {
    const assets = await api(`/api/library?kind=${kind}`);
    if (!dialog.isConnected) return;
    const paint = () => {
      const q = dialog.querySelector('input').value.toLowerCase();
      const items = assets.filter(a => [a.title,...a.tags].join(' ').toLowerCase().includes(q));
      grid.innerHTML = items.map(a => `<button type="button" class="btn ghost" data-asset="${esc(a.id)}"><img src="/api/library/thumb/${esc(a.id)}" alt=""><span>${esc(a.title || a.id)}</span></button>`).join('');
      status.textContent = items.length ? `${items.length} matches` : 'No matches. Add files in Library.';
      grid.querySelectorAll('[data-asset]').forEach(button => { button.onclick = async () => {
        try { await onPick(assets.find(a => a.id === button.dataset.asset)); close(); }
        catch (error) { status.textContent = error.message; }
      }; });
    };
    dialog.querySelector('input').oninput = paint; paint();
  } catch (error) { status.textContent = error.message; }
}

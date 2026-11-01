// Variables share the inspector's refresh path and only draw a proxy on demand.
let tlVariablesQueue = Promise.resolve();
async function tlVariablesLoad() {
  const pid = TL.pid, box = $('#tl-variables');
  if (!box) return;
  try {
    const values = await api(`/api/projects/${pid}/variables`);
    if (pid !== TL.pid || !box.isConnected) return;
    box.innerHTML = `<details><summary>Variables</summary>
      <label for="tl-variable-search">Search variables</label>
      <input id="tl-variable-search" type="search" placeholder="Find a variable">
      <label for="tl-variable-scope">Edit colours and frame for</label>
      <select id="tl-variable-scope"><option value="project">This project</option>
      ${state.project.channel_id ? '<option value="channel">Channel defaults (future projects)</option>' : ''}</select>
      <div id="tl-variable-groups"></div><p role="status" id="tl-variable-status"></p></details>`;
    const draw = () => {
      const query = $('#tl-variable-search').value.toLowerCase();
      $('#tl-variable-groups').innerHTML = Object.entries(values).map(([group, entries]) => {
        const rows = Object.entries(entries).filter(([key]) => `${group} ${key}`.includes(query));
        return `<section><h4>${esc(group === 'colors' ? 'Colours' : group === 'copy' ? 'Copy' : 'Frame')}</h4>${rows.map(([key, row]) => {
          const id = `tl-variable-${key}`, readonly = row.editable === false;
          return `<div class="tl-variable-row"><label for="${id}">${esc(key.replaceAll('_', ' '))}</label>
            <span class="mono dim">${esc(row.source)} ${esc(row.unit || '')}</span>
            <div class="row">${group === 'colors' ? `<input type="color" aria-label="${esc(key)} swatch" data-swatch="${key}" value="${esc(row.value)}" ${readonly ? 'disabled' : ''}>` : ''}
            <input id="${id}" data-variable="${key}" data-group="${group}" type="${group === 'frame' ? 'number' : 'text'}"
              ${group === 'frame' ? 'step="any" class="mono"' : ''} value="${esc(row.value)}" ${readonly ? 'readonly' : ''}>
            ${group !== 'copy' && !readonly ? `<button class="btn sm ghost" data-reset="${key}" aria-label="Reset ${key}">Reset</button>` : ''}</div></div>`;
        }).join('')}</section>`;
      }).join('');
      box.querySelectorAll('[data-variable]').forEach(el => {
        el.onchange = () => save(el.dataset.variable, el.type === 'number' ? Number(el.value) : el.value, el.dataset.group);
      });
      box.querySelectorAll('[data-swatch]').forEach(el => {
        el.onchange = () => save(el.dataset.swatch, el.value, 'colors');
      });
      box.querySelectorAll('[data-reset]').forEach(el => {
        el.onclick = () => save(el.dataset.reset, null, '');
      });
    };
    const save = (key, value, group) => {
      const scope = group === 'copy' && state.project.channel_id ? 'channel' : $('#tl-variable-scope').value;
      tlVariablesQueue = tlVariablesQueue.then(async () => {
        if (pid !== TL.pid || state.project?.id !== pid) return;
        try {
          const next = await api(`/api/projects/${pid}/variables`, {method: 'PATCH', body: JSON.stringify({scope, key, value})});
          if (pid !== TL.pid) return;
          state.project = await api(`/api/projects/${pid}`);
          Object.assign(values, next);
          draw();
          $('#tl-variable-status').textContent = 'Saved';
          await tlInspectorLoad();
          await tlRefresh(true);
        } catch (e) {
          if (box.isConnected) $('#tl-variable-status').textContent = e.message;
        }
      });
    };
    $('#tl-variable-search').oninput = draw;
    draw();
  } catch (e) { box.textContent = e.message; }
}

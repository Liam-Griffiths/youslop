// Per-viewer appearance; never sent to the settings API.
function setDisplayFace(value) {
  const face = value === 'grotesk' ? 'grotesk' : 'archivo';
  document.documentElement.dataset.display = face;
  try { localStorage.setItem('corkbored-display', face); } catch (e) { /* private viewer */ }
}


function settingsFieldRow(f) {
  const id = `set_${f.key}`;
  const placeholder = f.secret
    ? (f.set ? '•••••••••••••• (set — leave blank to keep)' : 'not set')
    : '';
  const value = f.secret ? '' : esc(f.value || '');
  const badge = f.locked
    ? `<span class="pill warn" style="margin-left:6px" title="A real environment variable (${esc(f.env)}) is set outside Corkbored and overrides this">locked by environment</span>`
    : f.set ? `<span class="pill on" style="margin-left:6px">set</span>` : '';
  // A field with a fixed, correct set of answers gets a <select> instead of
  // free text — which model, which backend, how hard it thinks are all
  // typo-prone as text and every wrong value fails the same way: a rejected
  // API call three steps later with no hint why.
  // An unset select shows what it would actually resolve to (f.default),
  // not just whichever option happens to be listed first.
  const effective = f.value || f.default;
  const control = f.options.length
    ? `<select id="${id}" ${f.locked ? 'disabled' : ''}
         onchange="settingsDirty.add('${f.key}')">
         ${f.options.map((o) => `<option value="${esc(o.value)}"
           ${o.value === effective ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}
       </select>`
    : `<input id="${id}" type="${f.secret ? 'password' : 'text'}"
         value="${value}" placeholder="${esc(placeholder)}"
         ${f.locked ? 'disabled' : ''}
         oninput="settingsDirty.add('${f.key}')">`;
  return `
    <label class="field">
      <span>${esc(f.label)} ${badge}</span>
      ${control}
      ${f.help ? `<div class="mono" style="color:var(--ink-faint);margin-top:5px;font-size:12px">${esc(f.help)}</div>` : ''}
    </label>`;
}

async function renderSettings() {
  view.innerHTML = `<div class="empty-note">${loadingLine()}</div>`;
  let data;
  try { data = await api('/api/settings'); }
  catch (e) { view.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; return; }
  settingsDirty.clear();

  const groups = [];
  for (const f of data.fields) {
    let g = groups.find((x) => x.name === f.group);
    if (!g) { g = { name: f.group, fields: [] }; groups.push(g); }
    g.fields.push(f);
  }

  view.innerHTML = `
    <h1>Settings</h1>
    <p class="sub">Set up writing, narration, research and rendering.
      Changes take effect the next time the app starts.</p>
    <p class="mono" style="color:var(--ink-faint);margin:-8px 0 22px">
      Data folder: ${esc(data.data_dir)}</p>
    <p class="mono">New-channel cards: ${esc(data.card_engine)}. Channel preview templates
      marked “scene” use Chromium; other templates use Pillow.</p>

    <h2 class="micro">Appearance</h2>
    <div class="panel">
      <label class="field"><span>Display face</span>
        <select id="display-face" onchange="setDisplayFace(this.value)">
          <option value="archivo" ${document.documentElement.dataset.display !== 'grotesk' ? 'selected' : ''}>Archivo (condensed)</option>
          <option value="grotesk" ${document.documentElement.dataset.display === 'grotesk' ? 'selected' : ''}>Space Grotesk</option>
        </select>
      </label>
    </div>
    <div id="settings-groups">
      ${groups.map((g) => `
        <h2 style="font-size:15px;margin:26px 0 10px">${esc(g.name)}</h2>
        <div class="panel">
          ${g.fields.map(settingsFieldRow).join('')}
        </div>`).join('')}
    </div>

    <div class="row" style="margin-top:22px;position:sticky;bottom:18px">
      <button class="btn primary" onclick="saveSettingsForm()">Save settings</button>
      <span class="mono" id="settings-state" style="color:var(--ink-faint)"></span>
    </div>`;
}

async function saveSettingsForm() {
  const payload = {};
  for (const key of settingsDirty) {
    const el = $(`#set_${key}`);
    if (el) payload[key] = el.value;
  }
  if (!Object.keys(payload).length) return toast('Nothing changed');
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(payload) });
    toast('Saved — takes effect next launch');
    await renderSettings();
  } catch (e) { toast(e.message, true); }
}

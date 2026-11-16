// Per-viewer appearance; never sent to the settings API.
function setDisplayFace(value) {
  const face = value === 'grotesk' ? 'grotesk' : 'archivo';
  document.documentElement.dataset.display = face;
  try { localStorage.setItem('corkbored-display', face); } catch (e) { /* private viewer */ }
}


const SETTINGS_SECTIONS = [
  ['writing', 'Writing model'], ['voices', 'Voices'], ['research', 'Research'],
  ['archives', 'Archives'], ['speech', 'Speech-to-text'], ['publishing', 'Publishing'],
  ['rendering', 'Rendering'], ['appearance', 'Appearance'], ['packs', 'Packs'], ['general', 'General'],
];

function settingsFieldRow(f) {
  // OpenAI's key also appears in Voices. Both controls edit the same setting.
  const id = `set_${f.key}${f.group === 'Voices' ? '_voices' : ''}`;
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
    ? `<select id="${id}" data-setting-key="${f.key}" data-original-value="${esc(effective || '')}" ${f.locked ? 'disabled' : ''}
         onchange="settingsFieldChanged(this)">
         ${f.options.map((o) => `<option value="${esc(o.value)}"
           ${o.value === effective ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}
       </select>`
    : `<input id="${id}" data-setting-key="${f.key}" data-original-value="${value}" type="${f.secret ? 'password' : 'text'}"
         value="${value}" placeholder="${esc(placeholder)}"
         ${f.locked ? 'disabled' : ''}
         oninput="settingsFieldChanged(this)">`;
  return `
    <label class="field" for="${id}">
      <span>${esc(f.label)} ${badge}</span>
      ${control}
      ${f.help ? `<div class="mono" style="color:var(--ink-faint);margin-top:5px;font-size:12px">${esc(f.help)}</div>` : ''}
    </label>`;
}

function settingsFieldChanged(control) {
  const key = control.dataset.settingKey;
  if (control.value === control.dataset.originalValue) settingsDirty.delete(key);
  else settingsDirty.add(key);
  document.querySelectorAll(`[data-setting-key="${key}"]`).forEach(el => {
    if (el !== control) el.value = control.value;
  });
  const status = $('#settings-state');
  if (status) status.textContent = settingsDirty.size ? 'Unsaved changes' : '';
  if (key === 'llm_backend' || key === 'stt_engine') settingsUpdateProviders();
}

function settingsFieldBackends(key) {
  if (key.startsWith('lmstudio_')) return ['lmstudio'];
  if (key.startsWith('llm_ollama_')) return ['ollama'];
  return {
    ollama_context: ['lmstudio', 'ollama'], anthropic_api_key: ['auto', 'api'],
    model_script: ['auto', 'cli', 'api'], model_utility: ['auto', 'cli', 'api'], effort: ['auto', 'cli', 'api'],
    openai_api_key: ['openai'], deepseek_api_key: ['deepseek'], xai_api_key: ['grok'],
    stt_folder: ['whisper.cpp'], stt_executable: ['whisper.cpp'], stt_whisper_cache: ['openai-whisper'],
    stt_hub_cache: ['faster-whisper', 'mlx-whisper'], stt_device: ['faster-whisper'],
  }[key];
}

function settingsProviderFields(fields, section) {
  const shared = fields.filter(f => !settingsFieldBackends(f.key));
  const providers = fields.filter(f => settingsFieldBackends(f.key));
  return `${shared.map(settingsFieldRow).join('')}
    <div id="settings-${section}-selected"></div>
    <details id="settings-${section}-other" ${section === 'speech' ? 'ontoggle="settingsUpdateSpeechStatus()"' : ''}>
      <summary>Other ${section === 'writing' ? 'providers' : 'engines'}</summary>
      <div id="settings-${section}-alternatives">
        ${providers.map((f, i) => `<div data-settings-provider="${section}"
          data-backends="${settingsFieldBackends(f.key).join(' ')}" data-order="${i}">${settingsFieldRow(f)}</div>`).join('')}
      </div>
    </details>`;
}

function settingsUpdateProviders() {
  for (const [section, key] of [['writing', 'llm_backend'], ['speech', 'stt_engine']]) {
    const selected = $(`#set_${key}`)?.value;
    const host = $(`#settings-${section}-selected`);
    if (!host) continue; // The first-run wizard also uses settingsFieldRow.
    const alternatives = $(`#settings-${section}-alternatives`);
    const rows = [...document.querySelectorAll(`[data-settings-provider="${section}"]`)]
      .sort((a, b) => Number(a.dataset.order) - Number(b.dataset.order));
    rows.forEach(row => (row.dataset.backends.split(' ').includes(selected) ? host : alternatives).append(row));
    $(`#settings-${section}-other`).hidden = !alternatives.children.length;
    if (section === 'writing') $('#settings-local-check').hidden = selected !== 'lmstudio';
  }
  settingsUpdateSpeechStatus();
}

function settingsUpdateSpeechStatus() {
  const selected = $('#set_stt_engine')?.value;
  const showAll = $('#settings-speech-other')?.open;
  document.querySelectorAll('[data-stt-engine]').forEach(row => {
    row.hidden = !!selected && !showAll && row.dataset.sttEngine !== selected;
  });
}

function settingsSelectSection(section, scroll = true) {
  const id = SETTINGS_SECTIONS.some(([id]) => id === section) ? section : 'writing';
  const select = $('#settings-section-select');
  if (select) select.value = id;
  document.querySelectorAll('.settings-nav a').forEach(link => {
    if (link.hash === `#/settings/${id}`) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  if (scroll) {
    const heading = $(`#settings-${id}-heading`);
    heading?.focus({preventScroll: true});
    heading?.scrollIntoView({block: 'start'});
  }
}

async function renderSettings() {
  view.innerHTML = `<div class="empty-note">${loadingLine()}</div>`;
  let data;
  try { data = await api('/api/settings'); }
  catch (e) { view.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; return; }
  settingsDirty.clear();

  view.innerHTML = `
    <div id="settings-screen">
    <h1>Settings</h1>
    <p><a class="btn" href="#/setup">Run first-run setup again</a></p>
    <p class="sub">Set up writing, narration, research and rendering.
      Changes take effect the next time the app starts.</p>
    <p class="mono" style="color:var(--ink-faint);margin:-8px 0 22px">
      Data folder: ${esc(data.data_dir)}</p>
    <div class="settings-layout">
      <nav class="settings-nav" aria-label="Settings sections">
        ${SETTINGS_SECTIONS.map(([id, name]) => `<a href="#/settings/${id}">${name}</a>`).join('')}
      </nav>
      <label class="field settings-section-picker" for="settings-section-select"><span>Settings section</span>
        <select id="settings-section-select" onchange="go('#/settings/' + this.value)">
          ${SETTINGS_SECTIONS.map(([id, name]) => `<option value="${id}">${name}</option>`).join('')}
        </select>
      </label>
      <div id="settings-groups">
        ${SETTINGS_SECTIONS.map(([id, name]) => {
          const fields = data.fields.filter(f => f.group === name);
          let content;
          if (id === 'appearance') content = `
      <div class="micro">Theme · applies immediately</div>
      <div class="theme-options" role="group" aria-label="Theme">
        ${themeModes.map(mode => `<button type="button" class="btn" data-theme-choice="${mode}"
          aria-pressed="${themeMode() === mode}" onclick="setTheme('${mode}')">${mode[0].toUpperCase() + mode.slice(1)}</button>`).join('')}
      </div>
      <label class="field"><span>Display face</span>
        <select id="display-face" onchange="setDisplayFace(this.value)">
          <option value="archivo" ${document.documentElement.dataset.display !== 'grotesk' ? 'selected' : ''}>Archivo (condensed)</option>
          <option value="grotesk" ${document.documentElement.dataset.display === 'grotesk' ? 'selected' : ''}>Space Grotesk</option>
        </select>
      </label>
      `;
          else if (id === 'packs') content = '<div id="packs-screen"></div>';
          else if (id === 'writing' || id === 'speech') {
            const key = id === 'writing' ? 'llm_backend' : 'stt_engine';
            content = fields.filter(f => f.key === key).map(settingsFieldRow).join('') +
              settingsProviderFields(fields.filter(f => f.key !== key), id);
            content += id === 'writing' ? `<div id="settings-local-check">${localModelCheckRow()}</div>` :
              '<button class="btn" onclick="checkSpeechEngines(true)">Re-check engines</button><div id="stt-engines" role="status"></div>';
          } else content = fields.map(settingsFieldRow).join('');
          return `<section class="settings-section" aria-labelledby="settings-${id}-heading">
            <h2 id="settings-${id}-heading" tabindex="-1">${name}</h2><div class="panel">${content}</div></section>`;
        }).join('')}
      </div>
    </div>
    <div class="settings-save-bar">
      <button class="btn primary" onclick="saveSettingsForm()">Save settings</button>
      <span class="mono" id="settings-state" role="status"></span>
    </div></div>`;
  settingsUpdateProviders();
  await renderPacks();
  await checkSpeechEngines();
  const section = location.hash.split('/')[2];
  settingsSelectSection(section, !!section);
}

// LM Studio check: one request to the local server when clicked, never on load.
function localModelCheckRow() {
  return `<div class="field"><span>Local model</span>
    <div class="row"><button type="button" class="btn" onclick="checkLocalModel()">Check LM Studio</button>
      <button type="button" class="btn" id="local-speed-test" onclick="testLocalModelSpeed()">Test speed</button></div>
    <p class="mono" style="color:var(--dim)">Check sends no prompt. Test speed sends one short prompt to the saved server address; it may take a minute or two.</p>
    <div class="mono" id="local-model-state" role="status" style="color:var(--dim)"></div></div>`;
}

async function checkLocalModel() {
  const out = $('#local-model-state');
  if (!out) return;
  out.textContent = 'Checking…';
  try {
    const r = await api('/api/llm/local');
    const parts = [];
    if (r.reachable && r.model) parts.push(`Connected · ${r.model}${r.context ? ` · ${r.context.toLocaleString()}-token context` : ''}`);
    else if (r.reachable) parts.push('Connected');
    if (r.warning) parts.push(r.warning);
    if (r.reachable && r.models.length > 1) parts.push(`Available: ${r.models.map((m) => m.id + (m.loaded ? ' (loaded)' : '')).join(', ')}`);
    out.textContent = parts.join(' — ');
  } catch (e) { out.textContent = e.message; }
}

async function testLocalModelSpeed() {
  const out = $('#local-model-state');
  const button = $('#local-speed-test');
  if (!out || !button || button.disabled) return;
  button.disabled = true;
  out.textContent = 'Starting speed test…';
  try {
    const { job } = await api('/api/llm/local/speed', { method: 'POST' });
    while (out.isConnected) {
      const j = await api(`/api/jobs/${job}`);
      if (!out.isConnected) return;
      if (j.state === 'error') throw new Error(j.error || 'Speed test failed');
      if (j.state === 'done') {
        const r = j.result;
        out.textContent = `${r.model} · ${r.estimated ? 'estimated ' : ''}${r.tokens_per_second.toFixed(1)} tok/s · first token ${r.first_token_seconds.toFixed(2)} s · ${r.reasoning_tokens.toLocaleString()} reasoning / ${r.answer_tokens.toLocaleString()} answer tokens` +
          (r.advice.length ? ` — ${r.advice.join(' ')}` : ' — No speed or thinking changes recommended.');
        return;
      }
      out.textContent = j.status || 'Waiting for LM Studio…';
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
  } catch (e) { if (out.isConnected) out.textContent = e.message; }
  finally { button.disabled = false; }
}

async function saveSettingsForm() {
  const payload = {};
  for (const key of settingsDirty) {
    const el = document.querySelector(`[data-setting-key="${key}"]`);
    if (el) payload[key] = el.value;
  }
  if (!Object.keys(payload).length) return toast('Nothing changed');
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(payload) });
    toast('Saved — takes effect next launch');
    await renderSettings();
  } catch (e) { toast(e.message, true); }
}


function packLink(url) {
  try { return ['https:', 'http:'].includes(new URL(url).protocol) ? esc(url) : ''; }
  catch { return ''; }
}

async function renderPacks() {
  const host = $('#packs-screen');
  if (!host) return;
  try {
    const data = await api('/api/packs');
    host.innerHTML = `<button class="btn" onclick="$('#pack-file').click()">Install pack…</button>
      <input id="pack-file" type="file" accept=".corkboredpack" hidden
        onchange="installPackFile(this.files[0]);this.value=''">
      ${packLink(data.more_url) ? `<a href="${packLink(data.more_url)}" target="_blank" rel="noopener">Get more packs</a>` : ''}
      <p class="sub">Choose a pack file or drop it onto the window. Installed packs are available immediately.</p>
      ${data.packs.length ? data.packs.map(p => `<article class="panel" style="margin:12px 0">
        ${p.preview ? `<img src="${esc(p.preview)}" alt="${esc(p.name)} preview" style="width:240px;max-width:100%">` : ''}
        <p><strong>${esc(p.name || p.id)}</strong> · ${esc(p.version)} · ${esc(p.author)} ·
          ${esc(Object.entries(p.items).map(([kind, items]) => `${items.length} ${items.length === 1 ? kind.replace(/s$/, '') : kind}`).join(', '))}</p>
        <p>${esc(p.description)}</p>
        <p>${packLink(p.licence_url) ? `<a href="${packLink(p.licence_url)}" target="_blank" rel="noopener">${esc(p.licence)}</a>` : esc(p.licence)}</p>
        ${[...p.problems, ...Object.entries(p.item_problems).map(([ref, errors]) => `${ref}: ${errors.join('; ')}`)]
          .map(problem => `<p class="pill warn">${esc(problem)}</p>`).join('')}
        <details><summary>Show contents</summary><ul>${Object.entries(p.items).flatMap(([kind, items]) =>
          items.map(i => `<li>${esc(kind)}: ${esc(i.label)} <span class="mono">${esc(i.ref)}</span></li>`)).join('')}</ul></details>
        ${p.builtin ? '<span class="muted">Built in</span>' : `<button class="btn sm ghost" data-pack-id="${esc(p.id)}" onclick="removePack(this.dataset.packId)">Remove…</button>`}
      </article>`).join('') : '<p>No packs installed.</p>'}`;
  } catch (e) { host.textContent = e.message; }
}

async function refreshPackPickers() {
  state.templates = null;
  state.thumbStyles = null;
  state.endTemplates = null;
  state.models = null;
  state.themes = await api('/api/themes');
}

async function installPackFile(file, replace = false) {
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  form.append('replace', String(replace));
  toast(`Installing ${file.name}…`);
  try {
    const p = await api('/api/packs/install', {method: 'POST', body: form});
    await refreshPackPickers();
    toast(`Installed ${p.name} · ${p.version}`);
    if ($('#packs-screen')) await renderPacks();
    else go('#/settings');
  } catch (e) {
    if (e.status === 409 && e.detail?.replace_required && await appConfirm({title: 'Replace pack?', body: e.message,
      ok: 'Replace', danger: true})) {
      return installPackFile(file, true);
    }
    toast(e.message, true);
  }
}

async function removePack(id) {
  try {
    const uses = await api(`/api/packs/${encodeURIComponent(id)}/uses`);
    const lines = [...uses.channels.map(c => `Channel: ${c.name}`), ...uses.projects.map(p => `Project: ${p.name}`)];
    if (!await appConfirm({title: 'Remove pack?', body: `${lines.length ? lines.join('\n') : 'No channels or projects use this pack.'}\n\nRemove ${id}? Its folder will be kept. Missing items fall back to defaults.`,
      ok: 'Remove', danger: true})) return;
    await api(`/api/packs/${encodeURIComponent(id)}`, {method: 'DELETE'});
    await refreshPackPickers();
    await renderPacks();
    toast('Pack removed. Its folder was kept.');
  } catch (e) { toast(e.message, true); }
}


async function checkSpeechEngines(refresh = false) {
  const host = $('#stt-engines');
  if (!host) return;
  try {
    const engines = await api(`/api/stt/engines?refresh=${refresh}`);
    if (!host.isConnected) return;
    host.innerHTML = `<p class="sub">Optional. Save settings and restart to use changed paths or defaults.</p>` +
      Object.entries(engines).map(([name, info], index) => `<div class="field" data-stt-engine="${esc(name)}" style="margin-bottom:22px;padding-bottom:14px;border-bottom:1px solid var(--line)"><strong>${esc(name)} · ${info.installed ? 'Installed' : 'Not found'}</strong>
        <p class="mono">${esc([info.version, info.device, info.notes].filter(Boolean).join(' · '))}</p>
        <p class="mono">Last runtime: ${esc(info.runtime ? `${info.runtime.version || 'Version unknown'} · ${info.runtime.device || 'Device unknown'}` : 'Not run in this session')}</p>
        <p class="mono">Models: ${esc(info.models.join(', ') || 'No local models found')}</p>
        <a href="${esc(info.install_url)}" target="_blank" rel="noopener">Install instructions</a>
        ${(info.downloads || []).length ? `<div class="row"><label for="stt-download-${index}">Model to download</label><select id="stt-download-${index}">${info.downloads.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join('')}</select><button class="btn" data-stt-download="${esc(name)}" data-select="stt-download-${index}">Download model</button></div><p class="sub">Downloads use the whisper.cpp folder active when the app started (default ~/.cache/whisper.cpp). Save and restart before downloading to a changed folder. Existing models are kept. Choose the downloaded path as your default, save and restart.</p><div data-download-status role="status"></div>` : '<p class="sub">Use the engine’s instructions to obtain a model, then choose its local path above.</p>'}</div>`).join('');
    host.querySelectorAll('[data-stt-download]').forEach(button => {
      button.onclick = () => downloadSpeechModel(button);
    });
    settingsUpdateSpeechStatus();
  } catch (e) { host.textContent = e.message; }
}

async function downloadSpeechModel(button) {
  const status = button.closest('.field').querySelector('[data-download-status]');
  button.disabled = true;
  try {
    const model = document.getElementById(button.dataset.select).value;
    const {job} = await api('/api/stt/download', {method:'POST', body:JSON.stringify({
      engine:button.dataset.sttDownload, model, confirm:true})});
    status.innerHTML = '<progress aria-label="Model download progress"></progress> <span class="mono" data-progress></span> <button class="btn sm">Cancel download</button>';
    const cancel = status.querySelector('button');
    cancel.onclick = async () => {
      try { await api(`/api/jobs/${job}/cancel`, {method:'POST'}); cancel.disabled = true; }
      catch(e) { toast(e.message, true); }
    };
    while (true) {
      const current = await api(`/api/jobs/${job}`);
      if (status.isConnected) {
        const message = current.log?.at(-1)?.m || current.state;
        status.querySelector('[data-progress]').textContent = message;
        const counts = message.match(/(\d+) of (\d+) bytes/);
        if (counts && Number(counts[2]) > 0) {
          const bar = status.querySelector('progress');
          bar.max = Number(counts[2]); bar.value = Number(counts[1]);
        }
      }
      if (current.state !== 'running') {
        status.textContent = current.state === 'done' ? `Downloaded: ${current.result.model}. Set the default model path above.` :
          current.state === 'cancelled' ? 'Download cancelled.' : current.error;
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  } catch (e) { status.textContent = e.message; }
  finally { button.disabled = false; }
}

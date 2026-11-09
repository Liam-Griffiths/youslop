// A route, not a gate: Skip and Finish later always leave a way forward.
const SETUP_STEPS = ['Where projects live', 'Writing model', 'A voice for drafts', 'Research', 'YouTube'];
let setupStep = 0;
let setupData = null;

async function renderSetup(step = 0) {
  setupStep = step;
  view.innerHTML = '<p class="sub">Checking this computer…</p>';
  try {
    const [checks, settings] = await Promise.all([api('/api/setup'), api('/api/settings')]);
    if (location.hash !== '#/setup') return;
    setupData = checks;
    settingsDirty.clear();
    const groups = {1: ['Writing model'], 3: ['Research'], 4: ['Publishing']};
    const fields = settings.fields.filter(f => (groups[step] || []).includes(f.group));
    const descriptions = [
      'Projects, recordings and model files stay in your data folder.',
      'Choose which model researches and writes: Claude, or a local model on your own machines. These checks detect configuration; they do not make a model call or verify sign-in.',
      'A local voice lets you hear the cut before recording it yourself. You can use your own recordings instead.',
      'Choose a search backend for research. DuckDuckGo needs no key. No search runs during setup.',
      'Publishing is optional. Connect YouTube from a channel after saving your Google credentials and restarting.'
    ];
    const states = [checks.paths.data, `${checks.llm.resolved} · configuration detected`,
      checks.tts.ready ? 'Ready' : 'Not ready', 'Optional', checks.youtube.connected ? 'Connected' : 'Optional'];
    let content = fields.map(settingsFieldRow).join('');
    if (step === 1) content = `<p class="mono">Backend: ${esc(checks.llm.resolved)} · CLI ${checks.llm.cli_found ? 'found (sign-in not checked)' : 'not found'}</p>
      <p class="sub">For the CLI backend, install Claude Code and sign in outside the app. For the API backend, enter your key below.
      To write with a free local model instead, open LM Studio, load a model, start its server (Developer tab), then choose LM Studio below.</p>` + content + localModelCheckRow();
    if (step === 0) content = `<label class="field"><span>Data folder</span>
      <input type="text" class="mono" readonly value="${esc(checks.paths.data)}"></label>
      <p class="sub">To use another folder, set CORKBORED_DATA before launching the app. Keep your existing data folder when upgrading.</p>`;
    if (step === 2) {
      const t = checks.tts;
      const base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0';
      content = `<strong>Kokoro · local voice</strong><p class="mono">${t.ready ? 'Ready' : esc(t.detail)}</p>
        ${!t.weights ? `<p class="sub">Download both files, then place them at these paths. Nothing downloads until you click.</p>
          <p><a class="btn" href="${base}/kokoro-v1.0.onnx" rel="noopener" target="_blank">Download voice model</a></p>
          <p class="mono setup-path">${esc(t.model_path)}</p>
          <p><a class="btn" href="${base}/voices-v1.0.bin" rel="noopener" target="_blank">Download voice data</a></p>
          <p class="mono setup-path">${esc(t.voices_path)}</p>` : ''}
        <p class="sub">${t.ready ? 'Choose a voice in the Voice stage.' : 'Refresh checks after installing the missing files or package.'}</p>`;
    }
    if (step === 4) content += `<p class="mono">YouTube: ${checks.youtube.connected ? 'connected' : 'not connected'}</p>
      <a class="btn" href="#/channels">Open channels to connect YouTube</a>`;
    view.innerHTML = `<div class="setup-screen"><nav aria-label="Setup steps" class="setup-steps">
      ${SETUP_STEPS.map((name, i) => `<button type="button" class="setup-step" ${i === step ? 'aria-current="step"' : ''}
        onclick="setupAdvance(${i})"><span class="mono setup-number">${i + 1}</span><span>${name}<small>${esc(states[i])}</small></span></button>`).join('')}
      <a class="btn ghost" href="#/">Finish later</a></nav>
      <section class="setup-work" aria-labelledby="setup-heading">
        <p class="mono sub">Setup · step ${step + 1} of ${SETUP_STEPS.length}</p>
        <h1 id="setup-heading" tabindex="-1">${SETUP_STEPS[step]}</h1><p class="sub">${descriptions[step]}</p>
        <div class="panel">${content}</div>
        ${fields.length ? '<p class="sub">Continue saves only fields you change. Restart the app to apply configuration changes.</p>' : ''}
        <div class="row"><h2>System checks</h2><div class="spacer"></div>
          <button type="button" class="btn sm" onclick="refreshSetupChecks()">Refresh checks</button></div>
        <div id="setup-checks" class="setup-checks" aria-live="polite"></div>
        <div class="row setup-actions">
          ${step ? `<button type="button" class="btn" onclick="setupAdvance(${step - 1})">Back</button>` : ''}
          <button type="button" class="btn ghost" onclick="setupAdvance(${step + 1}, false)">Skip</button>
          <div class="spacer"></div><button type="button" class="btn primary" onclick="setupAdvance(${step + 1})">${step === 4 ? 'Finish setup' : 'Continue'}</button>
        </div></section></div>`;
    paintSetupChecks();
    $('#setup-heading').focus();
  } catch (e) {
    view.innerHTML = `<p>${esc(e.message)}</p><a class="btn" href="#/">Finish later</a>`;
  }
}

function paintSetupChecks() {
  if (!$('#setup-checks')) return;
  const c = setupData;
  const mic = !!navigator.mediaDevices;
  const rows = [
    ['ffmpeg', c.ffmpeg.ready ? c.ffmpeg.detail.replace(/\s*Copyright[\s\S]*$/, '') : `${c.ffmpeg.detail}. Install ffmpeg with libx264.`],
    ['Speech-to-text', c.stt?.detail || 'none installed (optional)'],
    ['Chromium', c.chromium.ready ? c.chromium.path : c.chromium.detail],
    ['Graphics / RAM', `${c.system.available_ram_mb == null ? 'RAM unavailable' : `${Math.round(c.system.available_ram_mb)} MB RAM available`} · GPU not probed`],
    ['Microphone', mic ? 'Browser support detected · set up later in Voice' : 'Browser support unavailable · try localhost in a system browser']
  ];
  $('#setup-checks').innerHTML = rows.map(([name, detail]) => `<div class="panel"><strong>${esc(name)}</strong><p class="mono sub">${esc(detail)}</p></div>`).join('');
}

async function refreshSetupChecks() {
  try {
    if (setupStep === 2) return await renderSetup(2);
    setupData = await api('/api/setup'); paintSetupChecks();
  }
  catch (e) { toast(e.message, true); }
}

async function setupAdvance(next, save = true) {
  try {
    const payload = {};
    if (save) for (const key of settingsDirty) {
      const field = $(`#set_${key}`);
      if (field) payload[key] = field.value;
    }
    if (next >= SETUP_STEPS.length) payload.setup_complete = 'true';
    if (Object.keys(payload).length) await api('/api/settings', {method: 'POST', body: JSON.stringify(payload)});
    if (next >= SETUP_STEPS.length) go('#/');
    else await renderSetup(next);
  } catch (e) { toast(e.message, true); }
}

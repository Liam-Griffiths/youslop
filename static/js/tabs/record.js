
// ------------------------------------------------------------------ record
function paintRecord() {
  if (cameraMode()) return paintCameraRecord();
  const p = state.project;
  const i = Math.min(state.rec.index, p.slides.length - 1);
  state.rec.index = i;
  const s = p.slides[i];
  if (!s) { $('#tabbody').innerHTML = '<div class="empty-note">Nothing to read yet — write a script first.</div>'; return; }
  const ai = (p.narrator || {}).mode === 'ai';
  // The voice being worked on here — the microphone, or the AI engine picked
  // below. Its reads are kept apart from every other voice's, and the video
  // uses whichever one is chosen in the voice bar, which need not be this one.
  const track = ai ? narratorEngine(p) : 'mic';
  const tk = (x) => (x.takes || {})[track];
  const done = p.slides.filter(tk).length;
  const take = tk(s);

  $('#tabbody').innerHTML = `
    <div class="voice-studio">
    ${voiceParagraphList(p)}
    <section class="voice-work" aria-label="Prompter">
    <div class="voice-meta">¶${i + 1} · ${done} of ${p.slides.length} ${ai ? 'drafted' : 'recorded'} · ${fmtTime(p.recorded_seconds)} in the can</div>
    <details class="voice-options" ${ai && done < p.slides.length ? 'open' : ''}><summary>Voice &amp; draft settings</summary>
    ${recordModeSwitch()}
    ${voiceBar(p, track)}

    <div class="row" style="margin:14px 0 0;gap:6px">
      <button class="btn sm ${ai ? 'ghost' : 'selected'}"
        onclick="setNarrator({mode:'mic'})">read it yourself</button>
      <button class="btn sm ${ai ? 'selected' : 'ghost'}"
        onclick="setNarrator({mode:'ai'})">Narrator</button>
      <span class="mono" style="color:var(--ink-faint)">${ai
        ? (narratorEngine(p) === 'kokoro'
            ? 'A model on this machine reads the script. Nothing leaves the computer.'
            : `${esc(engineInfo(narratorEngine(p)).label || 'A voice service')} reads the script, billed to your account.`)
        : 'You read it into a microphone.'}</span>
    </div>

    ${ai ? aiVoicePanel(p, s) : ''}
    </details>

    ${ai || micAvailable() ? '' : `
      <div class="panel warn-panel" style="margin-top:14px">
        <strong>This browser will not open a microphone here.</strong>
        <div class="mono" style="margin-top:6px;color:var(--ink-dim)">
          A microphone is only handed to a page on <b>https</b> or on
          <b>localhost</b>, and this page is
          <b>${esc(location.protocol.replace(':', ''))}://${esc(location.hostname)}</b>.
          Everything else on this tab works; only recording is blocked.
        </div>
        <div class="mono" style="margin-top:10px;color:var(--ink-faint)">
          Restart the server with <b>HOST=0.0.0.0 HTTPS=1 ./run.sh</b> and open the
          https address it prints (accept the certificate warning once), or tunnel
          the port so this machine sees it as localhost:<br>
          <b>ssh -N -L 8420:localhost:8420 you@the-mac</b>
        </div>
      </div>`}

    ${voicePrompter(s)}

    ${ai ? '' : `
    <div class="row" style="margin:12px 0 -4px">
      <button class="btn sm" onclick="openMicPanel()"
        ${micAvailable() ? '' : 'disabled'}>Microphone setup</button>
      <span class="mono" style="color:var(--ink-faint)">${esc(voiceSummary())}</span>
    </div>`}

    ${ai ? `
    <div class="rec-bar">
      <button class="btn" onclick="voiceOneSlide()">${take ? 'Re-draft' : 'Draft'} this paragraph</button>
      ${take ? `<span class="pill on num"><span class="dot"></span>${take.duration.toFixed(1)}s${
        take.synthetic ? ` · ${esc(voiceLabel(take.voice))}` : ' · your voice'}</span>` : ''}
    </div>` : `
    <div class="rec-bar">
      <button class="btn rec ${state.rec.recording ? 'armed' : ''}" id="recbtn"
        ${micAvailable() ? '' : 'disabled'} onclick="toggleRec()">
        ${state.rec.recording ? '■ Stop' : take ? '● Retake' : '● Record'}</button>
      <span class="timer ${state.rec.recording ? 'live' : ''}" id="timer">0:00</span>
      <div class="level" role="meter" aria-label="Input peak" aria-valuemin="-80" aria-valuemax="0"><i id="level"></i></div><span class="mono" id="voice-peak">Peak — dB</span>
      ${take ? `<span class="pill on num"><span class="dot"></span>${take.duration.toFixed(1)}s</span>` : ''}
      ${!state.rec.stream && micAvailable()
        ? `<button class="btn sm ghost" onclick="openMic()">check the microphone</button>` : ''}
      ${state.mic.report && state.mic.report.analysis.ok
        ? `<span class="pill ${state.mic.report.analysis.room_score >= 50 ? 'on' : 'warn'}"
             title="measured in the mic panel">room: ${esc(state.mic.report.analysis.verdict)}</span>` : ''}
    </div>`}

    <div class="rec-nav">
      <button class="btn sm" onclick="jumpTake(-1)" ${i === 0 ? 'disabled' : ''}>← previous</button>
      <button class="btn sm" onclick="jumpTake(1)" ${i >= p.slides.length - 1 ? 'disabled' : ''}>next →</button>
      ${take ? `<button class="btn sm ghost" onclick="playTake()">play back</button>
                  <button class="btn sm ghost" onclick="dropTake()">retire to history</button>` : ''}
      <div class="spacer"></div>
      ${done && !ai ? `<button class="btn sm ghost" onclick="recleanTakes()"
        title="run every take through the current voice chain again, from the raw recording"
        >re-clean all takes</button>` : ''}
      <button class="btn sm ghost" onclick="jumpNextUnrecorded()">jump to next blank</button>
    </div>
    ${ai ? '' : `
    <div class="row" style="margin-top:12px;color:var(--ink-faint);font-size:12.5px">
      <kbd>space</kbd> record / stop &nbsp; <kbd>→</kbd> next &nbsp; <kbd>←</kbd> back &nbsp;
      <kbd>p</kbd> play back &nbsp; <kbd>r</kbd> retire to history
    </div>`}

    ${voiceNextUp(p, i)}
    ${voicePresenterOptions(p)}
    </section>${voiceTakesPanel(p, s)}</div>
    <audio id="player" style="display:none"></audio>`;

  if (ai) {
    watchSayDraft();
    // The channel's entries apply too, and are only shown as a count here.
    if (p.channel_id && state.channelLexicon === undefined) {
      state.channelLexicon = [];
      api(`/api/channels/${p.channel_id}`).then((c) => {
        state.channelLexicon = c.lexicon || [];
        if (state.tab === 'record') paintRecord();
      }).catch(() => {});
    }
  }

  // If this browser has already been given permission, the device labels are
  // readable now and the picker can appear before the first take.
  if (state.rec.mics === undefined && micAvailable()) {
    state.rec.mics = [];
    listMics().then((mics) => {
      if (mics.some((m) => m.label)) {
        state.rec.mics = mics;
        if (!state.rec.recording && state.tab === 'record') paintRecord();
      }
    });
  }
}

// ------------------------------------------------------------- the AI reader
// Loaded once: whether the local model is installed, and the voices it offers.
function showCommand(platform) {
  const cmdText = $('code#cmd-text');
  const noteEl = $('#cmd-note');
  if (!cmdText) return;

  cmdText.textContent = 'pip install kokoro-onnx soundfile';

  let note = '';
  if (platform === 'windows') {
    note = 'Run in PowerShell or Command Prompt. If using the Corkbored desktop app, run this in your system terminal (not within the app).';
  } else {
    note = 'Run in your terminal (bash, zsh, etc.). If using the Corkbored desktop app, run this in your system terminal (not within the app).';
  }

  if (noteEl && note) {
    noteEl.textContent = note;
    noteEl.style.display = 'block';
  }
}

function copyInstallCommand() {
  const cmdText = $('code#cmd-text');
  if (!cmdText) return;
  const text = cmdText.textContent;
  navigator.clipboard.writeText(text).then(() => {
    toast('Copied to clipboard');
  }).catch(() => {
    toast('Failed to copy', true);
  });
}

async function loadTTS() {
  if (state.tts) return state.tts;
  state.tts = await api('/api/tts').catch(() => ({ ready: false, voices: [],
    detail: 'Could not reach the voice engine.' }));
  return state.tts;
}

function voiceLabel(id) {
  const lists = [((state.tts || {}).voices || []),
    ...Object.values(state.cloudVoices || {}).filter(Array.isArray)];
  for (const list of lists) {
    const v = list.find((x) => x.id === id);
    if (v) return v.label;
  }
  return id || 'a voice';
}

const narratorEngine = (p) => ((p || state.project).narrator || {}).engine || 'kokoro';
const engineInfo = (key) => (((state.tts || {}).engines) || []).find((e) => e.key === key) || {};

// Which model reads it: this machine, or a hosted voice service. A row of
// switches above the panel for whichever one is chosen.
function aiVoicePanel(p, slide) {
  const t = state.tts;
  if (!t) { loadTTS().then(() => { if (state.tab === 'record') paintRecord(); });
            return '<div class="panel" style="margin-top:14px">Checking the voice engine…</div>'; }
  const engine = narratorEngine(p);
  const engines = t.engines || [{ key: 'kokoro', label: 'On this computer', ready: t.ready }];
  const tabs = `<div class="row" style="margin:14px 0 0;gap:6px;flex-wrap:wrap">
    ${engines.map((e) => `<button class="btn sm ${e.key === engine ? 'selected' : 'ghost'}"
        onclick="setNarrator({engine:'${e.key}'})"
        title="${esc(e.blurb || '')}">${esc(e.label)}${e.ready ? '' : ' · not set up'}</button>`).join('')}
  </div>`;
  return tabs + (engine === 'kokoro' ? localVoicePanel(p, slide)
                                      : cloudVoicePanel(p, engineInfo(engine)));
}

// How far each take is from what the narrator is set to now: read in another
// engine, voice, pace or model means it needs reading again.
function staleTakes(p) {
  const n = p.narrator || {};
  const engine = narratorEngine(p);
  const e = engineInfo(engine);
  const model = engine === 'kokoro' ? '' : (n.model || ((e.models || [])[0] || {}).id || '');
  const lo = (e.speed || [0.5, 1.5])[0], hi = (e.speed || [0.5, 1.5])[1];
  const speed = Math.min(hi, Math.max(lo, n.speed));
  return p.slides.filter((x) => {
    // Only this engine's own reads: another voice's are kept, not stale.
    const tk = (x.takes || {})[engine] || {};
    if (!tk.synthetic) return false;
    return tk.voice !== n.voice
      || Math.abs((tk.speed || 1) - speed) > 0.011 || (tk.model || '') !== model;
  }).length;
}

function cloudVoicePanel(p, e) {
  if (!e.ready) {
    return `<div class="panel warn-panel" style="margin-top:14px">
      <strong>${esc(e.label)} isn't set up yet.</strong>
      <div class="mono" style="margin-top:6px;color:var(--ink-dim)">${esc(e.blurb || '')}</div>
      <div class="row" style="margin-top:10px">
        <a class="btn sm primary" href="#/settings">add your ${esc(e.label)} API key in Settings</a>
        <span class="mono" style="color:var(--ink-faint)">it works as soon as it's saved — no restart</span>
      </div>
    </div>`;
  }
  state.cloudVoices = state.cloudVoices || {};
  const list = state.cloudVoices[e.key];
  if (list === undefined) {
    state.cloudVoices[e.key] = null;
    api(`/api/tts/voices/${e.key}`)
      .then((v) => { state.cloudVoices[e.key] = v; })
      .catch((err) => { state.cloudVoices[e.key] = { error: err.message }; })
      .then(() => { if (state.tab === 'record') paintRecord(); });
  }
  if (!list) return `<div class="panel" style="margin-top:14px">Fetching ${esc(e.label)} voices…</div>`;
  if (list.error) {
    return `<div class="panel warn-panel" style="margin-top:14px">
      <strong>Couldn't list the ${esc(e.label)} voices.</strong>
      <div class="mono" style="margin-top:6px;user-select:text">${esc(list.error)}</div>
      <button class="btn sm" style="margin-top:10px"
        onclick="state.cloudVoices['${e.key}']=undefined;paintRecord()">try again</button>
    </div>`;
  }
  const n = p.narrator || {};
  const read = p.slides.filter((x) => (x.takes || {})[narratorEngine(p)]).length;
  const stale = staleTakes(p);
  const chars = p.slides.reduce((a, x) => a + (x.narration || '').trim().length, 0);
  const groups = {};
  list.forEach((v) => { (groups[v.accent || 'Voices'] = groups[v.accent || 'Voices'] || []).push(v); });
  const [lo, hi] = e.speed || [0.7, 1.2];
  const speed = Math.min(hi, Math.max(lo, n.speed));
  const known = list.some((v) => v.id === n.voice);

  return `<div class="panel" style="margin-top:14px">
    <div class="row" style="margin-bottom:10px">
      <strong>The voice</strong>
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">${read} of ${p.slides.length} read${
        stale ? ` · ${stale} in another voice or setting` : ''}</span>
    </div>
    ${known ? '' : `<div class="mono" style="color:var(--ink-faint);margin-bottom:8px">
      Reading as <b>${esc(n.voice)}</b>, which isn't in this account's list — pick one below.</div>`}
    ${e.key === 'elevenlabs' ? `
      <div class="row" style="gap:10px;margin-bottom:10px">
        <button class="btn sm" onclick="openVoiceLibrary()">browse the ElevenLabs voice library…</button>
        <span class="mono" style="color:var(--ink-faint)">the thousands of voices on their
          website — hear any of them, then add one to your account to read with</span>
      </div>` : ''}
    <div style="max-height:420px;overflow:auto">
    ${Object.entries(groups).map(([group, vs]) => `
      <div class="mono" style="color:var(--ink-faint);margin:8px 0 6px">${esc(group)}</div>
      <div class="voice-grid">
        ${vs.map((v) => `
          <div class="voice-card ${v.id === n.voice ? 'sel' : ''}"
               onclick="setNarrator({voice:'${esc(v.id)}'})">
            <div class="row" style="gap:6px">
              <strong>${esc(v.label)}</strong>
              <div class="spacer"></div>
              <button class="btn xs ghost" onclick="event.stopPropagation();hearVoice('${esc(v.id)}')"
                >hear</button>
            </div>
            <div class="mono voice-note">${esc(v.note || v.sex || '')}</div>
          </div>`).join('')}
      </div>`).join('')}
    </div>

    <div class="grid-2" style="margin-top:14px">
      <label class="field"><span>Model</span>
        <select onchange="setNarrator({model:this.value})">
          ${(e.models || []).map((m, i) => `<option value="${esc(m.id)}"
            ${(n.model || (e.models[0] || {}).id) === m.id ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}
        </select></label>
      <label class="field"><span>Pace — <b>${speed.toFixed(2)}×</b></span>
        <input type="range" min="${lo}" max="${hi}" step="0.01" value="${speed}"
          onchange="setNarrator({speed:+this.value})"></label>
    </div>

    <div class="row" style="margin-top:12px">
      <button class="btn" onclick="voiceWholeScript()">
        ${read ? (stale ? `re-read ${stale} paragraph${stale === 1 ? '' : 's'}`
                        : 'read anything still blank') : 'read the whole script'}</button>
      ${read ? `<button class="btn sm ghost" onclick="voiceWholeScript(true)"
        title="re-read every paragraph, including ones already done">read it all again</button>` : ''}
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">the whole script is
        ${chars.toLocaleString()} characters, billed to your ${esc(e.label)} account</span>
    </div>
    <audio id="voiceplayer" style="display:none"></audio>
  </div>

  ${pronunciationPanel(p)}`;
}

// ElevenLabs' shared Voice Library, searched from here. A library voice has to
// be added to the account before the API will read with it, so "use" adds it
// and then picks it — the same thing "Add to my voices" does on their site.
function openVoiceLibrary() {
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box" style="width:min(980px,100%)">
      <div class="row" style="margin-bottom:12px">
        <strong>ElevenLabs voice library</strong>
        <span class="mono" style="color:var(--ink-faint)">English voices, most popular first</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="vlclose">close</button>
      </div>
      <div class="row" style="gap:8px;margin-bottom:12px;flex-wrap:wrap">
        <input type="text" id="vlq" placeholder="deep, documentary, british, calm…" style="flex:1;min-width:200px">
        <select id="vlgender"><option value="">any voice</option><option value="male">male</option>
          <option value="female">female</option><option value="neutral">neutral</option></select>
        <select id="vluse"><option value="narrative_story">Narration &amp; story</option></select>
        <input type="text" id="vlaccent" placeholder="accent (american, british…)" style="width:190px">
        <button class="btn sm primary" id="vlgo">search</button>
      </div>
      <div id="vlresults" class="voice-grid" style="max-height:60vh;overflow:auto">
        <div class="empty-note" style="grid-column:1/-1">Looking…</div>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="btn sm ghost" id="vlmore" style="display:none">more</button>
        <div class="spacer"></div>
        <span class="mono" style="color:var(--ink-faint)">Adding a voice uses one of your
          ElevenLabs plan's custom voice slots, as it does on their site.</span>
      </div>
      <audio id="vlplayer" style="display:none"></audio>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { const el = wrap.querySelector('#vlplayer'); if (el) el.pause(); wrap.remove(); };
  wrap.querySelector('#vlclose').onclick = close;
  wrap.addEventListener('click', (ev) => { if (ev.target === wrap) close(); });
  const results = wrap.querySelector('#vlresults');
  const more = wrap.querySelector('#vlmore');
  let page = 0;
  let found = [];

  const card = (v, n) => `
    <div class="voice-card">
      <div class="row" style="gap:6px">
        <strong>${esc(v.label)}</strong>
        <div class="spacer"></div>
        ${v.preview_url ? `<button class="btn xs ghost" data-hear="${n}">hear</button>` : ''}
        <button class="btn xs" data-use="${n}">use</button>
      </div>
      <div class="mono voice-note">${esc([v.sex, v.age, v.accent, v.use_case].filter(Boolean).join(' · '))}</div>
      ${v.note ? `<div class="mono voice-note" style="margin-top:4px">${esc(v.note)}</div>` : ''}
    </div>`;

  const run = async (append) => {
    if (!append) { page = 0; found = []; results.innerHTML = '<div class="empty-note" style="grid-column:1/-1">Looking…</div>'; }
    const q = new URLSearchParams({
      q: wrap.querySelector('#vlq').value, gender: wrap.querySelector('#vlgender').value,
      use_case: wrap.querySelector('#vluse').value, accent: wrap.querySelector('#vlaccent').value,
      page: String(page) });
    try {
      const r = await api(`/api/tts/library?${q}`);
      const sel = wrap.querySelector('#vluse');
      if (sel.options.length < 2 && r.use_cases) {
        const cur = sel.value;
        sel.innerHTML = r.use_cases.map((u) => `<option value="${esc(u.id)}"
          ${u.id === cur ? 'selected' : ''}>${esc(u.label)}</option>`).join('');
      }
      found = found.concat(r.voices);
      results.innerHTML = found.length ? found.map(card).join('')
        : '<div class="empty-note" style="grid-column:1/-1">Nothing matched. Try fewer words.</div>';
      more.style.display = r.has_more ? '' : 'none';
    } catch (err) {
      results.innerHTML = `<div class="empty-note" style="grid-column:1/-1;user-select:text">${esc(err.message)}</div>`;
    }
  };
  results.addEventListener('click', async (ev) => {
    const hear = ev.target.closest('[data-hear]');
    const use = ev.target.closest('[data-use]');
    if (hear) {
      const el = wrap.querySelector('#vlplayer');
      el.src = found[+hear.dataset.hear].preview_url;
      el.play().catch(() => toast('Could not play that preview.', true));
    } else if (use) {
      const v = found[+use.dataset.use];
      use.disabled = true; use.textContent = 'adding…';
      try {
        const r = await api('/api/tts/library/add', { method: 'POST',
          body: JSON.stringify({ owner: v.owner, id: v.id, name: v.label }) });
        state.cloudVoices.elevenlabs = undefined;     // the account's list changed
        close();
        await setNarrator({ voice: r.voice_id });
        toast(`${v.label} added to your ElevenLabs voices and picked`);
      } catch (err) { toast(err.message, true); use.disabled = false; use.textContent = 'use'; }
    }
  });
  wrap.querySelector('#vlgo').onclick = () => run(false);
  wrap.querySelector('#vlq').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') run(false); });
  more.onclick = () => { page += 1; run(true); };
  run(false);
}

function localVoicePanel(p, slide) {
  const t = state.tts;
  if (!t.ready) {
    const isMissing = t.detail && t.detail.includes('missing');
    let setupGuide = '';
    if (t.detail && t.detail.includes('pip install')) {
      setupGuide = `
        <div style="margin-top:10px">
          <strong style="font-size:13px">Installation:</strong>
          <div style="margin-top:6px;font-size:12px;color:var(--ink-faint)">Copy the command for your system:</div>
          <div class="row" style="margin-top:8px;gap:6px;flex-wrap:wrap">
            <label style="flex:1;min-width:160px">
              <input type="radio" name="platform" value="linux-mac" checked onchange="showCommand(this.value)">
              Linux / macOS
            </label>
            <label style="flex:1;min-width:160px">
              <input type="radio" name="platform" value="windows" onchange="showCommand(this.value)">
              Windows (PowerShell)
            </label>
          </div>
          <div id="install-cmd" style="margin-top:8px;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:8px;position:relative">
            <code style="color:var(--good);font-size:12px;font-family:monospace;display:block;overflow-x:auto;padding-right:50px" id="cmd-text">pip install kokoro-onnx soundfile</code>
            <button class="btn xs ghost" onclick="copyInstallCommand()" style="position:absolute;top:4px;right:4px">copy</button>
          </div>
          <div id="cmd-note" style="margin-top:6px;font-size:12px;color:var(--ink-faint);display:none"></div>
          <script>showCommand('linux-mac')</script>
        </div>
      `;
    } else if (isMissing) {
      // The folder is the per-user data folder in a packaged app, not the
      // source checkout's assets/tts, so it is spelled out rather than left
      // to the README.
      const dir = t.model_path.replace(/[\\/][^\\/]+$/, '');
      const base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0';
      const q = (s) => `"${s}"`;
      // In PowerShell `curl` is Invoke-WebRequest and `mkdir -p` is not a
      // thing; curl.exe ships with Windows 10 and later.
      const win = t.model_path.includes('\\');
      const cmd = [
        win ? `New-Item -ItemType Directory -Force -Path ${q(dir)}` : `mkdir -p ${q(dir)}`,
        `${win ? 'curl.exe' : 'curl'} -L -o ${q(t.model_path)} ${base}/kokoro-v1.0.onnx`,
        `${win ? 'curl.exe' : 'curl'} -L -o ${q(t.voices_path)} ${base}/voices-v1.0.bin`,
      ].join('\n');
      setupGuide = `
        <div style="margin-top:10px;font-size:12px;color:var(--ink-faint)">
          Two model files (~337MB) need to be downloaded into
          <code class="mono" style="user-select:all">${esc(dir)}</code>
        </div>
        <div style="margin-top:8px;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:8px;position:relative">
          <pre style="margin:0;color:var(--good);font-size:12px;font-family:monospace;overflow-x:auto;padding-right:50px" id="weights-cmd">${esc(cmd)}</pre>
          <button class="btn xs ghost" style="position:absolute;top:4px;right:4px"
            onclick="navigator.clipboard.writeText($('#weights-cmd').textContent).then(() => toast('Copied to clipboard'), () => toast('Failed to copy', true))">copy</button>
        </div>
        <div style="margin-top:6px;font-size:12px;color:var(--ink-faint)">Run in a terminal, then restart Corkbored.</div>`;
    } else if (t.detail) {
      setupGuide = `<div style="margin-top:10px;font-size:12px;color:var(--ink-faint);user-select:text">${esc(t.detail)}</div>`;
    }
    return `<div class="panel warn-panel" style="margin-top:14px">
      <strong>The local voice model is not ready.</strong>
      ${setupGuide}
    </div>`;
  }
  const n = p.narrator || {};
  const read = p.slides.filter((x) => (x.takes || {})[narratorEngine(p)]).length;
  const stale = staleTakes(p);
  const byAccent = {};
  t.voices.forEach((v) => { (byAccent[v.accent] = byAccent[v.accent] || []).push(v); });

  return `<div class="panel" style="margin-top:14px">
    <div class="row" style="margin-bottom:10px">
      <strong>The voice</strong>
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">${read} of ${p.slides.length} read${
        stale ? ` · ${stale} in an older voice` : ''}</span>
    </div>
    ${Object.entries(byAccent).map(([accent, list]) => `
      <div class="mono" style="color:var(--ink-faint);margin:8px 0 6px">${esc(accent)}</div>
      <div class="voice-grid">
        ${list.map((v) => `
          <div class="voice-card ${v.id === n.voice ? 'sel' : ''}"
               onclick="setNarrator({voice:'${v.id}'})">
            <div class="row" style="gap:6px">
              <strong>${esc(v.label)}</strong>
              <div class="spacer"></div>
              <button class="btn xs ghost" onclick="event.stopPropagation();hearVoice('${v.id}')"
                >hear</button>
            </div>
            <div class="mono voice-note">${esc(v.note)}</div>
          </div>`).join('')}
      </div>`).join('')}

    <label class="field" style="margin:14px 0 4px"><span>Pace — <b>${
      n.speed.toFixed(2)}×</b>${n.speed === 1 ? ' (the model\'s own)' : ''}</span>
      <input type="range" min="0.7" max="1.3" step="0.01" value="${n.speed}"
        onchange="setNarrator({speed:+this.value})"></label>

    <div class="row" style="margin-top:12px">
      <button class="btn" onclick="voiceWholeScript()">
        ${read ? (stale ? `re-read ${stale} paragraph${stale === 1 ? '' : 's'}`
                        : 'read anything still blank') : 'read the whole script'}</button>
      ${read ? `<button class="btn sm ghost" onclick="voiceWholeScript(true)"
        title="re-read every paragraph, including ones already done">read it all again</button>` : ''}
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">about ${
        Math.max(1, Math.round(p.slides.length * 3.5 / 60))} min to synthesise</span>
    </div>
    <audio id="voiceplayer" style="display:none"></audio>
  </div>

  ${pronunciationPanel(p)}`;
}

// ------------------------------------------------------- pronunciation guide
// espeak is good at English and unreliable at names: "Elon" reads as ih-LON.
// An entry fixes one name; the whole value is in being able to hear the
// difference before it is baked into twenty minutes of narration.
function pronunciationPanel(p) {
  const lex = p.lexicon || [];
  const chanCount = (state.channelLexicon || []).length;
  return `<div class="panel" style="margin-top:14px">
    <div class="row" style="margin-bottom:4px">
      <strong>How to say things</strong>
      <div class="spacer"></div>
      <span class="mono" style="color:var(--ink-faint)">${lex.length} in this video${
        chanCount ? ` · ${chanCount} from the channel` : ''}</span>
    </div>
    <div class="mono" style="color:var(--ink-faint);margin-bottom:12px">
      Write the respelling in syllables and put the stressed one in CAPITALS —
      <b>ELL-on</b>, <b>rod-REE-gess</b>. Hear it before and after; the guide
      applies to every paragraph when the script is read.
      ${narratorEngine(p) === 'kokoro' ? '' : `<br>${esc(engineInfo(narratorEngine(p)).label)}
        reads words, not phonemes, so it is handed the respelling as a word
        (<b>ELL-on</b> → <b>Ellon</b>). Each “hear” is a small billed request.`}
    </div>

    ${lex.length ? `<div class="say-list">
      ${lex.map((e, n) => `
        <div class="say-row">
          <input type="text" value="${esc(e.term)}" placeholder="in the script"
            onchange="editSay(${n},'term',this.value)">
          <input type="text" value="${esc(e.respell)}" placeholder="ELL-on"
            onchange="editSay(${n},'respell',this.value)">
          <span class="mono say-ipa" title="the phonemes actually used">${esc(e.ipa)}</span>
          <button class="btn xs ghost" onclick="hearSay(${n})">hear</button>
          <button class="btn xs ghost danger" onclick="dropSay(${n})">×</button>
        </div>`).join('')}
    </div>` : ''}

    <div class="say-row" style="margin-top:10px">
      <input type="text" id="sayterm" placeholder="word in the script — e.g. Elon"
        onkeydown="if(event.key==='Enter')addSay()">
      <input type="text" id="sayrespell" placeholder="say it — e.g. ELL-on"
        onkeydown="if(event.key==='Enter')addSay()">
      <span class="mono say-ipa" id="saypreview"></span>
      <button class="btn xs ghost" onclick="hearSayDraft()">hear</button>
      <button class="btn xs" onclick="addSay()">add</button>
    </div>
    <div class="mono" id="saycompare" style="color:var(--ink-faint);margin-top:8px"></div>
    <audio id="sayplayer" style="display:none"></audio>
  </div>`;
}

const sayVoice = () => (state.project.narrator || {}).voice || 'bm_george';

async function saveLexicon(next) {
  try {
    state.project = await api(`/api/projects/${state.project.id}`,
      { method: 'PATCH', body: JSON.stringify({ lexicon: next }) });
    paintRecord();
  } catch (e) { toast(e.message, true); }
}

function editSay(n, field, value) {
  const next = (state.project.lexicon || []).map((e) => ({ ...e }));
  if (!next[n]) return;
  next[n][field] = value.trim();
  // A new respelling replaces the phonemes it resolved to last time.
  if (field === 'respell') next[n].ipa = '';
  saveLexicon(next);
}

function dropSay(n) {
  const next = (state.project.lexicon || []).filter((_, i) => i !== n);
  saveLexicon(next);
}

async function addSay() {
  const term = document.getElementById('sayterm').value.trim();
  const respell = document.getElementById('sayrespell').value.trim();
  if (!term) return toast('Which word?', true);
  if (!respell) return toast('How should it be said? Try ELL-on.', true);
  await saveLexicon([...(state.project.lexicon || []), { term, respell }]);
}

// The before/after, which is the whole point: you cannot correct a
// pronunciation you cannot compare with the one you are getting.
async function saySample(text, respell, ipa) {
  const el = document.getElementById('sayplayer');
  if (!el || !text) return;
  try {
    const r = await fetch(`/api/tts/say-preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, respell: respell || '', ipa: ipa || '',
                             voice: sayVoice(), engine: narratorEngine(),
                             model: (state.project.narrator || {}).model || '' }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'could not say that');
    el.src = URL.createObjectURL(await r.blob());
    el.play().catch(() => {});
  } catch (e) { toast(e.message, true); }
}

function hearSay(n) {
  const e = (state.project.lexicon || [])[n];
  if (e) saySample(e.term, e.respell, e.ipa);
}

function hearSayDraft() {
  saySample(document.getElementById('sayterm').value.trim(),
            document.getElementById('sayrespell').value.trim(), '');
}

// Live, as the respelling is typed: what the model says now, and what this
// entry would make it say. Debounced because each one is an espeak call.
function watchSayDraft() {
  const term = document.getElementById('sayterm');
  const respell = document.getElementById('sayrespell');
  if (!term || !respell || term.dataset.wired) return;
  term.dataset.wired = respell.dataset.wired = '1';
  const run = async () => {
    const t = term.value.trim();
    const out = document.getElementById('saypreview');
    const cmp = document.getElementById('saycompare');
    // The phoneme comparison is the local model's; a hosted voice has none.
    if (!t || narratorEngine() !== 'kokoro') { out.textContent = ''; cmp.textContent = ''; return; }
    try {
      const j = await api(`/api/tts/say?text=${encodeURIComponent(t)}`
        + `&respell=${encodeURIComponent(respell.value.trim())}`
        + `&voice=${sayVoice()}`);
      out.textContent = j.proposed || '';
      cmp.innerHTML = j.proposed
        ? (j.changes
            ? `reads as <b>${esc(j.current)}</b> → would read as <b>${esc(j.proposed)}</b>`
            : `that is already how it reads (<b>${esc(j.current)}</b>) — no entry needed`)
        : `reads as <b>${esc(j.current)}</b>`;
    } catch (e) { out.textContent = ''; }
  };
  let t = null;
  const kick = () => { clearTimeout(t); t = setTimeout(run, 260); };
  term.addEventListener('input', kick);
  respell.addEventListener('input', kick);
}

async function setNarrator(patch) {
  if (cameraLocked()) return;
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ narrator: patch }) });
  paintRecord();
}

function hearVoice(id) {
  const el = document.getElementById('voiceplayer');
  if (!el) return;
  const engine = narratorEngine();
  const model = (state.project.narrator || {}).model || '';
  el.src = engine === 'kokoro' ? `/api/tts/preview/${id}`
    : `/api/tts/preview/${encodeURIComponent(id)}?engine=${engine}&model=${encodeURIComponent(model)}`;
  el.play().catch(() => toast('Could not play that sample.', true));
}

async function voiceWholeScript(redo) {
  const p = state.project;
  if (redo && !confirm(`Read every paragraph again in ${trackLabel(narratorEngine(p))}, `
      + 'replacing the reads already made in that voice? Your other voices are not touched.')) return;
  if (narratorEngine(p) !== 'kokoro') {
    // A hosted voice is billed by the character: say how many first.
    let est;
    try {
      est = await api(`/api/projects/${p.id}/voice-over`,
        { method: 'POST', body: JSON.stringify({ redo: !!redo, dry_run: true }) });
    } catch (e) { return toast(e.message, true); }
    if (!est.paragraphs) return toast('Everything is already read in this voice.');
    const label = engineInfo(narratorEngine(p)).label || 'the voice service';
    if (!confirm(`Send ${est.paragraphs} paragraph${est.paragraphs === 1 ? '' : 's'} `
      + `(${est.characters.toLocaleString()} characters) to ${label}? `
      + 'It is billed to your account.')) return;
  }
  const r = await api(`/api/projects/${p.id}/voice-over`,
    { method: 'POST', body: JSON.stringify({ redo: !!redo }) });
  watchJob(r.job, 'voice-over');
  paintRecord();
}

async function voiceOneSlide() {
  const p = state.project;
  const s = p.slides[state.rec.index];
  try {
    const r = await api(`/api/projects/${p.id}/slides/${s.id}/voice-over`, { method: 'POST' });
    p.slides[state.rec.index] = r.slide;
    p.recorded_seconds = r.recorded_seconds;
    syncVoiceCounts();
    paintRecord();
    playTake();
  } catch (e) { toast(e.message, true); }
}

function jumpTake(delta) {
  if (cameraMode()) return cameraJump(state.rec.index + delta);
  if (state.rec.recording) return;
  const n = state.rec.index + delta;
  if (n < 0 || n >= state.project.slides.length) return;
  state.rec.index = n;
  paintRecord();
}

function jumpNextUnrecorded() {
  if (cameraLocked()) return;
  const p = state.project;
  const next = p.slides.findIndex((s, n) => n > state.rec.index && !s.take);
  state.rec.index = next >= 0 ? next : p.slides.findIndex((s) => !s.take);
  if (state.rec.index < 0) { state.rec.index = 0; toast('everything is recorded'); }
  paintRecord();
}

// Browsers only expose a microphone to a secure origin — https, or localhost.
// Over plain http to a LAN address `navigator.mediaDevices` is simply not there,
// so this is checked before anything tries to use it.
function micAvailable() {
  return !!(window.isSecureContext && navigator.mediaDevices
            && navigator.mediaDevices.getUserMedia);
}

async function listMics() {
  if (!micAvailable()) return [];
  try {
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'audioinput');
  } catch { return []; }
}

async function ensureMic() {
  if (state.rec.stream) return state.rec.stream;
  if (!micAvailable()) {
    throw new Error('this browser will not open a microphone over an insecure connection');
  }
  const wanted = localStorage.getItem('vb_mic') || '';
  // Raw signal by default: the ffmpeg voice chain does the same work with far
  // better control, and the browser's version is tuned for a call. Automatic
  // gain never comes on — it rides the level mid-sentence, and every take here
  // is loudness-matched afterwards anyway.
  const clean = !!voiceOf().browser_cleanup;
  const audio = {
    echoCancellation: clean, noiseSuppression: clean, autoGainControl: false,
    channelCount: 1, sampleRate: 48000,
  };
  if (wanted) audio.deviceId = { exact: wanted };
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio });
  } catch (e) {
    if (!wanted) throw e;
    // The remembered mic is not on this machine: fall back to the default one.
    localStorage.removeItem('vb_mic');
    delete audio.deviceId;
    stream = await navigator.mediaDevices.getUserMedia({ audio });
  }
  state.rec.stream = stream;
  // Labels are blank until permission is granted, so the picker is filled in
  // once a stream exists rather than on first paint.
  listMics().then((mics) => {
    state.rec.mics = mics;
    // Never mid-take: a repaint would replace the timer and level elements.
    if (!state.rec.recording && state.tab === 'record') paintRecord();
    if (state.mic.el) micRefresh();
  });
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  state.rec.ctx = ctx;
  state.rec.analyser = analyser;
  meter();
  return stream;
}

function meter() {
  const buf = new Uint8Array(state.rec.analyser.fftSize);
  let hold = 0, heldAt = 0;
  const loop = () => {
    if (!state.rec.analyser) return;
    state.rec.analyser.getByteTimeDomainData(buf);
    let peak = 0, sum = 0;
    for (const v of buf) {
      const x = (v - 128) / 128;
      sum += x * x;
      peak = Math.max(peak, Math.abs(x));
    }
    const rms = Math.sqrt(sum / buf.length);
    const now = performance.now();
    if (peak >= hold || now - heldAt > 1100) { hold = peak; heldAt = now; }
    const el = document.getElementById('level');
    if (el) {
      el.style.width = Math.min(100, peak * 145) + '%';
      el.style.background = peak > 0.92 ? 'var(--bad)' : peak > 0.06 ? 'var(--good)' : 'var(--line-strong)';
      el.parentElement.setAttribute('aria-valuenow', dbOf(peak).toFixed(0));
      const readout = document.getElementById('voice-peak');
      if (readout) readout.textContent = `Peak ${dbOf(hold).toFixed(0)} dB`;
    }
    micMeter(rms, peak, hold);
    requestAnimationFrame(loop);
  };
  loop();
}

// The panel's meter is the same numbers on a dBFS scale, because "somewhere
// near the middle" is not a gain setting anyone can repeat tomorrow.
const dbOf = (x) => (x > 0.00001 ? 20 * Math.log10(x) : -80);
const meterPos = (db) => Math.max(0, Math.min(100, (db + 60) / 60 * 100));

function micMeter(rms, peak, hold) {
  const bar = document.getElementById('micbar');
  if (!bar) return;
  const db = dbOf(rms), pk = dbOf(peak);
  bar.style.width = meterPos(db) + '%';
  bar.style.background = pk > -1.5 ? 'var(--bad)' : db > -12 ? 'var(--warn)' : 'var(--good)';
  const mark = document.getElementById('michold');
  if (mark) mark.style.left = meterPos(dbOf(hold)) + '%';
  const read = document.getElementById('micdb');
  if (read) read.textContent = `${db.toFixed(0)} dB rms · peak ${pk.toFixed(0)} dB`;
  const say = document.getElementById('micsay');
  if (say && !state.mic.counting) {
    // Judged on speech, not on the silence between sentences.
    const word = pk > -1.5 ? 'clipping — turn the gain down'
      : db > -10 ? 'hot — back off a little'
      : db > -26 ? 'good level'
      : db > -45 ? 'quiet — closer to the mic, or more gain'
      : 'nothing coming in';
    say.textContent = word;
    say.style.color = pk > -1.5 ? 'var(--bad)' : db > -26 ? 'var(--good)' : 'var(--ink-faint)';
  }
}

async function openMic() {
  try {
    await ensureMic();
    paintRecord();
    toast('Microphone open — say something and watch the level.');
  } catch (e) { toast('Microphone blocked: ' + e.message, true); }
}

async function chooseMic(deviceId) {
  localStorage.setItem('vb_mic', deviceId || '');
  const wasIndex = state.rec.index;
  stopStream();
  try {
    await ensureMic();
    const mic = (state.rec.mics || []).find((m) => m.deviceId === deviceId);
    toast(mic ? `recording from ${mic.label}` : 'using the default microphone');
  } catch (e) { toast('Microphone blocked: ' + e.message, true); }
  state.rec.index = wasIndex;
  paintRecord();
  if (state.mic.el) micRefresh();
}

function stopStream() {
  stopCamera();
  const r = state.rec;
  if (r.recorder && r.recording) { try { r.recorder.stop(); } catch {} }
  r.recording = false;
  clearInterval(r.tick);
  if (r.stream) r.stream.getTracks().forEach((t) => t.stop());
  if (r.ctx) r.ctx.close();
  r.stream = null; r.ctx = null; r.analyser = null; r.recorder = null;
}

async function toggleRec() {
  if (cameraMode()) return toggleCameraRec();
  const r = state.rec;
  if (r.recording) { r.recorder.stop(); return; }
  let stream;
  try { stream = await ensureMic(); }
  catch (e) { return toast('Microphone blocked: ' + e.message, true); }

  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    .find((t) => MediaRecorder.isTypeSupported(t)) || '';
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 128000 } : {});
  r.chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) r.chunks.push(e.data); };
  rec.onstop = () => uploadTake(new Blob(r.chunks, { type: mime || 'audio/webm' }));
  rec.start();
  r.recorder = rec;
  r.recording = true;
  r.t0 = Date.now();
  clearInterval(r.tick);
  r.tick = setInterval(() => {
    const el = document.getElementById('timer');
    if (el) el.textContent = fmtTime((Date.now() - r.t0) / 1000);
  }, 200);
  paintRecord();
}

async function uploadTake(blob) {
  const r = state.rec;
  r.recording = false;
  clearInterval(r.tick);
  const slide = state.project.slides[r.index];
  paintRecord();
  const fd = new FormData();
  fd.append('file', blob, 'take.webm');
  try {
    const res = await api(`/api/projects/${state.project.id}/slides/${slide.id}/take`,
      { method: 'POST', body: fd });
    Object.assign(slide, res.slide);
    syncVoiceCounts();
    state.project.recorded_seconds = res.recorded_seconds;
    toast(`take saved · ${res.slide.takes.mic.duration.toFixed(1)}s`);
    if (r.index < state.project.slides.length - 1) r.index += 1;
    paintRecord();
  } catch (e) { toast(e.message, true); paintRecord(); }
}

// The voice the record tab is working in: the mic, or the AI engine.
function recTrack() {
  const p = state.project;
  return (p.narrator || {}).mode === 'ai' ? narratorEngine(p) : 'mic';
}

async function restoreEarlierTake(n) {
  if (cameraLocked()) return;
  const p = state.project;
  const slide = p.slides[state.rec.index];
  try {
    const res = await api(`/api/projects/${p.id}/slides/${slide.id}/history/${n}/restore`, {method: 'POST'});
    Object.assign(slide, res.slide);
    syncVoiceCounts();
    p.recorded_seconds = res.recorded_seconds;
    toast(res.stale ? 'Take restored · recorded for different text' : 'Take restored');
    paintRecord();
  } catch (e) { toast(e.message, true); }
}

function playTake(track) {
  if (cameraMode()) return reviewCamera();
  track = track || recTrack();
  const slide = state.project.slides[state.rec.index];
  if (!(slide.takes || {})[track]) return;
  const el = document.getElementById('player');
  el.src = `/api/projects/${state.project.id}/slides/${slide.id}/take.wav`
    + `?track=${encodeURIComponent(track)}&cb=${Date.now()}`;
  el.play();
}

// Counts the server would send, worked out here after a single-take change
// rather than reloading the project.
function syncVoiceCounts() {
  const p = state.project;
  const counts = {};
  for (const s of p.slides) for (const k of Object.keys(s.takes || {})) counts[k] = (counts[k] || 0) + 1;
  p.voice_tracks = counts;
  if (!p.voice_track) {
    const first = Object.keys(counts).find((track) => track !== 'camera');
    if (first) p.voice_track = first;
  }
  for (const s of p.slides) s.take = (s.takes || {})[s.on_camera ? 'camera' : p.voice_track] || null;
  p.recorded_count = p.slides.filter((s) => s.take).length;
}
const trackLabel = (t) => ({ mic: 'Your mic', kokoro: 'Local voice',
  elevenlabs: 'ElevenLabs', openai: 'OpenAI' })[t] || t;

// Which voice the whole video uses, and every voice there are reads in. Each
// voice's reads are kept side by side, so trying one never loses another;
// the video uses exactly one, chosen here.
function voiceBar(p, working) {
  const counts = p.voice_tracks || {};
  const n = p.slides.length;
  const used = p.voice_track;
  const keys = TRACK_ORDER.filter((t) => counts[t] || t === working || t === used)
    .concat(Object.keys(counts).filter((t) => !TRACK_ORDER.includes(t)));
  const s = p.slides[state.rec.index] || {};
  const usedCount = counts[used] || 0;
  return `
    <div class="panel voice-bar" style="margin-top:14px;padding:12px 14px">
      <div class="row" style="gap:8px;margin-bottom:8px">
        <strong>Voice for this video</strong>
        <span class="mono" style="color:var(--ink-faint)">${used
          ? `${esc(trackLabel(used))} — what the render and the timeline use`
          : 'nothing read yet'}</span>
      </div>
      <div class="row" style="gap:8px;flex-wrap:wrap">
        ${keys.map((t) => {
          const c = counts[t] || 0;
          const here = !!(s.takes || {})[t];
          return `
            <div class="voice-chip ${t === used ? 'sel' : ''}">
              <b>${esc(trackLabel(t))}</b>
              <span class="mono">${c} of ${n}</span>
              ${here ? `<button class="btn sm ghost" title="paragraph ${state.rec.index + 1} in this voice"
                onclick="playTake('${t}')">▸ hear ¶${state.rec.index + 1}</button>` : ''}
              ${t === used
                ? '<span class="pill on">in use</span>'
                : `<button class="btn sm" ${c ? '' : 'disabled'}
                    onclick="useVoiceTrack('${t}')">use for the video</button>`}
            </div>`;
        }).join('')}
      </div>
      ${used && working !== used ? `
        <div class="mono" style="color:var(--ink-faint);margin-top:8px">
          You're working in ${esc(trackLabel(working))} here. The video still uses
          ${esc(trackLabel(used))}, and none of its reads are touched — switch above
          once you've heard enough.</div>` : ''}
      ${used && usedCount < n ? `
        <div class="mono" style="color:var(--warn, #e0a050);margin-top:8px">
          ${n - usedCount} paragraph${n - usedCount === 1 ? ' has' : 's have'} no read in
          ${esc(trackLabel(used))} yet and will be silent in the render.</div>` : ''}
    </div>`;
}

async function useVoiceTrack(track) {
  const p = state.project;
  const n = p.slides.length;
  const c = (p.voice_tracks || {})[track] || 0;
  if (c < n && !confirm(`Only ${c} of ${n} paragraphs are read in ${trackLabel(track)}. `
      + 'The rest will be silent until they are. Use it for the video anyway?\n\n'
      + 'Nothing is deleted — you can switch back at any time.')) return;
  try {
    state.project = await api(`/api/projects/${p.id}/voice-track`,
      { method: 'POST', body: JSON.stringify({ track }) });
    toast(`the video now uses ${trackLabel(track)}`);
    render();
  } catch (e) { toast(e.message, true); }
}

// The takes on disk were cleaned by whichever voice chain was current when they
// were recorded. This re-runs the current one over the raw recordings, so a
// change to the processing reaches a script that is already read.
async function recleanTakes() {
  const p = state.project;
  if (!confirm(`Clean all ${p.recorded_count} takes again from the raw recordings?`
             + '\nNothing is re-recorded; the takes are rebuilt.')) return;
  toast('cleaning takes…');
  try {
    const res = await api(`/api/projects/${p.id}/takes/reprocess`, { method: 'POST' });
    state.project = res.project;
    paintRecord();
    toast(res.failed.length
      ? `${res.reprocessed} cleaned · ${res.failed[0]}`
      : `${res.reprocessed} takes cleaned`, res.failed.length > 0);
  } catch (e) { toast(e.message, true); }
}

async function dropTake() {
  if (cameraLocked()) return;
  if (cameraMode()) return toast("Use Retake to record again; earlier camera takes are kept.");
  const slide = state.project.slides[state.rec.index];
  const res = await api(`/api/projects/${state.project.id}/slides/${slide.id}/take`
    + `?track=${encodeURIComponent(recTrack())}`, { method: 'DELETE' });
  Object.assign(slide, res.slide);
  syncVoiceCounts();
  paintRecord();
}

function voiceOf() { return (state.project && state.project.voice) || {}; }

function voiceSummary() {
  const v = voiceOf();
  const room = state.mic.report && state.mic.report.analysis;
  return `${v.preset || 'warm'} · de-room ${Math.round((v.de_room || 0) * 100)}%`
       + (room && room.ok ? ` · room: ${room.verdict}` : '');
}

// ------------------------------------------------------------------- panel
async function openMicPanel() {
  if (cameraLocked()) return;
  if (state.mic.el) return;
  const wrap = document.createElement('div');
  wrap.className = 'modal mic-drawer';
  wrap.innerHTML = `
    <div class="modal-box wide mic-panel" role="dialog" aria-modal="true" aria-label="Microphone and voice setup" tabindex="-1">
      <div class="row" style="margin-bottom:16px">
        <strong>Microphone &amp; voice</strong>
        <span class="mono" style="color:var(--ink-faint)">
          set it up once — every take on this video is cleaned the same way</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="micclose">done</button>
      </div>
      <div class="mic-cols">
        <div class="mic-col" id="micleft"></div>
        <div class="mic-col" id="micright"></div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  state.mic.el = wrap;
  wrap.querySelector('#micclose').onclick = closeMicPanel;
  wrap.onclick = (e) => { if (e.target === wrap) closeMicPanel(); };

  wrap.onkeydown = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); closeMicPanel(); }
    if (e.key === 'Tab') {
      const items = [...wrap.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), audio[controls]')];
      const first = items[0], last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };
  micRefresh();
  wrap.querySelector('#micclose').focus();
  if (micAvailable()) {
    try { await ensureMic(); } catch (e) { toast('Microphone blocked: ' + e.message, true); }
    micRefresh();
  }
}

function closeMicPanel() {
  if (!state.mic.el) return;
  abStop();
  if (state.mic.rec) { try { state.mic.rec.stop(); } catch {} state.mic.rec = null; }
  clearInterval(state.mic.tick);
  state.mic.tick = null;
  state.mic.counting = 0;
  state.mic.el.remove();
  state.mic.el = null;
  paintRecord();
  document.querySelector('[onclick="openMicPanel()"]')?.focus();
}

function micRefresh() {
  const wrap = state.mic.el;
  if (!wrap) return;
  paintMicDevice();
  paintMicVoice();
}

// ----------------------------------------------------------- left: the mic
function paintMicDevice() {
  const v = voiceOf();
  const mics = state.rec.mics || [];
  const picked = localStorage.getItem('vb_mic') || '';
  state.mic.el.querySelector('#micleft').innerHTML = `
    <div class="kicker">the microphone</div>

    <label class="field" style="margin-top:12px">
      <span>input device</span>
      <select id="micdev" onchange="chooseMic(this.value)"
        ${micAvailable() ? '' : 'disabled'}>
        <option value="">default input</option>
        ${mics.map((m) => `<option value="${esc(m.deviceId)}"
          ${m.deviceId === picked ? 'selected' : ''}
          >${esc(m.label || 'microphone')}</option>`).join('')}
      </select>
    </label>
    ${state.rec.stream || !micAvailable() ? '' : `
      <button class="btn sm" onclick="openMic().then(micRefresh)">open the microphone</button>`}

    <div class="meter-wrap">
      <div class="meter">
        <i id="micbar"></i>
        <b id="michold" ${state.rec.stream ? '' : 'hidden'}></b>
        <u class="meter-zone"></u>
      </div>
      <div class="meter-scale mono">
        <span>−60</span><span>−40</span><span>−24</span><span>−12</span><span>0 dBFS</span>
      </div>
      <div class="row" style="margin-top:6px">
        <span class="mono" id="micdb" style="color:var(--ink-faint)">—</span>
        <div class="spacer"></div>
        <span class="mono" id="micsay" style="color:var(--ink-faint)">
          ${state.rec.stream ? 'say a line at your reading volume' : 'microphone closed'}</span>
      </div>
    </div>

    <label class="row" style="margin:14px 0 4px;cursor:pointer">
      <input type="checkbox" style="width:auto" ${v.browser_cleanup ? 'checked' : ''}
        onchange="setBrowserCleanup(this.checked)">
      <span style="font-size:13px">let the browser clean the signal first</span>
    </label>
    <div class="mono hintline">
      Chrome's own denoiser is built for a call, not a read: it fights the chain
      on the right and smears the top of the voice. Worth trying only if the room
      is genuinely bad.
    </div>

    <div class="row" style="margin-top:18px">
      <button class="btn ${state.mic.report ? '' : 'primary'}" id="mictest"
        ${micAvailable() && !state.mic.counting && !state.mic.measuring ? '' : 'disabled'}
        onclick="micTestRecord()">
        ${state.mic.counting ? `recording… ${state.mic.counting}` :
          state.mic.measuring ? 'measuring…' :
          state.mic.report ? 'record another test' : '● record 8 seconds'}</button>
      <span class="mono" style="color:var(--ink-faint);flex:1;min-width:180px">
        read a couple of sentences the way you read a script</span>
    </div>

    <div id="micreport">${micReportHtml()}</div>`;
}

function micReportHtml() {
  const r = state.mic.report;
  if (!r) {
    return `<div class="mono hintline" style="margin-top:16px">
      Nothing measured yet. The test read tells you how far your voice gets
      clear of the room, which is the one thing no processing can fix later.
    </div>`;
  }
  const a = r.analysis;
  if (!a.ok) {
    return `<div class="panel warn-panel" style="margin-top:16px">
      ${a.notes.map((n) => `<div>${esc(n)}</div>`).join('')}</div>`;
  }
  const score = a.room_score;
  const tone = score >= 70 ? 'good' : score >= 50 ? 'ok' : score >= 30 ? 'warn' : 'bad';
  return `
    <div class="room-head">
      <div>
        <span class="room-verdict ${tone}">${esc(a.verdict)}</span>
        <span class="mono" style="color:var(--ink-faint)">
          — ${esc(VERDICT_BLURB[a.verdict] || '')}</span>
      </div>
    </div>
    <div class="room-bar ${tone}"><i style="width:${score}%"></i></div>
    <div class="room-nums mono">
      <span>voice <b>${a.speech_db} dB</b></span>
      <span>room tone <b>${a.room_db} dB</b></span>
      <span>peak <b>${a.peak_db} dB</b></span>
      <span title="how far your voice gets clear of its own reflections"
        >separation <b>${a.contrast} dB</b></span>
      <span title="how far the take falls in the 200ms after a word ends"
        >decay <b>${a.decay} dB</b></span>
    </div>
    ${a.notes.map((n) => `<div class="room-note mono">${esc(n)}</div>`).join('')}`;
}

async function setBrowserCleanup(on) {
  await saveVoice({ browser_cleanup: !!on }, false);
  stopStream();                       // the constraint only applies to a new stream
  try { await ensureMic(); } catch (e) { toast('Microphone blocked: ' + e.message, true); }
  micRefresh();
  if (state.mic.report) micPreview();
}

// --------------------------------------------------------- right: the voice
function paintMicVoice() {
  const v = voiceOf();
  const has = !!state.mic.report;
  state.mic.el.querySelector('#micright').innerHTML = `
    <div class="kicker">the voice</div>

    <div class="preset-row">
      ${Object.keys(PRESET_BLURB).map((k) => `
        <button class="chip ${v.preset === k ? 'sel' : ''}" onclick="saveVoice({preset:'${k}'})">
          ${k}<em>${esc(PRESET_BLURB[k])}</em></button>`).join('')}
      ${v.preset === 'custom' ? '<span class="chip sel static">custom</span>' : ''}
    </div>

    <div class="knobs" id="micknobs">
      ${VOICE_KNOBS.map((n) => `
        <label class="knob" title="${esc(n.hint)}">
          <span>${n.label}<b id="kv_${n.k}">${n.fmt(+v[n.k])}</b></span>
          <input type="range" min="${n.min}" max="${n.max}" step="${n.step}"
            value="${v[n.k]}" id="kn_${n.k}"
            oninput="micKnobLive('${n.k}', this.value)"
            onchange="saveVoice({${n.k}: +this.value})">
        </label>`).join('')}
    </div>

    <div class="ab-bar">
      <button class="btn sm ${state.mic.ab === 'raw' ? 'selected' : ''}"
        ${has ? '' : 'disabled'} onclick="abPlay('raw')">▶ before</button>
      <button class="btn sm ${state.mic.ab === 'wet' ? 'selected' : ''}"
        ${has ? '' : 'disabled'} onclick="abPlay('wet')">▶ after</button>
      <button class="btn sm ghost" ${has ? '' : 'disabled'} onclick="abStop()">stop</button>
      <span class="mono" id="abnote" style="color:var(--ink-faint);flex:1;min-width:150px">
        ${has ? (state.mic.busy ? 'rebuilding…' : 'switch while it plays — it stays in step')
              : 'record a test above to hear the chain'}</span>
    </div>

    <div class="row" style="margin-top:16px">
      <button class="btn sm ghost" onclick="saveVoiceToChannel()"
        ${state.project.channel_id ? '' : 'disabled'}
        title="every new video on this channel starts from these settings">
        make this the channel default</button>
      <button class="btn sm ghost" onclick="recleanTakes()"
        ${state.project.recorded_count ? '' : 'disabled'}
        title="run the takes already recorded through this chain again">
        re-clean ${state.project.recorded_count} take${state.project.recorded_count === 1 ? '' : 's'}</button>
    </div>
    <div class="mono hintline" style="margin-top:10px">
      Takes are cleaned as they are recorded. Change anything here after reading
      and the takes on disk keep the old chain until they are re-cleaned — the
      raw recordings are kept for exactly that.
    </div>`;
}

// Dragging a slider only moves its own label; the chain is rebuilt on release.
function micKnobLive(key, value) {
  const knob = VOICE_KNOBS.find((n) => n.k === key);
  const el = document.getElementById(`kv_${key}`);
  if (knob && el) el.textContent = knob.fmt(+value);
}

async function saveVoice(patch, preview = true) {
  state.project.voice = { ...voiceOf(), ...patch };   // so the UI answers at once
  if (preview && state.mic.report) return micPreview(patch);
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ voice: patch }) });
  micRefresh();
}
async function micPreview(patch) {
  clearTimeout(micPreviewTimer);
  state.mic.pending = { ...(state.mic.pending || {}), ...(patch || {}) };
  micPreviewTimer = setTimeout(async () => {
    const body = state.mic.pending || {};
    state.mic.pending = null;
    state.mic.busy = true;
    micRefresh();
    try {
      const r = await api(`/api/projects/${state.project.id}/voice/preview`,
        { method: 'POST', body: JSON.stringify({ voice: body }) });
      applyReport(r);
    } catch (e) { toast(e.message, true); }
    state.mic.busy = false;
    micRefresh();
    abReload();
  }, 260);
}

function applyReport(r) {
  state.mic.report = r;
  state.project.voice = r.voice;
  state.mic.trim = (r.take && r.take.trimmed && r.take.trimmed[0]) || 0;
}

async function saveVoiceToChannel() {
  const cid = state.project.channel_id;
  if (!cid) return;
  await api(`/api/channels/${cid}`,
    { method: 'PATCH', body: JSON.stringify({ voice: voiceOf() }) });
  toast('every new video on this channel starts here now');
}

// ------------------------------------------------------------ the test read
async function micTestRecord() {
  let stream;
  try { stream = await ensureMic(); }
  catch (e) { return toast('Microphone blocked: ' + e.message, true); }
  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    .find((t) => MediaRecorder.isTypeSupported(t)) || '';
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 128000 } : {});
  const chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    clearInterval(state.mic.tick);
    state.mic.counting = 0;
    state.mic.rec = null;
    if (!state.mic.el) return;          // the panel was closed mid-test
    state.mic.measuring = true;
    micRefresh();
    const fd = new FormData();
    fd.append('file', new Blob(chunks, { type: mime || 'audio/webm' }), 'mictest.webm');
    try {
      applyReport(await api(`/api/projects/${state.project.id}/voice/test`,
        { method: 'POST', body: fd }));
    } catch (e) { toast(e.message, true); }
    state.mic.measuring = false;
    micRefresh();
    abReload();
  };
  rec.start();
  state.mic.rec = rec;
  state.mic.counting = 8;
  micRefresh();
  clearInterval(state.mic.tick);
  state.mic.tick = setInterval(() => {
    state.mic.counting -= 1;
    if (state.mic.counting <= 0) { try { rec.stop(); } catch {} return; }
    micRefresh();
  }, 1000);
}

// ------------------------------------------------------------------- the A/B
function abEl(which) {
  let el = document.getElementById(`ab_${which}`);
  if (!el) {
    el = document.createElement('audio');
    el.id = `ab_${which}`;
    el.preload = 'auto';
    document.body.appendChild(el);
  }
  return el;
}

function abPlay(which) {
  const pid = state.project.id;
  const other = which === 'raw' ? 'wet' : 'raw';
  const from = abEl(other), to = abEl(which);
  // The cleaned file starts where the speech does; the raw one still has the
  // silence in front of it. Carrying that offset across is what makes the
  // switch land on the same word rather than half a second past it.
  const trim = state.mic.trim || 0;
  let at = from.currentTime && !from.paused
    ? from.currentTime + (which === 'raw' ? trim : -trim) : 0;
  from.pause();
  if (!to.src) {
    to.src = which === 'raw' ? `/api/projects/${pid}/voice/test.src`
                             : `/api/projects/${pid}/voice/test.wav?cb=${state.mic.report.stamp}`;
  }
  state.mic.ab = which;
  const start = () => { to.currentTime = Math.max(0, Math.min(at, to.duration || at)); to.play(); };
  if (to.readyState >= 1) start(); else to.addEventListener('loadedmetadata', start, { once: true });
  to.onended = () => { state.mic.ab = ''; micRefresh(); };
  micRefresh();
}

function abStop() {
  ['raw', 'wet'].forEach((w) => { const el = document.getElementById(`ab_${w}`); if (el) el.pause(); });
  state.mic.ab = '';
  micRefresh();
}

// After a rebuild the cleaned file is a different file at the same URL.
function abReload() {
  const el = document.getElementById('ab_wet');
  if (!el || !state.mic.report) return;
  const at = el.currentTime, playing = !el.paused;
  el.src = `/api/projects/${state.project.id}/voice/test.wav?cb=${state.mic.report.stamp}`;
  if (playing) el.addEventListener('loadedmetadata', () => {
    el.currentTime = Math.min(at, el.duration || at);
    el.play();
  }, { once: true });
}

// The list is cheap markup; media elements exist only for the selected paragraph.
function voiceParagraphList(p) {
  const done = p.slides.filter(s => s.take).length;
  return `<aside class="voice-list" aria-label="Paragraphs"><h2>Takes · ${done} of ${p.slides.length} voiced</h2>
    ${p.slides.map((s, n) => {
      const take = s.take;
      const live = n === state.rec.index && state.rec.recording;
      const kind = live ? 'live' : !take ? 'empty' : take.synthetic ? 'draft' : 'mic';
      const label = live ? 'recording' : !take ? 'not voiced' : take.synthetic ? 'draft voice' : s.on_camera ? 'camera' : 'mic';
      return `<button type="button" class="btn ghost voice-paragraph ${kind}" ${cameraLocked() ? 'disabled' : ''}
        ${n === state.rec.index ? 'aria-current="true"' : ''} onclick="selectVoiceParagraph(${n})">
        <span class="num">${String(n + 1).padStart(2, '0')}</span><span class="voice-excerpt">${esc(s.narration)}</span><span class="voice-state">${label}</span></button>`;
    }).join('')}</aside>`;
}
function selectVoiceParagraph(n) {
  if (cameraLocked()) return;
  state.rec.index = n;
  paintRecord();
}
function voicePrompter(s) {
  const sentences = s.narration.match(/[^.!?]+[.!?]+[”"']*|[^.!?]+$/g) || [s.narration];
  return `<div class="prompter voice-prompter"><p>${sentences.map((text, i) => `<span ${i === 0 ? 'class="current"' : ''}>${esc(text)} </span>`).join('')}</p></div>
    ${sentences.length > 1 ? '<button type="button" class="btn sm ghost" onclick="advanceVoiceSentence()">Next sentence</button>' : ''}`;
}
function advanceVoiceSentence() {
  const current = document.querySelector('.voice-prompter .current');
  if (current?.nextElementSibling) { current.classList.remove('current'); current.nextElementSibling.classList.add('current'); }
}
function voiceNextUp(p, i) {
  return p.slides[i + 1] ? `<div class="voice-next"><h2>Next up</h2><p>¶${i + 2} · ${esc(p.slides[i + 1].narration)}</p></div>` : '';
}
function voiceTakesPanel(p, s) {
  const locked = cameraLocked() ? 'disabled' : '';
  const used = s.on_camera ? 'camera' : p.voice_track;
  const file = path => `/api/projects/${p.id}/file/${esc(path)}`;
  const media = t => `${t.video ? `<video controls playsinline preload="none" src="${file(t.video)}"></video>` : ''}
    <audio controls preload="none" aria-label="Play ${t.synthetic ? 'draft' : 'recorded'} take" src="${file(t.path)}"></audio>`;
  return `<aside class="voice-takes" aria-label="Takes"><h2>¶${state.rec.index + 1} · every take is kept</h2>
    ${state.rec.recording ? '<div class="voice-take live"><strong>Recording · live</strong><p>The new take is saved when you stop.</p></div>' : ''}
    ${Object.entries(s.takes || {}).map(([track, t]) => `<div class="voice-take">
      <strong>${esc(trackLabel(track))}${t.synthetic ? ' · draft' : ''}</strong>
      <span class="voice-meta">${fmtTime(t.duration || 0)} · ${track === used ? 'in the cut' : 'available'}</span>
      ${media(t)}${track !== used && track !== 'camera' ? `<button type="button" class="btn sm" ${locked} onclick="useVoiceTrack('${esc(track)}')">Use this voice for the video</button>` : ''}
    </div>`).join('')}
    <h2>Earlier takes · ${(s.history || []).length}</h2>
    ${(s.history || []).map((t, n) => `<div class="voice-take"><strong>${esc(trackLabel(t.track || (t.synthetic ? t.engine : 'mic')))} · history</strong>
      <span class="voice-meta">${fmtTime(t.duration || 0)} · ${esc(t.reason || '')}${t.narration !== s.narration ? ' · different text' : ''}</span>
      ${media(t)}<button type="button" class="btn sm" ${locked} onclick="restoreEarlierTake(${n})">Use this take</button></div>`).join('')}
    ${!Object.keys(s.takes || {}).length && !(s.history || []).length ? '<p>No takes yet. Record or draft this paragraph.</p>' : ''}
    <p class="voice-meta">Replaced takes move to history and stay on disk. Nothing is deleted.</p></aside>`;
}

function voicePresenterOptions(p) {
  return typeof presenterPanel === 'function'
    ? `<details class="voice-options"><summary>On camera / presenter</summary>${presenterPanel(p)}</details>` : '';
}

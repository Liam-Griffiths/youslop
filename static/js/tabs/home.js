
// -------------------------------------------------------------------- home
async function renderHome() {
  const [projects, providers, chans] = await Promise.all([
    api('/api/projects'), api('/api/providers'), api('/api/channels'),
  ]);
  state.channels = chans;
  $('#topbar-right').innerHTML = providers
    .map((p) => `<span class="pill ${p.available ? 'on' : ''}" title="${p.available ? 'ready' : 'no API key'}">
      <span class="dot"></span>${esc(p.name)}</span>`).join('');

  const byChannel = (id) => projects.filter((p) => (p.channel_id || '') === id);
  const loose = byChannel('');
  state.soloCount = loose.length;
  paintSidebar();

  view.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <h1 style="flex:1;min-width:0">Build a video</h1>
      <button class="btn ghost sm" onclick="$('#projfile').click()"
        title="a .corkbored file saved from this or another computer">open project file…</button>
      <input type="file" id="projfile" accept=".corkbored,.youslop" style="display:none"
        onchange="openProjectFile(this.files[0]); this.value=''">
    </div>
    <p class="sub">Describe the story. Claude writes the script, the archives supply the pictures,
      you supply the voice. <a href="#/guide">New here? See how it works.</a></p>

    <div class="panel">
      <div class="tabs" style="margin:0 0 18px">
        <div class="tab ${state.mode !== 'script' ? 'active' : ''}"
             onclick="state.mode='idea';renderHome()">Start from an idea</div>
        <div class="tab ${state.mode === 'script' ? 'active' : ''}"
             onclick="state.mode='script';renderHome()">Paste a script</div>
      </div>

      ${state.mode === 'script' ? `
        <label class="field">
          <span>Your script — paste the whole thing, headings and all</span>
          <textarea id="script" rows="12" placeholder="Paste your article or script here. Newsletter furniture (subscribe prompts, image captions, links) is stripped automatically, and the text is split into paragraph-sized takes for recording."></textarea>
        </label>
        <label class="field">
          <span>How closely should it stick to your words?</span>
          <select id="fidelity">
            <option value="faithful">Faithful — keep my words, just split them for reading</option>
            <option value="adapted">Adapted — smooth written prose into speech</option>
          </select>
        </label>
      ` : `
        <label class="field">
          <span>The idea</span>
          <textarea id="idea" rows="4" placeholder="The history of YouTube slop — from Elsagate's knock-off cartoons and robot-voiced Top 10 lists to faceless AI channels uploading a video an hour, and why the algorithm kept rewarding them."></textarea>
        </label>
      `}
      <div class="grid-3">
        <label class="field">
          <span>Channel</span>
          <select id="chan" onchange="channelPicked()">
            <option value="">— standalone video —</option>
            ${chans.map((c) => `<option value="${c.id}" ${c.id === state.presetChannel ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
          </select>
        </label>
        <label class="field"><span>Saved format</span><select id="saved-format"><option value="">Channel defaults</option></select></label>
        ${state.mode === 'script' ? `
          <label class="field">
            <span>Length comes from your script</span>
            <input type="text" disabled value="measured after import">
          </label>` : `
          <label class="field">
            <span>Target length — <b id="minsLabel">${state.newTest ? '1 minute (test run)' : '12 minutes'}</b></span>
            <input type="range" id="mins" min="7" max="22" value="12" ${state.newTest ? 'disabled' : ''}
                   oninput="document.getElementById('minsLabel').textContent=this.value + ' minutes'">
            <label style="display:flex;gap:6px;align-items:center;margin-top:6px;font-size:13px;cursor:pointer"
                   title="a one-minute video with quick research, to try the whole pipeline cheaply">
              <input type="checkbox" id="testrun" ${state.newTest ? 'checked' : ''} style="width:auto"
                     onchange="newTestRun(this.checked)"> test run — 1 minute, quick research</label>
          </label>`}
        <label class="field">
          <span>Tone</span>
          <select id="tone">
            <option>warm documentary</option>
            <option>cool and analytical</option>
            <option>plain and understated</option>
            <option>tense and propulsive</option>
            <option>wry and literary</option>
          </select>
        </label>
      </div>

      ${state.mode === 'script' ? '' : `
        <label class="field">
          <span>Research</span>
          <select id="research" onchange="state.newResearch=this.value" ${state.newTest ? 'disabled' : ''}>
            <option value="quick" ${state.newTest || (state.newResearch || 'quick') === 'quick' ? 'selected' : ''}>Quick — one search pass</option>
            <option value="deep" ${!state.newTest && state.newResearch === 'deep' ? 'selected' : ''}>Deep — Claude's research mode, several rounds (slower, more Claude calls)</option>
          </select>
        </label>`}

      <label class="field"><span>Video style</span></label>
      ${formatPicker(state.newFormat || 'kenburns', '#E8C36A', 'pickNewFormat')}
      <div id="newmodels">${newModelsPicker()}</div>

      <label class="field">
        <span id="everyLabel">${pictureEveryLabel(state.newPictureEvery || 1)}</span>
        <input type="range" id="every" min="1" max="6" value="${state.newPictureEvery || 1}"
               oninput="state.newPictureEvery=+this.value;
                 document.getElementById('everyLabel').textContent=pictureEveryLabel(+this.value);"></label>
      <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
        1 is a new picture every paragraph. Raise it when the archives for this
        subject are likely to be thin — fewer pictures to find, each held
        longer. Changeable later on the Media tab.</div>

      <div class="row">
        <button class="btn primary" onclick="createProject()">
          ${isStage(state.newFormat) ? 'Plan the story and cast' : state.mode === 'script' ? 'Break it into a video' : 'Write the script'}</button>
        <span class="mono" style="color:var(--ink-faint)">takes 1–3 minutes</span>
      </div>
    </div>

    <div class="row" id="standalone" style="margin:34px 0 14px;align-items:baseline;
         scroll-margin-top:16px">
      <h2 style="margin:0">${chans.length ? 'Standalone videos' : 'Your videos'}</h2>
      <span class="mono" style="color:var(--ink-faint)">
        ${loose.length ? `${loose.length} video${loose.length === 1 ? '' : 's'} in no channel` : ''}</span>
    </div>
    ${loose.length === 0 ? '<div class="empty-note">Bucket\'s empty. Go make some slop.</div>'
      : loose.map(projRow).join('')}

    <div class="row" style="margin:34px 0 14px;align-items:baseline">
      <h2 style="margin:0">Channels</h2>
      <span class="mono" style="color:var(--ink-faint)">shared look, shared opening slate</span>
      <div class="spacer"></div>
      <button class="btn sm" onclick="newChannel()">new channel</button>
    </div>
    ${chans.length === 0
      ? `<div class="empty-note">No channels yet. Start one and every video poured from it
           gets the same look and the same animated opening.</div>`
      : chans.map((c) => `
        <div class="proj" onclick="go('#/c/${c.id}')">
          <span class="swatch" style="background:${esc(c.accent)}"></span>
          <div style="flex:1;min-width:0">
            <div class="t">${esc(c.name)}</div>
            <div class="m">${c.videos} video${c.videos === 1 ? '' : 's'}${c.tagline ? ' · ' + esc(c.tagline) : ''}</div>
          </div>
          <span class="pill ${c.intro_ready ? 'on' : 'warn'}">
            ${c.intro_ready ? `slate: ${c.intro_images} cast` : 'no slate yet'}</span>
        </div>`).join('')}

    ${chans.filter((c) => byChannel(c.id).length).map((c) => `
      <h2>${esc(c.name)}</h2>
      ${byChannel(c.id).map(projRow).join('')}`).join('')}
  `;
  if (state.presetChannel) {
    state.presetChannel = null;
    channelPicked();
  }
  if (state.afterHome) {
    const run = state.afterHome;
    state.afterHome = null;
    run();
  }
}

// ------------------------------------------------------------ project files
// One file per video, to carry it to another computer: see app/transfer.py.
async function saveProjectFile() {
  const p = state.project;
  toast('Saving the project file…');
  try {
    // Inside the desktop app the server writes it via a native save dialog;
    // a browser tab gets a 501 and downloads it instead.
    const r = await api(`/api/projects/${p.id}/export`, { method: 'POST' });
    toast(`Saved, ${r.size_mb} MB: ${r.path}`);
  } catch (e) {
    if (e.status === 501) location.href = `/api/projects/${p.id}/export`;
    else if (e.status !== 409) toast(e.message, true);
  }
}

async function openProjectFile(file, onConflict = '') {
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  form.append('on_conflict', onConflict);
  toast(`Opening ${file.name}…`);
  try {
    const r = await api('/api/projects/import', { method: 'POST', body: form });
    const extras = [r.channel && 'its channel', r.style && `the “${r.style}” style`,
      r.music.length && `${r.music.length} music track${r.music.length === 1 ? '' : 's'}`]
      .filter(Boolean);
    toast(`Opened “${r.title}”${extras.length ? `, with ${extras.join(' and ')}` : ''}.`);
    state.channels = null;
    state.project = null;
    go(`#/p/${r.id}`);
  } catch (e) {
    if (e.status === 409 && e.detail && e.detail.already_here) {
      const replace = confirm(`“${e.detail.title}” is already on this computer.\n\n`
        + 'OK replaces it with the version in this file.\n'
        + 'Cancel keeps both, opening the file as a copy.');
      return openProjectFile(file, replace ? 'replace' : 'copy');
    }
    toast(e.message, true);
  }
}

function projRow(p) {
  return `<div class="proj" onclick="go('#/p/${p.id}')">
    ${p.thumb_at
      ? `<img class="proj-thumb" loading="lazy"
             src="/api/projects/${p.id}/file/thumb/thumb.jpg?v=${p.thumb_at}">`
      : '<div class="proj-thumb empty"></div>'}
    <div style="flex:1;min-width:0">
      <div class="t">${esc(p.title || p.idea.slice(0, 70))}</div>
      <div class="m">${p.slides} paragraphs · ${p.recorded}/${p.slides} recorded ·
        ~${fmtTime(p.est_seconds)}</div>
    </div>
    ${p.test ? '<span class="pill warn" title="a one-minute test run">test</span>' : ''}
    <span class="pill ${p.has_output ? 'on' : ''}">${esc(p.status)}</span>
    <button class="btn sm danger ghost"
      onclick="event.stopPropagation();delProject('${p.id}')">delete</button>
  </div>`;
}

// ------------------------------------------------------------------ library
// A shared store of hand-downloaded stock (Storyblocks Essentials has no API,
// so this is where a manual download earns its keep): tag it once here and
// it turns up in every project's picture search from then on, ranked
// alongside the archives — see thumbUrl() and Library in media/providers.py.
state.library = { items: [], q: '', kind: '', file: null };

function channelPicked() {
  const c = (state.channels || []).find((x) => x.id === $('#chan').value);
  const saved = $('#saved-format');
  if (saved) saved.innerHTML = '<option value="">Channel defaults</option>' +
    (c?.formats || []).map((f) => `<option value="${esc(f.name)}">${esc(f.name)}</option>`).join('');
  // Standalone again: back to this form's own defaults rather than whatever
  // the last-picked channel left behind.
  state.newFormat = c ? c.format : 'kenburns';
  state.newPictureEvery = c ? (c.picture_every || 1) : 1;
  const strip = $('#fmtpicker');
  if (strip) strip.querySelectorAll('.tpl').forEach((el) =>
    el.classList.toggle('sel', el.dataset.fmt === state.newFormat));
  const every = $('#every'), label = $('#everyLabel');
  if (every) every.value = state.newPictureEvery;
  if (label) label.textContent = pictureEveryLabel(state.newPictureEvery);
  if (c) toast(`New videos will use “${c.name}”’s look and opening slate.`);
}

function pictureEveryLabel(n) {
  return `New picture every — ${n} ${n === 1 ? 'paragraph' : 'paragraphs'}`;
}

async function createProject() {
  const scripting = state.mode === 'script';
  const body = { tone: $('#tone').value, channel_id: $('#chan').value || '',
                 format: state.newFormat || 'kenburns',
                 picture_every: state.newPictureEvery || 1 };

  body.format_name = $('#saved-format')?.value || '';
  if (scripting) {
    const script = $('#script').value.trim();
    if (script.split(/\s+/).length < 120) {
      return toast('Paste a bit more — that is too short to build a video from.', true);
    }
    body.script = script;
    body.fidelity = $('#fidelity').value;
  } else {
    body.idea = $('#idea').value.trim();
    if (body.idea.length < 8) return toast('Give me a sentence or two to work with.', true);
    body.target_minutes = +$('#mins').value;
    body.research_mode = $('#research').value;
    if (state.newTest) { body.test = true; body.target_minutes = 1; body.research_mode = 'quick'; }
  }
  if (isStage(body.format)) body.models = state.newModels || [];

  const btn = event.target;
  btn.disabled = true;
  try {
    const r = await api('/api/projects', { method: 'POST', body: JSON.stringify(body) });
    state.project = r.project;
    const stage = isStage(body.format);
    go(`#/p/${r.project.id}${stage ? '/cast' : ''}`);
    await route();
    watchJob(r.job, stage ? 'brief' : scripting ? 'import' : 'script');
  } catch (e) { toast(e.message, true); btn.disabled = false; }
}

async function newChannel() {
  const name = prompt('Channel name\n(this is the title on the opening slate)', 'Your channel name');
  if (!name) return;
  const concept = prompt('What does this channel cover?\nThis steers the scripts and who appears in the opening titles.',
    '') || '';
  try {
    const c = await api('/api/channels', { method: 'POST', body: JSON.stringify({ name, concept }) });
    state.channels = null;   // the sidebar's cache — force it to pick up the new one
    go(`#/c/${c.id}`);
    await route();
  } catch (e) { toast(e.message, true); }
}

async function delProject(id) {
  if (!confirm('Delete this project and everything in it?')) return;
  await api(`/api/projects/${id}`, { method: 'DELETE' });
  renderHome();
}

// The home form's own picker: nothing exists to save to yet, so a pick just
// updates state and repaints the strip in place — the surrounding idea/script
// textarea must not be touched, or a half-typed idea would vanish under the
// user's cursor.
// A 3D explainer can start from models already in the library ("make it
// about these"): they join the cast before the story is planned.
function newModelsPicker() {
  if (!isStage(state.newFormat)) return '';
  const models = state.models || [];
  if (!state.models) {
    api('/api/models').then((m) => { state.models = m; const el = $('#newmodels'); if (el) el.innerHTML = newModelsPicker(); }).catch(() => {});
  }
  const picked = state.newModels || [];
  return `<label class="field"><span>Start from models you have (optional)</span></label>
    <div class="row" style="flex-wrap:wrap;gap:6px;margin:-4px 0 14px">
      ${models.map((m) => `<button class="btn xs ${picked.includes(m.id) ? 'primary' : 'ghost'}"
          onclick="toggleNewModel('${m.id}')">${esc(m.identity && m.identity.name || m.title)}</button>`).join('')
        || '<span class="mono" style="color:var(--ink-faint)">no models in the library yet</span>'}
    </div>
    <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
      A 3D explainer is made story, then cast, then words: this plans the story
      and proposes the models it needs. The script is written once they are gathered.</div>`;
}
function toggleNewModel(id) {
  const picked = new Set(state.newModels || []);
  picked.has(id) ? picked.delete(id) : picked.add(id);
  state.newModels = [...picked];
  $('#newmodels').innerHTML = newModelsPicker();
}

function pickNewFormat(key) {
  state.newFormat = key;
  const nm = $('#newmodels'); if (nm) nm.innerHTML = newModelsPicker();
  const strip = $('#fmtpicker');
  if (!strip) return;
  strip.querySelectorAll('.tpl').forEach((el) =>
    el.classList.toggle('sel', el.dataset.fmt === key));
}


// A test run: one minute, quick research — the whole pipeline, cheaply.
function newTestRun(on) {
  state.newTest = !!on;
  const mins = $('#mins'), label = $('#minsLabel'), research = $('#research');
  if (mins) mins.disabled = state.newTest;
  if (label) label.textContent = state.newTest ? '1 minute (test run)' : `${mins ? mins.value : 12} minutes`;
  if (research) { research.disabled = state.newTest; if (state.newTest) research.value = 'quick'; }
}

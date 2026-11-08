// -------------------------------------------------------------------- home
async function renderHome() {
  const [projects, chans, shoots] = await Promise.all([
    api('/api/projects'), api('/api/channels'), api('/api/footage/shoots'),
  ]);
  state.channels = chans;
  state.soloCount = projects.filter(p => !p.channel_id).length;
  paintSidebar();
  let homeQuery = '';
  try { homeQuery = localStorage.getItem('corkbored.homeQuery') || ''; } catch (_) {}
  view.innerHTML = `<div class="home">
    <section class="panel home-start" aria-labelledby="start-heading">
      <div class="row"><h1 id="start-heading">Idea in. Episode out.</h1><span class="micro">New video</span></div>
      <div class="row home-start-modes" role="group" aria-label="Start from">
        <button class="btn" data-start="idea" onclick="homeStart('idea')">An idea</button>
        <button class="btn" data-start="script" onclick="homeStart('script')">My own script</button>
        <button class="btn" disabled aria-describedby="footage-note">A footage shoot</button>
        <button class="btn" data-start="format" onclick="homeStart('format')">A saved style</button>
        <button class="btn ghost" onclick="$('#projfile').click()">Open a .corkbored file</button>
        <input type="file" id="projfile" accept=".corkbored,.youslop" hidden
          onchange="openProjectFile(this.files[0]);this.value=''">
      </div>
      <p id="footage-note" class="sub">Starting a video from a shoot is coming with footage integration.
        <a href="#/guide">See how it works</a></p>
      <label class="field" id="idea-field"><span>What is the video about?</span>
        <textarea id="idea" rows="2" placeholder="Describe the story you want to tell."></textarea></label>
      <div id="script-fields" hidden>
        <label class="field"><span>Your script — paste the whole thing, headings and all</span>
          <textarea id="script" rows="8" placeholder="Paste your article or script. It will be split into paragraph-sized takes."></textarea></label>
        <label class="field"><span>How closely should it stick to your words?</span><select id="fidelity">
          <option value="faithful">Faithful — keep my words, just split them for reading</option>
          <option value="adapted">Adapted — smooth written prose into speech</option></select></label>
      </div>
      <div class="home-controls">
        <label class="field"><span>Channel</span><select id="chan" onchange="channelPicked()">
          <option value="">Standalone video</option>
          ${chans.map(c => `<option value="${esc(c.id)}" ${c.id === state.presetChannel ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
          <option value="__new">New channel…</option></select></label>
        <div class="field"><span>Style</span><button type="button" class="btn style-current" id="home-style" onclick="openStylePicker('home')"></button></div>
        <div class="field"><span id="shape-label">Shape</span>
          <div class="row" role="group" aria-labelledby="shape-label">
            <button class="btn" data-shape="portrait" onclick="homeShape('portrait')">Short · 9:16</button>
            <button class="btn" data-shape="landscape" onclick="homeShape('landscape')">Long · 16:9</button>
          </div></div>
        <label class="field"><span>Length</span><select id="mins"></select></label>
        <label class="field"><span>Research</span><select id="research" onchange="state.newResearch=this.value">
          <option value="quick" title="One search pass">Quick</option><option value="deep" title="Several rounds: slower, more Claude calls">Deep</option>
        </select></label>
        <button class="btn primary" onclick="createProject(this)">Start video</button>
      </div>
      <p id="shape-note" class="sub" hidden>Short targets at most 60 seconds. Rendering is landscape only for now.
        Pasted scripts keep their full length; keep yours under 60 seconds for a Short.</p>
      <p id="script-length-note" class="sub" hidden>Length comes from your script, measured after import.</p>
      <form id="home-new-channel" hidden onsubmit="createHomeChannel(event)">
        <div class="row">
          <label class="field"><span>Channel name</span><input type="text" id="home-channel-name" required></label>
          <label class="field"><span>What does this channel cover?</span><input type="text" id="home-channel-concept"></label>
          <button class="btn" type="submit">Create channel</button>
          <button class="btn ghost" type="button" onclick="$('#home-new-channel').hidden=true">Cancel</button>
        </div>
      </form>
      <details id="home-more"><summary>More options</summary>
        <div class="grid-3">
          <label class="field"><span>Delivery</span><select id="delivery" onchange="state.newDelivery=this.value">
            <option value="voice_over">Voice-over</option><option value="on_camera">On camera</option><option value="mixed">Mixed</option></select></label>
          <label class="field"><span>Tone</span><select id="tone">
            ${['warm documentary', 'cool and analytical', 'plain and understated', 'tense and propulsive', 'wry and literary'].map(t => `<option>${t}</option>`).join('')}
          </select></label>
        </div>
        <label class="field"><span><input type="checkbox" id="testrun" ${state.newTest ? 'checked' : ''}
          onchange="newTestRun(this.checked)"> Test run — 1 minute, quick research</span></label>
        <div id="newmodels">${newModelsPicker()}</div>
        <label class="field"><span id="everyLabel">${pictureEveryLabel(state.newPictureEvery || 1)}</span>
          <input type="range" id="every" min="1" max="6" value="${state.newPictureEvery || 1}"
            oninput="state.newPictureEvery=+this.value;$('#everyLabel').textContent=pictureEveryLabel(+this.value)"></label>
        <p class="sub">1 is a new picture every paragraph. Raise it when archives are thin to hold fewer pictures longer. Changeable later in Visuals.</p>
      </details>
    </section>
    <div class="home-lists">
      <section id="standalone" aria-labelledby="projects-heading">
        <div class="row home-list-tools"><h2 id="projects-heading">Projects</h2>
          <input id="home-query" type="search" aria-label="Search projects" placeholder="Search title, channel or stage" value="${esc(homeQuery)}">
          <select id="home-channel" aria-label="Filter channel"><option value="*">All channels</option><option value="">Standalone</option>
            ${chans.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select>
          <select id="home-sort" aria-label="Sort projects"><option value="updated">Recently updated</option><option value="title">Title</option></select>
        </div>
        <div class="home-table-wrap"><table class="home-table"><thead><tr>
          <th>Title</th><th>Channel</th><th>Stage</th><th>Length</th><th>Updated</th>
        </tr></thead><tbody id="home-videos" aria-live="polite"></tbody></table></div>
      </section>
      <aside aria-labelledby="shoots-heading"><h2 id="shoots-heading">Footage shoots</h2>
        ${shoots.map(s => `<a class="home-shoot" href="#/footage/${encodeURIComponent(s.id)}">
          <b>${esc(s.name)}</b><span class="mono">${fmtTime(s.seconds)} · ${s.files} files · ${s.clips} clips</span>
          <span>${s.labelled} of ${s.clips} clips labelled</span></a>`).join('') || '<p class="empty-note">No shoots yet. Import a folder or camera card.</p>'}
        <button class="btn ghost" onclick="go('#/footage')" aria-describedby="import-shoot-note">Import a shoot: folder or camera card</button>
        <p class="sub" id="import-shoot-note">Link originals or keep a copy; proxies process in the background.</p>
      </aside>
    </div>
  </div>`;
  const names = new Map(chans.map(c => [c.id, c.name]));
  const paintVideos = () => {
    const query = $('#home-query').value.toLocaleLowerCase().trim();
    try { localStorage.setItem('corkbored.homeQuery', $('#home-query').value); } catch (_) {}
    const channel = $('#home-channel').value;
    const matches = projects.filter(p => (channel === '*' || (p.channel_id || '') === channel)
      && [p.title, p.idea, names.get(p.channel_id) || 'Standalone', p.stage?.label, p.stage?.reason]
        .join(' ').toLocaleLowerCase().includes(query));
    matches.sort($('#home-sort').value === 'title'
      ? (a, b) => (a.title || a.idea || '').localeCompare(b.title || b.idea || '')
      : (a, b) => b.updated_at - a.updated_at);
    $('#home-videos').innerHTML = matches.map(p => `<tr>
      <td><a href="#/p/${p.id}/${p.stage.id}">${esc(p.title || p.idea.slice(0, 70))}</a>${p.test ? ' <span class="pill">test</span>' : ''}</td>
      <td>${esc(names.get(p.channel_id) || 'Standalone')}</td>
      <td><span class="pill ${p.stage.status === 'ready' ? 'on' : ''}">${esc(p.stage.label)}</span>
        <span class="home-stage-detail">${esc(p.stage.reason)}</span></td>
      <td class="mono">~${fmtTime(p.est_seconds)}</td>
      <td class="mono"><time datetime="${new Date(p.updated_at * 1000).toISOString()}">${esc(new Date(p.updated_at * 1000).toLocaleDateString())}</time></td>
    </tr>`).join('') || '<tr><td colspan="5">No videos match these filters.</td></tr>';
  };
  $('#home-query').oninput = paintVideos;
  $('#home-channel').onchange = paintVideos;
  $('#home-sort').onchange = paintVideos;
  paintVideos();
  $('#delivery').value = state.newDelivery || 'voice_over';
  $('#research').value = state.newResearch || 'quick';
  homeStart(state.mode === 'script' ? 'script' : 'idea');
  homeShape(state.newAspect || 'landscape');
  if (state.presetChannel) { state.presetChannel = null; channelPicked(); }
  else pickNewFormat(state.newFormat || 'kenburns');
  if (state.afterHome) { const run = state.afterHome; state.afterHome = null; run(); }
}

function homeStart(mode) {
  state.mode = mode === 'script' ? 'script' : 'idea';
  $('#idea-field').hidden = state.mode === 'script';
  $('#script-fields').hidden = state.mode !== 'script';
  $('#script-length-note').hidden = state.mode !== 'script';
  $('.home-start-modes').querySelectorAll('[data-start]').forEach(b => b.setAttribute('aria-pressed', b.dataset.start === mode));
  newTestRun(state.newTest);
  if (mode === 'format') openStylePicker('home');
}

function homeShape(aspect) {
  state.newAspect = aspect;
  document.querySelectorAll('[data-shape]').forEach(b => b.setAttribute('aria-pressed', b.dataset.shape === aspect));
  $('#mins').innerHTML = aspect === 'portrait' ? '<option value="1">≤60 seconds</option>'
    : Array.from({length: 16}, (_, i) => i + 7).map(n => `<option value="${n}" ${n === 12 ? 'selected' : ''}>${n} min</option>`).join('');
  $('#shape-note').hidden = aspect !== 'portrait';
  newTestRun(state.newTest);
}

async function createHomeChannel(e) {
  e.preventDefault();
  const btn = e.submitter; btn.disabled = true;
  try {
    const c = await api('/api/channels', {method: 'POST', body: JSON.stringify({
      name: $('#home-channel-name').value.trim(), concept: $('#home-channel-concept').value.trim(),
    })});
    state.channels = await api('/api/channels');
    paintSidebar();
    const option = new Option(c.name, c.id, true, true);
    $('#chan').add(option, $('#chan').lastElementChild);
    $('#home-new-channel').hidden = true;
    channelPicked();
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; }
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
  if ($('#chan').value === '__new') {
    $('#chan').value = '';
    $('#home-new-channel').hidden = false;
    $('#home-channel-name').focus();
  }
  const c = (state.channels || []).find((x) => x.id === $('#chan').value);
  state.newKit = '';
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
  pickNewFormat(state.newFormat, false);
  if (c) toast(`New videos will use “${c.name}”’s look and opening slate.`);
}

function pictureEveryLabel(n) {
  return `New picture every — ${n} ${n === 1 ? 'paragraph' : 'paragraphs'}`;
}

async function createProject(btn) {
  const scripting = state.mode === 'script';
  const body = { aspect: state.newAspect || 'landscape', delivery: $('#delivery').value, tone: $('#tone').value, channel_id: $('#chan').value || '',
                 format: state.newFormat || 'kenburns',
                 picture_every: state.newPictureEvery || 1 };

  if (state.newKit) body.kit_id = state.newKit;
  if (scripting) {
    const script = $('#script').value.trim();
    if (script.split(/\s+/).length < 120) {
      return toast('Paste a bit more — that is too short to build a video from.', true);
    }
    body.script = script;
    body.fidelity = $('#fidelity').value;
  } else {
    body.idea = $('#idea').value.trim();
    if (body.idea.length < 8) return toast('Describe the idea in a sentence or two.', true);
    body.target_minutes = +$('#mins').value;
    body.research_mode = $('#research').value;
    if (state.newTest) { body.test = true; body.target_minutes = 1; body.research_mode = 'quick'; }
  }
  if (isStage(body.format)) body.models = state.newModels || [];

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
  const kit = (state.styleKits || []).find(k => k.id === state.newKit);
  const card = $('#home-style');
  if (card) card.innerHTML = `${stylePoster(kit?.id || key)}<span>${esc(kit?.name || styleName(key))}<small>Change style</small></span>`;
  const nm = $('#newmodels'); if (nm) nm.innerHTML = newModelsPicker();
}

// A test run: one minute, quick research — the whole pipeline, cheaply.
function newTestRun(on) {
  state.newTest = !!on;
  const mins = $('#mins'), research = $('#research');
  if (mins) {
    mins.querySelector('[data-test]')?.remove();
    if (state.newTest && state.mode !== 'script') {
      const option = new Option('1 min (test run)', '1', true, true);
      option.dataset.test = 'true'; mins.add(option);
    }
    mins.disabled = state.newTest || state.mode === 'script';
  }
  if (research) {
    research.disabled = state.newTest || state.mode === 'script';
    research.value = state.newTest ? 'quick' : state.newResearch || 'quick';
  }
  if ($('#testrun')) $('#testrun').disabled = state.mode === 'script';
}


// ------------------------------------------------------------------ render
async function paintRender() {
  const p = state.project;
  const st = p.style;
  const missingMedia = p.slides.filter((s) => !s.chosen_id).length;
  const missingTakes = p.slides.length - p.recorded_count;
  const music = await api('/api/music').catch(() => []);
  await ensureChannelsLoaded();          // the panel below files it in one
  // Only a standalone video picks its own slate and end card here; inside a
  // channel those live on the channel page and this page never draws them.
  if (!p.channel_id && !state.templates) {
    [state.templates, state.endTemplates] = await Promise.all([
      api('/api/intro/templates').catch(() => []),
      api('/api/outro/templates').catch(() => []),
    ]);
  }
  if (!state.youtubeCategories) {
    state.youtubeCategories = await api('/api/youtube/status')
      .then((r) => r.categories).catch(() => []);
  }

  $('#tabbody').innerHTML = `
    <div class="panel tl" id="tl"></div>
    <div class="grid-2">
      <div class="panel">
        <h3>Look</h3>
        <label class="field"><span>Video style</span></label>
        ${formatPicker(st.format || 'kenburns', st.accent, 'pickProjectFormat')}
        ${st.format === 'board' ? boardKnobs(st, 'saveStyle') : ''}
        ${isCut(st.format) ? cutKnobs(st, 'saveStyle') : ''}
        <label class="field"><span>Vignette — <b>${st.vignette.toFixed(2)}</b></span>
          <input type="range" min="0" max="0.8" step="0.02" value="${st.vignette}"
            onchange="saveStyle({vignette:+this.value})"></label>
        ${st.format === 'board' ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            The board cut draws every slide itself and ignores the drift, the
            grade and the chapter titles below. Write the boards on the
            pictures tab.</div>`
        : isCut(st.format) ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            This cut draws every frame itself, on hard cuts, and ignores the
            drift, crossfade, grade and chapter titles below. Write its cues
            on the pictures tab.</div>`
        : st.format === 'essay' ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            The essay cut sets the narration on screen in phrases and ignores the
            drift and the chapter titles below.</div>`
        : `<label class="field"><span>Ken Burns drift — <b>${st.ken_burns_amount.toFixed(2)}</b></span>
          <input type="range" min="0" max="0.24" step="0.01" value="${st.ken_burns_amount}"
            onchange="saveStyle({ken_burns:+this.value>0, ken_burns_amount:+this.value})"></label>`}
        <label class="field"><span>Crossfade — <b>${st.transition.toFixed(2)}s</b></span>
          <input type="range" min="0" max="1.6" step="0.05" value="${st.transition}"
            onchange="saveStyle({transition:+this.value})"></label>
        <label class="row" style="gap:8px;cursor:pointer;margin:-4px 0 14px">
          <input type="checkbox" ${st.chapter_cards !== false ? 'checked' : ''} style="width:auto"
            onchange="saveStyle({chapter_cards:this.checked})">
          <span>chapter cards${chapterCount(p) ? ` — ${chapterCount(p)} marked on the script tab` : ''}</span>
        </label>
        ${st.format === 'board' || isCut(st.format) || (st.format || '').startsWith('custom:') ? `
          <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
            This cut draws its own frames, so a chapter still opens a fresh
            slide and a longer pause, but no card is laid over it.</div>` : ''}
        <label class="field"><span>Grade</span>
          <select onchange="saveStyle({grade:this.value})">
            ${['warm', 'neutral', 'cool', 'mono'].map((g) =>
              `<option ${g === st.grade ? 'selected' : ''}>${g}</option>`).join('')}
          </select></label>
        <label class="field"><span>Title accent</span>
          <input type="text" value="${esc(st.accent)}" onchange="saveStyle({accent:this.value})"></label>
      </div>

      <div class="panel">
        <h3>Sound</h3>
        <label class="field"><span>Music bed</span>
          <select onchange="saveProject({music:this.value})">
            <option value="" ${!p.music ? 'selected' : ''}>— none —</option>
            <option value="__auto__" ${p.music === '__auto__' ? 'selected' : ''}>— pick one for me —</option>
            ${music.map((m) => `<option ${m.name === p.music ? 'selected' : ''}
              value="${esc(m.name)}">${esc(m.name)}</option>`).join('')}
          </select></label>
        <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
          ${!p.music
            ? 'No bed: the video plays on the narration alone.'
            : p.music === '__auto__'
              ? (music.length ? 'One of the tracks below, the same one on every re-render.'
                              : 'Nothing in assets/music to pick from yet.')
              : 'Looped if it is shorter than the video, and trimmed to length.'}</div>
        <div class="row" style="gap:10px;margin:0 0 14px">
          ${music.length === 0
            ? `<div class="pill warn">drop mp3s into assets/music to get a bed</div>` : ''}
          <button class="btn sm ghost" onclick="revealFile('music','','')">open the music folder</button>
          <span class="mono" style="color:var(--ink-faint)">add tracks, then reload this page to pick them</span>
        </div>
        <label class="field"><span>Music under voice — <b>${st.music_db.toFixed(0)} dB</b></span>
          <input type="range" min="-40" max="-14" step="1" value="${st.music_db}"
            onchange="saveStyle({music_db:+this.value})"></label>
        <label class="field"><span>Pause between paragraphs — <b>${(st.paragraph_gap ?? 0.42).toFixed(2)}s</b></span>
          <input type="range" min="0.15" max="1.2" step="0.01" value="${st.paragraph_gap ?? 0.42}"
            onchange="saveStyle({paragraph_gap:+this.value})"></label>
        <div class="mono" style="color:var(--ink-faint);margin:-8px 0 14px">
          The pause varies around this: about half of it when a paragraph runs on
          mid-sentence, twice it where a new section starts.</div>
        <div class="mono" style="color:var(--ink-faint)">
          Final mix is mastered to −14 LUFS, which is what YouTube wants.</div>
      </div>
    </div>

    ${openingPanel(p)}

    ${descriptionPanel(p)}

    ${presenterPanel(p)}

    <div class="panel" style="margin-top:18px">
      <div class="row">
        <button class="btn primary" onclick="doRender(false)"
          ${missingTakes === p.slides.length ? 'disabled' : ''}>Render the video</button>
        <button class="btn" onclick="doRender(true)">Preview cut (no voice)</button>
        <div class="spacer"></div>
        ${missingTakes ? `<span class="pill warn">${missingTakes} paragraph${missingTakes > 1 ? 's' : ''} unrecorded</span>` : ''}
        ${missingMedia ? `<span class="pill warn">${missingMedia} without a picture</span>` : ''}
      </div>
      <div class="mono" style="color:var(--ink-faint);margin-top:10px">
        ${missingTakes && missingTakes < p.slides.length
          ? 'Unrecorded paragraphs are skipped entirely in a full render.'
          : 'Preview uses estimated timings so you can check the picture edit before recording.'}
      </div>
    </div>

    ${p.render && p.render.output ? `
      <h2>Last render</h2>
      ${videoTag(`/api/projects/${p.id}/file/${p.render.output}`,
                 { scope: 'project', id: p.id, rel: p.render.output })}
      <div class="row" style="margin-top:12px">
        <span class="mono" style="color:var(--ink-faint)">
          ${fmtTime(p.render.duration)} · ${p.render.size_mb} MB · ${p.render.slides} slides
          ${p.render.preview ? '· preview' : ''}</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" title="show the file on disk"
          onclick="revealFile('project','${p.id}','${esc(encodeURIComponent(p.render.output))}')">
          open the folder</button>
        <a class="btn sm" href="/api/projects/${p.id}/download">download</a>
      </div>
      ${await uploadPanel(p)}` : ''}
  `;
  tlMount();
}

// How this video opens and closes. In a channel both come from the channel,
// which is most of what a channel is for, and this is only the switch for
// using them. Standalone, the video carries its own: the same slates and end
// cards, drawn from its own title, subtitle and colours, minus the ones that
// need a cast of portraits to fill.
// Where this video is filed. Moving it changes where its opening and close
// come from and which channel it uploads to; nothing about the script, the
// pictures or the recordings moves with it.
function channelPicker(p) {
  const chans = state.channels || [];
  return `
    <label class="row" style="gap:8px">
      <span class="mono" style="color:var(--ink-faint)">in</span>
      <select style="width:auto" onchange="saveOpening({channel_id:this.value})">
        <option value="" ${!p.channel_id ? 'selected' : ''}>— no channel —</option>
        ${chans.map((c) => `<option value="${c.id}" ${c.id === p.channel_id ? 'selected' : ''}>
          ${esc(c.name)}</option>`).join('')}
      </select>
    </label>`;
}

function openingPanel(p) {
  if (p.channel_id) {
    return `
      <div class="panel" id="opening-panel" style="margin-top:18px">
        <div class="row">
          <strong>Channel opening and close</strong>
          ${channelPicker(p)}
          <button class="btn sm" onclick="saveProjectFormat()">Save as format</button>
          <div class="spacer"></div>
          <label class="row" style="gap:8px;cursor:pointer">
            <input type="checkbox" ${p.use_intro ? 'checked' : ''} style="width:auto"
              onchange="saveProject({use_intro:this.checked})">
            <span>open with the channel slate</span>
          </label>
          <label class="row" style="gap:8px;cursor:pointer">
            <input type="checkbox" ${p.use_outro ? 'checked' : ''} style="width:auto"
              onchange="saveProject({use_outro:this.checked})">
            <span>close on the end screen</span>
          </label>
          <a class="btn sm ghost" href="#/c/${p.channel_id}">edit them</a>
        </div>
      </div>`;
  }

  const st = p.style;
  const intro = p.intro || {};
  const outro = p.outro || {};
  const slates = (state.templates || []).filter((t) => !t.needs_images);
  const ends = state.endTemplates || [];
  const openOn = !!intro.template;
  const firstSlate = (slates[0] || {}).key || 'signal';
  return `
    <div class="panel" id="opening-panel" style="margin-top:18px">
      <div class="row">
        <strong>Opening and close</strong>
        ${channelPicker(p)}
        <div class="spacer"></div>
        <label class="row" style="gap:8px;cursor:pointer">
          <input type="checkbox" ${openOn ? 'checked' : ''} style="width:auto"
            onchange="saveOpening({intro:{template:this.checked?'${esc(intro.template || firstSlate)}':''}})">
          <span>open on a title card</span>
        </label>
        <label class="row" style="gap:8px;cursor:pointer">
          <input type="checkbox" ${outro.enabled ? 'checked' : ''} style="width:auto"
            onchange="saveOpening({outro:{enabled:this.checked}})">
          <span>close on an end card</span>
        </label>
      </div>
      ${!openOn && !outro.enabled ? `
        <div class="mono" style="color:var(--ink-faint);margin-top:10px">
          A standalone video starts cold and ends on its last picture unless you
          turn these on. Put it in a channel instead and every video in the
          series opens the same way.</div>` : ''}

      ${openOn ? `
        <div class="row" style="margin:14px 0 8px">
          <span class="mono" style="color:var(--ink-faint);flex:1;min-width:0">
            The title card. Your video's title is the type on it; the subtitle is
            the line above. The slates that need a cast of faces belong to a
            channel and aren't offered here.</span>
          <button class="btn sm" onclick="previewOpening('intro')">preview it</button>
        </div>
        <div class="tpl-strip">
          ${slates.map((t) => `
            <div class="tpl ${t.key === intro.template ? 'sel' : ''}"
                 onclick="saveOpening({intro:{template:'${t.key}'}})">
              ${tplArt(t.key, st.accent)}
              <div class="tpl-name">${esc(t.label)}</div>
            </div>`).join('')}
        </div>
        <div class="grid-3">
          <label class="field"><span>On screen — <b>${(intro.duration || 5).toFixed(1)}s</b></span>
            <input type="range" min="2" max="12" step="0.5" value="${intro.duration || 5}"
              onchange="saveProject({intro:{duration:+this.value}})"></label>
          <label class="field"><span>Beat before the video — <b>${(intro.hold ?? 1).toFixed(1)}s</b></span>
            <input type="range" min="0" max="4" step="0.1" value="${intro.hold ?? 1}"
              onchange="saveProject({intro:{hold:+this.value}})"></label>
        </div>
        ${stingBlock('intro', intro)}` : ''}

      ${outro.enabled ? `
        <div class="row" style="margin:14px 0 8px">
          <span class="mono" style="color:var(--ink-faint);flex:1;min-width:0">
            The end card. The plates are empty on purpose — they are where you
            line up YouTube's own end-screen elements in Studio.</span>
          <button class="btn sm" onclick="previewOpening('outro')">preview it</button>
        </div>
        <div class="tpl-strip">
          ${ends.map((t) => `
            <div class="tpl ${t.key === outro.template ? 'sel' : ''}"
                 onclick="saveOpening({outro:{template:'${t.key}'}})">
              ${endArt(t.key, st.accent)}
              <div class="tpl-name">${esc(t.label)}</div>
            </div>`).join('')}
        </div>
        <div class="grid-3">
          <label class="field"><span>The line on it</span>
            <input type="text" value="${esc(outro.cta || '')}"
              placeholder="${esc((ends.find((t) => t.key === outro.template) || {}).cta || 'More like this')}"
              onchange="saveProject({outro:{cta:this.value}})"></label>
          <label class="field"><span>Your @handle</span>
            <input type="text" value="${esc(outro.handle || '')}" placeholder="@yourchannel"
              onchange="saveProject({outro:{handle:this.value}})"></label>
          <label class="field"><span>On screen — <b>${(outro.duration || 12).toFixed(0)}s</b></span>
            <input type="range" min="5" max="20" step="1" value="${outro.duration || 12}"
              onchange="saveProject({outro:{duration:+this.value}})"></label>
        </div>
        ${stingBlock('outro', outro)}` : ''}
    </div>`;
}

function stingSpanOf(role, spec) {
  return role === 'intro' ? (spec.duration || 5) + (spec.music_tail || 0) : (spec.duration || 12);
}

function stingBlock(role, spec) {
  const f = STING_FIELDS[role];
  const p = state.project;
  const has = !!spec[f.file];
  const dur = spec[f.dur] || 0;
  const maxStart = Math.max(0, dur - 1);
  const start = Math.min(spec[f.start] || 0, maxStart);
  const span = stingSpanOf(role, spec);
  const label = role === 'intro' ? 'Opening sting' : 'End card sting';
  const hint = role === 'intro'
    ? 'Its own music for the title card. The music bed waits until the card is over.'
    : 'Plays as the end card comes up and runs while it is on screen.';
  const set = (k, v) => `saveProject({${role}:{${k}:${v}}})`;
  return `
    <div class="panel" style="background:#0f1116;margin:12px 0 4px">
      <div class="row" style="margin-bottom:${has ? '14px' : '0'}">
        <div style="flex:1;min-width:200px">
          <strong>${label}</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:4px">
            ${has ? esc(spec[f.name] || 'sting') : hint}</div>
        </div>
        ${has ? `
          <audio id="sting-${role}" controls style="max-width:280px"
            src="/api/projects/${p.id}/file/${spec[f.file]}?v=${dur}-${esc(spec[f.name] || '')}"></audio>
          <button class="btn sm ghost danger" onclick="removeProjectSting('${role}')">remove</button>`
        : `<label class="btn sm" style="cursor:pointer">choose a sting
             <input type="file" accept="audio/*" hidden
               onchange="uploadProjectSting('${role}', this.files[0])">
           </label>`}
      </div>
      ${has ? `
        <div class="row" style="gap:10px;margin-bottom:12px">
          <div class="mono" style="flex:1;min-width:200px;color:var(--ink-faint)">
            ${fmtTime(dur)} long — it takes ${span.toFixed(1)}s, ${fmtTime(start)} to
            ${fmtTime(start + span)}${start + span > dur + 0.05 ? '. That runs off the end of the track.' : '.'}</div>
          <button class="btn sm ghost" onclick="auditionProjectSting('${role}')">hear the window</button>
        </div>
        <label class="field" style="margin:0 0 12px"><span>Start it — <b>${fmtTime(start)}${
            start > 0 ? ' into the track' : ' — the very top'}</b></span>
          <input type="range" min="0" max="${maxStart.toFixed(1)}" step="0.1" value="${start.toFixed(1)}"
            oninput="scrubProjectSting('${role}', +this.value)"
            onchange="${set(f.start, '+this.value')}"></label>
        <div class="grid-3">
          <label class="field" style="margin:0"><span>Level vs the narration — <b>${(spec[f.db] ?? -4).toFixed(0)} dB</b></span>
            <input type="range" min="-20" max="4" step="1" value="${spec[f.db] ?? -4}"
              onchange="${set(f.db, '+this.value')}"></label>
          ${role === 'intro' ? `
            <label class="field" style="margin:0"><span>Rings on past the card — <b>${(spec.music_tail ?? 1.1).toFixed(1)}s</b></span>
              <input type="range" min="0" max="3" step="0.1" value="${spec.music_tail ?? 1.1}"
                onchange="saveProject({intro:{music_tail:+this.value}})"></label>` : '<div></div>'}
          <label class="field" style="margin:0"><span>Fade out — <b>${
              (spec[f.fade] ?? 1.35) < 0.1 ? 'straight cut' : (spec[f.fade] ?? 1.35).toFixed(1) + 's'}</b></span>
            <input type="range" min="0" max="${role === 'intro' ? 4 : 8}" step="0.1" value="${spec[f.fade] ?? 1.35}"
              onchange="${set(f.fade, '+this.value')}"></label>
        </div>` : ''}
    </div>`;
}

async function uploadProjectSting(role, file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    state.project = await api(`/api/projects/${state.project.id}/sting/${role}`,
      { method: 'POST', body: fd });
    toast('sting added');
    render();
  } catch (e) { toast(e.message, true); }
}

async function removeProjectSting(role) {
  try {
    state.project = await api(`/api/projects/${state.project.id}/sting/${role}`,
      { method: 'DELETE' });
    render();
  } catch (e) { toast(e.message, true); }
}

function scrubProjectSting(role, seconds) {
  const el = document.getElementById(`sting-${role}`);
  if (el) { try { el.currentTime = seconds; } catch (e) { /* not loaded yet */ } }
}

// Play exactly the stretch the card will use, and stop where it stops.
function auditionProjectSting(role) {
  const el = document.getElementById(`sting-${role}`);
  const spec = state.project && state.project[role];
  if (!el || !spec) return;
  const f = STING_FIELDS[role];
  clearTimeout(window._stingStop);
  const from = Math.min(spec[f.start] || 0, Math.max(0, (spec[f.dur] || 0) - 1));
  el.currentTime = from;
  el.play().catch(() => {});
  window._stingStop = setTimeout(() => { el.pause(); el.currentTime = from; },
                                 stingSpanOf(role, spec) * 1000);
}

// Saves that change which controls are on screen, so the tab is repainted.
async function saveOpening(patch) {
  await saveProject(patch);
  render();
}

// The card on its own, full size — a few seconds of frames, so there is
// nothing to gain from rendering it small the way a segment preview does.
async function previewOpening(kind) {
  const r = await api(`/api/projects/${state.project.id}/preview-opening`,
    { method: 'POST', body: JSON.stringify({ kind }) });
  watchJob(r.job, `${kind} preview`, (j) => {
    if (j.state !== 'done' || !j.result) return;
    const card = j.result;
    openVideoModal(
      `<strong>${card.kind === 'outro' ? 'End card' : 'Title card'}</strong>
       <span class="mono" style="color:var(--ink-faint)">${fmtTime(card.seconds)}</span>`,
      videoTag(`/api/projects/${state.project.id}/file/${card.path}?v=${card.rendered_at}`,
               { scope: 'project', id: state.project.id, rel: card.path },
               'controls autoplay playsinline'));
  });
  render();
}

// Publishing itself: connecting a channel to YouTube lives on the channel
// page (youtubePanel()); this is the per-video "send this render" half.
async function uploadPanel(p) {
  if (!p.channel_id) {
    return `<div class="panel" style="margin-top:18px">
      <div class="mono" style="color:var(--ink-faint)">
        This video isn't on a channel, so there's nowhere to publish it to —
        add it to a channel first, or download and upload it by hand.</div>
    </div>`;
  }
  const yt = p.youtube || {};
  if (!yt.connected) {
    return `<div class="panel" style="margin-top:18px">
      <div class="row">
        <div style="flex:1;min-width:200px">
          <strong>Publish to YouTube</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:4px">
            Connect this channel to YouTube to upload straight from here.</div>
        </div>
        <a class="btn sm" href="#/c/${p.channel_id}">connect it</a>
      </div>
    </div>`;
  }

  if (!state.upload || state.upload.pid !== p.id) {
    // The written description if there is one; the bare credits otherwise.
    let description = p.description || '';
    if (!description) {
      try { description = (await api(`/api/projects/${p.id}/credits`)).text || ''; }
      catch { /* the field just starts blank */ }
    }
    state.upload = {
      pid: p.id, title: p.title || p.idea.slice(0, 90), description,
      tags: (p.yt_tags || []).join(', '), category_id: '22', privacy: 'private',
    };
  }
  const u = state.upload;
  const cats = state.youtubeCategories || [];
  const already = (p.render || {}).youtube_url;

  return `<div class="panel" style="margin-top:18px">
    <div class="row" style="margin-bottom:14px">
      <strong>Publish to YouTube</strong>
      <span class="mono" style="color:var(--ink-faint)">— ${esc(yt.channel_title || '')}</span>
      <div class="spacer"></div>
      ${already ? `<a class="pill on" href="${esc(already)}" target="_blank">already uploaded — view it</a>` : ''}
    </div>
    <label class="field"><span>Title</span>
      <input type="text" value="${esc(u.title)}" maxlength="100"
        onchange="state.upload.title=this.value"></label>
    <label class="field"><span>Description</span>
      <textarea rows="5" onchange="state.upload.description=this.value">${esc(u.description)}</textarea></label>
    <div class="grid-3">
      <label class="field" style="margin:0"><span>Tags — comma separated</span>
        <input type="text" value="${esc(u.tags)}" placeholder="history, documentary"
          onchange="state.upload.tags=this.value"></label>
      <label class="field" style="margin:0"><span>Category</span>
        <select onchange="state.upload.category_id=this.value">
          ${cats.map((c) => `<option value="${c.id}" ${c.id === u.category_id ? 'selected' : ''}>
            ${esc(c.label)}</option>`).join('')}
        </select></label>
      <label class="field" style="margin:0"><span>Privacy</span>
        <select onchange="state.upload.privacy=this.value">
          <option value="private" ${u.privacy === 'private' ? 'selected' : ''}>Private</option>
          <option value="unlisted" ${u.privacy === 'unlisted' ? 'selected' : ''}>Unlisted</option>
          <option value="public" ${u.privacy === 'public' ? 'selected' : ''}>Public</option>
        </select></label>
    </div>
    <div class="row" style="margin-top:6px">
      <button class="btn sm" onclick="doYoutubeUpload()">
        ${already ? 'upload again' : 'upload to YouTube'}</button>
      ${u.privacy !== 'private' ? `<span class="pill warn">will be ${u.privacy} the moment it finishes</span>` : ''}
    </div>
  </div>`;
}

async function doYoutubeUpload() {
  const u = state.upload;
  if (u.privacy !== 'private'
      && !confirm(`This will be ${u.privacy} on YouTube as soon as it finishes uploading. Continue?`)) {
    return;
  }
  const r = await api(`/api/projects/${state.project.id}/youtube/upload`, {
    method: 'POST',
    body: JSON.stringify({
      title: u.title, description: u.description,
      tags: u.tags.split(',').map((t) => t.trim()).filter(Boolean),
      category_id: u.category_id, privacy: u.privacy,
    }),
  });
  watchJob(r.job, 'youtube upload');
  render();
}

// ------------------------------------------------------------ description
// The YouTube description: Claude writes the hook, the summary and the tags;
// the chapter timestamps come off the timeline and the credits off the
// pictures, so neither is guessed. Editable, and kept on the project.
function descriptionPanel(p) {
  const text = p.description || '';
  const chars = text.length;
  return `
    <div class="panel" style="margin-top:18px">
      <div class="row" style="margin-bottom:10px">
        <strong>YouTube description</strong>
        <span class="mono" style="color:var(--ink-faint)">hook, summary, chapters with
          timestamps, credits and tags</span>
        <div class="spacer"></div>
        <button class="btn sm ${text ? 'ghost' : ''}" onclick="writeDescription()">
          ${text ? 'write it again' : 'write it'}</button>
        ${text ? `<button class="btn sm" onclick="copyDescription()">copy</button>` : ''}
      </div>
      ${text ? `
        <textarea id="desc-text" rows="14" style="width:100%;font-family:var(--mono, monospace);font-size:13px"
          onchange="saveDescription(this.value)">${esc(text)}</textarea>
        <div class="row" style="margin-top:6px">
          <span class="mono" style="color:${chars > 4800 ? 'var(--warn, #e0a050)' : 'var(--ink-faint)'}">
            ${chars.toLocaleString()} / 5,000 characters</span>
          <div class="spacer"></div>
          ${p.recorded_count < p.slides.length ? `<span class="pill warn">${p.slides.length - p.recorded_count}
            paragraph${p.slides.length - p.recorded_count === 1 ? '' : 's'} not recorded — chapter
            times are estimates; write it again after recording</span>` : ''}
        </div>
        <label class="field" style="margin:10px 0 0"><span>Tags — comma separated</span>
          <input type="text" value="${esc((p.yt_tags || []).join(', '))}"
            onchange="saveProject({yt_tags:this.value.split(',').map((t)=>t.trim()).filter(Boolean)})"></label>`
      : `<div class="mono" style="color:var(--ink-faint)">
          Chapters use the paragraphs you've marked as chapters (two or more), or the
          script's outline beats if you haven't. Timestamps are taken from the cut itself.</div>`}
    </div>`;
}

async function writeDescription() {
  const p = state.project;
  if (p.description && !confirm('Write the description again? Your edits to it will be replaced.')) return;
  try {
    const r = await api(`/api/projects/${p.id}/description`, { method: 'POST' });
    watchJob(r.job, 'description', (j) => {
      if (j.state === 'done') { state.upload = null; render(); }
    });
    render();
  } catch (e) { toast(e.message, true); }
}

async function saveDescription(text) {
  await saveProject({ description: text });
  state.upload = null;      // the upload form starts from the saved one
}

async function copyDescription() {
  const el = document.getElementById('desc-text');
  const text = el ? el.value : (state.project.description || '');
  try { await navigator.clipboard.writeText(text); toast('description copied'); }
  catch { if (el) { el.select(); document.execCommand('copy'); toast('description copied'); } }
}

// -------------------------------------------------------- talking-head clip
function presenterPanel(p) {
  const pr = p.presenter || {};
  const has = !!pr.path;
  const src = `/api/projects/${p.id}/file/${pr.path}?v=${p.updated_at}`;
  const max = pr.source_duration || 0;

  if (!has) {
    return `<div class="panel" style="margin-top:18px">
      <div class="row">
        <div style="flex:1;min-width:200px">
          <strong>Talking head</strong>
          <div class="mono" style="color:var(--ink-faint);margin-top:4px">
            Optional. A short piece to camera, cut in after the slate — viewers
            settle faster once they have seen your face.</div>
        </div>
        <label class="btn sm" style="cursor:pointer">choose a clip
          <input type="file" accept="video/*" hidden onchange="uploadPresenter(this.files[0])">
        </label>
      </div>
    </div>`;
  }

  return `<div class="panel" style="margin-top:18px">
    <div class="row" style="margin-bottom:14px">
      <strong>Talking head</strong>
      <span class="pill ${pr.enabled ? 'on' : ''}">${pr.duration.toFixed(1)}s on screen</span>
      ${pr.has_audio ? '' : '<span class="pill warn">no audio track</span>'}
      <div class="spacer"></div>
      <label class="row" style="gap:8px;cursor:pointer">
        <input type="checkbox" ${pr.enabled ? 'checked' : ''} style="width:auto"
          onchange="savePresenter({enabled:this.checked})">
        <span>include it</span>
      </label>
    </div>

    <div class="media-row">
      <div>
        ${videoTag(src, { scope: 'project', id: p.id, rel: pr.path },
                   'controls preload="metadata" id="presvid"')}
        <div class="mono" style="color:var(--ink-faint);margin-top:6px">
          ${esc(pr.filename)} · ${pr.width}×${pr.height} · ${max.toFixed(1)}s source</div>
      </div>
      <div>
        <label class="field"><span>Where it goes</span>
          <select onchange="savePresenter({position:this.value})">
            <option value="after_intro" ${pr.position === 'after_intro' ? 'selected' : ''}>
              after the channel slate</option>
            <option value="start" ${pr.position === 'start' ? 'selected' : ''}>
              at the very start, before the slate</option>
            <option value="end" ${pr.position === 'end' ? 'selected' : ''}>
              at the end, as a sign-off</option>
          </select></label>

        <label class="field"><span>Trim the start — <b>${pr.trim_start.toFixed(1)}s</b></span>
          <input type="range" min="0" max="${Math.max(0.1, max - 0.5).toFixed(1)}" step="0.1"
            value="${pr.trim_start}" oninput="scrubPresenter(this.value)"
            onchange="savePresenter({trim_start:+this.value})"></label>
        <label class="field"><span>Trim the end — <b>${pr.trim_end.toFixed(1)}s</b></span>
          <input type="range" min="0" max="${Math.max(0.1, max - 0.5).toFixed(1)}" step="0.1"
            value="${pr.trim_end}" oninput="scrubPresenter(${max} - this.value)"
            onchange="savePresenter({trim_end:+this.value})"></label>

        <div class="row">
          <button class="btn sm ghost" onclick="setPresenterFocal()">
            ${(pr.focal || []).length === 2 ? '✛ focus set' : 'set focus point'}</button>
          <div class="spacer"></div>
          <button class="btn sm ghost danger" onclick="removePresenter()">remove</button>
        </div>
        <div class="mono" style="color:var(--ink-faint);margin-top:10px">
          Your camera audio is levelled to match the narration 
          under it too. It dissolves in and out over ${(p.style.transition).toFixed(2)}s.</div>
      </div>
    </div>
  </div>`;
}

function scrubPresenter(t) {
  const v = document.getElementById('presvid');
  if (v) { v.currentTime = Math.max(0, +t); }
}

async function uploadPresenter(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  toast('uploading…');
  try {
    await api(`/api/projects/${state.project.id}/presenter`, { method: 'POST', body: fd });
    state.project = await api(`/api/projects/${state.project.id}`);
    render();
    toast('clip added');
  } catch (e) { toast(e.message, true); }
}

async function savePresenter(patch) {
  state.project = await api(`/api/projects/${state.project.id}`,
    { method: 'PATCH', body: JSON.stringify({ presenter: patch }) });
  render();
}

async function removePresenter() {
  if (!confirm('Remove the talking-head clip from this video?')) return;
  await api(`/api/projects/${state.project.id}/presenter`, { method: 'DELETE' });
  state.project = await api(`/api/projects/${state.project.id}`);
  render();
}

function setPresenterFocal() {
  const p = state.project, pr = p.presenter;
  // Grab a still from the clip so the point can be placed on an actual frame.
  const v = document.getElementById('presvid');
  const canvas = document.createElement('canvas');
  canvas.width = pr.width || 1280;
  canvas.height = pr.height || 720;
  let src;
  try {
    canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height);
    src = canvas.toDataURL('image/jpeg', 0.85);
  } catch { src = ''; }
  if (!src) return toast('Play the clip for a moment first, then set the point.', true);
  openFocal(src, pr.focal, (focal) => savePresenter({ focal }));
}

async function doRender(preview) {
  const path = `/api/projects/${state.project.id}/render`;
  let r = await api(path,
    { method: 'POST', body: JSON.stringify({ preview }) });
  if (r.check && r.check.counts.P0) {
    if (!confirm(`${r.check.counts.P0} P0 issues. Render anyway?`)) return;
    r = await api(path,
      { method: 'POST', body: JSON.stringify({ preview, force: true }) });
  }
  watchJob(r.job, preview ? 'preview render' : 'render');
  render();
}

// One explicit selection, independent of playback and scrubbing.
function tlItems(kind) {
  if (kind === 'music') return [{kind, id: 'music', sid: '', t0: 0, t1: TL.data.total}];
  if (kind === 'picture' || kind === 'slate') return tlSegs()
    .filter((s) => kind === 'picture' ? s.type === 'picture' : ['intro', 'outro'].includes(s.type))
    .map((s) => ({kind, id: s.ref, sid: s.lead, t0: s.start, t1: s.start + s.duration}));
  return tlParas().flatMap((q) => {
    const slide = state.project.slides.find((s) => s.id === q.id);
    if (kind === 'cue') return ((slide.cues || {})[state.project.style.format] || []).map((c, i) => ({
      kind, id: `${q.id}:${i}`, sid: q.id, cue: i,
      t0: q.timing.cues[i]?.start ?? q.start, t1: q.timing.cues[i]?.end ?? q.start + q.duration}));
    return [{kind, id: q.id, sid: q.id,
      t0: kind === 'title' ? q.timing.title_at.start : q.start,
      t1: kind === 'title' ? q.timing.title_at.start + q.timing.title_hold.value : q.start + q.duration}];
  });
}

function tlSelect(sel) {
  TL.selection = sel;
  tlInspector();
  tlSelectionPaint();
}

function tlSelectionPaint() {
  document.querySelectorAll('#tl-track [data-seg], #tl-track [data-para]').forEach((el) => {
    const s = TL.selection;
    el.classList.toggle('sel', !!s && (el.dataset.para === s.sid && s.kind === 'paragraph'
      || el.dataset.seg !== undefined && ['picture', 'slate'].includes(s.kind)
      && tlSegs()[+el.dataset.seg]?.ref === s.id));
  });
}

function tlSelectKind(kind) {
  const seg = tlSegAt(TL.cur);
  const para = [...(seg?.paragraphs || [])].reverse().find((q) => q.start <= TL.cur) || seg?.paragraphs[0];
  const items = tlItems(kind);
  tlSelect(items.find((s) => s.sid === para?.id) || items.find((s) => s.t0 <= TL.cur && s.t1 > TL.cur) || items[0] || null);
}

function tlSelectNext(dir) {
  if (!TL.selection) return;
  const items = tlItems(TL.selection.kind);
  const index = items.findIndex((s) => s.id === TL.selection.id);
  const item = items[Math.max(0, Math.min(items.length - 1, index + dir))];
  if (item) { tlPause(); tlSeek(item.t0, {ensure: false}); tlSelect(item); }
}

function tlInspector() {
  const box = $('#tl-inspector');
  if (!box) return;
  const sel = TL.selection, p = state.project;
  const kinds = ['picture', 'paragraph', 'title', 'cue', 'chapter', 'slate', 'music'];
  box.innerHTML = `<label for="tl-kind">Inspect</label><select id="tl-kind">
    <option value="">Select an item</option>${kinds.map((k) => `<option ${sel?.kind === k ? 'selected' : ''}>${k}</option>`).join('')}</select><button class="btn sm" id="tl-ask">Ask</button><div id="tl-fields"></div>`;
  $('#tl-ask').onclick = tlAsk;
  $('#tl-kind').onchange = (e) => e.target.value ? tlSelectKind(e.target.value) : tlSelect(null);
  const body = $('#tl-fields');
  if (!sel) { body.textContent = 'Select a picture or paragraph, or choose a kind at the playhead.'; return; }
  const slide = p.slides.find((s) => s.id === sel.sid);
  const para = tlParas().find((q) => q.id === sel.sid);
  const seg = tlSegs().find((s) => s.ref === sel.id);
  const field = (key, label, value, unit = '', options = null) => {
    const id = `tl-field-${key}`;
    return `<label for="${id}">${esc(label)}</label><div class="tl-input">${options
      ? `<select id="${id}" data-field="${key}">${options.map(([v, text]) => `<option value="${esc(v)}" ${String(value) === String(v) ? 'selected' : ''}>${esc(text)}</option>`).join('')}</select>`
      : `<input id="${id}" data-field="${key}" type="${unit ? 'number' : 'text'}" ${unit ? 'step="0.05"' : ''} value="${esc(value ?? '')}">`}
      ${unit ? `<span>${unit}</span>` : ''}</div>`;
  };
  const timing = (key, label, effective) => field(key, `${label} (blank = auto: ${effective.toFixed(2)} s)`, slide[key], 's');
  let html = `<div class="mono tl-note">${tlClock(sel.t0)} → ${tlClock(sel.t1)}</div>`;
  if (sel.kind === 'paragraph' && slide) html += `<div class="tl-text">${esc(slide.narration)}</div>
    <button class="btn sm" id="tl-edit-text">Edit the words</button>` + timing('gap_override', 'Gap after paragraph', para.timing.gap.value);
  if (sel.kind === 'title' && slide) html += field('title', 'Title', slide.title)
    + timing('title_at', 'Arrival', para.timing.title_at.value) + timing('title_hold', 'Hold', para.timing.title_hold.value);
  if (sel.kind === 'chapter' && slide) html += field('chapter', 'Chapter', slide.chapter)
    + timing('chapter_hold', 'Hold', para.timing.chapter_hold.value) + '<button class="btn sm" data-remove>Remove chapter</button>';
  if (sel.kind === 'picture' && slide) {
    html += field('title', 'Caption', slide.title) + '<button class="btn sm" id="tl-picture">Change picture</button>';
    const candidate = slide.candidates.find((c) => c.id === slide.chosen_id);
    if (candidate?.focal?.length === 2) html += field('focal_x', 'Focal X', candidate.focal[0], '0–1') + field('focal_y', 'Focal Y', candidate.focal[1], '0–1');
  }
  if (sel.kind === 'cue' && slide) {
    const cues = (slide.cues || {})[p.style.format] || [], cue = cues[sel.cue];
    if (cue) {
      const vocabulary = (cutInfo(p.style.format)?.kinds || '').split(' · ').map((k) => k.split(' ')[0]).filter(Boolean);
      html += field('text', 'Text', cue.text ?? cue.caption ?? cue.headline ?? cue.title ?? '') + field('at', 'Arrival (blank = auto)', cue.at, 's')
        + field('kind', 'Kind', cue.kind, [...new Set([cue.kind, ...vocabulary])].map((k) => [k, k]))
        + '<button class="btn sm" data-remove>Delete cue</button><button class="btn sm" id="tl-cue-editor">Edit all cue fields</button>';
    }
  }
  const channel = p.channel_id ? TL.inspectorChannel : null;
  if ((sel.kind === 'slate' && seg) || sel.kind === 'music') {
    if (p.channel_id && !channel) html += '<p>Loading channel…</p>';
    else if (sel.kind === 'slate') {
      const role = seg.type, spec = (channel || p)[role];
      const templates = role === 'intro' ? TL.inspectorTemplates.filter((t) => channel || !t.needs_images) : TL.inspectorEndTemplates;
      html += field('template', `${role} template`, spec.template, templates.map((t) => [t.key, t.label]));
      if (channel) html += previewStage(channel, role === 'intro' ? 'intro preview' : 'end screen preview', `cache/${role}_preview.webm`, role === 'intro' ? channel.preview_at : channel.outro_preview_at);
      html += '<p class="tl-note">Replay the selected segment to preview the saved template.</p>';
    } else {
      html += field('music', 'Track', p.music, '', [['', 'None'], ['__auto__', 'Automatic'], ...TL.inspectorMusic.map((m) => [m.name, m.name])])
        + field('music_db', 'Level under voice', p.style.music_db, 'dB');
      if ((channel || p).outro?.enabled && p.use_outro !== false) html += field('music_fade', 'Fade over end card', (channel || p).outro.music_fade, 's');
    }
  }
  body.innerHTML = html;
  if ($('#tl-edit-text')) $('#tl-edit-text').onclick = () => tlEditText(slide.id);
  if ($('#tl-picture')) $('#tl-picture').onclick = () => tlEditPicture(slide.id);
  if ($('#tl-cue-editor')) $('#tl-cue-editor').onclick = () => tlModal(() => openCueEditor(slide.id));
  body.querySelectorAll('[data-field]').forEach((el) => {
    let timer, sent = el.value;
    const send = () => {
      clearTimeout(timer);
      if (sent === el.value) return;
      sent = el.value;
      tlInspectorSave({...sel}, el.dataset.field, el.value, el);
    };
    el.oninput = () => { clearTimeout(timer); timer = setTimeout(send, 300); };
    el.onchange = send;
    el.onkeydown = (e) => {
      if (e.key === 'Enter') { e.preventDefault(); send(); TL.host.focus(); }
    };
  });
  const remove = body.querySelector('[data-remove]');
  if (remove) remove.onclick = () => tlInspectorSave({...sel}, 'remove', '', remove);
}

// Serialize requests so a slow response cannot overwrite a later edit.
let tlInspectorQueue = Promise.resolve();
function tlInspectorSave(sel, key, raw, el) {
  const pid = TL.pid;
  tlInspectorQueue = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    try {
      if (el.type === 'number' && raw !== '' && !Number.isFinite(Number(raw))) throw new Error('Enter a finite number.');
      const value = el.type === 'number' ? (raw === '' ? null : Number(raw)) : raw;
      let patch = {[key]: value};
      if (sel.kind === 'cue') {
        const slide = state.project.slides.find((s) => s.id === sel.sid);
        const fmt = state.project.style.format;
        const cues = structuredClone(slide.cues[fmt]);
        if (key === 'remove') cues.splice(sel.cue, 1);
        else if (key === 'at' && value === null) delete cues[sel.cue].at;
        else {
          const cue = cues[sel.cue];
          const textKey = ['text', 'caption', 'headline', 'title'].find((k) => k in cue) || 'text';
          cue[key === 'text' ? textKey : key] = value;
        }
        patch = {cues: {[fmt]: cues}};
      } else if (key === 'remove') patch = {chapter: ''};
      else if (key.startsWith('focal_')) {
        const slide = state.project.slides.find((s) => s.id === sel.sid);
        const focal = [...slide.candidates.find((c) => c.id === slide.chosen_id).focal];
        focal[key === 'focal_x' ? 0 : 1] = value;
        patch = {focal};
      }
      if (sel.kind === 'slate' || key === 'music_fade') {
        const role = key === 'music_fade' ? 'outro' : sel.id;
        if (state.project.channel_id) TL.inspectorChannel = await saveChannel({[role]: patch}, {id: state.project.channel_id, quiet: true});
        else await saveProject({[role]: patch}, true);
      } else if (key === 'music_db') await saveStyle(patch, false);
      else if (key === 'music') await saveProject(patch, true);
      else {
        if (Object.keys(patch).some((k) => !TL_FIELDS[sel.kind]?.includes(k))) throw new Error('Unsupported inspector field.');
        if (!await saveSlide(sel.sid, patch)) throw new Error('Could not save this field.');
      }
      TL.mixFailed = false;
      await tlRefresh(true);
      if (TL.selection?.id === sel.id && TL.selection?.kind === sel.kind) {
        const next = tlItems(sel.kind).find((s) => s.id === sel.id);
        TL.selection = key === 'remove' && sel.kind === 'cue' ? null : next || null;
        // Keep the live field and its caret while typing.
        if (!$('#tl-inspector')?.contains(document.activeElement)) tlInspector();
      }
    } catch (e) {
      tlMsg(e.message);
      if (TL.selection?.id === sel.id && TL.selection?.kind === sel.kind) tlInspector();
    }
  });
}

async function tlInspectorLoad() {
  const pid = TL.pid;
  try {
    const [templates, ends, music, channel] = await Promise.all([
      api('/api/intro/templates'), api('/api/outro/templates'), api('/api/music'),
      state.project.channel_id ? api(`/api/channels/${state.project.channel_id}`) : null]);
    if (pid !== TL.pid) return;
    Object.assign(TL, {inspectorTemplates: templates, inspectorEndTemplates: ends, inspectorMusic: music, inspectorChannel: channel});
    tlInspector();
  } catch (e) { tlMsg(e.message); }
}

// Open a tab with one paragraph scrolled into view (or, on Record, selected).
function tlOpenTab(tab, sid) {
  const i = state.project.slides.findIndex((x) => x.id === sid);
  state.focusSlide = sid;
  if (tab === 'record' && i >= 0) { state.rec = state.rec || {}; state.rec.index = i; }
  go(`#/p/${state.project.id}/${tab}`);
}

// Run one of the app's own editor modals, and refresh the cut when it closes.
function tlModal(open) {
  tlPause();
  const before = new Set(document.querySelectorAll('.modal'));
  open();
  const fresh = [...document.querySelectorAll('.modal')].filter((m) => !before.has(m));
  const watcher = new MutationObserver(() => {
    if (fresh.length && fresh.some((m) => document.body.contains(m))) return;
    watcher.disconnect();
    tlRefreshProject();
  });
  watcher.observe(document.body, { childList: true });
}

async function tlRefreshProject() {
  try { state.project = await api(`/api/projects/${state.project.id}`); } catch { /* keep */ }
  TL.lastPara = '';
  TL.mixFailed = false;
  await tlRefresh(true);
  if (TL.selection) tlSelect(tlItems(TL.selection.kind).find((s) => s.id === TL.selection.id) || null);
}

function tlEditPicture(leadId) { tlModal(() => openMediaSearch(leadId)); }

function tlEditText(sid) {
  tlPause();
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box" style="width:min(640px,100%)">
      <div class="row" style="margin-bottom:12px">
        <strong>Edit the words</strong>
        <span class="mono tl-note">paragraph ${state.project.slides.indexOf(s) + 1}</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="tx-cancel">cancel</button>
        <button class="btn sm primary" id="tx-save">save</button>
      </div>
      <textarea id="tx-text" rows="8" style="width:100%">${esc(s.narration)}</textarea>
      <label class="field" style="margin-top:10px"><span>On-screen title (optional)</span>
        <input type="text" id="tx-title" value="${esc(s.title)}"></label>
      ${s.take ? `<div class="pill warn" style="margin-top:10px">
        This paragraph is recorded. Changing the words leaves the recording as it
        was — record it again to match.</div>` : ''}
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector('#tx-cancel').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  wrap.querySelector('#tx-save').onclick = async () => {
    const r = await saveSlide(sid, {
      narration: wrap.querySelector('#tx-text').value,
      title: wrap.querySelector('#tx-title').value,
    });
    close();
    if (r) await tlRefreshProject();
  };
  wrap.querySelector('#tx-text').focus();
}

// One paused playhead, one proposal, explicit review before applying.
function tlAsk() {
  const pid = TL.pid;
  const t = TL.playing ? tlNow() : TL.cur;
  const seg = tlSegAt(t);
  const para = [...(seg?.paragraphs || [])].reverse().find((p) => p.start <= t);
  tlPause();
  tlModal(() => {
    const wrap = document.createElement('div');
    wrap.className = 'modal';
    wrap.innerHTML = `<div class="modal-box wide">
      <h3>Ask at <span class="num">${tlClock(t)}</span></h3>
      <label>What should change?<textarea data-intent rows="3" placeholder="Make this title shorter"></textarea></label>
      <div class="tl-actions">
        <button class="btn sm" data-copy>Copy for Claude Code</button>
        <button class="btn sm primary" data-ask>Ask here</button>
        <button class="btn sm" data-rule>Make this a rule</button>
        <button class="btn sm" data-close>Discard</button>
      </div>
      <p data-status role="status"></p><div data-answer></div>
    </div>`;
    document.body.appendChild(wrap);
    const intent = wrap.querySelector('[data-intent]');
    const status = wrap.querySelector('[data-status]');
    const answer = wrap.querySelector('[data-answer]');
    let proposal = null;
    wrap.querySelector('[data-close]').onclick = () => wrap.remove();
    async function request(mode) {
      proposal = null;
      answer.innerHTML = '';
      status.textContent = mode === 'copy' ? 'Preparing prompt…' : 'Asking…';
      const buttons = wrap.querySelectorAll('[data-copy], [data-ask]');
      buttons.forEach((b) => { b.disabled = true; });
      try {
        const result = await api(`/api/projects/${pid}/agent/ask`, {
          method: 'POST', body: JSON.stringify({ t, selection: para ? { slide_id: para.id } : {},
            intent: intent.value, mode }) });
        if (!wrap.isConnected) return;
        status.textContent = '';
        if (mode === 'copy') {
          // Also offer a selectable textarea when WebKit denies clipboard access.
          const text = document.createElement('textarea');
          text.value = result.prompt; text.rows = 8;
          answer.appendChild(text);
          const copy = document.createElement('button');
          copy.className = 'btn sm'; copy.textContent = 'Copy prompt';
          const write = () => {
            text.focus(); text.select();
            const fallback = () => {
              const ok = document.execCommand('copy');
              status.textContent = ok ? 'Copied to clipboard' : 'Select and copy the prompt above.';
            };
            if (navigator.clipboard?.writeText) {
              navigator.clipboard.writeText(result.prompt).then(
                () => { status.textContent = 'Copied to clipboard'; }, fallback);
            } else fallback();
          };
          copy.onclick = write; answer.appendChild(copy); write();
          return;
        }
        proposal = result;
        answer.innerHTML = `<pre style="white-space:pre-wrap">${esc(result.diff.map((d) =>
          `${d.id} · ${d.field}: ${JSON.stringify(d.old)} → ${JSON.stringify(d.new)}`).join('\n') || 'No changes proposed.')}</pre>
          <button class="btn sm primary" data-apply ${result.diff.length ? '' : 'disabled'}>Apply</button>`;
        answer.querySelector('[data-apply]').onclick = async (event) => {
          event.target.disabled = true;
          try {
            await api(`/api/projects/${pid}/agent/apply`, {
              method: 'POST', body: JSON.stringify(proposal) });
            wrap.remove(); // tlModal refreshes the project and timeline.
          } catch (e) { status.textContent = e.message; event.target.disabled = false; }
        };
      } catch (e) { status.textContent = e.message; }
      finally { buttons.forEach((b) => { b.disabled = false; }); }
    }
    wrap.querySelector('[data-copy]').onclick = () => request('copy');
    wrap.querySelector('[data-rule]').onclick = () => tlMakeRule(wrap.querySelector('[data-intent]').value);
    wrap.querySelector('[data-ask]').onclick = () => request('ask');
    intent.focus();
  });
}


async function tlMakeRule(problem) {
  const text = prompt('House rule (up to 200 characters)', problem || '');
  if (!text) return;
  const scope = prompt('Scope: project or channel', 'project');
  if (!scope) return;
  try {
    await api(`/api/projects/${TL.pid}/frame/rules`, {
      method: 'POST', body: JSON.stringify({text, scope}) });
    toast('Rule saved');
  } catch (e) { toast(e.message, true); }
}


async function tlRejectLook() {
  try {
    const vocabulary = await api('/api/looks');
    tlModal(() => {
      const wrap = document.createElement('div');
      wrap.className = 'modal';
      wrap.innerHTML = `<div class="modal-box"><h3>Reject this look</h3>
        <label>Look<select data-look></select></label>
        <label>Scope<select data-scope><option>project</option><option>channel</option></select></label>
        <button class="btn sm" data-save>Reject</button>
        <button class="btn sm" data-close>Cancel</button></div>`;
      const select = wrap.querySelector('[data-look]');
      for (const [kind, names] of Object.entries(vocabulary)) {
        for (const name of names) select.add(new Option(`${kind}: ${name}`, `${kind}:${name}`));
      }
      wrap.querySelector('[data-close]').onclick = () => wrap.remove();
      wrap.querySelector('[data-save]').onclick = async () => {
        try {
          await api(`/api/projects/${TL.pid}/frame/rejected`, {method: 'POST',
            body: JSON.stringify({look: select.value, scope: wrap.querySelector('[data-scope]').value})});
          wrap.remove();
          await tlRefreshProject();
        } catch (e) { toast(e.message, true); }
      };
      document.body.appendChild(wrap);
    });
  } catch (e) { toast(e.message, true); }
}

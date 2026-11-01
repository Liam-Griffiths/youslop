
// ---------------------------------------------------------------- inspector
function tlInspect(para) {
  const box = $('#tl-inspector');
  if (!box) return;
  const p = state.project;
  const s = p.slides.find((x) => x.id === para.id);
  if (!s) { box.innerHTML = ''; return; }
  const seg = tlSegs()[para.seg];
  const fmt = p.style.format;
  const cut = isCut(fmt);
  box.innerHTML = `
    <div class="mono tl-note">paragraph ${String(para.index + 1).padStart(2, '0')} ·
      ${tlName(seg)} ·
      ${tlClock(para.start)} → ${tlClock(para.start + para.duration)}
      ${para.recorded ? '' : '· <span style="color:var(--cool)">estimated, not recorded</span>'}</div>
    ${s.chapter ? `<div class="pill" style="margin:6px 0 0">⚑ chapter: ${esc(s.chapter)}</div>` : ''}
    <div class="tl-text">${esc(s.narration)}</div>
    ${seg.problems.length ? `<div class="tl-warn">${seg.problems.map((m) => '⚠ ' + esc(m)).join('<br>')}</div>` : ''}
    <div class="tl-actions">
      <button class="btn sm" onclick="tlAsk()">Ask</button>
      <button class="btn sm" onclick="tlEditText('${s.id}')">edit the words</button>
      <button class="btn sm" onclick="tlEditPicture('${seg.lead}')">change the picture</button>
      ${fmt === 'board' ? `<button class="btn sm" onclick="tlModal(() => openBoardEditor('${s.id}'))">edit the board</button>` : ''}
      ${cut ? `<button class="btn sm" onclick="tlModal(() => openCueEditor('${s.id}'))">edit the cues</button>` : ''}
      <button class="btn sm" onclick="tlOpenTab('record','${s.id}')">${para.recorded ? 're-record / re-read' : 'record this'}</button>
    </div>
    <div class="tl-links mono">open in
      <a onclick="tlOpenTab('script','${s.id}')">script</a> ·
      <a onclick="tlOpenTab('media','${s.id}')">media</a> ·
      <a onclick="tlOpenTab('record','${s.id}')">record</a></div>`;
}

// The slate and end card belong to the channel (or, standalone, to the panels
// further down this page), so that is where editing them goes.
function tlInspectSlate(seg) {
  const box = $('#tl-inspector');
  if (!box) return;
  const p = state.project;
  const intro = seg.type === 'intro';
  const where = p.channel_id
    ? `<button class="btn sm" onclick="go('#/c/${p.channel_id}')">edit it on the channel page</button>`
    : `<button class="btn sm" onclick="document.getElementById('opening-panel')?.scrollIntoView({block:'center'})">edit it below</button>`;
  box.innerHTML = `
    <div class="mono tl-note">${intro ? 'opening slate' : 'end card'} ·
      ${tlClock(seg.start)} → ${tlClock(seg.start + seg.duration)}
      ${seg.estimated ? '· <span style="color:var(--cool)">length estimated until drawn</span>' : ''}</div>
    <div class="tl-text">${intro
      ? 'The video opens on this slate, with its own sting if it has one. The music bed holds off until it is over.'
      : 'The video closes on this card. The music bed fades out over it.'}</div>
    <div class="tl-actions"><button class="btn sm" onclick="tlAsk()">Ask</button>${where}</div>`;
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

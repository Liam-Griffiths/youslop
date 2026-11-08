
// ------------------------------------------------------------------ drawing
function tlStepFor(zoom) {
  for (const s of [1, 2, 5, 10, 15, 30, 60, 120, 300, 600]) if (s * zoom >= 64) return s;
  return 900;
}

function tlThumb(seg) {
  if (seg.kind === 'camera') return `/api/projects/${TL.pid}/slides/${seg.lead}/camera.jpg?v=${seg.camera_stamp}`;
  const s = state.project.slides.find((x) => x.id === seg.lead);
  const c = s && s.candidates.find((x) => x.id === s.chosen_id);
  return c ? thumbUrl(c) : '';
}

function tlPaintNote() {
  const note = $('#tl-note');
  const d = TL.data;
  if (!note || !d) return;
  const pics = d.segments.filter((s) => s.type === 'picture').length;
  const mix = d.mix;
  const sound = !mix.audible ? 'silent: nothing recorded yet and no bed'
    : TL.mixBusy ? 'mixing the sound…'
    : TL.mixFailed ? 'sound failed to mix'
    : (mix.music ? `with the “${mix.music.replace(/\.[^.]+$/, '')}” bed` : 'narration only, no music bed')
      + (mix.sting ? (mix.stings && mix.stings.length > 1 ? ' and both stings' : ' and the ' + ((mix.stings || [''])[0] === 'outro' ? 'end card' : 'slate') + ' sting') : '');
  note.textContent = `${fmtTime(d.total)} · ${pics} pictures · ${d.width}×${d.height} at ${d.fps}fps · ${sound}`
    + (d.estimated ? ' · some lengths estimated' : '')
    + (d.camera_clip ? ' · the camera clip is not shown here' : '');
}

function tlDraw() {
  const track = $('#tl-track');
  if (!track || !TL.data) return;
  const d = TL.data, z = TL.zoom;
  tlPaintNote();
  track.style.width = `${Math.ceil(d.total * z) + 24}px`;
  const step = tlStepFor(z);
  let ticks = '';
  for (let t = 0; t <= d.total; t += step) {
    ticks += `<i style="left:${t * z}px"><b>${fmtTime(t)}</b></i>`;
  }
  const pics = d.segments.map((s) => {
    const img = s.type === 'picture' ? tlThumb(s) : '';
    const bad = s.problems.some((x) => x.startsWith('no picture'));
    return `<button type="button" aria-label="${esc(tlName(s))}" class="tl-pic ${s.type !== 'picture' ? 'slate' : ''} ${s.ready ? 'ready' : s.have ? 'stale' : ''}
        ${bad ? 'bad' : ''}" data-seg="${s.index}"
        style="left:${s.start * z}px;width:${Math.max(2, s.duration * z - 2)}px;
        ${img ? `background-image:url('${esc(img)}')` : ''}">
        <span class="tl-tag">${s.kind === 'camera' ? '📹 ' : ''}${tlLabel(s)}${s.problems.length ? ' ⚠' : ''}${s.estimated ? ' ~' : ''}</span>
        <i class="tl-dot" title="${s.ready ? 'proxy drawn' : s.have ? 'out of date' : 'not drawn yet'}"></i>
      </button>`;
  }).join('');
  const paras = tlParas().map((q) => `
      <button type="button" class="tl-para ${q.recorded ? '' : 'est'} ${q.chapter ? 'chap' : ''}" data-para="${q.id}"
        style="left:${q.start * z}px;width:${Math.max(2, q.duration * z - 2)}px"
        title="${esc(q.text.slice(0, 140))}">
        ${q.chapter ? '<span class="tl-flag">⚑</span>' : ''}<span>${esc(q.text)}</span>
      </button>`).join('');
  track.innerHTML = `
    <div class="tl-ruler">${ticks}</div>
    <div class="tl-lane"><em>pictures</em>${pics}</div>
    <div class="tl-lane para"><em>voice</em>${paras}${tlGapItems()}</div>
    ${tlCameraRows()}
    ${tlLayerRows()}
    <div class="tl-head-line" id="tl-line"><b></b></div>`;
  tlWireLayers();
  tlWireTiming();
  tlWireSponsorDrag();
  tlWireCamera();
  tlPaintProblems();
  tlPaintReview();
  TL.lastPara = '';
  tlPaintHead();
}

function tlPaintReview() {
  const box = $('#tl-review');
  if (!box || !TL.data) return;
  box.replaceChildren();
  const title = document.createElement('h3');
  title.textContent = 'Review';
  box.append(title);
  const reject = document.createElement('button');
  reject.className = 'btn sm';
  reject.textContent = 'Reject this look';
  reject.onclick = tlRejectLook;
  box.append(reject);
  for (const [mode, label] of [['targeted', 'Review'], ['full', 'Review every frame']]) {
    const button = document.createElement('button');
    button.className = 'btn sm';
    button.textContent = label;
    button.onclick = async () => {
      const result = await api(`/api/projects/${TL.pid}/review`, {
        method: 'POST', body: JSON.stringify({ mode }) });
      watchJob(result.job, 'vision review');
    };
    box.append(button);
  }
  const review = TL.data.review || {};
  const rows = [];
  if (review.weakest) rows.push({ t: review.weakest.t, see: 'Weakest shot',
    problem: review.weakest.why,
    path: (review.frames || []).find((f) => f.t === review.weakest.t)?.path });
  rows.push(...(review.notes || []).filter((n) => n.source !== 'check' && (n.state || 'open') === 'open'));
  rows.push(...(review.warnings_kept || []));
  for (const note of rows) {
    if (note === review.warnings_kept?.[0]) {
      const kept = document.createElement('h4');
      kept.textContent = 'Warnings kept';
      box.append(kept);
    }
    const row = document.createElement('div');
    row.className = 'tl-check-row';
    if (note.path) {
      const thumb = document.createElement('img');
      thumb.src = `/api/projects/${encodeURIComponent(TL.pid)}/file/${note.path}`;
      thumb.width = 120;
      thumb.alt = note.see;
      row.append(thumb);
    }
    const jump = document.createElement('button');
    jump.className = 'mono tl-chip';
    jump.textContent = `${tlClock(note.t)} · jump`;
    jump.onclick = () => tlSeek(note.t, { ensure: true });
    const text = document.createElement('span');
    text.textContent = `${note.severity || 'Pinned'} · ${note.see} · ${note.problem}`
      + (note.fix?.hint ? ` · ${note.fix.hint}` : '');
    row.append(jump, text);
    const rule = document.createElement('button');
    rule.className = 'btn sm';
    rule.textContent = 'Make this a rule';
    rule.onclick = () => tlMakeRule(note.problem);
    row.append(rule);
    if (note.id) tlFixButtons(row, note);
    box.append(row);
  }
}

function tlFixButtons(row, note, finding = false, context = null) {
  const kind = note.fix?.kind;
  for (const [action, label] of [['fix', 'Fix'], ['dismiss', 'Dismiss'], ['keep', 'Keep']]) {
    const button = document.createElement('button');
    button.className = 'btn sm';
    button.textContent = label;
    button.disabled = action === 'fix' && !['text', 'words', 'cue', 'cues', 'picture', 'title', 'look', 'style'].includes(kind);
    button.onclick = async () => {
      button.disabled = true;
      try {
        const send = (action) => api(`/api/projects/${context?.pid || TL.pid}/review/${note.id}`, {
          method: 'POST', body: JSON.stringify({ action, ...(finding ? { finding: true } : {}) }) });
        const result = await send(action);
        if (action !== 'fix') return await (context ? context.refresh() : tlRefresh());
        if (result.unsupported) return toast('This fix is not available yet.');
        const proposal = result.proposal;
        if (proposal.search !== undefined) {
          if (context) openMediaSearch(proposal.slide_id, proposal.search,
            cid => saveSlide(proposal.slide_id, {chosen_id: cid}), context.refreshProject);
          else tlModal(() => openMediaSearch(proposal.slide_id, proposal.search));
          return;
        }
        row.querySelector('.tl-fix-proposal')?.remove();
        const panel = document.createElement('div');
        panel.className = 'tl-fix-proposal';
        const diff = document.createElement('pre');
        diff.style.whiteSpace = 'pre-wrap';
        diff.textContent = proposal.field === 'cues' ? 'Cues re-planned:\n' + JSON.stringify(proposal.new, null, 2)
          : `Before: ${proposal.old ?? ''}\nAfter: ${proposal.new}`;
        const apply = document.createElement('button');
        apply.className = 'btn sm';
        apply.textContent = 'Apply';
        apply.onclick = async () => {
          apply.disabled = true;
          try { await send('apply'); await (context ? context.refreshProject() : tlRefreshProject()); }
          catch (e) { toast(e.message, true); apply.disabled = false; }
        };
        panel.append(diff, apply);
        row.append(panel);
      } catch (e) { toast(e.message, true); }
      finally { button.disabled = false; }
    };
    row.append(button);
  }
}

function tlPaintProblems() {
  const box = $('#tl-problems');
  if (!box || !TL.data) return;
  const findings = TL.data.check?.findings || TL.data.segments.flatMap((s) => s.findings || []);
  const summary = $('#tl-check-summary');
  if (summary) summary.textContent = 'Check · ' + ['P0', 'P1', 'P2'].map((level) =>
    `${level} ${findings.filter((f) => f.level === level && (f.state || 'open') === 'open').length}`).join(' · ');
  box.replaceChildren();
  if (!findings.length) {
    box.textContent = 'No check findings.';
    return;
  }
  for (const level of ['P0', 'P1', 'P2']) {
    const rows = findings.filter((f) => f.level === level && (f.state || 'open') === 'open');
    if (!rows.length) continue;
    const group = document.createElement('section');
    group.className = 'tl-check-group';
    const title = document.createElement('strong');
    title.textContent = `${level} (${rows.length})`;
    if (level === 'P0') title.className = 'tl-check-p0';
    group.append(title);
    for (const f of rows) {
      const row = document.createElement('div');
      row.className = 'tl-check-row';
      const chip = document.createElement('span');
      chip.className = 'tl-chip';
      chip.textContent = level;
      const jump = document.createElement('button');
      jump.className = 'mono tl-chip';
      jump.textContent = `${tlClock(f.t)} · jump`;
      jump.onclick = () => tlSeek(f.t, { ensure: true });
      const msg = document.createElement('span');
      msg.textContent = f.msg;
      row.append(chip, jump, msg);
      tlFixButtons(row, f, true);
      group.append(row);
    }
    box.append(group);
  }
}

// The cheap repaint: playhead, clock, play button, which paragraph is selected.
function tlPaintHead() {
  const d = TL.data;
  if (!d || !$('#tl-line')) return;
  $('#tl-line').style.left = `${104 + TL.cur * TL.zoom}px`;
  $('#tl-clock').textContent =
    `${tlClock(TL.cur)} / ${tlClock(d.total)}  ·  frame ${Math.round(TL.cur * d.fps)}`;
  $('#tl-play').textContent = TL.playing ? '❚❚' : '▶';
  tlSelectionPaint();
  // Keep the playhead on screen while it plays or is stepped.
  const sc = $('#tl-scroll'), x = 104 + TL.cur * TL.zoom;
  if (sc && !TL.scrubbing && (x < sc.scrollLeft + 20 || x > sc.scrollLeft + sc.clientWidth - 40)) {
    sc.scrollLeft = Math.max(0, x - sc.clientWidth * 0.3);
  }
}

function tlPaintStatus() {
  document.querySelectorAll('#tl-track .tl-pic').forEach((el) => {
    const s = tlSegs()[+el.dataset.seg];
    if (!s) return;
    el.classList.toggle('ready', s.ready);
    el.classList.toggle('stale', !s.ready && s.have);
    el.classList.toggle('drawing', TL.drawing === s.ref);
  });
}

function tlDrawAll() {
  const segs = tlSegs().filter((s) => !s.ready);
  if (!segs.length) { toast('every picture is already drawn'); return; }
  if (!confirm(`Draw ${segs.length} entr${segs.length > 1 ? 'ies' : 'y'} (pictures, slate and end card) at `
    + `${TL.data.width}×${TL.data.height}? It runs one after another in the background and uses a good `
    + 'share of this computer while it does.')) return;
  tlEnsure(segs.map((s) => s.ref));
}

// Preview only the selected span's segment (or the one under the playhead).
function tlPreviewBit() {
  if (!TL.data || !TL.host?.isConnected) return;
  tlPause();
  tlSeek(TL.selection?.t0 ?? TL.cur, {ensure: true});
}

function tlShortcuts() {
  if (document.querySelector('.modal')) return;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `<section class="modal-box tl-shortcut-sheet" role="dialog" aria-modal="true" aria-labelledby="tl-shortcut-title" tabindex="-1">
    <div class="row"><h2 id="tl-shortcut-title">Edit shortcuts</h2><div class="spacer"></div>
      <button type="button" class="btn sm ghost" id="tl-shortcut-close">Close</button></div>
    <dl>
      <dt>Space</dt><dd>Play / pause</dd>
      <dt>← / →</dt><dd>Step one frame</dd>
      <dt>Shift + ← / →</dt><dd>Previous / next paragraph</dd>
      <dt>Home / End</dt><dd>Start / end of timeline</dd>
      <dt>[ / ]</dt><dd>Previous / next item of the selected kind</dd>
      <dt>L</dt><dd>Loop picture</dd>
      <dt>S</dt><dd>Split paragraph at playhead</dd>
      <dt>C / Shift + C</dt><dd>Add / remove chapter</dd>
      <dt>Escape</dt><dd>Clear selection / cancel drag / close this sheet</dd>
      <dt>Alt + drag</dt><dd>Retiming without snapping</dd>
      <dt>Camera: I / O</dt><dd>Mark source range; Delete cuts it</dd>
      <dt>Overlay: 1 / 2 / 3</dt><dd>Cutaway / picture in picture / split</dd>
      <dt>Graphics: G</dt><dd>Add at playhead; arrows move, Shift + arrows resize, Delete removes</dd>
      <dt>Overlay: P / Delete</dt><dd>Change corner / remove overlay</dd>
      <dt>?</dt><dd>Open this sheet</dd>
    </dl></section>`;
  const previous = document.activeElement;
  const close = () => {
    wrap.remove(); document.removeEventListener('keydown', key, true);
    if (previous?.isConnected) previous.focus();
  };
  const key = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    if (e.key === 'Tab') { e.preventDefault(); wrap.querySelector('button').focus(); }
  };
  wrap.querySelector('button').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  document.addEventListener('keydown', key, true);
  document.body.append(wrap);
  wrap.querySelector('button').focus();
}

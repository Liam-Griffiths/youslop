
// ------------------------------------------------------------------ drawing
function tlStepFor(zoom) {
  for (const s of [1, 2, 5, 10, 15, 30, 60, 120, 300, 600]) if (s * zoom >= 64) return s;
  return 900;
}

function tlThumb(seg) {
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
        <span class="tl-tag">${tlLabel(s)}${s.problems.length ? ' ⚠' : ''}${s.estimated ? ' ~' : ''}</span>
        <i class="tl-dot" title="${s.ready ? 'proxy drawn' : s.have ? 'out of date' : 'not drawn yet'}"></i>
      </button>`;
  }).join('');
  const paras = tlParas().map((q) => `
      <button type="button" class="tl-para ${q.recorded ? '' : 'est'} ${q.chapter ? 'chap' : ''}" data-para="${q.id}"
        style="left:${q.start * z}px;width:${Math.max(2, q.duration * z - 2)}px"
        title="${esc(q.text.slice(0, 140))}">
        ${q.chapter ? '<span class="tl-flag">⚑</span>' : ''}<span>${esc(q.text)}</span>
      </button>`).join('');
  const titles = tlParas().filter((q) => q.title).map((q) => `<button class="tl-title-marker"
    data-title="${q.id}" style="left:${q.timing.title_at.start * z}px;width:${Math.max(8, q.timing.title_hold.value * z)}px"
    title="${esc(q.title)}">${esc(q.title)}</button>`).join('');
  track.innerHTML = `
    <div class="tl-ruler">${ticks}</div>
    <div class="tl-lane"><em>pictures</em>${pics}</div>
    <div class="tl-lane para"><em>voice</em>${paras}</div>
    <div class="tl-lane"><em>titles</em>${titles}</div>
    <div class="tl-head-line" id="tl-line"><b></b></div>`;
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

function tlFixButtons(row, note, finding = false) {
  const kind = note.fix?.kind;
  for (const [action, label] of [['fix', 'Fix'], ['dismiss', 'Dismiss'], ['keep', 'Keep']]) {
    const button = document.createElement('button');
    button.className = 'btn sm';
    button.textContent = label;
    button.disabled = action === 'fix' && !['text', 'words', 'cue', 'cues', 'picture', 'title', 'look', 'style'].includes(kind);
    button.onclick = async () => {
      button.disabled = true;
      try {
        const send = (action) => api(`/api/projects/${TL.pid}/review/${note.id}`, {
          method: 'POST', body: JSON.stringify({ action, ...(finding ? { finding: true } : {}) }) });
        const result = await send(action);
        if (action !== 'fix') return await tlRefresh();
        if (result.unsupported) return toast('This fix is not available yet.');
        const proposal = result.proposal;
        if (proposal.search !== undefined) {
          tlModal(() => openMediaSearch(proposal.slide_id, proposal.search));
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
          try { await send('apply'); await tlRefreshProject(); }
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
  $('#tl-line').style.left = `${TL.cur * TL.zoom}px`;
  $('#tl-clock').textContent =
    `${tlClock(TL.cur)} / ${tlClock(d.total)}  ·  frame ${Math.round(TL.cur * d.fps)}`;
  $('#tl-play').textContent = TL.playing ? '❚❚' : '▶';
  tlSelectionPaint();
  // Keep the playhead on screen while it plays or is stepped.
  const sc = $('#tl-scroll'), x = TL.cur * TL.zoom;
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

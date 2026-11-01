// All times here are picture seconds; only the PATCH is paragraph-relative.
function tlSnap(t, words, fps, pxTol, zoom, alt) {
  if (alt) return {t, guide: null};
  const frame = Math.round(t * fps) / fps;
  let best = {t, d: pxTol, guide: null};
  // Prefer a nearby word edge over the dense frame grid. Otherwise words
  // could only win within half a frame, even with a six-pixel tolerance.
  for (const w of words) for (const edge of [w.start, w.end]) {
    const d = Math.abs(edge - t) * zoom;
    if (d <= best.d) best = {t: edge, d, guide: edge};
  }
  if (best.guide !== null) return best;
  return Math.abs(frame - t) * zoom <= pxTol ? {t: frame, guide: frame} : best;
}

function tlTimingKind(s) {
  if (s.kind === 'title' && s.id === s.sid) return 'title';
  if (s.kind === 'cue') return 'cue';
  if (s.kind === 'chapter') return 'chapter';
  return '';
}

function tlGapItems() {
  return tlParas().map((q) => `<button type="button" class="tl-gap ${q.timing.gap.src === 'user' ? 'user' : ''}"
    data-gap="${esc(q.id)}" style="left:${(q.start + q.duration) * TL.zoom}px"
    aria-label="Gap after paragraph ${q.index + 1}: ${q.timing.gap.value.toFixed(2)} seconds"
    title="Drag gap · Alt disables snapping">↔</button>`).join('');
}

// Reuse the inspector queue: exactly one timing PATCH on drop or reset.
function tlSaveTiming(sel, patch) {
  const pid = TL.pid;
  tlInspectorQueue = tlInspectorQueue.then(async () => {
    if (TL.pid !== pid || state.project?.id !== pid) return;
    try {
      if (!await saveSlide(sel.sid, typeof patch === 'function' ? patch() : patch)) throw new Error('Could not save timing.');
      TL.mixFailed = false;
      await tlRefresh(true);
      if (TL.selection?.id === sel.id && TL.selection?.kind === sel.kind)
        tlSelect(tlItems(sel.kind).find((s) => s.id === sel.id) || null);
    } catch (e) { tlMsg(e.message); tlDraw(); }
  });
}

function tlCuePatch(sel, at) {
  const q = tlParas().find((q) => q.id === sel.sid);
  const fmt = state.project.style.format;
  const slide = state.project.slides.find((s) => s.id === sel.sid);
  const cues = structuredClone(slide.cues?.[fmt]?.length ? slide.cues[fmt] : q.effective_cues);
  if (at === null) delete cues[sel.cue].at;
  else cues[sel.cue].at = at;
  return {cues: {[fmt]: cues}};
}

function tlResetTiming(sel) {
  const patch = sel.kind === 'cue' ? () => tlCuePatch(sel, null)
    : sel.kind === 'title' ? {title_at: null, title_hold: null}
    : sel.kind === 'chapter' ? {chapter_hold: null} : {gap_override: null};
  tlSaveTiming(sel, patch);
}

function tlWireTiming() {
  const track = $('#tl-track');
  track.querySelectorAll('[data-layer], [data-gap]').forEach((el) => {
    const gap = el.dataset.gap;
    const sel = gap ? tlItems('paragraph').find((s) => s.sid === gap)
      : TL.data.layers[el.dataset.layer][+el.dataset.item];
    const kind = gap ? 'gap' : tlTimingKind(sel);
    if (!kind) return;
    el.classList.add('editable');
    if (kind === 'title' || kind === 'chapter') {
      const handle = document.createElement('span');
      handle.className = `tl-resize ${kind === 'chapter' ? 'left' : ''}`;
      handle.title = 'Resize hold';
      el.append(handle);
    }
    const click = el.onclick;
    let suppressClick = false;
    el.onclick = (e) => {
      e.stopPropagation();
      if (suppressClick) { suppressClick = false; return; }
      if (gap) tlSelect(sel); else click?.(e);
    };
    el.onpointerdown = (e) => {
      e.stopPropagation();
      if (e.button !== 0 || TL.drag) return;
      suppressClick = false;
      const mode = kind === 'gap' ? 'gap' : e.target.closest('.tl-resize') ? 'resize' : 'move';
      if (kind === 'chapter' && mode !== 'resize') return;
      const q = tlParas().find((q) => q.id === sel.sid);
      if (!q) return;
      tlPause(); tlSelect(sel);
      el.setPointerCapture(e.pointerId);
      const xTime = (event) => (event.clientX - track.getBoundingClientRect().left - 104) / TL.zoom;
      const original = {sel, mode, x0: xTime(e), t0: sel.t0, t1: sel.t1};
      TL.drag = original;
      const guide = document.createElement('div');
      guide.className = 'tl-snap-guide'; guide.hidden = true; track.append(guide);
      const holdKey = kind === 'chapter' ? 'chapter_hold' : 'title_hold';
      const hold = q.timing[holdKey].value;
      const oldGap = q.timing.gap.value;
      const boundary = q.start + q.duration;
      const last = tlParas().at(-1)?.id === q.id;
      const minHold = kind === 'title' && last ? Math.max(.5, TL.data.last_line_min_s) : .5;
      const prev = tlParas()[tlParas().findIndex((p) => p.id === q.id) - 1];
      const maxHold = kind === 'chapter' ? (prev?.timing.gap.value || 0)
        : Math.max(minHold, q.spoken - Math.max(0, sel.t0 - q.start));
      // Save geometry once; moving a gap stretches crossing spans and shifts
      // every subsequent picture, paragraph, layer item and gap handle.
      const geometry = [...track.querySelectorAll('[data-seg], [data-para], [data-layer], [data-gap]')]
        .map((node) => ({node, left: parseFloat(node.style.left), width: parseFloat(node.style.width) || 0}));
      const trackWidth = track.style.width;
      let value, moved = false;
      const move = (event) => {
        const delta = xTime(event) - original.x0;
        if (!moved && Math.abs(delta * TL.zoom) < 3) return;
        moved = true; suppressClick = true;
        const base = kind === 'gap' ? boundary : mode === 'resize'
          ? (kind === 'chapter' ? sel.t0 : sel.t0 + hold) : sel.t0;
        const snap = tlSnap(base + delta, q.word_times || [], tlFps(), 6, TL.zoom, event.altKey);
        const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
        let target;
        if (kind === 'gap') {
          value = clamp(oldGap + snap.t - boundary, 0, 10);
          const shift = value - oldGap;
          const gapStart = boundary - oldGap;
          const map = (t) => t >= boundary ? t + shift : t > gapStart && oldGap > 0
            ? gapStart + (t - gapStart) * value / oldGap : t;
          for (const g of geometry) {
            const a = map(g.left / TL.zoom), b = map((g.left + g.width + 2) / TL.zoom);
            g.node.style.left = `${a * TL.zoom}px`;
            if (g.width) g.node.style.width = `${Math.max(2, (b - a) * TL.zoom - 2)}px`;
          }
          track.style.width = `${Math.ceil((TL.data.total + shift) * TL.zoom) + 24}px`;
          target = boundary + shift;
        } else if (mode === 'resize') {
          value = clamp(hold + (kind === 'chapter' ? -1 : 1) * (snap.t - base), Math.min(minHold, maxHold), maxHold);
          if (kind === 'chapter') {
            target = sel.t0 + hold - value;
            el.style.left = `${target * TL.zoom}px`;
            el.style.width = `${Math.max(2, (sel.t1 - target) * TL.zoom - 2)}px`;
          } else {
            target = sel.t0 + value;
            el.style.width = `${Math.max(2, (value + TL.data.title_exit) * TL.zoom - 2)}px`;
          }
        } else {
          value = clamp(snap.t - q.start, 0, q.spoken);
          target = q.start + value;
          el.style.left = `${target * TL.zoom}px`;
        }
        guide.hidden = snap.guide === null || Math.abs(target - snap.t) > .001;
        guide.style.left = `${104 + target * TL.zoom}px`;
      };
      const finish = (cancel) => {
        if (TL.drag !== original) return;
        TL.drag = null;
        document.removeEventListener('keydown', key, true);
        el.onpointermove = el.onpointerup = el.onpointercancel = el.onlostpointercapture = null;
        if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
        guide.remove();
        if (cancel || !moved) {
          for (const g of geometry) { g.node.style.left = `${g.left}px`; if (g.width) g.node.style.width = `${g.width}px`; }
          track.style.width = trackWidth;
          return;
        }
        const patch = kind === 'cue' ? () => tlCuePatch(sel, value) : {
          [kind === 'gap' ? 'gap_override' : mode === 'resize' ? holdKey : 'title_at']: value};
        tlSaveTiming(sel, patch);
      };
      const key = (event) => {
        if (event.key !== 'Escape') return;
        event.preventDefault(); event.stopImmediatePropagation(); finish(true);
      };
      el.onpointermove = move;
      el.onpointerup = (event) => { move(event); finish(false); };
      el.onpointercancel = el.onlostpointercapture = () => finish(true);
      document.addEventListener('keydown', key, true);
    };
  });
}

try {
  document.documentElement.dataset.display = localStorage.getItem('corkbored-display') === 'grotesk' ? 'grotesk' : 'archivo';
} catch (e) { document.documentElement.dataset.display = 'archivo'; }

window.addEventListener('hashchange', route);

document.addEventListener('keydown', (e) => {
  if (state.tab !== 'record' || !state.project) return;
  if (state.mic.el) { if (e.key === 'Escape') closeMicPanel(); return; }
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  const keys = {
    ' ': () => toggleRec(),
    ArrowRight: () => jumpTake(1),
    ArrowLeft: () => jumpTake(-1),
    p: () => playTake(),
    r: () => dropTake(),
  };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
});

document.addEventListener('keydown', (e) => {
  if (!TL.host || !document.body.contains(TL.host) || !TL.data) return;
  if (e.key === 'Escape' && !document.querySelector('.modal')) { tlSelect(null); TL.host.focus(); return; }
  const tag = (e.target.tagName || '').toLowerCase();
  if (['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable) return;
  if (document.querySelector('.modal') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;
  if (k === '[' || k === ']') tlSelectNext(k === '[' ? -1 : 1);
  else if (k === 's' || k === 'S') tlSplitHere();
  else if (k === 'c' || k === 'C') tlChapterHere(e.shiftKey);
  else if (k === ' ') tlToggle();
  else if (k === 'ArrowLeft') e.shiftKey ? tlPara(-1) : tlStep(-1);
  else if (k === 'ArrowRight') e.shiftKey ? tlPara(1) : tlStep(1);
  else if (k === 'Home') { tlPause(); tlSeek(0); }
  else if (k === 'End') { tlPause(); tlSeek(TL.data.total); }
  else if (k === 'l' || k === 'L') { TL.loop = !TL.loop; const c = $('#tl-loop'); if (c) c.checked = TL.loop; }
  else return;
  e.preventDefault();
});


route();

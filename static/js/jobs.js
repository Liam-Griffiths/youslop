/* Summary polling belongs to the open drawer, independent of watchJob. */
let jobsDrawer = null;
let jobsSummary = [];

/* The strip lists every running job, from any project; a cheap loopback poll. */
async function pollJobsSummary() {
  if (document.hidden || jobsDrawer) return;
  try { jobsSummary = await api('/api/jobs'); paintJobsStrip(); } catch {}
}
setInterval(pollJobsSummary, 4000);

function openJobs() {
  if (jobsDrawer || document.querySelector('dialog[open]')) return;
  let timer;
  const dialog = studioDialog('jobs-drawer', `<div class="row">
    <h2 id="studio-dialog-title">Jobs</h2><div class="spacer"></div>
    <button type="button" class="btn sm ghost" data-close>Close</button></div>
    <p class="sub">Running and recent work across all projects. Cancel stops at the next progress update.</p>
    <div class="sub" data-jobs-error role="status"></div>
    <div data-jobs-list>Loading…</div>`, () => {
      clearTimeout(timer);
      jobsDrawer = null;
      paintJobsStrip();
    });
  jobsDrawer = dialog;
  $('[data-close]', dialog).onclick = () => dialog.close();
  const refresh = async () => {
    try {
      const rows = await api('/api/jobs');
      if (!dialog.open) return;
      jobsSummary = rows;
      const focused = document.activeElement?.dataset.cancelJob;
      const list = $('[data-jobs-list]', dialog);
      if (!list.querySelector('article')) list.textContent = '';
      for (const j of rows) {
        const markup = `
        <div class="row"><strong>${esc(jobLabel(j))}</strong><div class="spacer"></div>
          <span class="mono">${esc(j.state === 'error' ? 'failed' : j.state)} · ${j.elapsed}s</span>
          ${j.state === 'running' && j.cancellable ? `<button type="button" class="btn sm ghost"
            data-cancel-job="${esc(j.id)}" aria-label="Cancel ${esc(j.kind)} for ${esc(j.project_title || j.project_id || 'Library')}">Cancel</button>` : ''}</div>
        <div class="sub mono">${esc(j.project_title || 'Library')}</div>
        ${j.kind === 'transcribe' ? `<a href="#/footage/${encodeURIComponent(j.project_id)}" data-shoot>Open shoot</a>` : ''}
        ${j.state === 'error' ? errorMarkup(j, j) : `<p class="mono jobs-last-line">${esc(jobProgress(j))}</p>`}
        ${j.state === 'running' && j.status ? `<div class="sub mono">${esc(j.status)}</div>` : ''}`;
        let article = [...list.children].find(el => el.dataset.job === j.id);
        if (!article) {
          article = document.createElement('article');
          article.className = 'jobs-row'; article.dataset.job = j.id;
          list.insertBefore(article, list.children[rows.indexOf(j)] || null);
        }
        // Completed rows stay mounted so Details and selected report text survive polling.
        if (article.jobMarkup !== markup) { article.innerHTML = markup; article.jobMarkup = markup; }
      }
      for (const article of [...list.children]) {
        if (!rows.some(j => j.id === article.dataset.job)) article.remove();
      }
      if (!rows.length) list.textContent = 'No jobs yet.';
      if (focused) {
        const button = [...dialog.querySelectorAll('[data-cancel-job]')].find(b => b.dataset.cancelJob === focused);
        (button || $('[data-close]', dialog)).focus();
      }
      paintJobsStrip();
    } catch (e) {
      if (dialog.open) $('[data-jobs-error]', dialog).innerHTML = errorMarkup(e);
    } finally {
      if (dialog.open) timer = setTimeout(refresh, 1200);
    }
  };
  dialog.addEventListener('click', async e => {
    if (e.target.closest('[data-shoot]')) { dialog.close(); return; }
    const button = e.target.closest('[data-cancel-job]');
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      await api(`/api/jobs/${button.dataset.cancelJob}/cancel`, {method: 'POST'});
      if (dialog.open) $('[data-jobs-error]', dialog).textContent = 'Cancellation requested; waiting for the next progress update.';
    } catch (err) {
      if (dialog.open) { $('[data-jobs-error]', dialog).innerHTML = errorMarkup(err); button.disabled = false; }
    }
  });
  refresh();
}

function jobLabel(j) {
  const label = j.kind === 'timeline sound' ? 'Mixing the sound' : j.kind === 'timeline proxy' ? 'Preparing pictures' : j.kind;
  return String(label || 'Job').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
}

function jobProgress(j) {
  return j.writes === false && /timeline (sound|proxy)/.test(j.kind) ? jobLabel(j) : j.last_log_line || 'Working…';
}

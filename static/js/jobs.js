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
    <p class="sub" data-jobs-error role="status"></p>
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
      $('[data-jobs-list]', dialog).innerHTML = rows.map(j => `<article class="jobs-row">
        <div class="row"><strong>${esc(j.kind)}</strong><div class="spacer"></div>
          <span class="mono">${esc(j.state)} · ${j.elapsed}s</span>
          ${j.state === 'running' && j.cancellable ? `<button type="button" class="btn sm ghost"
            data-cancel-job="${esc(j.id)}" aria-label="Cancel ${esc(j.kind)} for ${esc(j.project_title || j.project_id || 'Library')}">Cancel</button>` : ''}</div>
        <div class="sub mono">${esc(j.project_title || j.project_id || 'Library')} · ${esc(j.id)}</div>
        ${j.kind === 'transcribe' ? `<a href="#/footage/${encodeURIComponent(j.project_id)}" data-shoot>Open shoot</a>` : ''}
        <p class="mono jobs-last-line">${esc(j.last_log_line || '—')}</p>
        ${j.state === 'running' && j.status ? `<div class="sub mono">${esc(j.status)}</div>` : ''}</article>`).join('')
        || '<p class="sub">No jobs yet.</p>';
      if (focused) {
        const button = [...dialog.querySelectorAll('[data-cancel-job]')].find(b => b.dataset.cancelJob === focused);
        (button || $('[data-close]', dialog)).focus();
      }
      paintJobsStrip();
    } catch (e) {
      if (dialog.open) $('[data-jobs-error]', dialog).textContent = e.message;
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
      if (dialog.open) { $('[data-jobs-error]', dialog).textContent = err.message; button.disabled = false; }
    }
  });
  refresh();
}

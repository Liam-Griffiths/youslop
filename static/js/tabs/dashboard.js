/* Project overview; all state comes from the cheap stages API. */
function paintDashboard() {
  const p = state.project;
  const rows = state.stageStates?.pid === p.id ? state.stageStates.items : [];
  const paragraphs = p.slides.filter(s => !s.insert);
  const voiced = paragraphs.filter(s => s.take?.path).length;
  const edit = rows.find(r => r.id === 'edit');
  const missing = Math.max(0, (edit?.pictures_total || 0) - (edit?.pictures_done || 0));
  const research = p.research?.facts?.length || p.research?.sources?.length ? p.research : p.draft?.research || {};
  const outline = Object.keys(p.outline || {}).length ? p.outline : p.draft?.outline || {};
  const channel = (state.channels || []).find(c => c.id === p.channel_id);
  const hook = outline.hook?.first_line?.trim();
  const firstParagraph = paragraphs[0]?.narration || '';
  const activity = (p.log || []).slice(-8);
  const actions = {script: ['Open script', 'script'],
    voice: [voiced < paragraphs.length ? `Record ${paragraphs.length - voiced} paragraph${paragraphs.length - voiced === 1 ? '' : 's'}` : 'Open voice', 'voice'],
    edit: [missing ? `Fill ${missing} pictures` : 'Open timeline', missing ? 'edit/pictures' : 'edit'],
    publish: [p.render?.output ? 'Open publish' : 'Render', 'publish']};
  $('#tabbody').innerHTML = `<h1>Dashboard</h1><div class="dashboard-layout">
    <section aria-label="Stage progress" class="dashboard-stages">${STAGES.filter(([id]) => id !== 'dashboard').map(([id, name]) => {
      const row = rows.find(r => r.id === id), [label, target] = actions[id];
      const value = id === 'script' ? paragraphs.filter(s => s.narration?.trim()).length
        : id === 'voice' ? voiced : id === 'edit' ? edit?.pictures_done || 0 : row?.status === 'ready' ? 1 : 0;
      const max = ['script', 'voice'].includes(id) ? paragraphs.length : id === 'edit' ? edit?.pictures_total : 1;
      return `<article class="dashboard-card"><h2>${esc(row?.label || name)}</h2>
        <p class="mono">${esc(row?.reason || 'Loading progress…')}</p>
        <progress value="${value}" max="${max || 1}" aria-label="${esc(name)} progress"></progress>
        <a class="btn sm" href="#/p/${p.id}/${target}">${esc(label)}</a></article>`;
    }).join('')}</section>
    <section class="dashboard-bin" aria-labelledby="dashboard-bin-title"><div class="bin-heading"><h2 id="dashboard-bin-title">Bin</h2>
      <div class="bin-actions"><button class="btn sm dashboard-drop" id="bin-add">Add files</button><button class="btn sm" id="bin-new">New note</button></div></div>
      <div id="project-bin"><p class="sub">Loading project bin…</p></div>
      <a class="dashboard-snippet" href="#/p/${p.id}/script"><span class="kicker">Script</span>
        ${hook && hook !== firstParagraph.trim() ? `<h3>${esc(hook)}</h3>` : ''}
        <p>${esc(firstParagraph || 'Write the first paragraph in Script.')}</p></a>
    </section>
    <aside class="dashboard-facts"><h2>Project facts</h2>
      <label class="kicker" for="dashboard-idea">Idea</label>
      <textarea id="dashboard-idea" rows="3" onchange="dashboardSaveIdea(this)">${esc(p.idea)}</textarea>
      <dl><dt>Channel</dt><dd>${esc(channel?.name || (p.channel_id ? 'Channel' : 'Standalone'))}</dd>
        <dt>Format</dt><dd>${esc(FORMAT_INFO.find(f => f.key === p.style.format)?.label || p.style.format)}</dd>
        <dt>Aspect</dt><dd class="mono">${p.aspect === 'portrait' ? '9:16' : p.aspect === 'square' ? '1:1' : '16:9'}</dd>
        <dt>Length</dt><dd class="mono">${fmtTime(p.est_seconds || 0)} current / ${p.target_minutes} min target</dd></dl>
      <h2>Research</h2><p class="mono">${research.facts?.length || 0} facts · ${research.sources?.length || 0} sources · ${research.open_questions?.length || 0} open questions</p>
      <a href="#/p/${p.id}/script/outline">Open research in Script</a>
      ${activity.length ? `<h2>Recent activity</h2><ol class="dashboard-activity mono">${activity.map(line => `<li>${esc(line)}</li>`).join('')}</ol>` : ''}
    </aside></div>`;
  paintBin();
}

async function dashboardSaveIdea(input) {
  const p = state.project, idea = input.value;
  try {
    const saved = await api(`/api/projects/${p.id}`, {method:'PATCH', body:JSON.stringify({idea})});
    if (state.project?.id === p.id) { state.project = saved; paintProjectShell(); }
    toast('Idea saved');
  } catch (e) { toast(e.message, true); }
}

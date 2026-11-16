/* Project Home: what you have gathered (materials and research), what the video
   still needs, and the brief. Production status is one line, not the page;
   the stage bar already carries the stages. All state comes from cheap APIs. */
function paintDashboard() {
  const p = state.project;
  const rows = state.stageStates?.pid === p.id ? state.stageStates.items.filter(r => r.id !== 'dashboard') : [];
  const research = p.research?.facts?.length || p.research?.sources?.length ? p.research : p.draft?.research || {};
  const channel = (state.channels || []).find(c => c.id === p.channel_id);
  const seconds = p.est_seconds || 0, target = (p.target_minutes || 0) * 60;
  const questions = research.open_questions || [];
  $('#tabbody').innerHTML = `<div class="home-layout">
    <section class="home-status" aria-label="Production status">
      <span class="home-length mono">${fmtTime(seconds)} of ${fmtTime(target)}</span>
      ${target ? `<span class="home-meter" role="img" aria-label="${fmtTime(seconds)} of a ${fmtTime(target)} target"><span style="width:${Math.min(100, seconds / target * 100).toFixed(1)}%"></span></span>` : ''}
      ${rows.map(r => `<a class="home-stage ${esc(r.status)}" href="#/p/${p.id}/${r.id}"><span class="home-dot" aria-hidden="true"></span>${esc(r.label)} <span class="mono">${esc(r.reason)}</span></a>`).join('')
        || '<span class="sub">Loading status…</span>'}
    </section>
    <div class="home-body">
      <aside class="home-agent" aria-label="Agent">${homeAgentPanel()}</aside>
      <div class="home-main">
        <section class="home-card" aria-labelledby="home-materials">
          <div class="home-card-head"><h2 id="home-materials">Materials</h2>
            <span class="mono sub" id="home-materials-count"></span><span class="spacer"></span>
            <button class="btn sm" id="bin-add">Add files</button><button class="btn sm" id="bin-new">New note</button></div>
          <div id="project-bin"><p class="sub">Loading materials…</p></div>
        </section>
        <section class="home-card" aria-labelledby="home-research">
          <div class="home-card-head"><h2 id="home-research">Research documents</h2>
            <span class="mono sub">${(research.documents || []).length} documents · ${research.facts?.length || 0} facts · ${questions.length} open questions</span>
            <span class="spacer"></span><a class="btn sm" href="#/p/${p.id}/script">Facts beside the script</a></div>
          <div id="home-docs"><p class="sub">Loading documents…</p></div>
          ${questions.length ? `<details class="home-questions-box"><summary class="kicker home-q-head">Open questions · ${questions.length}</summary><ul class="home-questions">${questions.map(q => `<li>${esc(typeof q === 'string' ? q : q.question || q.text || '')}</li>`).join('')}</ul></details>` : ''}
        </section>
        <section class="home-card" aria-labelledby="home-needed">
          <div class="home-card-head"><h2 id="home-needed">Still needed</h2></div>
          <div id="home-needs">${homeNeeds(p)}</div>
        </section>
      </div>
      <aside class="home-side" aria-label="Brief">
        <section class="home-card" aria-labelledby="home-brief"><h2 id="home-brief">Brief</h2>
          <label class="kicker" for="dashboard-idea">Idea</label>
          <textarea id="dashboard-idea" rows="4" onchange="dashboardSaveIdea(this)">${esc(p.idea)}</textarea>
          <dl class="home-facts"><dt>Channel</dt><dd>${esc(channel?.name || (p.channel_id ? 'Channel' : 'Standalone'))}</dd>
            <dt>Format</dt><dd>${esc(FORMAT_INFO.find(f => f.key === p.style.format)?.label || p.style.format)}</dd>
            <dt>Aspect</dt><dd class="mono">${p.aspect === 'portrait' ? '9:16' : p.aspect === 'square' ? '1:1' : '16:9'}</dd>
            <dt>Target</dt><dd class="mono">${p.target_minutes} min</dd></dl>
        </section>
      </aside>
    </div></div>`;
  paintBin();
  paintHomeDocs();
  homeAgentPaint();
}

// What the video still needs, from every stage, each with a way there.
// Material rights come in once the materials listing has loaded.
function homeNeeds(p) {
  const runs = scriptRuns(p), shotOf = sid => runs.findIndex(run => run.some(s => s.id === sid));
  const spoken = p.slides.filter(s => !s.insert?.kind);
  const leads = (p.picture_runs || []).map(r => p.slides.find(s => s.id === r[0])).filter(Boolean);
  const bare = leads.filter(s => !s.insert?.kind && !s.on_camera && ['kenburns', 'essay'].includes(pictureKind(s, p))
    && !s.candidates?.some(c => c.id === s.chosen_id));
  const stale = spoken.filter(s => s.take?.path && s.take.narration != null && s.take.narration !== s.narration);
  const unread = spoken.filter(s => !s.take?.path && s.narration?.trim());
  const shotList = ids => [...new Set(ids.map(shotOf).filter(n => n >= 0))].sort((a, b) => a - b).slice(0, 8).map(n => n + 1).join(', ');
  const items = [];
  if (bare.length) items.push(['EDIT', `${bare.length} visual${bare.length === 1 ? ' has' : 's have'} no picture`, `Shots ${shotList(bare.map(s => s.id))}`,
    `<a class="btn sm" href="#/p/${p.id}/script/shots" onclick="scriptOpenShot('${runs[shotOf(bare[0].id)]?.[0].id}')">Design the first</a>`]);
  if (stale.length) items.push(['VOICE', `${stale.length} recording${stale.length === 1 ? ' is' : 's are'} out of date`, `The words changed after recording, in shots ${shotList(stale.map(s => s.id))}`,
    `<a class="btn sm" href="#/p/${p.id}/voice">Re-record</a>`]);
  if (unread.length) items.push(['VOICE', `${unread.length} paragraph${unread.length === 1 ? '' : 's'} not recorded`, '',
    `<a class="btn sm" href="#/p/${p.id}/voice">Record</a>`]);
  const rights = (binView.pid === p.id ? binView.items : []).filter(binRightsUnknown);
  if (rights.length) items.push(['RIGHTS', `${rights.length} material${rights.length === 1 ? '' : 's'} in the video with no licence noted`, rights.slice(0, 3).map(i => i.title).join(' · '),
    `<button class="btn sm" onclick="homeShowMaterials(${JSON.stringify(rights.map(i => i.id)).replaceAll('"', '&quot;')})">Show them</button>`]);
  return items.map(([stage, title, detail, action]) => `<div class="home-need"><span class="mono home-need-stage">${stage}</span>
      <div><strong>${esc(title)}</strong>${detail ? `<span class="sub">${esc(detail)}</span>` : ''}</div>${action}</div>`).join('')
    || '<p class="sub">Nothing outstanding that Home can see.</p>';
}
function homeNeedsPaint() {
  const host = $('#home-needs'), count = $('#home-materials-count');
  if (host && state.project) host.innerHTML = homeNeeds(state.project);
  if (count && binView.pid === state.project?.id) {
    const unused = binView.items.filter(i => ['image', 'clip', 'audio'].includes(i.kind) && !i.used_in.length).length;
    count.textContent = `${binView.items.length} item${binView.items.length === 1 ? '' : 's'}${unused ? ` · ${unused} unused` : ''}`;
  }
}
function homeShowMaterials(ids) {
  binView.selected = ids;
  binView.kind = '';
  binShell();
  $('#project-bin')?.scrollIntoView({block: 'start'});
}

async function dashboardSaveIdea(input) {
  const p = state.project, idea = input.value;
  try {
    const saved = await api(`/api/projects/${p.id}`, {method:'PATCH', body:JSON.stringify({idea})});
    if (state.project?.id === p.id) { state.project = saved; paintProjectShell(); }
    toast('Idea saved');
  } catch (e) { toast(e.message, true); }
}

/* Proxy-only footage logger. Transcripts can join footageSearchText when ASR exists. */
let footageView = null, footagePoll, footageReverse;
const footageURL = (tail = '') => `/api/footage/shoots/${footageView.id}${tail}`;
const footageClip = () => footageView?.clips.find(c => c.id === footageView.current);
const footageLabels = () => [...new Set([...footageView.vocabulary, ...footageView.clips.flatMap(c => c.labels)])];
const footageSearchText = c => [...c.labels, c.note].join(' ').toLocaleLowerCase();
function footageStop() { clearTimeout(footagePoll); clearInterval(footageReverse); }
async function renderFootage(id) {
  footageStop();
  try {
    if (!id) {
      const shoots = await api('/api/footage/shoots');
      view.innerHTML = `<h1>Footage</h1><p class="sub">Import a folder or camera card. Proxies process in the background.</p>
        ${shoots.map(s => `<a class="home-shoot" href="#/footage/${esc(s.id)}"><b>${esc(s.name)}</b><span class="mono">${s.files} files · ${s.clips} clips · ${s.labelled} labelled</span></a>`).join('') || '<p>No shoots yet.</p>'}
        <section class="panel footage-import"><h2>Import a shoot</h2><label for="footage-path">Source folder or file</label>
        <div class="row"><input id="footage-path" type="text"><button class="btn" onclick="footagePick('footage-path')">Choose folder</button></div>
        <label><input id="footage-copy" type="checkbox">Copy originals into this shoot</label>
        <button class="btn primary" onclick="footageImport()">Import a shoot</button></section>`;
      return;
    }
    const previous = footageView?.id === id ? footageView : {};
    const data = await api(`/api/footage/shoots/${encodeURIComponent(id)}`);
    if (location.hash !== `#/footage/${id}`) return;
    footageView = {...previous, ...data, selected: previous.selected || new Set(), query: previous.query || '', filter: previous.filter || 'all'};
    footageView.current = data.clips.some(c => c.id === previous.current) ? previous.current : data.clips.find(c => !c.rejected)?.id;
    view.innerHTML = `<div class="row"><a href="#/footage">All shoots</a><h1>${esc(data.path.split('/').pop() || id)}</h1><span class="mono">${data.status.ready}/${data.status.total} proxies · ${data.clips.length} clips</span></div>
      <p id="footage-status" role="status" aria-live="polite">${data.processing ? 'Processing — logger read-only until done' : 'Ready to log'}</p>
      <div class="footage-layout"><aside class="panel"><h2>Your labels</h2><div id="footage-palette"></div>
      <label for="footage-vocabulary">Vocabulary (one per line)</label><textarea id="footage-vocabulary" ${data.processing ? 'disabled' : ''}>${esc(data.vocabulary.join('\n'))}</textarea>
      <button class="btn" onclick="footageVocabulary()" ${data.processing ? 'disabled' : ''}>Save vocabulary</button>
      <button class="btn" onclick="footageEstimate()" ${data.processing ? 'disabled' : ''}>Estimate Claude labels</button><div id="footage-budget"></div>
      <label for="footage-filter">Show</label><select id="footage-filter" onchange="footageView.filter=this.value;footageGrid()"><option value="all">Usable and flagged</option><option value="usable">Usable</option><option value="flagged">Flagged</option></select>
      <label><input type="checkbox" onchange="footageView.rejected=this.checked;footageGrid()" ${previous.rejected ? 'checked' : ''}>Show rejected</label></aside>
      <section><div class="footage-work"><div><video id="footage-player" controls preload="metadata"></video><div id="footage-trim" class="footage-trim" aria-label="Selected span"></div>
      <div class="row"><button class="btn" onclick="footageShuttle(-1)">J · Reverse</button><button class="btn" onclick="footageShuttle(0)">K · Pause</button><button class="btn" onclick="footageShuttle(1)">L · Forward</button><button class="btn" onclick="footagePlay()">Space · Play/pause</button></div>
      <p class="mono sub">Arrows select · I/O trim · 1–9 label · S star · X reject · / search</p></div><div id="footage-inspector" class="panel"></div></div>
      <label for="footage-search">Search labels and notes</label><input id="footage-search" type="search" value="${esc(footageView.query)}" oninput="footageView.query=this.value;footageGrid()">
      <div class="row"><button class="btn" onclick="footageSelectVisible()">Select visible clips</button><button class="btn" onclick="footageView.selected.clear();footageGrid()">Clear selection</button><span id="footage-count" class="mono"></span></div>
      <div id="footage-grid"></div>
      <fieldset ${data.processing ? 'disabled' : ''}><legend>Selected clips</legend><label for="footage-bulk">Labels (comma separated)</label><input type="text" id="footage-bulk">
      <button class="btn" onclick="footageBulk(false)">Add labels</button><button class="btn" onclick="footageBulk(true)">Remove labels</button>
      <details><summary>Export selected clips</summary><label for="footage-output">Output folder</label><input type="text" id="footage-output"><button class="btn" onclick="footagePick('footage-output')">Choose folder</button>
      <label for="footage-pattern">Naming pattern</label><input type="text" id="footage-pattern" value="{label}-{id}"><label for="footage-mode">Encoding</label><select id="footage-mode"><option value="encode">Re-encode · frame precision</option><option value="copy">Stream copy · may differ by one GOP</option></select>
      <button class="btn" onclick="footageExport()">Export selected</button></details></fieldset></section></div>`;
    $('#footage-filter').value = footageView.filter;
    footagePalette(); footageGrid(); footageInspect();
    if (data.processing) footagePoll = setTimeout(() => renderFootage(id), 1500);
  } catch (e) { view.innerHTML = `<p>${esc(e.message)}</p><a href="#/footage">All shoots</a>`; }
}
async function footagePick(field) {
  try { const d = await api('/api/pick-folder', {method:'POST'}); $(`#${field}`).value = d.path; }
  catch (e) { if (e.status === 501) { toast('Type or paste a folder path'); $(`#${field}`).focus(); } else toast(e.message, true); }
}
async function footageImport() {
  try { const d = await api('/api/footage/import', {method:'POST', body:JSON.stringify({path:$('#footage-path').value, copy:$('#footage-copy').checked})}); go(`#/footage/${d.id}`); }
  catch (e) { toast(e.message, true); }
}
function footagePalette() {
  $('#footage-palette').innerHTML = footageLabels().map((l,i) => `${i === footageView.vocabulary.length ? '<h2>Other labels</h2>' : ''}<button class="btn" ${footageView.processing ? 'disabled' : ''} onclick="footageToggleLabel(${i})"><span class="mono">${i < 9 ? i+1 : ''}</span> ${esc(l)} <span class="mono">${footageView.clips.filter(c=>c.labels.includes(l)).length}</span></button>`).join('');
}
function footageVisible() {
  return footageView.clips.filter(c => (footageView.rejected || !c.rejected) && footageSearchText(c).includes(footageView.query.toLocaleLowerCase()) && (footageView.filter === 'all' || (footageView.filter === 'flagged') === (c.quality.usable === false)));
}
function footageGrid() {
  const groups = new Map(), clips = footageVisible();
  for (const c of clips) { const label = footageLabels().find(l=>c.labels.includes(l)) || ''; if (!groups.has(label)) groups.set(label, []); groups.get(label).push(c); }
  $('#footage-grid').innerHTML = [...groups].sort(([a],[b])=>!a ? 1 : !b ? -1 : 0).map(([label,items]) => `<h2>${esc(label || 'Unlabelled')} <span class="mono">${items.length}</span></h2><div class="footage-grid">${items.map(c => `<article>
    <button class="footage-tile ${c.id === footageView.current ? 'active' : ''}" data-clip="${esc(c.id)}" aria-label="Open ${esc(c.id)}" onclick="footageChoose('${c.id}')" onpointermove="footageScrub(event,'${c.id}')" style="background-image:url('${footageURL(`/media/sprites/${c.file}.jpg`)}')"></button>
    <label><input type="checkbox" ${footageView.selected.has(c.id) ? 'checked' : ''} onchange="this.checked?footageView.selected.add('${c.id}'):footageView.selected.delete('${c.id}');footageCount()">${esc(c.id)}</label>
    <span class="mono">${(c.out_s-c.in_s).toFixed(1)} s</span> ${[...c.quality.reasons || [], c.starred?'starred':'', c.rejected?'rejected':'', c.duplicate_group ? c.best_take === c.id ? 'best' : 'duplicate' : ''].filter(Boolean).map(p=>`<span class="chip">${esc(p)}</span>`).join('')}</article>`).join('')}</div>`).join('') || '<p>No matching clips.</p>';
  for (const tile of document.querySelectorAll('.footage-tile')) footageScrub({currentTarget:tile, clientX:tile.getBoundingClientRect().left}, tile.dataset.clip);
  footageCount();
}
function footageCount() { $('#footage-count').textContent = `${footageView.selected.size} selected`; }
function footageSelectVisible() { footageVisible().forEach(c=>footageView.selected.add(c.id)); footageGrid(); }
function footageScrub(e,id) {
  const c = footageView.clips.find(c=>c.id===id), tile=e.currentTarget, box=tile.getBoundingClientRect();
  const duration=footageView.files.find(f=>f.id===c.file).duration;
  const t=c.in_s+(c.out_s-c.in_s)*Math.max(0,Math.min(1,(e.clientX-box.left)/box.width));
  const frame=Math.max(0,Math.min(Math.ceil(duration/2)-1,Math.floor(t/2))), scale=box.width/160;
  tile.style.backgroundSize=`${1600*scale}px auto`; tile.style.backgroundPosition=`${-frame%10*box.width}px ${-Math.floor(frame/10)*90*scale}px`;
}
function footageChoose(id) { clearInterval(footageReverse); footageView.current=id; footageGrid(); footageInspect(); }
function footageInspect() {
  const c=footageClip(), player=$('#footage-player');
  if (!c) { $('#footage-inspector').textContent='Select a clip to log.'; player.removeAttribute('src'); return; }
  const duration=footageView.files.find(f=>f.id===c.file).duration;
  $('#footage-trim').innerHTML=`<span style="margin-left:${c.in_s/duration*100}%;width:${(c.out_s-c.in_s)/duration*100}%" class="mono">${c.in_s.toFixed(2)}–${c.out_s.toFixed(2)} s</span>`;
  player.src=footageURL(`/media/proxies/${c.file}.mp4`); player.onloadedmetadata=()=>{player.currentTime=c.in_s;};
  player.ontimeupdate=()=>{if (player.currentTime>=c.out_s) player.pause();};
  $('#footage-inspector').innerHTML=`<h2>${esc(c.id)}</h2><fieldset ${footageView.processing?'disabled':''}><legend>Clip</legend>
    <div class="footage-inout"><label for="footage-in">In (s)</label><label for="footage-out">Out (s)</label>
    <div class="row"><input class="mono" id="footage-in" type="number" step="0.01" value="${c.in_s}" onchange="footagePatch({in_s:Number(this.value)})"><button class="btn sm" onclick="footageMark('in_s')" title="Set in at the playhead (I)">I</button></div>
    <div class="row"><input class="mono" id="footage-out" type="number" step="0.01" value="${c.out_s}" onchange="footagePatch({out_s:Number(this.value)})"><button class="btn sm" onclick="footageMark('out_s')" title="Set out at the playhead (O)">O</button></div></div>
    <label for="footage-labels">Labels (comma separated)</label><input type="text" id="footage-labels" value="${esc(c.labels.join(', '))}" onchange="footagePatch({labels:this.value.split(',').map(x=>x.trim()).filter(Boolean)})">
    <label for="footage-note">Note</label><textarea id="footage-note" rows="2" onchange="footagePatch({note:this.value})">${esc(c.note)}</textarea>
    <button class="btn" aria-pressed="${c.starred}" onclick="footagePatch({starred:!footageClip().starred})">S · Star</button><button class="btn" aria-pressed="${c.rejected}" onclick="footageReject()">X · Reject</button></fieldset>
    <p>${esc((c.quality.reasons || []).join(', ') || 'No quality flags')}</p><p>${c.duplicate_group ? `Similar takes · best: ${esc(c.best_take)}` : ''}</p>`;
}
async function footagePatch(changes, message) {
  if (!footageClip() || footageView.processing) return;
  const c=footageClip(), time=$('#footage-player').currentTime;
  try { Object.assign(c, await api(footageURL(`/clips/${c.id}`), {method:'PATCH', body:JSON.stringify(changes)})); footagePalette(); footageGrid(); footageInspect(); $('#footage-player').onloadedmetadata=()=>{$('#footage-player').currentTime=time;}; $('#footage-status').textContent=message || 'Saved'; }
  catch(e) { toast(e.message,true); if(e.status===409) renderFootage(footageView.id); }
}
function footageToggleLabel(i) { const c=footageClip(), l=footageLabels()[i]; if(c&&l) footagePatch({labels:c.labels.includes(l)?c.labels.filter(x=>x!==l):[...c.labels,l]}, `Labelled: ${l}`); }
async function footageReject() {
  const c=footageClip(); if(!c) return;
  const list=footageVisible(), i=list.findIndex(x=>x.id===c.id);
  await footagePatch({rejected:!c.rejected}, c.rejected ? 'Restored' : 'Rejected');
  if (!footageView.rejected && footageClip()?.rejected) { const next=footageVisible()[Math.min(i, footageVisible().length-1)]; if(next) footageChoose(next.id); }
}
function footageMark(name) { footagePatch({[name]:$('#footage-player').currentTime}); }
function footagePlay() { clearInterval(footageReverse); const p=$('#footage-player'); if(!footageClip())return; if(p.paused){if(p.currentTime>=footageClip().out_s)p.currentTime=footageClip().in_s;p.play().catch(e=>toast(e.message,true));}else p.pause(); }
function footageShuttle(direction) {
  clearInterval(footageReverse); const p=$('#footage-player'); if(!footageClip())return;
  if(direction<=0) p.pause();
  if(direction<0) footageReverse=setInterval(()=>{p.currentTime=Math.max(footageClip().in_s,p.currentTime-.1);if(p.currentTime<=footageClip().in_s)clearInterval(footageReverse);},100);
  if(direction>0){p.playbackRate=p.paused?1:Math.min(4,p.playbackRate*2);if(p.currentTime>=footageClip().out_s)p.currentTime=footageClip().in_s;p.play().catch(e=>toast(e.message,true));}
}
async function footageSend(action, payload) {
  try { await api(footageURL(`/${action}`), {method:'POST',body:JSON.stringify(payload)}); await renderFootage(footageView.id); }
  catch(e){toast(e.message,true);if(e.status===409)renderFootage(footageView.id);}
}
function footageBulk(remove) { const labels=$('#footage-bulk').value.split(',').map(x=>x.trim()).filter(Boolean); return footageSend('relabel',{clip_ids:[...footageView.selected], [remove?'remove':'add']:labels}); }
function footageVocabulary() { return footageSend('vocabulary',{labels:$('#footage-vocabulary').value.split('\n').map(x=>x.trim()).filter(Boolean)}); }
async function footageEstimate() {
  try { const budget=await api(footageURL('/labels/estimate')); footageView.budget=budget; $('#footage-budget').innerHTML=`<p class="mono">${budget.uncached} uncached clips · ${budget.calls} calls · ~${budget.input_tokens} input / ${budget.output_tokens} output tokens</p><button class="btn" onclick="footageSend('labels',{confirm:true,estimate:footageView.budget})">Confirm and label with Claude</button>`; }
  catch(e){toast(e.message,true);}
}
function footageExport() { return footageSend('export',{clip_ids:[...footageView.selected],output:$('#footage-output').value,pattern:$('#footage-pattern').value,mode:$('#footage-mode').value}); }
document.addEventListener('keydown', e=>{
  if(!location.hash.startsWith('#/footage/') || !$('#footage-grid') || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('.modal, dialog[open]'))return;
  const k=e.key.toLowerCase(), c=footageClip();
  if(k.startsWith('arrow')) { const list=footageVisible(), i=list.findIndex(x=>x.id===c?.id), tile=$('.footage-tile'), columns=tile?Math.max(1,Math.floor(tile.parentElement.parentElement.clientWidth/(tile.parentElement.offsetWidth+10))):1; const delta={arrowleft:-1,arrowright:1,arrowup:-columns,arrowdown:columns}[k]; if(list.length)footageChoose(list[Math.max(0,Math.min(list.length-1,i+delta))].id); }
  else if(k==='/')$('#footage-search').focus();
  else if(k===' ')footagePlay();
  else if(k==='j'||k==='k'||k==='l')footageShuttle({j:-1,k:0,l:1}[k]);
  else if(k==='i'||k==='o')footageMark(k==='i'?'in_s':'out_s');
  else if(k==='s'&&c)footagePatch({starred:!c.starred});
  else if(k==='x'&&c)footageReject();
  else if(/^[1-9]$/.test(k))footageToggleLabel(Number(k)-1);
  else return;
  e.preventDefault();
});

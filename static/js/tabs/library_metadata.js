// Culling controls live separately from explorer navigation and shared picture helpers.
const LM = {filters:{}, collections:[], labels:[], writes:Promise.resolve(), used:null};
const libColors = ['', 'red', 'yellow', 'green', 'blue', 'purple'];
const libFilters = () => LM.filters[LX.node] ||= {};
function libRemember() {
  const f=libFilters(); f.q=state.library.q; f.kind=state.library.kind;
  try { localStorage.setItem('library-filters',JSON.stringify(LM.filters)); } catch {}
}
function libRestore() {
  const f=libFilters(); state.library.q=f.q || ''; state.library.kind=f.kind || '';
  if($('#libq')) $('#libq').value=state.library.q;
  libFilterBar();
}
function libMatches(a,f) {
  const labels=f.labels || [], tags=a.tags || [], date=a.added_at&&(f.from||f.to) ? new Date(a.added_at*1000).toLocaleDateString('en-CA') : '';
  const orientation=a.width>0&&a.height>0 ? a.width===a.height?'square':a.width>a.height?'landscape':'portrait' : '';
  return (!f.kind || a.kind===f.kind) && (a.rating||0)>=(+f.rating||0) && (!f.color || a.color===f.color)
    && (!labels.length || (f.match==='all' ? labels.every(t=>tags.includes(t)) : labels.some(t=>tags.includes(t))))
    && (!f.orientation || f.orientation===orientation) && (!f.from || date>=f.from) && (!f.to || (date&&date<=f.to))
    && (!f.usage || (LM.used!==null && (f.usage==='used' ? !!LM.used[a.id]?.length : !LM.used[a.id]?.length)))
    && (!f.q || [libName(a),libFile(a),...tags].join(' ').toLowerCase().includes(f.q.trim().toLowerCase()));
}
async function libMetadataInit() {
  Object.assign(LM,await api('/api/library/metadata/context'));
  try { LM.filters=JSON.parse(localStorage.getItem('library-filters') || '{}') || {}; } catch {}
  libRestore();
  if(Object.values(LM.filters).some(f=>f.usage)||LM.collections.some(c=>c.filters?.usage)) libLoadUses().catch(()=>{});
}
function libLoadUses() {
  if(LM.used!==null) return Promise.resolve(LM.used);
  if(!LM.loading) LM.loading=api('/api/library/metadata/used').then(uses=>{LM.used=uses;if($('#libgrid')){libTree();libPaint();}return uses;})
    .catch(e=>{toast(e.message,true);throw e;}).finally(()=>{LM.loading=null;});
  return LM.loading;
}
function libFilterBar() {
  const bar=$('#libfilters'); if(!bar)return;
  const f=libFilters(), select=(key,label,options)=>`<label for="libfilter-${key}">${label}<select id="libfilter-${key}" data-filter="${key}">${options.map(([v,t])=>`<option value="${v}" ${String(f[key]||'')===String(v)?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;
  bar.innerHTML=select('rating','Rating ≥',[['','Any'],...[1,2,3,4,5].map(n=>[n,'★'.repeat(n)])])
    +select('color','Colour',[['','Any'],...libColors.slice(1).map(c=>[c,c])])
    +`<label for="libfilter-labels">Labels<input id="libfilter-labels" data-filter="labels" placeholder="Comma separated" value="${esc((f.labels||[]).join(', '))}"></label>`
    +select('match','Labels match',[['any','Any'],['all','All']])+select('usage','Project use',[['','Any'],['used','Used'],['unused','Unused']])
    +select('orientation','Orientation',[['','Any'],...['landscape','portrait','square'].map(s=>[s,s])])
    +`<label for="libfilter-from">Added from<input id="libfilter-from" type="date" data-filter="from" value="${esc(f.from||'')}"></label><label for="libfilter-to">Added to<input id="libfilter-to" type="date" data-filter="to" value="${esc(f.to||'')}"></label>
    <button class="btn xs ghost" data-reset>Reset filters</button>`;
  bar.querySelectorAll('[data-filter]').forEach(el=>el.onchange=()=>{
    f[el.dataset.filter]=el.dataset.filter==='labels'?el.value.split(',').map(t=>t.trim()).filter(Boolean):el.value;
    libRemember(); if(f.usage) libLoadUses().catch(()=>{}); libPaint();
  });
  bar.querySelector('[data-reset]').onclick=()=>{LM.filters[LX.node]={};libRestore();libRemember();libPaint();};
}
function libCulling(a) {
  return `<span class="library-culling" aria-label="${a.rating||0} stars, ${esc(a.color||'no colour')}"><span class="library-stars">${'★'.repeat(a.rating||0)}<span>${'★'.repeat(5-(a.rating||0))}</span></span>${a.color?`<span class="library-dot" data-color="${esc(a.color)}" title="${esc(a.color)}"></span>`:''}</span>`;
}
function libWrite(operation,payload) {
  const task=LM.writes.then(async()=>{
    const data=await api('/api/library/metadata/'+operation,{method:'POST',body:JSON.stringify(payload)});
    LM.collections=data.collections;LM.labels=data.labels;state.library.items=data.assets;
    if(operation==='labels'&&['rename','delete'].includes(payload.action)) {
      for(const f of Object.values(LM.filters)) f.labels=[...new Set((f.labels||[]).flatMap(t=>t!==payload.old?[t]:payload.action==='rename'?[payload.new.trim()]:[]))];
      libRemember();libFilterBar();
    }
    if($('#libtree')){const focused=$('#libgrid')?.contains(document.activeElement);libTree();libPaint();if(focused)($('#libgrid [tabindex="0"]')||$('#libgrid')).focus();}
  });
  LM.writes=task.catch(e=>toast(e.message,true));return task;
}
function libRateKey(e) {
  if(e.ctrlKey||e.metaKey||e.altKey||!(/^[0-9`]$/.test(e.key)))return false;
  const ids=[...LX.selected].filter(id=>state.library.items.some(a=>a.id===id));
  if(!ids.length)return false;
  e.preventDefault();libWrite('batch',{ids,...(+e.key<=5&&e.key!=='`'?{rating:+e.key}:{color:e.key==='`'?'':libColors[+e.key-5]})}).catch(()=>{});return true;
}
function libMetadataControls(selected,shared) {
  const a=selected[0];
  return `<label for="librating">Rating (keys 0–5)</label><select id="librating"><option value="">Set rating…</option>${[0,1,2,3,4,5].map(n=>`<option value="${n}">${n} stars</option>`).join('')}</select>
    <label for="libcolor">Colour (6–9; backtick clears)</label><select id="libcolor"><option value="">Set colour…</option>${libColors.map(c=>`<option value="${c||'clear'}">${c||'Clear'}</option>`).join('')}</select>
    ${selected.length===1?libCulling(a):''}<button type="button" class="btn sm ghost" id="liblabels">Edit label vocabulary</button>
    <p class="sub">Remove shared labels above, or remove any label below.</p><label for="libremove">Remove labels (comma separated)</label><input id="libremove">
    <button type="button" class="btn sm" id="libremovebtn">Remove labels</button>
    <label for="libmanual">Manual collection</label><select id="libmanual"><option value="">Choose collection…</option>${LM.collections.filter(c=>c.kind==='manual').map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select>
    <button type="button" class="btn sm" id="libcollect">Add selection to collection</button><div id="libuses" class="mono" role="status"></div>`;
}
function libBindMetadata(selected) {
  const ids=selected.map(a=>a.id), send=patch=>libWrite('batch',{ids,...patch}).catch(()=>{});
  $('#librating').onchange=e=>{if(e.target.value!=='')send({rating:+e.target.value});};
  $('#libcolor').onchange=e=>{if(e.target.value)send({color:e.target.value==='clear'?'':e.target.value});};
  $('#libremovebtn').onclick=()=>send({remove:$('#libremove').value.split(',').map(t=>t.trim()).filter(Boolean)});
  $('#liblabels').onclick=()=>openLabelsEditor({getLabels:()=>LM.labels,change:p=>libWrite('labels',p)});
  $('#libcollect').onclick=()=>{const id=$('#libmanual').value;if(id)libWrite('collections',{id,ids}).catch(()=>{});else $('#libmanual').focus();};
  const show=()=>{const el=$('#libuses');if(!el||ids.length!==LX.selected.size||!ids.every(id=>LX.selected.has(id)))return;
    const uses=[...new Map(selected.flatMap(a=>LM.used?.[a.id]||[]).map(p=>[p.id,p])).values()];
    el.innerHTML=LM.used===null?'Loading project use…':`Used in: ${uses.map(p=>`<a href="#/p/${encodeURIComponent(p.id)}/dashboard">${esc(p.title)}</a>`).join(', ')||'No projects'}`;};
  show();if(LM.used===null)libLoadUses().then(show).catch(()=>{});
}
function libCollectionNodes(add) {
  for(const c of LM.collections) add('collection:'+c.id,c.name,a=>c.kind==='manual'?c.ids.includes(a.id):
    libMatches(a,c.filters)&&(!c.filters.scope||LX.nodes.find(n=>n.id===c.filters.scope)?.match(a)));
}
function libCollectionDialog() {
  const dialog=studioDialog('library-collection',`<h2 id="studio-dialog-title">New collection</h2>
    <label for="libcollectionname">Name</label><input id="libcollectionname" required>
    <label for="libcollectionkind">Kind</label><select id="libcollectionkind"><option value="manual">Manual — drag media into the tree</option><option value="smart">Smart — save current filters</option></select>
    <button class="btn" data-save>Save collection</button><button class="btn ghost" data-cancel>Cancel</button>`);
  dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
  dialog.querySelector('[data-save]').onclick=async()=>{
    libRemember();const name=$('#libcollectionname').value.trim(),kind=$('#libcollectionkind').value;
    if(!name)return $('#libcollectionname').focus();
    if(kind==='smart'&&/^(shoot|project|footage|projects)/.test(LX.node))return toast('Select Library media to save a smart collection.',true);
    const filters={...libFilters(),scope:LX.node==='all'?'':LX.node};
    try{await libWrite('collections',{name,kind,filters});dialog.close();}catch{}
  };
}
function libCollectionDrops() {
  $('#libtree').querySelectorAll('[data-node^="collection:"]').forEach(el=>{
    const c=LM.collections.find(c=>'collection:'+c.id===el.dataset.node);if(c?.kind!=='manual')return;
    el.ondragover=e=>{if(e.dataTransfer.types.includes('application/x-corkbored-library'))e.preventDefault();};
    el.ondrop=e=>{e.preventDefault();try{libWrite('collections',{id:c.id,ids:libDragRefs(e.dataTransfer).map(r=>r.slice(8))}).catch(()=>{});}catch(err){toast(err.message,true);}};
  });
}

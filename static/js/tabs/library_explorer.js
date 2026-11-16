// Explorer state survives metadata saves and rescans; references never edit originals.
const LX = {node:'all', selected:new Set(), anchor:0, focus:0, mode:'grid', sort:'added_at', direction:-1, extra:[], nodes:[]};
const libName = a => a.title || a.filename || a.id;
const libFile = a => (a.source_path || a.filename || '').split('/').at(-1);
const libSize = a => a.size ? `${(a.size / 1048576).toFixed(2)} MB` : '—';
const libDate = a => a.added_at ? new Date(a.added_at*1000).toLocaleDateString() : '—';
const libDims = a => a.width ? `${a.width}×${a.height}` : '—';
const libUrl = a => a.url || `/api/library/file/${encodeURIComponent(a.id)}`;
const libThumb = a => a.thumb ?? `/api/library/thumb/${encodeURIComponent(a.id)}`;

function libConfirm(message) {
  return appConfirm({title: 'Library', body: message});
}

async function renderLibrary() {
  LX.observer?.disconnect();
  const tools = await renderLibraryManagement();
  view.innerHTML = `<div class="row"><h1>Library</h1><div class="spacer"></div><a href="#/blocks">Blocks</a></div>
    ${jobPanel()}<section class="library-explorer" aria-label="Library explorer">
      <nav class="library-tree" aria-label="Media folders"><div id="libtree"></div><div class="library-tree-tools">
        <button class="btn sm" id="libcollection">+ Collection</button><button class="btn sm" id="liblink">+ Link a folder</button><button class="btn sm" id="libscan">Rescan</button>
        <label for="libtreewidth">Tree width</label><input id="libtreewidth" type="range" min="180" max="400" value="260"></div></nav>
      <div class="library-center"><div id="libcrumb" aria-label="Breadcrumb"></div><div class="library-toolbar">
        <label for="libq">Search</label><input id="libq" type="search" placeholder="Title, tags or filename" value="${esc(state.library.q)}">
        <div id="libkinds" role="group" aria-label="Kind"></div>
        <label for="libsize">Thumbnails</label><input id="libsize" type="range" min="80" max="320" step="10">
        <button class="btn sm" id="libmode">Details</button><span id="libcount" class="mono" role="status"></span></div>
        <details class="library-filters-wrap"><summary>Filters</summary><div id="libfilters" class="library-filters" aria-label="Media filters"></div></details><div id="libcolumns"></div><div id="libgrid" class="library-grid" role="listbox" aria-label="Media" aria-multiselectable="true" tabindex="0"></div></div>
      <aside id="libpreview" class="library-preview" aria-label="Media preview"></aside></section>`;
  view.append(tools); paintModelLibrary();
  $('#liblink').onclick = () => { tools.open = true; $('#libfolderpath').scrollIntoView(); browseForLibraryFolder(); };
  $('#libscan').onclick = () => rescanLibraryFolder(LX.nodes.find(n=>n.id===LX.node)?.folder);
  $('#libq').oninput = () => { state.library.q = $('#libq').value; libRemember(); libPaint(); };
  $('#libcollection').onclick=libCollectionDialog;
  await libMetadataInit();
  $('#libmode').onclick = () => { LX.mode = LX.mode === 'grid' ? 'list' : 'grid'; libPaint(); };
  let size = 160; try { size = +localStorage.getItem('library-thumb-size') || size; } catch {}
  $('#libsize').value = Math.min(320, Math.max(80,size));
  $('#libsize').oninput = e => { $('#libgrid').style.setProperty('--thumb', `${e.target.value}px`); try { localStorage.setItem('library-thumb-size',e.target.value); } catch {} };
  $('#libtreewidth').oninput = e => $('.library-explorer').style.setProperty('--tree', `${e.target.value}px`);
  $('#libgrid').onkeydown = libKey; $('#libgrid').onpointerdown = libMarquee;
  $('#libgrid').onscroll = e => { $('#libcolumns').scrollLeft = e.target.scrollLeft; };
  const results = await Promise.allSettled([api('/api/footage/shoots'), api('/api/projects')]);
  if (!$('#libtree')) return;
  LX.shoots = results[0].status === 'fulfilled' ? results[0].value : [];
  LX.projects = results[1].status === 'fulfilled' ? results[1].value : [];
  if (results.some(r=>r.status==='rejected')) toast('Some Library roots could not be loaded. Reopen Library to retry.',true);
  libTree(); if (/^(shoot|project):/.test(LX.node)) await libNode(LX.node); else libPaint();
}

function libTree() {
  const items = state.library.items, nodes = LX.nodes = [];
  if (LX.node==='all') LX.extra=[];
  const add = (id,label,match,parent='',folder='') => { const n={id,label,match,parent,folder}; nodes.push(n); return n; };
  add('all','All media',()=>true); add('uploaded','Uploaded',a=>!a.folder_id);
  add('recent','Recent',a=>items.slice(0,50).includes(a));
  for (const f of state.library.folders) {
    const root = `folder:${f.id}`, base = f.path.replace(/\/$/,'')+'/';
    add(root,f.label || f.path.split('/').at(-1),a=>a.folder_id===f.id,'',f.id);
    const paths = new Set();
    items.filter(a=>a.folder_id===f.id && a.source_path.startsWith(base)).forEach(a=>{
      const parts=a.source_path.slice(base.length).split('/').slice(0,-1);
      parts.forEach((_,i)=>paths.add(parts.slice(0,i+1).join('/')));
    });
    [...paths].sort().forEach(path=>add(`${root}/${path}`,path.split('/').at(-1),
      a=>a.folder_id===f.id && a.source_path.startsWith(base+path+'/'),path.includes('/') ? `${root}/${path.slice(0,path.lastIndexOf('/'))}` : root,f.id));
  }
  add('footage','Footage',()=>false); add('projects','Projects',()=>false);
  (LX.shoots || []).forEach(s=>add(`shoot:${s.id}`,s.name,()=>false,'footage'));
  (LX.projects || []).forEach(p=>add(`project:${p.id}`,p.title || p.id,()=>false,'projects'));
  libCollectionNodes(add);
  if (!nodes.some(n=>n.id===LX.node)) { LX.node='all'; LX.extra=[]; }
  const opened = new Set([...document.querySelectorAll('#libtree details[open]')].map(el=>el.dataset.node));
  const branch = parent => nodes.filter(n=>n.parent===parent).map(n=>{
    const children=nodes.some(c=>c.parent===n.id), count=n.id.startsWith('shoot:') ? LX.shoots.find(s=>`shoot:${s.id}`===n.id).clips :
      n.id.startsWith('project:') ? (LX.projectCounts?.[n.id] ?? LX.projects.find(p=>`project:${p.id}`===n.id)?.bin_count ?? 0) : n.id==='footage' ? (LX.shoots||[]).reduce((n,s)=>n+s.clips,0) : n.id==='projects' ? (LX.projects||[]).length : items.filter(n.match).length;
    const button=`<button class="btn ghost" data-node="${esc(n.id)}" aria-current="${n.id===LX.node ? 'page' : 'false'}">${esc(n.label)} <span class="mono">${count}</span></button>`;
    return children ? `<details data-node="${esc(n.id)}" ${opened.has(n.id) || LX.node.startsWith(n.id+'/') ? 'open' : ''}><summary>${button}</summary><div>${branch(n.id)}</div></details>` : button;
  }).join('');
  $('#libtree').innerHTML = branch('');
  $('#libtree').querySelectorAll('button').forEach(b=>b.onclick=e=>{ e.preventDefault(); libNode(b.dataset.node).catch(err=>toast(err.message,true)); });
  libCollectionDrops();
  $('#libtree').onkeydown = e => {
    const d=e.target.closest('details'); if (!d || !['ArrowLeft','ArrowRight'].includes(e.key)) return;
    e.preventDefault(); d.open=e.key==='ArrowRight';
  };
}

async function libNode(id) {
  libRemember(); LX.node=id; libRestore(); LX.extra=[]; LX.selected.clear(); LX.focus=0; LX.anchor=0; libTree(); libPaint();
  if (id.startsWith('shoot:')) {
    const s=await api(`/api/footage/shoots/${encodeURIComponent(id.slice(6))}`); if (LX.node!==id) return;
    LX.extra=s.clips.map(c=>{ const f=s.files.find(f=>f.id===c.file) || {}, base=`/api/footage/shoots/${s.id}/media/`;
      return {...f,...c,id:`footage:${s.id}/${c.id}`,title:c.title || c.note || c.id,tags:c.labels,kind:f.kind || 'video',
        duration:c.out_s-c.in_s,added_at:s.added_at,readonly:true,route:`#/footage/${s.id}`,
        thumb:c.thumbs[0] ? base+'thumbs/'+c.thumbs[0] : '',strip:c.thumbs.map(t=>base+'thumbs/'+t),
        url:base+(f.kind==='audio' ? 'audio/'+f.id : 'proxies/'+f.id+'.mp4')+`#t=${c.in_s},${c.out_s}`}; });
  } else if (id.startsWith('project:')) {
    const pid=encodeURIComponent(id.slice(8)), data=await api(`/api/projects/${pid}/bin`); if (LX.node!==id) return;
    (LX.projectCounts ||= {})[id]=data.items.length; libTree();
    LX.extra=data.items.map(a=>({...a,id:`bin:${pid}/${a.id}`,kind:a.kind==='clip'?'video':a.kind,tags:a.labels,
      license:a.licence,author:a.credit,readonly:true,route:`#/p/${pid}/dashboard`,url:a.kind==='note'||a.kind==='link'?'':`/api/projects/${pid}/bin/${a.id}/file`}));
  }
  libPaint();
}

function libVisible() {
  const node=LX.nodes.find(n=>n.id===LX.node), q=state.library.q.trim().toLowerCase();
  const items=LX.node.startsWith('shoot:') || LX.node.startsWith('project:') ? LX.extra : state.library.items.filter(node?.match || (()=>true));
  const values={name:libName,filename:libFile,dimensions:libDims,tags:a=>(a.tags||[]).join(', ')};
  return items.filter(a=>libMatches(a,libFilters()) && (!state.library.kind || a.kind===state.library.kind) && [libName(a),libFile(a),...(a.tags||[])].join(' ').toLowerCase().includes(q))
    .sort((a,b)=>{ const x=(values[LX.sort] || (a=>a[LX.sort]))(a) ?? '', y=(values[LX.sort] || (a=>a[LX.sort]))(b) ?? '';
      return LX.direction*(typeof x==='number' ? x-y : String(x).localeCompare(String(y))); });
}

function libPaint() {
  const grid=$('#libgrid'); if (!grid || !$('#libpreview')) return;
  LX.observer?.disconnect(); const items=LX.visible=libVisible();
  LX.selected=new Set([...LX.selected].filter(id=>items.some(a=>a.id===id)));
  LX.focus=Math.min(LX.focus,Math.max(0,items.length-1));
  const node=LX.nodes.find(n=>n.id===LX.node), crumbs=[];
  for(let n=node;n;n=LX.nodes.find(p=>p.id===n.parent)) crumbs.unshift(n.label);
  $('#libcrumb').textContent=crumbs.join(' / '); $('#libscan').disabled=!node?.folder;
  $('#libcount').textContent=`${items.length} items`; $('#libmode').textContent=LX.mode==='grid'?'Details':'Grid';
  $('#libmode').setAttribute('aria-pressed',String(LX.mode==='list'));
  $('#libkinds').innerHTML=['','image','video','audio'].map((k,i)=>`<button class="btn xs ghost" data-kind="${k}" aria-pressed="${state.library.kind===k}">${['All','Images','Clips','Audio'][i]}</button>`).join('');
  $('#libkinds').querySelectorAll('button').forEach(b=>b.onclick=()=>{state.library.kind=b.dataset.kind;libRemember();libPaint();});
  $('#libcolumns').innerHTML=LX.mode==='list' ? ['name','kind','size','dimensions','duration','added_at','tags','rating','color'].map(k=>`<button class="btn xs ghost" data-sort="${k}">${{added_at:'Added',tags:'Labels'}[k] || k}${LX.sort===k ? LX.direction===1?' ↑':' ↓' : ''}</button>`).join('') : '';
  if(LX.mode==='list') $('#libcolumns').innerHTML='<div class="library-columns-row">'+$('#libcolumns').innerHTML+'</div>';
  $('#libcolumns').querySelectorAll('button').forEach(b=>b.onclick=()=>{LX.direction=LX.sort===b.dataset.sort?-LX.direction:1;LX.sort=b.dataset.sort;libPaint();});
  grid.classList.toggle('details',LX.mode==='list'); grid.style.setProperty('--thumb',`${$('#libsize').value}px`);
  grid.innerHTML=items.map((a,i)=>`<div class="library-item" role="option" aria-selected="${LX.selected.has(a.id)}" tabindex="${i===LX.focus?0:-1}" data-index="${i}" draggable="${!a.readonly}">
    <div class="library-poster">${libThumb(a) ? `<img data-src="${esc(libThumb(a))}" loading="lazy" alt="">` : `<span>${esc(a.kind)}</span>`}</div>
    <span class="library-name" title="${esc(libName(a))}">${esc(libName(a))}</span><span class="mono">${esc(a.kind)}</span>
    ${LX.mode==='list'?`<span class="mono">${libSize(a)}</span><span class="mono">${libDims(a)}</span>`:''}
    <span class="mono">${a.duration?fmtTime(a.duration):'—'}</span>${LX.mode==='list'?`<span class="mono">${libDate(a)}</span><span>${esc((a.tags||[]).join(', '))}</span>`:''}${libCulling(a)}</div>`).join('') || '<p class="empty-note">No media here. Upload a file or link a folder below.</p>';
  LX.observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){const img=e.target;img.src=img.dataset.src;LX.observer.unobserve(img);}}),{root:grid,rootMargin:'250px'});
  grid.querySelectorAll('img').forEach(img=>LX.observer.observe(img));
  grid.querySelectorAll('[data-index]').forEach(el=>{
    const i=+el.dataset.index,a=items[i]; el.onclick=e=>libSelect(i,e); el.ondblclick=()=>libOpen(i);
    el.ondragstart=e=>{if(a.readonly)return e.preventDefault();if(!LX.selected.has(a.id))libSelect(i,{});
      const refs=[...LX.selected].map(id=>'library:'+id); e.dataTransfer.effectAllowed='copy';
      e.dataTransfer.setData('application/x-corkbored-library',JSON.stringify(refs)); e.dataTransfer.setData('text/plain',refs.join('\n'));
    };
    el.ondragend=()=>{if(typeof TL!=='undefined'){TL.insertDrag=null;tlInsertClearGhost();}};
    if(a.strip?.length) {el.onpointermove=e=>{const img=el.querySelector('img');if(img)img.src=a.strip[Math.max(0,Math.min(a.strip.length-1,Math.floor((e.clientX-el.getBoundingClientRect().left)/el.clientWidth*a.strip.length)))];};el.onpointerleave=()=>{el.querySelector('img').src=libThumb(a);};}
  });
  libPreview();
}

function libSelect(i,e) {
  const items=LX.visible; if(!items[i])return;
  if(e.shiftKey){if(!e.ctrlKey&&!e.metaKey)LX.selected.clear();items.slice(Math.min(LX.anchor,i),Math.max(LX.anchor,i)+1).forEach(a=>LX.selected.add(a.id));}
  else {if(!e.ctrlKey&&!e.metaKey)LX.selected.clear();const id=items[i].id;if(LX.selected.has(id))LX.selected.delete(id);else LX.selected.add(id);LX.anchor=i;}
  LX.focus=i; libSelection();
}
function libSelection() {
  $('#libgrid').querySelectorAll('[data-index]').forEach(el=>{el.setAttribute('aria-selected',LX.selected.has(LX.visible[+el.dataset.index].id));el.tabIndex=+el.dataset.index===LX.focus?0:-1;}); libPreview();
}
function libKey(e) {
  if(e.target.closest('input,textarea,button'))return;
  if(libRateKey(e))return;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();LX.visible.forEach(a=>LX.selected.add(a.id));libSelection();return;}
  if(e.key===' '||e.key==='Enter'){e.preventDefault();if(LX.visible.length)libOpen(LX.focus);return;}
  const el=$('#libgrid [data-index]'), cols=LX.mode==='list'?1:Math.max(1,Math.floor($('#libgrid').clientWidth/((el?.offsetWidth||160)+8)));
  const step={ArrowLeft:-1,ArrowRight:1,ArrowUp:-cols,ArrowDown:cols}[e.key]; if(!step)return;
  e.preventDefault();libSelect(Math.max(0,Math.min(LX.visible.length-1,LX.focus+step)),e);
  const focus=$(`#libgrid [data-index="${LX.focus}"]`);focus?.focus();focus?.scrollIntoView({block:'nearest'});
}
function libMarquee(e) {
  if(e.button!==0||e.target.closest('[data-index]'))return;
  const grid=e.currentTarget,r=grid.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top+grid.scrollTop;
  const before=e.ctrlKey||e.metaKey?new Set(LX.selected):new Set(), box=document.createElement('div');box.className='library-marquee';e.preventDefault();grid.focus();grid.append(box);grid.setPointerCapture(e.pointerId);LX.selected=new Set(before);libSelection();
  grid.onpointermove=ev=>{const xx=ev.clientX-r.left,yy=ev.clientY-r.top+grid.scrollTop,left=Math.min(x,xx),top=Math.min(y,yy),right=Math.max(x,xx),bottom=Math.max(y,yy);
    Object.assign(box.style,{left:left+'px',top:top+'px',width:right-left+'px',height:bottom-top+'px'});LX.selected=new Set(before);
    grid.querySelectorAll('[data-index]').forEach(el=>{const b=el.getBoundingClientRect(),l=b.left-r.left,t=b.top-r.top+grid.scrollTop;if(l<right&&l+b.width>left&&t<bottom&&t+b.height>top)LX.selected.add(LX.visible[+el.dataset.index].id);});libSelection();};
  grid.onpointerup=grid.onpointercancel=()=>{if(grid.hasPointerCapture(e.pointerId))grid.releasePointerCapture(e.pointerId);box.remove();grid.onpointermove=grid.onpointerup=grid.onpointercancel=null;};
}

function libMedia(a) {
  if(a.kind==='image')return `<img src="${esc(libUrl(a))}" alt="${esc(libName(a))}">`;
  if(['video','audio'].includes(a.kind))return `<${a.kind} controls preload="metadata" src="${esc(libUrl(a))}"></${a.kind}>`;
  return `<p>${esc(a.note || a.url || libName(a))}</p>`;
}
function libPreview() {
  const pane=$('#libpreview'), selected=LX.visible.filter(a=>LX.selected.has(a.id));
  if(!selected.length){pane.innerHTML='<p>Select media to preview and edit its metadata.</p>';return;}
  const a=selected[0], shared=(a.tags||[]).filter(t=>selected.every(a=>(a.tags||[]).includes(t))), readonly=selected.some(a=>a.readonly);
  let controls=readonly ? `<p>Read-only reference.</p><a href="${esc(a.route)}">Open source</a>` : `<form id="libmetadata">
    ${selected.length===1?`<label for="libedit-title">Title</label><input id="libedit-title" value="${esc(a.title)}">`:''}
    <label for="libedit-tags">${selected.length>1?'Shared labels':'Labels'} (comma separated)</label><input id="libedit-tags" value="${esc(shared.join(', '))}">
    <button class="btn sm">Save</button></form>`;
  if(!readonly&&selected.length===1) controls+=`<button class="btn sm ghost" id="libedit">Edit credit and licence</button><button class="btn sm ghost" id="libdelete">Delete</button>${a.source_path?'<button class="btn sm ghost" id="libreveal">Show in folder</button>':''}`;
  pane.innerHTML=`<h2>${selected.length>1?`${selected.length} selected`:esc(libName(a))}</h2>
    ${selected.length===1 ? `<div class="library-media">${libMedia(a)}</div><dl class="mono">${Object.entries({'File':libFile(a),'Path':a.source_path,'Dimensions':libDims(a),'Duration':a.duration?fmtTime(a.duration):'—','Size':libSize(a),'Added':libDate(a),'Source':a.source_page || (a.readonly?'Reference':a.folder_id?'Linked folder':'Uploaded'),'Licence':a.license,'Credit':a.author}).filter(([,v])=>v).map(([k,v])=>`<dt>${k}</dt><dd>${esc(String(v))}</dd>`).join('')}</dl>`:''}${controls}${readonly?'':libMetadataControls(selected,shared)}`;
  if(readonly)return;
  $('#libedit')?.addEventListener('click',()=>editLibraryAsset(a.id)); $('#libdelete')?.addEventListener('click',()=>deleteLibraryAsset(a.id));
  $('#libreveal')?.addEventListener('click',()=>api('/api/reveal',{method:'POST',body:JSON.stringify({scope:'library',id:a.id})}).catch(e=>toast(e.message,true)));
  $('#libmetadata').onsubmit=async e=>{e.preventDefault();const tags=$('#libedit-tags').value.split(',').map(t=>t.trim()).filter(Boolean), title=$('#libedit-title')?.value;
    const patch={ids:selected.map(a=>a.id),add:tags,remove:shared.filter(t=>!tags.includes(t))};if(title!==undefined)patch.title=title;
    try{await libWrite('batch',patch);toast('Metadata saved.');}catch{}};
  libBindMetadata(selected);
  if(selected.length===1&&!a.infoLoaded){a.infoLoaded=true;api(`/api/library/info/${a.id}`).then(info=>{a.size=info.size;if(LX.selected.size===1&&LX.selected.has(a.id)&&$('#libpreview')&&!$('#libpreview').contains(document.activeElement))libPreview();}).catch(()=>{});}
}
function libOpen(index) {
  const dialog=studioDialog('library-large', '<h2 id="studio-dialog-title">Preview</h2><button class="btn ghost" data-close>Close</button><div data-media></div>');
  const paint=()=>{const a=LX.visible[index];if(!a)return;dialog.querySelector('h2').textContent=libName(a);dialog.querySelector('[data-media]').innerHTML=libMedia(a);};
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();index=Math.max(0,Math.min(LX.visible.length-1,index+(e.key==='ArrowRight'?1:-1)));paint();});paint();
}

function libDragRefs(transfer) {
  const refs=JSON.parse(transfer.getData('application/x-corkbored-library'));
  if(!Array.isArray(refs)||!refs.length||!refs.every(r=>typeof r==='string'&&/^library:[a-zA-Z0-9_-]+$/.test(r))) throw Error('Invalid Library references');
  return refs;
}
// Bridge cross-window Library drags to the existing Edit insertion contract.
for(const type of ['dragover','drop'])document.addEventListener(type,e=>{
  if(!e.target.closest('#tl-track .tl-pictures, #tl-sources')||!e.dataTransfer?.types.includes('application/x-corkbored-library'))return;
  e.preventDefault();
  if(type==='dragover'){TL.insertDrag={pid:TL.pid,payload:{kind:'picture',seconds:4}};return;}
  try {const asset_id=libDragRefs(e.dataTransfer)[0].slice(8), payload={kind:'picture',asset_id,seconds:4};
    TL.insertDrag={pid:TL.pid,payload};
    if(e.target.closest('#tl-sources')){e.stopPropagation();tlSourceView.choice=payload;tlSourcesPaint();TL.insertDrag=null;}
  }catch(err){e.stopPropagation();TL.insertDrag=null;tlInsertClearGhost();toast(err.message,true);}
},true);
// Accept references in existing Materials without changing the bin implementation.
for(const type of ['dragover','drop'])document.addEventListener(type,async e=>{
  if(!e.target.closest('.home-layout')||!e.dataTransfer?.types.includes('application/x-corkbored-library')||!$('#project-bin'))return;
  e.preventDefault();if(type!=='drop')return;
  try {const refs=libDragRefs(e.dataTransfer);for(const source of refs)await binSend('/link','POST',{source});}catch(err){toast(err.message,true);}
});

window.addEventListener('hashchange',()=>LX.observer?.disconnect());

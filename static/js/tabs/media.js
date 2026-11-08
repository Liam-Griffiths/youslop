
async function renderLibrary() {
  const [items, folders] = await Promise.all([
    api('/api/library'), api('/api/library/folders'),
  ]);
  state.library.items = items;
  state.library.folders = folders;
  view.innerHTML = `
    <h1>Library</h1>
    <p class="sub">Your own royalty-free stock — downloaded by hand, tagged here,
      and searched alongside the archives for every slide in every project.</p>

    ${jobPanel()}
    <p>Browse, create and pin <a href="#/blocks">Blocks</a>.</p>

    <div class="card" style="margin-bottom:22px">
      <h3>Linked folders</h3>
      <p class="mono" style="color:var(--ink-faint);margin:-4px 0 14px">
        Point this at a folder of your own photos or footage and it is indexed
        in place — nothing is copied, only a small thumbnail per file. Rescan
        any time to pick up what changed.</p>
      ${folders.map((f) => `
        <div class="row" style="margin-bottom:8px;padding:9px 12px;background:#0f1116;
             border:1px solid var(--line-soft);border-radius:8px">
          <div style="flex:1;min-width:0">
            <strong>${esc(f.label || f.path.split('/').pop())}</strong>
            ${f.exists ? '' : '<span class="pill warn" style="margin-left:6px">missing</span>'}
            <div class="mono" style="color:var(--ink-faint);font-size:12px;
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(f.path)}</div>
          </div>
          <span class="mono" style="color:var(--ink-faint)">${f.asset_count} asset${f.asset_count === 1 ? '' : 's'}</span>
          <button class="btn sm ghost" onclick="rescanLibraryFolder('${f.id}')">rescan</button>
          <button class="btn sm ghost" onclick="removeLibraryFolder('${f.id}')">remove</button>
        </div>`).join('') || `<div class="empty-note" style="padding:14px">no folders linked yet</div>`}
      <div class="row" style="margin-top:10px">
        <input type="text" id="libfolderpath" placeholder="/path/to/your/photos"
          style="flex:1;min-width:220px">
        <button class="btn sm ghost" id="libfolderbrowse" onclick="browseForLibraryFolder()">browse…</button>
        <button class="btn sm primary" onclick="addLibraryFolder()">add folder</button>
      </div>
    </div>

    <div class="card" style="margin-bottom:22px">
      <h3>Add a single file</h3>
      <div class="row" style="margin-bottom:10px">
        <label class="btn sm" style="cursor:pointer">choose a file
          <input type="file" id="libfile" accept="image/*,video/*" hidden
            onchange="pickLibraryFile(this.files[0])"></label>
        <span class="mono" id="libfilename" style="color:var(--ink-faint)">no file chosen</span>
      </div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="libtitle" placeholder="title" style="flex:1;min-width:200px">
        <input type="text" id="libtags" placeholder="tags, comma separated" style="flex:1;min-width:200px">
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="libauthor" placeholder="author / photographer" style="flex:1;min-width:160px">
        <input type="text" id="liblicense" placeholder="licence — e.g. “Storyblocks (Essentials)”"
          style="flex:1;min-width:220px">
        <input type="text" id="libsource" placeholder="source page (optional)" style="flex:1;min-width:220px">
      </div>
      <button class="btn sm" id="libadd" onclick="uploadLibraryAsset()">add to library</button>
    </div>

    <div class="row" style="margin-bottom:16px">
      <input type="text" id="libq" placeholder="search title or tags…"
        style="flex:1;min-width:220px" value="${esc(state.library.q)}" oninput="filterLibrary()">
      <select id="libkind" style="width:auto" onchange="filterLibrary()">
        <option value="" ${state.library.kind === '' ? 'selected' : ''}>photos & clips</option>
        <option value="image" ${state.library.kind === 'image' ? 'selected' : ''}>photos only</option>
        <option value="video" ${state.library.kind === 'video' ? 'selected' : ''}>clips only</option>
      </select>
      <span class="mono" id="libcount" style="color:var(--ink-faint)"></span>
    </div>
    <div class="lib-grid" id="libgrid"></div>

    <div class="card" style="margin-top:28px" id="models3d"></div>
  `;
  paintLibraryGrid();
  paintModelLibrary();
}

// --------------------------------------------------------------- folders
async function browseForLibraryFolder() {
  try {
    const r = await api('/api/pick-folder', { method: 'POST' });
    $('#libfolderpath').value = r.path;
  } catch (e) {
    // 501 here just means "not running inside the desktop app" — the text
    // field below is the fallback, not an error worth a toast over.
    if (!String(e.message).includes('501')) toast(e.message, true);
  }
}

async function addLibraryFolder() {
  const path = $('#libfolderpath').value.trim();
  if (!path) return toast('Enter a folder path first.', true);
  try {
    const f = await api('/api/library/folders', {
      method: 'POST', body: JSON.stringify({ path }),
    });
    toast('Folder added — scanning…');
    await renderLibrary();
    await rescanLibraryFolder(f.id);
  } catch (e) { toast(e.message, true); }
}

async function rescanLibraryFolder(folderId) {
  const r = await api(`/api/library/folders/${folderId}/scan`, { method: 'POST' });
  watchJob(r.job, 'library scan', async () => { await renderLibrary(); });
  await renderLibrary();   // paints the now-set state.job so ticks have
                            // #joblog/#jobstate to update in place
}

async function removeLibraryFolder(folderId) {
  if (!confirm('Stop tracking this folder? Its entries leave the library — ' +
               'the files on disk are never touched.')) return;
  await api(`/api/library/folders/${folderId}`, { method: 'DELETE' });
  toast('Folder removed from the library.');
  await renderLibrary();
}

function pickLibraryFile(file) {
  state.library.file = file || null;
  $('#libfilename').textContent = file ? file.name : 'no file chosen';
  if (file && !$('#libtitle').value) {
    $('#libtitle').value = file.name.replace(/\.[a-z0-9]+$/i, '').replace(/[_-]+/g, ' ');
  }
}

async function uploadLibraryAsset() {
  const file = state.library.file;
  if (!file) return toast('Choose a file first.', true);
  const btn = $('#libadd');
  btn.disabled = true;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('title', $('#libtitle').value.trim());
  fd.append('tags', $('#libtags').value.trim());
  fd.append('author', $('#libauthor').value.trim());
  fd.append('license', $('#liblicense').value.trim());
  fd.append('source_page', $('#libsource').value.trim());
  try {
    await api('/api/library', { method: 'POST', body: fd });
    toast('Added to the library.');
    await renderLibrary();
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
  }
}

function filterLibrary() {
  state.library.q = $('#libq').value;
  state.library.kind = $('#libkind').value;
  paintLibraryGrid();
}

function paintLibraryGrid() {
  const grid = $('#libgrid');
  if (!grid) return;
  const q = state.library.q.trim().toLowerCase();
  const kind = state.library.kind;
  const items = state.library.items.filter((a) => {
    if (kind && a.kind !== kind) return false;
    if (!q) return true;
    return a.title.toLowerCase().includes(q) || a.tags.some((t) => t.toLowerCase().includes(q));
  });
  $('#libcount').textContent = `${items.length} asset${items.length === 1 ? '' : 's'}`;
  grid.innerHTML = items.map((a) => `
    <div class="lib-card">
      <div class="lib-thumb">
        <img src="/api/library/thumb/${a.id}" loading="lazy" onerror="this.parentNode.style.opacity=.25">
        ${a.kind === 'video' ? `<span class="kindtag num">clip · ${fmtTime(a.duration)}</span>` : ''}
      </div>
      <div class="lib-body">
        <div class="lib-title" title="${esc(a.title)}">${esc(a.title)}</div>
        <div class="lib-meta">${a.width || '?'}×${a.height || '?'}${esc(a.author ? ' · ' + a.author : '')}</div>
        <div class="lib-tags">
          ${a.tags.map((t) => `<span class="pill">${esc(t)}</span>`).join('') || ''}
        </div>
        <div class="row">
          <button class="btn xs ghost" onclick="editLibraryAsset('${a.id}')">edit</button>
          <button class="btn xs ghost danger" onclick="deleteLibraryAsset('${a.id}')">delete</button>
        </div>
      </div>
    </div>`).join('') || '<div class="empty-note">No downloads yet. Add a file above.</div>';
}

function editLibraryAsset(id) {
  const a = state.library.items.find((x) => x.id === id);
  if (!a) return;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:14px">
        <strong>Edit asset</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="ecancel">cancel</button>
      </div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="etitle" placeholder="title" style="flex:1;min-width:200px" value="${esc(a.title)}">
        <input type="text" id="etags" placeholder="tags, comma separated" style="flex:1;min-width:200px"
          value="${esc(a.tags.join(', '))}">
      </div>
      <div class="row" style="margin-bottom:14px">
        <input type="text" id="eauthor" placeholder="author" style="flex:1;min-width:160px" value="${esc(a.author)}">
        <input type="text" id="elicense" placeholder="licence" style="flex:1;min-width:200px" value="${esc(a.license)}">
        <input type="text" id="esource" placeholder="source page" style="flex:1;min-width:200px" value="${esc(a.source_page)}">
      </div>
      <button class="btn sm primary" id="esave">save</button>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  wrap.querySelector('#ecancel').onclick = close;
  wrap.querySelector('#esave').onclick = async () => {
    try {
      await api(`/api/library/${id}`, { method: 'PATCH', body: JSON.stringify({
        title: wrap.querySelector('#etitle').value.trim(),
        tags: wrap.querySelector('#etags').value.split(',').map((t) => t.trim()).filter(Boolean),
        author: wrap.querySelector('#eauthor').value.trim(),
        license: wrap.querySelector('#elicense').value.trim(),
        source_page: wrap.querySelector('#esource').value.trim(),
      }) });
      close();
      await renderLibrary();
    } catch (e) { toast(e.message, true); }
  };
}

async function deleteLibraryAsset(id) {
  if (!confirm('Remove this asset from the library? Projects that already used it keep their own copy.')) return;
  try {
    await api(`/api/library/${id}`, { method: 'DELETE' });
    state.library.items = state.library.items.filter((a) => a.id !== id);
    paintLibraryGrid();
  } catch (e) { toast(e.message, true); }
}

async function setSlideFocal(sid, cid) {
  const s = state.project.slides.find((x) => x.id === sid);
  const cand = s.candidates.find((c) => c.id === cid);
  if (!cand) return;
  openFocal(thumbUrl(cand), cand.focal, async (focal) => {
    cand.focal = focal;
    paintMedia();
    await saveSlide(sid, { focal, focal_id: cid });
  });
}

async function savePictureEvery(n) {
  await saveStyle({ picture_every: n });      // saveStyle repaints the tab
  toast(n === 1 ? 'A picture for every paragraph.'
                : `One picture every ${n} paragraphs — fewer to find.`);
}

async function setPictureMode(sid, mode) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (s.picture_mode === mode) mode = 'auto';
  await saveSlide(sid, { picture_mode: mode });
  state.project = await api(`/api/projects/${state.project.id}`);
  paintMedia();
}

async function choose(sid, cid) {
  const s = state.project.slides.find((x) => x.id === sid);
  s.chosen_id = cid;
  s.locked_media = true;
  paintMedia();
  await saveSlide(sid, { chosen_id: cid });
}

async function toggleKind(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  const kind = s.prefer_kind === 'image' ? 'video' : 'image';
  await saveSlide(sid, { prefer_kind: kind });
  const r = await api(`/api/projects/${state.project.id}/media`,
    { method: 'POST', body: JSON.stringify({ slide_ids: [sid] }) });
  watchJob(r.job, 'media');
  render();
}

// ------------------------------------------------------------ picture search
// The strip under a slide only has room for a dozen options at thumbnail size.
// This opens the full picker: type any term, ask for photos or clips, and judge
// the hits large. Picking saves straight away, so you can keep searching.
function openMediaSearch(sid, query = null, onPick = null, onClose = null) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const term = query ?? ((s.queries || [])[0] || s.visual_note || s.title || s.beat || '');
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>Find a picture</strong>
        <span class="mono" style="color:var(--ink-faint);min-width:0;overflow:hidden;
              text-overflow:ellipsis;white-space:nowrap">${esc(s.title || s.beat || '')}</span>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="pdone">done</button>
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="pq" style="flex:1;min-width:220px"
          placeholder="search the archives — e.g. “Grytviken whaling station 1914”"
          value="${esc(term)}">
        <select id="pkind" style="width:auto">
          <option value="image" ${s.prefer_kind === 'video' ? '' : 'selected'}>photos</option>
          <option value="video" ${s.prefer_kind === 'video' ? 'selected' : ''}>clips</option>
          <option value="reaction">reaction gif 😄</option>
        </select>
        <button class="btn sm primary" id="pgo">search</button>
      </div>
      <div class="mono" id="pnote" style="color:var(--ink-faint);margin-bottom:10px"></div>
      <div class="pick-grid" id="pres"></div>
    </div>`;
  document.body.appendChild(wrap);

  const q = wrap.querySelector('#pq');
  const kind = wrap.querySelector('#pkind');
  const go = wrap.querySelector('#pgo');
  const note = wrap.querySelector('#pnote');
  const res = wrap.querySelector('#pres');

  const paint = (list, label) => {
    note.textContent = label;
    res.innerHTML = list.map((c) => `
      <div class="pick ${c.id === s.chosen_id ? 'sel' : ''}" data-id="${esc(c.id)}"
           title="${esc(c.title)}">
        <img src="${thumbUrl(c)}" loading="lazy" onerror="this.parentNode.style.opacity=.25">
        ${c.kind === 'video' ? '<span class="kindtag">clip</span>' : ''}
        ${playBtn(sid, c)}
        <div class="pick-meta">
          <span>${esc(c.provider)}</span>
          <span>${c.width || '?'}×${c.height || '?'}</span>
        </div>
      </div>`).join('') || '<div class="empty-note">No pictures found. Try a broader search.</div>';
    res.querySelectorAll('.pick').forEach((el) => {
      el.onclick = () => {
        res.querySelectorAll('.pick').forEach((o) => o.classList.remove('sel'));
        el.classList.add('sel');
        if (onPick) Promise.resolve(onPick(el.dataset.id)).then(close).catch(e=>toast(e.message,true));
        else choose(sid, el.dataset.id);
      };
    });
  };

  const run = async () => {
    const query = q.value.trim();
    if (!query) return q.focus();
    go.disabled = q.disabled = true;
    note.textContent = `searching for “${query}”…`;
    res.innerHTML = '';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/search`,
        { method: 'POST', body: JSON.stringify({ query, kind: kind.value }) });
      Object.assign(s, r.slide);
      const hits = r.results || [];
      paint(hits, `${hits.length} for “${query}” · ${r.added} new to this slide`);
    } catch (e) {
      toast(e.message, true);
      note.textContent = e.message || 'that search failed';
    }
    go.disabled = q.disabled = false;
    q.focus();
  };

  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const close = () => { document.removeEventListener('keydown', onKey); wrap.remove(); if (onClose) onClose(); else paintMedia(); };
  document.addEventListener('keydown', onKey);
  wrap.querySelector('#pdone').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  go.onclick = run;
  q.onkeydown = (e) => { if (e.key === 'Enter') run(); };
  kind.onchange = () => {
    q.placeholder = kind.value === 'reaction'
      ? 'the reaction, not the subject — e.g. "mind blown", "facepalm", "slow clap"'
      : 'search the archives — e.g. "Grytviken whaling station 1914"';
    run();
  };

  paint(s.candidates, s.candidates.length
    ? `${s.candidates.length} options already gathered — or search for something else`
    : 'nothing gathered yet for this slide');
  q.focus();
  q.select();
}

async function uploadMedia(sid, file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await api(`/api/projects/${state.project.id}/slides/${sid}/upload`,
      { method: 'POST', body: fd });
    Object.assign(state.project.slides.find((x) => x.id === sid), r.slide);
    paintMedia();
    toast('added');
  } catch (e) { toast(e.message, true); }
}

function openMapPicker(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const place = s.map_place || s.visual_note || s.title || s.beat || '';
  const hasSaved = !!(s.map_lat || s.map_lon);
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:12px">
        <strong>Get a map</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="mclose">cancel</button>
      </div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="mjump" style="flex:1;min-width:220px"
          placeholder="jump to a place — e.g. “Ziguinchor, Senegal”" value="${esc(place)}">
        <button class="btn sm ghost" id="mjumpgo">jump</button>
      </div>
      <div id="mmap" style="height:380px;border-radius:8px;overflow:hidden;margin-bottom:10px"></div>
      <div class="row" style="margin-bottom:10px">
        <select id="mkind" style="width:auto">
          <option value="satellite">satellite</option>
          <option value="hybrid">satellite + labels</option>
          <option value="terrain">terrain</option>
          <option value="street">street map</option>
        </select>
        <select id="mstyle" style="width:auto">
          <option value="still">still</option>
          <option value="establishing">establishing shot — smooth zoom in</option>
          <option value="reveal">reveal — pull back to context</option>
          <option value="pan">pan — drift in from the side</option>
        </select>
        <div class="spacer"></div>
        <button class="btn sm primary" id="mgo" disabled>click the map first</button>
      </div>
      <div class="mono" id="mnote" style="color:var(--ink-faint)">click anywhere on the map to drop the pin — the zoom you're at is the zoom it renders at</div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { map.remove(); wrap.remove(); };
  wrap.querySelector('#mclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const kindSel = wrap.querySelector('#mkind');
  const styleSel = wrap.querySelector('#mstyle');
  const jump = wrap.querySelector('#mjump');
  const note = wrap.querySelector('#mnote');
  const go = wrap.querySelector('#mgo');
  kindSel.value = MAP_LAYERS_FOR[s.map_kind] ? s.map_kind : 'satellite';
  styleSel.value = ['establishing', 'reveal', 'pan'].includes(s.map_style) ? s.map_style : 'still';

  const startLat = hasSaved ? s.map_lat : 20, startLon = hasSaved ? s.map_lon : 0;
  const startZoom = hasSaved ? (s.map_zoom || 13) : 2;
  const map = L.map(wrap.querySelector('#mmap')).setView([startLat, startLon], startZoom);
  let tileLayers = [];
  let marker = hasSaved ? L.marker([s.map_lat, s.map_lon]).addTo(map) : null;

  function setTiles(kind) {
    tileLayers.forEach((l) => map.removeLayer(l));
    tileLayers = MAP_LAYERS_FOR[kind].map((source) => L.tileLayer(MAP_TILE_URLS[source],
      { attribution: MAP_TILE_ATTR[source] || '', maxZoom: 19 }).addTo(map));
  }
  setTiles(kindSel.value);
  kindSel.onchange = () => setTiles(kindSel.value);

  function armGo() {
    go.disabled = false;
    go.textContent = 'get it';
  }
  map.on('click', (e) => {
    if (marker) marker.setLatLng(e.latlng); else marker = L.marker(e.latlng).addTo(map);
    armGo();
  });
  if (marker) armGo();

  jump.onclick = null;
  wrap.querySelector('#mjumpgo').onclick = async () => {
    const q = jump.value.trim();
    if (!q) return jump.focus();
    note.textContent = 'looking it up…';
    try {
      const r = await api(`/api/maps/geocode?q=${encodeURIComponent(q)}`);
      map.setView([r.lat, r.lon], 13);
      note.textContent = 'click to drop the pin here, or pan/zoom first';
    } catch (e) {
      note.textContent = e.message;
    }
  };

  go.onclick = async () => {
    if (!marker) return;
    const { lat, lng } = marker.getLatLng();
    go.disabled = true;
    note.textContent = 'fetching tiles…';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/map`, {
        method: 'POST',
        body: JSON.stringify({
          lat, lon: lng, zoom: map.getZoom(),
          label: jump.value.trim(),
          kind: kindSel.value, style: styleSel.value,
        }),
      });
      Object.assign(s, r.slide);
      paintMedia();
      toast('added');
      close();
    } catch (e) {
      note.textContent = e.message;
      armGo();
    }
  };
  // Leaflet sizes itself off the DOM at construction time; the modal box
  // isn't done laying out yet on that first tick, so the tile grid renders
  // wrong until this nudges it once the box has its real size.
  setTimeout(() => map.invalidateSize(), 0);
}

// ------------------------------------------------------------------- board
// The handwritten format. Everything here is drawn server-side by Pillow and
// shown as a flat png, the same deal the thumbnail gets: one implementation of
// the layout, and what the editor shows is literally a frame of the render.
function boardKnobs(st, saver) {
  const hand = st.board_hand || 'marker';
  // The hands come from the server — it owns which faces are bundled, and a
  // second list here would go stale the first time one changed.
  const hands = state.boardHands || [{ key: 'marker', label: 'Marker', blurb: '' }];
  return `
    <label class="field"><span>Handwriting</span>
      <select onchange="${saver}({board_hand:this.value})">
        ${hands.map((h) => `<option value="${h.key}" ${h.key === hand ? 'selected' : ''}
          >${esc(h.label)}${h.blurb ? ' — ' + esc(h.blurb.split('.')[0].toLowerCase()) : ''}</option>`).join('')}
      </select></label>
    <label class="field"><span>The board</span>
      <input type="text" value="${esc(st.board_ground || '#3A4552')}"
        onchange="${saver}({board_ground:this.value})"></label>
    <label class="field"><span>Surface tooth — <b>${(st.board_grain ?? 0.5).toFixed(2)}</b></span>
      <input type="range" min="0" max="1" step="0.05" value="${st.board_grain ?? 0.5}"
        onchange="${saver}({board_grain:+this.value})"></label>
    <label class="field"><span>How fast a line lands — <b>${(st.board_settle ?? 0.5).toFixed(2)}s</b></span>
      <input type="range" min="0.18" max="1.2" step="0.02" value="${st.board_settle ?? 0.5}"
        onchange="${saver}({board_settle:+this.value})"></label>`;
}

function cutKnobs(st, saver) {
  const info = cutInfo(st.format);
  if (!info) return '';
  return `
    <div class="mono" style="color:var(--ink-faint);margin:-4px 0 12px">
      made for ${esc(info.for.toLowerCase())}</div>
    <label class="field"><span>Look</span>
      <select onchange="${saver}({cut_look:this.value})">
        ${info.looks.map((l) => `<option value="${l.key}" ${l.key === (st.cut_look || '') ? 'selected' : ''}
          >${esc(l.label)}</option>`).join('')}
      </select></label>`;
}

function cutUrl(sid, t = 0.5) {
  return `/api/projects/${state.project.id}/slides/${sid}/cut.png?t=${t}&v=${state.boardV || 0}`;
}

async function planCues(redo) {
  if (redo && !confirm('Rewrite every paragraph\'s cues for this cut, including the ones you edited?')) return;
  const r = await api(`/api/projects/${state.project.id}/cues/plan`,
    { method: 'POST', body: JSON.stringify({ redo: !!redo }) });
  watchJob(r.job, 'media');
  render();
}

// The cue editor: the paragraph's cues for this cut as JSON — the same shape
// the writer produces, which is the honest interface for a list of
// differently-shaped things — with a scrubbable frame redrawn on every save.
function openCueEditor(sid) {
  const p = state.project;
  const s = p.slides.find((x) => x.id === sid);
  const fmt = pictureKind(s);
  const info = cutInfo(fmt);
  if (!s || !info) return;
  const written = (s.cues || {})[fmt] || [];
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:12px">
        <strong>What this paragraph puts on screen — ${esc(info.label)}</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="cclose">close</button>
      </div>
      <div class="grid-2">
        <div>
          <div class="mono" style="color:var(--ink-faint);margin-bottom:8px">
            kinds: ${esc(info.kinds)}. Each cue's <b>on</b> is the words it lands on.
            ${written.length ? '' : '<br>Nothing written yet — this is drawn from the narration.'}</div>
          <textarea id="ccues" rows="16" spellcheck="false"
            style="font-family:monospace;font-size:12px"
            placeholder='[{"kind": "...", "on": "first words it lands on"}]'
          >${esc(written.length ? JSON.stringify(written, null, 2) : '')}</textarea>
          <div class="row" style="margin-top:10px">
            <button class="btn sm primary" id="csave">save</button>
            <div class="spacer"></div>
            <button class="btn sm ghost" id="cclear" title="go back to drawing it from the narration">
              clear</button>
          </div>
          <div class="mono" style="color:var(--ink-faint);margin-top:10px">
            ${esc(s.narration.slice(0, 260))}</div>
        </div>
        <div>
          <img id="cprev" src="${cutUrl(sid, 0.5)}" style="width:100%;border-radius:8px;background:#111">
          <label class="field" style="margin-top:8px"><span>Scrub through the paragraph</span>
            <input type="range" id="cscrub" min="0" max="1" step="0.02" value="0.5"></label>
          <div class="mono" id="cstate" style="color:var(--ink-faint)"></div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { wrap.remove(); paintMedia(); };
  wrap.querySelector('#cclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  const img = wrap.querySelector('#cprev');
  const scrub = wrap.querySelector('#cscrub');
  scrub.onchange = () => { img.src = cutUrl(sid, scrub.value); };
  const status = wrap.querySelector('#cstate');

  async function send(cues) {
    status.textContent = 'drawing…';
    try {
      const updated = await saveSlide(sid, { cues: { [fmt]: cues } });
      Object.assign(s, updated);
      state.boardV = (state.boardV || 0) + 1;
      img.src = cutUrl(sid, scrub.value);
      status.textContent = 'saved';
    } catch (e) { status.textContent = String(e.message || e); }
  }
  wrap.querySelector('#csave').onclick = () => {
    let cues;
    try { cues = JSON.parse(wrap.querySelector('#ccues').value || '[]'); }
    catch (e) { status.textContent = `That isn't valid JSON: ${e.message}`; return; }
    if (!Array.isArray(cues)) { status.textContent = 'Cues are a list: [ {...}, {...} ]'; return; }
    send(cues);
  };
  wrap.querySelector('#cclear').onclick = () => {
    wrap.querySelector('#ccues').value = '';
    send([]);
  };
}

function boardUrl(sid) {
  return `/api/projects/${state.project.id}/slides/${sid}/board.png?v=${state.boardV || 0}`;
}

function bumpBoards() {
  state.boardV = (state.boardV || 0) + 1;
}

async function planBoards(redo) {
  if (redo && !confirm('Rewrite every board, including the ones you wrote yourself?')) return;
  const r = await api(`/api/projects/${state.project.id}/board/plan`,
    { method: 'POST', body: JSON.stringify({ redo: !!redo }) });
  watchJob(r.job, 'media');
  render();
}

// The board editor: the four fields a template draws from, and the finished
// board redrawn after every change so you are editing the thing itself.
function openBoardEditor(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const tpls = state.boardTemplates || [];
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box">
      <div class="row" style="margin-bottom:12px">
        <strong>What this slide writes</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="bclose">close</button>
      </div>
      <div class="grid-2">
        <div>
          <label class="field"><span>Template</span>
            <select id="btpl">
              <option value="auto">auto — pick from what I write</option>
              ${tpls.map((t) => `<option value="${t.key}"
                ${t.key === s.board_template ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}
            </select></label>
          <div class="mono" id="bblurb" style="color:var(--ink-faint);margin:-8px 0 12px"></div>
          <label class="field"><span>The line it is about</span>
            <input type="text" id="blead" value="${esc(s.board_lead || '')}"
              placeholder="2-7 words, no full stop"></label>
          <label class="field"><span>Lines under it — one per line</span>
            <textarea id="bpoints" rows="6" placeholder="two to six words each
* a line starting with a star is picked out in the accent
this | that pairs up the two columns of a versus board
> a line starting with a chevron is the called-out line of code"
>${esc((s.board_points || []).join('\n'))}</textarea></label>
          <label class="field"><span>Footnote, caption or attribution</span>
            <input type="text" id="bnote" value="${esc(s.board_note || '')}"></label>
          <div class="row">
            <button class="btn sm primary" id="bsave">save</button>
            <button class="btn sm ghost" id="bdiagram">draw a diagram…</button>
            <div class="spacer"></div>
            <button class="btn sm ghost" id="bclear" title="go back to lines pulled out of the narration">
              clear</button>
          </div>
          <div class="mono" style="color:var(--ink-faint);margin-top:10px">
            ${esc(s.narration.slice(0, 220))}</div>
        </div>
        <div>
          <img id="bprev" src="${boardUrl(sid)}"
            style="width:100%;border-radius:8px;background:#2f3843">
          <div class="mono" id="bstate" style="color:var(--ink-faint);margin-top:8px">
            the finished board — it arrives element by element as you talk</div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { wrap.remove(); paintMedia(); };
  wrap.querySelector('#bclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const tpl = wrap.querySelector('#btpl');
  const blurb = wrap.querySelector('#bblurb');
  const showBlurb = () => {
    const t = tpls.find((x) => x.key === tpl.value);
    blurb.textContent = t ? t.blurb : 'Picks the template that fits what you write, '
      + 'and avoids repeating the slide before it.';
  };
  tpl.onchange = () => { showBlurb(); save(); };
  showBlurb();

  async function save() {
    const body = {
      board_template: tpl.value,
      board_lead: wrap.querySelector('#blead').value,
      board_points: wrap.querySelector('#bpoints').value.split('\n'),
      board_note: wrap.querySelector('#bnote').value,
    };
    wrap.querySelector('#bstate').textContent = 'drawing…';
    const updated = await saveSlide(sid, body);
    Object.assign(s, updated);
    bumpBoards();
    wrap.querySelector('#bprev').src = boardUrl(sid);
    wrap.querySelector('#bstate').textContent = 'saved';
  }
  wrap.querySelector('#bsave').onclick = save;
  wrap.querySelector('#bclear').onclick = async () => {
    wrap.querySelector('#blead').value = '';
    wrap.querySelector('#bpoints').value = '';
    wrap.querySelector('#bnote').value = '';
    tpl.value = 'auto';
    await save();
  };
  wrap.querySelector('#bdiagram').onclick = () => { close(); openDiagramEditor(sid); };
}

// ----------------------------------------------------------------- diagrams
// A spec in, a drawing out. The left half is the spec as lines, because typing
// JSON by hand is miserable; the JSON itself is one click away, because that
// is the shape an agent writes and the shape you paste back in.
function diagramToLines(spec) {
  const nodes = (spec.nodes || []).map((n) =>
    `${n.accent ? '*' : ''}${n.label}${n.note ? ' | ' + n.note : ''}${n.group ? ' @' + n.group : ''}`);
  const edges = (spec.edges || []).map((e) =>
    `${e.from} > ${e.to}${e.label ? ' : ' + e.label : ''}${e.dashed ? ' ~' : ''}`);
  return { nodes: nodes.join('\n'), edges: edges.join('\n') };
}

function linesToSpec(kind, title, nodeText, edgeText, note, reveal) {
  const nodes = nodeText.split('\n').map((raw) => raw.trim()).filter(Boolean).map((raw) => {
    const accent = raw.startsWith('*');
    let rest = accent ? raw.slice(1).trim() : raw;
    let group = '';
    const at = rest.lastIndexOf(' @');
    if (at > 0) { group = rest.slice(at + 2).trim(); rest = rest.slice(0, at); }
    const [label, ...note2] = rest.split('|');
    return { id: label.trim(), label: label.trim(), note: note2.join('|').trim(),
             group, accent };
  });
  const edges = edgeText.split('\n').map((raw) => raw.trim()).filter(Boolean).map((raw) => {
    const dashed = raw.endsWith('~');
    let rest = dashed ? raw.slice(0, -1).trim() : raw;
    const [pair, ...label] = rest.split(':');
    const [from, to] = pair.split('>').map((x) => x.trim());
    return { from, to, label: label.join(':').trim(), dashed };
  }).filter((e) => e.from && e.to);
  return { kind, title, nodes, edges, note, reveal };
}

function openDiagramEditor(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  const kinds = state.diagramKinds || [];
  const spec = Object.keys(s.diagram || {}).length ? s.diagram
    : { kind: 'flow', title: s.board_lead || s.title || '', nodes: [], edges: [],
        note: '', reveal: 'sequence' };
  const lines = diagramToLines(spec);
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>Draw a diagram</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="djson">show the spec</button>
        <button class="btn sm ghost" id="dclose">close</button>
      </div>
      <div class="grid-2">
        <div style="overflow:auto;max-height:calc(100vh - 160px);padding-right:16px">
          <div class="panel" style="background:#13151c;margin:0 0 16px;padding:14px">
            <div class="row" style="margin-bottom:8px">
              <span style="font-size:13px">✨ Ask Claude to draw this</span>
            </div>
            <textarea id="daskwhat" rows="2" style="margin-bottom:8px"
              placeholder="Leave blank to let Claude read the paragraph and pick a shape, or steer it — “as a cycle”, “put the database in the middle”…"></textarea>
            <button class="btn sm" id="dask">draw it for me</button>
            <span class="mono" id="daskstate" style="color:var(--ink-faint);margin-left:8px"></span>
          </div>
          <label class="field"><span>Layout</span>
            <select id="dkind">
              ${kinds.map((k) => `<option value="${k.key}"
                ${k.key === spec.kind ? 'selected' : ''}>${esc(k.label)}</option>`).join('')}
            </select></label>
          <div class="mono" id="dblurb" style="color:var(--ink-faint);margin:-8px 0 12px"></div>
          <label class="field"><span>Heading</span>
            <input type="text" id="dtitle" value="${esc(spec.title || '')}"></label>
          <label class="field"><span>Boxes — one per line</span>
            <textarea id="dnodes" rows="6" placeholder="Browser
Edge cache | 40ms
*Your server | the slow bit
a star picks one out, | adds a note, @ puts it in a column"
>${esc(lines.nodes)}</textarea></label>
          <label class="field"><span>Arrows — “from &gt; to : label”, ~ for dashed (flow only)</span>
            <textarea id="dedges" rows="3" placeholder="Browser > Edge cache : GET /
Edge cache > Your server : miss ~"
>${esc(lines.edges)}</textarea></label>
          <label class="field"><span>Footnote</span>
            <input type="text" id="dnote" value="${esc(spec.note || '')}"></label>
          <div class="row">
            <button class="btn sm primary" id="duse">use it on this slide</button>
            <button class="btn sm ghost" id="dstill">as a still, not a drawing</button>
          </div>
          <div class="mono" id="dstate" style="color:var(--ink-faint);margin-top:10px"></div>
        </div>
        <div style="align-self:start">
          <img id="dprev" style="width:100%;border-radius:8px;background:#2f3843">
          <textarea id="dspec" rows="12" class="mono" style="display:none;margin-top:10px"
            placeholder="paste a spec here"></textarea>
          <div class="row" style="margin-top:8px;display:none" id="dspecrow">
            <button class="btn sm ghost" id="dspecload">load that spec</button>
          </div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const q = (id) => wrap.querySelector(id);
  const close = () => { wrap.remove(); paintMedia(); };
  q('#dclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const showBlurb = () => {
    const k = kinds.find((x) => x.key === q('#dkind').value);
    q('#dblurb').textContent = k ? `${k.blurb} (${k.wants})` : '';
  };
  const current = () => linesToSpec(
    q('#dkind').value, q('#dtitle').value, q('#dnodes').value, q('#dedges').value,
    q('#dnote').value, spec.reveal || 'sequence');

  let timer = null;
  async function redraw() {
    const body = { spec: current(), accent: state.project.style.accent,
                   hand: state.project.style.board_hand || 'marker' };
    q('#dspec').value = JSON.stringify(body.spec, null, 2);
    try {
      const res = await fetch('/api/diagram/preview',
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json()).detail || 'no');
      const blob = await res.blob();
      const old = q('#dprev').src;
      q('#dprev').src = URL.createObjectURL(blob);
      if (old.startsWith('blob:')) URL.revokeObjectURL(old);
      q('#dstate').textContent = '';
    } catch (e) {
      q('#dstate').textContent = e.message;
    }
  }
  const nudge = () => { clearTimeout(timer); timer = setTimeout(redraw, 260); };
  ['#dkind', '#dtitle', '#dnodes', '#dedges', '#dnote'].forEach((id) => {
    q(id).oninput = nudge;
    q(id).onchange = () => { showBlurb(); nudge(); };
  });
  showBlurb();
  redraw();

  q('#djson').onclick = () => {
    const box = q('#dspec'), row = q('#dspecrow');
    const on = box.style.display === 'none';
    box.style.display = row.style.display = on ? '' : 'none';
    q('#djson').textContent = on ? 'hide the spec' : 'show the spec';
  };
  q('#dspecload').onclick = () => {
    let loaded;
    try { loaded = JSON.parse(q('#dspec').value); }
    catch (e) { return (q('#dstate').textContent = 'that is not valid JSON'); }
    q('#dkind').value = loaded.kind || 'flow';
    q('#dtitle').value = loaded.title || '';
    q('#dnote').value = loaded.note || '';
    const l = diagramToLines(loaded);
    q('#dnodes').value = l.nodes;
    q('#dedges').value = l.edges;
    showBlurb();
    redraw();
  };

  async function use(motion) {
    q('#dstate').textContent = 'drawing…';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/diagram`,
        { method: 'POST', body: JSON.stringify({ spec: current(), motion }) });
      Object.assign(s, r.slide);
      bumpBoards();
      toast(motion === 'still' ? 'drawn' : 'drawn — it inks in on screen');
      close();
    } catch (e) {
      q('#dstate').textContent = e.message;
    }
  }
  q('#duse').onclick = () => use('reveal');
  q('#dstill').onclick = () => use('still');

  q('#dask').onclick = async () => {
    const btn = q('#dask');
    btn.disabled = true;
    q('#daskstate').textContent = 'thinking…';
    try {
      const r = await api(`/api/projects/${state.project.id}/slides/${sid}/diagram/generate`,
        { method: 'POST', body: JSON.stringify({ instruction: q('#daskwhat').value.trim() }) });
      let j;
      for (;;) {
        j = await api(`/api/jobs/${r.job}`);
        if (j.state !== 'running') break;
        await new Promise((res) => setTimeout(res, 900));
      }
      if (j.state === 'error') throw new Error(j.error || 'Claude could not draw this one.');
      const loaded = j.result.spec;
      q('#dkind').value = loaded.kind || 'flow';
      q('#dtitle').value = loaded.title || '';
      q('#dnote').value = loaded.note || '';
      const l = diagramToLines(loaded);
      q('#dnodes').value = l.nodes;
      q('#dedges').value = l.edges;
      showBlurb();
      redraw();
      q('#daskstate').textContent = 'drawn from the narration — tweak anything, then use it';
    } catch (e) {
      q('#daskstate').textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  };
}

// A spec can legitimately carry a value this build doesn't know about — a
// newer size, an animation added server-side. Keeping it as an option means
// editing some other field can't silently rewrite it to the first one.
function customOptions(list, current) {
  const all = list.includes(current) || !current ? list : [...list, current];
  return all.map((v) => `<option ${v === current ? 'selected' : ''}>${esc(v)}</option>`).join('');
}

function blankCustomElement(type) {
  const base = { type, x: 0.1, y: 0.1, w: 0.4, h: 0.2, order: 0, anim: 'fade', opacity: 1 };
  if (type === 'text') {
    return { ...base, text: 'new text', size: 'lg', align: 'left',
             color: '#ffffff', font: 'hand' };
  }
  if (type === 'image') return { ...base, query: '', fit: 'cover' };
  return { ...base, color: '#E8C36A', fill: true, stroke: 4 };
}

// Opened against one paragraph (from the Media tab) or against nothing at all
// (the Video style picker's "Design a style…"). The editor is the same either
// way; what changes is where Claude's brief comes from — a paragraph to read,
// or only the words you type — and whether the result lands on a slide or in
// the style library.
function openCustomEditor(sid) {
  const s = state.project.slides.find((x) => x.id === sid);
  if (!s) return;
  openCustomDesigner({
    sid,
    slide: s,
    projectId: state.project.id,
    accent: state.project.style.accent,
    hand: state.project.style.board_hand || 'marker',
    spec: Object.keys(s.custom || {}).length
      ? JSON.parse(JSON.stringify(s.custom))
      : { background: '', reveal: 'sequence', elements: [] },
  });
}

// No project needed: this is how a style gets made from the home page, before
// there is a video to design it against.
function openStyleDesigner() {
  openCustomDesigner({
    styleMode: true,
    projectId: '',
    accent: (state.project && state.project.style.accent) || '#E8C36A',
    hand: (state.project && state.project.style.board_hand) || 'marker',
    spec: { background: '', reveal: 'sequence', elements: [] },
  });
}

function openCustomDesigner(opts) {
  const styleMode = !!opts.styleMode;
  const s = opts.slide;
  const sid = opts.sid;
  let spec = opts.spec;
  let htmlMode = !styleMode && !!s.custom_html;

  const wrap = document.createElement('div');
  wrap.className = 'modal';
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>${styleMode ? 'Design a video style' : 'Design a slide'}</strong>
        <div class="spacer"></div>
        ${styleMode ? '' : '<label><input type="checkbox" id="chtml"> HTML</label>'}
        <button class="btn sm ghost" id="cjson">show the spec</button>
        <button class="btn sm ghost" id="cclose">close</button>
      </div>
      <div class="grid-2">
        <div style="overflow:auto;max-height:calc(100vh - 160px);padding-right:16px">
          <div class="panel" style="background:#13151c;margin:0 0 16px;padding:14px">
            <div class="row" style="margin-bottom:8px">
              <span style="font-size:13px">✨ ${styleMode
                ? 'Describe the look you want' : 'Ask Claude to design this slide'}</span>
            </div>
            <textarea id="caskwhat" rows="2" style="margin-bottom:8px"
              placeholder="${styleMode
                ? 'e.g. “one huge number on near-black with a thin accent rule”, “a full-bleed photo with a quote over a dark scrim”, “three cards across the middle”…'
                : 'Leave blank to let Claude read the paragraph and design something, or steer it — “one huge number over a photo”, “three cards across the middle”, “a quote, big, on black”…'}"></textarea>
            <button class="btn sm" id="cask">design it for me</button>
            <span class="mono" id="caskstate" style="color:var(--ink-faint);margin-left:8px"></span>
          </div>
          ${styleMode ? `<div class="mono" style="color:var(--ink-faint);margin-bottom:12px">
            Every paragraph of the video gets this design, with its own words and
            pictures swapped into it. So write the text here as a placeholder
            showing what belongs in each slot, not as anything about one subject.</div>` : ''}
          <textarea id="chtmltext" rows="14" class="mono" style="display:none" aria-label="Slide HTML"></textarea>
          <div id="cjsoncontrols"><div class="row" style="margin-bottom:10px">
            <label class="field" style="flex:1;margin:0"><span>Background</span>
              <input type="text" id="cbg" placeholder="blank = the usual board"
                value="${esc(spec.background || '')}"></label>
          </div>
          <div id="cels"></div>
          <div class="row" style="margin:12px 0">
            <span class="mono" style="color:var(--ink-faint)">add:</span>
            <button class="btn xs ghost" data-add="text">text</button>
            <button class="btn xs ghost" data-add="rect">rect</button>
            <button class="btn xs ghost" data-add="circle">circle</button>
            <button class="btn xs ghost" data-add="line">line</button>
            <button class="btn xs ghost" data-add="image">image</button>
          </div>
          </div><div class="row">
            ${styleMode ? '' : `
              <button class="btn sm primary" id="cuse">use it on this slide</button>
              <button class="btn sm ghost" id="cstill">as a still, not animated</button>`}
            <button class="btn sm ${styleMode ? '' : 'ghost'}" id="csave"
              title="keep this design as a reusable video style">
              ${styleMode ? 'save this style' : 'save as a style…'}</button>
          </div>
          <div class="mono" id="cstate" style="color:var(--ink-faint);margin-top:10px"></div>
        </div>
        <div style="align-self:start">
          <img id="cprev" style="width:100%;border-radius:8px;background:#2f3843">
          <div class="mono" style="color:var(--ink-faint);margin-top:6px">
            ${styleMode
              ? 'Image slots stay empty here — each paragraph fetches its own picture when the video is written.'
              : 'Image elements only show here once they’ve been fetched — press “use it on this slide” to pull them from the archives.'}</div>
          <textarea id="cspec" rows="14" class="mono" style="display:none;margin-top:10px"></textarea>
          <div class="row" style="margin-top:8px;display:none" id="cspecrow">
            <button class="btn sm ghost" id="cspecload">load that spec</button>
          </div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);
  const q = (id) => wrap.querySelector(id);
  q('#chtmltext').value = s?.custom_html || '<section class="cb-slide"><h1 class="cb-title">Slide title</h1></section>';
  function paintMode() {
    q('#chtmltext').style.display = htmlMode ? '' : 'none';
    q('#cjsoncontrols').style.display = htmlMode ? 'none' : '';
    q('#csave').disabled = htmlMode;
    q('#cjson').disabled = htmlMode;
    q('#cspec').style.display = q('#cspecrow').style.display = 'none';
  }
  if (!styleMode) {
    q('#chtml').checked = htmlMode;
    q('#chtml').onchange = () => { htmlMode = q('#chtml').checked; paintMode(); nudge(); };
  }
  q('#chtmltext').oninput = () => nudge();
  // In style mode there is no Media tab behind this modal to repaint.
  const close = () => { wrap.remove(); if (!styleMode) paintMedia(); };
  q('#cclose').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };

  const num = (v) => Math.round((+v || 0) * 100) / 100;

  function paintElements() {
    q('#cels').innerHTML = spec.elements.map((el, i) => `
      <div class="panel" style="background:#13151c;margin:0 0 10px;padding:12px">
        <div class="row" style="margin-bottom:8px">
          <strong style="font-size:13px">${i + 1}. ${esc(el.type)}</strong>
          <div class="spacer"></div>
          <button class="btn xs ghost" data-up="${i}" ${i ? '' : 'disabled'}>↑</button>
          <button class="btn xs ghost danger" data-del="${i}">remove</button>
        </div>
        ${el.type === 'text' ? `
          <textarea rows="2" data-f="text" data-i="${i}"
            style="margin-bottom:8px">${esc(el.text || '')}</textarea>
          <div class="row" style="gap:6px;margin-bottom:8px">
            <select data-f="size" data-i="${i}" style="width:auto">
              ${customOptions(CUSTOM_SIZES, el.size)}
            </select>
            <select data-f="font" data-i="${i}" style="width:auto">
              ${customOptions(CUSTOM_FONTS, el.font)}
            </select>
            <select data-f="align" data-i="${i}" style="width:auto">
              ${customOptions(['left', 'center', 'right'], el.align)}
            </select>
            <input type="text" data-f="color" data-i="${i}" value="${esc(el.color || '#ffffff')}"
              style="width:90px">
          </div>` : ''}
        ${el.type === 'image' ? `
          <input type="text" data-f="query" data-i="${i}" placeholder="what to search the archives for"
            value="${esc(el.query || '')}" style="margin-bottom:8px">
          <div class="row" style="gap:6px;margin-bottom:8px">
            <select data-f="fit" data-i="${i}" style="width:auto">
              ${customOptions(['cover', 'contain'], el.fit)}
            </select>
            <span class="mono" style="color:var(--ink-faint)">
              ${el.local_path ? 'fetched' : 'not fetched yet'}</span>
          </div>` : ''}
        ${['rect', 'circle', 'line'].includes(el.type) ? `
          <div class="row" style="gap:6px;margin-bottom:8px">
            <input type="text" data-f="color" data-i="${i}" value="${esc(el.color || '#E8C36A')}"
              style="width:90px">
            <label class="row" style="gap:4px;cursor:pointer">
              <input type="checkbox" data-f="fill" data-i="${i}" style="width:auto"
                ${el.fill ? 'checked' : ''}><span class="mono">filled</span></label>
            <input type="number" data-f="stroke" data-i="${i}" value="${el.stroke || 4}"
              min="1" max="20" style="width:70px" title="stroke width">
          </div>` : ''}
        <div class="row" style="gap:6px">
          ${['x', 'y', 'w', 'h'].map((f) => `
            <label class="mono" style="color:var(--ink-faint)">${f}
              <input type="number" data-f="${f}" data-i="${i}" value="${num(el[f])}"
                step="0.01" min="0" max="1" style="width:74px"></label>`).join('')}
        </div>
        <div class="row" style="gap:6px;margin-top:8px">
          <label class="mono" style="color:var(--ink-faint)">order
            <input type="number" data-f="order" data-i="${i}" value="${el.order || 0}"
              min="0" max="20" style="width:66px"></label>
          <select data-f="anim" data-i="${i}" style="width:auto">
            ${customOptions(CUSTOM_ANIMS, el.anim)}
          </select>
          <label class="mono" style="color:var(--ink-faint)">opacity
            <input type="number" data-f="opacity" data-i="${i}"
              value="${el.opacity === undefined ? 1 : el.opacity}"
              step="0.05" min="0" max="1" style="width:74px"></label>
        </div>
      </div>`).join('') || '<div class="empty-note">No elements yet — ask Claude, or add one below.</div>';

    q('#cels').querySelectorAll('[data-f]').forEach((input) => {
      const i = +input.dataset.i, f = input.dataset.f;
      const handler = () => {
        const el = spec.elements[i];
        if (input.type === 'checkbox') el[f] = input.checked;
        else if (input.type === 'number') el[f] = +input.value;
        else el[f] = input.value;
        if (['fill', 'size', 'font', 'align', 'fit', 'anim'].includes(f)) paintElements();
        nudge();
      };
      input.oninput = handler;
      input.onchange = handler;
    });
    q('#cels').querySelectorAll('[data-del]').forEach((b) => {
      b.onclick = () => { spec.elements.splice(+b.dataset.del, 1); paintElements(); nudge(); };
    });
    q('#cels').querySelectorAll('[data-up]').forEach((b) => {
      b.onclick = () => {
        const i = +b.dataset.up;
        [spec.elements[i - 1], spec.elements[i]] = [spec.elements[i], spec.elements[i - 1]];
        paintElements();
        nudge();
      };
    });
  }

  wrap.querySelectorAll('[data-add]').forEach((b) => {
    b.onclick = () => {
      spec.elements.push(blankCustomElement(b.dataset.add));
      paintElements();
      nudge();
    };
  });
  q('#cbg').oninput = () => { spec.background = q('#cbg').value; nudge(); };

  let timer = null;
  async function redraw() {
    q('#cspec').value = JSON.stringify(spec, null, 2);
    if (!htmlMode && !spec.elements.length) { q('#cstate').textContent = ''; return; }
    try {
      const res = await fetch('/api/custom/preview',
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...(htmlMode ? {custom_html: q('#chtmltext').value, slide_id: sid} : {spec}), project_id: opts.projectId || '',
                                 hand: opts.hand }) });
      if (!res.ok) throw new Error((await res.json()).detail || 'no');
      const blob = await res.blob();
      const old = q('#cprev').src;
      q('#cprev').src = URL.createObjectURL(blob);
      if (old.startsWith('blob:')) URL.revokeObjectURL(old);
      q('#cstate').textContent = '';
    } catch (e) {
      q('#cstate').textContent = e.message;
    }
  }
  const nudge = () => { clearTimeout(timer); timer = setTimeout(redraw, 300); };

  q('#cjson').onclick = () => {
    const box = q('#cspec'), row = q('#cspecrow');
    const on = box.style.display === 'none';
    box.style.display = row.style.display = on ? '' : 'none';
    q('#cjson').textContent = on ? 'hide the spec' : 'show the spec';
  };
  q('#cspecload').onclick = () => {
    let loaded;
    try { loaded = JSON.parse(q('#cspec').value); }
    catch { return (q('#cstate').textContent = 'that is not valid JSON'); }
    spec = loaded;
    q('#cbg').value = spec.background || '';
    paintElements();
    redraw();
  };

  async function use(motion) {
    if (!htmlMode && !spec.elements.length) return (q('#cstate').textContent = 'nothing to draw yet');
    q('#cstate').textContent = 'drawing…';
    try {
      const r = await api(`/api/projects/${opts.projectId}/slides/${sid}/custom`,
        { method: 'POST', body: JSON.stringify({ ...(htmlMode ? {custom_html: q('#chtmltext').value} : {spec}), motion }) });
      let j;
      for (;;) {
        j = await api(`/api/jobs/${r.job}`);
        if (j.state !== 'running') break;
        q('#cstate').textContent = j.message || 'drawing…';
        await new Promise((res) => setTimeout(res, 900));
      }
      if (j.state === 'error') throw new Error(j.error || 'Could not draw that slide.');
      Object.assign(s, j.result.slide);
      bumpBoards();
      toast(motion === 'still' ? 'designed' : 'designed — it builds on screen');
      close();
    } catch (e) {
      q('#cstate').textContent = e.message;
    }
  }
  if (!styleMode) {
    q('#cuse').onclick = () => use('reveal');
    q('#cstill').onclick = () => use('still');
  }

  q('#csave').onclick = async () => {
    if (!spec.elements.length) return (q('#cstate').textContent = 'nothing to save yet');
    const name = prompt('Name this style\n(it joins Documentary, Video essay and '
      + 'Handwritten board in the Video style picker)', 'My slide style');
    if (!name) return;
    q('#cstate').textContent = 'saving…';
    try {
      await api('/api/slide-styles', { method: 'POST',
        body: JSON.stringify({ spec, name, hand: opts.hand }) });
      state.slideStyles = null;
      await ensureSlideStyles();
      toast(`saved — “${name}” is now a video style`);
      q('#cstate').textContent = '';
      // Made from the picker: close back onto it so the new tile is right there.
      if (styleMode) { close(); route(); }
    } catch (e) {
      q('#cstate').textContent = e.message;
    }
  };

  q('#cask').onclick = async () => {
    const btn = q('#cask');
    btn.disabled = true;
    q('#caskstate').textContent = 'designing…';
    try {
      const brief = q('#caskwhat').value.trim();
      // With no project there is no paragraph to read, so the brief is the
      // whole input and a different endpoint answers it.
      const r = styleMode
        ? await api('/api/slide-styles/design',
            { method: 'POST', body: JSON.stringify({ description: brief,
                                                     accent: opts.accent }) })
        : await api(`/api/projects/${opts.projectId}/slides/${sid}/custom/generate`,
            { method: 'POST', body: JSON.stringify({ instruction: brief, html: htmlMode }) });
      let j;
      for (;;) {
        j = await api(`/api/jobs/${r.job}`);
        if (j.state !== 'running') break;
        await new Promise((res) => setTimeout(res, 900));
      }
      if (j.state === 'error') throw new Error(j.error || 'Claude could not design this one.');
      if ('custom_html' in j.result) q('#chtmltext').value = j.result.custom_html;
      else spec = j.result.spec;
      q('#cbg').value = spec.background || '';
      paintElements();
      redraw();
      q('#caskstate').textContent = styleMode
        ? 'drawn — tweak anything, then save it as a style'
        : 'designed from the narration — tweak anything, then use it';
    } catch (e) {
      q('#caskstate').textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  };

  paintElements();
  paintMode();
  redraw();
}

async function gatherMedia() {
  const r = await api(`/api/projects/${state.project.id}/media`,
    { method: 'POST', body: JSON.stringify({}) });
  watchJob(r.job, 'media');
  render();
}

/* Sparse block settings. A sheet owns one in-flight request and one latest draft. */
function blockThemePanel() {
  return '<section class="panel block-theme" id="block-theme" aria-label="Block theme"><h3>Block theme</h3><p role="status">Loading block theme…</p></section>';
}

async function mountBlockTheme(scope, id) {
  const host = $('#block-theme');
  if (!host) return;
  try {
    const data = await api(`/api/blocks/theme?scope=${scope}&id=${encodeURIComponent(id)}`);
    if (!host.isConnected) return;
    const draft = {}, session = `theme-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let sequence = 0, busy = false, pending = false, timer;
    const label = key => ({bg:'Background', ink:'Text', accent:'Accent', accent2:'Second accent', panel:'Panel',
      line:'Rule line', dim:'Muted text', font_display:'Title font', font_body:'Body font', radius:'Corner radius',
      weight:'Title weight', pace:'Animation pace'})[key] || key.replaceAll('_',' ');
    const colors = ['bg','ink','accent','accent2','panel','line','dim'];
    const faces = Object.keys(data.fonts);
    // Local font files only; option previews use the same faces as the blocks.
    for (const [name,url] of Object.entries(data.fonts)) {
      const face = new FontFace(name, `url("${url}")`);
      face.load().then(f => document.fonts.add(f)).catch(() => {});
    }
    host.innerHTML = `<h3>Block theme</h3><label for="block-theme-start">Start from a theme</label>
      <select id="block-theme-start"><option value="">Choose colours</option>${data.themes.map(t => `<option value="${esc(t.key)}">${esc(t.label)}</option>`).join('')}</select>
      <div class="block-theme-fields">${Object.entries(data.tokens).map(([key,token]) => {
        const field = `block-token-${key}`, value = token.value;
        const control = colors.includes(key) ? `<input type="color" id="${field}" value="${esc(value || '#16181C')}" aria-label="${esc(label(key))}"><output data-hex="${key}" class="mono">${esc(value || 'Derived')}</output>`
          : key.startsWith('font_') || key === 'weight' ? `<select id="${field}">${['',...(key === 'weight' ? ['regular','bold','heavy'] : faces)].map(v => `<option value="${esc(v)}" ${v === value ? 'selected' : ''} ${key.startsWith('font_') && v ? `style="font-family:'${esc(v)}'"` : ''}>${esc(v || 'Family default')}</option>`).join('')}</select>`
          : `<input type="range" id="${field}" min="${key === 'pace' ? '.7' : '0'}" max="${key === 'pace' ? '1.4' : '32'}" step="${key === 'pace' ? '.05' : '1'}" value="${value}"><output class="mono" data-number="${key}">${value}</output>`;
        return `<div class="block-theme-token"><label for="${field}">${esc(label(key))}</label><div class="row">${control}</div>
          <div class="row"><small data-source="${key}">${esc(token.source)}</small><button type="button" class="btn sm ghost" data-reset-token="${key}">Reset</button>${scope === 'project' ? `<button type="button" class="btn sm ghost" data-override-token="${key}" ${token.source === 'project' ? 'hidden' : ''}>Override here</button>` : ''}</div>
          <small class="block-theme-warning" data-warning="${key}">${esc(token.warning || '')}</small></div>`;
      }).join('')}</div><button type="button" class="btn sm" id="block-theme-save">Save block theme</button>
      <p role="status" aria-live="polite" id="block-theme-status"></p><div class="block-theme-sheet"></div>`;
    const status = host.querySelector('#block-theme-status');
    const update = tokens => {
      data.tokens = tokens;
      for (const [key,token] of Object.entries(tokens)) {
        host.querySelector(`[data-source="${key}"]`).textContent = token.source;
        host.querySelector(`[data-warning="${key}"]`).textContent = token.warning || '';
        const hex = host.querySelector(`[data-hex="${key}"]`);
        if (hex) hex.textContent = token.value || 'Derived';
        const number = host.querySelector(`[data-number="${key}"]`);
        if (number) number.textContent = token.value;
        host.querySelector(`[data-override-token="${key}"]`)?.toggleAttribute('hidden', token.source === 'project');
      }
    };
    const refresh = async () => {
      pending = true;
      if (busy) return;
      busy = true;
      while (pending && host.isConnected) {
        pending = false;
        const version = sequence;
        status.textContent = 'Refreshing block sheet…';
        try {
          const result = await api('/api/blocks/theme-sheet', {method:'POST',body:JSON.stringify({scope,id,overrides:{...draft},session,sequence:version})});
          if (!host.isConnected || version !== sequence || result.stale) continue;
          update(result.tokens);
          for (const key of Object.keys(draft)) if (draft[key] === null) {
            host.querySelector(`#block-token-${key}`).value = result.tokens[key].value || (colors.includes(key) ? '#16181C' : '');
          }
          host.querySelector('.block-theme-sheet').innerHTML = result.posters.map(p => `<button type="button" class="btn" data-sheet-ref="${esc(p.ref)}"><img src="${esc(p.url)}" alt="${esc(p.name)}"><span>${esc(p.name)}</span></button>`).join('');
          host.querySelectorAll('[data-sheet-ref]').forEach(button => { button.onclick = async () => {
            try {
              const items = await api('/api/blocks');
              const poster = result.posters.find(p => p.ref === button.dataset.sheetRef);
              openBlockPreview(items.find(b => b.ref === poster.ref),poster.aspect,poster.values,
                {theme_context:{scope,owner:id,overrides:{...draft}}});
            } catch (e) { status.textContent = e.message; }
          }; });
          status.textContent = result.disabled ? 'Block posters disabled for snapshots.' : Object.keys(draft).length ? 'Preview ready. Changes are unsaved.' : 'Preview ready.';
        } catch (e) { if (version === sequence) status.textContent = e.message; }
      }
      busy = false;
    };
    const changed = () => { sequence++; clearTimeout(timer); timer = setTimeout(refresh,300); };
    for (const key of Object.keys(data.tokens)) {
      const input = host.querySelector(`#block-token-${key}`);
      input.oninput = () => {
        draft[key] = ['radius','pace'].includes(key) ? Number(input.value) : input.value;
        const out = input.parentElement.querySelector('output');
        if (out) out.textContent = input.value;
        changed();
      };
      host.querySelector(`[data-reset-token="${key}"]`).onclick = () => { draft[key] = null; changed(); };
      const override = host.querySelector(`[data-override-token="${key}"]`);
      if (override) override.onclick = () => { draft[key] = data.tokens[key].value; changed(); };
    }
    host.querySelector('#block-theme-start').onchange = e => {
      const theme = data.themes.find(t => t.key === e.target.value);
      if (!theme) return;
      for (const key of colors.slice(0,4)) {
        draft[key] = theme[key === 'bg' ? 'ground' : key];
        host.querySelector(`#block-token-${key}`).value = draft[key];
      }
      changed();
    };
    host.querySelector('#block-theme-save').onclick = async e => {
      const edits = {...draft}; e.target.disabled = true;
      try {
        const result = await api('/api/blocks/theme',{method:'PATCH',body:JSON.stringify({scope,id,overrides:edits})});
        const owner = scope === 'channel' ? state.channel : state.project;
        if (owner?.id === id) {
          owner.style.block_theme ||= {};
          for (const [key,value] of Object.entries(edits)) {
            if (value === null) delete owner.style.block_theme[key]; else owner.style.block_theme[key] = value;
          }
        }
        for (const [key,value] of Object.entries(edits)) if (draft[key] === value) delete draft[key];
        themedPosterCache.clear();
        update(result.tokens); status.textContent = 'Block theme saved.';
      } catch (error) { status.textContent = error.message; }
      finally { e.target.disabled = false; }
    };
    await refresh();
  } catch (e) { if (host.isConnected) host.querySelector('[role=status]').textContent = e.message; }
}


// --------------------------------------------------------------- thumbnail
// The thumbnail is drawn server-side by Pillow and shown here as a plain jpeg:
// no canvas, no second implementation of the layout to keep in step with the
// renderer. Every change saves, redraws and swaps the preview's src.
function thumbArt(key, accent) {
  const a = esc(accent), ink = '#c9cdd6', dim = '#3a4150', photo = '#2a2f3a';
  const svg = {
    loupe: `<rect width="160" height="90" fill="#16181e"/>
      <circle cx="112" cy="45" r="30" fill="#2a2f3a"/>
      <circle cx="112" cy="45" r="26" fill="${photo}"/>
      ${Array.from({length: 22}, (_, n) => {
        const r = n * 360 / 22 * Math.PI / 180;
        return `<line x1="${112 + Math.cos(r) * 27}" y1="${45 + Math.sin(r) * 27}"
                      x2="${112 + Math.cos(r) * 32}" y2="${45 + Math.sin(r) * 32}"
                      stroke="${a}" stroke-width="2.6"/>`;
      }).join('')}
      <circle cx="112" cy="45" r="27" fill="none" stroke="${a}" stroke-width="2"/>
      <path d="M 96 30 A 22 22 0 0 0 92 48" fill="none" stroke="#fff"
        stroke-width="3" opacity=".45"/>
      <rect x="12" y="24" width="26" height="3" fill="${a}"/>
      <rect x="12" y="34" width="62" height="10" fill="${ink}"/>
      <rect x="12" y="48" width="48" height="10" fill="${ink}"/>
      <rect x="12" y="64" width="20" height="3" fill="${a}"/>`,
    banner: `<rect width="160" height="90" fill="${photo}"/>
      <rect y="46" width="160" height="44" fill="#0c0d11" opacity=".82"/>
      <rect x="10" y="56" width="10" height="4" fill="${a}"/>
      <rect x="26" y="56" width="34" height="3" fill="${ink}" opacity=".55"/>
      <rect x="10" y="65" width="120" height="9" fill="${ink}"/>
      <rect x="10" y="77" width="72" height="9" fill="${ink}"/>`,
    split: `<rect width="160" height="90" fill="#12141a"/>
      <rect x="88" width="72" height="90" fill="${photo}"/>
      <rect x="86" width="3" height="90" fill="${a}"/>
      <rect x="10" y="22" width="8" height="4" fill="${a}"/>
      <rect x="22" y="22" width="30" height="3" fill="${ink}" opacity=".55"/>
      <rect x="10" y="34" width="66" height="9" fill="${ink}"/>
      <rect x="10" y="46" width="52" height="9" fill="${ink}"/>
      <rect x="10" y="62" width="20" height="3" fill="${a}"/>`,
    spotlight: `<rect width="160" height="90" fill="#111318"/>
      <ellipse cx="104" cy="44" rx="34" ry="30" fill="${photo}"/>
      <ellipse cx="104" cy="44" rx="22" ry="19" fill="#4b525f"/>
      <rect x="10" y="12" width="44" height="12" rx="3" fill="${a}"/>
      <rect x="12" y="34" width="86" height="11" fill="${a}" opacity=".85"/>
      <rect x="10" y="32" width="86" height="11" fill="#fff"/>
      <rect x="12" y="50" width="58" height="11" fill="${a}" opacity=".85"/>
      <rect x="10" y="48" width="58" height="11" fill="#fff"/>`,
    medallion: `<rect width="160" height="90" fill="#1b1e25"/>
      <circle cx="116" cy="45" r="33" fill="${photo}" stroke="${a}" stroke-width="3"/>
      <rect x="12" y="26" width="30" height="3" fill="${a}"/>
      <rect x="12" y="36" width="62" height="8" fill="${ink}"/>
      <rect x="12" y="48" width="48" height="8" fill="${ink}"/>
      <rect x="12" y="63" width="20" height="3" fill="${a}"/>`,
    diagonal: `<rect width="160" height="90" fill="#0f1116"/>
      <path d="M74 0H160V90H100Z" fill="${photo}"/>
      <path d="M70 0h6l26 90h-6z" fill="${a}"/>
      <rect x="10" y="24" width="28" height="3" fill="${a}"/>
      <rect x="10" y="34" width="50" height="10" fill="${ink}"/>
      <rect x="10" y="48" width="38" height="10" fill="${ink}"/>`,
    sticker: `<rect width="160" height="90" fill="#1b0f3a"/>
      ${[0, 1, 2, 3, 4].map((r) => [0, 1, 2, 3, 4, 5].map((c) => `<rect
        x="${c * 28 + (r % 2 ? 6 : -8)}" y="${r * 19 + 3}" width="8" height="6" rx="2"
        fill="${c % 2 ? a : ink}" opacity=".24"/>`).join('')).join('')}
      <path d="M86 0h74v90H86z" fill="${photo}" opacity=".9"/>
      <rect x="10" y="12" width="34" height="11" rx="5" fill="${a}"/>
      ${[32, 48, 64].map((y) => `<rect x="7" y="${y - 3}" width="${y === 64 ? 52 : 70}"
        height="18" fill="${a}"/>
        <rect x="10" y="${y}" width="${y === 64 ? 46 : 64}" height="12" fill="#fff"/>`).join('')}`,
    duotone: `<rect width="160" height="90" fill="${a}"/>
      <rect width="160" height="52" fill="#e8663f"/>
      <path d="M0 34l30-14 26 12 30-18 32 16 42-10v34H0z" fill="#c0245a" opacity=".7"/>
      <rect y="52" width="160" height="38" fill="#180a12"/>
      <rect y="50" width="160" height="3" fill="${a}"/>
      <rect x="10" y="8" width="38" height="12" fill="${a}"/>
      <rect x="10" y="60" width="130" height="10" fill="${ink}"/>
      <rect x="10" y="74" width="86" height="10" fill="${ink}"/>`,
    gloss: `<rect width="160" height="90" fill="#f6dce6"/>
      <ellipse cx="112" cy="45" rx="52" ry="44" fill="#fdeef4"/>
      <circle cx="112" cy="45" r="33" fill="${photo}" opacity=".85"/>
      <circle cx="112" cy="45" r="35" fill="none" stroke="${a}" stroke-width="2"/>
      <rect x="12" y="22" width="26" height="4" fill="${a}"/>
      <rect x="12" y="34" width="58" height="10" fill="#3a2a31"/>
      <rect x="12" y="48" width="46" height="10" fill="#3a2a31"/>
      <rect x="12" y="66" width="24" height="2.6" fill="${a}"/>`,
    scoreline: `<rect width="160" height="90" fill="${photo}"/>
      <path d="M0 24l160-18v54L0 78z" fill="#0d1c2e" opacity=".95"/>
      <path d="M0 22l160-18v4L0 26z" fill="${a}"/>
      <path d="M0 60l160-18v4L0 64z" fill="${a}"/>
      <g transform="rotate(-6.5 80 45)">
        <rect x="26" y="16" width="40" height="9" fill="${a}"/>
        <rect x="26" y="32" width="104" height="12" fill="#fff"/>
        <rect x="26" y="48" width="72" height="12" fill="#fff"/></g>`,
    tiles: `<rect width="160" height="90" fill="#1a1c22"/>
      <rect x="90" width="70" height="90" fill="${photo}"/>
      ${[0, 1, 2, 3].map((r) => [0, 1, 2].map((c) => `<rect x="${c * 30 + 1}"
        y="${r * 23 + 1}" width="28" height="21"
        fill="${(r + c) % 2 ? '#2b3340' : '#232a34'}"/>`).join('')).join('')}
      <rect x="8" y="24" width="76" height="42" rx="3" fill="#0f1116"
        stroke="${a}" stroke-width="1.8"/>
      <rect x="28" y="31" width="36" height="4" fill="${a}"/>
      <rect x="16" y="40" width="60" height="9" fill="${ink}"/>
      <rect x="26" y="52" width="40" height="9" fill="${ink}"/>`,
    poster: `<rect width="160" height="90" fill="#eee9de"/>
      <rect x="8" y="7" width="144" height="40" fill="${photo}"/>
      <rect x="8" y="7" width="144" height="40" fill="none" stroke="#26231f" stroke-width="1"/>
      <rect x="56" y="54" width="48" height="3" fill="#26231f" opacity=".5"/>
      <rect x="30" y="62" width="100" height="10" fill="#26231f"/>
      <rect x="44" y="80" width="28" height="1.6" fill="${a}"/>
      <rect x="88" y="80" width="28" height="1.6" fill="${a}"/>
      <path d="M80 77l4 3.8-4 3.8-4-3.8z" fill="${a}"/>`,
  }[key] || '<rect width="160" height="90" fill="#14151a"/>';
  return `<svg class="tpl-art thumb-art" viewBox="0 0 160 90" preserveAspectRatio="none">${svg}</svg>`;
}

async function paintThumb() {
  const p = state.project;
  const t = p.thumb || {};
  const styles = state.thumbStyles || [];
  const meta = styles.find((s) => s.key === t.template) || styles[0] || {};
  const src = t.image ? `/api/projects/${p.id}/file/${t.image}?v=${t.rendered_at || 0}` : '';
  const credit = t.credit || {};

  $('#tabbody').innerHTML = `
    <div class="thumb-wrap">
      <div>
        <div class="thumb-stage">
          ${t.rendered_at
            ? `<img id="thumbimg" src="/api/projects/${p.id}/file/thumb/thumb.jpg?v=${t.rendered_at}">`
            : `<div class="empty-note" id="thumbimg">Cooking up a thumbnail…</div>`}
        </div>
        <div class="row" style="margin-top:10px">
          <span class="mono" id="thumbsize" style="color:var(--ink-faint)">1280×720</span>
          <div class="spacer"></div>
          ${t.image ? `<button class="btn sm ghost" onclick="thumbFocal()">
            ${(t.focal || []).length === 2 ? '✛ focus set' : 'set focus point'}</button>` : ''}
          <a class="btn sm primary" download="thumbnail.jpg"
             href="/api/projects/${p.id}/file/thumb/thumb.jpg?v=${t.rendered_at || 0}">download</a>
        </div>
        <div class="mono thumb-credit">
          ${t.image
            ? `${esc(credit.provider || 'local')}${credit.author ? ' · ' + esc(credit.author) : ''}
               ${credit.source_page ? `· <a href="${esc(credit.source_page)}" target="_blank">source</a>` : ''}
               <br>${esc((credit.license || '').slice(0, 80))}`
            : 'No picture yet — pick one below and it appears here.'}
        </div>
      </div>

      <div>
        <div class="row" style="margin-bottom:10px">
          <strong>Picture</strong>
          <div class="spacer"></div>
          <button class="btn sm" onclick="openThumbPicker()">choose a picture…</button>
          <label class="btn sm ghost" style="cursor:pointer">upload
            <input type="file" accept="image/*" hidden onchange="uploadThumbImage(this.files[0])"></label>
        </div>

        <label class="field"><span>Headline — a few words, not the title again</span>
          <textarea id="thumbhead" rows="2" placeholder="${esc((p.title || p.idea || '').slice(0, 50))}"
            oninput="saveThumb({headline:this.value})">${esc(t.headline || '')}</textarea></label>
        <div class="row" style="margin:-6px 0 14px">
          <input type="text" id="thumbkick" style="flex:1" placeholder="kicker — optional, one or two words"
            value="${esc(t.kicker || '')}" oninput="saveThumb({kicker:this.value})">
          <button class="btn sm" onclick="suggestHeadlines()">write me some</button>
        </div>
        <div id="thumbopts"></div>

        <div class="tpl-strip">
          ${styles.map((s) => `
            <div class="tpl ${s.key === t.template ? 'sel' : ''}"
                 onclick="saveThumb({template:'${s.key}'}, true)">
              ${thumbArt(s.key, t.accent || p.style.accent)}
              <div class="tpl-name">${esc(s.label)}</div>
            </div>`).join('')}
        </div>
        <div class="mono" style="color:var(--ink-faint);margin:-8px 0 16px">
          ${esc(meta.blurb || '')}</div>

        <div class="grid-2">
          <label class="field"><span>Text size — <b>${(t.text_scale || 1).toFixed(2)}×</b></span>
            <input type="range" min="0.7" max="1.35" step="0.05" value="${t.text_scale || 1}"
              onchange="saveThumb({text_scale:+this.value}, true)"></label>
          <label class="field"><span>Picture knocked back — <b>${Math.round((t.dim ?? 0.55) * 100)}%</b></span>
            <input type="range" min="0" max="0.95" step="0.05" value="${t.dim ?? 0.55}"
              onchange="saveThumb({dim:+this.value}, true)"></label>
        </div>
        <div class="row" style="gap:16px;margin-bottom:14px">
          <label class="row" style="gap:7px;cursor:pointer">
            <input type="checkbox" style="width:auto" ${t.uppercase ? 'checked' : ''}
              onchange="saveThumb({uppercase:this.checked}, true)"><span>Set in capitals</span></label>
          ${meta.flip ? `<label class="row" style="gap:7px;cursor:pointer">
            <input type="checkbox" style="width:auto" ${t.flip ? 'checked' : ''}
              onchange="saveThumb({flip:this.checked}, true)"><span>Mirror the layout</span></label>` : ''}
          <div class="spacer"></div>
          <label class="row" style="gap:7px">
            <span class="mono" style="color:var(--ink-faint)">accent</span>
            <input type="text" style="width:110px" value="${esc(t.accent || p.style.accent)}"
              onchange="saveThumb({accent:this.value}, true)"></label>
        </div>
      </div>
    </div>`;

  if (!t.rendered_at) renderThumb();
}

function saveThumb(patch, repaint = false) {
  const p = state.project;
  Object.assign(p.thumb, patch);
  Object.assign(thumbPending, patch);
  if (repaint) paintThumb();
  clearTimeout(thumbTimer);
  thumbTimer = setTimeout(async () => {
    const body = thumbPending;
    thumbPending = {};
    try {
      const r = await api(`/api/projects/${p.id}`,
        { method: 'PATCH', body: JSON.stringify({ thumb: body }) });
      p.thumb = r.thumb;
      await renderThumb();
    } catch (e) { toast(e.message, true); }
  }, 300);
}

async function renderThumb() {
  const p = state.project;
  try {
    const r = await api(`/api/projects/${p.id}/thumb/render`, { method: 'POST' });
    p.thumb = r.thumb;
    const stage = $('.thumb-stage');
    if (!stage) return;
    const url = `/api/projects/${p.id}/file/${r.path}?v=${r.rendered_at}`;
    stage.innerHTML = `<img id="thumbimg" src="${url}">`;
    const size = $('#thumbsize');
    if (size) size.textContent = `1280×720 · ${Math.round(r.bytes / 1024)} KB`;
    const dl = $('a[download="thumbnail.jpg"]');
    if (dl) dl.href = url;
  } catch (e) { toast(e.message, true); }
}

function thumbFocal() {
  const p = state.project, t = p.thumb;
  if (!t.image) return;
  openFocal(`/api/projects/${p.id}/file/${t.image}`, t.focal, (focal) => {
    saveThumb({ focal }, true);
  });
}

async function uploadThumbImage(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await api(`/api/projects/${state.project.id}/thumb/upload`, { method: 'POST', body: fd });
    state.project.thumb = r.thumb;
    paintThumb();
    toast('picture set');
  } catch (e) { toast(e.message, true); }
}

async function suggestHeadlines() {
  const r = await api(`/api/projects/${state.project.id}/thumb/headlines`, { method: 'POST' });
  watchJob(r.job, 'headlines', (done) => {
    const options = ((done && done.result) || {}).options || [];
    const box = $('#thumbopts');
    if (!box || !options.length) return;
    box.innerHTML = `<div class="head-opts">
      ${options.map((o, i) => `<button class="head-opt" onclick="useHeadline(${i})">
          ${o.kicker ? `<span class="mono">${esc(o.kicker)}</span>` : ''}
          <strong>${esc(o.headline)}</strong></button>`).join('')}
    </div>`;
    state.headlines = options;
  });
}

function useHeadline(i) {
  const o = (state.headlines || [])[i];
  if (!o) return;
  saveThumb({ headline: o.headline, kicker: o.kicker || '' }, true);
}

// Every picture in the project, plus the archives, in one panel.
function openThumbPicker() {
  const p = state.project;
  const wrap = document.createElement('div');
  wrap.className = 'modal';
  const mine = [];
  p.slides.forEach((s, i) => {
    const c = s.candidates.find((x) => x.id === s.chosen_id);
    if (c && c.kind !== 'video') mine.push({ ...c, _slide: i + 1 });
  });
  wrap.innerHTML = `
    <div class="modal-box wide">
      <div class="row" style="margin-bottom:12px">
        <strong>Choose the thumbnail picture</strong>
        <div class="spacer"></div>
        <button class="btn sm ghost" id="tpdone">done</button>
      </div>
      <div class="row" style="margin-bottom:12px">
        <input type="text" id="tpq" style="flex:1;min-width:220px"
          placeholder="search the archives for something better…"
          value="${esc(p.title || p.idea || '')}">
        <button class="btn sm primary" id="tpgo">search</button>
      </div>
      <div class="mono" id="tpnote" style="color:var(--ink-faint);margin-bottom:10px"></div>
      <div class="pick-grid" id="tpres"></div>
    </div>`;
  document.body.appendChild(wrap);

  const q = wrap.querySelector('#tpq');
  const go = wrap.querySelector('#tpgo');
  const note = wrap.querySelector('#tpnote');
  const res = wrap.querySelector('#tpres');
  let shown = [];

  const paint = (list, label) => {
    shown = list;
    note.textContent = label;
    res.innerHTML = list.map((c, i) => `
      <div class="pick" data-i="${i}" title="${esc(c.title)}">
        <img src="${thumbUrl(c)}" loading="lazy" onerror="this.parentNode.style.opacity=.25">
        <div class="pick-meta">
          <span>${esc(c._slide ? 'slide ' + c._slide : c.provider)}</span>
          <span>${c.width || '?'}×${c.height || '?'}</span>
        </div>
      </div>`).join('') || '<div class="empty-note">nothing to show yet — go fish</div>';
    res.querySelectorAll('.pick').forEach((el) => {
      el.onclick = async () => {
        el.classList.add('sel');
        note.textContent = 'fetching the full-size picture…';
        try {
          const r = await api(`/api/projects/${p.id}/thumb/pick`,
            { method: 'POST', body: JSON.stringify({ candidate: shown[+el.dataset.i] }) });
          p.thumb = r.thumb;
          close();
          toast('picture set');
        } catch (e) { toast(e.message, true); note.textContent = 'that one could not be fetched'; }
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
      const r = await api(`/api/projects/${p.id}/thumb/search`,
        { method: 'POST', body: JSON.stringify({ query }) });
      paint(r.results || [], `${(r.results || []).length} from the archives`);
    } catch (e) { toast(e.message, true); note.textContent = e.message || 'that search failed'; }
    go.disabled = q.disabled = false;
  };

  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const close = () => { document.removeEventListener('keydown', onKey); wrap.remove(); paintThumb(); };
  document.addEventListener('keydown', onKey);
  wrap.querySelector('#tpdone').onclick = close;
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  go.onclick = run;
  q.onkeydown = (e) => { if (e.key === 'Enter') run(); };

  paint(mine, mine.length
    ? `${mine.length} already in this video — or search for something else`
    : 'this video has no pictures yet; search the archives');
}

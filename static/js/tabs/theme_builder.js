/* The theme builder: make a channel theme from four colours, a pattern and
   its icons, with a live sample beside the controls. Saved themes join the
   theme strip for every channel. */
let themeDraft = null;
let themeOptions = null;
let themeSampleTimer = 0;
let themeSampleUrl = '';

const THEME_COLOURS = [['accent', 'Main colour'], ['accent2', 'Second colour'], ['ground', 'Background'], ['ink', 'Text']];
const THEME_PATTERNS = {icons: 'Icons', stripes: 'Stripes', words: 'Channel name', halftone: 'Dots'};
const THEME_GRADES = {warm: 'Warm', neutral: 'Neutral', cool: 'Cool', mono: 'Black and white'};

function themeContrast(a, b) {
  const lum = hex => {
    const v = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

async function themeBuilderOpen(key = '') {
  const c = state.channel;
  if (!c) return;
  try { themeOptions = themeOptions || await api('/api/themes/options'); }
  catch (e) { return toast(e, true); }
  const list = state.themes || [];
  const source = list.find(t => t.key === (key || c.style.theme)) || list[0] || {};
  themeDraft = {
    key, label: key ? source.label : '', for: key ? source.for : '', blurb: key ? source.blurb : '',
    // A new theme starts from how this channel looks now, so small changes are quick.
    accent: key ? source.accent : c.style.accent || source.accent,
    accent2: key ? source.accent2 : c.style.accent2 || source.accent2,
    ground: source.ground, ink: source.ink,
    grade: key ? source.grade : c.style.grade || source.grade,
    pattern: source.pattern, icons: [...(source.icons || [])].slice(0, themeOptions.max_icons),
    intro: key ? source.intro : c.intro.template, thumb: key ? source.thumb : c.thumb_template,
    outro: key ? source.outro : c.outro.template,
    blocks: {radius: 0, panel_opacity: 1, border: 0, font_display: '', weight: '',
      ...(key ? source.blocks : Object.fromEntries(Object.entries(c.style.block_theme || {}).filter(([k]) => themeOptions.block_fields.includes(k))))},
  };
  const slider = (name, label, min, max, step, unit) => `<label for="theme-${name}">${label}</label>
    <input type="range" id="theme-${name}" data-block="${name}" min="${min}" max="${max}" step="${step}" value="${themeDraft.blocks[name]}">
    <output class="mono" data-out="${name}" data-unit="${unit}"></output>`;
  const pick = (name, label, rows) => `<label class="micro-label" for="theme-${name}">${label}</label>
    <select id="theme-${name}" data-field="${name}">${(rows || []).map(t =>
      `<option value="${esc(t.key)}"${t.key === themeDraft[name] ? ' selected' : ''}>${esc(t.label || t.key)}</option>`).join('')}</select>`;
  const dialog = studioDialog('theme-builder', `
    <div class="row"><h2>${key ? 'Edit theme' : 'New theme'}</h2><div class="spacer"></div>
      <button type="button" class="btn sm ghost" data-close>Close</button></div>
    <div class="theme-builder-grid">
      <form class="theme-builder-form" autocomplete="off">
        <label class="micro-label" for="theme-label">Name</label>
        <input id="theme-label" data-field="label" maxlength="40" value="${esc(themeDraft.label)}" placeholder="Night shift" required>
        <label class="micro-label" for="theme-for">Made for</label>
        <input id="theme-for" data-field="for" maxlength="60" value="${esc(themeDraft.for)}" placeholder="History, essays, explainers">

        <h3>Colours</h3>
        <div class="theme-colours">${THEME_COLOURS.map(([name, label]) => `
          <label for="theme-${name}">${label}</label>
          <input type="color" id="theme-${name}" data-colour="${name}" value="${esc(themeDraft[name])}">
          <input class="mono" data-hex="${name}" value="${esc(themeDraft[name])}" maxlength="7" aria-label="${label} as a hex code">`).join('')}
        </div>
        <p class="agent-note" data-contrast hidden></p>

        <h3>Pattern</h3>
        <div class="theme-segment" role="radiogroup" aria-label="Pattern">${themeOptions.patterns.map(p =>
          `<button type="button" role="radio" data-pattern="${p}">${THEME_PATTERNS[p] || p}</button>`).join('')}</div>
        <div data-icons-wrap>
          <div class="row"><h3>Icons for slates and thumbnails</h3><div class="spacer"></div><span class="agent-note" data-icon-count></span></div>
          <div class="theme-icons">${themeOptions.icons.map(k => `<button type="button" data-icon="${k}" title="${esc(k.replaceAll('_', ' '))}"
            aria-label="${esc(k.replaceAll('_', ' '))}"><img alt="" loading="lazy" src="/api/themes/icon/${k}.png?color=%23888888"></button>`).join('')}</div>
        </div>

        <h3>Graphics over the picture</h3>
        <div class="theme-sliders">
          ${slider('radius', 'Corner rounding', 0, 32, 1, 'px')}
          ${slider('panel_opacity', 'Panel opacity', 0.2, 1, 0.05, '%')}
          ${slider('border', 'Border width', 0, 8, 1, 'px')}
        </div>
        <label class="micro-label" for="theme-font">Title font</label>
        <select id="theme-font" data-block="font_display"><option value="">Each graphic's own</option>${themeOptions.fonts.map(f =>
          `<option value="${esc(f)}"${f === themeDraft.blocks.font_display ? ' selected' : ''}>${esc(f.replace(/^pack:/, ''))}</option>`).join('')}</select>
        <label class="micro-label" for="theme-weight">Title weight</label>
        <select id="theme-weight" data-block="weight">${[['', "Each graphic's own"], ['regular', 'Regular'], ['bold', 'Bold'], ['heavy', 'Heavy']].map(([v, l]) =>
          `<option value="${v}"${v === themeDraft.blocks.weight ? ' selected' : ''}>${l}</option>`).join('')}</select>
      </form>
      <div class="theme-builder-side">
        <img class="theme-sample" data-sample alt="A sample of the theme: the channel name on its background and pattern">
        <p class="agent-note">A sample: the pattern, and a panel drawn with your corners, opacity and border. Slates, thumbnails and graphics use these.</p>
        <p class="agent-note" data-error role="status"></p>
        <h3>Picture and templates</h3>
        <label class="micro-label" for="theme-grade">Colour grade on the pictures</label>
        <select id="theme-grade" data-field="grade">${themeOptions.grades.map(g =>
          `<option value="${g}"${g === themeDraft.grade ? ' selected' : ''}>${THEME_GRADES[g] || g}</option>`).join('')}</select>
        ${pick('intro', 'Opening slate', state.templates)}
        ${pick('thumb', 'Thumbnail', state.thumbStyles)}
        ${pick('outro', 'End screen', state.endTemplates)}

      </div>
    </div>
    <div class="row theme-builder-actions">
      ${key ? '<button type="button" class="btn sm ghost danger" data-delete>Delete theme</button>' : ''}
      <div class="spacer"></div>
      <button type="button" class="btn ghost" data-close>Cancel</button>
      <button type="button" class="btn" data-save>Save</button>
      <button type="button" class="btn primary" data-save-use>Save and use here</button>
    </div>`, () => {
    clearTimeout(themeSampleTimer);
    if (themeSampleUrl) URL.revokeObjectURL(themeSampleUrl);
    themeSampleUrl = ''; themeDraft = null;
  });
  dialog.querySelectorAll('[data-close]').forEach(b => { b.onclick = () => dialog.close(); });
  dialog.querySelector('form').onsubmit = e => e.preventDefault();
  dialog.addEventListener('input', e => {
    const t = e.target;
    if (t.dataset.field) themeDraft[t.dataset.field] = t.value;
    else if (t.dataset.block) themeDraft.blocks[t.dataset.block] = t.type === 'range' ? Number(t.value) : t.value;
    else if (t.dataset.colour) {
      themeDraft[t.dataset.colour] = t.value.toUpperCase();
      dialog.querySelector(`[data-hex="${t.dataset.colour}"]`).value = t.value.toUpperCase();
    } else if (t.dataset.hex) {
      const value = t.value.trim().replace(/^#?/, '#');
      if (!/^#[0-9a-f]{6}$/i.test(value)) return;
      themeDraft[t.dataset.hex] = value.toUpperCase();
      dialog.querySelector(`[data-colour="${t.dataset.hex}"]`).value = value;
    } else return;
    themeBuilderPaint(dialog);
  });
  dialog.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.pattern) themeDraft.pattern = b.dataset.pattern;
    else if (b.dataset.icon) {
      const at = themeDraft.icons.indexOf(b.dataset.icon);
      if (at >= 0) { if (themeDraft.icons.length > 1) themeDraft.icons.splice(at, 1); }
      else if (themeDraft.icons.length < themeOptions.max_icons) themeDraft.icons.push(b.dataset.icon);
      else return toast(`A theme holds up to ${themeOptions.max_icons} icons. Take one out first.`);
    } else if (b.hasAttribute('data-save')) return themeBuilderSave(dialog, false);
    else if (b.hasAttribute('data-save-use')) return themeBuilderSave(dialog, true);
    else if (b.hasAttribute('data-delete')) return themeBuilderDelete(dialog);
    else return;
    themeBuilderPaint(dialog);
  });
  themeBuilderPaint(dialog, true);
  dialog.querySelector('#theme-label').focus();
}

function themeBuilderPaint(dialog, now = false) {
  const d = themeDraft;
  if (!d) return;
  dialog.querySelectorAll('[data-pattern]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.pattern === d.pattern)));
  dialog.querySelectorAll('[data-icon]').forEach(b => b.setAttribute('aria-pressed', String(d.icons.includes(b.dataset.icon))));
  dialog.querySelector('[data-icon-count]').textContent = `${d.icons.length} of ${themeOptions.max_icons}`;
  dialog.querySelectorAll('[data-out]').forEach(o => {
    const v = d.blocks[o.dataset.out];
    o.textContent = o.dataset.unit === '%' ? `${Math.round(v * 100)}%` : `${v} px`;
  });
  const note = dialog.querySelector('[data-contrast]');
  const ratio = themeContrast(d.ink, d.ground);
  note.hidden = ratio >= 4.5;
  note.textContent = 'The text colour is hard to read on this background. Make one lighter or the other darker.';
  clearTimeout(themeSampleTimer);
  themeSampleTimer = setTimeout(async () => {
    const sent = JSON.stringify(d);
    try {
      const res = await fetch('/api/themes/sample', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({theme: {...d, label: d.label || 'Theme'}, name: d.label || state.channel?.name || ''})});
      if (!res.ok) throw Error((await res.json()).detail || 'The sample could not be drawn');
      const blob = await res.blob();
      if (!themeDraft || JSON.stringify(themeDraft) !== sent || !dialog.open) return;
      if (themeSampleUrl) URL.revokeObjectURL(themeSampleUrl);
      themeSampleUrl = URL.createObjectURL(blob);
      dialog.querySelector('[data-sample]').src = themeSampleUrl;
      dialog.querySelector('[data-error]').textContent = '';
    } catch (e) {
      if (dialog.open) dialog.querySelector('[data-error]').textContent = e.message;
    }
  }, now ? 0 : 220);
}

async function themeBuilderSave(dialog, use) {
  const d = themeDraft, channel = state.channel;
  if (!d.label.trim()) { dialog.querySelector('#theme-label').focus(); return toast('Give the theme a name.', true); }
  try {
    const {key, ...theme} = d;
    const saved = await api('/api/themes', {method: 'POST', body: JSON.stringify({theme, key})});
    state.themes = await api('/api/themes');
    dialog.close();
    if (use && state.channel?.id === channel.id) {
      const fresh = await api(`/api/channels/${channel.id}/theme`, {method: 'POST',
        body: JSON.stringify({key: saved.key, templates: true})});
      if (state.channel?.id === channel.id) applyChannel(fresh);
      toast(`${saved.label} saved and in use on this channel.`);
    } else {
      if (state.channel?.id === channel.id) paintChannel();
      toast(`${saved.label} saved. It is in the theme list for every channel.`);
    }
  } catch (e) { toast(e, true); }
}

async function themeBuilderDelete(dialog) {
  const d = themeDraft;
  try {
    const uses = await api(`/api/themes/uses?key=${encodeURIComponent(d.key)}`);
    const body = uses.channels.length
      ? `Used by ${uses.channels.join(', ')}. ${uses.channels.length === 1 ? 'It keeps its' : 'They keep their'} two colours and templates, and the background goes back to the default.`
      : 'No channel uses it.';
    if (!await appConfirm({title: `Delete ${d.label}?`, body, ok: 'Delete', danger: true})) return;
    await api(`/api/themes?key=${encodeURIComponent(d.key)}`, {method: 'DELETE'});
    state.themes = await api('/api/themes');
    dialog.close();
    if (state.channel) paintChannel();
    toast('Theme deleted.');
  } catch (e) { toast(e, true); }
}

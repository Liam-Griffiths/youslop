/* Shared app preference; localStorage is only the first-paint cache. */
const themeModes = ['system', 'light', 'dark'];
let themeRevision = 0, themeWrites = Promise.resolve(), themePending = 0;
function themeMode() { return document.documentElement.dataset.theme || 'system'; }
function applyTheme(value) {
  const mode = themeModes.includes(value) ? value : 'system';
  if (mode === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = mode;
  try { localStorage.setItem('corkbored-theme', mode); } catch (e) { /* private viewer */ }
  for (const button of document.querySelectorAll('[data-theme-choice]'))
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === mode));
  document.getElementById('cf-wave')?.paintTheme?.();
  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    const label = `Theme: ${mode}. Switch to ${themeModes[(themeModes.indexOf(mode) + 1) % 3]}`;
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
  }
}
function setTheme(mode) {
  if (!themeModes.includes(mode)) return;
  themeRevision++;
  applyTheme(mode);
  themePending++;
  // Serialize rapid clicks so an earlier save cannot overwrite a later one.
  themeWrites = themeWrites.then(() => api('/api/settings', {
    method: 'POST', body: JSON.stringify({theme: mode})
  })).catch(e => toast(`Theme could not be saved: ${e.message}`, true))
    .finally(() => { themePending--; });
  return themeWrites;
}
function cycleTheme() { return setTheme(themeModes[(themeModes.indexOf(themeMode()) + 1) % 3]); }
async function syncTheme() {
  if (themePending) return;
  const revision = themeRevision;
  try {
    const data = await api('/api/theme');
    if (revision === themeRevision && !themePending) applyTheme(data.theme);
  } catch (e) { /* Keep the first-paint cache while disconnected. */ }
}
// Separate webviews have separate storage; poll the shared preference while open.
window.addEventListener('focus', syncTheme);
window.addEventListener('storage', e => {
  if (e.key === 'corkbored-theme') { themeRevision++; applyTheme(e.newValue); }
});
setInterval(() => { if (!document.hidden) syncTheme(); }, 5000);
applyTheme(themeMode());
syncTheme();
// System uses CSS media queries, so OS changes apply live without a reload.
window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => applyTheme(themeMode()));

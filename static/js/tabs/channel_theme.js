/* Theme choices and an in-memory undo of exactly the fields the endpoint changes. */
async function pickTheme(key) {
  const channel = state.channel;
  const t = (state.themes || []).find(x => x.key === key) || {};
  const choice = await appChoose({
    title: `Use ${t.label || key}?`,
    body: `Choose colours and templates (${t.intro} slate, ${t.thumb} thumbnail, ${t.outro} end screen), or keep your current templates.`,
    choices: [{id: 'templates', label: 'Use colours and templates', primary: true},
      {id: 'colours', label: 'Colours only'}],
    cancel: 'Cancel',
  });
  if (choice === null || state.channel?.id !== channel.id) return;
  const before = JSON.parse(JSON.stringify({
    style: Object.fromEntries(['theme', 'accent', 'accent2', 'grade', 'block_theme'].map(k => [k, channel.style[k]])),
    frame: channel.frame,
    intro: {template: channel.intro.template}, thumb_template: channel.thumb_template,
    outro: {template: channel.outro.template, slots: channel.outro.slots},
  }));
  try {
    const fresh = await api(`/api/channels/${channel.id}/theme`, {
      method: 'POST', body: JSON.stringify({key, templates: choice === 'templates'}),
    });
    if (state.channel?.id === channel.id) applyChannel(fresh);
    toast(`${t.label || key} ${choice === 'templates' ? 'colours and templates' : 'colours'} applied`, false, {
      label: 'Undo', run: async () => {
        const restored = await saveChannel(before, {id: channel.id, quiet: true});
        if (state.channel?.id === channel.id) applyChannel(restored);
        toast('Theme change undone');
      },
    });
  } catch (e) { toast(e.message, true); }
}

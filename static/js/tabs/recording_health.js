// Availability is response-only metadata; it never changes saved takes.
const recordingHealthPending = new WeakSet();
function loadRecordingHealth(p) {
  if (recordingHealthPending.has(p)) return;
  recordingHealthPending.add(p);
  api(`/api/projects/${p.id}/recordings`).then(items => {
    const changed = JSON.stringify(items) !== JSON.stringify(p.missing_recordings || []);
    p.missing_recordings = items;
    if (changed && state.project === p && state.tab === 'record' && !cameraLocked()) paintRecord();
  }).catch(() => {}).finally(() => recordingHealthPending.delete(p));
}

function recordingMissing(p, sid, track = null) {
  const slide = p.slides.find(s => s.id === sid);
  const selected = track ?? (slide?.on_camera ? 'camera' : p.voice_track);
  const take = slide?.takes?.[selected] || (track === null ? slide?.take : null);
  return (p.missing_recordings || []).find(r => r.owner === 'slides' && r.id === sid
    && r.track === selected && r.path === (take?.path || ''));
}

async function recoverVoiceTake(track, action) {
  const p = state.project, s = p.slides[state.rec.index];
  const item = recordingMissing(p, s.id, track);
  if (item) await recoverRecording(item, action);
}

async function recoverRecording(item, action = '') {
  if (cameraLocked()) return;
  const pid = state.project.id;
  try {
    if (item.reprocess && !action) {
      state.project = await api(`/api/projects/${pid}/recordings/reprocess`, {
        method:'POST', body:JSON.stringify(item) });
      if (state.tab === 'record') paintRecord();
      else if (state.stage === 'edit') await tlRefreshProject();
      else await render();
      toast(`${item.label} reprocessed; the previous reference is kept in history.`);
      return;
    }
    if (item.owner === 'inserts') {
      go(`#/p/${pid}/edit`);
      toast(`Restore the source for ${item.label} or choose another source in its insert inspector.`);
      return;
    }
    // Who narrates is a whole-video choice; recovery never changes it.
    if (!action) action = state.project.narrator?.mode === 'ai' ? 'draft' : 'record';
    if (item.owner === 'sponsors') {
      go(`#/p/${pid}/edit`);
      toast(`Select ${item.label} in the Sponsor lane, then Voice with the local draft voice.`);
      return;
    }
    state.rec.index = state.project.slides.findIndex(s => s.id === item.id);
    if (state.rec.index < 0) return;
    state.rec.openDraft = action !== 'record';
    go(`#/p/${pid}/voice`);
    setRecordMode(action === 'record' && item.track === 'camera');
    paintRecord();
    if (action !== 'record') {
      const options = document.querySelector('.voice-options');
      if (options) options.open = true;
      toast('Choose a local draft voice, then Draft this paragraph. Use this voice for the video when ready.');
    } else toast(`Record ${item.label} again; the missing reference stays in history.`);
  } catch (e) { toast(e.message, true); }
}

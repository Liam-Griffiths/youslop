// The stage's headless page, driven by app/stage.py in a throwaway Chromium.
// It reads /job.json and does one of three things with the GPU:
//
//   intake   measure and classify library models (intake.js), and take
//            their thumbnails — what the confirm screen does on first open
//   solve    plan and check each paragraph's shot (plan.js, search.js), in
//            the video's order, so a shot can follow the one before it;
//            posts the pick, its checks and three small frames
//   render   draw every frame of each solved shot at the delivered size and
//            post it raw, in order, to the server's ffmpeg
//
// Nothing here reads the clock: frame i of a shot is a pure function of the
// shot, so a render is reproducible and the order clips are drawn in does
// not matter.
import { THREE, loadModel, points, fit, standing, boxOf } from './core.js';
import { poseAt, applyPose, frameCount } from './shot.js';
import { search, checkShot } from './search.js';
import { motion, jumpCut } from './checks.js';
import { analyse } from './intake.js';
import { buildScene, sceneKey, disposeObject } from './scene.js';
import { planFor } from './plan.js';
import { applyLook } from './looks.js';

const post = (p, body) => fetch(p, { method: 'POST', body: typeof body === 'string' || body instanceof Blob || ArrayBuffer.isView(body) ? body : JSON.stringify(body) });
const log = (m) => post('/log', m);
const job = await (await fetch('/job.json')).json();

const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = job.task === 'render';
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.appendChild(renderer.domElement);
const fitCam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);   // framing
const cam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);      // checks and frames

const url = (id) => `/models/${id}.glb`;
const entriesOf = (item) => item.entries.map((e) => ({ sid: e.sid, manifest: job.models[e.model], url: url(e.model) }));

// Scenes stay loaded while the next item needs them; at most two at once,
// since a big scan can take a few hundred megabytes of GPU memory.
const scenes = new Map();
async function sceneFor(item) {
  const entries = entriesOf(item), key = sceneKey(entries);
  if (scenes.has(key)) { const sc = scenes.get(key); scenes.delete(key); scenes.set(key, sc); return sc; }
  while (scenes.size >= 2) { const [k, old] = scenes.entries().next().value; scenes.delete(k); old.dispose(renderer); }
  const t0 = performance.now();
  const sc = await buildScene(entries);
  await log(`loaded ${key} in ${Math.round(performance.now() - t0)} ms`);
  scenes.set(key, sc);
  return sc;
}

async function jpeg(w, h, q = 0.88) {
  return new Promise((ok) => renderer.domElement.toBlob(ok, 'image/jpeg', q));
}

// ------------------------------------------------------------------ intake
async function intake() {
  for (const { model } of job.items) {
    const m = job.models[model];
    const t0 = performance.now();
    const holder = await loadModel(m, { url: url(model) });
    const a = analyse(renderer, holder.userData.inner);
    const scene = new THREE.Scene(); scene.add(holder); holder.updateMatrixWorld(true);
    await post('/result', { model, measured: holder.userData.measured.toArray().map((v) => +v.toFixed(5)), analysis: a,
                            ms: Math.round(performance.now() - t0) });
    // The library card: a three-quarter view outside, or from inside a room.
    const W = 640, H = 360;
    renderer.setSize(W, H, false); cam.aspect = W / H; cam.updateProjectionMatrix();
    holder.userData.manifest = { ...m, analysis: a };      // standing() reads the floor from it
    const st = a.kind_auto === 'interior' ? standing(holder, 1.6) : null;
    let undo;
    if (st) {
      const size = boxOf(holder).getSize(new THREE.Vector3()), look = size.z >= size.x ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(-1, 0, 0);
      cam.fov = 60; cam.position.set(st.centre.x, st.eye, st.centre.z).addScaledVector(look, -Math.max(size.x, size.z) * 0.3);
      cam.near = 0.02; cam.far = Math.max(size.x, size.z) * 20; cam.lookAt(cam.position.clone().add(look));
      cam.updateProjectionMatrix();
      undo = applyLook(renderer, scene, 'baked');
    } else {
      undo = applyLook(renderer, scene, 'set', { models: [holder] });
      cam.fov = 35;
      const sph = boxOf(holder).getBoundingSphere(new THREE.Sphere());
      fit(cam, points([holder], 3000), { az: 35, el: 18, fill: 0.78, sceneRadius: sph.radius });
    }
    renderer.render(scene, cam);
    await post(`/thumb/${model}`, await jpeg(W, H, 0.86));
    undo();
    scene.remove(holder); disposeObject(holder); renderer.renderLists.dispose();
  }
}

// ------------------------------------------------------------------- solve
async function solve() {
  const done = new Map();                 // item id -> { shot, k, scene }
  for (const item of job.items) {
    const t0 = performance.now();
    let sc;
    try { sc = await sceneFor(item); } catch (e) {
      await post('/result', { id: item.id, error: `could not load the scene: ${e.message || e}` }); continue;
    }
    const prev = (item.prev_id && done.get(item.prev_id)) || item.prev || null;
    const samePrev = prev && prev.scene === sc.key ? prev : null;
    const plan = planFor(item.intent, sc, fitCam, { secs: item.secs, prev: samePrev });
    const ctx = { ...plan.ctx, gpu: { renderer, scene: sc.scene, cam } };
    // A hard cut onto the same scene from nearly the same place is a jump cut.
    const jumpy = samePrev && samePrev.shot && ['cut', 'match'].includes(item.intent.join || 'cut');
    const check = (s, k, quick) => {
      const r = checkShot(s, ctx, quick);
      if (jumpy) {
        const j = jumpCut(samePrev.shot, s);
        r.checks.jump = j;
        if (!j.ok) { r.ok = false; r.failed.push('jump'); r.score += 60; }
      }
      return r;
    };
    const r = search(plan.cands, plan.build, check, { max: plan.max });
    if (!r) { await post('/result', { id: item.id, error: 'no candidates', notes: plan.notes }); continue; }
    const { dev, ...pick } = r.k;
    done.set(item.id, { shot: r.shot, k: pick, scene: sc.key });
    await post('/result', {
      id: item.id, scene: sc.key, kind: plan.kind, look: plan.look, subject: plan.subject, notes: plan.notes,
      shot: r.shot, pick, tried: r.tried, of: r.of, flagged: r.flagged, flag: r.flag || '',
      failed: r.report.failed, score: r.report.score, checks: r.report.checks, ms: Math.round(performance.now() - t0),
    });
    if (item.thumbs) {
      const W = 480, H = 270, undo = applyLook(renderer, sc.scene, plan.look, { models: sc.holders, haze: r.report.checks.haze });
      renderer.setSize(W, H, false); cam.aspect = W / H;
      const N = frameCount(r.shot);
      for (const [j, u] of [0, 0.5, 1].entries()) {
        applyPose(cam, poseAt(r.shot, Math.round(u * (N - 1))), { W, H });
        renderer.render(sc.scene, cam);
        await post(`/thumb/${item.id}/${j}`, await jpeg(W, H));
      }
      undo();
    }
  }
}

// ------------------------------------------------------------------ render
async function render() {
  // Grouped by scene, so each scene's models load once.
  const order = [...job.items].sort((a, b) => sceneKey(entriesOf(a)).localeCompare(sceneKey(entriesOf(b))));
  for (const item of order) {
    const sc = await sceneFor(item);
    const { W, H, fps, frames } = item, shot = { ...item.shot, secs: frames / fps };
    // The motion check again at the length the voice actually runs: a move
    // solved for twelve seconds turns faster when the take is eight.
    if (item.intent) {
      const plan = planFor(item.intent, sc, fitCam, { secs: shot.secs });
      const m = motion(shot, plan.ctx.subject.pts, { fps });
      if (!m.ok) await log(`shot ${item.id}: motion check fails at ${shot.secs.toFixed(1)} s (peak turn ${m.peak_turn_deg_s}°/s)`);
    }
    const undo = applyLook(renderer, sc.scene, item.look || 'set', { models: sc.holders, haze: item.haze });
    renderer.setSize(W, H, false); cam.aspect = W / H;
    const gl = renderer.getContext(), buf = new Uint8Array(W * H * 4);
    await post(`/begin/${item.clip}`, { W, H, fps, frames });
    const t0 = performance.now();
    for (let i = 0; i < frames; i++) {
      applyPose(cam, poseAt(shot, i, fps), { W, H });
      renderer.render(sc.scene, cam);
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, buf);
      const r = await post(`/frame/${item.clip}`, buf);
      if (!r.ok) throw new Error(`the encoder refused frame ${i} of ${item.clip}`);
    }
    await post(`/end/${item.clip}`, { ms: Math.round(performance.now() - t0) });
    undo();
  }
}

await ({ intake, solve, render }[job.task])();
for (const sc of scenes.values()) sc.dispose(renderer);
await post('/done', {});

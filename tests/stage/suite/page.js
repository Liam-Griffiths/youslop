// Runs every case in cases.js for the models the runner (suite.py) lists:
// the solver's search with the GPU checks, then three frames of the pick —
// first, middle, last — drawn at preview size for the contact sheet.
import { THREE, loadModel, buildSet } from '/static/stage/core.js';
import { poseAt, applyPose, frameCount } from '/static/stage/shot.js';
import { search, checkShot } from '/static/stage/search.js';
import { CASES } from './cases.js';

const W = 480, H = 270;
const post = (p, o) => fetch(p, { method: 'POST', body: typeof o === 'string' ? o : JSON.stringify(o) });
const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true });
renderer.setSize(W, H); renderer.toneMapping = THREE.ACESFilmicToneMapping;
document.body.appendChild(renderer.domElement);
const fitCam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);    // the cases' framing
const cam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);       // checks and frames

// How the sheet draws a shot. Only the frames see this: the checks run on the
// model alone, so a floor or sky can never hide an edge or a hole.
function look(kind, scene, report) {
  const g = new THREE.Group(), keep = { bg: scene.background, fog: scene.fog, env: scene.environment };
  let set = null;
  if (kind === 'set') set = buildSet(renderer, scene, [scene.userData.model]);
  else {
    const sky = { baked: 0xf2efe8, scan_sky: 0xb9d3ec, city: 0xc4d2e0, set_inside: 0xb9d3ec }[kind] ?? 0x888888;
    scene.background = new THREE.Color(sky);
    g.add(new THREE.HemisphereLight(0xffffff, 0x555555, kind === 'set_inside' ? 2 : 1.4));
    if (kind === 'city') {
      const sun = new THREE.DirectionalLight(0xffffff, 1.8); sun.position.set(1, 2, 0.6); g.add(sun);
      const hz = report.checks.haze;
      if (hz && hz.far) scene.fog = new THREE.Fog(sky, hz.near, hz.far);
    }
    scene.add(g);
  }
  return () => {
    if (set) set.dispose();
    scene.remove(g); scene.background = keep.bg; scene.fog = keep.fog; scene.environment = keep.env;
  };
}

function dispose(obj) {
  obj.traverse((o) => {
    if (!o.isMesh) return;
    o.geometry.dispose();
    for (const m of [].concat(o.material)) {
      for (const v of Object.values(m)) if (v && v.isTexture) v.dispose();
      m.dispose();
    }
  });
  renderer.renderLists.dispose();
}

const { models, trace } = await (await fetch('/suite/models.json')).json();
for (const { file, id } of models) {
  const make = CASES[file];
  if (!make) continue;
  const manifest = await (await fetch(`/models/${id}.json`)).json();
  const t0 = performance.now();
  const holder = await loadModel(manifest, { url: `/models/${id}.glb` });
  const scene = new THREE.Scene();
  scene.add(holder, new THREE.HemisphereLight(0xffffff, 0x444444, 2));
  scene.userData.model = holder;
  holder.updateMatrixWorld(true);
  await post('/log', { model: file, loaded_ms: Math.round(performance.now() - t0) });

  for (const c of make(holder, fitCam)) {
    const t1 = performance.now();
    const ctx = { ...c.ctx, gpu: { renderer, scene, cam } };
    // --trace: every candidate's checks, to see why a search found nothing
    const tried = [];
    const check = (s, k, q) => {
      const rep = checkShot(s, ctx, q);
      if (trace) tried.push({ k, quick: q, failed: rep.failed, score: rep.score, checks: rep.checks });
      return rep;
    };
    const r = search(c.cands, c.build, check, { max: c.max || 400 });
    if (trace) await post('/trace', { model: file, case: c.name, tried });
    if (!r) { await post('/result', { model: file, case: c.name, error: 'no candidates' }); continue; }
    const { dev, ...pick } = r.k;
    await post('/result', {
      model: file, case: c.name, pick, shot: r.shot, tried: r.tried, of: r.of, flagged: r.flagged,
      failed: r.report.failed, score: r.report.score, checks: r.report.checks, ms: Math.round(performance.now() - t1),
    });
    const undo = look(c.look, scene, r.report), N = frameCount(r.shot);
    for (const [j, u] of [0, 0.5, 1].entries()) {
      cam.aspect = W / H;
      applyPose(cam, poseAt(r.shot, Math.round(u * (N - 1))), { W, H });
      renderer.setRenderTarget(null); renderer.render(scene, cam);
      await post(`/frame/${file}/${c.name}/${j}`, renderer.domElement.toDataURL('image/jpeg', 0.9));
    }
    undo();
  }
  scene.remove(holder); dispose(holder);
}
await post('/done', {});

// The Stage tab's shot view: one shot's scene, lit as it will render,
// played live at real speed — the one-section preview, which costs nothing —
// and a free camera for setting a shot by hand. A shot set from the view is
// a move between the two framings the creator stood at (or a still from
// one), checked here with the same checks the solver runs before it is saved.
//
// app.js is a classic script, so this hands it `window.StageEditor`.
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { THREE } from './core.js';
import { poseAt, applyPose, frameCount, FPS } from './shot.js';
import { checkShot } from './search.js';
import { buildScene } from './scene.js';
import { planFor, framingOf } from './plan.js';
import { applyLook } from './looks.js';

// `data` is GET /api/projects/{pid}/stage/{sid}/scene.
async function mount(el, data, { onTime = () => {} } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  el.innerHTML = '';
  el.appendChild(renderer.domElement);
  renderer.domElement.style.display = 'block';

  let sc;
  try { sc = await buildScene(data.entries); } catch (e) {
    renderer.dispose();
    throw new Error(`Could not load the scene: ${e.message || e}`);
  }
  const fitCam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);
  const cam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);
  const checkCam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);
  const plan = planFor(data.intent, sc, fitCam, { secs: data.secs });
  const checks = (data.solved && data.solved.checks) || {};
  let undoLook = applyLook(renderer, sc.scene, plan.look, { models: sc.holders, haze: checks.haze });

  let shot = data.solved && data.solved.shot ? { ...data.solved.shot, secs: data.secs } : null;
  let t = 0, playing = false, last = 0, free = false;
  const controls = new OrbitControls(cam, renderer.domElement);
  controls.enabled = false; controls.enableDamping = true;

  function size() {
    const w = el.clientWidth || 640, h = Math.round(w * 9 / 16);
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = '100%'; renderer.domElement.style.height = 'auto';
    cam.aspect = 16 / 9; cam.updateProjectionMatrix();
    return [w, h];
  }
  const ro = new ResizeObserver(size); ro.observe(el);
  size();

  function pose() {
    if (!shot || free) return;
    const N = frameCount(shot);
    applyPose(cam, poseAt(shot, Math.min(N - 1, Math.round(t * FPS))), { W: 1920, H: 1080 });
  }
  // A view to start the free camera from, when there is no shot yet.
  function startView() {
    const c = sc.box.getCenter(new THREE.Vector3());
    cam.position.copy(c).addScaledVector(new THREE.Vector3(1, 0.4, 1).normalize(), sc.radius * 2.5);
    controls.target.copy(c);
    cam.near = sc.radius * 0.005; cam.far = sc.radius * 60; cam.updateProjectionMatrix();
  }
  if (shot) pose(); else startView();

  let alive = true;
  (function loop(now) {
    if (!alive) return;
    if (playing && shot) {
      t += Math.min(0.1, (now - last) / 1000);
      if (t >= shot.secs) { t = shot.secs; playing = false; }
      onTime(t, shot.secs, playing);
    }
    last = now;
    if (free) controls.update(); else pose();
    renderer.render(sc.scene, cam);
    requestAnimationFrame(loop);
  })(performance.now());

  // The checks run on the model alone, never on the look's floor or sky.
  function check(s) {
    undoLook();
    try {
      return checkShot(s, { ...plan.ctx, gpu: { renderer, scene: sc.scene, cam: checkCam } });
    } finally {
      undoLook = applyLook(renderer, sc.scene, plan.look, { models: sc.holders, haze: checks.haze });
      size();
    }
  }

  let marks = { a: null, b: null };
  const here = () => ({ ...framingOf(cam.position.clone(), controls.target.clone()), fov: cam.fov });

  return {
    plan, hasShot: () => !!shot, secs: () => (shot ? shot.secs : data.secs),
    play() { if (!shot) return; if (t >= shot.secs) t = 0; free = false; controls.enabled = false; playing = true; },
    pause() { playing = false; },
    seek(u) { if (!shot) return; free = false; controls.enabled = false; t = u * shot.secs; playing = false; onTime(t, shot.secs, false); },
    // Free camera, starting from where the shot is now.
    free() {
      playing = false; free = true; controls.enabled = true;
      if (shot) {
        const p = poseAt(shot, Math.min(frameCount(shot) - 1, Math.round(t * FPS)));
        controls.target.copy(p.aim);
      }
      controls.update();
    },
    mark(which) { marks[which] = here(); return marks; },
    marks: () => marks,
    // The shot the marks make: a move from start to end on one ease curve,
    // or a locked-off frame when only one is set. The lens is the start's.
    fromMarks() {
      const a = marks.a || marks.b, b = marks.b || marks.a;
      if (!a) return null;
      const f = (m) => ({ target: m.target, az: m.az, el: m.el, dist: m.dist });
      // the shorter way round
      let bz = b.az; while (bz - a.az > 180) bz -= 360; while (a.az - bz > 180) bz += 360;
      return { kind: 'move', secs: data.secs, fov: a.fov, a: f(a), b: { ...f(b), az: bz } };
    },
    use(s) { shot = { ...s, secs: data.secs }; t = 0; free = false; controls.enabled = false; marks = { a: null, b: null }; pose(); },
    check,
    dispose() {
      alive = false; ro.disconnect(); controls.dispose(); undoLook();
      sc.dispose(renderer); renderer.dispose(); renderer.forceContextLoss();
      el.innerHTML = '';
    },
  };
}

window.StageEditor = { mount };

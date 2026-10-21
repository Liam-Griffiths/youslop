// The stage: the scene code every 3D explainer surface shares — the library
// viewer, the scene editor, and the headless renderer — so what is checked
// and previewed in the app is exactly what is drawn. See docs/3d-explainer.md.
//
// Units are metres, +y is up, and a model's front faces +z once its
// manifest's `heading` is applied. Nothing in here reads the clock: a shot is
// a pure function of time, which is what lets the renderer draw any frame of
// it in any order.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export { THREE };
export const rad = THREE.MathUtils.degToRad;
export const lerp = (a, b, u) => a + (b - a) * u;
export const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const bearing = (az, el) => new THREE.Vector3(
  Math.sin(rad(az)) * Math.cos(rad(el)), Math.sin(rad(el)), Math.cos(rad(az)) * Math.cos(rad(el)));

// ------------------------------------------------------------------ models
// A library model as a three.js object, built from its manifest:
//
//   holder   position in the scene, and `heading` (turns the front to +z)
//   └ scaler `scale` (file units -> metres)
//     └ inner  the GLB, stood on y=0 and centred on x/z
//
// `measured` is the inner model's size in file units: what the intake screen
// multiplies by `scale` to show real metres, and how it works out the scale
// from a true dimension the creator types in.
export async function loadModel(manifest, { at = [0, 0, 0], url = null } = {}) {
  const gltf = await new GLTFLoader().loadAsync(url || `/api/models/${manifest.id}/model.glb`);
  const inner = gltf.scene, scaler = new THREE.Group(), holder = new THREE.Group();
  scaler.add(inner); holder.add(scaler);
  inner.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(inner);
  const c = box.getCenter(new THREE.Vector3());
  inner.position.sub(new THREE.Vector3(c.x, box.min.y, c.z));
  const measured = box.getSize(new THREE.Vector3());
  inner.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  holder.userData = { manifest, measured, inner, scaler, originals: new Map() };
  holder.position.fromArray(at);
  applyManifest(holder, manifest);
  return holder;
}

// Re-apply what a human can change on the intake screen, without reloading.
export function applyManifest(holder, manifest) {
  const { scaler, inner, originals } = holder.userData;
  holder.userData.manifest = manifest;
  scaler.scale.setScalar(manifest.scale || 1);
  holder.rotation.y = rad(manifest.heading || 0);
  // A bare scan (no textures) can be given one flat colour — muslin for the
  // Wright Flyer. Textured materials are never touched.
  inner.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of [].concat(o.material)) {
      if (m.map) continue;
      if (!originals.has(m)) originals.set(m, { color: m.color.clone(), roughness: m.roughness });
      const orig = originals.get(m);
      if (manifest.tint) { m.color.set(manifest.tint); m.roughness = 0.85; }
      else { m.color.copy(orig.color); m.roughness = orig.roughness; }
    }
  });
  holder.updateMatrixWorld(true);
}

// The model's size in metres, as width (x) × height (y) × length (z) after
// its heading — the order the intake screen shows and asks for.
export function sizeMetres(holder) {
  const { measured, manifest } = holder.userData;
  const s = manifest.scale || 1, sideways = Math.round((manifest.heading || 0) / 90) % 2 !== 0;
  return {
    width: (sideways ? measured.z : measured.x) * s,
    height: measured.y * s,
    length: (sideways ? measured.x : measured.z) * s,
  };
}

export const boxOf = (...objs) =>
  objs.reduce((b, o) => b.union(new THREE.Box3().setFromObject(o)), new THREE.Box3());

// --------------------------------------------------------------------- set
// Reflections from a generated room, a sun with soft shadows, and a floor
// that fades into the background so there is never an edge or false horizon.
// The fade texture has no mipmaps: at grazing angles they average the whole
// gradient into a grey band along the horizon.
export function buildSet(renderer, scene, models, { bg = 0x1d232a, pool = 0x313943, sunAz = 35, sunEl = 50 } = {}) {
  const group = new THREE.Group();
  scene.background = new THREE.Color(bg);
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  const box = models.length ? boxOf(...models) : new THREE.Box3(new THREE.Vector3(-1, 0, -1), new THREE.Vector3(1, 2, 1));
  const sph = box.getBoundingSphere(new THREE.Sphere());
  const R = Math.max(sph.radius * 40, 1500);
  const cv = document.createElement('canvas'); cv.width = cv.height = 1024;
  const g = cv.getContext('2d'), grad = g.createRadialGradient(512, 512, 0, 512, 512, 512);
  const css = (c) => '#' + new THREE.Color(c).getHexString();
  const k = sph.radius / R;                // pool about the scene's size, fading over ~12x that
  grad.addColorStop(0, css(pool)); grad.addColorStop(Math.min(0.3, k * 1.5), css(pool));
  grad.addColorStop(Math.min(0.95, k * 12), css(bg)); grad.addColorStop(1, css(bg));
  g.fillStyle = grad; g.fillRect(0, 0, 1024, 1024);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace; tex.generateMipmaps = false; tex.minFilter = THREE.LinearFilter;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(R * 2, R * 2),
    new THREE.MeshBasicMaterial({ map: tex, toneMapped: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.set(sph.center.x, -0.002, sph.center.z);
  floor.userData.set = true;
  const catcher = new THREE.Mesh(new THREE.PlaneGeometry(R * 2, R * 2), new THREE.ShadowMaterial({ opacity: 0.4 }));
  catcher.rotation.x = -Math.PI / 2; catcher.position.copy(floor.position); catcher.receiveShadow = true;
  catcher.userData.set = true;
  const hemi = new THREE.HemisphereLight(0xdfe8ff, 0x30343a, 0.6);
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.position.copy(sph.center).addScaledVector(bearing(sunAz, sunEl), sph.radius * 3);
  sun.target.position.copy(sph.center);
  sun.castShadow = true; sun.shadow.mapSize.set(4096, 4096); sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.02;
  const sc = sun.shadow.camera;
  sc.left = sc.bottom = -sph.radius * 1.1; sc.right = sc.top = sph.radius * 1.1;
  sc.near = sph.radius * 0.5; sc.far = sph.radius * 6; sc.updateProjectionMatrix();
  group.add(floor, catcher, hemi, sun, sun.target);
  scene.add(group);
  return { group, box, sphere: sph, dispose: () => { scene.remove(group); tex.dispose(); } };
}

// ----------------------------------------------------------------- framing
// Up to `max` vertices of the objects, in world space. Framing measures
// these, not bounding boxes: a box's empty corners pull a three-quarter view
// off centre.
export function points(objs, max = 4000) {
  const all = [], v = new THREE.Vector3();
  let total = 0;
  objs.forEach((o) => o.traverse((m) => { if (m.isMesh && !m.userData.set) total += m.geometry.attributes.position.count; }));
  const step = Math.max(1, Math.floor(total / max));
  objs.forEach((o) => o.traverse((m) => {
    if (!m.isMesh || m.userData.set) return;
    m.updateMatrixWorld(true);
    const pos = m.geometry.attributes.position;
    for (let i = 0; i < pos.count; i += step) all.push(v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld).clone());
  }));
  return all;
}

function extent(cam, pts) {
  cam.updateMatrixWorld(true);
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9, behind = false;
  const v = new THREE.Vector3();
  for (const p of pts) {
    v.copy(p).applyMatrix4(cam.matrixWorldInverse);
    if (v.z > -cam.near) { behind = true; continue; }
    v.applyMatrix4(cam.projectionMatrix);
    x0 = Math.min(x0, v.x); x1 = Math.max(x1, v.x); y0 = Math.min(y0, v.y); y1 = Math.max(y1, v.y);
  }
  return { behind, x0, x1, y0, y1, fill: Math.max((x1 - x0) / 2, (y1 - y0) / 2) };
}

// Put the camera on a bearing (degrees) from the points and find the distance
// at which their projection fills `fill` of the frame, centred. Solved once
// per framing — never per frame of a move, which is what made a camera bounce.
export function fit(cam, pts, { az, el, fill = 0.7, sceneRadius = 100 }) {
  const sph = new THREE.Sphere().setFromPoints(pts);
  const dir = bearing(az, el), target = sph.center.clone();
  cam.near = 0.05; cam.far = 10000; cam.updateProjectionMatrix();
  let dist = sph.radius * 2;
  for (let pass = 0; pass < 3; pass++) {
    let lo = sph.radius * 0.3, hi = sph.radius * 60;
    for (let k = 0; k < 40; k++) {
      dist = (lo + hi) / 2;
      cam.position.copy(target).addScaledVector(dir, dist); cam.lookAt(target);
      const e = extent(cam, pts);
      if (e.behind || e.fill > fill) lo = dist; else hi = dist;
    }
    // re-centre on the projection, not on the 3D centre
    cam.position.copy(target).addScaledVector(dir, dist); cam.lookAt(target);
    const e = extent(cam, pts), halfH = Math.tan(rad(cam.fov / 2)) * dist, halfW = halfH * cam.aspect;
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1);
    target.addScaledVector(right, ((e.x0 + e.x1) / 2) * halfW).addScaledVector(up, ((e.y0 + e.y1) / 2) * halfH);
  }
  place(cam, target, az, el, dist, sceneRadius);
  return { pos: cam.position.clone(), target, dist, az, el };
}

// The camera at a bearing and distance from a target. The far plane reaches
// past the floor's fade — short of it, the floor is cut into a false horizon.
export function place(cam, target, az, el, dist, sceneRadius = 100) {
  cam.position.copy(target).addScaledVector(bearing(az, el), dist);
  cam.lookAt(target);
  cam.near = Math.max(0.05, dist * 0.02); cam.far = dist + sceneRadius * 15;
  cam.updateProjectionMatrix();
}

// ------------------------------------------------------------------ checks
// Walk every frame of a shot without drawing it. A deliberate move changes
// direction at most once per axis (ease in, ease out); more is a bounce.
export function motionCheck(cam, N, fps, setFrame, subjectPts) {
  const sample = subjectPts.filter((_, i) => i % 20 === 0);
  const rows = [];
  for (let i = 0; i < N; i++) {
    setFrame(i); cam.updateMatrixWorld(true);
    const dir = new THREE.Vector3(); cam.getWorldDirection(dir);
    let sx = 0, sy = 0;
    for (const p of sample) { const v = p.clone().project(cam); sx += v.x; sy += v.y; }
    rows.push({ pos: cam.position.clone(), dir, sx: sx / sample.length, sy: sy / sample.length });
  }
  const reversals = (series) => {
    const v = series.slice(1).map((s, i) => s - series[i]);
    const peak = Math.max(...v.map(Math.abs)) || 1, eps = peak * 0.05;
    let n = 0, last = 0;
    for (const x of v) { if (Math.abs(x) < eps) continue; const s = Math.sign(x); if (last && s !== last) n++; last = s; }
    return n;
  };
  const turn = rows.slice(1).map((r, i) => (r.dir.angleTo(rows[i].dir) * 180) / Math.PI * fps);
  const report = {
    reversals: {
      cam_x: reversals(rows.map((r) => r.pos.x)), cam_y: reversals(rows.map((r) => r.pos.y)),
      cam_z: reversals(rows.map((r) => r.pos.z)),
      subject_x: reversals(rows.map((r) => r.sx)), subject_y: reversals(rows.map((r) => r.sy)),
    },
    peak_turn_deg_s: +(Math.max(0, ...turn)).toFixed(1),
  };
  report.ok = Object.values(report.reversals).every((n) => n <= 1) && report.peak_turn_deg_s <= 20;
  return report;
}

// Occlusion, on the GPU: draw the target flat red over a black scene and
// count red pixels; then the target alone. The ratio is how much of it is
// actually visible. `target` is { meshes: Set, box?: Box3 }; with a box, only
// the part of those meshes inside it counts — a region of an unsplit scan.
const VW = 320, VH = 180;
let _rt = null;
const _black = new THREE.MeshBasicMaterial({ color: 0x000000 });
export function visibility(renderer, scene, cam, target) {
  _rt = _rt || new THREE.WebGLRenderTarget(VW, VH);
  renderer.localClippingEnabled = true;
  const meshes = target.meshes, box = target.box;
  const planes = box ? [
    new THREE.Plane(new THREE.Vector3(1, 0, 0), -box.min.x), new THREE.Plane(new THREE.Vector3(-1, 0, 0), box.max.x),
    new THREE.Plane(new THREE.Vector3(0, 1, 0), -box.min.y), new THREE.Plane(new THREE.Vector3(0, -1, 0), box.max.y),
    new THREE.Plane(new THREE.Vector3(0, 0, 1), -box.min.z), new THREE.Plane(new THREE.Vector3(0, 0, -1), box.max.z)] : [];
  const red = new THREE.MeshBasicMaterial({ color: 0xff0000, clippingPlanes: planes,
    depthFunc: THREE.LessEqualDepth, side: THREE.DoubleSide });
  const buf = new Uint8Array(VW * VH * 4), saved = [];
  scene.traverse((o) => { if (o.isMesh) saved.push([o, o.material, o.visible]); });
  const bg = scene.background, env = scene.environment, auto = renderer.autoClear;
  scene.environment = null;
  const count = () => {
    renderer.readRenderTargetPixels(_rt, 0, 0, VW, VH, buf);
    let n = 0; for (let i = 0; i < buf.length; i += 4) if (buf[i] > 100 && buf[i + 1] < 60) n++;
    return n;
  };
  renderer.setRenderTarget(_rt);
  scene.background = new THREE.Color(0);
  saved.forEach(([o]) => { o.material = _black; });
  renderer.autoClear = true; renderer.render(scene, cam);
  saved.forEach(([o]) => { o.material = red; o.visible = meshes.has(o); });
  renderer.autoClear = false; scene.background = null; renderer.render(scene, cam);
  const seen = count();
  renderer.autoClear = true; scene.background = new THREE.Color(0); renderer.render(scene, cam);
  const alone = count();
  renderer.setRenderTarget(null); renderer.autoClear = auto;
  saved.forEach(([o, m, v]) => { o.material = m; o.visible = v; });
  scene.background = bg; scene.environment = env; red.dispose();
  return { visible: alone ? seen / alone : 0, coverage: alone / (VW * VH) };
}

// Distance from a camera position to the nearest sampled point of anything.
export const clearance = (pos, pts) => pts.reduce((m, p) => Math.min(m, p.distanceTo(pos)), Infinity);

// A bearing for a shot: try angles around the preferred one, checking the
// whole move (start, middle, end), and keep the nearest that sees enough of
// the target and stays clear of the geometry. When nothing passes, return
// the best with a flag for a human — never fail, never hide it.
export function chooseAngle(renderer, scene, cam, framePts, target, allPts, pref,
  { fill = 0.65, sceneRadius = 50, minVis = 0.85, sweep = 0 } = {}) {
  const tried = [];
  for (const dAz of [0, 10, -10, 20, -20, 30, -30, 45, -45, 60, -60, 90, -90]) {
    for (const dEl of [0, 10, -8, 20]) {
      const az = pref.az + dAz, el = Math.max(3, pref.el + dEl);
      let ok = true, worst = 1, minClear = Infinity;
      for (const k of [0, 0.5, 1]) {
        const f = fit(cam, framePts, { az: az + sweep * k, el, fill, sceneRadius });
        const v = visibility(renderer, scene, cam, target), c = clearance(cam.position, allPts);
        worst = Math.min(worst, v.visible); minClear = Math.min(minClear, c);
        if (v.visible < minVis || c < f.dist * 0.25) ok = false;
      }
      tried.push({ az, el, vis: +worst.toFixed(2), clear: +minClear.toFixed(1), ok });
      if (ok) return { az, el, ok: true, tried };
    }
  }
  const best = [...tried].sort((a, b) => b.vis - a.vis)[0];
  return { az: best.az, el: best.el, ok: false, flag: `best view only ${Math.round(best.vis * 100)}% unobstructed`, tried };
}

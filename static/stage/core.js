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

import { rad, bearing } from './frame.js';

export { THREE };
export { rad, lerp, ease, bearing } from './frame.js';

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

// Where to stand inside a model, in the scene: the intake's floor, ceiling
// and room centre (measured in the scaler's space, file units) carried
// through the model's heading, scale and position. `eye` is the floor plus
// `eyeMetres` of real height — scaled, so an unconfirmed model's guess
// stays a guess rather than a camera under the floor.
export function standing(holder, eyeMetres = 1.6) {
  const a = holder.userData.manifest.analysis || {}, sc = holder.userData.scaler;
  if (a.floor_y == null) return null;
  holder.updateMatrixWorld(true);
  const local = a.room_centre ? [a.room_centre[0], a.floor_y, a.room_centre[1]] : [a.probe_at[0], a.floor_y, a.probe_at[2]];
  const floor = sc.localToWorld(new THREE.Vector3().fromArray(local));
  const ceiling = a.ceiling_y != null ? sc.localToWorld(new THREE.Vector3(local[0], a.ceiling_y, local[2])).y : null;
  return { centre: floor.clone(), floor: floor.y, ceiling, eye: floor.y + eyeMetres };
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

// Framing, shots and checks live in their own modules (frame.js, shot.js,
// checks.js, gpu.js, search.js); these re-exports keep older imports working.
export { points, fit, place, keepInFrame, clearance } from './frame.js';
export { visibility } from './gpu.js';

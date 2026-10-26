// The checks that need the renderer: each draws the scene small, in flat
// colours, and counts pixels. Small and flat is what makes them cheap enough
// to run on dozens of candidate shots — the Abbey's search tried hundreds.
//
// Anything that is set dressing rather than the model (a floor, a sky dome,
// a ground skirt) should be hidden by the caller or passed in `hide`: the
// edge and void checks exist to see what the model does NOT cover, and a
// skirt drawn under it would hide exactly that.
import * as THREE from 'three';
import { probe } from './probe.js';

const W = 320, H = 180;
const KEY = new THREE.Color(0xff00ff);         // a colour no surface has
let _rt = null, _buf = null;
const target = () => {
  _rt = _rt || new THREE.WebGLRenderTarget(W, H);
  _buf = _buf || new Uint8Array(W * H * 4);
  return _rt;
};
const isKey = (b, j) => b[j] > 240 && b[j + 1] < 20 && b[j + 2] > 240;

function drawKeyed(renderer, scene, cam, hide = []) {
  const keep = { bg: scene.background, fog: scene.fog, vis: hide.map((o) => o.visible) };
  scene.background = KEY; scene.fog = null; hide.forEach((o) => { o.visible = false; });
  renderer.setRenderTarget(target()); renderer.render(scene, cam);
  renderer.readRenderTargetPixels(_rt, 0, 0, W, H, _buf); renderer.setRenderTarget(null);
  scene.background = keep.bg; scene.fog = keep.fog; hide.forEach((o, i) => { o.visible = keep.vis[i]; });
  return _buf;
}

// The share of the frame (0..100) where nothing was modelled: past a scan's
// edge, through a hole, out of a set's missing wall.
export function keyShare(renderer, scene, cam, { hide = [] } = {}) {
  const b = drawKeyed(renderer, scene, cam, hide);
  let n = 0; for (let j = 0; j < b.length; j += 4) if (isKey(b, j)) n++;
  return (100 * n) / (W * H);
}

// The same, told apart: a keyed pixel whose ray passes through one of the
// `windows` (Box3s around a set's window openings) is sky, which is fine;
// any other is a hole in the set. Without this a set's windows read as
// missing walls and every shot of the loft was rejected.
export function voids(renderer, scene, cam, windows = [], { hide = [] } = {}) {
  const b = drawKeyed(renderer, scene, cam, hide);
  cam.updateMatrixWorld(true);
  const ray = new THREE.Ray(), v = new THREE.Vector3();
  let sky = 0, bad = 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (!isKey(b, (y * W + x) * 4)) continue;
    v.set(((x + 0.5) / W) * 2 - 1, ((y + 0.5) / H) * 2 - 1, 0.5).unproject(cam);
    ray.set(cam.position, v.sub(cam.position).normalize());
    if (windows.some((w) => ray.intersectsBox(w))) sky++; else bad++;
  }
  return { holes: (100 * bad) / (W * H), sky: (100 * sky) / (W * H) };
}

// How far the camera is from anything, in six directions, on the GPU: the
// nearest surface to the side and the drop to the ground below. A city's
// two million triangles make the vertex-distance version far too slow.
export function clearanceAt(renderer, scene, pos) {
  const r = probe(renderer, scene, pos);
  return Math.min(r.clear_side, r.floor_below ?? Infinity, r.ceiling_above ?? Infinity);
}

// Occlusion: draw the target flat red over a black scene and count red
// pixels; then the target alone. The ratio is how much of it is actually
// visible. `subject` is { meshes: Set, box?: Box3 }; with a box, only the
// part of those meshes inside it counts — a region of an unsplit scan.
const _black = new THREE.MeshBasicMaterial({ color: 0x000000 });
export function visibility(renderer, scene, cam, subject) {
  target();
  renderer.localClippingEnabled = true;
  const meshes = subject.meshes, box = subject.box;
  const planes = box ? [
    new THREE.Plane(new THREE.Vector3(1, 0, 0), -box.min.x), new THREE.Plane(new THREE.Vector3(-1, 0, 0), box.max.x),
    new THREE.Plane(new THREE.Vector3(0, 1, 0), -box.min.y), new THREE.Plane(new THREE.Vector3(0, -1, 0), box.max.y),
    new THREE.Plane(new THREE.Vector3(0, 0, 1), -box.min.z), new THREE.Plane(new THREE.Vector3(0, 0, -1), box.max.z)] : [];
  const red = new THREE.MeshBasicMaterial({ color: 0xff0000, clippingPlanes: planes,
    depthFunc: THREE.LessEqualDepth, side: THREE.DoubleSide });
  const saved = [];
  scene.traverse((o) => { if (o.isMesh) saved.push([o, o.material, o.visible]); });
  const bg = scene.background, env = scene.environment, fog = scene.fog, auto = renderer.autoClear;
  scene.environment = null; scene.fog = null;
  const count = () => {
    renderer.readRenderTargetPixels(_rt, 0, 0, W, H, _buf);
    let n = 0; for (let i = 0; i < _buf.length; i += 4) if (_buf[i] > 100 && _buf[i + 1] < 60) n++;
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
  scene.background = bg; scene.environment = env; scene.fog = fog; red.dispose();
  return { visible: alone ? seen / alone : 0, coverage: alone / (W * H) };
}

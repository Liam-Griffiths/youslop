// The pictures Claude identifies a model from — different for each kind,
// because what a picture can tell depends on what the model is
// (docs/3d-explainer.md, step 3):
//
//   object         six views round it, labelled by the side the camera is on
//   interior       four views from inside, at eye height
//   set            the same four from inside, plus one from outside
//   aerial/modelled site
//                  straight down with a labelled coordinate grid (so Claude
//                  can say where the subject is), plus one oblique view
//
// Drawn in the model's own file units, with no heading or scale — the same
// space the intake analysis uses — so grid coordinates Claude reads off the
// top view map straight back onto the model.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { points, fit } from './core.js';

const W = 768, H = 432;

// Views of an object, by the side of it the camera stands on.
export const OBJECT_VIEWS = [
  { id: 'A', az: 0, el: 10, side: '+z' },
  { id: 'B', az: 90, el: 10, side: '+x' },
  { id: 'C', az: 180, el: 10, side: '-z' },
  { id: 'D', az: 270, el: 10, side: '-x' },
  { id: 'E', az: 45, el: 28, side: 'between +z and +x, above' },
  { id: 'F', top: true, side: 'directly above (top of the picture is -z)' },
];

const niceStep = (span, lines = 10) => {
  const raw = span / lines, p = Math.pow(10, Math.floor(Math.log10(raw)));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || p * 10;
};

// Straight down on `rect` ([x0, z0, x1, z1], model units) with a labelled grid
// of about `lines` lines across. Big enough to read: locating a subject on a
// map is where a vision model is weakest, so it gets pixels and a fine grid.
const GW = 1280, GH = 720;
async function gridTop(renderer, scene, rect, box, lines) {
  const cx = (rect[0] + rect[2]) / 2, cz = (rect[1] + rect[3]) / 2;
  const half = Math.max((rect[2] - rect[0]) / GW, (rect[3] - rect[1]) / GH) * 1.04 / 2;
  const sizeY = box.max.y - box.min.y;
  const ortho = new THREE.OrthographicCamera(-half * GW, half * GW, half * GH, -half * GH, 0.01, sizeY * 10 + 10);
  ortho.position.set(cx, box.max.y + sizeY + 1, cz); ortho.up.set(0, 0, -1); ortho.lookAt(cx, box.min.y, cz);
  ortho.updateProjectionMatrix();
  const keep = renderer.getSize(new THREE.Vector2());
  renderer.setSize(GW, GH, false); renderer.render(scene, ortho);
  const upp = 2 * half, step = niceStep(Math.max(rect[2] - rect[0], rect[3] - rect[1]), lines);
  const cv = document.createElement('canvas'); cv.width = GW; cv.height = GH;
  const g = cv.getContext('2d'); g.drawImage(renderer.domElement, 0, 0, GW, GH);
  renderer.setSize(keep.x, keep.y, false);
  g.lineWidth = 1; g.font = 'bold 13px sans-serif';
  const px = (x) => GW / 2 + (x - cx) / upp, py = (z) => GH / 2 + (z - cz) / upp;
  const label = (t, x, y) => { g.fillStyle = 'rgba(0,0,0,.6)'; g.fillRect(x - 1, y - 12, g.measureText(t).width + 4, 15); g.fillStyle = '#ff0'; g.fillText(t, x + 1, y); };
  for (let x = Math.ceil((cx - half * GW) / step) * step; x < cx + half * GW; x += step) {
    g.strokeStyle = 'rgba(255,40,40,.8)'; g.beginPath(); g.moveTo(px(x), 0); g.lineTo(px(x), GH); g.stroke();
    label(`x ${+x.toFixed(4)}`, px(x) + 2, 14);
  }
  for (let z = Math.ceil((cz - half * GH) / step) * step; z < cz + half * GH; z += step) {
    g.strokeStyle = 'rgba(255,40,40,.8)'; g.beginPath(); g.moveTo(0, py(z)); g.lineTo(GW, py(z)); g.stroke();
    label(`z ${+z.toFixed(4)}`, 2, py(z) - 3);
  }
  return { step, upp, half, canvas: cv, blob: await new Promise((ok) => cv.toBlob(ok, 'image/jpeg', 0.85)),
           grid: { step, x: [cx - half * GW, cx + half * GW], z: [cz - half * GH, cz + half * GH] } };
}

// The second, closer look: the first answer's box with room around it and a
// finer grid, so the subject's box can be drawn tight (coarse-to-fine).
export async function renderZoom(renderer, inner, rect) {
  const parent = inner.parent, scene = new THREE.Scene();
  scene.add(inner); inner.updateMatrixWorld(true);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x555555, 1.2));
  try {
    const box = new THREE.Box3().setFromObject(inner);
    const w = rect[2] - rect[0], d = rect[3] - rect[1], m = Math.max(w, d) * 0.6;
    const r = [Math.max(box.min.x, rect[0] - m), Math.max(box.min.z, rect[1] - m), Math.min(box.max.x, rect[2] + m), Math.min(box.max.z, rect[3] + m)];
    const top = await gridTop(renderer, scene, r, box, 12);
    return { caption: `Closer view, straight down, grid in model units every ${top.step} (x grows to the right, z grows downward)`, blob: top.blob, grid: top.grid };
  } finally {
    pmrem.dispose();
    if (parent) parent.add(inner);
    inner.updateMatrixWorld(true);
  }
}

// How tall the subject is, in model units: the highest point inside its box
// above the ground around it — for checking a known height ("towers 69 m").
export function regionHeight(inner, rect) {
  inner.updateMatrixWorld(true);
  const parentInv = new THREE.Matrix4().copy(inner.parent.matrixWorld).invert();
  const pts = points([inner], 60000).map((p) => p.applyMatrix4(parentInv));
  const inside = pts.filter((p) => p.x >= rect[0] && p.x <= rect[2] && p.z >= rect[1] && p.z <= rect[3]);
  const w = rect[2] - rect[0], d = rect[3] - rect[1];
  const ring = pts.filter((p) => p.x >= rect[0] - w && p.x <= rect[2] + w && p.z >= rect[1] - d && p.z <= rect[3] + d).map((p) => p.y).sort((a, b) => a - b);
  if (!inside.length || !ring.length) return null;
  return inside.reduce((mx, p) => Math.max(mx, p.y), -Infinity) - ring[Math.floor(ring.length * 0.05)];
}

export async function renderViews(renderer, inner, analysis, kind) {
  const parent = inner.parent, scene = new THREE.Scene();
  scene.add(inner); inner.updateMatrixWorld(true);
  const keepSize = renderer.getSize(new THREE.Vector2()), keepRatio = renderer.getPixelRatio();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.background = new THREE.Color(0x8e98a4);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x555555, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(1, 2, 1.4); scene.add(sun);
  renderer.setPixelRatio(1); renderer.setSize(W, H, false);
  const cam = new THREE.PerspectiveCamera(40, W / H, 0.01, 1e6);
  const out = [], meta = {};
  const snap = async (caption, draw) => {
    renderer.render(scene, cam);
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const g = cv.getContext('2d'); g.drawImage(renderer.domElement, 0, 0, W, H);
    if (draw) draw(g);
    out.push({ caption, blob: await new Promise((ok) => cv.toBlob(ok, 'image/jpeg', 0.82)) });
  };
  try {
    const box = new THREE.Box3().setFromObject(inner), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const pts = points([inner], 3000), R = size.length() / 2;
    if (kind === 'object') {
      for (const v of OBJECT_VIEWS) {
        if (v.top) {
          cam.position.set(c.x, box.max.y + R * 2.5, c.z); cam.up.set(0, 0, -1); cam.lookAt(c);
          cam.near = R * 0.05; cam.far = R * 10; cam.updateProjectionMatrix();
          // frame it: distance for the larger of the two footprint sides
          const d = Math.max(size.x / cam.aspect, size.z) / 2 / Math.tan(THREE.MathUtils.degToRad(cam.fov / 2)) * 1.15;
          cam.position.set(c.x, box.max.y + d, c.z); cam.lookAt(c.x, box.max.y - 1, c.z);
        } else {
          cam.up.set(0, 1, 0);
          fit(cam, pts, { az: v.az, el: v.el, fill: 0.8, sceneRadius: R });
        }
        await snap(`View ${v.id}: camera on the ${v.side} side`);
      }
    } else if (kind === 'interior' || kind === 'set') {
      const rc = analysis.room_centre || [c.x, c.z];
      const f = analysis.floor_y ?? box.min.y, ce = analysis.ceiling_y ?? box.max.y;
      const eye = new THREE.Vector3(rc[0], f + (ce - f) * 0.42, rc[1]);
      cam.fov = 70; cam.near = 0.01; cam.far = R * 20; cam.updateProjectionMatrix(); cam.up.set(0, 1, 0);
      for (const [id, dir, name] of [['A', [0, 0, -1], '-z'], ['B', [1, 0, 0], '+x'], ['C', [0, 0, 1], '+z'], ['D', [-1, 0, 0], '-x']]) {
        cam.position.copy(eye); cam.lookAt(eye.clone().add(new THREE.Vector3(...dir)));
        await snap(`View ${id}: from the middle of the room at eye height, looking toward ${name}`);
      }
      if (kind === 'set') {
        cam.fov = 40; cam.updateProjectionMatrix();
        fit(cam, pts, { az: 35, el: 30, fill: 0.85, sceneRadius: R });
        await snap('View E: the whole model from outside, above');
      }
    } else {
      // a site: straight down, orthographic, with a labelled grid in model units
      const top = await gridTop(renderer, scene, [box.min.x, box.min.z, box.max.x, box.max.z], box, 22);
      out.push({ caption: `View A: straight down, with a grid in model units every ${top.step} (x grows to the right, z grows downward; the top of the picture is -z)`,
                 blob: top.blob });
      meta.grid = top.grid;
      cam.up.set(0, 1, 0);
      fit(cam, pts, { az: 35, el: 35, fill: 0.85, sceneRadius: R });
      await snap('View B: the whole model from above at an angle, the camera on the +z/+x side');
    }
    meta.size_units = size.toArray().map((v) => +v.toFixed(4));
    meta.min = box.min.toArray().map((v) => +v.toFixed(4));
    return { views: out, meta };
  } finally {
    pmrem.dispose();
    renderer.setPixelRatio(keepRatio); renderer.setSize(keepSize.x, keepSize.y, false);
    if (parent) parent.add(inner);
    inner.updateMatrixWorld(true);
  }
}

// ------------------------------------------------------------------ parts
// Each named part highlighted in context, six to a sheet, numbered. Paired
// with where each part sits — measured here, relative to the model's own
// front — because a picture alone cannot reliably say which of four engines
// is the left inboard one, and a name that gets left and right wrong would
// send a close-up to the wrong engine.
const TW = 400, TH = 225, PER_SHEET = 6;

export async function renderParts(renderer, inner, nodes, heading = 0) {
  const parent = inner.parent, scene = new THREE.Scene();
  scene.add(inner); inner.updateMatrixWorld(true);
  const keepSize = renderer.getSize(new THREE.Vector2()), keepRatio = renderer.getPixelRatio();
  const saved = [];
  inner.traverse((o) => { if (o.isMesh) saved.push([o, o.material]); });
  const ghost = new THREE.MeshBasicMaterial({ color: 0xb8c0cc, transparent: true, opacity: 0.22, depthWrite: false });
  const hot = new THREE.MeshBasicMaterial({ color: 0xff6a00 });
  scene.background = new THREE.Color(0x1d232a);
  renderer.setPixelRatio(1); renderer.setSize(TW, TH, false);
  const cam = new THREE.PerspectiveCamera(35, TW / TH, 0.01, 1e6);
  try {
    const box = new THREE.Box3().setFromObject(inner), c = box.getCenter(new THREE.Vector3()), half = box.getSize(new THREE.Vector3()).multiplyScalar(0.5);
    const pts = points([inner], 3000), R = half.length();
    // the model's own frame: heading turns its front to +z, so its own left is +x
    const toOwn = (v) => v.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(heading));
    // the model's half-width and half-length in its own frame, from its points
    const ownHalf = pts.reduce((h, p) => { const o = toOwn(p.clone().sub(c)); h.x = Math.max(h.x, Math.abs(o.x)); h.z = Math.max(h.z, Math.abs(o.z)); return h; },
      new THREE.Vector3());
    const found = nodes.map((n) => ({ node: n, obj: inner.getObjectByName(n) })).filter((x) => x.obj);
    const table = [], sheets = [];
    for (let s = 0; s < found.length; s += PER_SHEET) {
      const cv = document.createElement('canvas'); cv.width = TW * 2; cv.height = TH * 3;
      const g = cv.getContext('2d'); g.fillStyle = '#1d232a'; g.fillRect(0, 0, cv.width, cv.height);
      for (let k = 0; k < PER_SHEET && s + k < found.length; k++) {
        const { node, obj } = found[s + k], num = s + k + 1;
        const meshes = new Set(); obj.traverse((o) => { if (o.isMesh) meshes.add(o); });
        saved.forEach(([o]) => { o.material = meshes.has(o) ? hot : ghost; });
        const pb = new THREE.Box3().setFromObject(obj), pc = pb.getCenter(new THREE.Vector3());
        const own = toOwn(pc.clone().sub(c));
        table.push({ num, node,
          side: +(own.x / (ownHalf.x || 1)).toFixed(2),        // + = the model's own left, - = its right
          fore: +(own.z / (ownHalf.z || 1)).toFixed(2),        // + = toward its front
          height: +((pc.y - box.min.y) / ((box.max.y - box.min.y) || 1)).toFixed(2) });
        // look from the side the part is on, a little above, the whole model in frame
        const dir = pc.clone().sub(c).setY(0);
        const az = dir.lengthSq() > 1e-9 ? THREE.MathUtils.radToDeg(Math.atan2(dir.x, dir.z)) : 35;
        cam.up.set(0, 1, 0);
        fit(cam, pts, { az, el: 28, fill: 0.86, sceneRadius: R });
        renderer.render(scene, cam);
        const x = (k % 2) * TW, y = Math.floor(k / 2) * TH;
        g.drawImage(renderer.domElement, x, y, TW, TH);
        g.fillStyle = 'rgba(0,0,0,.65)'; g.fillRect(x + 4, y + 4, 34, 26);
        g.fillStyle = '#fff'; g.font = 'bold 20px sans-serif'; g.fillText(String(num), x + 10, y + 24);
        g.strokeStyle = '#000'; g.strokeRect(x + 0.5, y + 0.5, TW - 1, TH - 1);
      }
      sheets.push({ caption: `Parts ${s + 1}–${Math.min(s + PER_SHEET, found.length)}, each highlighted in orange in its numbered tile`,
                    blob: await new Promise((ok) => cv.toBlob(ok, 'image/jpeg', 0.85)) });
    }
    return { sheets, table };
  } finally {
    saved.forEach(([o, m]) => { o.material = m; });
    ghost.dispose(); hot.dispose();
    renderer.setPixelRatio(keepRatio); renderer.setSize(keepSize.x, keepSize.y, false);
    if (parent) parent.add(inner);
    inner.updateMatrixWorld(true);
  }
}

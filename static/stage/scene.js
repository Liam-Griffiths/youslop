// A scene: the cast members one shot shows, on one stage. Shared by the
// headless solver and renderer (run.js) and the Stage tab's preview, so a
// shot is checked and drawn against exactly the same layout.
//
// A scene is named by its models, in order — the Flyer alone is one scene,
// the Flyer beside the A380 another — and the layout follows from them:
//
//   one model    at the origin, its front (+z) toward the default camera
//   several      side by side along x at true scale, fronts aligned, largest
//                first, a gap of a sixth of the widest between them.
//                Only objects line up; a room or a site is a scene alone.
import * as THREE from 'three';
import { loadModel, boxOf } from './core.js';

export const sceneKey = (entries) => entries.map((e) => e.manifest.id).join('+');

// `entries`: [{ sid, manifest, url? }] — a cast subject and the library
// model playing it. `url` overrides where the GLB is fetched from (the
// headless pages serve the library themselves).
export async function buildScene(entries) {
  const holders = [];
  for (const e of entries) {
    const h = await loadModel(e.manifest, { url: e.url || null });
    h.userData.sid = e.sid;
    holders.push(h);
  }
  if (holders.length > 1) lineUp(holders);
  const scene = new THREE.Scene();
  holders.forEach((h) => scene.add(h));
  scene.updateMatrixWorld(true);
  const box = boxOf(...holders);
  const m = entries[0].manifest;
  const kind = holders.length > 1 ? 'object' : (m.kind || (m.analysis || {}).kind_auto || 'object');
  return {
    key: sceneKey(entries), scene, holders, kind, box,
    radius: box.getBoundingSphere(new THREE.Sphere()).radius,
    bySid: (sid) => holders.find((h) => h.userData.sid === sid) || null,
    dispose(renderer) { holders.forEach((h) => { scene.remove(h); disposeObject(h); }); if (renderer) renderer.renderLists.dispose(); },
  };
}

// Largest first along +x: the default three-quarter camera stands on the
// +x side, so the smallest model is nearest it and still reads.
function lineUp(given) {
  const sized = given.map((h) => { h.position.set(0, 0, 0); h.updateMatrixWorld(true); return [h, new THREE.Box3().setFromObject(h)]; });
  sized.sort((a, b) => b[1].getSize(new THREE.Vector3()).length() - a[1].getSize(new THREE.Vector3()).length());
  const holders = sized.map(([h]) => h), widths = sized.map(([, b]) => b);
  const gap = Math.max(...widths.map((b) => b.max.x - b.min.x)) / 6;
  let x = 0;
  holders.forEach((h, i) => {
    const b = widths[i];
    h.position.x = x - b.min.x;
    x += (b.max.x - b.min.x) + gap;
  });
  const shift = (x - gap) / 2;
  holders.forEach((h) => { h.position.x -= shift; h.updateMatrixWorld(true); });
}

// Free a model's geometry, materials and textures.
export function disposeObject(obj) {
  obj.traverse((o) => {
    if (!o.isMesh) return;
    o.geometry.dispose();
    for (const m of [].concat(o.material)) {
      for (const v of Object.values(m)) if (v && v.isTexture) v.dispose();
      m.dispose();
    }
  });
}

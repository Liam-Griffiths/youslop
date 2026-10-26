// Framing: where a camera stands so a set of points fills the frame.
//
// Pure three.js maths — no renderer, no DOM — so it runs under Node's test
// runner as well as in the page (tests/stage/). Framings are solved once, at
// a shot's start and end, and never per frame of a move: re-solving every
// frame is what made the spike's first camera bounce.
import * as THREE from 'three';

export const rad = THREE.MathUtils.degToRad;
export const deg = THREE.MathUtils.radToDeg;
export const lerp = (a, b, u) => a + (b - a) * u;
// One ease curve for every parameter of a move: in, out, and nothing between.
export const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const smoothstep = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
// The unit vector from a target toward a camera at azimuth `az` (0 = +z, the
// model's front; 90 = +x) and elevation `el`, in degrees.
export const bearing = (az, el) => new THREE.Vector3(
  Math.sin(rad(az)) * Math.cos(rad(el)), Math.sin(rad(el)), Math.cos(rad(az)) * Math.cos(rad(el)));

// Up to `max` vertices of the objects, in world space. Framing measures
// these, not bounding boxes: a box's empty corners pull a three-quarter view
// off centre. Meshes flagged `userData.set` (floors, skies) are skipped.
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

// Every `n`th point, for checks that only need the shape.
export const thin = (pts, n = 3000) => pts.filter((_, i) => i % Math.max(1, Math.floor(pts.length / n)) === 0);

// The points' extent on screen, in normalised device coordinates (-1..1).
// `behind` is set when any point is behind the camera's near plane.
export function extent(cam, pts) {
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
// at which their projection fills `fill` of the frame, centred on the
// projection rather than on the 3D centre. Returns a framing — target,
// bearing, distance — that a shot moves between.
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
  cam.up.set(0, 1, 0); cam.lookAt(target);
  cam.near = Math.max(0.05, dist * 0.02); cam.far = dist + sceneRadius * 15;
  cam.updateProjectionMatrix();
}

// Keep the points inside the safe area (|ndc| <= safe) by sliding the aim
// point and the camera together — never the bearing or the distance, so a
// reveal stays the move it was planned as.
export function keepInFrame(cam, pts, target, safe = 0.88) {
  for (let pass = 0; pass < 3; pass++) {
    const e = extent(cam, pts);
    const dx = e.x1 > safe ? e.x1 - safe : e.x0 < -safe ? e.x0 + safe : 0;
    const dy = e.y1 > safe ? e.y1 - safe : e.y0 < -safe ? e.y0 + safe : 0;
    if (!dx && !dy) return target;
    const dist = cam.position.distanceTo(target), halfH = Math.tan(rad(cam.fov / 2)) * dist, halfW = halfH * cam.aspect;
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1);
    const shift = right.multiplyScalar(dx * halfW).addScaledVector(up, dy * halfH);
    target.add(shift); cam.position.add(shift); cam.lookAt(target);
  }
  return target;
}

// Distance from a camera position to the nearest sampled point of anything.
// For big scans the GPU probe (gpu.js, clearanceAt) is the better measure.
export const clearance = (pos, pts) => pts.reduce((m, p) => Math.min(m, p.distanceTo(pos)), Infinity);

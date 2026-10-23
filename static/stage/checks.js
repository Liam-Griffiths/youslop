// The checks a shot must pass before a frame is drawn — the ones that need
// no GPU. Each walks the shot's poses (shot.js) with a camera of its own, so
// they run under Node's test runner too. The GPU checks — occlusion, the
// key-colour edge and voids, probe clearance — are in gpu.js; search.js runs
// both kinds for a shot, chosen by the model's limits.
//
// Thresholds are the spike's, each found by a failure someone saw. See
// docs/3d-explainer.md, step 8.
import * as THREE from 'three';
import { deg, rad } from './frame.js';
import { poseAt, applyPose, frameCount, FPS } from './shot.js';

export const LIMITS = {
  reversals: 1,          // per axis: ease in, ease out — a second one is a bounce
  turn_deg_s: 20,        // faster reads as a whip pan
  look_down_deg: 20,     // aerial scans melt near the ground
  level_deg: 0.5,        // interiors: a tilted camera leans the walls
  detail_px: 2.0,        // screen pixels per texel before a texture goes soft
};

const camFor = (aspect) => new THREE.PerspectiveCamera(35, aspect, 0.1, 1000);

// Direction changes in a series, ignoring wobble under 5% of its peak step.
export function reversals(series) {
  const v = series.slice(1).map((s, i) => s - series[i]);
  const peak = Math.max(0, ...v.map(Math.abs)) || 1, eps = peak * 0.05;
  let n = 0, last = 0;
  for (const x of v) { if (Math.abs(x) < eps) continue; const s = Math.sign(x); if (last && s !== last) n++; last = s; }
  return n;
}

// Every frame of the shot, undrawn: does the camera, or its subject on
// screen, change direction more than once on any axis, and does the view
// ever turn faster than a viewer can follow? The subject is the shot's own,
// not the whole scene — a pass over a building should track the building.
// Only subject points in front of the lens for the whole shot are tracked: a
// point that passes behind the camera (a room's near wall during a dolly)
// projects to wild screen positions and reads as a bounce that isn't there.
export function motion(shot, subjectPts, { fps = FPS, aspect = 16 / 9 } = {}) {
  const cam = camFor(aspect), N = frameCount(shot, fps);
  let sample = subjectPts.filter((_, i) => i % Math.max(1, Math.floor(subjectPts.length / 200)) === 0);
  const views = [], v = new THREE.Vector3();
  for (let i = 0; i < N; i++) {
    applyPose(cam, poseAt(shot, i, fps), { W: 1000 * aspect, H: 1000 });
    views.push({ pos: cam.position.clone(), dir: cam.getWorldDirection(new THREE.Vector3()),
                 view: cam.matrixWorldInverse.clone(), proj: cam.projectionMatrix.clone(), near: cam.near });
  }
  if (shot.kind !== 'turn') sample = sample.filter((p) => views.every((f) => v.copy(p).applyMatrix4(f.view).z < -f.near));
  const rows = views.map((f) => {
    let sx = 0, sy = 0;
    for (const p of sample) { v.copy(p).applyMatrix4(f.view).applyMatrix4(f.proj); sx += v.x; sy += v.y; }
    return { pos: f.pos, dir: f.dir, sx: sx / (sample.length || 1), sy: sy / (sample.length || 1) };
  });
  const turn = rows.slice(1).map((r, i) => deg(r.dir.angleTo(rows[i].dir)) * fps);
  const rev = {
    cam_x: reversals(rows.map((r) => r.pos.x)), cam_y: reversals(rows.map((r) => r.pos.y)),
    cam_z: reversals(rows.map((r) => r.pos.z)),
    subject_x: sample.length ? reversals(rows.map((r) => r.sx)) : 0,
    subject_y: sample.length ? reversals(rows.map((r) => r.sy)) : 0,
  };
  // A turn on the spot spins the subject across the screen by design; its
  // speed limit is what keeps it deliberate.
  if (shot.kind === 'turn') { rev.subject_x = 0; rev.subject_y = 0; }
  const peak = Math.max(0, ...turn);
  return { ok: Object.values(rev).every((n) => n <= LIMITS.reversals) && peak <= LIMITS.turn_deg_s,
           reversals: rev, peak_turn_deg_s: +peak.toFixed(1) };
}

// ------------------------------------------------------------- detail budget
// How many delivered pixels one texel covers at a distance. Always worked
// out at the delivered height (1080), never the preview's: a preview framed
// by its own size framed differently from the final render.
export const pxPerTexel = (dist, fov, texelsPerMetre, outH = 1080) =>
  (outH / 2) / (Math.max(1e-6, dist) * Math.tan(rad(fov / 2))) / texelsPerMetre;

// The nearest a camera may stand before one texel covers `maxPx` pixels.
export const nearestFor = (fov, texelsPerMetre, maxPx = LIMITS.detail_px, outH = 1080) =>
  (outH / 2) / (Math.tan(rad(fov / 2)) * maxPx * texelsPerMetre);

// The worst pixels-per-texel on the subject across the shot. `reach` is how
// far the subject's near side sits in front of its centre.
export function detail(shot, centre, reach, texelsPerMetre, { fps = FPS, outH = 1080, every = 10 } = {}) {
  let worst = 0;
  for (let i = 0, N = frameCount(shot, fps); i < N; i += every) {
    const p = poseAt(shot, i, fps);
    worst = Math.max(worst, pxPerTexel(p.pos.distanceTo(centre) - reach, p.fov, texelsPerMetre, outH));
  }
  return { ok: worst <= LIMITS.detail_px, px_per_texel: +worst.toFixed(2) };
}

// ------------------------------------------------------------- angle limits
// The shallowest the camera looks down at any frame (degrees below level).
export function lookDown(shot, { fps = FPS, every = 10 } = {}) {
  let min = 90;
  for (let i = 0, N = frameCount(shot, fps); i < N; i += every) {
    const p = poseAt(shot, i, fps), d = p.aim.clone().sub(p.pos).normalize();
    min = Math.min(min, -deg(Math.asin(d.y)));
  }
  return { ok: min >= LIMITS.look_down_deg, min_deg: +min.toFixed(1) };
}

// Level: the camera's view never tilts up or down, and its up stays +y.
// A lens shift is the way to show more ceiling or floor.
export function level(shot, { fps = FPS, every = 10 } = {}) {
  let worst = 0;
  for (let i = 0, N = frameCount(shot, fps); i < N; i += every) {
    const p = poseAt(shot, i, fps), d = p.aim.clone().sub(p.pos).normalize();
    worst = Math.max(worst, Math.abs(deg(Math.asin(d.y))), deg(p.up.angleTo(new THREE.Vector3(0, 1, 0))));
  }
  return { ok: worst <= LIMITS.level_deg, tilt_deg: +worst.toFixed(2) };
}

// ------------------------------------------------------------------- haze
// Where a horizontal ray from `o` leaves a rectangle {minX, maxX, minZ, maxZ}.
export function exitDistance(o, dir, rect) {
  let t = Infinity;
  if (dir.x > 1e-6) t = Math.min(t, (rect.maxX - o.x) / dir.x);
  if (dir.x < -1e-6) t = Math.min(t, (rect.minX - o.x) / dir.x);
  if (dir.z > 1e-6) t = Math.min(t, (rect.maxZ - o.z) / dir.z);
  if (dir.z < -1e-6) t = Math.min(t, (rect.minZ - o.z) / dir.z);
  return t;
}

// Haze for a site that ends at an edge: fixed for the whole shot (haze that
// changes during a move reads as weather), fully opaque before the edge in
// every direction the shot looks, and as gentle a ramp as the subject allows
// — the subject is never more than `allowed` hazed. Returns {near, far} for
// THREE.Fog, or ok: false when the edge is too close for any haze to hide it
// without swallowing the subject.
export function haze(shot, rect, centre, reach, { allowed = 0.1, fps = FPS, aspect = 16 / 9, every = 10 } = {}) {
  const N = frameCount(shot, fps), up = new THREE.Vector3(0, 1, 0);
  let edge = Infinity, far = 0;
  for (let i = 0; i < N; i += every) {
    const p = poseAt(shot, i, fps), f = p.aim.clone().sub(p.pos).setY(0);
    if (f.lengthSq() < 1e-9) continue;            // looking straight down: no horizon to hide
    f.normalize();
    const hfov = 2 * Math.atan(Math.tan(rad(p.fov / 2)) * aspect);
    for (let k = -4; k <= 4; k++) edge = Math.min(edge, exitDistance(p.pos, f.clone().applyAxisAngle(up, (k / 4) * hfov / 2), rect));
  }
  if (!isFinite(edge)) return { ok: true, none: true };
  far = edge * 0.9;
  const at = (d, n) => Math.min(1, Math.max(0, (d - n) / (far - n)));
  const worst = (n) => {
    let w = 0;
    for (let i = 0; i < N; i += every) w = Math.max(w, at(poseAt(shot, i, fps).pos.distanceTo(centre) + reach, n));
    return w;
  };
  let near = far * 0.25, subj = worst(near);
  while (subj > allowed && near < far * 0.97) { near = Math.min(far * 0.97, near + far * 0.02); subj = worst(near); }
  return { ok: subj <= allowed, near: +near.toFixed(3), far: +far.toFixed(3), edge: +edge.toFixed(3), subject_haze: +subj.toFixed(2) };
}

// ----------------------------------------------------------------- flats
// A backdrop flat (a painted card) read face-on is scenery; side-on it is
// cardboard. The worst angle between a view ray and any flat's normal.
export function flatAngle(shot, flats, { fps = FPS, every = 15 } = {}) {
  let worst = 0;
  for (let i = 0, N = frameCount(shot, fps); i < N; i += every) {
    const p = poseAt(shot, i, fps);
    for (const f of flats) {
      const v = new THREE.Vector3().fromArray(f.centre).sub(p.pos).normalize();
      worst = Math.max(worst, deg(Math.acos(Math.min(1, Math.abs(v.dot(new THREE.Vector3().fromArray(f.normal)))))));
    }
  }
  return { ok: worst <= 50, worst_deg: Math.round(worst) };
}

// The share of sampled subject points that fall outside the frame's safe
// edge (|ndc| > 0.97): a subject that is not whole.
export function cutOff(cam, pts, every = 50) {
  cam.updateMatrixWorld(true);
  const v = new THREE.Vector3(); let out = 0, n = 0;
  for (let i = 0; i < pts.length; i += every) { n++; v.copy(pts[i]).project(cam); if (Math.abs(v.x) > 0.97 || Math.abs(v.y) > 0.97 || v.z > 1) out++; }
  return n ? out / n : 0;
}

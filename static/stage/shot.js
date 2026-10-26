// A shot is plain JSON — it can be stored on a project, edited by hand in the
// Stage tab, and drawn frame by frame in any order — and the camera at frame
// `i` is a pure function of it. Every kind follows the same rule the spike
// earned: solve the framings once, then move every parameter one way on one
// ease curve. No kind re-aims the camera per frame.
//
//   move      between two framings {target, az, el, dist}: distance on a log
//             scale (a push-in feels even), aim tied to distance, bearing
//             eased. Orbits, push-ins, pull-backs and reveals are all moves.
//   path      a straight dolly p0 -> p1 aimed a0 -> a1 (interiors, cranes)
//   turn      stand at one spot and turn: constant speed with smooth ramps,
//             integrated so the angle comes out exact (the hall's 360)
//   overhead  straight down, descending h0 -> h1 with a slow yaw (plans)
//   still     a locked-off frame
//
// Common fields: secs, fov (vertical degrees, fixed for the shot — a lens
// does not zoom mid-move), and shift (a lens shift as a fraction of the frame
// height: a level camera that still shows the ceiling without leaning walls).
// Positions are [x, y, z] in metres in the scene.
import * as THREE from 'three';
import { bearing, ease, lerp, smoothstep, rad } from './frame.js';

export const FPS = 30;
const V = (a) => new THREE.Vector3().fromArray(a);

export const frameCount = (shot, fps = FPS) => Math.max(2, Math.round((shot.secs || 1) * fps));

// A turn's angle at each frame, precomputed once per shot: speed ramps up
// over `ramp` of the shot, holds, ramps down, and the integral is scaled so
// the shot turns through exactly `degrees`.
const _turns = new WeakMap();
function turnAngles(shot, N) {
  const hit = _turns.get(shot);
  if (hit && hit.length === N) return hit;
  const ramp = shot.ramp ?? 0.15;
  const v = Array.from({ length: N }, (_, i) => smoothstep(i / (N * ramp)) * smoothstep((N - 1 - i) / (N * ramp)));
  const cum = [0];
  for (let i = 1; i < N; i++) cum.push(cum[i - 1] + (v[i - 1] + v[i]) / 2);
  const total = cum[N - 1] || 1, out = cum.map((c) => (shot.yaw0 || 0) + ((shot.degrees ?? 360) * c) / total);
  _turns.set(shot, out);
  return out;
}

// The camera at frame i: { pos, aim, up, fov, shift } (THREE.Vector3s).
export function poseAt(shot, i, fps = FPS) {
  const N = frameCount(shot, fps), t = Math.min(1, Math.max(0, i / (N - 1))), u = ease(t);
  const out = { up: new THREE.Vector3(0, 1, 0), fov: shot.fov || 35, shift: shot.shift || 0 };
  switch (shot.kind) {
    case 'move': {
      const a = shot.a, b = shot.b;
      const dist = Math.exp(lerp(Math.log(a.dist), Math.log(b.dist), u));
      // the aim travels in step with the distance, so a push-in toward a part
      // arrives on it as the camera arrives, never ahead or behind
      const w = Math.abs(b.dist - a.dist) > 1e-6 * a.dist ? (dist - a.dist) / (b.dist - a.dist) : u;
      out.aim = V(a.target).lerp(V(b.target), w);
      out.pos = out.aim.clone().addScaledVector(bearing(lerp(a.az, b.az, u), lerp(a.el, b.el, u)), dist);
      break;
    }
    case 'path':
      out.pos = V(shot.p0).lerp(V(shot.p1), u);
      out.aim = V(shot.a0).lerp(V(shot.a1 || shot.a0), u);
      break;
    case 'turn': {
      const y = rad(turnAngles(shot, N)[Math.round(t * (N - 1))]), p = rad(shot.pitch || 0);
      out.pos = V(shot.at);
      out.aim = out.pos.clone().add(new THREE.Vector3(Math.sin(y) * Math.cos(p), Math.sin(p), Math.cos(y) * Math.cos(p)));
      break;
    }
    case 'overhead': {
      const c = V(shot.centre), h = Math.exp(lerp(Math.log(shot.h0), Math.log(shot.h1 || shot.h0), u));
      const yaw = rad(lerp(shot.yaw0 || 0, shot.yaw1 ?? shot.yaw0 ?? 0, u));
      out.pos = new THREE.Vector3(c.x, c.y + h, c.z);
      out.aim = c;
      out.up.set(Math.sin(yaw), 0, -Math.cos(yaw));     // "up" on screen is north (-z) at yaw 0
      break;
    }
    case 'still':
      out.pos = V(shot.pos); out.aim = V(shot.aim);
      break;
    default:
      throw new Error(`unknown shot kind: ${shot.kind}`);
  }
  return out;
}

// Put a pose on a camera. `W`/`H` are only needed for a lens shift, which is
// a view offset of the full frame. Near and far come from the shot when it
// sets them, otherwise from the distance to the aim point.
export function applyPose(cam, pose, { W = 1920, H = 1080, near = null, far = null } = {}) {
  cam.position.copy(pose.pos); cam.up.copy(pose.up); cam.lookAt(pose.aim);
  cam.fov = pose.fov;
  const d = pose.pos.distanceTo(pose.aim);
  cam.near = near ?? Math.max(0.02, d * 0.02);
  cam.far = far ?? Math.max(d * 20, 100);
  if (pose.shift) cam.setViewOffset(W, H, 0, -Math.round(H * pose.shift), W, H);
  else if (cam.view) cam.clearViewOffset();
  cam.updateProjectionMatrix();
  cam.updateMatrixWorld(true);
}

// A setFrame(i) for the render loop and the checks.
export const driver = (cam, shot, opts = {}) => (i) => applyPose(cam, poseAt(shot, i, opts.fps), opts);

// A move from two framings as fit() returns them.
export function moveShot(a, b, { secs = 8, fov = 35 } = {}) {
  const f = (x) => ({ target: x.target.toArray(), az: x.az, el: x.el, dist: x.dist });
  return { kind: 'move', secs, fov, a: f(a), b: f(b) };
}

// The pure half of the stage solver: framing, shots, and the checks that
// need no GPU. The GPU checks are covered by the regression renders.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { fit, extent, points } from '../../static/stage/frame.js';
import { poseAt, applyPose, frameCount, moveShot } from '../../static/stage/shot.js';
import * as C from '../../static/stage/checks.js';
import { search, checkShot, withOptions } from '../../static/stage/search.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const cam = () => new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);
// A plane-ish cloud: 40 m wide, 10 m tall, 70 m long, standing on y = 0.
function cloud(n = 2000, w = 40, h = 10, l = 70) {
  let s = 1; const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  return Array.from({ length: n }, () => V((rnd() - 0.5) * w, rnd() * h, (rnd() - 0.5) * l));
}
const PTS = cloud(), CENTRE = new THREE.Sphere().setFromPoints(PTS).center;

test('fit fills the asked share of the frame, centred', () => {
  const c = cam();
  for (const [az, el, fill] of [[0, 10, 0.7], [135, 30, 0.5], [270, 60, 0.85]]) {
    fit(c, PTS, { az, el, fill });
    const e = extent(c, PTS);
    assert.ok(!e.behind);
    assert.ok(Math.abs(e.fill - fill) < 0.01, `fill ${e.fill} for ${fill}`);
    assert.ok(Math.abs(e.x0 + e.x1) < 0.02 && Math.abs(e.y0 + e.y1) < 0.02, 'centred on its projection');
  }
});

test('a move starts and ends exactly on its two framings', () => {
  const c = cam(), a = fit(c, PTS, { az: 30, el: 15, fill: 0.5 }), b = fit(c, PTS, { az: 80, el: 8, fill: 0.8 });
  const shot = moveShot(a, b, { secs: 6 }), N = frameCount(shot);
  assert.equal(N, 180);
  assert.ok(poseAt(shot, 0).pos.distanceTo(a.pos) < 1e-6);
  assert.ok(poseAt(shot, N - 1).pos.distanceTo(b.pos) < 1e-6);
});

test('a solved move passes the motion check; a bouncing one does not', () => {
  const c = cam(), a = fit(c, PTS, { az: -40, el: 20, fill: 0.45 }), b = fit(c, PTS, { az: 10, el: 10, fill: 0.75 });
  const good = C.motion(moveShot(a, b, { secs: 8 }), PTS);
  assert.ok(good.ok, JSON.stringify(good));
  // The spike's first failure: a camera corrected per frame went up, down
  // and up again. No shot kind can do that, so the series stands in for it.
  const N = 240, heights = Array.from({ length: N }, (_, i) => 20 + 3 * Math.sin((i / N) * Math.PI * 4));
  assert.ok(C.reversals(heights) > C.LIMITS.reversals);
  assert.equal(C.reversals(Array.from({ length: N }, (_, i) => 20 + 3 * Math.sin((i / N) * Math.PI))), 1, 'one rise and fall is a deliberate arc');
});

test('a 36 s turn goes round exactly once, never faster than 20°/s', () => {
  const shot = { kind: 'turn', secs: 36, fov: 50, at: [0, 1.6, 0], yaw0: 180, degrees: 360, shift: 0.14 };
  const N = frameCount(shot);
  const d0 = poseAt(shot, 0), d1 = poseAt(shot, N - 1);
  const dir = (p) => p.aim.clone().sub(p.pos);
  assert.ok(dir(d0).angleTo(dir(d1)) < 1e-6, 'ends where it began');
  const m = C.motion(shot, PTS);
  assert.ok(m.ok && m.peak_turn_deg_s < 13, JSON.stringify(m));
  assert.ok(C.level(shot).ok, 'level, with the lens shifted rather than tilted');
});

test('a whip pan fails the turn-speed limit', () => {
  const shot = { kind: 'turn', secs: 3, fov: 50, at: [0, 1.6, 0], degrees: 180 };
  assert.equal(C.motion(shot, PTS).ok, false);
});

test('lens shift is applied as a view offset, not a tilt', () => {
  const c = cam(), p = poseAt({ kind: 'still', secs: 1, fov: 50, pos: [0, 1.6, 0], aim: [0, 1.6, -5], shift: 0.14 }, 0);
  applyPose(c, p, { W: 1920, H: 1080 });
  assert.equal(c.view.offsetY, -Math.round(1080 * 0.14));
  const d = c.getWorldDirection(new THREE.Vector3());
  assert.ok(Math.abs(d.y) < 1e-9);
});

test('the detail budget: nearestFor and pxPerTexel agree, at the delivered height', () => {
  for (const fov of [16, 24, 35]) {
    const d = C.nearestFor(fov, 3.6, 2.0);
    assert.ok(Math.abs(C.pxPerTexel(d, fov, 3.6) - 2.0) < 1e-9);
  }
  // the Abbey scan: 45.3 texels per file unit at 12.5 m per unit is a texel
  // of about 28 cm, so a 35° lens may come no nearer than about 237 m
  const tpm = 45.3 / (156 / 12.44);
  assert.ok(Math.abs(C.nearestFor(35, tpm) - 237) < 3, String(C.nearestFor(35, tpm)));
});

test('an aerial scan must always look down at least 20°', () => {
  const low = { kind: 'move', secs: 6, fov: 35, a: { target: [0, 0, 0], az: 0, el: 12, dist: 300 }, b: { target: [0, 0, 0], az: 20, el: 30, dist: 250 } };
  const ok = { ...low, a: { ...low.a, el: 38 }, b: { ...low.b, el: 48 } };
  assert.equal(C.lookDown(low).ok, false);
  assert.ok(C.lookDown(ok).ok);
  const top = { kind: 'overhead', secs: 8, fov: 35, centre: [0, 0, 0], h0: 300, h1: 270, yaw0: -8, yaw1: 8 };
  assert.ok(C.lookDown(top).min_deg > 89);
});

test('haze is opaque before the edge and leaves the subject clear', () => {
  const rect = { minX: -3000, maxX: 3000, minZ: -3000, maxZ: 3000 };
  const shot = { kind: 'move', secs: 9, fov: 35, a: { target: [0, 150, 0], az: 115, el: 16, dist: 1800 }, b: { target: [0, 150, 0], az: 100, el: 9, dist: 700 } };
  const h = C.haze(shot, rect, V(0, 150, 0), 50, { allowed: 0.6 });
  assert.ok(h.ok, JSON.stringify(h));
  assert.ok(h.far < h.edge && h.near < h.far);
  // a camera standing near the edge cannot hide it without hazing the subject
  const tight = { minX: -900, maxX: 900, minZ: -900, maxZ: 900 };
  assert.equal(C.haze(shot, tight, V(0, 150, 0), 50, { allowed: 0.1 }).ok, false);
});

test('search takes the nearest passing candidate, and flags the best when none passes', () => {
  const c = cam();
  const ctx = { subject: { pts: PTS, centre: CENTRE, reach: 20 }, limits: ['no_low_angles'] };
  const build = (k) => moveShot(fit(c, PTS, { az: k.az, el: k.el, fill: k.fill }), fit(c, PTS, { az: k.az + 15, el: k.el - 5, fill: k.fill + 0.1 }), { secs: 6, fov: k.fov });
  const cands = withOptions([5, 15, 25, 35, 45].map((el) => ({ az: 30, el, dev: Math.abs(el - 5) })), [{ fill: 0.55, cost: 0 }]);
  const r = search(cands, build, (s, k, quick) => checkShot(s, ctx, quick));
  assert.equal(r.flagged, false);
  assert.equal(r.k.el, 25, 'the first elevation that keeps looking down 20° through the move');
  const none = search(cands.slice(0, 2), build, (s, k, quick) => checkShot(s, ctx, quick));
  assert.equal(none.flagged, true);
  assert.ok(none.flag.includes('look_down'));
});

test('points samples meshes and skips set dressing', () => {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2)));
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(1000, 1000)); floor.userData.set = true; g.add(floor);
  const pts = points([g]);
  assert.ok(pts.length > 0 && pts.every((p) => Math.abs(p.x) <= 1.0001));
});

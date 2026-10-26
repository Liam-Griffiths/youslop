// The regression suite's reference shots: for each of the six spike models,
// the shots that taught a rule (docs/3d-explainer.md, step 3b–3e), each run
// through the solver exactly as the app will run it. Models are found in the
// library by their file name, so the suite runs against whatever library
// YOUSLOP_DATA points at.
//
// A case is { name, cands, build(k) -> shot, ctx, look?, max? }. A fixed shot is a
// search with one candidate. `look` is how the contact sheet draws it —
// never part of what is checked.
import { THREE, standing } from '/static/stage/core.js';
import { points } from '/static/stage/frame.js';
import { moveShot } from '/static/stage/shot.js';
import { withOptions } from '/static/stage/search.js';
import { helpers } from '/static/stage/plan.js';

const V = (...a) => new THREE.Vector3(...a);
const meshesOf = (o) => { const s = new Set(); o.traverse((m) => { if (m.isMesh) s.add(m); }); return s; };
const centreOf = (pts) => new THREE.Sphere().setFromPoints(pts).center;
// Vertical field of view for a horizontal one, at 16:9.
const vfov = (h) => THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(h / 2)) / (16 / 9)));

// The helpers every case gets are the planner's own (plan.js).
export { helpers };

// An object: an establishing orbit of the whole thing, slow, a quarter-turn
// at most, lit by our set.
function establish(h, holder, { az = 35, el = 15, radius }) {
  const pts = points([holder], 3000), meshes = meshesOf(holder);
  const cands = [];
  for (const d of [0, 15, -15, 30, -30]) for (const e of [el, el + 10, el - 8]) cands.push({ az: az + d, el: e, dev: Math.abs(d) + Math.abs(e - el) });
  return {
    name: 'establish', cands,
    build: (k) => moveShot(h.fitAt(pts, k.az, k.el, 0.6, radius), h.fitAt(pts, k.az + 25, k.el + 5, 0.68, radius), { secs: 10 }),
    ctx: { subject: { pts, centre: centreOf(pts), reach: 0, meshes }, limits: h.limits },
    look: 'set',
  };
}

export const CASES = {
  // ---------------------------------------------------------------- objects
  'airbus_a380.glb': (holder, cam) => {
    const h = helpers(holder, cam), radius = new THREE.Box3().setFromObject(holder).getBoundingSphere(new THREE.Sphere()).radius;
    const nodeName = Object.entries(h.manifest.identity?.parts || {}).find(([, v]) => v === 'left wing')?.[0];
    const wing = nodeName && h.node(nodeName);
    const out = [establish(h, holder, { az: 35, el: 12, radius })];
    if (wing) {
      // The near wing and its engines: a move that ends closer, the wing
      // running out of the frame's edge allowed — it is a close-up.
      const pts = points([wing], 3000), cands = [];
      for (const d of [0, 15, -15, 30, -30, 45, -45]) for (const el of [10, 20, 35, 50]) cands.push({ az: 90 + d, el, dev: Math.abs(d) + Math.abs(el - 10) * 0.5 });
      out.push({
        name: 'left_wing', cands,
        build: (k) => moveShot(h.fitAt(pts, k.az, k.el, 0.55, radius), h.fitAt(pts, k.az + 15, k.el - 4, 0.7, radius), { secs: 8 }),
        ctx: { subject: { pts, centre: centreOf(pts), reach: 10, meshes: meshesOf(wing) }, limits: h.limits, gate: 2 },
        look: 'set',
      });
    }
    return out;
  },

  '1903_wright_flyer.glb': (holder, cam) => {
    const h = helpers(holder, cam), radius = new THREE.Box3().setFromObject(holder).getBoundingSphere(new THREE.Sphere()).radius;
    const pts = points([holder], 3000);
    return [
      establish(h, holder, { az: 35, el: 15, radius }),
      // A slow push-in from three-quarters: the bare scan, tinted, in our light.
      { name: 'push_in', cands: [0, 15, -15, 30].map((d) => ({ az: 30 + d, el: 20, dev: Math.abs(d) })),
        build: (k) => moveShot(h.fitAt(pts, k.az, k.el, 0.55, radius), h.fitAt(pts, k.az, k.el, 0.85, radius), { secs: 8 }),
        ctx: { subject: { pts, centre: centreOf(pts), reach: 0, meshes: meshesOf(holder) }, limits: h.limits },
        look: 'set' },
    ];
  },

  // ---------------------------------------------------------------- interior
  'the_king_s_hall.glb': (holder, cam) => {
    const h = helpers(holder, cam), st = standing(holder, 1.6), pts = points([holder], 3000);
    const size = new THREE.Box3().setFromObject(holder).getSize(V());
    const yaw0 = size.z >= size.x ? 180 : 90;      // down the long axis
    const fov = vfov(78), at = V(st.centre.x, st.eye, st.centre.z);
    const ctx = { subject: { pts, centre: st.centre, reach: 0, whole: false }, limits: h.limits };
    return [
      // The 360: steady ~10°/s with smooth ramps, level, from the room's middle.
      { name: 'turn_360', cands: [{}],
        build: () => ({ kind: 'turn', secs: 36, fov, at: at.toArray(), yaw0, degrees: 360, pitch: 0, ramp: 0.12 }),
        ctx, look: 'baked' },
      // The painted ceiling by lens shift, not tilt: a level dolly down the room.
      { name: 'ceiling_shift', cands: [0.22, 0.3, 0.15].map((shift, i) => ({ shift, dev: i })),
        build: (k) => {
          const dir = V(Math.sin(THREE.MathUtils.degToRad(yaw0)), 0, Math.cos(THREE.MathUtils.degToRad(yaw0)));
          const p0 = at.clone().addScaledVector(dir, -2), p1 = at.clone().addScaledVector(dir, 1);
          return { kind: 'path', secs: 10, fov, shift: k.shift, p0: p0.toArray(), p1: p1.toArray(),
                   a0: p0.clone().addScaledVector(dir, 10).toArray(), a1: p1.clone().addScaledVector(dir, 10).toArray() };
        },
        ctx, look: 'baked' },
    ];
  },

  // ---------------------------------------------------------------- sites
  'westminster_abbey_london_uk.glb': (holder, cam) => {
    const h = helpers(holder, cam), box = h.manifest.identity?.subject?.box;
    if (!box) return [];
    const pts = h.inRect(box), centre = centreOf(pts), meshes = meshesOf(holder);
    const radius = new THREE.Box3().setFromObject(holder).getBoundingSphere(new THREE.Sphere()).radius;
    // Edge-aware: bearing, height, lens, framing, which way the orbit turns
    // and an aim slid off the subject toward the tile's middle are all free.
    // A long lens sees the same subject with less ground beyond it; a steeper
    // look and a tighter start leave less of the frame past the subject. The
    // spike's pick needed several (16°, much tighter than planned).
    const base = [];
    for (let d = 0; d < 360; d += 30) for (const el of [35, 45, 60]) {
      const off = Math.min(d, 360 - d);
      base.push({ az: (200 + d) % 360, el, dev: off * 0.1 + Math.abs(el - 35) * 0.2 });
    }
    let cands = withOptions(base, [{ fov: 35, cost: 0 }, { fov: 24, cost: 4 }, { fov: 16, cost: 8 }]);
    cands = withOptions(cands, [{ fill: 0.55, cost: 0 }, { fill: 0.72, cost: 3 }, { fill: 0.85, cost: 6 }]);
    cands = withOptions(cands, [{ turn: 20, cost: 0 }, { turn: -20, cost: 1 }]);
    cands = withOptions(cands, [{ slide: 0, cost: 0 }, { slide: 0.12, cost: 2 }, { slide: 0.25, cost: 4 }]);
    const sr = new THREE.Sphere().setFromPoints(pts).radius;
    const inward = holder.getWorldPosition(V()).sub(centre).setY(0).normalize();
    return [{
      name: 'subject_move', cands, max: 3000,
      build: (k) => {
        const a = h.fitAt(pts, k.az, k.el, k.fill, radius, k.fov);
        const b = h.fitAt(pts, k.az + k.turn, k.el, Math.min(0.9, k.fill + 0.07), radius, k.fov);
        for (const f of [a, b]) f.target.addScaledVector(inward, k.slide * sr);
        return moveShot(a, b, { secs: 10, fov: k.fov });
      },
      ctx: { subject: { pts, centre, reach: 0 }, limits: h.limits, texels: h.texels(meshes), detailMax: 3.5 },
      look: 'scan_sky',
    }];
  },

  'paris.glb': (holder, cam) => {
    const h = helpers(holder, cam), tower = h.node('Eiffel_Tower');
    if (!tower) return [];
    const pts = points([tower], 3000), centre = centreOf(pts), meshes = meshesOf(tower);
    const radius = new THREE.Sphere().setFromPoints(pts).radius * 6;
    const towerH = new THREE.Box3().setFromObject(tower).getSize(V()).y;
    // A slow orbit; clearance is a gate (40 m, in units the model's scale
    // makes metres), and the haze hides the map's edge without the tower.
    const cands = [];
    for (const el of [8, 12, 16, 22]) for (const d of [0, 30, -30, 60]) cands.push({ az: 150 + d, el, dev: Math.abs(el - 12) + Math.abs(d) * 0.2 });
    return [{
      name: 'tower_orbit', cands,
      build: (k) => moveShot(h.fitAt(pts, k.az, k.el, 0.55, radius), h.fitAt(pts, k.az + 30, k.el + 3, 0.6, radius), { secs: 12 }),
      ctx: { subject: { pts, centre, reach: towerH * 0.2, meshes }, limits: h.limits, rect: h.rect(),
             gate: 40 / h.scale, hazeAllowed: 0.1, texels: h.texels(meshes) },
      look: 'city',
    }];
  },

  // ---------------------------------------------------------------- set
  'loft_5_interior_for_free.glb': (holder, cam) => {
    const h = helpers(holder, cam), byName = (n) => h.node(n);
    const winNode = byName('Plane002'), floorNode = byName('Plane');
    if (!winNode || !floorNode) return [];
    const win = new THREE.Box3().setFromObject(winNode).expandByScalar(0.05);
    const furniture = points(['node_0', 'node_0001', 'node_0002', 'node_0003', 'node_0004', 'node_0005', 'Cube008', 'Cube007'].map(byName).filter(Boolean), 3000);
    const room = new THREE.Box3().setFromObject(floorNode), fc = centreOf(furniture);
    // Scale unconfirmed: the furniture says about 0.5 m a unit, so eye height
    // is 3.2 units until a human confirms it.
    const st = standing(holder, h.manifest.confirmed ? 1.6 : 3.2), EYE = st.eye;
    const cands = [];
    for (let i = 0; i <= 6; i++) for (let k = 0; k <= 8; k++) for (const fov of [55, 48, 62]) {
      const x = room.min.x + 0.6 + (room.max.x - room.min.x - 0.8) * i / 6, z = room.min.z + 0.6 + (room.max.z - room.min.z - 0.8) * k / 8;
      const p0 = V(x, EYE, z), aim = V(fc.x, st.floor + (EYE - st.floor) * 0.75, fc.z);
      if (p0.distanceTo(aim) < 4) continue;
      const dir = aim.clone().sub(p0).setY(0).normalize(), p1 = p0.clone().addScaledVector(dir, 1.6);
      cands.push({ p0: p0.toArray(), p1: p1.toArray(), a0: aim.toArray(), fov, dev: -p0.distanceTo(aim) + Math.abs(fov - 55) * 0.05 });
    }
    return [{
      name: 'establish_inside', cands,
      build: (k) => ({ kind: 'path', secs: 9, fov: k.fov, p0: k.p0, p1: k.p1, a0: k.a0 }),
      ctx: { subject: { pts: furniture, centre: fc, reach: 2, whole: false }, limits: h.limits, windows: [win] },
      look: 'set_inside',
    }];
  },
};

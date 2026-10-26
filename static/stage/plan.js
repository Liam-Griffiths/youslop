// From intent to candidates: what the shot planner writes for a paragraph
// ("the A380's left wing, push in, tight, from the side") becomes a search
// the solver can run — candidates nearest the intent first, a build that
// turns each into a shot, and the context its checks need. The planner never
// writes coordinates; this is where they come from (docs/3d-explainer.md,
// steps 7 and 8).
//
// An intent:
//   subjects  cast subject ids, in the scene's order (scene.js)
//   part      a named part or region of the first subject, or "" for whole
//   move      static | orbit | push | pull | crane | reveal | pan | turn
//   framing   wide | medium | tight
//   side      auto | front | three_quarter | left | right | rear | above | low
//   join      cut | match | continuous | dip  (how it follows the shot before)
//
// Each kind of model is shot its own way, with the rules the spike learned:
// objects by moves between two fitted framings; rooms from inside, level,
// by turns and dollies; sets from where their missing wall would be; aerial
// scans edge-aware with lens, framing and aim slide free; modelled cities
// with haze and a clearance gate.
import * as THREE from 'three';
import { standing } from './core.js';
import { points, fit, bearing } from './frame.js';
import { moveShot } from './shot.js';
import { withOptions } from './search.js';
import { limitsFor } from './intake.js';
import { lookFor } from './looks.js';

const V = (...a) => new THREE.Vector3(...a);
const D = THREE.MathUtils.radToDeg, R = THREE.MathUtils.degToRad;
export const vfov = (h, aspect = 16 / 9) => D(2 * Math.atan(Math.tan(R(h / 2)) / aspect));
export const meshesOf = (...objs) => { const s = new Set(); objs.forEach((o) => o.traverse((m) => { if (m.isMesh) s.add(m); })); return s; };
const centreOf = (pts) => new THREE.Sphere().setFromPoints(pts).center;
const radiusOf = (pts) => new THREE.Sphere().setFromPoints(pts).radius;
const thinTo = (pts, max) => pts.filter((_, i, a) => i % Math.max(1, Math.floor(a.length / max)) === 0);
const norm = (t) => String(t || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const WHOLE = new Set(['', 'whole', 'the whole', 'all', 'full', 'overall', 'exterior', 'whole model', 'whole aircraft']);

export const MOVES = ['static', 'orbit', 'push', 'pull', 'crane', 'reveal', 'pan', 'turn'];
export const FRAMINGS = { wide: 0.52, medium: 0.66, tight: 0.82 };
export const SIDES = { front: 0, three_quarter: 35, left: 90, right: 270, rear: 180 };
// Degrees of turn per second of shot that keep a ramped turn under the
// motion check's 20°/s peak (checks.js LIMITS.turn_deg_s).
const TURN_FIT = 15;

// The limit codes for the kind the creator settled on, which may not be the
// one intake guessed.
export function limitsOf(manifest) {
  const a = manifest.analysis || {}, kind = manifest.kind || a.kind_auto;
  return kind ? limitsFor({ ...a, kind }) : (a.limits || []);
}

// ------------------------------------------------------------- the model
// What a holder offers a shot: its points, a named part's, the points inside
// a box in the scaler's space (where regions and a site's subject live), and
// the detail budget of its own materials.
export function helpers(holder, cam) {
  const { manifest, scaler, inner } = holder.userData;
  const scale = manifest.scale || 1;
  const node = (name) => inner.getObjectByName(name) || inner.getObjectByName(String(name).replace(/[.\s]/g, ''));
  let _all = null;
  const all = () => (_all = _all || points([inner], 60000));
  const toLocal = () => new THREE.Matrix4().copy(scaler.matrixWorld).invert();
  // [x0, z0, x1, z1] in the scaler's space, as the identification grid reads it
  const inRect = (rect, max = 3000) => {
    const m = toLocal(), v = V();
    return thinTo(all().filter((p) => { v.copy(p).applyMatrix4(m); return v.x >= rect[0] && v.x <= rect[2] && v.z >= rect[1] && v.z <= rect[3]; }), max);
  };
  // [[x,y,z],[x,y,z]] in the scaler's space, as the regions editor saves it
  const inBox = (box, max = 3000) => {
    const m = toLocal(), v = V(), b = new THREE.Box3(V(...box[0]), V(...box[1]));
    return thinTo(all().filter((p) => b.containsPoint(v.copy(p).applyMatrix4(m))), max);
  };
  const worldBox = (box) => new THREE.Box3(V(...box[0]), V(...box[1])).applyMatrix4(scaler.matrixWorld);
  // The sharpest-needed budget among the meshes' own (untiled) materials,
  // in texels per scene metre.
  const texels = (meshes) => {
    const mats = (manifest.analysis || {}).materials || [], names = new Set();
    meshes.forEach((m) => [].concat(m.material).forEach((x) => names.add(x.name)));
    const tpu = mats.filter((m) => !m.tiled && m.texels_per_unit && (names.has(m.name) || mats.length === 1)).map((m) => m.texels_per_unit);
    return tpu.length ? Math.max(...tpu) / scale : null;
  };
  const rect = () => {
    const b = new THREE.Box3().setFromObject(inner);
    return { minX: b.min.x, maxX: b.max.x, minZ: b.min.z, maxZ: b.max.z };
  };
  const fitAt = (pts, az, el, fill, sceneRadius, fov = 35) => {
    cam.fov = fov; cam.aspect = 16 / 9; cam.clearViewOffset(); cam.updateProjectionMatrix();
    return fit(cam, pts, { az, el, fill, sceneRadius });
  };
  return { manifest, limits: limitsOf(manifest), node, all, inRect, inBox, worldBox, texels, rect, fitAt, scale };
}

// The parts and regions a shot can aim at, by name: Claude's part names,
// the file's own part labels, and the regions drawn by hand. Mirrors
// app/cast.py `_shootable`, which tells the writer the same list.
export function shootable(manifest) {
  const named = (manifest.identity || {}).parts || {};
  const out = Object.entries(named).map(([nodeName, label]) => ({ label, node: nodeName }));
  for (const p of manifest.parts || []) if (p.label && !(p.node in named)) out.push({ label: p.label, node: p.node });
  for (const r of manifest.regions || []) if (r.label) out.push({ label: r.label, box: r.box });
  return out;
}

// A named part of a holder as a subject: { label, pts, meshes, box? }, or
// null for the whole. An exact name wins over a partial one.
export function partOf(holder, name, h) {
  const n = norm(name);
  if (WHOLE.has(n)) return null;
  const list = shootable(holder.userData.manifest);
  const hit = list.find((p) => norm(p.label) === n)
    || list.find((p) => { const l = norm(p.label); return l && (l.includes(n) || n.includes(l)); });
  if (!hit) return null;
  if (hit.box) {
    const pts = h.inBox(hit.box);
    if (pts.length < 20) return null;
    return { label: hit.label, pts, meshes: meshesOf(holder), box: h.worldBox(hit.box) };
  }
  const node = h.node(hit.node);
  if (!node) return null;
  return { label: hit.label, pts: points([node], 3000), meshes: meshesOf(node) };
}

// A site's own subject — the building Claude placed on its top view — when
// no part is asked for.
function siteSubject(holder, h) {
  const box = ((h.manifest.identity || {}).subject || {}).box;
  if (!box) return null;
  const pts = h.inRect(box);
  return pts.length >= 20 ? { label: (h.manifest.identity.subject.name || 'the subject'), pts } : null;
}

// ------------------------------------------------------------- the plan
// `sc` is a built scene (scene.js); `opts`:
//   secs   how long the shot runs (the paragraphs under it)
//   prev   the shot before, when it is in the same scene: { shot, k, intent }
// Returns { cands, build(k), ctx, look, max, subject, notes }.
export function planFor(intent, sc, cam, opts = {}) {
  const it = { move: 'orbit', framing: 'medium', side: 'auto', join: 'cut', part: '', ...intent };
  if (!MOVES.includes(it.move)) it.move = 'orbit';
  if (!(it.framing in FRAMINGS)) it.framing = 'medium';
  const kind = sc.kind, first = sc.holders[0], h = helpers(first, cam);
  const notes = [];
  const part = partOf(first, it.part, h);
  if (it.part && !WHOLE.has(norm(it.part)) && !part) notes.push(`no part called "${it.part}"; the whole model is framed`);
  const make = { object: objectPlan, interior: interiorPlan, set: setPlan, aerial_site: aerialPlan, modelled_site: cityPlan }[kind] || objectPlan;
  const plan = make(it, sc, h, part, cam, opts);
  plan.notes = [...notes, ...(plan.notes || [])];
  plan.look = plan.look || lookFor(kind);
  plan.kind = kind;
  return plan;
}

const secsOf = (opts) => Math.max(2, opts.secs || 8);

// ---------------------------------------------------------------- objects
// One object, or several lined up. Every move is two framings fitted to the
// subject's points; the solver searches bearing, height and lens around the
// intent, and which way an orbit turns.
function objectPlan(it, sc, h, part, cam, opts) {
  const whole = points(sc.holders, 3000), wholeC = centreOf(whole), wholeR = radiusOf(whole);
  const S = part ? part.pts : whole, sC = centreOf(S), sR = radiusOf(S);
  const radius = sc.radius, fill = FRAMINGS[it.framing];
  // Which way to look from. A part off to one side is seen from its side.
  let az = SIDES[it.side] ?? SIDES.three_quarter, el = it.framing === 'tight' && part ? 20 : 12;
  if (it.side === 'auto' && part) {
    const off = V(sC.x - wholeC.x, 0, sC.z - wholeC.z);
    if (off.length() > wholeR * 0.2) az = (D(Math.atan2(off.x, off.z)) + 360) % 360;
  }
  if (it.side === 'above') el = 55;
  if (it.side === 'low') el = 4;
  const prev = opts.prev && opts.prev.shot;
  const continuous = it.join === 'continuous' && prev && prev.kind === 'move';
  if (it.join === 'match' && opts.prev && opts.prev.k && opts.prev.k.az != null) { az = opts.prev.k.az; el = opts.prev.k.el; }

  const lens = continuous ? [{ fov: prev.fov, cost: 0 }] : [{ fov: 35, cost: 0 }, { fov: 28, cost: 3 }, { fov: 45, cost: 4 }];
  const turns = it.move === 'static' ? [{ turn: 0, cost: 0 }] : [{ turn: 25, cost: 0 }, { turn: -25, cost: 1 }];
  const base = [];
  for (const d of [0, 15, -15, 30, -30, 45, -45, 60, -60]) for (const de of [0, 8, -6, 18]) {
    const e = Math.max(2, Math.min(70, el + de));
    base.push({ az: (az + d + 360) % 360, el: e, dev: Math.abs(d) + Math.abs(e - el) * 0.5 });
  }
  const cands = withOptions(withOptions(base, lens), turns);

  const F = (pts, a, e, f, fov) => h.fitAt(pts, a, e, Math.min(0.92, f), radius, fov);
  const secs = secsOf(opts);
  const build = (k) => {
    let a, b;
    switch (it.move) {
      case 'static': a = b = F(S, k.az, k.el, fill, k.fov); break;
      case 'push':
        a = part ? F(whole, k.az, k.el, FRAMINGS.wide, k.fov) : F(S, k.az, k.el, fill * 0.7, k.fov);
        b = F(S, k.az + k.turn * 0.3, k.el, fill, k.fov); break;
      case 'pull':
        b = part ? F(whole, k.az + k.turn * 0.3, k.el, FRAMINGS.wide, k.fov) : F(S, k.az + k.turn * 0.3, k.el, fill * 0.7, k.fov);
        a = F(S, k.az, k.el, fill, k.fov); break;
      case 'crane': a = F(S, k.az, Math.max(2, k.el - 6), fill, k.fov); b = F(S, k.az + k.turn * 0.3, k.el + 22, fill, k.fov); break;
      case 'reveal': a = F(part ? part.pts : S, k.az, k.el, 0.92, k.fov); b = F(whole, k.az + k.turn, k.el + 6, FRAMINGS.wide, k.fov); break;
      case 'pan': a = F(S, k.az, k.el, fill, k.fov); b = F(S, k.az + k.turn * 2, k.el + 3, fill, k.fov); break;
      default: a = F(S, k.az, k.el, fill, k.fov); b = F(S, k.az + k.turn, k.el + 4, fill + 0.04, k.fov);
    }
    if (continuous) {
      // The move carries on from where the shot before ended: same lens,
      // the same first framing, so the cut is invisible.
      const f = (x) => ({ target: x.target.toArray(), az: x.az, el: x.el, dist: x.dist });
      return { kind: 'move', secs, fov: prev.fov, a: { ...prev.b }, b: f(b) };
    }
    return moveShot(a, b, { secs, fov: k.fov });
  };
  const reveal = it.move === 'reveal';
  const subjPts = reveal ? whole : S;
  const tight = it.framing === 'tight' || part;
  const meshes = part ? part.meshes : meshesOf(...sc.holders);
  return {
    cands, build, max: 300,
    ctx: {
      subject: { pts: subjPts, centre: centreOf(subjPts), reach: reveal ? wholeR * 0.5 : 0, meshes, box: part && part.box,
                 whole: reveal || continuous ? false : true },
      limits: h.limits, texels: h.texels(meshes),
      gate: tight ? Math.max(0.25, Math.min(2, sR * 0.1)) : null,
    },
    subject: part ? part.label : 'whole',
  };
}

// --------------------------------------------------------------- interiors
// A room is shot from inside, at eye height, level: turns on the spot,
// dollies down its long axis, a crane straight up. The ceiling is shown by
// lens shift, never by tilting (the King's Hall).
function interiorPlan(it, sc, h, part, cam, opts) {
  const holder = sc.holders[0], st = standing(holder, 1.6), notes = [];
  const all = points([holder], 3000);
  if (!st) return { ...objectPlan(it, sc, h, part, cam, opts), notes: ['no floor measured: shot from outside'] };
  const size = new THREE.Box3().setFromObject(holder).getSize(V());
  const longYaw = size.z >= size.x ? 180 : 90;
  const hf = { wide: 85, medium: 75, tight: 58 }[it.framing];
  const at = V(st.centre.x, st.eye, st.centre.z), secs = secsOf(opts);
  const dirOf = (yaw) => V(Math.sin(R(yaw)), 0, Math.cos(R(yaw)));
  let yaws = [longYaw, longYaw + 180, longYaw + 90, longYaw - 90].map((y, i) => ({ yaw: (y + 360) % 360, dev: i ? 4 + i : 0 }));
  if (part) {
    // Face the part: from the room's middle toward it.
    const c = centreOf(part.pts), d = V(c.x - at.x, 0, c.z - at.z);
    if (d.length() > 1e-3) yaws = [0, 20, -20].map((o, i) => ({ yaw: (D(Math.atan2(d.x, d.z)) + o + 360) % 360, dev: i * 3 }));
  }
  const up = part ? Math.max(0, centreOf(part.pts).y - st.eye) : 0;
  let cands = withOptions(yaws, [{ hf, cost: 0 }, { hf: hf + 10, cost: 3 }, { hf: hf - 10, cost: 3 }]);
  cands = withOptions(cands, up > 1 || it.side === 'above'
    ? [{ shift: 0.22, cost: 0 }, { shift: 0.3, cost: 1 }, { shift: 0.15, cost: 1 }]
    : [{ shift: 0, cost: 0 }, { shift: 0.12, cost: 2 }]);
  const room = Math.min(size.x, size.z);
  if (['turn', 'orbit', 'pan'].includes(it.move) && secs * TURN_FIT < { turn: 360, pan: 120, orbit: 75 }[it.move]) {
    notes.push(`${Math.max(20, Math.floor(secs * TURN_FIT))}° of turn fits ${secs.toFixed(1)} s`);
  }
  const build = (k) => {
    const fov = vfov(k.hf), dir = dirOf(k.yaw), aimAt = (p) => p.clone().addScaledVector(dir, 10).toArray();
    const step = Math.min(3, room * 0.18);
    switch (it.move) {
      case 'turn': case 'orbit': case 'pan': {
        // Never faster than a viewer can follow: a 360 under four seconds of
        // narration becomes the part of a turn that fits.
        const want = it.move === 'turn' ? 360 : it.move === 'pan' ? 120 : 75;
        return { kind: 'turn', secs, fov, shift: k.shift, at: at.toArray(), yaw0: k.yaw,
                 degrees: Math.min(want, Math.max(20, Math.floor(secs * TURN_FIT))), pitch: 0, ramp: 0.15 };
      }
      case 'static': return { kind: 'still', secs, fov, shift: k.shift, pos: at.toArray(), aim: aimAt(at) };
      case 'crane': {
        const rise = Math.max(0.5, Math.min(2.5, ((st.ceiling ?? st.eye + 3) - st.eye) * 0.4));
        const p1 = at.clone().add(V(0, rise, 0));
        return { kind: 'path', secs, fov, shift: k.shift, p0: at.toArray(), p1: p1.toArray(), a0: aimAt(at), a1: aimAt(p1) };
      }
      default: {                      // push, pull, reveal: a level dolly
        const back = at.clone().addScaledVector(dir, -step * 0.6), fwd = at.clone().addScaledVector(dir, step * 0.5);
        const [p0, p1] = it.move === 'pull' || it.move === 'reveal' ? [fwd, back] : [back, fwd];
        return { kind: 'path', secs, fov, shift: k.shift, p0: p0.toArray(), p1: p1.toArray(), a0: aimAt(p0), a1: aimAt(p1) };
      }
    }
  };
  const subj = part ? part.pts : all;
  return { cands, build, max: 60, notes,
           ctx: { subject: { pts: subj, centre: part ? centreOf(subj) : st.centre, reach: 0, whole: false }, limits: h.limits },
           subject: part ? part.label : 'the room' };
}

// -------------------------------------------------------------------- sets
// A cutaway set: stand where its missing wall would be. Camera spots are
// searched across the set's own floor, so the open sides stay behind the
// lens; windows (regions named so) count as sky, not as holes. No turns.
function setPlan(it, sc, h, part, cam, opts) {
  const holder = sc.holders[0], st = standing(holder, 1.6);
  if (!st) return { ...objectPlan(it, sc, h, part, cam, opts), notes: ['no floor measured: shot from outside'] };
  // Aim at the part, or at the room's own centre (intake's) a little below
  // eye height. Camera spots cover the set's floor, nearest the sides intake
  // found open first: the missing wall is then behind the lens.
  const S = part ? part.pts : points([holder], 3000);
  const c = part ? centreOf(S) : V(st.centre.x, st.floor + (st.eye - st.floor) * 0.75, st.centre.z);
  const box = new THREE.Box3().setFromObject(holder), inset = Math.min(0.6, (box.max.x - box.min.x) * 0.08);
  const AX = { '+x': [1, 0, 0], '-x': [-1, 0, 0], '+z': [0, 0, 1], '-z': [0, 0, -1] };
  const open = (((h.manifest.analysis || {}).centre_probe || {}).open_sides || [])
    .filter((a) => AX[a]).map((a) => V(...AX[a]).applyQuaternion(holder.quaternion))
    .reduce((acc, v) => acc.add(v), V());
  if (open.lengthSq() > 1e-6) open.normalize();
  const secs = secsOf(opts), hf = { wide: 62, medium: 55, tight: 45 }[it.framing];
  const cands = [];
  for (let i = 0; i <= 6; i++) for (let k = 0; k <= 8; k++) for (const [fv, cost] of [[hf, 0], [hf - 7, 3], [hf + 7, 3]]) {
    const x = box.min.x + inset + (box.max.x - box.min.x - 2 * inset) * i / 6, z = box.min.z + inset + (box.max.z - box.min.z - 2 * inset) * k / 8;
    const p0 = V(x, st.eye, z), d = p0.distanceTo(c);
    if (d < 1) continue;
    const back = open.lengthSq() ? p0.clone().sub(c).setY(0).dot(open) : d;
    cands.push({ p0: p0.toArray(), aim: c.toArray(), hf: fv, dev: -back + cost });
  }
  const windows = (h.manifest.regions || []).filter((r) => /window|glass|sky|opening/i.test(r.label)).map((r) => h.worldBox(r.box).expandByScalar(0.05));
  const build = (k) => {
    const p0 = V(...k.p0), aim = V(...k.aim), dir = aim.clone().sub(p0).setY(0).normalize();
    const right = V(dir.z, 0, -dir.x), travel = Math.min(1.6, p0.distanceTo(aim) * 0.25);
    let p1 = p0.clone();
    if (it.move === 'push') p1 = p0.clone().addScaledVector(dir, travel);
    else if (it.move === 'pull' || it.move === 'reveal') p1 = p0.clone().addScaledVector(dir, -travel);
    else if (it.move !== 'static') p1 = p0.clone().addScaledVector(right, travel);   // a slow truck, never a turn
    return { kind: 'path', secs, fov: vfov(k.hf), p0: p0.toArray(), p1: p1.toArray(), a0: aim.toArray() };
  };
  return { cands, build, max: 300,
           ctx: { subject: { pts: S, centre: c, reach: 0, whole: false }, limits: h.limits, windows },
           notes: windows.length ? [] : ['no window regions: daylight through windows reads as holes'],
           subject: part ? part.label : 'the set' };
}

// ------------------------------------------------------------ aerial scans
// An aerial photogrammetry tile: the camera always looks down, the tile's
// edge must stay out of frame, and the detail budget is priced. Bearing,
// height, lens, framing, orbit direction and an aim slid toward the tile's
// middle are all free (the Abbey needed a 24° lens, tight, slid 12%).
function aerialPlan(it, sc, h, part, cam, opts) {
  const holder = sc.holders[0];
  const sub = part || siteSubject(holder, h) || { label: 'the site', pts: points([holder], 3000) };
  const pts = sub.pts, centre = centreOf(pts), sr = radiusOf(pts), radius = sc.radius;
  const pref = SIDES[it.side] ?? 35, el0 = it.side === 'above' ? 60 : 35;
  const base = [];
  for (let d = 0; d < 360; d += 30) for (const el of [el0, 45, 60].filter((v, i, a) => a.indexOf(v) === i)) {
    const off = Math.min(d, 360 - d);
    base.push({ az: (pref + d) % 360, el, dev: off * 0.1 + Math.abs(el - el0) * 0.2 });
  }
  const f0 = { wide: 0.5, medium: 0.6, tight: 0.75 }[it.framing];
  let cands = withOptions(base, [{ fov: 35, cost: 0 }, { fov: 24, cost: 4 }, { fov: 16, cost: 8 }]);
  cands = withOptions(cands, [{ fill: f0, cost: 0 }, { fill: f0 + 0.12, cost: 3 }, { fill: Math.min(0.9, f0 + 0.25), cost: 6 }]);
  cands = withOptions(cands, it.move === 'static' ? [{ turn: 0, cost: 0 }] : [{ turn: 20, cost: 0 }, { turn: -20, cost: 1 }]);
  cands = withOptions(cands, [{ slide: 0, cost: 0 }, { slide: 0.12, cost: 2 }, { slide: 0.25, cost: 4 }]);
  const inward = holder.getWorldPosition(V()).sub(centre).setY(0);
  if (inward.lengthSq() > 1e-9) inward.normalize();
  const secs = secsOf(opts);
  const build = (k) => {
    let fa = k.fill, fb = Math.min(0.9, k.fill + 0.07);
    if (it.move === 'push') fb = Math.min(0.92, k.fill + 0.18);
    if (it.move === 'pull' || it.move === 'reveal') [fa, fb] = [Math.min(0.92, k.fill + 0.18), k.fill];
    const a = h.fitAt(pts, k.az, k.el, fa, radius, k.fov);
    const b = h.fitAt(pts, k.az + k.turn, k.el, fb, radius, k.fov);
    for (const f of [a, b]) f.target.addScaledVector(inward, k.slide * sr);
    return moveShot(a, b, { secs, fov: k.fov });
  };
  return { cands, build, max: 3000,
           ctx: { subject: { pts, centre, reach: 0 }, limits: h.limits, texels: h.texels(meshesOf(holder)), detailMax: 3.5 },
           subject: sub.label };
}

// --------------------------------------------------------- modelled cities
// A built city: our sun, haze that hides the map's edge but not the subject,
// and clearance as a gate — an orbit must never pass through a building.
function cityPlan(it, sc, h, part, cam, opts) {
  const holder = sc.holders[0];
  const sub = part || siteSubject(holder, h) || { label: 'the city', pts: points([holder], 3000), meshes: meshesOf(holder) };
  const pts = sub.pts, centre = centreOf(pts), meshes = sub.meshes || null;
  const radius = radiusOf(pts) * 6, height = new THREE.Box3().setFromPoints(pts).getSize(V()).y;
  const pref = SIDES[it.side] ?? 150, el0 = it.side === 'above' ? 40 : it.side === 'low' ? 6 : 12;
  const fill = { wide: 0.5, medium: 0.58, tight: 0.72 }[it.framing];
  const cands = [];
  for (const el of [el0, el0 + 4, el0 - 4, el0 + 10].filter((e) => e > 2)) for (const d of [0, 30, -30, 60, -60, 90]) for (const turn of it.move === 'static' ? [0] : [30, -30]) {
    cands.push({ az: (pref + d + 360) % 360, el, turn, dev: Math.abs(el - el0) + Math.abs(d) * 0.2 + (turn < 0 ? 1 : 0) });
  }
  const secs = secsOf(opts);
  const build = (k) => {
    let fa = fill, fb = fill + 0.05;
    if (it.move === 'push') fb = Math.min(0.9, fill + 0.2);
    if (it.move === 'pull' || it.move === 'reveal') [fa, fb] = [Math.min(0.9, fill + 0.2), fill];
    return moveShot(h.fitAt(pts, k.az, k.el, fa, radius), h.fitAt(pts, k.az + k.turn, k.el + 3, fb, radius), { secs });
  };
  return { cands, build, max: 400,
           ctx: { subject: { pts, centre, reach: height * 0.2, meshes }, limits: h.limits, rect: h.rect(),
                  gate: it.framing === 'tight' ? 8 : 20, hazeAllowed: 0.1, texels: meshes ? h.texels(meshes) : null },
           subject: sub.label };
}

// The bearing a camera would need to look at `aim` from `pos`, for setting a
// hand-made view back into a move's framing (the Stage tab's set-from-view).
export function framingOf(pos, aim) {
  const d = pos.clone().sub(aim), dist = d.length();
  return { target: aim.toArray(), az: (D(Math.atan2(d.x, d.z)) + 360) % 360, el: D(Math.asin(d.y / Math.max(1e-9, dist))), dist };
}
export { bearing };

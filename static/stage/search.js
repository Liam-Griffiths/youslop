// Choosing a shot: every candidate is a complete shot (shot.js), ranked by
// how far it strays from what was asked for — another angle, a longer lens,
// a looser detail budget each cost something — and the nearest one that
// passes every check wins. When none passes, the best is used and flagged
// for a human; a shot is never silently dropped and never silently bad.
//
// Which checks run depends on the model's kind, through the limit codes
// intake.js gave it (docs/3d-explainer.md, step 3 and the checks table):
//
//   always            motion; the subject whole in frame; occlusion if the
//                     subject has meshes; clearance if a gate is set
//   edge + no_low_angles   (an aerial scan) the key-colour edge share, and
//                     the camera always looking down
//   edge, otherwise   (a modelled site) haze that hides the edge
//   stand_inside      voids, with window rays told apart from holes
//   level_camera      no tilt
//   texels known      the detail budget
import * as THREE from 'three';
import { poseAt, applyPose, frameCount, FPS } from './shot.js';
import * as C from './checks.js';
import * as G from './gpu.js';

export const PASS = {
  edge_pct: 0.3,         // tile edge in frame, % of pixels
  holes_pct: 0.05,       // unmodelled, not-window pixels
  cut: 0.01,             // share of the subject outside the safe frame
  visible: 0.85,         // share of the subject not hidden behind anything
};

// The candidates crossed with options that each cost something:
//   withOptions(cands, [{fov: 35, cost: 0}, {fov: 24, cost: 3}])
export const withOptions = (cands, options) =>
  cands.flatMap((k) => options.map(({ cost = 0, ...o }) => ({ ...k, ...o, dev: (k.dev || 0) + cost })));

// Nearest first. `build(k)` turns a candidate into a shot; `check(shot, k,
// quick)` returns a report with `ok` and a `score` (lower is better), where
// `quick` asks for the end frames only — most candidates fail there, and a
// full check costs five times as much. Returns the pick and how it was
// found; `flagged` means nothing passed and the pick is the best of the rest.
export function search(cands, build, check, { log = () => {}, max = Infinity } = {}) {
  const order = [...cands].sort((a, b) => (a.dev || 0) - (b.dev || 0));
  let best = null, tried = 0;
  for (const k of order) {
    if (tried >= max) break;
    tried++;
    if (tried % 25 === 0) log({ tried, of: order.length });
    const shot = build(k);
    const q = check(shot, k, true);
    if (!q.ok && best && q.score >= best.report.score) continue;    // can neither pass nor beat the best
    const r = check(shot, k, false);
    if (r.ok) return { shot, k, report: r, tried, of: order.length, flagged: false };
    if (!best || r.score < best.report.score) best = { shot, k, report: r };
  }
  if (!best) return null;
  return { ...best, tried, of: order.length, flagged: true,
           flag: `no shot passed every check; using the best (${best.report.failed.join(', ')})` };
}

// Every check that applies to this shot, as one report. `ctx`:
//   subject   { pts, centre: Vector3, reach, meshes?: Set, box?: Box3,
//               whole?: false when it may run out of frame }
//   limits    the model's limit codes
//   texels    texels per metre on the subject (the detail budget), optional
//   rect      the site's extent {minX, maxX, minZ, maxZ}, for haze
//   windows   Box3s of a set's window openings, for voids
//   gate      the nearest the camera may come to anything, in metres
//   gpu       { renderer, scene, cam, hide } — without it only the pure
//             checks run (Node tests, quick planning)
// `quick` samples the first and last frames for the GPU checks; a full
// check samples five, and the motion check always walks every frame.
export function checkShot(shot, ctx, quick = false) {
  const fps = ctx.fps || FPS, aspect = ctx.aspect || 16 / 9, L = new Set(ctx.limits || []);
  const out = {}, failed = [];
  let score = 0;
  const note = (name, r, cost) => { out[name] = r; if (!r.ok) { failed.push(name); score += cost; } };
  const sub = ctx.subject;

  if (!quick) note('motion', C.motion(shot, sub.pts, { fps, aspect }), 100);
  if (L.has('level_camera')) note('level', C.level(shot, { fps }), 100);
  if (L.has('no_low_angles')) note('look_down', C.lookDown(shot, { fps }), 50);
  if (ctx.texels) {
    const d = C.detail(shot, sub.centre, sub.reach || 0, ctx.texels, { fps, outH: ctx.outH || 1080 });
    note('detail', d, Math.max(0, d.px_per_texel - C.LIMITS.detail_px) * 10);
  }
  if (L.has('edge') && !L.has('no_low_angles') && ctx.rect) {
    const h = C.haze(shot, ctx.rect, sub.centre, sub.reach || 0, { allowed: ctx.hazeAllowed ?? 0.1, fps, aspect });
    note('haze', h, h.ok ? 0 : 20 + 100 * (h.subject_haze || 0));
  }

  // Per sampled frame: the subject whole, and the GPU checks.
  const N = frameCount(shot, fps), at = quick ? [0, 1] : [0, 0.25, 0.5, 0.75, 1];
  const cam = ctx.gpu ? ctx.gpu.cam : new THREE.PerspectiveCamera(35, aspect, 0.1, 1000);
  let cut = 0, edge = 0, holes = 0, sky = 0, vis = 1, clear = Infinity;
  for (const u of at) {
    applyPose(cam, poseAt(shot, Math.round(u * (N - 1)), fps), { W: 1920, H: 1080, ...(ctx.clip || {}) });
    cut = Math.max(cut, C.cutOff(cam, sub.pts));
    if (!ctx.gpu) continue;
    const { renderer, scene, hide = [] } = ctx.gpu;
    if (L.has('edge') && L.has('no_low_angles')) edge = Math.max(edge, G.keyShare(renderer, scene, cam, { hide }));
    if (L.has('stand_inside')) {
      const v = G.voids(renderer, scene, cam, ctx.windows || [], { hide });
      holes = Math.max(holes, v.holes); sky = Math.max(sky, v.sky);
    }
    if (sub.meshes) vis = Math.min(vis, G.visibility(renderer, scene, cam, sub).visible);
    if (ctx.gate) clear = Math.min(clear, G.clearanceAt(renderer, scene, cam.position.clone()));
  }
  // A subject must be whole in frame — unless it is the room itself, seen
  // from inside, or a close-up that runs along a part on purpose.
  if (sub.whole !== false) note('whole', { ok: cut <= PASS.cut, cut: +cut.toFixed(3) }, cut * 200);
  if (ctx.gpu) {
    if (L.has('edge') && L.has('no_low_angles')) note('edge', { ok: edge <= PASS.edge_pct, pct: +edge.toFixed(2) }, edge * 10);
    if (L.has('stand_inside')) note('voids', { ok: holes <= PASS.holes_pct, holes_pct: +holes.toFixed(2), sky_pct: +sky.toFixed(1) }, holes * 20);
    if (sub.meshes) note('visible', { ok: vis >= PASS.visible, visible: +vis.toFixed(2) }, (1 - vis) * 100);
    if (ctx.gate) note('clearance', { ok: clear >= ctx.gate, metres: +clear.toFixed(2) }, 200);
  }
  return { ok: failed.length === 0, failed, score: +score.toFixed(2), checks: out };
}

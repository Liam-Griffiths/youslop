// Intake: what kind of model this is, and what that means for the camera.
//
// The spike's main finding (docs/3d-explainer.md, step 3) is that
// understanding a model depends on its kind — object, interior, aerial site,
// modelled site, or set — and each kind limits the camera differently. This
// works the kind out from the file and a handful of depth probes, measures
// what the shots will need, and returns limit codes the confirm screen turns
// into sentences and the planner will obey.
//
// Everything is measured in the model's own file units with no heading or
// scale applied, so the result does not change when the creator confirms a
// true size; anything in metres is derived from it with the manifest's scale.
import * as THREE from 'three';
import { probe, FACE } from './probe.js';

export const VERSION = 7;              // bump to re-analyse every model on next open
export const KINDS = {
  object: 'Object — something you look at from outside',
  interior: 'Interior — a room you stand inside',
  aerial_site: 'Aerial site — a scanned patch of the world',
  modelled_site: 'Modelled site — a built city or landscape',
  set: 'Set — a cutaway built to be seen from one side',
};

const median = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : null; };

// ----------------------------------------------------------- the materials
// Texel density per material — the detail budget of every shot that frames
// it — and the signs of a photogrammetry scan: few materials, one big texture
// (or none), a great many triangles. A scan's photos already hold its light.
function materials(model) {
  const per = new Map(), a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  let tris = 0, area = 0;
  model.traverse((o) => {
    if (!o.isMesh) return;
    const g = o.geometry, pos = g.attributes.position, uv = g.attributes.uv, idx = g.index;
    const n = idx ? idx.count : pos.count, get = (i) => (idx ? idx.getX(i) : i);
    for (const m of [].concat(o.material)) {
      const tex = m.map && m.map.image ? [m.map.image.width, m.map.image.height] : null;
      if (!per.has(m)) per.set(m, { name: m.name || '(unnamed)', tex, unlit: !!m.isMeshBasicMaterial, A: 0, U: 0, tris: 0 });
    }
    const e = per.get([].concat(o.material)[0]);
    for (let i = 0; i < n; i += 3) {
      const i0 = get(i), i1 = get(i + 1), i2 = get(i + 2);
      a.fromBufferAttribute(pos, i0).applyMatrix4(o.matrixWorld);
      b.fromBufferAttribute(pos, i1).applyMatrix4(o.matrixWorld);
      c.fromBufferAttribute(pos, i2).applyMatrix4(o.matrixWorld);
      const t = b.sub(a).cross(c.sub(a)).length() / 2;
      e.A += t; area += t; e.tris++; tris++;
      if (uv) {
        const u0 = uv.getX(i0), v0 = uv.getY(i0), u1 = uv.getX(i1), v1 = uv.getY(i1), u2 = uv.getX(i2), v2 = uv.getY(i2);
        e.U += Math.abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)) / 2;
      }
    }
  });
  const list = [...per.values()].map((e) => ({
    name: e.name.slice(0, 60), tex: e.tex, unlit: e.unlit, tris: e.tris,
    area_share: area ? +(e.A / area).toFixed(4) : 0,
    tiled: e.U > 1.5,                               // UVs wrap: a repeating texture, sharp at any distance
    texels_per_unit: e.tex && e.A ? +Math.sqrt((e.U * e.tex[0] * e.tex[1]) / e.A).toFixed(5) : null,
  })).sort((x, y) => y.area_share - x.area_share);
  const textured = list.filter((m) => m.tex);
  const scan = list.length <= 3 && tris > 250000 &&
    (textured.length === 0 || textured.every((m) => Math.max(...m.tex) >= 2048 && !m.tiled));
  return { list, tris, scan, bare: textured.length === 0 };
}

// What fraction of the footprint has something in it, seen from straight above.
function topCover(renderer, scene, box) {
  const S = 128, size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  const cam = new THREE.OrthographicCamera(-size.x / 2, size.x / 2, size.z / 2, -size.z / 2, 0.001, size.y * 4 + 1);
  cam.position.set(c.x, box.max.y + size.y + 0.01, c.z); cam.up.set(0, 0, -1); cam.lookAt(c.x, box.min.y, c.z);
  cam.updateProjectionMatrix();
  const rt = new THREE.WebGLRenderTarget(S, S), buf = new Uint8Array(S * S * 4);
  const keep = { o: scene.overrideMaterial, bg: scene.background, rt: renderer.getRenderTarget() };
  scene.overrideMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide });
  scene.background = new THREE.Color(0);
  renderer.setRenderTarget(rt); renderer.render(scene, cam); renderer.readRenderTargetPixels(rt, 0, 0, S, S, buf);
  renderer.setRenderTarget(keep.rt); scene.overrideMaterial.dispose();
  scene.overrideMaterial = keep.o; scene.background = keep.bg; rt.dispose();
  let n = 0; for (let i = 0; i < buf.length; i += 4) if (buf[i] > 128) n++;
  return n / (S * S);
}

// ------------------------------------------------------------------- kind
function classify(c, top, aspect, scan) {
  // Enclosed from inside: walls all round, front faces, no void.
  if (c.void < 0.02 && c.back < 0.05) return 'interior';
  // Flat and wide, ground across the footprint, open sky above the middle.
  if (aspect >= 4 && top >= 0.6 && c.per[FACE.up].hit < 0.3) return scan ? 'aerial_site' : 'modelled_site';
  // A room with a floor, a ceiling, at least one solid wall at eye level, and
  // at least one side left open. (Between a biplane's wings there is a "floor"
  // and a "ceiling" too, but only struts and wires at eye level — no wall.)
  // Floor and ceiling only need to be clearly there: a set's bounding box is
  // stretched by backdrops outside it, so its centre can sit near a wall and
  // see past it. The walls-and-openings test is what tells a set apart.
  if (c.back < 0.1 && c.per[FACE.down].hit > 0.5 && c.per[FACE.up].hit > 0.5 &&
      c.wall_sides.length >= 1 && c.open_sides.length >= 1) return 'set';
  return 'object';
}

// Floor and ceiling for anything you stand in: the median over a grid of
// probes, never one ray (one ray from the King's Hall's centre hit the table
// under the chandelier and put eye height 0.77 m too high).
function floorAndCeiling(renderer, scene, box) {
  const floors = [], ceilings = [], voids = [], inside = [];
  const y = box.getCenter(new THREE.Vector3()).y;
  for (let i = 0; i < 7; i++) for (let k = 0; k < 7; k++) {
    const p = new THREE.Vector3(THREE.MathUtils.lerp(box.min.x, box.max.x, (i + 0.5) / 7), y,
      THREE.MathUtils.lerp(box.min.z, box.max.z, (k + 0.5) / 7));
    const r = probe(renderer, scene, p);
    if (r.back > 0.02 || r.floor_below == null) continue;          // outside the room or inside a wall
    floors.push(p.y - r.floor_below); inside.push(p);
    if (r.ceiling_above != null) ceilings.push(p.y + r.ceiling_above);
    voids.push(r.void);
  }
  // The room's own middle: the centroid of the probes that stood over its
  // floor. The bounding box's centre is not it when backdrops stretch the box
  // (the loft's box centre sat on its window wall).
  const mid = inside.length ? inside.reduce((a, p) => a.add(p), new THREE.Vector3()).divideScalar(inside.length) : null;
  return { floor_y: median(floors), ceiling_y: median(ceilings), samples: floors.length,
           holes: voids.length ? median(voids) : null,
           room_centre: mid ? [+mid.x.toFixed(4), +mid.z.toFixed(4)] : null };
}

const OPEN = { [FACE.px]: '+x', [FACE.nx]: '-x', [FACE.pz]: '+z', [FACE.nz]: '-z' };

// The whole analysis. `inner` is the loaded glTF scene (no heading, no scale);
// it is measured in a scene of its own so no helper or floor is mistaken for it.
export function analyse(renderer, inner) {
  const t0 = performance.now();
  const parent = inner.parent, scene = new THREE.Scene();
  const keep = { pos: inner.position.clone() };
  scene.add(inner); inner.updateMatrixWorld(true);
  try {
    const box = new THREE.Box3().setFromObject(inner), size = box.getSize(new THREE.Vector3());
    const mats = materials(inner);
    let at = box.getCenter(new THREE.Vector3());
    let c = probe(renderer, scene, at);
    // Inside something with a floor and a ceiling, look again from halfway up,
    // above the furniture: from the box's centre the loft's open front was
    // hidden behind its sofa.
    if (c.floor_below != null && c.ceiling_above != null) {
      const mid = box.getCenter(new THREE.Vector3());
      mid.y += (c.ceiling_above - c.floor_below) / 2;
      c = probe(renderer, scene, mid); at = mid;
    }
    const top = topCover(renderer, scene, box);
    const aspect = Math.max(size.x, size.z) / Math.max(1e-6, size.y);
    const kind = classify(c, top, aspect, mats.scan);
    const light = mats.list.some((m) => m.unlit) || (mats.scan && !mats.bare) ? 'baked' : 'ours';
    const out = {
      version: VERSION, kind_auto: kind, light, scan: mats.scan, bare: mats.bare, triangles: mats.tris,
      materials: mats.list.slice(0, 24), top_cover: +top.toFixed(2), aspect: +aspect.toFixed(1),
      centre_probe: { void: +c.void.toFixed(3), back: +c.back.toFixed(3), open_sides: c.open_sides.map((f) => OPEN[f]),
        wall_sides: c.wall_sides.map((f) => OPEN[f]), band: [FACE.px, FACE.nx, FACE.pz, FACE.nz].map((f) => +c.per[f].band.toFixed(2)),
        floor_cover: +c.per[FACE.down].hit.toFixed(2), ceiling_cover: +c.per[FACE.up].hit.toFixed(2) },
      size_units: size.toArray().map((v) => +v.toFixed(4)),
      probe_at: at.toArray().map((v) => +v.toFixed(4)),      // where the room was judged from (file units)
    };
    if (kind === 'interior' || kind === 'set') Object.assign(out, floorAndCeiling(renderer, scene, box));
    out.limits = limitsFor(out);
    out.ms = Math.round(performance.now() - t0);
    return out;
  } finally {
    if (parent) parent.add(inner);
    inner.position.copy(keep.pos); inner.updateMatrixWorld(true);
  }
}

// What the kind and measurements forbid or demand of the camera. Codes, so
// the planner can obey them; the confirm screen words them.
export function limitsFor(a) {
  const L = [];
  if (a.light === 'baked') L.push('baked_light');
  if (a.bare) L.push('bare_scan');
  switch (a.kind || a.kind_auto) {
    case 'interior': L.push('stand_inside', 'level_camera'); if (a.holes > 0.002) L.push('holes'); break;
    case 'aerial_site': L.push('subject_is_a_part', 'edge', 'no_low_angles'); break;
    case 'modelled_site': L.push('subject_is_a_part', 'edge'); break;
    case 'set': L.push('one_direction', 'stand_inside'); break;
    default: break;
  }
  return L;
}

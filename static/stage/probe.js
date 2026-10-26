// The depth probe: what surrounds a point, in six small GPU renders.
//
// From `p`, render six 90° views (±x, ±y, ±z) of signed distance to whatever
// is there: positive on a surface's front face, negative on its back face,
// zero where there is nothing. Six 64×64 renders on the GPU replace millions
// of ray–triangle tests in JavaScript, which is what makes it usable on a
// 2-million-triangle scan. See docs/3d-explainer.md, "Interiors".
import * as THREE from 'three';

const N = 64;
const DIRS = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
const UPS = [[0, 1, 0], [0, 1, 0], [0, 0, -1], [0, 0, 1], [0, 1, 0], [0, 1, 0]];
export const FACE = { px: 0, nx: 1, up: 2, down: 3, pz: 4, nz: 5 };

let _mat = null, _rt = null, _cam = null;
function setup() {
  if (_mat) return;
  _mat = new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    uniforms: { eye: { value: new THREE.Vector3() } },
    vertexShader: 'varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }',
    fragmentShader: 'uniform vec3 eye; varying vec3 vW; void main(){ float d = length(vW - eye); gl_FragColor = vec4(gl_FrontFacing ? d : -d, 0.0, 0.0, 1.0); }',
  });
  _rt = new THREE.WebGLRenderTarget(N, N, { type: THREE.FloatType });
  _cam = new THREE.PerspectiveCamera(90, 1, 0.001, 1e7);
}

// Returns the six faces' raw distances and a summary. `scene` should hold
// only the model: helpers and floors would be measured as if they were it.
export function probe(renderer, scene, p) {
  setup();
  const buf = new Float32Array(N * N * 4), faces = [];
  const keep = { o: scene.overrideMaterial, bg: scene.background, env: scene.environment, rt: renderer.getRenderTarget() };
  scene.overrideMaterial = _mat; scene.background = null; scene.environment = null;
  _mat.uniforms.eye.value.copy(p);
  const clear = renderer.getClearColor(new THREE.Color()), alpha = renderer.getClearAlpha();
  renderer.setRenderTarget(_rt);
  renderer.setClearColor(0x000000, 1);
  for (let f = 0; f < 6; f++) {
    _cam.position.copy(p); _cam.up.fromArray(UPS[f]);
    _cam.lookAt(p.clone().add(new THREE.Vector3().fromArray(DIRS[f])));
    renderer.clear(); renderer.render(scene, _cam);
    renderer.readRenderTargetPixels(_rt, 0, 0, N, N, buf);
    const d = new Float32Array(N * N);
    for (let i = 0; i < N * N; i++) d[i] = buf[i * 4];
    faces.push(d);
  }
  renderer.setRenderTarget(keep.rt); renderer.setClearColor(clear, alpha);
  scene.overrideMaterial = keep.o; scene.background = keep.bg; scene.environment = keep.env;
  return summarise(faces);
}

function summarise(faces) {
  const share = (f) => {               // per face: how much is hit, how much is back faces
    let hit = 0, back = 0, near = Infinity;
    for (const v of f) { if (v === 0) continue; hit++; if (v < 0) back++; near = Math.min(near, Math.abs(v)); }
    return { hit: hit / f.length, back: hit ? back / hit : 0, near };
  };
  const per = faces.map(share);
  // Side views judged at eye level only: the middle band of rows. A whole side
  // view also sees the floor and the ceiling, so an open side of a room would
  // look more than half full.
  const band = (f) => {
    let hit = 0, n = 0;
    for (let y = Math.floor(N * 0.42); y < Math.ceil(N * 0.58); y++) for (let x = 0; x < N; x++) { n++; if (f[y * N + x] !== 0) hit++; }
    return hit / n;
  };
  for (const f of [FACE.px, FACE.nx, FACE.pz, FACE.nz]) per[f].band = band(faces[f]);
  const all = per.reduce((a, s) => ({ hit: a.hit + s.hit / 6, backN: a.backN + s.back * s.hit, hitN: a.hitN + s.hit }), { hit: 0, backN: 0, hitN: 0 });
  const centre = (f) => { const v = faces[f][(N / 2) * N + N / 2]; return v === 0 ? null : Math.abs(v); };
  const sides = [FACE.px, FACE.nx, FACE.pz, FACE.nz];
  return {
    faces, per,
    void: 1 - all.hit,
    back: all.hitN ? all.backN / all.hitN : 0,
    floor_below: centre(FACE.down),           // straight down; null = nothing there
    ceiling_above: centre(FACE.up),
    clear_side: Math.min(...sides.map((f) => per[f].near)),
    open_sides: sides.filter((f) => per[f].band < 0.3),           // nothing at eye level that way
    wall_sides: sides.filter((f) => per[f].band > 0.85),          // a solid wall that way
  };
}

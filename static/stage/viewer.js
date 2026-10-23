// The model viewer used by the library's intake screen: one model on the
// stage floor, orbitable, with the two things a human needs to confirm it —
// an arrow on the floor marking the front (+z), and a 1.8 m figure beside it,
// so a model at the wrong scale is obvious at a glance.
//
// app.js is a classic script, so this hands it `window.Stage3D`.
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { THREE, loadModel, applyManifest, sizeMetres, buildSet, points, fit, boxOf } from './core.js';
import { analyse, limitsFor, KINDS, VERSION } from './intake.js';
import { renderViews, renderZoom, regionHeight, renderParts, OBJECT_VIEWS } from './identify.js';

const PERSON_M = 1.8;

function label(text, color) {
  const cv = document.createElement('canvas'); cv.width = 256; cv.height = 64;
  const g = cv.getContext('2d');
  g.font = '600 38px system-ui, sans-serif'; g.fillStyle = color; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 128, 34);
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  s.scale.set(4, 1, 1); s.userData.set = true;
  return s;
}

async function mount(el, manifest, { accent = '#E8C36A' } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  el.innerHTML = '';
  el.appendChild(renderer.domElement);
  renderer.domElement.style.display = 'block';
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 1000);
  const controls = new OrbitControls(cam, renderer.domElement);
  controls.enableDamping = true; controls.maxPolarAngle = Math.PI / 2 - 0.02;   // never under the floor

  let model;
  try {
    model = await loadModel(manifest);
  } catch (e) {
    renderer.dispose();
    throw new Error(`Could not load this model: ${e.message || e}`);
  }
  scene.add(model);

  // Helpers, rebuilt whenever the size changes.
  const helpers = new THREE.Group(); scene.add(helpers);
  let set = null;
  const person = new THREE.Mesh(new THREE.CapsuleGeometry(0.22, PERSON_M - 0.44 - 0.24, 6, 16),
    new THREE.MeshStandardMaterial({ color: 0x8892a4, roughness: 0.7 }));
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 16, 12), person.material);
  person.add(head); head.position.y = (PERSON_M - 0.24) / 2 + 0.02;
  person.castShadow = true; head.castShadow = true;
  person.userData.set = head.userData.set = true;

  function layout() {
    model.updateMatrixWorld(true);
    if (set) set.dispose();
    set = buildSet(renderer, scene, [model]);
    helpers.clear();
    const box = boxOf(model), size = box.getSize(new THREE.Vector3());
    const span = Math.max(size.x, size.z, PERSON_M);
    // the front arrow, on the floor just ahead of the model's nose
    const len = Math.max(0.6, span * 0.18);
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1),
      new THREE.Vector3(box.getCenter(new THREE.Vector3()).x, 0.02, box.max.z + span * 0.04), len, accent, len * 0.35, len * 0.22);
    arrow.traverse((o) => { o.userData.set = true; });
    const tag = label('front', accent);
    tag.scale.set(len * 1.2, len * 0.3, 1);
    tag.position.set(arrow.position.x, len * 0.25, arrow.position.z + len * 1.25);
    // the person, standing off the model's right side (as seen from the front)
    person.position.set(box.min.x - Math.max(0.6, span * 0.06), PERSON_M / 2, box.getCenter(new THREE.Vector3()).z);
    helpers.add(arrow, tag, person);
    // what the opening view must include besides the model: the arrow and its label
    guides = [arrow.position.clone().add(new THREE.Vector3(0, 0, len)), tag.position.clone(),
      person.position.clone().setY(PERSON_M)];
  }
  let guides = [];

  function frame(az = 35, el2 = 20) {
    const pts = points([model], 3000).concat(guides);
    const sph = boxOf(model).getBoundingSphere(new THREE.Sphere());
    const f = fit(cam, pts, { az, el: el2, fill: 0.78, sceneRadius: sph.radius });
    controls.target.copy(f.target);
    controls.minDistance = sph.radius * 0.05; controls.maxDistance = sph.radius * 20;
    cam.far = sph.radius * 60; cam.updateProjectionMatrix();
    controls.update();
  }

  // Rooms and sets are understood from inside, at eye height, looking down
  // the long axis — from outside an interior scan is just a closed box.
  // Rooms and sets are understood from inside, at eye height. An interior is
  // seen down its long axis; a set from its open side, looking at the wall
  // opposite — standing where the missing wall would be.
  function frameInside(a) {
    const m = model.userData.manifest, k = m.scale || 1;
    if (a.floor_y == null) return false;
    model.updateMatrixWorld(true);
    const b = boxOf(model), size = b.getSize(new THREE.Vector3());
    // probe_at was measured with the inner model at its own (centred) position,
    // i.e. in the scaler's space — not the inner node's.
    const local = a.room_centre ? [a.room_centre[0], 0, a.room_centre[1]] : a.probe_at;
    const at = local ? model.userData.scaler.localToWorld(new THREE.Vector3().fromArray(local)) : b.getCenter(new THREE.Vector3());
    const eyeY = b.min.y + a.floor_y * k + 1.6, span = Math.max(size.x, size.z);
    const AX = { '+x': [1, 0, 0], '-x': [-1, 0, 0], '+z': [0, 0, 1], '-z': [0, 0, -1] };
    const open = (a.centre_probe && a.centre_probe.open_sides || [])[0];
    let look, back;
    if (open) {                       // a set: back toward the opening, look at the far wall
      const o = new THREE.Vector3().fromArray(AX[open]).applyQuaternion(model.quaternion);
      look = o.clone().negate(); back = o.multiplyScalar(span * 0.15);
    } else {                          // an interior: down the long axis
      look = size.z >= size.x ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(-1, 0, 0);
      back = look.clone().multiplyScalar(-span * 0.3);
    }
    cam.position.set(at.x, eyeY, at.z).add(back);
    controls.target.copy(cam.position).addScaledVector(look, span * 0.3);
    controls.minDistance = 0.05; controls.maxDistance = span * 3;
    cam.near = 0.02; cam.far = span * 20; cam.updateProjectionMatrix();
    helpers.visible = false;
    controls.update();
    return true;
  }

  function resize() {
    const w = el.clientWidth || 640, h = el.clientHeight || 360;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = '100%'; renderer.domElement.style.height = '100%';
    cam.aspect = w / h; cam.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize); ro.observe(el);
  resize(); layout(); frame();

  // ---- regions: boxes in the model's own file units (children of the scaler,
  // so they scale and turn with it), moved and sized with handles. For a
  // scan with no named parts, this is how "the engine" comes to exist.
  const regionGroup = new THREE.Group(); model.userData.scaler.add(regionGroup);
  const gizmo = new TransformControls(cam, renderer.domElement);
  gizmo.setSize(0.8);
  const gizmoHelper = gizmo.getHelper(); scene.add(gizmoHelper);
  gizmo.addEventListener('dragging-changed', (e) => { controls.enabled = !e.value; if (!e.value && onRegions) onRegions(readRegions()); });
  let onRegions = null, regionMeshes = [];
  const regionMat = (sel) => new THREE.MeshBasicMaterial({ color: sel ? 0xffb347 : accent, transparent: true, opacity: sel ? 0.28 : 0.16, depthWrite: false });
  function readRegions() {
    return regionMeshes.map((r) => {
      const c = r.position, h = r.scale.clone().multiplyScalar(0.5);
      return { label: r.userData.label, box: [[c.x - h.x, c.y - h.y, c.z - h.z], [c.x + h.x, c.y + h.y, c.z + h.z]].map((v) => v.map((n) => +n.toFixed(5))) };
    });
  }
  function setRegions(list, selected = -1) {
    gizmo.detach();
    regionMeshes.forEach((r) => { r.geometry.dispose(); r.material.dispose(); regionGroup.remove(r); });
    regionMeshes = (list || []).map((reg, i) => {
      const [lo, hi] = reg.box, mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), regionMat(i === selected));
      mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: i === selected ? 0xffb347 : accent })));
      mesh.position.set((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
      mesh.scale.set(Math.max(1e-4, hi[0] - lo[0]), Math.max(1e-4, hi[1] - lo[1]), Math.max(1e-4, hi[2] - lo[2]));
      mesh.userData = { label: reg.label, set: true }; mesh.renderOrder = 2;
      mesh.traverse((o) => { o.userData.set = true; });
      regionGroup.add(mesh); return mesh;
    });
    if (regionMeshes[selected]) gizmo.attach(regionMeshes[selected]);
  }

  let alive = true;
  (function loop() {
    if (!alive) return;
    controls.update();
    renderer.render(scene, cam);
    requestAnimationFrame(loop);
  })();

  return {
    // Size in metres (width × height × length, after the heading), and the
    // raw file-unit measurement the server keeps.
    size: () => sizeMetres(model),
    measured: () => model.userData.measured.toArray().map((v) => +v.toFixed(5)),
    update(next, { reframe = false } = {}) {
      const prev = model.userData.manifest;
      applyManifest(model, next);
      if (reframe || prev.scale !== next.scale || prev.heading !== next.heading) { layout(); if (reframe || prev.scale !== next.scale) frame(); }
    },
    view(az, el2) { helpers.visible = true; frame(az, el2); },
    // What kind of model this is and what it limits (static/stage/intake.js).
    analyse() { const a = analyse(renderer, model.userData.inner); model.updateMatrixWorld(true); return a; },
    inside(a) { return frameInside(a); },
    // The pictures Claude identifies it from, chosen for its kind (identify.js).
    async idViews(kind, a) { const r = await renderViews(renderer, model.userData.inner, a || {}, kind); resize(); return r; },
    async zoomView(rect) { const r = await renderZoom(renderer, model.userData.inner, rect); resize(); return r; },
    regionHeight(rect) { return regionHeight(model.userData.inner, rect); },
    // Regions: show a list, select one for the handles, hear about edits.
    setRegions(list, selected = -1) { setRegions(list, selected); },
    regionMode(mode) { gizmo.setMode(mode === 'size' ? 'scale' : 'translate'); },
    onRegions(fn) { onRegions = fn; },
    // A starting box: a fifth of the model's size, at its middle (file units).
    newRegion(label) {
      const inner = model.userData.inner, b = new THREE.Box3().setFromObject(inner);
      const inv = new THREE.Matrix4().copy(model.userData.scaler.matrixWorld).invert();
      b.applyMatrix4(inv);
      const c = b.getCenter(new THREE.Vector3()), h = b.getSize(new THREE.Vector3()).multiplyScalar(0.1);
      return { label, box: [[c.x - h.x, c.y - h.y, c.z - h.z], [c.x + h.x, c.y + h.y, c.z + h.z]].map((v) => v.map((n) => +n.toFixed(5))) };
    },
    async partSheets(nodes, heading) { const r = await renderParts(renderer, model.userData.inner, nodes, heading); resize(); return r; },
    // A three-quarter view as a JPEG, without the helpers, for the library card.
    // A room's card is taken from inside (pass its analysis); anything else
    // from a three-quarter view outside.
    async snapshot(w = 640, h = 360, inside = null) {
      helpers.visible = false; regionGroup.visible = false; gizmoHelper.visible = false;
      const keep = { pos: cam.position.clone(), target: controls.target.clone(), aspect: cam.aspect };
      renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
      if (!(inside && frameInside(inside))) {
        const pts = points([model], 3000), sph = boxOf(model).getBoundingSphere(new THREE.Sphere());
        fit(cam, pts, { az: 35, el: 18, fill: 0.78, sceneRadius: sph.radius });   // room for the card's crop
      }
      cam.aspect = w / h; cam.updateProjectionMatrix();
      renderer.render(scene, cam);
      const blob = await new Promise((ok) => renderer.domElement.toBlob(ok, 'image/jpeg', 0.86));
      helpers.visible = true; regionGroup.visible = true; gizmoHelper.visible = true;
      cam.position.copy(keep.pos); controls.target.copy(keep.target);
      resize(); controls.update();
      return blob;
    },
    dispose() {
      alive = false; ro.disconnect(); controls.dispose(); gizmo.detach(); gizmo.dispose();
      if (set) set.dispose();
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        for (const m of [].concat(o.material || [])) { if (m.map) m.map.dispose(); m.dispose(); }
      });
      renderer.dispose(); renderer.forceContextLoss();
      el.innerHTML = '';
    },
  };
}

window.Stage3D = { mount, limitsFor, KINDS, VERSION, OBJECT_VIEWS };
window.dispatchEvent(new Event('stage3d-ready'));

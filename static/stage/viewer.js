// The model viewer used by the library's intake screen: one model on the
// stage floor, orbitable, with the two things a human needs to confirm it —
// an arrow on the floor marking the front (+z), and a 1.8 m figure beside it,
// so a model at the wrong scale is obvious at a glance.
//
// app.js is a classic script, so this hands it `window.Stage3D`.
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { THREE, loadModel, applyManifest, sizeMetres, buildSet, points, fit, boxOf } from './core.js';

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

  function resize() {
    const w = el.clientWidth || 640, h = el.clientHeight || 360;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = '100%'; renderer.domElement.style.height = '100%';
    cam.aspect = w / h; cam.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize); ro.observe(el);
  resize(); layout(); frame();

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
    view(az, el2) { frame(az, el2); },
    // A three-quarter view as a JPEG, without the helpers, for the library card.
    async snapshot(w = 640, h = 360) {
      helpers.visible = false;
      const keep = { pos: cam.position.clone(), target: controls.target.clone(), aspect: cam.aspect };
      renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
      const pts = points([model], 3000), sph = boxOf(model).getBoundingSphere(new THREE.Sphere());
      fit(cam, pts, { az: 35, el: 18, fill: 0.78, sceneRadius: sph.radius });   // room for the card's crop
      renderer.render(scene, cam);
      const blob = await new Promise((ok) => renderer.domElement.toBlob(ok, 'image/jpeg', 0.86));
      helpers.visible = true;
      cam.position.copy(keep.pos); controls.target.copy(keep.target);
      resize(); controls.update();
      return blob;
    },
    dispose() {
      alive = false; ro.disconnect(); controls.dispose();
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

window.Stage3D = { mount };
window.dispatchEvent(new Event('stage3d-ready'));

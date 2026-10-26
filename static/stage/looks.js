// How a shot is lit and what lies behind the model: one look per kind of
// model, shared by the renderer, the Stage tab's preview and the regression
// suite's contact sheets, so what is previewed is what is drawn.
//
// Only frames see a look. The checks run on the model alone (search.js),
// so a floor or a sky can never hide an edge or a hole from them.
//
//   set         an object on our stage floor: reflections, a sun with soft
//               shadows, a floor that fades into the background (core.js)
//   baked       a room whose scan already holds its light: a flat fill only
//   scan_sky    an aerial scan under a pale sky
//   city        a modelled city: our sun, and haze fixed for the shot that
//               hides the map's edge (checks.js, haze)
//   set_inside  a cutaway set, seen from inside, daylight through its windows
import * as THREE from 'three';
import { buildSet } from './core.js';

const SKY = { baked: 0xf2efe8, scan_sky: 0xb9d3ec, city: 0xc4d2e0, set_inside: 0xb9d3ec };

// The look for a model's kind (intake.js KINDS). A line-up of several
// objects is lit as one object.
export const lookFor = (kind) => ({
  interior: 'baked', aerial_site: 'scan_sky', modelled_site: 'city', set: 'set_inside',
}[kind] || 'set');

// Put a look on the scene. `models` are what `set` builds its floor and sun
// around; `haze` is the shot's haze check ({near, far}) for a city. Returns
// a function that takes the look off again.
export function applyLook(renderer, scene, look, { models = [], haze = null } = {}) {
  const g = new THREE.Group(), keep = { bg: scene.background, fog: scene.fog, env: scene.environment };
  let set = null;
  if (look === 'set') set = buildSet(renderer, scene, models);
  else {
    const sky = SKY[look] ?? 0x888888;
    scene.background = new THREE.Color(sky);
    g.add(new THREE.HemisphereLight(0xffffff, 0x555555, look === 'set_inside' ? 2 : 1.4));
    if (look === 'city') {
      const sun = new THREE.DirectionalLight(0xffffff, 1.8); sun.position.set(1, 2, 0.6); g.add(sun);
      if (haze && haze.far) scene.fog = new THREE.Fog(sky, haze.near, haze.far);
    }
    scene.add(g);
  }
  return () => {
    if (set) set.dispose();
    scene.remove(g); scene.background = keep.bg; scene.fog = keep.fog; scene.environment = keep.env;
  };
}

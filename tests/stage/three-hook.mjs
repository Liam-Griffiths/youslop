// Node resolves `three` the way the page's import map does: to the vendored
// copy. Run the stage tests with
//   node --import ./tests/stage/three-hook.mjs --test 'tests/stage/*.test.mjs'
import { register } from 'node:module';

register('data:text/javascript,' + encodeURIComponent(`
const root = ${JSON.stringify(new URL('../../static/vendor/three/', import.meta.url).href)};
export async function resolve(spec, ctx, next) {
  if (spec === 'three') return { url: root + 'three.module.js', shortCircuit: true };
  if (spec.startsWith('three/addons/')) return { url: root + 'addons/' + spec.slice(13), shortCircuit: true };
  return next(spec, ctx);
}`));

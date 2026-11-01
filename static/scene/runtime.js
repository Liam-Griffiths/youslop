/* Seekable composition runtime. Load before GSAP and all scene scripts. */
(() => {
  'use strict';
  const nativeFrame = window.requestAnimationFrame.bind(window);
  const nativeTimeout = window.setTimeout.bind(window);
  const nativeClearTimeout = window.clearTimeout.bind(window);
  let ready = false;
  window.__t = 0;
  window.__deterministic = true;
  window.__timelines = window.__timelines || {};
  Date.now = () => window.__t * 1000;
  Object.defineProperty(performance, 'now', {value: () => window.__t * 1000, configurable: true});
  let seed = 1, seedRoot = null;
  Math.random = () => {
    // A body composition may be parsed after this head script (and GSAP).
    const root = document.querySelector('[data-seed]');
    if (root && root !== seedRoot) {
      seedRoot = root;
      seed = Number(root.dataset.seed) >>> 0;
    }
    let n = seed += 0x6D2B79F5;
    n = Math.imul(n ^ n >>> 15, n | 1);
    n ^= n + Math.imul(n ^ n >>> 7, n | 61);
    return ((n ^ n >>> 14) >>> 0) / 4294967296;
  };
  for (const name of ['setTimeout', 'setInterval', 'requestAnimationFrame']) {
    const original = window[name].bind(window);
    window[name] = (...args) => {
      const stack = new Error().stack || '';
      const caller = stack.split('\n')[2] || '';
      if (ready && window.__deterministic && !/gsap\.min\.js|\/scene\/runtime\.js/.test(caller)) {
        console.warn(`Scene used ${name} after __ready; use a paused timeline.\n${stack}`);
      }
      return original(...args);
    };
  }
  const number = (value, fallback = 0) => Number.isFinite(parseFloat(value)) ? parseFloat(value) : fallback;
  const clipStart = el => {
    let start = 0;
    for (let c = el?.closest('.clip'); c; c = c.parentElement?.closest('.clip')) {
      start += number(c.dataset.start);
    }
    return start;
  };
  function variables(root, values) {
    for (const [key, value] of Object.entries(values)) root.style.setProperty(`--${key}`, String(value));
    for (const el of [root, ...root.querySelectorAll('[data-var-text], [data-var-src]')]) {
      if (el.dataset.varText in values) el.textContent = values[el.dataset.varText];
      if (el.dataset.varSrc in values) el.setAttribute('src', values[el.dataset.varSrc]);
    }
  }
  async function scripts(root, values) {
    window.__hyperframes = {getVariables: () => values};
    for (const old of [...root.querySelectorAll('script')]) {
      const script = document.createElement('script');
      for (const attr of old.attributes) script.setAttribute(attr.name, attr.value);
      // External scripts must finish before the next mount changes getVariables().
      const loaded = script.src ? new Promise((resolve, reject) => {
        script.onload = resolve;
        script.onerror = () => reject(new Error(`Cannot load component script: ${script.src}`));
      }) : null;
      script.textContent = old.textContent;
      old.replaceWith(script);
      if (loaded) await loaded;
    }
  }
  let mountCount = 0;
  async function mountAll(root, base = document.baseURI) {
    // Snapshot hosts before mounting, then recurse with the component's URL.
    const hosts = [...root.querySelectorAll('.clip[data-composition-src]')].filter(host => {
      const parent = host.parentElement.closest('.clip[data-composition-src]');
      return parent === root || !root.contains(parent);
    });
    for (const host of hosts) {
      const url = new URL(host.dataset.compositionSrc, base);
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Cannot mount ${url}: ${response.status}`);
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const decl = JSON.parse(doc.documentElement.dataset.compositionVariables || '[]');
      const vals = Object.fromEntries(decl.map(v => [v.id, v.default]));
      Object.assign(vals, JSON.parse(host.dataset.variableValues || '{}'));
      const template = doc.querySelector('template');
      if (!template) throw new Error(`Missing component template: ${url}`);
      const fragment = template.content.cloneNode(true);
      for (const el of fragment.querySelectorAll('[src], [href]')) {
        for (const attr of ['src', 'href']) {
          if (el.hasAttribute(attr)) el.setAttribute(attr, new URL(el.getAttribute(attr), url).href);
        }
      }
      host.appendChild(fragment);
      variables(host, vals);
      const id = doc.documentElement.dataset.compositionId;
      const before = window.__timelines[id];
      await scripts(host, vals);
      const tl = window.__timelines[id];
      if (tl && tl !== before) {
        delete window.__timelines[id];
        tl.data = {...tl.data, start: clipStart(host)};
        window.__timelines[`${id}#${mountCount++}`] = tl;
      }
      // Preserve another instance registered under the same composition id.
      if (before) window.__timelines[id] = before;
      await mountAll(host, url);
    }
  }
  let motions;
  const easeNames = {'quad-out':'power1.out', 'cubic-out':'power2.out', 'expo-out':'expo.out', 'linear':'none'};
  function preset(el, index) {
    const builder = el.hasAttribute('data-layer');
    const kind = builder ? el.dataset.motion || 'none' : el.dataset.anim;
    if (!motions[kind] || kind === 'none') return;
    const spec = motions[kind];
    const css = getComputedStyle(el);
    const dur = Math.max(0, number(el.dataset.duration));
    const arrive = Math.min(dur, Math.max(0.001, builder ? number(el.dataset.motionDuration, spec.duration) : number(el.dataset.animDur, number(css.getPropertyValue('--arrive-s'), spec.duration))));
    const exit = builder ? Math.min(dur / 2, number(el.dataset.motionExit)) : Math.min(dur / 2, arrive * Math.max(0, number(el.dataset.animExit, number(css.getPropertyValue('--exit-ratio'), 0.5))));
    let targets = el;
    if (kind === 'words' && !builder) {
      const parts = el.textContent.split(/(\s+)/);
      el.replaceChildren(...parts.map(word => {
        if (/^\s*$/.test(word)) return document.createTextNode(word);
        const span = document.createElement('span');
        span.style.display = 'inline-block'; span.textContent = word;
        return span;
      }));
      targets = el.querySelectorAll('span');
    }
    const from = {...spec.from}, to = {...spec.to};
    delete from.wipe; delete to.wipe;
    if ('y' in from) from.y = number(el.dataset.motionY || el.dataset.animY, from.y);
    if (builder && ['words', 'wipe'].includes(kind)) { from.clipPath = 'inset(0 100% 0 0)'; to.clipPath = 'inset(0 0% 0 0)'; }
    const tl = gsap.timeline({paused: true, data: {start: builder ? number(el.dataset.start) + number(el.closest('[data-screen]')?.dataset.start) : clipStart(el)}});
    const stagger = kind === 'words' && !builder ? {amount: arrive * 0.4} : 0;
    tl.fromTo(targets, from, {...to, duration: kind === 'words' && !builder ? arrive * 0.6 : arrive, stagger,
      ease: kind === 'pop' && !builder ? p => Math.min(1, 1.4 * (1 - (1 - p) ** 2)) : (builder ? easeNames[el.dataset.motionEase || spec.ease] : el.dataset.animEase || easeNames[spec.ease]) || 'back.out(1.70158)'}, 0);
    if (exit > 0) tl.to(targets, {opacity: 0, duration: exit, ease: 'power3.in'}, dur - exit);
    window.__timelines[`preset#${index}`] = tl;
  }
  function seekMedia(el, t) {
    el.pause();
    const parent = el.closest('.clip');
    if (parent && getComputedStyle(el).visibility !== 'visible') return Promise.resolve();
    const target = Math.max(0, Math.min(t - clipStart(el), Number.isFinite(el.duration) ? el.duration : Infinity));
    if (Math.abs(el.currentTime - target) < 0.00001 && !el.seeking) return Promise.resolve();
    return new Promise(resolve => {
      let timer;
      const done = () => {
        nativeClearTimeout(timer);
        el.removeEventListener('seeked', done);
        resolve();
      };
      el.addEventListener('seeked', done);
      timer = nativeTimeout(done, 500);
      try { el.currentTime = target; } catch (_) { done(); }
    });
  }
  // Publish the promise immediately: capture callers can await it while mounting.
  window.__ready = new Promise((resolve, reject) => {
    const init = async () => {
      try {
        const root = document.querySelector('[data-composition-id]');
        if (!root) throw new Error('Scene requires [data-composition-id]');
        const W = number(root.dataset.width, 1920), H = number(root.dataset.height, 1080);
        window.__composition = {width: W, height: H, duration: number(root.dataset.duration), fps: number(root.dataset.fps, 30)};
        for (const el of [document.documentElement, document.body]) {
          Object.assign(el.style, {width: `${W}px`, height: `${H}px`, overflow: 'hidden', margin: '0'});
        }
        variables(root, window.__vars || {});
        const bg = getComputedStyle(root).getPropertyValue('--bg').trim();
        if (bg) document.body.style.background = bg;
        await mountAll(root);
        const motionData = document.getElementById('scene-motion');
        motions = motionData ? JSON.parse(motionData.textContent) : await fetch('/static/scene/motion.json').then(r => { if (!r.ok) throw new Error('Cannot load motion table'); return r.json(); });
        root.querySelectorAll('[data-anim], [data-layer]').forEach(preset);
        const clips = [...document.querySelectorAll('.clip')];
        const style = document.createElement('style');
        style.textContent = '*{transition:none!important;animation-play-state:paused!important;caret-color:transparent!important}';
        document.head.appendChild(style);
        window.__seek = async t => {
          t = Number(t);
          if (!Number.isFinite(t)) throw new Error('Scene seek time must be finite');
          window.__t = t;
          for (const el of clips) {
            const start = clipStart(el);
            // A nested clip must also be inside every ancestor's active interval.
            let visible = true;
            for (let c = el; c; c = c.parentElement?.closest('.clip')) {
              const s = clipStart(c);
              visible &&= t >= s && t < s + number(c.dataset.duration);
            }
            el.style.visibility = visible && t >= start ? 'visible' : 'hidden';
          }
          for (const el of document.querySelectorAll('[data-screen], [data-layer]')) {
            const start = number(el.dataset.start) + (el.hasAttribute('data-layer') ? number(el.closest('[data-screen]')?.dataset.start) : 0);
            el.style.visibility = t >= start && t < start + number(el.dataset.duration, window.__composition.duration) ? 'visible' : 'hidden';
          }
          for (const tl of Object.values(window.__timelines)) {
            tl.pause(); tl.time(Math.max(0, t - number(tl.data?.start)), false);
          }
          const screen = [...document.querySelectorAll('[data-screen]')].find(e =>
            t >= number(e.dataset.start) && t < number(e.dataset.start) + number(e.dataset.duration));
          const camera = JSON.parse(screen?.dataset.camera || root.dataset.camera || '[]');
          if (camera.length && !window.__builderCapture) {
            let a = camera[0], b = camera[camera.length - 1];
            for (let i = 1; i < camera.length; i++) { if (t < camera[i].t) { a = camera[i-1]; b = camera[i]; break; } a = camera[i]; }
            const p = b.t > a.t ? Math.max(0, Math.min(1, (t-a.t)/(b.t-a.t))) : 1;
            const q = gsap.parseEase(easeNames[b.ease || 'linear'] || 'back.out(1.70158)')(p);
            const value = (k, d) => (a[k] ?? d) + ((b[k] ?? d)-(a[k] ?? d))*q;
            const z = value('zoom', 1), x = Math.max(0, Math.min(W-W/z, value('x',0))), y = Math.max(0, Math.min(H-H/z, value('y',0)));
            document.body.style.transformOrigin = '0 0';
            document.body.style.transform = `scale(${z}) translate(${-x}px,${-y}px)`;
          }
          gsap.ticker.sleep();
          for (const animation of document.getAnimations()) {
            animation.pause();
            animation.currentTime = (t - clipStart(animation.effect?.target)) * 1000;
          }
          await Promise.all([...document.querySelectorAll('video, audio')].map(el => seekMedia(el, t)));
          await new Promise(resolveFrame => nativeFrame(resolveFrame));
        };
        await document.fonts.ready;
        const query = new URLSearchParams(location.search);
        await window.__seek(query.has('demo') ? number(query.get('t')) : 0);
        ready = true;
        resolve();
      } catch (error) { reject(error); }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
    else init();
  });
})();

"""Appearance contracts use synthetic settings and GJS; no browser or media work."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def test_shared_theme_setting(tmp_path, monkeypatch):
    from app import main, settings
    monkeypatch.setattr(settings, 'path', lambda: tmp_path / 'settings.json')
    assert main.get_theme() == {'theme': 'system'}
    for mode in ('light', 'dark', 'system'):
        assert not main.save_settings({'theme': mode})['restart_required']
        assert main.get_theme() == {'theme': mode}
        assert settings.load_file()['theme'] == mode
        assert '' not in settings.environment_overrides()
    assert main.save_settings({'user_agent': 'Creator'})['restart_required']
    with pytest.raises(ValueError, match='Theme must'):
        settings.save_file({'theme': 'sepia'})
    assert settings.load_file()['user_agent'] == 'Creator'


def test_css_hex_only_in_tokens_or_media():
    css = Path('static/styles.css').read_text()
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    # These literals belong to content viewing surfaces, independent of app theme.
    media = {
        '.cast-focus': {'#A0A6AE'},  # Caption over a dark portrait scrim.
        '.pick .kindtag': {'#6FB7FF'},  # Badge over a dark picture scrim.
        '.pick-meta': {'#cfd3dd'},  # Caption over picture gradient.
        '.focal-stage': {'#07080b'},  # Image viewing matte.
        '.thumb .src': {'#cfd3dd'},  # Thumbnail caption over gradient.
        '.thumb .kindtag, .lib-thumb .kindtag': {'#6FB7FF'},  # Image badges.
        '.play-btn::after': {'#fff'},  # White play triangle over media.
        '.clip-modal video': {'#000'},  # Video letterboxing.
        'video': {'#000'},  # Video letterboxing.
        '.tl-stage': {'#000'},  # Timeline player letterboxing.
        '.tl-msg': {'#A0A6AE'},  # Player message over a dark scrim.
        '.tl-pic': {'#222'},  # Timeline picture matte.
        '.tl-tag': {'#fff', '#000'},  # Picture caption and shadow.
        '.tl-pic.slate': {'#2a2540', '#1d2a3a'},  # Slate preview artwork.
        '.model-view': {'#1d232a'},  # 3D viewing matte.
        '.camera-frame': {'#000'},  # Camera letterboxing.
        '.camera-thirds': {'#ffffff55'},  # Guides over the camera feed.
        '.camera-headroom': {'#fff8'},  # Guide over the camera feed.
        '.camera-prompter': {'#000b'},  # Camera prompter scrim.
    }
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
        selector, body = match.groups()
        selector = ' '.join(selector.split())
        if selector.startswith(':root'):
            continue
        literals = set(re.findall(r'#[\da-fA-F]{3,8}\b', body))
        assert literals <= media.get(selector, set()), (selector, literals)


def test_theme_switch_and_shared_sync(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    harness = r'''
const loop = new imports.gi.GLib.MainLoop(null, false);
const check = (ok, message) => { if (!ok) throw Error(message); };
const events={}, choices=['system','light','dark'].map(mode=>({dataset:{themeChoice:mode},
  setAttribute(key,value){this[key]=value;}}));
const toggle={setAttribute(key,value){this[key]=value;}};
const document={documentElement:{dataset:{}}, querySelectorAll:()=>choices,
  getElementById:()=>toggle, hidden:false};
const window={addEventListener:(name,fn)=>events[name]=fn,
 matchMedia:()=>({addEventListener:(name,fn)=>events.os=fn})};
let timer, shared='system', saved=[], notices=[], storageBroken=false, hold;
const localStorage={setItem(key,value){if(storageBroken) throw Error('private');}};
const setInterval=fn=>timer=fn;
const toast=message=>notices.push(message);
const api=async (url,options)=>{
 if(options){const mode=JSON.parse(options.body).theme;
  if(hold) { const wait=hold; hold=null; await wait; }
  shared=mode; saved.push(mode); return {};}
 return {theme:shared};
};
'''
    checks = r'''
(async()=>{
 await syncTheme();
 check(themeMode()==='system','default System');
 events.os(); check(themeMode()==='system','OS change keeps System preference');
 await setTheme('light');
 check(themeMode()==='light' && shared==='light' && choices[1]['aria-pressed']==='true','immediate switch and save');
 check(toggle['aria-label'].includes('Switch to dark'),'accessible cycle label');
 let release; hold=new Promise(resolve=>release=resolve);
 const first=setTheme('dark'), second=setTheme('system');
 check(themeMode()==='system' && !('theme' in document.documentElement.dataset),'System clears explicit theme');
 await syncTheme(); check(themeMode()==='system','poll does not clobber pending choice');
 release(); await Promise.all([first,second]);
 check(saved.join(',')==='light,dark,system' && shared==='system','rapid clicks save in order');
 shared='dark'; await syncTheme(); check(themeMode()==='dark','other webview updates');
 await cycleTheme(); check(themeMode()==='system','cycle includes System');
 events.storage({key:'corkbored-theme',newValue:'light'});
 check(themeMode()==='light','same-browser storage update');
 storageBroken=true; await setTheme('dark');
 check(shared==='dark' && themeMode()==='dark','private storage still uses shared setting');
 await setTheme('invalid'); check(themeMode()==='dark','invalid mode ignored');
 check(notices.length===0 && typeof timer==='function','poll registered without errors');
})().catch(e=>{printerr(e.stack); imports.system.exit(1);}).finally(()=>loop.quit());
loop.run();
'''
    path = tmp_path / 'theme.js'
    path.write_text(harness + Path('static/js/theme.js').read_text() + checks)
    result = subprocess.run([gjs, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_light_tokens_match_system_and_meet_text_contrast():
    css = Path('static/styles.css').read_text()
    tokens = lambda block: dict(re.findall(r'(--[\w-]+):\s*([^;]+);', block))
    explicit = tokens(css.split(':root[data-theme="light"] {', 1)[1].split('}', 1)[0])
    system = tokens(css.split(':root:not([data-theme="dark"]) {', 1)[1].split('}', 1)[0])
    assert explicit == system
    def luminance(hex_colour):
        rgb = [int(hex_colour[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
        return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
    for name in ('ink', 'ink-2', 'dim', 'accent-ink', 'cool', 'good', 'warn', 'bad'):
        for surface in ('bg', 'panel', 'raised'):
            light, dark = sorted([luminance(explicit['--'+name]), luminance(explicit['--'+surface])], reverse=True)
            assert (light + .05) / (dark + .05) >= 4.5, (name, surface)

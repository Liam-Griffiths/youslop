"""Unfinished actions stay quiet; exercise plain JS with GJS, without a browser."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def test_no_unfinished_feature_copy():
    root = Path(__file__).resolve().parents[2]
    files = [root / 'static/index.html', *sorted((root / 'static').rglob('*.js'))]
    forbidden = re.compile(r'not available yet|coming soon', re.IGNORECASE)
    hits = [f'{path.relative_to(root)}:{line_no}: {line.strip()}'
            for path in files
            for line_no, line in enumerate(path.read_text().splitlines(), 1)
            if forbidden.search(line)]
    assert not hits, '\n'.join(hits)


def test_unsupported_actions_are_disabled(tmp_path):
    gjs = shutil.which('gjs')
    if not gjs:
        pytest.skip('GJS unavailable')
    source = '\n'.join(Path(path).read_text() for path in (
        'static/js/timeline/draw.js', 'static/js/timeline/inspect.js',
        'static/js/timeline/graphics.js'))
    harness = r'''
const loop = new imports.gi.GLib.MainLoop(null, false);
function check(ok, message) { if (!ok) throw Error(message); }
const state = {project:{id:'p', slides:[{id:'s',kind:'essay',takes:{}}]}};
const TL = {pid:'p',cur:1};
const document = {createElement:()=>({}), querySelector:()=>null};
const isCut = kind => kind === 'loudmouth';
const pictureKind = slide => slide.kind;
let writes = 0, refreshes = 0, notices = 0;
const api = async () => { writes++; return {unsupported:'cue'}; };
const toast = () => { notices++; };
const tlRefresh = async () => { refreshes++; };
function buttons(fix, extra={}) {
  const row = {children:[], append(item){this.children.push(item);}};
  tlFixButtons(row, {id:'n',fix,...extra});
  return row.children;
}
function tlParas() { return [{id:'s',start:0,duration:3}]; }
function tlPause() { throw Error('Unsupported split must stop before playback changes'); }
function tlMsg() { notices++; }
(async () => {
  for (const fix of [{kind:'timing'}, {kind:'unsupported'}, {kind:'cue',slide_id:'s'},
                     {kind:'title',unsupported:true}]) {
    const [fixButton,dismiss,keep] = buttons(fix);
    check(fixButton.disabled, 'unsupported fix disabled');
    check(!dismiss.disabled && !keep.disabled, 'dismiss and keep retained');
  }
  check(buttons({kind:'title'},{proposal:{unsupported:'title'}})[0].disabled,
        'persisted unsupported proposal disabled');
  for (const kind of ['title','text','picture','look'])
    check(!buttons({kind,slide_id:'s'})[0].disabled, 'working fix retained');
  state.project.slides[0].kind = 'loudmouth';
  const [fix,dismiss] = buttons({kind:'cue',slide_id:'s'});
  check(!fix.disabled, 'drawn-cut cue fix enabled');
  await fix.onclick();
  check(fix.disabled && writes === 1 && notices === 0, 'guard response disables quietly');
  await dismiss.onclick();
  check(refreshes === 1 && !dismiss.disabled, 'dismiss still works');
  state.project.slides[0].takes = {camera:{video:'raw/camera.webm'}};
  check(!tlCanSplit(state.project.slides[0]), 'camera split disabled');
  await tlSplitHere();
  check(writes === 2 && notices === 0, 'camera shortcut stops without request or notice');
  state.project.slides[0].takes = {voice:{path:'takes/voice.wav'}};
  check(tlCanSplit(state.project.slides[0]), 'voice split retained');
  state.project.kind = 'clip';
  await openGraphicPicker('s');
  check(writes === 2 && notices === 0, 'clip graphic shortcut stays quiet');
})().catch(error => { printerr(error.stack); imports.system.exit(1); })
  .finally(() => loop.quit());
loop.run();
'''
    script = tmp_path / 'unfinished.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([gjs, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

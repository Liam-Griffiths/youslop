"""Copy regressions with synthetic inputs; no browser, models or rendering."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from app import ops, script_gen
from app.schema import Project


def test_music_empty_state_stays_in_music_sections():
    for path in Path('static/js').rglob('*.js'):
        # Allow music-specific helpers; reject this copy in any other function.
        for match in re.finditer('No music yet', path.read_text()):
            functions = list(re.finditer(r'(?:async )?function (\w+)\(', path.read_text()[:match.start()]))
            assert functions and 'music' in functions[-1][1].lower(), str(path)
    channel = Path('static/js/tabs/channels.js').read_text()
    assert 'No videos yet' in channel


@pytest.mark.parametrize('words', [1, 11, 119])
def test_short_script_gives_minimum_and_count(words):
    text = 'word ' * words
    message = f'Paste at least 120 words (you have {words}).'
    with pytest.raises(ops.PayloadError) as error:
        ops.prepare_create({'script': text})
    assert str(error.value) == message
    with pytest.raises(ValueError) as error:
        script_gen.import_script(Project(id='copy', idea='Copy test'), text)
    assert str(error.value) == message


def test_home_modes_word_count_and_trial_labels(tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS required')
    source = '\n'.join(Path(p).read_text() for p in [
        'static/js/tabs/home.js', 'static/js/tabs/blocks_browser.js', 'static/js/jobs.js'])
    harness = r'''
const check = (ok, msg) => { if (!ok) throw Error(msg); };
class Option { constructor(){this.dataset={};} }
const state = {}, esc = s => String(s ?? ''), setInterval = () => 1;
const nodes = {}, $ = key => nodes[key] ||= {value:'',querySelector:()=>null,
  querySelectorAll:()=>[],add(){},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}};
let message;
const toast = text => {message=text;}, api = () => {throw Error('Unexpected API call');};
''' + source + r'''
for (const words of [0, 1, 11, 119]) {
  state.mode='script'; $('#script').value='  '+('word '.repeat(words))+'\n';
  await createProject({});
  check(message===`Paste at least 120 words (you have ${words}).`,'exact word count');
}
homeStart('script');
check($('#mins').disabled && $('#mins').title==='Set by your script','script length disabled');
check($('#mins')['aria-describedby']==='script-length-note','script length explanation linked');
homeStart('idea'); check(!$('#mins').disabled && !$('#mins').title,'idea length enabled again');
newTestRun(true); check($('#mins').disabled,'test run still disables length');
const label=blockTrialField('raw_name',{label:'Display name',type:'text',default:''},0);
check(label.includes('>Display name</label>') && label.includes('title="text"'),'label and tooltip');
check(blockTrialField('title_text',{type:'text',default:''},1).includes('>Title Text</label>'),'fallback');
check(jobLabel({kind:'script'})==='Script','sentence case job label');
'''
    script = tmp_path / 'copy.mjs'
    script.write_text(harness)
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

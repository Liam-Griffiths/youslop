"""Missing current files are actionable; checks and mixes never edit recordings."""
from copy import deepcopy
import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import pytest

from app import audio, check, ffutil, main, ops, recording_health, render, review, store
from app.audio_files import next_raw_path, next_take_path
from app.schema import Project, Slide, SponsorSlot


@pytest.fixture
def cut(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    monkeypatch.setattr('app.llm.complete_json', lambda *a, **kw: pytest.fail('LLM called'))
    monkeypatch.setattr('app.stage.browser', lambda: None)
    p = Project(id='missing-recordings', idea='Synthetic recovery', use_intro=False, use_outro=False)
    p.style.format = 'board'
    p.slides = [Slide(id='a', narration='A good recording.'), Slide(id='b', narration='A missing recording.')]
    root = store.project_dir(p.id)
    path = root / 'takes/good.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(i * .08))) for i in range(24000)))
    p.set_take(p.slides[0], 'mic', dict(path='takes/good.wav', duration=.5))
    p.set_take(p.slides[1], 'mic', dict(path='takes/missing.wav', duration=1,
        raw_path='raw/original.wav', cuts=[dict(a=.25, b=.5, by='hand')]))
    shutil.copyfile(path, root / 'raw/original.wav')
    p.slides[1].history = [dict(path='takes/absent-history.wav', duration=2, track='mic')]
    store.save(p)
    return p, root


def test_check_one_p0_and_render_gate_are_read_only(cut, monkeypatch):
    p, root = cut
    before = {f: f.read_bytes() for f in root.rglob('*') if f.is_file()}
    result = check.run(p)
    assert result['counts']['P0'] == 1
    finding = next(f for f in result['findings'] if f['level'] == 'P0')
    assert finding['code'] == 'missing_recording'
    assert '¶2' in finding['msg'] and 'takes/missing.wav' in finding['msg']
    assert finding['fix']['reprocess'] and finding['fix']['track'] == 'mic'
    assert main.get_project(p.id)['missing_recordings'] == recording_health.missing(p)
    monkeypatch.setattr(ops.renderer, 'render', lambda *a, **kw: pytest.fail('Full render called'))
    assert ops.render(p.id, {}, lambda _: None)['error'] == 'Render blocked by P0 issues.'
    assert all(f.read_bytes() == content for f, content in before.items())
    assert not (root / 'takes/missing.wav').exists()


def test_all_tracks_sponsors_and_inserts_exclude_history(cut, monkeypatch):
    p, root = cut
    p.slides[1].takes['kokoro'] = dict(path='takes/draft.wav', duration=1)
    p.sponsors = [SponsorSlot(id='ad', after_slide_id='a', take=dict(path='takes/ad.wav', duration=1)),
                  SponsorSlot(id='off', enabled=False, take=dict(path='takes/off.wav', duration=1))]
    p.slides.append(Slide(id='insert', insert=dict(kind='clip', seconds=.5, in_s=0,
        shoot_id='shoot', source_id='source', source_audio=True)))
    monkeypatch.setattr('app.inserts.source', lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError('gone')))
    items = recording_health.missing(p)
    assert {(r['owner'], r['id'], r['track']) for r in items} == {
        ('slides', 'b', 'mic'), ('slides', 'b', 'kokoro'), ('sponsors', 'ad', ''), ('inserts', 'insert', '')}
    findings = [f for f in check.run(p)['findings'] if f['code'] == 'missing_recording']
    assert len(findings) == len({review.note_id(f) for f in findings}) == 4
    assert not next(r for r in items if r['track'] == 'kokoro')['active']
    assert not next(r for r in items if r['track'] == 'kokoro')['reprocess']
    monkeypatch.setattr('app.inserts.source', lambda *a, **kw: root / 'takes/good.wav')
    assert not any(r['owner'] == 'inserts' for r in recording_health.missing(p))


@pytest.mark.parametrize('path', ['takes/missing.wav', ''])
def test_missing_mix_preserves_duration_and_good_audio(cut, tmp_path, caplog, path):
    p, root = cut
    p.slides[1].take['path'] = path
    before = deepcopy(p.to_dict())
    files = {f: f.read_bytes() for folder in ('takes', 'raw') for f in (root / folder).rglob('*') if f.is_file()}
    out = tmp_path / 'narration.wav'
    length = audio.build_slice(p, p.slides, out, head=0)
    assert length == pytest.approx(.5 + .75 + sum(audio.paragraph_gaps(p)), abs=.003)
    with wave.open(str(out)) as wav:
        samples = struct.unpack('<' + 'h' * wav.getnframes(), wav.readframes(wav.getnframes()))
    assert max(abs(x) for x in samples[:20000]) > 1000
    silent_start = round((.5 + audio.paragraph_gaps(p)[0]) * 48000)
    assert not any(samples[silent_start:])
    assert 'Sound mixed without ¶2: its recording is missing.' in caplog.text
    assert p.to_dict() == before
    assert {f: f.read_bytes() for folder in ('takes', 'raw') for f in (root / folder).rglob('*') if f.is_file()} == files


def test_timeline_warning_cache_and_sponsor_insert_inputs(cut, monkeypatch):
    p, root = cut
    p.sponsors = [SponsorSlot(id='ad', after_slide_id='a', take=dict(path='takes/ad.wav', duration=.5))]
    p.slides.append(Slide(id='insert', insert=dict(kind='clip', seconds=.5, in_s=0,
        shoot_id='shoot', source_id='source', source_audio=True)))
    monkeypatch.setattr('app.inserts.source', lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError('gone')))
    commands = []
    def run(args, **kw):
        commands.append(args)
        Path(args[-1]).write_bytes(b'mixed')
    monkeypatch.setattr(ffutil, 'run', run)
    monkeypatch.setattr(ffutil, 'duration', lambda _: 4)
    monkeypatch.setattr(render, '_master_audio_graph', lambda p, inputs, graph, *a: graph)
    mixed = render.build_mix(p)
    assert mixed['ready'] and len(mixed['warnings']) == 3
    assert any('¶2' in text for text in mixed['warnings'])
    assert commands[0].count('anullsrc=r=48000:cl=mono') == 2
    assert commands[1].count('anullsrc=r=48000:cl=mono') == 1
    assert not any(str(root / 'takes/missing.wav') in args for args in commands)
    assert render.build_mix(p) == mixed and len(commands) == 2
    shutil.copyfile(root / 'takes/good.wav', root / 'takes/missing.wav')
    assert not render.timeline(p)['mix']['ready']
    assert all('¶2' not in text for text in render.timeline(p)['mix']['warnings'])


def test_reprocess_fresh_path_preserves_old_reference(cut, monkeypatch):
    p, root = cut
    item = recording_health.missing(p)[0]
    original = deepcopy(p.slides[1].take)
    raw = (root / original['raw_path']).read_bytes()
    def process(src, out, voice):
        assert src.read_bytes() == raw
        assert out != root / original['path']
        shutil.copyfile(src, out)
        return dict(duration=1)
    monkeypatch.setattr(audio, 'process_take', process)
    result = main.reprocess_recording(p.id, item)
    restored = store.load(p.id).slides[1]
    assert (root / restored.take['path']).is_file()
    assert restored.history[-1]['path'] == original['path']
    assert restored.history[-1]['reason'] == 'reprocess'
    assert not (root / original['path']).exists()
    assert (root / original['raw_path']).read_bytes() == raw
    assert result['missing_recordings'] == []
    assert next_take_path(root, '', 'missing') != root / original['path']
    p = store.load(p.id)
    p.slides[1].history.append(dict(path='takes/retired.wav', raw_path='raw/retired.webm'))
    store.save(p)
    assert next_take_path(root, '', 'retired').name == 'retired.2.wav'
    assert next_raw_path(root, 'retired').name == 'retired.2.webm'
    with pytest.raises(main.HTTPException, match='changed'):
        main.reprocess_recording(p.id, item)


def test_voice_markup_and_edit_warning_without_browser(cut, tmp_path):
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('gjs unavailable')
    repo = Path(__file__).resolve().parents[2]
    source = '\n'.join((repo / path).read_text() for path in [
        'static/js/tabs/record.js', 'static/js/tabs/recording_health.js',
        'static/js/timeline/draw.js', 'static/js/timeline/playback.js'])
    harness = r'''
const state = {project:{voice_track:'mic',slides:[{id:'s',narration:'Hello',
  take:{path:'gone.wav'},takes:{mic:{path:'gone.wav'}},history:[{path:'old.wav'}]}],
  missing_recordings:[{owner:'slides',id:'s',track:'mic',path:'gone.wav',active:true,reprocess:true}]},rec:{index:0}};
const cameraLocked = () => false, fmtTime = x => '0:01', esc = x => String(x || '');
function check(value) { if (!value) throw Error('Missing recording UI assertion'); }
check(voiceParagraphList(state.project).includes('voice-paragraph missing'));
const panel = voiceTakesPanel(state.project,state.project.slides[0]);
check(panel.includes('This file is missing on disk.') && panel.includes('>Reprocess</button>'));
check(panel.includes('>Record</button>') && panel.includes('>Re-voice</button>'));
check(!panel.includes('in the cut') && !panel.includes('src="/api/projects/undefined/file/gone.wav"'));
check(panel.includes('file/old.wav'));
const note = {}, $ = () => note;
const TL = {data:{segments:[],total:2,mix:{audible:true,ready:true,warnings:[
  'Sound mixed without ¶2: its recording is missing.']}}};
tlPaintNote();
check(note.textContent.includes('Sound mixed without ¶2: its recording is missing.'));
'''
    script = tmp_path / 'missing.js'
    script.write_text(source + '\n' + harness)
    result = subprocess.run([runtime, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

"""Delivery defaults and migration; LLM and camera processing stay mocked."""
import asyncio
from tempfile import SpooledTemporaryFile

import pytest
from fastapi import HTTPException, UploadFile

from app import main, ops, script_gen, store
from app.schema import Presenter, Project, Slide, new_project
from tests.unit.test_camera_render import test_presenter_command_unchanged
from tests.unit.test_graph_golden import test_segment_graph as _legacy_segment_graph


@pytest.mark.parametrize('name,fmt,size,fps', [
    ('doc_full', 'kenburns', (1920, 1080), 30),
    ('essay_full', 'essay', (1920, 1080), 30),
    ('doc_preview', 'kenburns', (480, 270), 15),
])
def test_presenter_segment_graph(project, request, name, fmt, size, fps):
    project.presenter = Presenter(path='legacy.mp4', source_duration=5)
    _legacy_segment_graph(project, request, name, fmt, size, fps)


@pytest.mark.parametrize('delivery', ['voice_over', 'on_camera', 'mixed'])
def test_delivery_creation_and_generated_paragraphs(monkeypatch, delivery):
    p, _ = ops.prepare_create({'idea': 'A synthetic story', 'delivery': delivery})
    assert store.load(p.id).delivery == delivery
    assert Project.from_dict(p.to_dict()).delivery == delivery
    prompts = []
    def complete(prompt, **kwargs):
        prompts.append(prompt)
        assert kwargs['system'] == script_gen.NARRATOR_SYSTEM
        return [{'text': 'You can see the story here.', 'visual': 'A map'}]
    monkeypatch.setattr(script_gen, 'complete_json', complete)
    outline = {'sections': [{'heading': 'Opening', 'kind': 'intro', 'words': 55}]}
    slides = script_gen.write_script(p, outline)
    assert slides and all(s.on_camera == (delivery == 'on_camera') for s in slides)
    assert (script_gen.CAMERA_DELIVERY in prompts[0]) == (delivery == 'on_camera')
    other = new_project(p.idea)
    other.delivery = 'mixed' if delivery == 'on_camera' else 'on_camera'
    assert script_gen.draft_key(other) != script_gen.draft_key(p)


def test_old_delivery_default_and_validation():
    assert Project.from_dict({'id': 'old', 'idea': 'Old project'}).delivery == 'voice_over'
    assert new_project('Default project').delivery == 'voice_over'
    with pytest.raises(ops.PayloadError, match='Delivery'):
        ops.prepare_create({'idea': 'Synthetic project', 'delivery': 'typo'})


@pytest.mark.parametrize('fidelity', ['faithful', 'adapted'])
def test_import_camera_and_faithful_words(monkeypatch, fidelity):
    p = new_project('Synthetic import', delivery='on_camera')
    text = ' '.join(f'You have the original sentence number {i}.' for i in range(25))
    parts = text.split('. ')
    paragraphs = ['. '.join(parts[:8]) + '.', '. '.join(parts[8:16]) + '.', '. '.join(parts[16:])]
    prompts = []
    def complete(prompt, **kwargs):
        prompts.append(prompt)
        if 'Return JSON:' in prompt:
            return {'title': 'Original sentences'}
        return [{'text': t, 'visual': 'A map', 'beat': 'Original'} for t in paragraphs]
    monkeypatch.setattr(script_gen, 'complete_json', complete)
    for name in ('plan_visuals', 'plan_cues', '_plan_style_slides'):
        monkeypatch.setattr(script_gen, name, lambda *a: None)
    script_gen.import_script(p, text, fidelity=fidelity)
    assert all(s.on_camera for s in p.slides)
    assert ' '.join(s.narration for s in p.slides) == text
    assert (script_gen.CAMERA_DELIVERY in prompts[1]) == (fidelity == 'adapted')
    if fidelity == 'faithful':
        assert script_gen.FAITHFUL_RULES in prompts[1]


@pytest.fixture
def camera_project(monkeypatch):
    p = new_project('Synthetic camera migration')
    p.slides = [Slide(narration='Existing words')]
    p.presenter = Presenter(path='presenter/original.mp4', filename='original.mp4',
                            source_duration=6, trim_start=1, trim_end=1, focal=[.3, .4])
    store.save(p)
    root = store.project_dir(p.id)
    (root / 'presenter').mkdir()
    (root / p.presenter.path).write_bytes(b'original recording')
    def process(raw, wav, mp4, voice):
        wav.write_bytes(b'clean sound')
        mp4.write_bytes(b'clean picture')
        return dict(duration=5, trimmed=[.5, 5.5], av_offset=0, sync_warning=False, kind='camera')
    monkeypatch.setattr(main.camera, 'process_camera_take', process)
    monkeypatch.setattr(main.words_mod, 'estimate', lambda *a: [])
    return p


@pytest.mark.parametrize('position,index', [('after_intro', 0), ('end', 1)])
def test_add_camera_paragraph(camera_project, position, index):
    p = camera_project
    with SpooledTemporaryFile() as source:
        source.write(b'new recording')
        source.seek(0)
        result = asyncio.run(main.add_camera_paragraph(p.id,
            UploadFile(filename='new.mp4', file=source),
            position=position, convert_presenter=False))
    q = store.load(p.id)
    assert q.slides[index].id == result['sid']
    assert q.slides[index].on_camera and q.slides[index].takes['camera']['video']
    assert q.presenter.to_dict() == p.presenter.to_dict()
    assert next(s for s in q.slides if s.id == p.slides[0].id).narration == 'Existing words'


def test_add_before_selected_paragraph(camera_project):
    p = camera_project
    p.slides.append(Slide(narration='Second paragraph'))
    store.save(p)
    with SpooledTemporaryFile() as source:
        source.write(b'new recording')
        source.seek(0)
        result = asyncio.run(main.add_camera_paragraph(p.id,
            UploadFile(filename='new.mp4', file=source),
            position=f'before:{p.slides[1].id}', convert_presenter=False))
    assert [s['id'] for s in result['project']['slides']] == [p.slides[0].id, result['sid'], p.slides[1].id]


def test_convert_presenter_keeps_original_and_trim(camera_project):
    p = camera_project
    result = asyncio.run(main.add_camera_paragraph(p.id, position='end', convert_presenter=True))
    q = store.load(p.id)
    assert not q.presenter.enabled
    s = next(s for s in q.slides if s.id == result['sid'])
    take = s.takes['camera']
    assert take['cuts'] == [{'a': 0., 'b': .5, 'by': 'hand'}, {'a': 4.5, 'b': 5., 'by': 'hand'}]
    assert take['focal'] == [.3, .4]
    assert (store.project_dir(p.id) / p.presenter.path).read_bytes() == b'original recording'
    assert (store.project_dir(p.id) / take['raw_path']).read_bytes() == b'original recording'


def test_failed_conversion_keeps_legacy(camera_project, monkeypatch):
    p = camera_project
    def fail(*a):
        raise ValueError('Synthetic processing failure')
    monkeypatch.setattr(main.camera, 'process_camera_take', fail)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.add_camera_paragraph(p.id, position='end', convert_presenter=True))
    assert 'Camera paragraph kept' in error.value.detail
    assert store.load(p.id).presenter.to_dict() == p.presenter.to_dict()
    assert (store.project_dir(p.id) / p.presenter.path).read_bytes() == b'original recording'


def test_delivery_and_presenter_ui(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS needed for plain JS checks')
    root = Path(__file__).resolve().parents[2]
    sources = '\n'.join((root / 'static/js/tabs' / name).read_text()
                        for name in ('home.js', 'camera.js', 'render.js'))
    script = tmp_path / 'talking-head.mjs'
    script.write_text(r'''
const assert = (v, why) => {if (!v) throw Error(why);};
const saved = new Map();
const localStorage = {getItem:k => saved.get(k) ?? null, setItem:(k,v) => saved.set(k,v)};
const state = {rec:{index:0},project:{id:'p1',delivery:'on_camera',slides:[{id:'s1',narration:'Words'}]}};
const esc = s => String(s ?? '');
function videoTag(src, media, attrs){return `<video ${attrs}></video>`;}
''' + sources + r'''
assert(cameraMode(), 'delivery selects camera on first visit');
localStorage.setItem('cb_record_mode_p1','voice');
assert(!cameraMode(), 'saved voice choice respected');
state.project.slides[0].on_camera = true;
assert(cameraMode(), 'per-paragraph camera still wins');
state.project.slides[0].on_camera = false;
state.project.delivery = 'mixed'; saved.clear();
assert(!cameraMode(), 'mixed keeps paragraph choice');
let panel = presenterPanel(state.project);
assert(panel.includes('Add a paragraph on camera'), 'new import action');
assert(!panel.includes('uploadPresenter'), 'legacy upload retired');
state.project.presenter = {path:'legacy.mp4',enabled:true,has_audio:true,duration:2,source_duration:3,
  trim_start:0,trim_end:1,position:'start',focal:[]};
state.project.style = {transition:.5};
panel = presenterPanel(state.project);
assert(panel.includes('Convert to a camera paragraph'), 'legacy conversion offered');
assert(panel.includes('after the slate'), 'conversion placement explained');
assert(panel.includes('presvid'), 'legacy controls retained');
print('delivery and presenter UI checks passed');
''')
    result = subprocess.run([runtime, '-m', str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'delivery and presenter UI checks passed'

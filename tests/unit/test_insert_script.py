"""Script lifecycle uses synthetic recordings and mocked models/voice engines."""
from copy import deepcopy

import pytest

from app import check, inserts, llm, main, media, script_gen, stages, store, undo
from app.media import footage
from app.schema import Project, Slide


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def fail(*a, **kw):
        pytest.fail('Unexpected model call')
    monkeypatch.setattr(llm, 'complete_json', fail)
    monkeypatch.setattr(script_gen, 'complete_json', fail)


def model(monkeypatch, fn):
    monkeypatch.setattr(llm, 'complete_json', fn)
    monkeypatch.setattr(script_gen, 'complete_json', fn)


def card(ident):
    return Slide(id=ident, insert=dict(kind='card', seconds=4, text=ident),
                 locked_media=False, chapter='Chapter', title='Keep',
                 overlays=[dict(block='keep')])


@pytest.fixture
def cut(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path)
    p = Project(id='pscriptinserts', idea='Synthetic', slides=[
        card('opening'), Slide(id='old1', narration='First words.'),
        card('middle1'), card('middle2'), Slide(id='old2', narration='Second words.'),
        card('late'), Slide(id='old3', narration='Last words.'), card('terminal')])
    p.slides[1].take = dict(path='raw/mic.wav', raw_path='raw/mic.webm')
    p.slides[1].takes = {'mic': deepcopy(p.slides[1].take),
                         'cloud': dict(path='raw/cloud.wav')}
    p.slides[1].history = [dict(path='raw/retired.wav', track='mic')]
    p.slides[4].takes = {'camera': dict(path='raw/camera.wav', video_path='raw/camera.webm')}
    root = store.project_dir(p.id)
    for name in ('mic.wav', 'mic.webm', 'cloud.wav', 'retired.wav', 'camera.wav', 'camera.webm'):
        (root / 'raw' / name).write_bytes(name.encode())
    store.save(p)
    return p


@pytest.mark.parametrize('operation', ['generate', 'import'])
@pytest.mark.parametrize('count', [1, 2, 5])
def test_replacement_preserves_order_and_recordings(cut, monkeypatch, operation, count):
    before = {s.id: s.to_dict() for s in cut.slides if s.insert}
    new = [dict(text=f'New paragraph {i} with plain narration.', visual='A photograph.')
           for i in range(count)]
    def complete(prompt, **kw):
        if 'Read the opening of an article' in prompt:
            return dict(title='New script')
        if 'Split part of an article' in prompt or 'Write the narration for one section' in prompt:
            return new
        if 'For each narration paragraph' in prompt:
            return []
        if 'Check only script consistency' in prompt:
            return []
        pytest.fail(prompt[:100])
    model(monkeypatch, complete)
    if operation == 'generate':
        monkeypatch.setattr(script_gen, 'brief', lambda *a: dict(title='New', sections=[
            dict(kind='main', heading='New beat', words=55)]))
        script_gen.generate(cut)
    else:
        script_gen.import_script(cut, 'Article body words. ' * 50)
    paragraphs = [s for s in cut.slides if not s.insert]
    assert len(paragraphs) == count
    assert {s.id: s.to_dict() for s in cut.slides if s.insert} == before
    ids = [s.id for s in cut.slides]
    assert ids == (['opening', paragraphs[0].id, 'middle1', 'middle2']
                   + ([paragraphs[1].id] if count > 1 else []) + ['late']
                   + [s.id for s in paragraphs[2:]] + ['terminal'])
    # Retention must work in memory and without an undo edit context.
    expected = {'raw/mic.wav', 'raw/cloud.wav', 'raw/retired.wav', 'raw/camera.wav'}
    assert {t['path'] for t in cut.retired_takes} == expected
    store.save(cut)
    saved = store.load(cut.id)
    assert {t['path'] for t in saved.retired_takes} == expected
    store.save(saved)
    assert len(store.load(cut.id).retired_takes) == 4
    for file in (store.project_dir(cut.id) / 'raw').iterdir():
        assert file.read_bytes() == file.name.encode()


@pytest.mark.parametrize('operation', ['generate', 'import'])
@pytest.mark.parametrize('failure', ['model', 'empty', 'planner'])
def test_failed_replacement_keeps_rows_and_recordings(cut, monkeypatch, operation, failure):
    before = [s.to_dict() for s in cut.slides]
    disk = (store.project_dir(cut.id) / 'project.json').read_bytes()
    def complete(prompt, **kw):
        if 'Read the opening' in prompt:
            return dict(title='New script')
        if failure == 'model':
            raise llm.LLMError('Synthetic failure')
        return [] if failure == 'empty' else [dict(text='New narration.', visual='Photo.')]
    model(monkeypatch, complete)
    if failure == 'planner':
        def fail(*a):
            raise llm.LLMError('Planner failure')
        monkeypatch.setattr(script_gen, 'plan_visuals', fail)
    monkeypatch.setattr(script_gen, 'brief', lambda *a: dict(sections=[dict(kind='main', words=55)]))
    with pytest.raises((ValueError, llm.LLMError)):
        if operation == 'generate':
            script_gen.generate(cut)
        else:
            script_gen.import_script(cut, 'Article words. ' * 70)
    assert [s.to_dict() for s in cut.slides] == before
    assert (store.project_dir(cut.id) / 'project.json').read_bytes() == disk


def test_insert_only_boundaries_and_undo(cut):
    only = Project(id='ponly', idea='', slides=[card('a'), card('b')])
    inserts.replace_script(only, [Slide(id='new')])
    assert [s.id for s in only.slides] == ['a', 'b', 'new']
    token = undo.edit_source.set(('replace script', ''))
    try:
        inserts.replace_script(cut, [Slide(id='new', narration='New words.')])
        store.save(cut)
    finally:
        undo.edit_source.reset(token)
    for operation in (main.undo_project, main.redo_project):
        operation(cut.id)
        p = store.load(cut.id)
        assert [s.id for s in p.slides if s.insert] == ['opening', 'middle1', 'middle2', 'late', 'terminal']
        paths = {t['path'] for _, _, t in undo.recordings(p.to_dict())}
        assert {'raw/mic.wav', 'raw/cloud.wav', 'raw/retired.wav', 'raw/camera.wav'} <= paths


@pytest.mark.parametrize('operation,fmt', [
    ('plan_visuals', 'kenburns'), ('plan_boards', 'board'), ('plan_cues', 'ticker'),
    ('_plan_style_slides', 'custom:fixture'), ('verify_script', 'kenburns'),
    ('consistency_check', 'kenburns'), ('revise_style', 'kenburns')])
def test_narration_planners_exclude_inserts(monkeypatch, operation, fmt):
    row = card('UNSPOKEN_SENTINEL')
    row.narration = 'UNSPOKEN_SENTINEL. It is worth noting that this changed everything.'
    row.visual_note = 'UNSPOKEN_SENTINEL'
    row.kind = fmt
    p = Project(id='pplan', idea='', slides=[Slide(id='spoken', narration='Spoken words.'), row],
                research={'facts': [dict(claim='Spoken words.', source='fixture')]})
    p.style.format = fmt
    calls = []
    def complete(prompt, **kw):
        assert 'UNSPOKEN_SENTINEL' not in prompt
        calls.append(prompt)
        return []
    model(monkeypatch, complete)
    before = row.to_dict()
    fn = getattr(script_gen, operation)
    if operation.startswith('plan_') or operation == '_plan_style_slides':
        fn(p, p.slides)
        fn(p, [row])
    else:
        fn(p)
        p.slides = [row]
        fn(p)
    assert row.to_dict() == before
    if operation in ('plan_visuals', 'verify_script', 'consistency_check'):
        assert len(calls) == 1
    assert not check.script(p)['findings']


def test_voice_entry_points_skip_inserts(cut, monkeypatch):
    for row in cut.slides:
        if row.insert:
            row.narration = 'UNSPOKEN_SENTINEL'
    store.save(cut)
    monkeypatch.setattr(main, '_engine_ready', lambda *a: None)
    calls = []
    def speak(text, out, *a, **kw):
        assert text != 'UNSPOKEN_SENTINEL'
        assert all('UNSPOKEN_SENTINEL' not in c for c in kw['context'])
        calls.append(text)
        out.write_bytes(b'synthetic')
        return dict(duration=1, synthetic=True)
    monkeypatch.setattr(main.tts_mod, 'speak_to_file', speak)
    assert main.voice_over(cut.id, dict(dry_run=True, redo=True))['paragraphs'] == 3
    monkeypatch.setattr(main.jobs, 'start', lambda kind, pid, work: work(lambda m: None))
    result = main.voice_over(cut.id, dict(redo=True))['job']
    assert result['read'] == 3 and result['kept'] == 0 and len(calls) == 3
    with pytest.raises(main.HTTPException) as exc:
        main.voice_over_one(cut.id, 'opening')
    assert exc.value.status_code == 400
    with pytest.raises(ValueError):
        main._voice_one(cut, cut.slides[0], store.project_dir(cut.id))
    assert len(calls) == 3


def test_auto_media_and_counts_ignore_insert_narration(monkeypatch):
    row = card('unspoken')
    row.chosen_id = 'keep'
    row.candidates = [dict(id='other', score=100)]
    p = Project(id='pcounts', idea='', slides=[row])
    monkeypatch.setattr(media, 'search', lambda *a, **kw: pytest.fail('Insert media search'))
    monkeypatch.setattr(footage, 'suggestions', lambda *a, **kw: pytest.fail('Insert footage search'))
    media.gather(p)
    media._autopick(p)
    assert footage.fill(p, overwrite=True, rerank=True) == 0
    assert row.chosen_id == 'keep'
    for kind in ('clip', 'picture', 'block', 'card'):
        row.insert['kind'] = kind
        rows = {r['id']: r for r in stages.stages(p, {})}
        assert rows['script']['reason'] == '0 paragraphs'
        assert rows['voice']['reason'] == '0 of 0 read'
        assert all(rows[k]['status'] == 'ready' for k in ('script', 'voice', 'visuals'))
        assert rows['visuals']['reason'] == '1 pictures'
    p.slides.append(Slide(narration='Spoken words.'))
    rows = {r['id']: r for r in stages.stages(p, {})}
    assert rows['script']['reason'] == '1 paragraphs'
    assert rows['voice']['reason'] == '0 of 1 read'
    assert rows['visuals']['reason'] == '1 need a picture'


def test_model_numbering_and_rewrite_context_skip_inserts(monkeypatch):
    row = card('insert')
    row.narration = 'UNSPOKEN_SENTINEL'
    p = Project(id='pnumber', idea='', slides=[
        Slide(id='first', narration='First spoken paragraph.'), row,
        Slide(id='second', narration='Second spoken paragraph.')],
        research={'facts': [dict(claim='A fact.', source='fixture')]})
    def complete(prompt, **kw):
        assert 'UNSPOKEN_SENTINEL' not in prompt
        if 'Rewrite one paragraph' in prompt:
            assert 'PARAGRAPH BEFORE: "First spoken paragraph."' in prompt
            return dict(text='Rewritten paragraph.')
        return [dict(n=2, kind='contradiction', claim='Claim', issue='Issue')]
    model(monkeypatch, complete)
    assert script_gen.consistency_check(p)[0]['slide_id'] == 'second'
    assert script_gen.verify_script(p)[0]['slide_id'] == 'second'
    assert script_gen.rewrite_slide(p, p.slides[-1], 'Tighten') == 'Rewritten paragraph.'
    with pytest.raises(ValueError):
        script_gen.rewrite_slide(p, row, 'Tighten')


def test_word_checks_ignore_insert_fields():
    row = card('insert')
    row.narration = 'It is worth noting that this changed everything.'
    p = Project(id='pwords', idea='', slides=[row], research={'flags': [
        dict(slide_id=row.id, kind='contradiction', claim='Stale claim', issue='Stale issue')]})
    assert not check.script(p)['findings']
    para = dict(id=row.id, insert=row.insert, narration=row.narration, start=0,
                take=dict(words=[dict(start=0, w='unspoken')]), cues=[])
    sb = dict(paragraphs=[para], segments=[], frame={})
    assert check._ctx(sb).words == []
    assert check.script_style([para]) == []

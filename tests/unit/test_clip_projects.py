"""Source-linked clip edits and preview graphs; no models or owner data."""
import pytest

from app import clip_projects as clips, footage, render, store, transcripts
from app.schema import Project


@pytest.fixture
def clip_project(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path/'shoots')
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path/'projects')
    path = tmp_path/'source.mp4'
    path.write_bytes(b'original')
    stamp = path.stat().st_mtime_ns
    footage._save(footage.Shoot('shoot', files=[footage.SourceFile('file', str(path),
        duration=10, width=1920, height=1080, audio=[dict(channels=1)])],
        clips=[footage.Clip('named', 'file', 1, 8, title='Moment', hook='The hook')]))
    doc = dict(coverage=[[1, 8]], words=[dict(w=w, start=a, end=b, src='stt') for w,a,b in
        [('Hello',1,2), ('um',2,3), ('world.',3,4), ('Next',5,6), ('sentence.',6,8)]],
        segments=[dict(start=1,end=4,text='Hello um world.'),
                  dict(start=5,end=8,text='Next sentence.')])
    transcripts._write(transcripts._path('shoot','file'), doc)
    project = clips.create('shoot','named',{})
    yield project, path
    assert path.read_bytes() == b'original'
    assert path.stat().st_mtime_ns == stamp
    assert not list((store.project_dir(project.id)/'takes').iterdir())


def test_model_manual_and_roundtrip(clip_project):
    project, original = clip_project
    assert project.kind == 'clip' and project.aspect == 'portrait'
    assert project.clip['hook'] == 'The hook'
    assert render._chosen(project, project.slides[0])[0] == original
    assert [s.narration for s in project.slides] == ['Hello um world.', 'Next sentence.']
    assert clips.duration(project) == 7
    saved = store.load(project.id)
    assert saved.clip == project.clip
    raw = saved.to_dict()
    loaded = Project.from_dict(raw)
    loaded.clip['cuts'].append([2, 3])
    assert not raw['clip']['cuts']
    assert Project.from_dict(dict(id='old', idea='', clip=None)).clip == {}
    assert all(not s.take and not s.takes and not s.history for s in saved.slides)
    assert saved.to_dict()['voice_tracks'] == {}
    assert Project.from_dict(dict(id='old',idea='',future=True)).kind == 'video'
    assert Project('old', 'idea', 'Positional title').title == 'Positional title'
    transcripts._path('shoot','file').unlink()
    manual = clips.create('shoot','named',{'aspect':'1:1'})
    assert len(manual.slides) == 1 and not manual.slides[0].narration
    assert clips.duration(manual) == 7


def test_word_trim_cut_and_stable_paragraph(clip_project):
    project, _ = clip_project
    ident = project.slides[1].id
    edited = clips.update(project, dict(in_s=2,out_s=8,cuts=[[2,3]],
                                      reframes={ident:'left third'}))
    assert clips.ranges(edited) == [(3,8)]
    assert project.clip['in_s'] == 1 and project.clip['cuts'] == []
    assert edited.slides[-1].id == ident
    assert edited.slides[0].narration == 'world.'
    assert edited.clip['reframes'] == {ident:'left third'}
    assert edited.slides[0].id == project.slides[0].id
    assert edited.est_seconds() == 5
    store.save(edited)
    assert store.load(project.id).clip == edited.clip


@pytest.mark.parametrize('payload', [dict(in_s=True),dict(out_s=float('nan')),
    dict(in_s=1.5),dict(cuts=[[1,8]]),dict(cuts=[[2,2.5]]),dict(cuts=[[]]),
    dict(reframes={'missing':'centre'}),dict(aspect='4:3'),dict(cuts='bad')])
def test_bad_edits_are_atomic(clip_project,payload):
    project, _ = clip_project
    before = project.to_dict()
    with pytest.raises((ValueError,TypeError)):
        clips.update(project,payload)
    assert project.to_dict() == before


def test_section_graph_has_original_audio_hard_video_cut_and_crossfade(clip_project,monkeypatch):
    project, path = clip_project
    monkeypatch.setattr(render.ffutil,'dimensions',lambda p:(1920,1080))
    project = clips.update(project,dict(cuts=[[2,3]]))
    inputs, graph, seconds = clips.section_graph(project,project.slides[0].id)
    assert inputs == ['-i',str(path)]
    assert 'trim=start=1.000000:end=2.000000' in graph
    assert 'trim=start=3.000000:end=5.000000' in graph
    assert 'concat=n=2:v=1:a=0' in graph
    assert 'acrossfade=d=0.066667' in graph
    assert 'loudnorm=I=-14' in graph and 'crop=270:480' in graph
    assert seconds == 3
    with pytest.raises(ValueError,match='full rendering is not available'):
        render.render(project)
    with pytest.raises(ValueError,match='timeline is not available'):
        render.timeline(project)


def test_preview_routes_through_source_graph(clip_project,monkeypatch):
    from pathlib import Path
    from app import block_overlays
    project, path = clip_project
    monkeypatch.setattr(render.ffutil,'dimensions',lambda p:(1920,1080))
    def fake(args):
        assert args[args.index('-i')+1] == str(path)
        assert '[0:a]atrim=start=1.000000:end=5.000000' in Path(args[args.index('-filter_complex_script')+1]).read_text()
        Path(args[-1]).write_bytes(b'preview')
    monkeypatch.setattr(block_overlays,'run_graph',fake)
    result = render.preview_segment(project,project.slides[0].id)
    assert result['seconds'] == 4
    assert (store.project_dir(project.id)/result['path']).exists()
    assert not list((store.project_dir(project.id)/'cache').glob('*.ffgraph'))


def test_api_factory_and_locked_patch(clip_project):
    from app import main
    from fastapi import HTTPException
    project, _ = clip_project
    created = main.clip_project_create('shoot','named',{'aspect':'1:1'})
    assert created['kind'] == 'clip' and created['aspect'] == 'square'
    edited = main.clip_project_edit(project.id,dict(cuts=[[2,3]]))
    assert edited['clip']['cuts'] == [[2,3]]
    with pytest.raises(HTTPException) as exc:
        main.clip_project_edit(project.id,dict(in_s=1.5))
    assert exc.value.status_code == 400

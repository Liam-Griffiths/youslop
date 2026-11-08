"""Footage edit lists stay local and only build argv/graphs; no encodes."""
import json

import pytest

from app import footage, llm, media, render, store
from app.media.footage import fill, resolve, suggestions
from app.media.providers import Footage
from app.schema import MediaCandidate


@pytest.fixture
def shoot(tmp_path, monkeypatch):
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    original = tmp_path / 'original.mp4'
    original.write_bytes(b'original untouched')
    s = footage.Shoot('stest', files=[footage.SourceFile('f1', str(original), duration=30,
                                                       width=1920, height=1080)],
                      clips=[footage.Clip('c1', 'f1', 2, 10, labels=['harbour boats']),
                             footage.Clip('c2', 'f1', 12, 20, labels=['forest trees'])])
    footage._save(s)
    proxy, _ = footage._outputs(s, s.files[0])
    proxy.parent.mkdir(parents=True)
    proxy.write_bytes(b'proxy untouched')
    return s


def test_match_fill_and_no_copy(project, shoot, tmp_path, monkeypatch):
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: pytest.fail('default called LLM'))
    for s, text in zip(project.slides, ['boats in the harbour', 'a forest tree', 'harbour boat']):
        s.narration, s.visual_note, s.chosen_id = text, '', ''
    assert fill(project) == len(project.slides)
    assert [s.chosen_id for s in project.slides[:2]] == ['ftstest_c1', 'ftstest_c2']
    choices = [s.chosen_id for s in project.slides]
    assert fill(project) == 0
    assert [s.chosen_id for s in project.slides] == choices
    project.slides[0].chosen_id = 'owner-choice'
    assert fill(project) == 0
    candidate = project.slides[1].candidates[0]
    assert candidate['local_path'] == ''
    assert media.download_to(candidate, tmp_path / 'must-not-exist') == ''
    assert not (tmp_path / 'must-not-exist').exists()
    assert media.download_chosen(project) == []
    assert footage.source_path(shoot, shoot.files[0]).read_bytes() == b'original untouched'
    store.save(project)
    assert store.load(project.id).slides[1].candidates[0] == candidate
    assert MediaCandidate('old', 'local', 'video').in_s is None


def test_ranking_and_live_edits(shoot):
    shoot.clips += [footage.Clip('c3', 'f1', 2, 10, labels=['harbour boats'], starred=True),
                    footage.Clip('c4', 'f1', 2, 10, labels=['harbour boats'], quality={'usable': False}),
                    footage.Clip('c5', 'f1', 2, 10, labels=['harbour boats'], rejected=True)]
    shoot.clips[0].best_take = 'c1'
    shoot.clips[1].auto_labels = {'subject': 'boat'}
    shoot.clips[1].note = 'harbour'
    footage._save(shoot)
    ids = [c.clip_id for c in Footage().search('harbour boats', 'video')]
    assert ids.index('c3') < ids.index('c1') < ids.index('c4')
    assert 'c5' not in ids
    footage.edit_clips(shoot.id, ['c3'], {'rejected': True})
    assert 'c3' not in [c.clip_id for c in media._cached_search(Footage(), 'harbour boats', 'video')]
    assert Footage().search('boat', 'image') == []


def test_explicit_rerank_caps_model_input(shoot, monkeypatch):
    shoot.clips = [footage.Clip(f'c{i}', 'f1', 2, 10, labels=['boat']) for i in range(25)]
    footage._save(shoot)
    def mocked(prompt, **kwargs):
        payload = json.loads(prompt[prompt.index('{'):])
        assert len(payload['clips']) == 20
        return [c['id'] for c in reversed(payload['clips'])]
    monkeypatch.setattr(llm, 'complete_json', mocked)
    assert suggestions('boat', rerank=True)[0].clip_id == 'c19'


def test_resolution_and_missing_drive(project, shoot):
    c = suggestions('boat')[0].to_dict()
    original = footage.source_path(shoot, shoot.files[0])
    proxy = footage.media_path(shoot.id, 'proxies', 'f1.mp4')
    assert resolve(c) == original
    assert resolve(c, preview=True) == proxy
    original.unlink()  # Synthetic fixture only.
    messages = []
    assert resolve(c, progress=messages.append) == proxy
    assert 'original missing' in messages[0]
    proxy.unlink()
    assert resolve(c) is None
    project.slides[0].candidates, project.slides[0].chosen_id = [c], c['id']
    assert render._chosen(project, project.slides[0])[0] is None
    c['out_s'] = float('nan')
    assert resolve(c) is None


def test_safe_thumb_route(shoot):
    root = footage.shoot_dir(shoot.id)
    (root / 'thumbs').mkdir()
    (root / 'thumbs/c1.jpg').write_bytes(b'thumb')
    shoot.clips[0].thumbs = ['thumbs/c1.jpg']
    footage._save(shoot)
    assert footage.media_path(shoot.id, 'thumbs', 'thumbs/c1.jpg').read_bytes() == b'thumb'
    for name in ['shoot.json', '../original.mp4', 'thumbs/other.jpg']:
        with pytest.raises(FileNotFoundError):
            footage.media_path(shoot.id, 'thumbs', name)


@pytest.mark.parametrize('size', [(render.WIDTH, render.HEIGHT), (480, 270)])
def test_trimmed_segment_graph(project, shoot, monkeypatch, size):
    project.style.format = 'kenburns'
    project.style.captions_engine = 'pillow'
    slide = project.slides[0]
    candidate = suggestions('boat')[0].to_dict()
    slide.candidates, slide.chosen_id = [candidate], candidate['id']
    monkeypatch.setattr(render.ffutil, 'dimensions', lambda p: (1920, 1080))
    monkeypatch.setattr(render.ffutil, 'duration', lambda p: pytest.fail('must not probe whole file'))
    inputs, graph, last = render._segment_graph(project, [(slide, 3)], 3, 'set', size=size)
    src = resolve(candidate, preview=size != (render.WIDTH, render.HEIGHT))
    assert inputs[:6] == ['-ss', '2.000', '-t', '8.000', '-i', str(src)]
    assert '[base]' in graph and last
    # Every repeat seeks to the saved span, including the long-hold fallback.
    for seconds in (15, 40, 300):
        argv, _ = render._clip_source(src, seconds, 'null', (2, 10))
        assert all(argv[i-4:i] == ['-ss', '2.000', '-t', '8.000']
                   for i, arg in enumerate(argv) if arg == '-i')


def test_footage_graph_matches_video_golden(project, shoot, monkeypatch):
    import os
    from tests._fixtures import ROOT
    project.style.format = 'kenburns'
    project.style.captions_engine = 'pillow'
    project.slides[0].chapter = 'Opening'
    candidate = suggestions('boat')[0].to_dict()
    project.slides[0].candidates = [candidate]
    project.slides[0].chosen_id = candidate['id']
    monkeypatch.setattr(render.ffutil, 'dimensions', lambda p: (1920, 1080))
    group = render._picture_groups(project, render._slide_durations(project, False))[0]
    inputs, graph, last = render._segment_graph(project, group, 3, render.camera_plan(project, [group])[0],
                                               chapter=('Next chapter', 'Test'))
    original = str(resolve(candidate))
    norm = lambda s: s.replace(original, '<DATA>/projects/ptest0001/media/pic.jpg').replace(
        os.environ['CORKBORED_DATA'], '<DATA>').replace(str(ROOT), '<REPO>')
    # The pre-change video reference differs only by input seeking and the source.
    actual = '\n'.join(norm(a) for a in inputs[4:]) + '\n---\n' + norm(graph).replace(';', ';\n') + '\n---\n' + last + '\n'
    assert inputs[:4] == ['-ss', '2.000', '-t', '8.000']
    assert actual == (ROOT / 'tests/golden/video_full.txt').read_text()


def test_source_search_and_fill_routes(project, shoot, monkeypatch):
    from app import main
    monkeypatch.setattr(main, '_load', lambda pid: project)
    monkeypatch.setattr(main.store, 'save', lambda p: None)
    monkeypatch.setattr(main.media, 'search', lambda *a, **kw: pytest.fail('archive search'))
    result = main.slide_search(project.id, project.slides[1].id, {'source':'footage', 'query':'trees'})
    assert result['results'][0]['clip_id'] == 'c2'
    project.slides[1].narration, project.slides[1].visual_note = 'Boats in the harbour.', ''
    # Slide 2 ("This paragraph has no recording yet.") shares no word with any clip.
    assert main.fill_footage(project.id, {})['filled'] == 1
    assert project.slides[1].chosen_id == 'ftstest_c1'
    assert project.slides[2].chosen_id != 'ftstest_c1' and not project.slides[2].chosen_id.startswith('ftstest_')
    assert project.slides[0].chosen_id == 'c1'  # Existing owner's picture retained.

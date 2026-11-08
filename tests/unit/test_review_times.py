"""Review selection and surfaces need no renderer, browser or model."""
import pytest
from PIL import Image

from app import cli, ffutil, main, render, review, store
from app.schema import FrameSpec


def story(duration=12):
    return dict(project=dict(duration=duration), paragraphs=[
        dict(id='a', start=.6, end=5, cues=[dict(start=2.01)]),
        dict(id='b', start=5, end=duration)], segments=[], findings=[])


def test_dedupe_hook_findings_and_cards():
    sb = story()
    sb['findings'] = [dict(level='P1', t=2, code='test', slide_id='a'),
                      dict(level='P2', t=7, code='ignored', slide_id='b')]
    sb['segments'] = [dict(cards=[dict(start=8, slide_id='b')])]
    rows = review.snapshot_times(sb, FrameSpec())
    times = [r['t'] for r in rows]
    assert times == sorted(times)
    assert {0, 1.5, 3, 2, 8.45, 10, 11} <= set(times)
    assert 7 not in times and 2.01 not in times
    assert next(r for r in rows if r['t'] == 2)['why'] == 'finding: test'
    assert all(b - a >= .25 for a, b in zip(times, times[1:]))


def test_cap_drops_middles_then_cues():
    sb = story(200)
    sb['paragraphs'] = [dict(id=str(i), start=5*i+5, end=5*i+9,
                             cues=[dict(start=5*i+6)]) for i in range(40)]
    rows = review.snapshot_times(sb, FrameSpec())
    assert len(rows) == 48
    assert not any(r['why'] == 'paragraph middle' for r in rows)
    assert sum(r['why'] == 'paragraph start' for r in rows) == 39  # Reserve a slot for the video's last frame.
    assert {0, 1.5, 3} <= {r['t'] for r in rows}
    sb['findings'] = [dict(level='P0', t=180, code='late', slide_id='x')]
    assert 180 in {r['t'] for r in review.snapshot_times(sb, FrameSpec())}


@pytest.mark.parametrize('duration', [0, .1, 1, 2])
def test_short_cut(duration):
    rows = review.snapshot_times(story(duration), FrameSpec())
    assert all(0 <= r['t'] < duration for r in rows)


def segment(ready=True, kind='picture'):
    return dict(start=4, duration=5, skip=.325 if kind == 'picture' else 0,
                ready=ready, ref='0' if kind == 'picture' else kind,
                path='cache/test.webm', type=kind, paragraphs=[
                    dict(id='s1', start=4, duration=5)])


@pytest.mark.parametrize('kind', ['picture', 'intro', 'outro'])
def test_grab_seek_and_missing_proxy(project, tmp_path, monkeypatch, kind):
    seg = segment(False, kind)
    monkeypatch.setattr(render, 'timeline', lambda p: dict(segments=[seg]))
    built, commands = [], []
    monkeypatch.setattr(render, 'proxy_ref', lambda *a, **kw: built.append((a, kw)))
    def run(args):
        commands.append(args)
        Image.new('RGB', (640, 360)).save(args[-1])
    monkeypatch.setattr(ffutil, 'run', run)
    assert review.grab(project, 5, tmp_path / 'frame.png').exists()
    assert built[0][0][1] == seg['ref'] and built[0][1] == dict(download=False)
    assert commands[0][:2] == ['-ss', '1.325' if kind == 'picture' else '1.000']
    with pytest.raises(ValueError, match='outside'):
        review.grab(project, 9, tmp_path / 'outside.png')


def test_manifest_sheet_cli_api(project, tmp_path, monkeypatch, capsys):
    root = store.project_dir(project.id)
    monkeypatch.setattr(review, '_story', lambda p: story())
    monkeypatch.setattr(review, '_storyboard_hash', lambda p: 'synthetic-story')
    monkeypatch.setattr(render, 'timeline', lambda p: dict(segments=[]))
    def grab(p, t, out, size, segments):
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', size, 'white').save(out)
        return out, t == 0
    monkeypatch.setattr(review, '_grab', grab)
    monkeypatch.setattr(store, 'load', lambda pid: project)
    monkeypatch.setattr(main, '_load', lambda pid: project)
    assert main.get_snapshots(project.id) == []
    assert cli.main(['snapshot', project.id, '--sheet']) == 0
    assert str(root / 'review/snaps.json') in capsys.readouterr().out
    rows = main.get_snapshots(project.id)
    assert rows[0]['why'].endswith('(approximate still)')
    assert all((root / r['path']).exists() for r in rows)
    with Image.open(root / 'review/sheet.png') as image:
        assert image.width == 1440
        # The label strip sits under the frame, so the frame's lower third stays clean.
        assert image.getpixel((355, 200)) == (255, 255, 255)
        assert image.getpixel((355, 230)) == (24, 24, 24)
    def start(kind, pid, fn, *, cancellable=False):
        assert cancellable is True
        assert kind == 'snapshot' and pid == project.id
        assert fn(lambda msg: None)['sheet'] == 'review/sheet.png'
        return 'job1'
    monkeypatch.setattr(main.jobs, 'start', start)
    assert main.start_snapshots(project.id) == dict(job='job1')
    assert any(r.path == '/api/projects/{pid}/file/{rel:path}' for r in main.app.routes)
    monkeypatch.setattr(cli, '_guard_write', lambda: (_ for _ in ()).throw(ValueError('app is open')))
    assert cli.main(['snapshot', project.id]) == 1


def test_board_fallback_fraction(project, tmp_path, monkeypatch):
    project.style.format = 'board'
    seg = segment(False)
    def broken(*a, **kw):
        raise ffutil.FFError('unavailable')
    monkeypatch.setattr(render, 'proxy_ref', broken)
    seen = []
    def still(p, slide, out, **kw):
        seen.append(kw['at'])
        Image.new('RGB', (100, 100)).save(out)
    monkeypatch.setattr(review.board, 'still', still)
    path, approximate = review._grab(project, 6, tmp_path / 'fallback.png', (640, 360), [seg])
    assert approximate and seen == [.4]
    with Image.open(path) as image:
        assert image.size == (640, 360)


@pytest.mark.parametrize('fmt', ['kenburns', 'board', 'loudmouth'])
def test_chapter_times_follow_render_hold(project, monkeypatch, fmt):
    project.style.format = fmt
    sb = story()
    sb['segments'] = [dict(type='picture', start=0, duration=5, skip=.2),
                      dict(type='picture', start=5, duration=7, skip=.2)]
    groups = [[(project.slides[0], 5)], [(project.slides[1], 7)]]
    monkeypatch.setattr(review.storyboard, 'build', lambda p: sb)
    monkeypatch.setattr(review.check, 'run', lambda p: dict(findings=[]))
    monkeypatch.setattr(render, '_groups_for_preview', lambda p: groups)
    monkeypatch.setattr(render, 'chapter_card', lambda p, s: ('New chapter', ''))
    monkeypatch.setattr(review.audio, 'gap_map', lambda p: {project.slides[0].id: 3})
    monkeypatch.setattr(review.scenes, 'handles', lambda fmt: False)
    result = review._story(project)
    frame = project.frame
    hold = (min(3, frame.arrive_s + frame.title_hold_base_s + 2 * frame.title_hold_per_word_s)
            if fmt == 'kenburns' else 2.88)
    expected = 5.2 - hold + frame.arrive_s
    rows = review.snapshot_times(result, frame)
    assert result['segments'][0]['cards'][0]['start'] == pytest.approx(5.2 - hold)
    assert any(abs(r['t'] - expected) < .25 for r in rows)

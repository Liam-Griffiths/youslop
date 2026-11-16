"""UI harness contracts, deliberately independent of Chromium and sockets."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

from scripts.ui_snapshots import FIELD_LABEL_AUDIT, FORMATS, PROJECT_STAGES, console_error, output_path, routes, seed


def test_routes_match_current_tabs_and_families():
    paths = routes()
    assert len(paths) == len(set(paths)) == 116
    assert paths[:5] == ['#/', '#/setup', '#/library', '#/settings', '#/guide']
    assert '#/p/psnapoutline/script/outline' in paths
    assert '#/p/psnapbeatonly/script/outline' in paths
    assert '#/footage/ssnapshot' in paths and '#/footage/saudio' in paths
    assert '#/footage/saudio/clips/a1' in paths  # T14.3 adds the clip-finder route.
    assert '#/c/csnapshot' in paths and '#/c/csnapshot/setup' in paths
    for fmt in FORMATS:
        expected = set(PROJECT_STAGES) | {'media', 'record', 'thumb', 'render',
            'plan', 'visuals', 'script/outline', 'edit/pictures', 'visuals/media', 'publish/render', 'publish/thumb'}
        if fmt == 'stage':
            expected |= {'cast', 'stage', 'visuals/cast', 'visuals/stage'}
        assert {p.removeprefix(f'#/p/psnap{fmt}/') for p in paths
                if p.startswith(f'#/p/psnap{fmt}/')} == expected


def test_output_paths_are_unique_and_contained(tmp_path):
    paths = [output_path(tmp_path, route) for route in routes()]
    assert len(set(paths)) == 116
    assert paths[0] == tmp_path / 'home.png'
    assert output_path(tmp_path, '#/p/psnapstage/stage').name == 'p--psnapstage--stage.png'
    assert all(p.parent == tmp_path and p.suffix == '.png' for p in paths)


@pytest.mark.parametrize('route', ['../../escape', '#/../escape', '#//etc', '#/a-b', '#/a%2Fb', '#/a\\b'])
def test_reject_unsafe_output_routes(tmp_path, route):
    with pytest.raises(ValueError):
        output_path(tmp_path, route)


@pytest.mark.parametrize('event, expected', [
    ({'method': 'Runtime.consoleAPICalled', 'params': {'type': 'error', 'args': [
        {'value': 'probe'}, {'description': 'Error: broken'}, {'value': 42}]}},
     'console.error: probe Error: broken 42'),
    ({'method': 'Runtime.consoleAPICalled', 'params': {'type': 'error'}}, 'console.error: '),
    ({'method': 'Runtime.exceptionThrown', 'params': {'exceptionDetails': {
        'text': 'Uncaught', 'exception': {'description': 'ReferenceError: missing'},
        'url': 'core.js', 'lineNumber': 9}}}, 'exception: ReferenceError: missing (core.js:10)'),
    ({'method': 'Runtime.exceptionThrown', 'params': {'exceptionDetails': {'text': 'Uncaught'}}},
     'exception: Uncaught (:1)'),
    ({'method': 'Runtime.consoleAPICalled', 'params': {'type': 'warning'}}, None),
    ({'method': 'Network.loadingFinished'}, None),
])
def test_console_error_parsing(event, expected):
    assert console_error(event) == expected


def test_seed_uses_only_fixture_data(monkeypatch, tmp_path):
    from app import channels, config, library, settings, store, footage
    monkeypatch.setenv('CORKBORED_DATA', str(tmp_path))
    monkeypatch.setattr(footage, 'FOOTAGE_DIR', tmp_path / 'footage')
    monkeypatch.setattr(store, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(channels, 'CHANNELS_DIR', tmp_path / 'channels')
    monkeypatch.setattr(config, 'WRITABLE_DIRS', (tmp_path / 'library',))
    monkeypatch.setattr(library, '_INDEX_FILE', tmp_path / 'library/library.json')
    monkeypatch.setattr(library, '_FILES', tmp_path / 'library')
    monkeypatch.setattr(library, '_THUMBS', tmp_path / 'library')
    monkeypatch.setattr(library, 'LIBRARY_DIR', tmp_path / 'library')
    seed()
    summaries = {p['id']: p for p in store.list_projects(include_stage=True)}
    assert summaries['psnapclip']['kind'] == 'clip'
    assert summaries['psnapnew']['kind'] == 'video'
    assert len(footage.load('ssnapshot').clips) == 2
    assert footage.status('ssnapshot')['ready'] == 1
    audio = footage.load('saudio')
    assert audio.files[0].kind == 'audio' and footage.status('saudio')['ready'] == 1
    from app import transcripts
    assert transcripts.load('saudio', 'a1')['words'][0]['src'] == 'stt'
    assert settings.load_file()['setup_complete'] == 'true'
    assert not settings.setup_needed()
    assert channels.load('csnapshot').name == 'Snapshot channel'
    assert channels.load('csnapshot').blocks == ['title_card']
    assert channels.load('csnapshot').block_presets[0]['name'] == 'Our chapter card'
    for fmt in FORMATS:
        p = store.load(f'psnap{fmt}')
        assert p.style.format == fmt
        assert p.channel_id == 'csnapshot'
        assert all(not slide.take for slide in p.slides)
        assert store.project_dir(p.id).joinpath('media/pic.jpg').is_file()
    long = store.load('psnaplong')
    assert len(long.slides) == 20 and not any(s.take for s in long.slides)
    from app.render import _slide_durations
    assert sum(d for _, d in _slide_durations(long, True)) == 1200
    assert '#/p/psnaplong/edit' in routes()
    writing = store.load('psnapbeatonly')
    assert not any(s.chapter for s in writing.slides)
    assert {s.beat for s in writing.slides} == {b['heading'] for b in writing.outline['sections']}
    mixed = store.load('psnapmixed')
    inspector = store.load('psnapinspector')
    assert inspector.picture_runs() == [['s1', 's2'], ['s3']]
    assert len(inspector.slides[0].candidates) == 3
    assert len({s.visual_note for s in inspector.slides}) == 1
    assert '#/p/psnapinspector/edit' in routes()
    from app.kinds import kind_for
    assert [kind_for(mixed,s) for s in mixed.slides] == ['kenburns','board','casefile','block']
    inserts = store.load('psnapinserts')
    assert [s.insert['kind'] for s in inserts.slides if s.insert] == ['clip','block','picture','card']
    assert not any(s.take for s in inserts.slides)
    from app.stages import stages, readiness_check
    for pid, todo in [('psnapnew', '4 to do'), ('psnaphalf', '3 to do'), ('psnapdone', '0 to do')]:
        project = store.load(pid)
        assert stages(project, readiness_check(project))[0]['reason'] == todo
        assert f'#/p/{pid}/dashboard' in routes()
        if pid == 'psnaphalf':
            assert len(project.bin) == 12 and project.labels == ['Street', 'Research', 'Morning']
            assert project.outline['hook']['first_line'] == project.slides[0].narration
            assert len(project.to_dict()['log']) == 10
    assets = library.list_all()
    assert len(assets) == 61 and assets[0]['title'] == 'Fixture picture'
    assert {a['kind'] for a in assets} == {'image', 'video'}
    assert sum(a['folder_id'] == 'explorerfolder' for a in assets) == 60


def test_insert_snapshot_routes():
    assert '#/p/psnapinserts/edit' in routes()
    assert '#/p/psnapinserts/script' in routes()


def test_field_label_audit(tmp_path):
    """Execute the browser audit's naming decisions in GJS, without Chromium."""
    runtime = shutil.which('gjs')
    if not runtime:
        pytest.skip('GJS unavailable')
    fields = [
        {'id': 'missing'},
        {'id': 'placeholder', 'placeholder': 'Name'},
        {'id': 'title', 'title': 'Name'},
        {'id': 'blank', 'aria-label': '  ', 'labels': [' ']},
        {'id': 'disabled', 'disabled': True},
        {'id': 'broken-ref', 'aria-labelledby': 'absent empty'},
        {'id': 'field-only-label', 'labels': [''], 'value': 'Not label text'},
        {'id': 'explicit', 'labels': ['Name']},
        {'id': 'wrapping', 'tag': 'TEXTAREA', 'labels': ['Narration']},
        {'id': 'aria', 'tag': 'SELECT', 'aria-label': 'Voice'},
        {'id': 'references', 'aria-labelledby': 'absent heading'},
        {'id': 'offscreen', 'labels': ['Below the fold']},
        {'id': 'hidden', 'type': 'hidden'},
        {'id': 'closed-details', 'visible': False},
        {'id': 'closed-dialog', 'visible': False},
        {'id': 'hidden-ancestor', 'visible': False},
        {'id': 'invisible', 'visible': False},
        {'id': 'submit', 'type': 'submit'},
        {'id': 'button', 'type': 'button'},
        {'id': 'reset', 'type': 'reset'},
    ]
    harness = r'''
const fields = FIXTURES.map(f => ({...f, tagName:f.tag || 'INPUT', type:f.type || 'text',
  getAttribute:key => f[key] || null,
  checkVisibility:options => {
    if (!options.visibilityProperty) throw Error('Must check visibility:hidden');
    return f.visible !== false;
  },
  labels:(f.labels || []).map(label => ({cloneNode:() => ({
    textContent:label, querySelectorAll:() => [{remove(){}}]
  })}))
}));
const document = {querySelectorAll:() => fields,
  getElementById:id => ({heading:{textContent:'Voice'}, empty:{textContent:' '}}[id])};
print(JSON.stringify(AUDIT));
'''.replace('FIXTURES', json.dumps(fields)).replace('AUDIT', FIELD_LABEL_AUDIT)
    script = tmp_path / 'field-labels.js'
    script.write_text(harness)
    result = subprocess.run([runtime, str(script)], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [f'input#{f["id"]}' for f in fields[:7]]

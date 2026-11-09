"""Fixed download catalog; fake streams only, no network or optional engines."""
from io import BytesIO

import pytest

from app import jobs, settings, stt
from app.stt import downloads


@pytest.mark.parametrize('outcome', ['done', 'cancel', 'short', 'failure'])
def test_atomic_download_progress_and_cleanup(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv('CORKBORED_STT_FOLDER', str(tmp_path))
    class Response(BytesIO):
        headers = {'Content-Length': '4' if outcome != 'short' else '8'}
        def read(self, size):
            if outcome == 'failure':
                raise OSError('fake read error')
            return super().read(size)
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: Response(b'fake'))
    events = []
    def progress(message):
        events.append(message)
        if outcome == 'cancel' and '4 of 4' in message:
            raise jobs.JobCancelled()
    if outcome == 'done':
        result = downloads.download('whisper.cpp', 'tiny', progress)
        assert result['model'] == str(tmp_path / 'ggml-tiny.bin')
        assert (tmp_path / 'ggml-tiny.bin').read_bytes() == b'fake'
        assert any('4 of 4 bytes' in m for m in events)
        with pytest.raises(ValueError, match='already exists'):
            downloads.download('whisper.cpp', 'tiny', progress)
        assert (tmp_path / 'ggml-tiny.bin').read_bytes() == b'fake'
    else:
        with pytest.raises((jobs.JobCancelled, ValueError, OSError)):
            downloads.download('whisper.cpp', 'tiny', progress)
        assert not list(tmp_path.iterdir())
    assert not list(tmp_path.glob('*.part'))


def test_cache_settings_restart_detection_and_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('CORKBORED_STT_WHISPER_CACHE', str(tmp_path / 'whisper'))
    monkeypatch.setenv('CORKBORED_STT_HUB_CACHE', str(tmp_path / 'hub'))
    monkeypatch.setenv('CORKBORED_STT_FOLDER', str(tmp_path / 'cpp'))
    for path in ('whisper/tiny.pt', 'hub/models--test-whisper/snapshots/one/config.json', 'cpp/ggml-tiny.bin'):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'fake')
    monkeypatch.setattr(stt.importlib.util, 'find_spec', lambda m: None)
    monkeypatch.setattr(stt.shutil, 'which', lambda m: None)
    try:
        info = stt.configured(refresh=True)
        assert info['openai-whisper']['models'] == [str(tmp_path / 'whisper/tiny.pt')]
        assert info['faster-whisper']['models'] == [str(tmp_path / 'hub/models--test-whisper/snapshots/one')]
        assert info['whisper.cpp']['models'] == [str(tmp_path / 'cpp/ggml-tiny.bin')]
        assert info['whisper.cpp']['downloads'] == list(downloads.MODELS)
        stt.report('whisper.cpp', version='fake-v1', device='fake-vulkan')
        assert stt.configured()['whisper.cpp']['runtime'] == dict(version='fake-v1', device='fake-vulkan')
        assert 'stt_hub_cache' in settings.FIELDS_BY_KEY
    finally:
        stt._detect.cache_clear()
        stt._RUNTIME.clear()


def test_registration_drives_discovery_without_imports(tmp_path, monkeypatch):
    model = tmp_path / 'local.weights'
    model.write_bytes(b'fake')
    monkeypatch.setattr(stt.importlib.util, 'find_spec', lambda m: None)
    monkeypatch.setattr(stt.importlib, 'import_module', lambda *a: pytest.fail('must stay lazy'))
    try:
        stt.register('synthetic', 'synthetic_adapter', 'https://example.invalid/install',
                     cache=str(tmp_path), pattern='*.weights')
        info = stt.detect()['synthetic']
        assert not info['installed'] and info['models'] == [str(model)]
        assert info['runtime'] is None and info['downloads'] == []
    finally:
        stt.ENGINES.pop('synthetic')
        stt.METADATA.pop('synthetic')
        stt._detect.cache_clear()


def test_publish_race_keeps_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv('CORKBORED_STT_FOLDER', str(tmp_path))
    class Response(BytesIO):
        headers = {}
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **kw: Response(b'new'))
    def progress(message):
        if 'saving model' in message:
            (tmp_path / 'ggml-tiny.bin').write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        downloads.download('whisper.cpp', 'tiny', progress)
    assert [p.name for p in tmp_path.iterdir()] == ['ggml-tiny.bin']
    assert (tmp_path / 'ggml-tiny.bin').read_bytes() == b'existing'

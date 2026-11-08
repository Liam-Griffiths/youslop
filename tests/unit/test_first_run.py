"""First-run detection and status checks use only isolated, synthetic data."""
import pytest
import asyncio
import httpx

from app import settings, setup
from app.main import app


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv('CORKBORED_DATA', str(tmp_path))
    return tmp_path


def test_fresh_root_needs_setup(root):
    assert settings.setup_needed()


@pytest.mark.parametrize(('folder', 'filename'), [('projects', 'project.json'), ('channels', 'channel.json')])
def test_existing_data_skips_setup(root, folder, filename):
    entry = root / folder / 'existing' / filename
    entry.parent.mkdir(parents=True)
    entry.write_text('{}')
    assert not settings.setup_needed()


def test_flag_persists_without_changing_other_settings(root):
    settings.save_file({'anthropic_api_key': 'keep-this', 'setup_complete': 'true'})
    assert not settings.setup_needed()
    settings.save_file({'setup_complete': 'true'})
    assert settings.load_file()['anthropic_api_key'] == 'keep-this'


def test_checks_endpoint(root, monkeypatch):
    monkeypatch.setattr(setup, 'ffmpeg_check', lambda: (True, 'ffmpeg fixture'))
    monkeypatch.setattr(setup.stage, 'available', lambda: (False, 'Install Chromium'))
    monkeypatch.setattr(setup.stage, 'browser', lambda: None)
    monkeypatch.setattr(setup.llm, 'backend_status', lambda: {'resolved': 'cli', 'cli_found': False})
    monkeypatch.setattr(setup.tts, 'status', lambda: {'ready': False, 'weights': False})
    monkeypatch.setattr(setup.sysinfo, 'available_mb', lambda: 1234)
    monkeypatch.setattr(setup.sys, 'platform', 'linux')
    monkeypatch.setattr(setup.youtube, 'available', lambda: True)
    channel = root / 'channels' / 'example' / 'channel.json'
    channel.parent.mkdir(parents=True)
    channel.write_text('{}')
    monkeypatch.setattr(setup.youtube, 'status', lambda cid: {'connected': cid == 'example'})
    def forbidden(*args, **kwargs):
        raise AssertionError('Checks must not invoke a model or launch Chromium')
    monkeypatch.setattr(setup.llm, 'complete_json', forbidden)
    monkeypatch.setattr(setup.stage, '_run_cdp', forbidden)
    async def direct(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr('fastapi.routing.run_in_threadpool', direct)
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://127.0.0.1') as client:
            return await client.get('/api/setup')
    response = asyncio.run(request())
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {'needed', 'ffmpeg', 'chromium', 'llm', 'tts', 'paths', 'system', 'youtube'}
    assert data['ffmpeg'] == {'ready': True, 'detail': 'ffmpeg fixture'}
    assert data['chromium'] == {'ready': False, 'detail': 'Install Chromium', 'path': None}
    assert data['llm']['resolved'] == 'cli'
    assert not data['tts']['ready']
    assert data['paths']['data'] == str(root)
    assert data['system'] == {'available_ram_mb': 1234, 'gpu': None}
    assert data['youtube'] == {'available': True, 'connected': True}
    assert not data['needed']


def test_snapshot_setup_route_and_seed():
    from scripts.ui_snapshots import routes
    assert '#/setup' in routes()

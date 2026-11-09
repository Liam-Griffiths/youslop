"""Offline speech engines. Detection never imports an optional dependency."""
import importlib
import importlib.metadata
import importlib.util
import platform
import shutil
from functools import lru_cache
from pathlib import Path

ENGINES = {
    'faster-whisper': ('faster_whisper', 'https://github.com/SYSTRAN/faster-whisper'),
    'whisper.cpp': ('cpp', 'https://github.com/ggml-org/whisper.cpp'),
    'openai-whisper': ('whisper', 'https://github.com/openai/whisper'),
    'mlx-whisper': ('mlx_whisper', 'https://github.com/ml-explore/mlx-examples/tree/main/whisper'),
}
_ERRORS = {}


def binary(configured=''):
    return shutil.which(configured) if configured else next(
        (p for name in ('whisper-cli', 'whisper-cpp', 'main') if (p := shutil.which(name))), None)


@lru_cache(maxsize=16)
def _detect(folder='', executable=''):
    result = {}
    for name, (module, url) in ENGINES.items():
        try:
            installed = bool(binary(executable)) if module == 'cpp' else importlib.util.find_spec(module) is not None
            if module == 'mlx_whisper':
                installed = installed and platform.system() == 'Darwin' and platform.machine() == 'arm64'
            try:
                version = importlib.metadata.version(name) if installed and module != 'cpp' else ''
            except importlib.metadata.PackageNotFoundError:
                version = ''
            models = []
            if module == 'cpp' and folder:
                models = [str(p) for p in Path(folder).expanduser().glob('ggml-*.bin')]
            elif module == 'whisper':
                models = [str(p) for p in (Path.home() / '.cache/whisper').glob('*.pt')]
            elif module in ('faster_whisper', 'mlx_whisper'):
                import os
                hub = Path(os.environ.get('HF_HUB_CACHE', Path.home() / '.cache/huggingface/hub'))
                models = [str(p.parent) for p in hub.glob('models--*whisper*/snapshots/*/config.json')]
            result[name] = dict(installed=installed, version=version, models=sorted(models),
                                device='Apple Silicon' if module == 'mlx_whisper' else 'CPU (build/runtime dependent)',
                                word_timestamps=True, notes='', install_url=url)
        except Exception as exc:
            result[name] = dict(installed=False, version='', models=[], device='',
                                word_timestamps=True, notes=str(exc), install_url=url)
    return result


def detect(*, folder='', executable='', refresh=False):
    if refresh:
        _detect.cache_clear()
        _ERRORS.clear()
    return {name: {**info, 'notes': _ERRORS.get(name, info['notes'])}
            for name, info in _detect(folder, executable).items()}


def transcribe(engine, path, **kwargs):
    """Lazy imports and inference failures remain visible to detection callers."""
    try:
        module = importlib.import_module('.' + ENGINES[engine][0], __name__)
        yield from module.transcribe(path, **kwargs)
    except Exception as exc:
        from ..jobs import JobCancelled
        if not isinstance(exc, JobCancelled):
            _ERRORS[engine] = f'{type(exc).__name__}: {exc}'
        raise

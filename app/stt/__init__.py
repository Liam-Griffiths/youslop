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
                                device=('Apple Silicon' if module == 'mlx_whisper' else
                                        'CPU · int8 or CUDA · float16 (selected per run)' if module == 'faster_whisper' else
                                        'CPU' if module == 'whisper' else 'Unknown until runtime; depends on executable build'),
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


def configured(refresh=False):
    """Read launch-time settings; match Settings' restart semantics."""
    from .. import brand
    return detect(folder=brand.env('STT_FOLDER', ''),
                  executable=brand.env('STT_EXECUTABLE', ''), refresh=refresh)


def setup_status(refresh=False):
    from .. import brand
    engines = configured(refresh)
    default = brand.env('STT_ENGINE', '')
    installed = [name for name, info in engines.items() if info['installed']]
    detail = ('none installed (optional)' if not installed else
              default if default in installed else 'Choose a default in Settings (optional)')
    return dict(ready=bool(installed), detail=detail, engine=default)


def resolve(options):
    from .. import brand
    if options.keys() - {'engine', 'model', 'language', 'start', 'end', 'retranscribe'}:
        raise ValueError('Unknown transcription option')
    result = dict(options)
    for key in ('engine', 'model'):
        value = result.get(key, brand.env('STT_' + key.upper(), ''))
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Choose a default engine and local model in Settings, or specify them for this run')
        result[key] = value
    engine = result['engine']
    if engine not in ENGINES or not configured()[engine]['installed']:
        raise ValueError('Speech-to-text engine is not installed; see Settings')
    from .common import local_model
    result['model'] = local_model(result['model'])
    if engine == 'whisper.cpp':
        result['executable'] = brand.env('STT_EXECUTABLE', '')
    if engine == 'faster-whisper':
        result['device'] = brand.env('STT_DEVICE', 'cpu')
        if result['device'] not in ('cpu', 'cuda'):
            raise ValueError('Device must be cpu or cuda')
    if result.get('language') is not None and (not isinstance(result['language'], str)
            or not result['language'].isalpha() or len(result['language']) > 8):
        raise ValueError('Language must be a language code or null')
    if type(result.get('retranscribe', False)) is not bool:
        raise ValueError('retranscribe must be boolean')
    return result

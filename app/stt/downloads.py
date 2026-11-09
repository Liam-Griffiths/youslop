"""Explicit, cancellable downloads from a fixed whisper.cpp model catalog."""
import os
import tempfile
import threading
from pathlib import Path
from urllib.request import urlopen

from .. import brand, jobs

MODELS = {name: f'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin'
          for name in ('tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en', 'medium', 'large-v3-turbo')}
_LOCK = threading.Lock()


def folder():
    return Path(brand.env('STT_FOLDER', '') or Path.home() / '.cache/whisper.cpp').expanduser()


def validate(engine, model):
    if engine != 'whisper.cpp' or model not in MODELS:
        raise ValueError('Choose a supported whisper.cpp download')
    target = folder() / f'ggml-{model}.bin'
    if target.exists():
        raise ValueError('Model already exists; existing models are never overwritten')
    return target


def download(engine, model, progress):
    # Serialize publication so two clicks cannot replace each other's model.
    with _LOCK:
        target = validate(engine, model)
        progress(f'Downloading {model}')
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.stt-', suffix='.part')
        try:
            with os.fdopen(fd, 'wb') as out, urlopen(MODELS[model], timeout=15) as response:
                total = int(response.headers.get('Content-Length', 0))
                received = 0
                while True:
                    progress(f'{model}: {received} of {total or "unknown"} bytes')
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
                    received += len(block)
                if not received or (total and received != total):
                    raise ValueError('Incomplete model download')
            progress(f'Download complete: {received} bytes; saving model')
            # Link is atomic and refuses an existing destination, including races
            # with another process. The temporary file is on the same filesystem.
            os.link(temporary, target)
        finally:
            os.unlink(temporary)
    return {'model': str(target)}


def start_job(engine, model):
    validate(engine, model)
    return jobs.start('stt-download', '', lambda progress: download(engine, model, progress), cancellable=True)

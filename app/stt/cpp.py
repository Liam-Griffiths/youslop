import json
import subprocess
from . import binary
from .common import local_model, normalize, window


def transcribe(path, *, model, language=None, start=None, end=None, progress, cancel, context=False, executable=''):
    with window(path, start, end) as (wav, offset):
        output = wav.with_suffix('')
        command = [binary(executable) or 'whisper-cli', '-m', local_model(model), '-f', str(wav),
                   '-ojf', '-of', str(output), '-l', language or 'auto']
        # File output avoids a blocked stderr pipe; poll for cooperative cancellation.
        with wav.with_suffix('.log').open('w+') as log:
            process = subprocess.Popen(command, stdout=log, stderr=log)
            try:
                while True:
                    cancel()
                    try:
                        code = process.wait(timeout=.2)
                        break
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            if code:
                log.seek(0)
                raise RuntimeError(log.read()[-2000:])
        result = json.loads(output.with_suffix('.json').read_text())
        from . import report
        report('whisper.cpp', version=result.get('version', 'unknown (executable did not report)'),
               device='unknown (executable did not report execution device)')
        rows = []
        for s in result['transcription']:
            words = []
            for token in s.get('tokens', []):
                text = token['text']
                if text.startswith('[_') or token['offsets']['from'] < 0:
                    continue
                a, b = token['offsets']['from'] / 1000, token['offsets']['to'] / 1000
                if words and not text.startswith(' '):
                    words[-1]['w'] += text
                    words[-1]['end'] = b
                elif text.strip():
                    words.append(dict(w=text.strip(), start=a, end=b, p=token.get('p')))
            rows.append(dict(start=s['offsets']['from'] / 1000, end=s['offsets']['to'] / 1000,
                             text=s['text'], words=words))
        yield from normalize(rows, offset, start, end, cancel, context)

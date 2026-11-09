from .common import local_model, normalize, window


def transcribe(path, *, model, language=None, start=None, end=None, progress, cancel):
    import whisper
    cancel()
    engine = whisper.load_model(local_model(model), device='cpu')
    with window(path, start, end) as (wav, offset):
        result = engine.transcribe(str(wav), language=language, word_timestamps=True, fp16=False)
        rows = ({**s, 'words': [dict(w=w['word'].strip(), start=w['start'], end=w['end'],
                                    p=w.get('probability')) for w in s.get('words', [])]}
                for s in result['segments'])
        yield from normalize(rows, offset, start, end, cancel)

from .common import local_model, normalize, window


def transcribe(path, *, model, language=None, start=None, end=None, progress, cancel):
    import mlx_whisper
    cancel()
    with window(path, start, end) as (wav, offset):
        result = mlx_whisper.transcribe(str(wav), path_or_hf_repo=local_model(model),
                                        language=language, word_timestamps=True)
        rows = ({**s, 'words': [dict(w=w['word'].strip(), start=w['start'], end=w['end'],
                                    p=w.get('probability')) for w in s.get('words', [])]}
                for s in result['segments'])
        yield from normalize(rows, offset, start, end, cancel)

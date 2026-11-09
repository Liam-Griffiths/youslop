from .common import local_model, normalize, window


def transcribe(path, *, model, language=None, start=None, end=None, progress, cancel, device='cpu'):
    from faster_whisper import WhisperModel
    cancel()
    engine = WhisperModel(local_model(model), device=device, compute_type='int8' if device == 'cpu' else 'float16', local_files_only=True)
    with window(path, start, end) as (wav, offset):
        segments, _ = engine.transcribe(str(wav), language=language, word_timestamps=True)
        rows = ({'start': s.start, 'end': s.end, 'text': s.text,
                 'words': [dict(w=w.word.strip(), start=w.start, end=w.end, p=w.probability)
                           for w in (s.words or [])]} for s in segments)
        yield from normalize(rows, offset, start, end, cancel)

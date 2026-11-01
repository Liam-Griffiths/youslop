"""Loudmouth's scene context; timing remains owned by cuts/kit."""
from .. import scenes, scene_builder
from . import loudmouth

TEMPLATE = 'cuts/loudmouth.html'


def context(project, ctx, beats, sources, chapter='', card_at=None, hide=frozenset()):
    data = scenes.context_base(project, ctx.channel)
    data['palette'].update(loudmouth._palette(ctx))
    data['fonts'].update(Display='/fonts/ArchivoBlack-Regular.ttf', Bold='/fonts/Inter-Bold.ttf')
    data.update(look=ctx.look, beats=[], chapter=chapter, card_at=card_at, hide_cues='cues' in hide)
    offset = 0.0
    for beat, source in zip(beats, sources):
        data['beats'].append(dict(id=beat.slide.id, start=offset, length=beat.length,
            voice_end=beat.lead+beat.spoken, source=str(source) if source else '',
            source_stamp=[source.stat().st_mtime_ns, source.stat().st_size] if source else None,
            video=bool(beat.motion), cues=[dict(cue, start=a, end=b,
                words=loudmouth._words(cue['text'])) for cue, (a,b) in zip(beat.cues, beat.times)]))
        offset += beat.length
    return data


def render(project, ctx, beats, sources, out, *, seconds, size, fps, crf,
           chapter='', card_at=None, hide=frozenset(), frames=None):
    data = context(project, ctx, beats, sources, chapter, card_at, hide)
    result = scene_builder.render(project, TEMPLATE, data, out, seconds=seconds,
                                  size=size, fps=fps, crf=crf, frames=frames)
    # Consumers/reviewer can inspect the real builder counters beside a preview.
    import json
    out.with_suffix(out.suffix+'.stats.json').write_text(json.dumps(result.stats, sort_keys=True))
    return result.path

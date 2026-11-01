"""Fast storyboard checks. No rendering, media probing or model calls."""
from dataclasses import asdict, dataclass
from typing import Callable

from . import cuts, render, storyboard, titles
from .cuts import kit
from .schema import FrameSpec


@dataclass
class Finding:
    code: str
    level: str
    t: float
    slide_id: str
    msg: str
    fix: dict

    def to_dict(self):
        return asdict(self)


@dataclass
class Ctx:
    words: list[tuple[float, str, str, str]]
    overlays: list[tuple[float, str, str]]
    lines: list[dict]


def _pictures(sb):
    return [s for s in sb['segments'] if s['type'] == 'picture']


def _cues(sb):
    return [(p, c) for p in sb['paragraphs'] for c in p.get('cues', [])]


def _finding(code, level, t, sid, msg, kind='none', **fix):
    return Finding(code, level, round(max(0, t), 3), sid, msg,
                   {'kind': kind, **({'slide_id': sid} if sid else {}), **fix})


def _ctx(sb):
    words, overlays, lines = [], [], []
    frame = FrameSpec.from_dict(sb.get('frame', {}))
    paras = {p['id']: p for p in sb['paragraphs']}
    fmt = sb['project']['format']
    for p in sb['paragraphs']:
        for w in p.get('take', {}).get('words', []):
            words.append((p['start'] + w['start'], w['w'], p['id'], w.get('src', 'est')))
        for c in p.get('cues', []):
            overlays.append((c['start'], c['kind'], p['id']))
            if c.get('text', '').strip():
                lines.append(dict(c, slide_id=p['id'], type='cue'))
    pictures = _pictures(sb)
    for si, seg in enumerate(pictures):
        overlays.append((seg['start'], 'picture', seg['lead']))
        offset = seg['start'] - seg.get('skip', 0)
        file_end = seg['start'] + seg['duration'] + seg.get('skip', 0)
        for pi, para in enumerate(seg['paragraphs']):
            p = paras[para['id']]
            dur = para['duration']
            final = si == len(pictures) - 1 and pi == len(seg['paragraphs']) - 1
            if fmt == 'essay':
                chunks = titles.essay_chunks(p['narration'])
                spoken = p['take'].get('duration') or dur * .85
                shares = render._caption_timings(chunks, min(dur, spoken), frame)
                if final and shares:
                    shares[-1] = max(shares[-1], frame.last_line_min_s)
                cap = offset
                for text, share in zip(chunks, shares):
                    end = min(file_end - .05, cap + share)
                    # Include omitted flashes: they still fail the reading contract.
                    lines.append(dict(start=cap, end=end, text=text,
                                      slide_id=p['id'], type='caption'))
                    cap += share
            elif fmt == 'kenburns' and p.get('title'):
                start = offset + frame.arrive_s
                hold = render._title_hold(frame, p['title'], dur)
                if final:
                    hold = max(hold, frame.last_line_min_s)
                end = min(file_end - frame.arrive_s * frame.exit_ratio, start + hold)
                lines.append(dict(start=start, end=end, text=p['title'],
                                  slide_id=p['id'], type='title'))
            offset += dur
        for card in seg.get('cards', []):
            lines.append(dict(card, type='chapter'))
    overlays.extend((l['start'], l['type'], l['slide_id']) for l in lines
                    if l['type'] != 'cue')
    return Ctx(sorted(words), sorted(overlays), sorted(lines, key=lambda l: l['start']))


def empty_first_frame(sb, frame, ctx):
    pictures = _pictures(sb)
    if not pictures:
        return []
    first = pictures[0]
    p = next((p for p in sb['paragraphs'] if p['id'] == first['lead']), {})
    if cuts.is_cut(sb['project']['format']):
        cues = p.get('cues', [])
        # A normalised photo/chart cue can be valid without a text field.
        empty = not cues or not cues[0].get('kind')
    else:
        empty = not p.get('picture', {}).get('path')
    return [_finding('empty_first_frame', 'P0', first['start'], first['lead'],
                     'The opening picture has no chosen asset or readable cue.', 'picture')] if empty else []


def hook_muted(sb, frame, ctx):
    hook = sb.get('outline', {}).get('hook') or {}
    title_only = bool(sb['segments'] and (sb['segments'][0]['type'] in {'title', 'chapter'} or
                      sb['segments'][0].get('title_only')))
    if not hook.get('muted_image') or title_only:
        return [_finding('hook_muted', 'P1', 0, '',
                         'The opening needs a clear image that works with the sound muted.', 'picture')]
    return []


def first_word_collision(sb, frame, ctx):
    if not ctx.words:
        return []
    t, _, sid, _ = ctx.words[0]
    windows = [(0, sb.get('sting_end', 0))]
    windows += [(l['start'], l['end'] if l['type'] == 'chapter' else
                 l['start'] + (0.14 if l['type'] == 'caption' else frame.arrive_s))
                for l in ctx.lines if l['type'] != 'cue']
    if any(a <= t < b for a, b in windows):
        return [_finding('first_word_collision', 'P1', t, sid,
                         'The first spoken word overlaps a sting, chapter card or title arrival.', 'timing')]
    return []


def dead_stretch(sb, frame, ctx):
    spans = []
    if cuts.is_cut(sb['project']['format']):
        changes = sorted({c['start'] for _, c in _cues(sb)})
        for seg in _pictures(sb):
            points = [seg['start']] + [t for t in changes if seg['start'] < t < seg['start'] + seg['duration']]
            points.append(seg['start'] + seg['duration'])
            spans.extend((a, b - a, 3, seg['lead']) for a, b in zip(points, points[1:]))
    elif sb['project']['format'] in {'kenburns', 'essay'}:
        spans = [(s['start'], s['duration'], min(frame.max_gap_ever_s,
                  frame.max_gap_first_90_s if s['start'] < 90 else frame.max_gap_after_s), s['lead'])
                 for s in _pictures(sb)]
    return [_finding('dead_stretch', 'P1', t, sid,
                     f'The picture holds for {dur:.1f}s without a change (limit {limit:g}s).',
                     'cues', instruction=f'add a cue at {t + limit:.3f}')
            for t, dur, limit, sid in spans if dur > limit]


def overlay_budget(sb, frame, ctx):
    total = sb['project']['duration']
    windows = [(0, min(total, frame.hook_s), frame.overlays_per_hook, 'opening')]
    windows += [(t, min(total, t + 90), frame.overlays_per_90_s, '90-second interval')
                for t in range(0, int(total), 90)]
    return [_finding('overlay_budget', 'P2', a, '',
                     f'The {label} has fewer than {budget} visual changes.', 'cues')
            for a, b, budget, label in windows if b > a and
            sum(a <= t < b for t, _, _ in ctx.overlays) < budget]


def small_text(sb, frame, ctx):
    # TODO(T5.2e): scenes report their own fitted size.
    out = []
    for line in ctx.lines:
        if line['type'] == 'caption':
            font, _ = titles._fit_caption(line['text'], titles.CAPTION_MAX_W)
            size = font.size
        elif line['type'] == 'title':
            size = round(1080 * (frame.title_height_pct_min + frame.title_height_pct_max) / 200 / .72)
        else:
            continue
        if size < frame.title_height_pct_min / 100 * 1080:
            out.append(_finding('small_text', 'P1', line['start'], line['slide_id'],
                                f'Text fits at only {size}px; font size approximates visible letter height.',
                                'words', instruction='shorten'))
    return out


def unreadable_line(sb, frame, ctx):
    return [_finding('unreadable_line', 'P1', l['start'], l['slide_id'],
                     'The text disappears before there is time to read it.', 'timing',
                     min_hold=frame.title_hold_base_s + frame.title_hold_per_word_s * len(l['text'].split()))
            for l in ctx.lines if l['end'] - l['start'] + 1e-6 <
            frame.title_hold_base_s + frame.title_hold_per_word_s * len(l['text'].split())]


def anchor_off(sb, frame, ctx):
    out = []
    for p in sb['paragraphs']:
        words = [(t, kit._norm(w), src) for t, w, sid, src in ctx.words if sid == p['id']]
        pos = 0
        for cue in p.get('cues', []):
            on = kit._norm(cue.get('on', '')).split()
            match = None
            for n in (3, 2, 1):
                if len(on) < n:
                    continue
                match = next((i for i in range(pos, len(words) - n + 1)
                              if [w[1] for w in words[i:i+n]] == on[:n]), None)
                if match is not None:
                    break
            if match is None:
                continue
            t, _, src = words[match]
            pos = match + 1
            delta = cue['start'] - t
            if delta > frame.anchor_after_s + 1e-6 or delta < -frame.anchor_before_s - 1e-6:
                out.append(_finding('anchor_off', 'P2' if src == 'est' else 'P1', cue['start'], p['id'],
                                    f'The cue is {delta:+.2f}s from its spoken anchor.', 'timing', anchor=t))
    return out


def same_device_twice(sb, frame, ctx):
    out = []
    pictures = _pictures(sb)
    for a, b in zip(pictures, pictures[1:]):
        if a.get('camera') and a['camera'] == b.get('camera'):
            out.append(_finding('same_device_twice', 'P2', b['start'], b['lead'],
                                'Consecutive pictures repeat the same camera move.', 'picture'))
    cues = _cues(sb)
    for (_, a), (p, b) in zip(cues, cues[1:]):
        if a.get('kind') and a['kind'] == b.get('kind'):
            out.append(_finding('same_device_twice', 'P2', b['start'], p['id'],
                                'Consecutive cues repeat the same device.', 'cues'))
    return out


def last_line_short(sb, frame, ctx):
    if not ctx.lines:
        return []
    line = ctx.lines[-1]
    if line['end'] - line['start'] + 1e-6 < frame.last_line_min_s:
        return [_finding('last_line_short', 'P1', line['start'], line['slide_id'],
                         'The final line needs more time to land.', 'timing', min_hold=frame.last_line_min_s)]
    return []


def silent_film(sb, frame, ctx):
    if sb.get('music'):
        return []
    spans = [(p['start'], p['start'] + p['take'].get('duration', 0))
             for p in sb['paragraphs'] if p.get('take', {}).get('path')]
    spans += sb.get('music_spans', [])
    out, end = [], 0
    for a, b in sorted(spans) + [(sb['project']['duration'], sb['project']['duration'])]:
        if a - end > 15:
            out.append(_finding('silent_film', 'P1', end, '',
                                f'The film has {a - end:.1f}s without narration or music.', 'timing'))
        end = max(end, b)
    return out


def open_loop_unpaid(sb, frame, ctx):
    from .script_gen import check_hook
    return [_finding('open_loop_unpaid', 'P1', 0, '', flag['issue'], 'words')
            for flag in check_hook(sb.get('outline', {}))]


def banned_used(sb, frame, ctx):
    names = [(c['kind'], c['start'], p['id']) for p, c in _cues(sb)]
    names += [(s.get(key, ''), s['start'], s.get('lead', ''))
              for s in sb['segments'] for key in ('camera', 'transition')]
    return [_finding('banned_used', 'P2', t, sid,
                     f'The device “{name}” uses the banned look “{ban}”.', 'style')
            for name, t, sid in names for ban in frame.banned
            if ban and ban.casefold() in name.casefold()]


def timeline_problem(sb, frame, ctx):
    dead = {f.slide_id for f in dead_stretch(sb, frame, ctx)}
    return [_finding('timeline_problem', 'P1', s['start'], s.get('lead', ''), msg)
            for s in sb['segments'] for msg in s.get('problems', [])
            if not (s.get('lead') in dead and msg.startswith('the same picture holds for '))]


def _sponsor_reads(sb):
    slots = {s['id']: s for s in sb.get('sponsors', []) if s.get('enabled', True)}
    previous = ''
    for seg in sb['segments']:
        if seg['type'] == 'picture' and seg.get('paragraphs'):
            previous = seg['paragraphs'][-1]['id']
        if seg['type'] == 'sponsor' and seg.get('sponsor') in slots:
            yield slots[seg['sponsor']], seg['start'], previous


def sponsor_early_long(sb, frame, ctx):
    return [_finding('sponsor_early_long', 'P1', t, sid,
                     'Move the long sponsor read after the first 60 seconds.')
            for slot, t, sid in _sponsor_reads(sb) if slot['variant'] == 'long' and t < 60]


def sponsor_count(sb, frame, ctx):
    seen, out = set(), []
    for slot, t, sid in _sponsor_reads(sb):
        variant = slot['variant']
        if variant in seen:
            out.append(_finding('sponsor_count', 'P2', t, sid,
                                f'Use at most one {variant} sponsor read by default.'))
        seen.add(variant)
    return out


def sponsor_disclosure(sb, frame, ctx):
    import re
    bundled = {'sponsor/' + name + '.html' for name in
               ('house_short', 'short', 'short_vertical', 'long', 'long_vertical')}
    return [_finding('sponsor_disclosure', 'P1', t, sid,
                     'The paid sponsor needs visible disclosure (for example “Paid promotion”).')
            for slot, t, sid in _sponsor_reads(sb) if slot.get('paid') and
            (slot.get('template') not in bundled or not re.search(
                r'\b(paid|sponsored|advertisement)\b',
                slot.get('vars', {}).get('made', ''), re.IGNORECASE))]


def sponsor_question(sb, frame, ctx):
    paras = {p['id']: p for p in sb['paragraphs']}
    return [_finding('sponsor_question', 'P2', t, sid,
                     'A sponsor follows a question; keep its answer before the read.')
            for slot, t, sid in _sponsor_reads(sb)
            if paras.get(sid, {}).get('narration', '').rstrip().endswith('?')]


def sponsor_music(sb, frame, ctx):
    style = sb.get('style', {})
    if not sb.get('music') or style.get('music_db', -17.5) + style.get('sponsor_music_db', -6) <= 0:
        return []
    return [_finding('sponsor_music', 'P1', t, sid,
                     'Music is louder than the voice during the sponsor read.', 'style')
            for slot, t, sid in _sponsor_reads(sb)]


Rule = Callable[[dict, FrameSpec, Ctx], list[Finding]]
RULES: list[Rule] = [empty_first_frame, hook_muted, first_word_collision, dead_stretch,
                    overlay_budget, small_text, unreadable_line, anchor_off,
                    same_device_twice, last_line_short, silent_film, open_loop_unpaid,
                    banned_used, timeline_problem, sponsor_early_long, sponsor_count,
                    sponsor_disclosure, sponsor_question, sponsor_music]


def run(project) -> dict:
    from .learning import effective_frame
    frame = effective_frame(project)
    sb = storyboard.build(project)
    sb['outline'] = project.outline
    sb['music'] = bool(render.pick_music(project))
    pictures = _pictures(sb)
    groups = render._picture_groups(project, render._slide_durations(project, True))
    for i, seg in enumerate(pictures):
        if i:
            seg['transition'] = render._join_for(groups[i-1], groups[i], frame)
        if i + 1 < len(groups) and project.style.format in {'kenburns', 'essay', 'stage'}:
            card = render.chapter_card(project, groups[i+1][0][0])
            if card:
                from . import audio
                gap = audio.gap_map(project)[groups[i][-1][0].id]
                hold = max(project.frame.arrive_s, min(gap, project.frame.arrive_s +
                           project.frame.title_hold_base_s + project.frame.title_hold_per_word_s * len(card[0].split())))
                end = seg['start'] + seg['duration'] + seg['skip']
                seg['cards'] = [dict(start=max(seg['start'] - seg['skip'] + .2, end - hold),
                                     end=end, text=card[0], slide_id=groups[i+1][0][0].id)]
    channel = render._slate_channel(project)
    for seg in sb['segments']:
        if seg['type'] == 'intro':
            seg['title_only'] = not bool(channel and channel.intro.images)
    stings = render._stings_for(project)
    sb['music_spans'] = []
    for seg in sb['segments']:
        if seg['type'] in stings:
            spec = stings[seg['type']][1]
            end = seg['start'] + seg['duration'] + spec.music_tail
            sb['music_spans'].append((seg['start'], end))
            if seg['type'] == 'intro':
                sb['sting_end'] = end
    ctx = _ctx(sb)
    findings = [f for rule in RULES for f in rule(sb, project.frame, ctx)]
    findings.sort(key=lambda f: (int(f.level[1]), f.t))
    counts = {level: sum(f.level == level for f in findings) for level in ('P0', 'P1', 'P2')}
    return {'ok': counts['P0'] == 0, 'counts': counts,
            'findings': [f.to_dict() for f in findings]}

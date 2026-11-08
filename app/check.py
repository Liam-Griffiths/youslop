"""Storyboard checks with optional cached browser text geometry."""
from dataclasses import asdict, dataclass
from typing import Callable

from . import kinds
from . import cuts, render, storyboard, titles
from .cuts import kit
from .schema import FrameSpec, Project, Slide, Style
from .take_edits import cut_ranges


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


def _kind(sb, seg):
    return seg["kind"] if "kinds" in sb["project"] else sb["project"]["format"]


def _cues(sb):
    return [(p, c) for p in sb['paragraphs'] for c in p.get('cues', [])]


def _finding(code, level, t, sid, msg, kind='none', **fix):
    return Finding(code, level, round(max(0, t), 3), sid, msg,
                   {'kind': kind, **({'slide_id': sid} if sid else {}), **fix})


def _ctx(sb):
    words, overlays, lines = [], [], []
    frame = FrameSpec.from_dict(sb.get('frame', {}))
    paras = {p['id']: p for p in sb['paragraphs']}
    plan_project = Project(id='check', idea='', style=Style(**sb.get('style', {})), frame=frame)
    for p in sb['paragraphs']:
        for w in p.get('take', {}).get('words', []):
            words.append((p['start'] + w['start'], w['w'], p['id'], w.get('src', 'est')))
        for c in p.get('cues', []):
            overlays.append((c['start'], c['kind'], p['id']))
            if c.get('text', '').strip():
                lines.append(dict(c, slide_id=p['id'], type='cue'))
    pictures = _pictures(sb)
    for si, seg in enumerate(pictures):
        fmt = _kind(sb, seg)
        overlays.append((seg['start'], 'picture', seg['lead']))
        offset = seg['start'] - seg.get('skip', 0)
        file_end = seg['start'] + seg['duration'] + seg.get('tail_skip', seg.get('skip', 0))
        for pi, para in enumerate(seg['paragraphs']):
            p = paras[para['id']]
            dur = para['duration']
            final = si == len(pictures) - 1 and pi == len(seg['paragraphs']) - 1
            if fmt == 'essay':
                # Same planner as the graph; storyboard starts are voice time.
                # Storyboard words/duration already use the edited clock.
                member = Slide(id=p['id'], narration=p['narration'],
                               take={k: v for k, v in p['take'].items() if k != 'cuts'})
                for phrase in render._essay_phrases(plan_project, member, dur,
                        lead_in=p['start'] - offset, last_line=final):
                    lines.append(dict(start=offset + phrase['t0'],
                                      end=min(file_end - .05, offset + phrase['t1']),
                                      text=phrase['text'], slide_id=p['id'], type='caption'))
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
    if cuts.is_cut(_kind(sb, first)):
        cues = p.get('cues', [])
        # A normalised photo/chart cue can be valid without a text field.
        empty = not cues or not cues[0].get('kind')
    elif _kind(sb, first) in {'board', 'block', 'camera'} or _kind(sb, first).startswith('custom:'):
        empty = False
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
                 l['start'] + (0.14 if l['type'] == 'caption' and
                              sb.get('style', {}).get('captions_engine', 'scene') == 'pillow'
                              else frame.arrive_s))
                for l in ctx.lines if l['type'] not in {'cue', 'scene'}]
    if any(a <= t < b for a, b in windows):
        return [_finding('first_word_collision', 'P1', t, sid,
                         'The first spoken word overlaps a sting, chapter card or title arrival.', 'timing')]
    return []


def dead_stretch(sb, frame, ctx):
    spans = []
    changes = sorted({c['start'] for _, c in _cues(sb)})
    for seg in _pictures(sb):
        fmt = _kind(sb, seg)
        if cuts.is_cut(fmt):
            points = [seg['start']] + [t for t in changes if seg['start'] < t < seg['start'] + seg['duration']]
            points.append(seg['start'] + seg['duration'])
            spans.extend((a, b - a, 3, seg['lead']) for a, b in zip(points, points[1:]))
        elif fmt in {'kenburns', 'essay'}:
            spans.append((seg['start'], seg['duration'], min(frame.max_gap_ever_s,
                          frame.max_gap_first_90_s if seg['start'] < 90 else frame.max_gap_after_s), seg['lead']))
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
    out, scene_small = [], {}
    for line in ctx.lines:
        if line['type'] == 'caption':
            if sb.get('style', {}).get('captions_engine', 'scene') != 'pillow':
                metrics = line.get('metrics')
                if metrics is None:
                    continue  # Chromium unavailable: geometry needs reviewer verification.
                size = metrics['size']
            else:
                font, _ = titles._fit_caption(line['text'], titles.CAPTION_MAX_W)
                size = font.size
        elif line['type'] == 'scene':
            size = line['metrics']['px']
        elif line['type'] == 'title':
            size = round(1080 * (frame.title_height_pct_min + frame.title_height_pct_max) / 200 / .72)
        else:
            continue
        if size < frame.title_height_pct_min / 100 * 1080:
            if line['type'] == 'scene':
                # A scene reports every text element; one finding per paragraph.
                worst = scene_small.setdefault(line['slide_id'], [line['start'], size, 0])
                worst[1], worst[2] = min(worst[1], size), worst[2] + 1
                continue
            out.append(_finding('small_text', 'P1', line['start'], line['slide_id'],
                                f'Text fits at only {size}px; font size approximates visible letter height.',
                                'words', instruction='shorten'))
    for sid, (start, size, count) in scene_small.items():
        lines = f' ({count} text elements)' if count > 1 else ''
        out.append(_finding('small_text', 'P1', start, sid,
                            f'Text fits at only {size}px{lines}; font size approximates visible letter height.',
                            'words', instruction='shorten'))
    return out


def text_overflow(sb, frame, ctx):
    return [_finding('text_overflow', 'P1', line['start'], line['slide_id'],
                     'Text overflows its rendered box or the frame.', 'words', instruction='shorten')
            for line in ctx.lines if line.get('metrics', {}).get('overflow')]


def unreadable_line(sb, frame, ctx):
    return [_finding('unreadable_line', 'P1', l['start'], l['slide_id'],
                     'The text disappears before there is time to read it.', 'timing',
                     min_hold=frame.title_hold_base_s + frame.title_hold_per_word_s * len(l['text'].split()))
            for l in ctx.lines if l['type'] != 'scene' and l['end'] - l['start'] + 1e-6 <
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
    lines = [line for line in ctx.lines if line['type'] != 'scene']
    if not lines:
        return []
    line = lines[-1]
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


def number_match(sb, frame, ctx):
    from . import blocks, core_data_blocks, data_numbers, number_blocks
    out, library = [], None
    for p in sb['paragraphs']:
        cues = p.get('block_cues', []) + [c for c in p.get('cues', []) if c.get('block')]
        if not cues:
            continue
        if library is None:
            library = blocks.discover()
        numbers, dates, headlines = [], [], []
        for cue in cues:
            ref = cue.get('block')
            if ref not in core_data_blocks.IDS + number_blocks.DATA_IDS:
                continue
            meta = library[ref]['meta']
            values = blocks.validate_vars(meta, cue.get('vars', {}))
            ns, ds, hs = data_numbers.shown(meta, values, ref)
            numbers.extend(ns)
            dates.extend(ds)
            headlines.extend(hs)
        spoken = data_numbers.extract(p['narration'])
        bad = [s['text'] for s in spoken if (not s['year'] or dates) and
               not any(data_numbers.matches(s, n) for n in (dates if s['year'] else numbers))]
        nonyears = [s for s in spoken if not s['year']]
        bad += [h['text'] for h in headlines if nonyears and
                not any(data_numbers.matches(s, h) for s in nonyears)]
        if bad and (numbers or dates):
            out.append(_finding('number_match', 'P1', p['start'], p['id'],
                f'Numbers disagree: narration [{", ".join(s["text"] for s in spoken)}]; '
                f'block [{", ".join(n["text"] for n in numbers + dates)}]. '
                f'Unmatched: {", ".join(dict.fromkeys(bad))}.', 'words', instruction='check data'))
    return out


def _camera_paragraphs(sb):
    return [p for p in sb['paragraphs'] if p.get('on_camera')]


def camera_dark(sb, frame, ctx):
    from .camera import correction
    out = []
    for p in _camera_paragraphs(sb):
        take = p['take']
        luma = take.get('measure', {}).get('YAVG')
        brightness, _ = correction(take, sb.get('camera_target', 110))
        if luma is not None and luma + brightness * 255 < 60:
            out.append(_finding('camera_dark', 'P1', p['start'], p['id'],
                                'Camera picture remains too dark after gentle correction.'))
    return out


def camera_blown(sb, frame, ctx):
    return [_finding('camera_blown', 'P1', p['start'], p['id'],
                     'More than 3% of camera pixels have clipped highlights.')
            for p in _camera_paragraphs(sb) if p['take'].get('measure', {}).get('clipped', 0) > .03]


def camera_sync(sb, frame, ctx):
    return [_finding('camera_sync', 'P0', p['start'], p['id'],
                     'Camera audio/video start offset exceeds 80 ms and is uncorrected.')
            for p in _camera_paragraphs(sb)
            if abs(p['take'].get('av_offset', 0)) > .08
            and not p['take'].get('sync_corrected', 'video_start' in p['take'])]


def camera_low_res(sb, frame, ctx):
    return [_finding('camera_low_res', 'P2', p['start'], p['id'],
                     'Camera footage is narrower than 1280 pixels.')
            for p in _camera_paragraphs(sb) if 0 < p['take'].get('width', 0) < 1280]


def camera_no_focal(sb, frame, ctx):
    return [_finding('camera_no_focal', 'P2', p['start'], p['id'],
                     'Set a focal point: the camera crop may cut off the face.')
            for p in _camera_paragraphs(sb) if not p['take'].get('focal')
            and p['take'].get('height', 0) > 0 and p['take'].get('width', 0) > 0
            and abs(p['take']['width'] / p['take']['height'] - 16 / 9) > .01]


def camera_held(sb, frame, ctx):
    out = []
    for p in _camera_paragraphs(sb):
        take = p['take']
        duration = p['end'] - p['start']
        # Cut ranges are in original take time; overlay times are after cuts.
        events, removed = [0.0, duration], 0.0
        # Storyboard duration is effective; cuts still describe source time.
        for a, b in cut_ranges(take, duration=float('inf')):
            if b > a:
                events.append(max(0, min(duration, a - removed)))
                removed += b - a
        for overlay in take.get('overlays', []):
            if overlay.get('kind') == 'cutaway':
                a = max(0, min(duration, overlay['at']))
                b = max(a, min(duration, overlay['at'] + overlay['dur']))
                events.extend([a, b])
        events = sorted(set(events))
        for a, b in zip(events, events[1:]):
            hidden = any(o.get('kind') == 'cutaway' and o['at'] <= a
                         and o['at'] + o['dur'] >= b for o in take.get('overlays', []))
            if b - a > frame.max_gap_after_s and not hidden:
                out.append(_finding('camera_held', 'P2', p['start'] + a, p['id'],
                                    'Camera shot holds too long; add a cut, punch or cutaway.'))
    return out


Rule = Callable[[dict, FrameSpec, Ctx], list[Finding]]
RULES: list[Rule] = [empty_first_frame, hook_muted, first_word_collision, dead_stretch,
                    overlay_budget, small_text, text_overflow, unreadable_line, anchor_off,
                    same_device_twice, last_line_short, silent_film, open_loop_unpaid,
                    banned_used, timeline_problem, sponsor_early_long, sponsor_count,
                    sponsor_disclosure, sponsor_question, sponsor_music, number_match,
                    camera_dark, camera_blown, camera_sync, camera_low_res,
                    camera_held, camera_no_focal]


def _scene_text(project, sb, ctx, groups, measure):
    from . import board, board_scenes, custom_scenes, scenes, store
    requests, owners = [], []
    for seg, group in zip(_pictures(sb), groups):
        fmt = kinds.kind_for(project, group[0][0])
        _, _, length = render._segment_timing(project, groups, seg['group'])
        offset = seg['start'] - seg['skip']
        if fmt == 'board' and project.style.board_engine != 'pillow':
            previous, spent = '', 0
            for n, (slide, dur) in enumerate(group):
                source, _, _ = render._chosen(project, slide)
                cache = store.project_dir(project.id) / 'board'
                if not measure and source and source.suffix.lower() in {'.mp4', '.mov', '.webm', '.mkv', '.m4v'}:
                    source = cache / f'poster_{source.stem}.jpg'
                image = board._load_photo(source, cache)
                index = next(i for i, s in enumerate(project.slides) if s.id == slide.id)
                key = board.pick(slide, image is not None, previous, index)
                previous = key
                seconds = length - spent if n == len(group) - 1 else min(dur, length - spent)
                if seconds <= .05:
                    continue
                if board_scenes.handles(project, key):
                    hand = project.style.board_hand or board.dg.DEFAULT_HAND
                    sheet = board.build(slide, key, project.style.accent, hand, image)
                    scene = board_scenes.context(project, slide, key, sheet, None, hand,
                        seconds, max(.18, min(1.2, project.style.board_settle)))
                    requests.append((f'board/{key}.html', scene, 0))
                    owners.append((slide.id, offset + spent, seconds))
                spent += seconds
        elif fmt.startswith('custom:'):
            slide = group[0][0]
            root = store.project_dir(project.id) / 'media'
            if slide.custom_html:
                scene = custom_scenes.html_context(root, slide.custom_html, slide.custom, length, project)
            elif project.style.custom_engine != 'pillow':
                from . import slide_styles
                style = slide_styles.get(slide_styles.id_from_format(fmt))
                spec = slide.custom if (slide.custom or {}).get('elements') else style.spec if style else {}
                if not spec:
                    continue
                scene, _ = custom_scenes.context(root, spec, length,
                    hand=project.style.board_hand or 'marker', measure_only=True)
            else:
                continue
            requests.append(('slides/custom.html', scene, 0))
            owners.append((slide.id, offset, length))
        elif scenes.handles(fmt):
            scene = scenes.context_base(project)
            lead = seg['skip'] + cuts.head_pad_for(project, group[0][0])
            scene.update(slides=[dict(asdict(slide), duration=dur) for slide, dur in group],
                         narration='\n\n'.join(s.narration for s, _ in group),
                         titles=[s.title for s, _ in group], duration=length,
                         cues=cuts.timed_cues(project, group, length, lead) if cuts.is_cut(fmt) else [],
                         chapter=None, lead_in=lead, hold=0)
            requests.append((f'{fmt}/segment.html', scene, 0))
            owners.append((group[0][0].id, offset, length))
    for (sid, offset, duration), rows in zip(owners, scenes.measure_many(project, requests, render=measure)):
        for row in rows:
            start = offset + row.get('start', 0)
            ctx.lines.append(dict(type='scene', start=start, end=offset + duration,
                                  slide_id=sid, metrics=row))


def script(project) -> dict:
    """Words only: no storyboard, media probes, browser, or model calls."""
    import hashlib
    import json
    from .learning import effective_frame
    from .script_gen import check_hook
    findings = []
    for slide in project.slides:
        if not slide.narration.strip():
            findings.append(_finding('empty_narration', 'P0', 0, slide.id,
                                     'This paragraph has no narration.', 'words').to_dict())
    for flag in check_hook(project.outline) + (project.research or {}).get('flags', []):
        findings.append(_finding('script_claim', 'P1' if flag.get('severity') == 'high' else 'P2',
            0, flag.get('slide_id', ''),
            ': '.join(filter(None, [flag.get('claim'), flag.get('issue')])), 'words').to_dict())
    for finding in findings:
        finding['id'] = 'script-' + hashlib.sha256(json.dumps(finding, sort_keys=True).encode()).hexdigest()[:16]
    return dict(findings=findings, counts={level: sum(f['level'] == level for f in findings)
                                         for level in ('P0', 'P1', 'P2')},
                rules=effective_frame(project).rules)


def run(project, measure=False) -> dict:
    from .learning import effective_frame
    frame = effective_frame(project)
    sb = storyboard.build(project)
    from .camera import target
    sb['camera_target'] = target(project)
    sb['outline'] = project.outline
    sb['music'] = bool(render.pick_music(project))
    pictures = _pictures(sb)
    groups = render._picture_groups(project, render._slide_durations(project, True))
    for i, seg in enumerate(pictures):
        if i:
            seg['transition'] = ('cut' if any(s.kind for s in project.slides) and render._overlaps(project, groups)[i] == cuts.HARD_CUT
                                 else render._join_for(groups[i-1], groups[i], frame))
        if i + 1 < len(groups) and kinds.kind_for(project, groups[i][0][0]) in {'kenburns', 'essay', 'stage'}:
            card = render.chapter_card(project, groups[i+1][0][0])
            if card:
                from . import audio
                gap = audio.gap_map(project)[groups[i][-1][0].id]
                hold = max(project.frame.arrive_s, min(gap, project.frame.arrive_s +
                           project.frame.title_hold_base_s + project.frame.title_hold_per_word_s * len(card[0].split())))
                end = seg['start'] + seg['duration'] + seg.get('tail_skip', seg['skip'])
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
    from . import scenes, stage
    can_measure = measure and bool(stage.browser())
    if 'essay' in kinds.kinds_in(project) and project.style.captions_engine != 'pillow':
        lines = [line for line in ctx.lines if line['type'] == 'caption']
        if lines:
            for line, metrics in zip(lines, scenes.measure_captions(
                    project, [l['text'] for l in lines], render=can_measure)):
                if metrics is not None:
                    line['metrics'] = metrics
    _scene_text(project, sb, ctx, groups, can_measure)
    findings = [f for rule in RULES for f in rule(sb, project.frame, ctx)]
    for para in sb['paragraphs']:
        slide = next(s for s in project.slides if s.id == para['id'])
        fmt = kinds.kind_for(project, slide)
        if cuts.is_cut(fmt) and not cuts.normalise(cuts.BY_KEY[fmt], slide.cues.get(fmt)):
            findings.append(_finding('no_cues', 'P1', para['start'], slide.id,
                                     'This paragraph has no planned cues for ' + fmt + '.', 'cues'))
    from . import overlay_checks
    if any(s.overlays for s in project.slides):
        sb['layers'] = render._layers(project, sb['segments'])
    findings.extend(overlay_checks.run(project, sb))
    from .retired_catalog import references
    for slide in project.slides:
        for ref in references(slide.to_dict()):
            findings.append(_finding('retired_catalog', 'P1', next(
                (p['start'] for p in sb['paragraphs'] if p['id'] == slide.id), 0),
                slide.id, f'Retired catalog block: {ref}. A placeholder is shown; '
                'choose a Corkbored block in Visuals.'))
    from . import packs
    for ref in sorted(set(packs.missing_items(project.to_dict()) +
                          packs.missing_items(channel.to_dict() if channel else {}))):
        findings.append(_finding('missing_pack_item', 'P1', 0, '',
                                 f'Missing pack item: {ref}. Using a default or omitting it.'))
    findings.sort(key=lambda f: (int(f.level[1]), f.t))
    counts = {level: sum(f.level == level for f in findings) for level in ('P0', 'P1', 'P2')}
    return {'ok': counts['P0'] == 0, 'counts': counts,
            'findings': [f.to_dict() for f in findings]}

"""Sponsor placement in the unsponsored cut, always at paragraph boundaries."""
from . import brand
from .config import HEAD_PAD, WORDS_PER_MINUTE


def duration(slot):
    return round(float((slot.take or {}).get("duration") or
                       max(2.5, len(slot.script.split()) / WORDS_PER_MINUTE * 60)), 3)


def placements(project, plan, pre=0.0):
    """Map paragraph ids to reads following them, preserving slot order.

    Time requests use original picture time (including the opening slate),
    rounded forward to the next paragraph boundary. Other sponsors never move
    that anchor. An explicit paragraph id takes precedence over at_s.
    """
    if not plan:
        return {}
    boundaries, t = [], pre + HEAD_PAD
    for slide, seconds in plan:
        t += seconds
        boundaries.append((slide.id, t))
    result = {}
    for slot in project.sponsors:
        if not slot.enabled:
            continue
        if slot.placement == "end":
            sid = plan[-1][0].id
        elif slot.placement == "mid" and slot.after_slide_id:
            sid = slot.after_slide_id
            if sid not in {s.id for s, _ in plan}:
                continue
        elif slot.placement in {"pre", "mid"}:
            target = pre + project.frame.hook_s if slot.placement == "pre" else slot.at_s
            if target is None:
                continue
            sid = next((sid for sid, end in boundaries if end >= target), boundaries[-1][0])
        else:
            continue
        result.setdefault(sid, []).append(slot)
    return result


def suggest_slots(project):
    """Suggest anchors in unsponsored body time without modifying the project."""
    from .render import _slide_durations
    plan = _slide_durations(project, True)
    if not plan:
        return []
    boundaries, t = [], HEAD_PAD
    for slide, seconds in plan:
        t += seconds
        boundaries.append((slide.id, round(t, 3)))
    pre = next((b for b in boundaries if b[1] >= project.frame.hook_s), boundaries[-1])
    chapters = [boundaries[i - 1] for i, (slide, _) in enumerate(plan)
                if i and slide.chapter.strip()]
    candidates = chapters or boundaries[:-1] or boundaries
    runtime = t - HEAD_PAD
    def rank(boundary):
        fraction = (boundary[1] - HEAD_PAD) / runtime
        return (max(.35 - fraction, 0, fraction - .50), abs(fraction - .425))
    mid = min(candidates, key=rank)
    return [dict(placement=kind, after_slide_id=sid, at_s=seconds)
            for kind, (sid, seconds) in zip(('pre', 'mid', 'end'),
                                           (pre, mid, boundaries[-1]))]


def pads(placements):
    return {sid: sum(duration(slot) for slot in slots) for sid, slots in placements.items()}


def scene_context(ctx):
    """Resolve sponsor copy and take-relative beats without a browser or model.

    Assets are served by the scene host, never fetched remotely. Word matches
    retain their source confidence; an estimate is not upgraded to a TTS timing.
    """
    import math
    import re
    from urllib.parse import urlsplit

    values = {**ctx.get('vars', {}), **ctx}
    defaults = dict(name=brand.NAME, logo='', url=brand.SITE_URL, code='',
                    made='This video was made with',
                    learn='Learn how you can build your own videos',
                    link='Link in the description', accent='#FF5A1F', ink='#1B1B1F')
    limits = dict(name=64, url=120, code=32, made=64, learn=120, link=64)
    sponsor = {key: values.get(key, default) for key, default in defaults.items()}
    for key, limit in limits.items():
        if not isinstance(sponsor[key], str) or len(sponsor[key]) > limit:
            raise ValueError(f'sponsor {key} must be text of at most {limit} characters')
    for key in ('accent', 'ink'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', sponsor[key]):
            raise ValueError(f'sponsor {key} must be a six-digit hex colour')

    # Measure the vendored face before HTML/timeline creation. Keep the approved
    # default size when it fits; otherwise allow two lines with wrapping slack.
    # Ignore negative tracking here so the estimate stays conservative.
    from PIL import ImageFont
    from .config import FONTS_DIR
    font = ImageFont.truetype(str(FONTS_DIR / 'ArchivoBlack-Regular.ttf'), 132)
    name_width = font.getlength(sponsor['name'])
    card_width = 808 if ctx.get('width', 1920) < ctx.get('height', 1080) else 848
    sponsor['name_size'] = (132 if name_width <= card_width else
                            int(min(72, 132 * card_width * 1.8 / name_width)))

    def local(url):
        parts = urlsplit(url)
        if (parts.scheme or parts.netloc or '\\' in url or
                not url.startswith(('/static/', '/scene/')) or
                '..' in parts.path.split('/')):
            raise ValueError('sponsor assets must use local /static/ or /scene/ URLs')
        return url

    if sponsor['logo']:
        sponsor['logo'] = local(sponsor['logo'])
    media = values.get('media', [])
    if not isinstance(media, list) or len(media) > 4:
        raise ValueError('sponsor media must be a list of at most four slots')
    sponsor['media'] = []
    for item in media:
        if item.get('kind', 'image') not in ('image', 'video'):
            raise ValueError('sponsor media kind must be image or video')
        caption = item.get('caption', '')
        if not isinstance(caption, str) or len(caption) > 120:
            raise ValueError('sponsor media caption must be at most 120 characters')
        sponsor['media'].append(dict(src=local(item['src']), kind=item.get('kind', 'image'),
                                     caption=caption))
    # Empty slots stay useful as product-copy cards; no stock/footage searches.
    if not sponsor['media']:
        sponsor['media'] = [dict(src='', kind='image', caption=sponsor['learn']),
                            dict(src='', kind='image', caption=sponsor['link'])]
    elif len(sponsor['media']) < 2:
        raise ValueError('sponsor long reads need two to four media slots')

    seconds = float(ctx.get('duration', 7.5))
    offset = float(ctx.get('word_offset', 0))
    if not math.isfinite(seconds) or seconds <= 0 or not math.isfinite(offset):
        raise ValueError('sponsor duration and word offset must be finite')
    fallback = dict(made=.4, brand=1.9, learn=2.95, link=5.55)
    beats = {key: value / 7.5 * seconds for key, value in fallback.items()}
    sources = {key: 'proportional' for key in beats}
    words = (ctx.get('take') or {}).get('words', [])
    tokens = lambda text: re.findall(r'\w+', text.casefold())
    entries = []
    for word in words:
        try:
            start = float(word['start']) + offset
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(start) and 0 <= start < seconds:
            entries.extend((token, start, word.get('src', 'est')) for token in tokens(word.get('w', '')))

    def match(phrase):
        needle = tokens(phrase)
        if needle:
            for i in range(len(entries) - len(needle) + 1):
                if [e[0] for e in entries[i:i + len(needle)]] == needle:
                    return entries[i][1:]
        return None

    for key, phrases in dict(made=['This video'], brand=[sponsor['name']],
                             learn=['Learn', 'Discover'], link=['link', 'description']).items():
        found = next((hit for phrase in phrases if (hit := match(phrase))), None)
        if found:
            beats[key], sources[key] = found
    for key, value in values.get('beats', {}).items():
        if key in beats:
            value = float(value)
            if not math.isfinite(value) or not 0 <= value < seconds:
                raise ValueError(f'sponsor beat {key} is outside the segment')
            beats[key], sources[key] = value, 'explicit'
    return dict(sponsor=sponsor, beats=beats, beat_sources=sources)


def house():
    from .schema import Sponsor
    return Sponsor(id='house', name=brand.NAME, url=brand.SITE_URL, paid=False,
                   disclosure='This video was made with', template='sponsor/house_short.html',
                   short_copy=f'This video was made with {brand.NAME}. Learn how you can build your own videos, with the link in the description below.')


def library(channel):
    return [house(), *[s for s in channel.sponsors if s.id != 'house']]


def validate_sponsor(payload, existing=None):
    """Validate writes; ids, templates and logo paths are owned by the app."""
    import re
    from .schema import Sponsor
    sponsor = Sponsor.from_dict(existing.to_dict()) if existing else Sponsor()
    limits = dict(name=64, url=120, code=32, short_copy=10000, long_copy=10000, disclosure=64)
    if set(payload) - {*limits, 'accent', 'ink', 'paid'}:
        raise ValueError('Unknown or read-only sponsor field')
    for key, value in payload.items():
        if key in limits and (not isinstance(value, str) or len(value) > limits[key]):
            raise ValueError(f'Invalid sponsor {key}')
        if key in ('accent', 'ink') and (not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value)):
            raise ValueError('Expected six-digit hex colour')
        if key == 'paid' and not isinstance(value, bool):
            raise ValueError('paid must be boolean')
        setattr(sponsor, key, value)
    if not sponsor.name.strip():
        raise ValueError('A sponsor needs a name')
    return sponsor


def copy_to_slot(channel, slot, sponsor_id):
    """Snapshot library values; never touch recordings or resolve on load."""
    sponsor = next((s for s in library(channel) if s.id == sponsor_id), None)
    if sponsor is None:
        raise ValueError('Sponsor not found')
    slot.sponsor_id, slot.paid = sponsor.id, sponsor.paid
    slot.brief = {key: getattr(sponsor, key) for key in
                  ('short_copy', 'long_copy', 'disclosure')}
    slot.script = sponsor.long_copy if slot.variant == 'long' else sponsor.short_copy
    slot.template = sponsor.template if slot.variant == 'short' else 'sponsor/long.html'
    slot.vars = dict(name=sponsor.name, url=sponsor.url, code=sponsor.code,
                     accent=sponsor.accent, ink=sponsor.ink, made=sponsor.disclosure,
                     # The house card's middle line; a paid sponsor has no such line.
                     learn='Learn how you can build your own videos' if sponsor.id == 'house' else '',
                     link='Link in the description',
                     logo=('/scene/{token}/channel/' + sponsor.logo) if sponsor.logo else '')

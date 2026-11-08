"""Conservative, deterministic graphics proposals; no model or media work."""
import hashlib
import re

from . import kinds
from . import block_overlays, blocks, channels, cuts
from .data_numbers import extract


def suggest(narration, visual_note='', title='', *, footage=False, channel=None, aspect=None):
    result = []
    # Explicit hints may name a single person/place. Otherwise avoid interpreting
    # sentence-opening capitalisation as an entity.
    hint = re.search(r'(?:name:|lower third:?)\s*([^;\n.]+)', visual_note, re.I)
    names = re.finditer(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', narration)
    name = hint[1].strip() if hint else next((m[0] for m in names
        if narration[:m.start()].strip() and not re.search(r'[.!?]\s*$', narration[:m.start()])), '')
    if not name and title and title in narration and re.fullmatch(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', title):
        name = title
    if name and name in narration and len(name) <= 48:
        result.append(dict(block_id='lower_third_panel', vars={'title': name, 'subtitle': ''}, on=name))
    numbers = [n['text'] for n in extract(narration) if not n['year']]
    # The data-block parser currently recognises digits; accept common spoken
    # percentages too, preserving the exact phrase as the word anchor.
    spoken = re.search(r'\b(?:[a-z]+[ -]){1,3}(?:per cent|percent)\b', narration, re.I)
    if not numbers and spoken:
        words = r'(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)'
        match = re.search(r'\b' + words + r'(?:[ -]' + words + r'){0,2}\s+(?:per cent|percent)\b', narration, re.I)
        if match:
            numbers = [match[0]]
    if footage and numbers and len(numbers[0]) <= 48:
        result.append(dict(block_id='kinetic_caption_rise', vars={'title': numbers[0]}, on=numbers[0]))
    from .block_suggest import prefer_channel
    return prefer_channel(result[:2], channel, key='block_id', aspect=aspect)


def apply(project, slide):
    """Replace auto proposals only; hand graphics retain values and identity."""
    if slide.on_camera or cuts.is_cut(kinds.kind_for(project, slide)):
        return
    base = next((c for c in slide.candidates if c['id'] == slide.chosen_id), {})
    proposals = suggest(slide.narration, slide.visual_note, slide.title,
                        footage=base.get('provider') == 'footage',
                        channel=channels.load_or_none(project.channel_id),
                        aspect='9:16' if project.aspect == 'portrait' else '16:9')
    hand = [o for o in slide.overlays if o.get('by', 'hand') == 'hand']
    library = blocks.discover()
    used = {o['id'] for o in hand}
    lower = any(o['block_id'].startswith('lower_third_') for o in hand)
    auto = []
    for proposal in proposals:
        if len(hand) + len(auto) >= 2:
            break
        if lower and proposal['block_id'].startswith('lower_third_'):
            continue
        ref = proposal['block_id']
        if ref not in library:
            continue
        ident = 'auto-' + hashlib.sha256((slide.id + ref + proposal['on']).encode()).hexdigest()[:16]
        if ident in used:
            continue
        used.add(ident)
        lower = lower or ref.startswith('lower_third_')
        auto.append(dict(proposal, id=ident, at=0., dur=4., by='auto',
                         position=library[ref]['meta']['overlay']['position'][0]))
    slide.overlays = hand + block_overlays.validate(slide.take, auto)

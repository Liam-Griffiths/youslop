"""Offline suggestions from explicit words and numbers; never apply a choice."""
import re

from .data_numbers import SCALES, extract


def _clip(text: str, limit: int) -> str:
    """Trim at a word boundary, without a dangling comma or 'and'."""
    text = ' '.join(text.split()).strip(' ,;:-.')
    if len(text) <= limit:
        return text
    cut = text[:limit + 1].rsplit(' ', 1)[0]
    if cut.rfind(',') >= 12:  # Prefer a whole clause to a broken one.
        cut = cut[:cut.rfind(',')]
    for _ in range(3):  # "…, up from" → "…"
        cut = re.sub(r'[\s,]+(?:and|or|but|the|a|an|of|to|in|by|from|with|for|at|on|up|as)$', '', cut, flags=re.I)
    return cut.strip(' ,;:-')


def _date_label(text: str, date: str) -> str:
    """The words after a year, up to the next year or the end of the clause."""
    m = re.search(r'(?<!\d)' + re.escape(date) + r'(?!\d)[,]?\s*(.*?)(?=(?<!\d)\d{4}(?!\d)|[.;!?]|,\s*(?:and|but)\b|$)', text)
    label = _clip(m[1], 40) if m else ''
    return label[:1].upper() + label[1:]


def suggest(narration: str, visual_note: str = '', title: str = '') -> list[dict]:
    text = f'{narration} {visual_note}'.strip()
    heading = _clip(title or re.split(r'(?<=[.!?])\s', narration.strip())[0], 48)
    result = []

    def add(ref, values, reason):
        result.append({'block': ref, 'vars': {'title': heading, **values}, 'reason': reason})

    steps = re.split(r'\b(?:first|then|finally)\b[:,]?\s*|(?:^|\s)\d+[.)]\s+', text, flags=re.I)
    has_steps = len(steps) >= 3
    numbers = extract(text)
    dates = re.findall(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)', text)
    if not dates:
        dates = [str(int(n['value'])) for n in numbers if n['year']]
    dates = list(dict.fromkeys(dates))
    if len(dates) >= 2:
        add('date_timeline', {'rows': [{'date': d, 'label': _date_label(text, d)} for d in dates], 'source': ''}, 'Sequence of dates')
    quantities = [n for n in numbers if not n['year'] and not has_steps]
    # ISO date components are dates, not quantities.
    if re.search(r'\d{4}-\d{2}-\d{2}', text):
        quantities = [n for n in extract(re.sub(r'\d{4}-\d{2}-\d{2}', '', text)) if not n['year'] and not has_steps]
    for n in quantities:
        if n['percent'] and 0 <= n['value'] <= 100:
            add('percentage_ring', {'value': float(n['value']), 'label': '', 'source': ''}, 'Percentage in the paragraph')
            break
    if len(quantities) >= 2:
        add('stat_comparison', {'rows': [{'label': n['text'].strip(), 'value': float(n['value'])} for n in quantities[:2]],
                                'unit': '%' if all(n['percent'] for n in quantities[:2]) else '', 'source': ''}, 'Two quantities to compare')
    if quantities:
        n = quantities[0]
        unit = next((word for word in SCALES if re.search(r'\b' + word + r'\b', n['text'], re.I)), '')
        value = n['value'] / SCALES[unit] if unit else n['value']
        if abs(value) <= 999999:
            decimals = min(2, max(0, -value.normalize().as_tuple().exponent))
            add('number_slam', {'value': float(value), 'decimals': str(decimals),
                                'unit': '%' if n['percent'] else unit, 'source': ''}, 'Number in the paragraph')
    quote = re.search(r'[“"]([^”"\n]+)[”"]', text)
    if quote:
        said = re.match(r'\s*,?\s*(?:said|says|wrote|writes|told \w+)\s+([^.,;]+)|\s*,?\s*([^.,;]+?)\s+(?:said|says|wrote|writes)\b',
                        text[quote.end():], re.I)
        who = _clip((said[1] or said[2]) if said else '', 60)
        for ref, limit in [('quote_card', 160), ('pull_quote_picture', 120)]:
            add(ref, {'title': _clip(quote[1], limit), 'subtitle': who[:1].upper() + who[1:]}, 'Quoted words')
    if has_steps:
        rows = [{'label': s.strip(' ,.;:\n')} for s in steps[1:] if s.strip(' ,.;:\n')]
        add('step_list', {'rows': rows, 'source': ''}, 'Ordered steps')
    if re.search(r'\b(?:map|where|location)\b', visual_note, re.I):
        add('map_highlight', {'title': visual_note[:48], 'label': '', 'source': '', 'picture': ''}, 'Map requested in the picture note')
    return result

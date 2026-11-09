"""Bounded, offline layouts for generic screen blocks; never execute sample code."""
import math
import re

IDS = ('chat_thread', 'post_card', 'comment_card', 'notification_stack', 'news_ticker',
       'search_box', 'code_typing', 'code_diff', 'terminal', 'flow_steps')
DATA_IDS = ('post_card',)
TOKEN = re.compile(r'("[^"\n]*"|\'[^\'\n]*\'|#[^\n]*|\b(?:def|return|if|else|for|in|import|from|print|True|False|None)\b|\b\d+(?:\.\d+)?\b)')


def layout(ref, v, ctx):
    portrait = ctx['height'] > ctx['width']
    x, w, y, h = (130, 756, 520, 880) if portrait else (230, 1460, 300, 560)
    if ref in ('comment_card', 'news_ticker'):
        if ref == 'comment_card' and not portrait:
            w = 1000
            if ctx.get('overlay_position', '').endswith('right'):
                x = 690
        h = 380 if ref == 'comment_card' else 220
        y = (1440 if portrait else 950)-h
        pos = ctx.get('overlay_position', '')
        if pos.startswith('top'):
            y = 350 if portrait else 190
    rows = v.get('rows', [])
    lo, hi = {'chat_thread':(1,4), 'post_card':(1,3), 'notification_stack':(1,3),
              'search_box':(1,3), 'terminal':(1,5), 'flow_steps':(2,5)}.get(ref,(0,0))
    if not lo <= len(rows) <= hi:
        raise ValueError(f'rows: {ref} requires {lo}..{hi} rows')
    result = []
    for i, row in enumerate(rows):
        item = dict(row)
        for key in ('sender', 'label', 'text'):
            if key not in row:
                continue
            limit = 80 if key == 'text' else 24
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > limit:
                raise ValueError(f'rows[{i}].{key}: requires 1..{limit} characters')
        if ref == 'post_card':
            n = row['value']
            if type(n) not in (int,float) or not math.isfinite(n) or not 0 <= n <= 999999999 or n != int(n):
                raise ValueError(f'rows[{i}].value: requires an integer in 0..999999999')
            item['display'] = f'{int(n):,}'
        result.append(item)
    if ref == 'code_typing' and len(v['code'].split('\n')) > 4:
        raise ValueError('code: requires at most four lines')
    if ref == 'code_diff' and any('\n' in v[key] for key in ('before','after')):
        raise ValueError('before/after: requires single-line snippets')
    tokens = []
    for part in TOKEN.split(v.get('code','')):
        if part:
            kind = 'literal' if part[0] in "\"'" or part[0].isdigit() else 'note' if part.startswith('#') else 'keyword' if TOKEN.fullmatch(part) else 'plain'
            tokens.append(dict(text=part,kind=kind))
    return dict(ref=ref,portrait=portrait,x=x,w=w,y=y,h=h,rows=result,tokens=tokens,
                gap=h/max(1,len(rows)), header=330 if portrait else 140)

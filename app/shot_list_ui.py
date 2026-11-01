"""Plain, shareable shot-list page; all routes inherit app token middleware."""
from html import escape
from urllib.parse import quote

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import footage, shot_list, stage, store


def _project(pid):
    # Project store paths are trusted elsewhere; validate this public page's ids.
    if not pid.isascii() or not pid.isalnum():
        raise HTTPException(400, 'Invalid project id')
    try:
        return store.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Project not found') from exc


def _shoot(shoot):
    if not shoot:
        return None
    try:
        return footage.load(shoot)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, 'Shoot not found') from exc


def _url(pid, shoot=''):
    return f'/projects/{pid}/shot-list' + (f'?shoot={quote(shoot)}' if shoot else '')


def page_html(project, selected=None, *, printable=False):
    rows = []
    # People on set read paragraph numbers, not ids.
    number = {s.id: i + 1 for i, s in enumerate(project.slides)}
    for i, shot in enumerate(project.shot_list):
        result = shot_list.coverage(shot, selected) if selected else None
        status = (f'<p>{result["status"]}'
                  + (': ' + escape(', '.join(m['clip_id'] for m in result['matches']))
                     if result['matches'] else '') + '</p>') if result else ''
        rows.append(f'''<li><label><input type="checkbox" name="done" value="{i}"
            {'checked' if shot.done else ''}> Shot {i + 1} · {escape(shot.size)}</label>
            <p>{'<br>'.join(escape(n) for n in shot.notes)}</p>
            <small>{'Paragraph' if len(shot.paragraph_ids) == 1 else 'Paragraphs'} {escape(', '.join(str(number.get(pid, pid)) for pid in shot.paragraph_ids))}</small>{status}</li>''')
    controls = ''
    if not printable:
        options = '<option value="">Before filming</option>' + ''.join(
            f'<option value="{escape(s.id)}" '
            f'{"selected" if selected and s.id == selected.id else ""}>'
            f'{escape(s.path or s.id)}</option>' for s in footage.list_shoots())
        pdf = (f'<a href="{_url(project.id)}/pdf'
               f'{"?shoot=" + quote(selected.id) if selected else ""}">Download PDF</a>'
               if stage.browser() else '')
        controls = f'''<nav><a href="/#/p/{project.id}/script">Back to Script</a> {pdf}</nav>
            <form method="get"><label for="shoot">Coverage from shoot</label>
            <select id="shoot" name="shoot">{options}</select><button>Show coverage</button></form>
            <form method="post" action="{_url(project.id)}/build"><button>Build / update shot list</button></form>'''
    action = _url(project.id, selected.id if selected else '')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Shot list · {escape(project.title or project.idea)}</title>
        <style>
        *{{box-sizing:border-box}} body{{margin:0;background:#0E0F11;color:#F2F2F2;
        font:18px/1.6 sans-serif}} main{{max-width:760px;margin:auto;padding:24px}}
        a{{color:#6FB7FF;margin-right:16px}} form{{margin:20px 0}}
        button,select{{font:inherit;min-height:44px;max-width:100%;margin:6px 0;
        padding:8px;background:#1D2026;color:inherit;border:1px solid #A0A6AE;border-radius:4px}}
        li{{border-top:1px solid #A0A6AE;padding:20px 0;break-inside:avoid;overflow-wrap:anywhere}}
        ol{{list-style:none;padding:0}} label{{display:block;min-height:44px}}
        input{{width:24px;height:24px;vertical-align:middle}} small{{color:#A0A6AE}}
        :focus-visible{{outline:2px solid #6FB7FF;outline-offset:2px}}
        @media print{{body{{background:white;color:black;font-size:12pt}}
        main{{padding:0}}nav,button,select{{display:none}}small{{color:#333}}}}
        </style></head><body><main>{controls}
        <h1>Shot list</h1><p>{escape(project.title or project.idea)}</p>
        {'<p>Coverage is provisional: covered = at least 60% label overlap; maybe = partial overlap; missing = none.</p>' if selected else ''}
        <form method="post" action="{action}"><ol>{''.join(rows)}</ol>
        {'<p>No shots saved. Build the list from the script’s visual notes.</p>' if not rows else ''}
        {'<button>Save checkboxes</button>' if not printable and rows else ''}</form>
        </main></body></html>'''


def page(pid: str, shoot: str = ''):
    return HTMLResponse(page_html(_project(pid), _shoot(shoot)))


def build(pid: str):
    with store.lock_for(pid):
        project = _project(pid)
        project.shot_list = shot_list.build(project)
        store.save(project)
    return RedirectResponse(_url(pid), status_code=303)


def save_checks(pid: str, shoot: str = '', done: list[int] = Form(default=[])):
    with store.lock_for(pid):
        project = _project(pid)
        if any(i < 0 or i >= len(project.shot_list) for i in done):
            raise HTTPException(400, 'Unknown shot')
        for i, shot in enumerate(project.shot_list):
            shot.done = i in done
        store.save(project)
    return RedirectResponse(_url(pid, shoot), status_code=303)


def pdf(pid: str, shoot: str = ''):
    html = page_html(_project(pid), _shoot(shoot), printable=True)
    try:
        data = stage.print_pdf(html)
    except stage.StageError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(data, media_type='application/pdf',
                    headers={'Content-Disposition': 'attachment; filename="shot-list.pdf"'})

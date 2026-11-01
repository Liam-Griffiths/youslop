"""Small export dialog until the full footage logger screen exists."""
from html import escape

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse

from . import ffutil, footage, footage_export

router = APIRouter()


@router.get('/footage/export', response_class=HTMLResponse)
def export_dialog(shoot: str = ''):
    shoots = footage.list_shoots()
    selected = next((s for s in shoots if s.id == shoot), None)
    options = ''.join(f'<option value="{escape(s.id)}" '
                      f'{"selected" if s.id == shoot else ""}>{escape(s.path)}</option>' for s in shoots)
    clips = ''
    if selected:
        clips = ''.join(f'<p><label><input type="checkbox" name="clip_ids" '
                        f'value="{escape(c.id)}" checked> '
                        f'{escape(", ".join(c.labels) or c.id)} · {c.in_s:g}–{c.out_s:g} s'
                        '</label></p>' for c in selected.clips)
    return f'''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Export clips</title><link rel="stylesheet" href="/static/styles.css">
<body><main style="max-width:720px;margin:40px auto;padding:20px">
<a href="/">Back to Corkbored</a><h1>Export clips</h1>
<form method="get"><label for="shoot">Shoot</label>
<select name="shoot" id="shoot">{options}</select><button class="btn">Choose shoot</button></form>
<form method="post"><input type="hidden" name="shoot" value="{escape(shoot)}">
<fieldset><legend>Selected clips</legend>{clips or '<p>Choose a shoot with clips.</p>'}</fieldset>
<p><label for="output">Output folder</label><input type="text" id="output" name="output" required></p>
<p><label for="pattern">Naming pattern</label>
<input type="text" id="pattern" name="pattern" value="{{label}}-{{id}}" required>
<small>Use {{label}}, {{id}}, {{source}}. Existing files get a suffix.</small></p>
<p><label for="mode">Encoding</label><select name="mode" id="mode">
<option value="encode">Re-encode · frame precision</option>
<option value="copy">Stream copy · may differ by one GOP</option></select></p>
<p>Exports read original footage. JSON and CSV sidecars include labels and source timecodes.</p>
<button class="btn primary" {'disabled' if not clips else ''}>Export selected clips</button></form></main></body></html>'''


@router.post('/footage/export', response_class=HTMLResponse)
def export_selected(shoot: str = Form(...), clip_ids: list[str] = Form(...),
                    output: str = Form(...), pattern: str = Form('{label}-{id}'),
                    mode: str = Form('encode')):
    try:
        result = footage_export.export_clips(shoot, clip_ids, output, pattern=pattern, mode=mode)
    except (ValueError, OSError, ffutil.FFError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return HTMLResponse(f'<h1>Exported {len(result["clips"])} clips</h1>'
                        f'<p>{escape(str(output))}</p><a href="/footage/export">Export clips</a>')

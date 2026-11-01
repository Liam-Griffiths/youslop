"""Generate the T5.4 still comparison from a synthetic fixture.

From the repo root:
CORKBORED_DATA="$(mktemp -d)" PYTHONPATH=. .venv/bin/python docs/tickets/05-migrations/compare/thumbs/compare.py
Requires local Chromium and permission to bind the stage runner's loopback socket.
No video encoding, owner data, downloads or LLM calls.
"""
import os

if not os.environ.get('CORKBORED_DATA'):
    raise SystemExit('Set CORKBORED_DATA to a temporary directory before running.')

import argparse
import io
from pathlib import Path
from PIL import Image, ImageDraw
from app import scenes, stage, store, thumbs
from app.schema import Project

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pillow-only', action='store_true', help='Render the baseline without Chromium')
args = parser.parse_args()

p = Project(id='thumb-compare', idea='The hidden mechanism', title='The hidden mechanism')
p.thumb.headline = 'The hidden mechanism'
p.thumb.kicker = 'Inside the machine'
p.thumb.image = 'subject.png'
root = store.project_dir(p.id)
# Synthetic watch fixture: no owner project or external assets.
photo = Image.new('RGB', (1000, 900), '#526575')
d = ImageDraw.Draw(photo)
d.rectangle((400, 0, 600, 900), fill='#302b28')
d.ellipse((170, 120, 830, 780), fill='#cab88a', outline='#eee8da', width=25)
d.ellipse((215, 165, 785, 735), fill='#1c262c')
for x,y in [(500,210),(740,450),(500,690),(260,450)]:
    d.ellipse((x-16,y-16,x+16,y+16), fill='#cab88a')
d.line((500,270,500,450,640,510), fill='#eee8da', width=22)
photo.save(root / p.thumb.image)
items = []
p.style.thumb_engine = 'pillow'
for key in thumbs.TEMPLATE_KEYS:
    p.thumb.template = key
    thumbs.render_thumb(p, root, root / f'{key}-pillow.jpg')
    if args.pillow_only:
        continue
    src = thumbs._Source(root / p.thumb.image, [], thumbs._accent(p))
    ctx = thumbs.scene_context(p, root, src)
    digest, html, _ = scenes._prepare(root, f'thumbs/{key}.html', ctx, 1, (1280,720), 30)
    items.append(dict(clip=key, url_path=f'/scene/{{token}}/{html.name}', W=1280,H=720,t=0,size=(1280,720)))

out_dir = Path('docs/tickets/05-migrations/compare/thumbs')
baseline = Image.new('RGB', (400, 12 * 253 + 42), '#111216')
d = ImageDraw.Draw(baseline)
d.text((12,12), 'PILLOW - synthetic watch fixture', fill='white')
for i, key in enumerate(thumbs.TEMPLATE_KEYS):
    y = 42 + i * 253
    d.text((12,y), key, fill='white')
    with Image.open(root / f'{key}-pillow.jpg') as image:
        baseline.paste(image.resize((400,225)), (0,y+23))
baseline.save(out_dir / 'pillow-reference.jpg', quality=90)
print('12 Pillow JPEGs rendered via thumbs.render_thumb (style.thumb_engine=pillow)', flush=True)
if args.pillow_only:
    raise SystemExit(0)
captured = stage.capture_stills(items, root / 'scenes', project_root=str(root))
sheet = Image.new('RGB', (800, 12 * 253 + 42), '#111216')
d = ImageDraw.Draw(sheet)
d.text((12,12), 'PILLOW (left) / SCENE (right) - synthetic watch fixture', fill='white')
for i,key in enumerate(thumbs.TEMPLATE_KEYS):
    y = 42 + i*253
    d.text((12,y), key, fill='white')
    for x,img in [(0,Image.open(root/f'{key}-pillow.jpg')), (400,Image.open(io.BytesIO(captured[key])))]:
        assert img.size == (1280,720)
        sheet.paste(img.resize((400,225)), (x,y+23))
out = Path('docs/tickets/05-migrations/compare/thumbs/pillow-vs-scene.jpg')
sheet.save(out, quality=90)
print(f'{len(captured)} scene stills captured at 1280x720; comparison: {out}')

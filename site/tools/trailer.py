"""Cut the site trailer from a declarative edit list, with ffmpeg and Pillow.

Run from the repo root (after capture.py and with the sources in place):
    .venv/bin/python site/tools/trailer.py

Sources:
  site/media-src/<name>.png     app screenshots (capture.py, 2x)
  site/trailer-src/<file>       footage: archive film and 3D renders (not in git;
                                see CREDITS.md beside this script for each file)
Writes site/public/media/trailer-<hash>.webm (1080p), trailer-<hash>-720.webm,
trailer-<hash>-poster.webp, and records them in site/lib/media-manifest.json.

Every shot sits in the site's soft dark frame on paper, with a plain caption
lower left. No audio: music goes on later.
"""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parent
SHOTS, FOOTAGE = SITE / 'media-src', SITE / 'trailer-src'
OUT, MANIFEST = SITE / 'public' / 'media', SITE / 'lib' / 'media-manifest.json'
FONTS = REPO / 'resources' / 'fonts'
W, H, FPS = 1920, 1080, 30
PAPER, INK, DIM, FRAME, ACCENT = '#F4F2EE', '#0B0B0B', '#6B6862', '#0E0F11', '#E84A12'
BOX = (120, 96, 1800, 900)        # where a shot's frame sits on the paper

# (kind, source, seconds, label, caption, options)
EDIT = [
    ('card', 'title', 3.0, '', '', {}),
    ('still', 'research.png', 4.5, '1 · Plan', 'Research you can check', {}),
    ('still', 'script.png', 4.5, '2 · Script', 'A script you edit', {}),
    ('still', 'voice.png', 4.0, '3 · Voice', 'Your voice, or a local one', {}),
    ('still', 'visuals.png', 4.5, '4 · Visuals', 'A shot for every paragraph', {}),
    ('film', 'film-1895.webm', 3.5, 'Archive film', 'La Ciotat, 1895', {'ss': 1}),
    ('film', 'film-1921.webm', 3.5, 'Archive film', 'New York harbour, 1921', {'ss': 2}),
    ('film', 'film-1939.webm', 3.5, 'Archive film', "World's Fair, 1939", {'ss': 1}),
    ('film', 'film-1969.webm', 3.5, 'Archive film', 'Apollo 11, 1969', {'ss': 2}),
    ('still', 'blocks.png', 4.0, 'Blocks', 'Titles, charts and maps you fill in', {}),
    ('film', 'a380.mp4', 8.0, '3D scene', 'The shot planner frames the move', {'ss': 0.5, 'right': True}),
    ('film', 'abbey.mp4', 5.5, '3D scene', 'Blocks over a scan of Westminster Abbey', {'ss': 0.2, 'right': True}),
    ('still', 'timeline.png', 4.5, '5 · Edit', 'A timeline you can edit', {}),
    ('still', 'models.png', 4.0, 'Setup', 'Your choice of model', {}),
    ('card', 'end', 3.5, '', '', {}),
]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def display(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / 'Archivo-Variable.ttf'), size)
    axes = [a['name'].lower() if isinstance(a['name'], str) else a['name'].decode().lower()
            for a in f.get_variation_axes()]
    f.set_variation_by_axes([62 if 'width' in a else 800 for a in axes])
    return f


def frame_plate(shot: Image.Image | None = None) -> Image.Image:
    """Paper with a soft-shadowed dark frame; the shot, if given, fitted inside it."""
    plate = Image.new('RGB', (W, H), PAPER)
    x0, y0, x1, y1 = BOX
    shadow = Image.new('L', (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + 18, x1, y1 + 18), 22, fill=70)
    plate.paste(Image.new('RGB', (W, H), '#B9B2A6'), mask=shadow.filter(ImageFilter.GaussianBlur(28)))
    ImageDraw.Draw(plate).rounded_rectangle(BOX, 22, fill=FRAME)
    if shot is not None:
        inner = (x1 - x0 - 24, y1 - y0 - 24)
        fit = shot.copy()
        fit.thumbnail(inner, Image.LANCZOS)
        mask = Image.new('L', fit.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *fit.size), 12, fill=255)
        plate.paste(fit, ((x0 + x1 - fit.width) // 2, (y0 + y1 - fit.height) // 2), mask)
    return plate


def caption(label: str, text: str, right: bool = False) -> Image.Image:
    """A transparent overlay: mono label and one line, lower left, on an ink pill."""
    over = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    if not text:
        return over
    d = ImageDraw.Draw(over)
    mono, ui = font('JetBrainsMono-Regular.ttf', 22), font('Inter-Bold.ttf', 40)
    pad, x, y = 26, BOX[0] + 40, BOX[3] - 150
    w = max(d.textlength(label.upper(), font=mono), d.textlength(text, font=ui)) + 2 * pad
    if right:  # Clear of a shot's own lower-left block.
        x = BOX[2] - 40 - w
    d.rounded_rectangle((x, y, x + w, y + 112), 14, fill=(11, 11, 11, 225))
    d.text((x + pad, y + 18), label.upper(), font=mono, fill=(244, 242, 238, 170))
    d.text((x + pad, y + 50), text, font=ui, fill=(244, 242, 238, 255))
    return over


def card(which: str) -> Image.Image:
    im = Image.new('RGB', (W, H), PAPER)
    d = ImageDraw.Draw(im)
    big = display(260)
    d.text((W // 2, H // 2 - 40), 'CORKBORED', font=big, fill=INK, anchor='mm')
    line = ('Turn an idea or a script into a researched, narrated video.' if which == 'title'
            else 'corkbored.com')
    d.text((W // 2, H // 2 + 120), line, font=font('Inter-Medium.ttf', 40),
           fill=DIM if which == 'title' else ACCENT, anchor='mm')
    return im


def run(*args: str) -> None:
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args], check=True)


def segment(i: int, kind: str, src: str, secs: float, label: str, text: str, opts: dict, tmp: Path) -> Path:
    out = tmp / f'seg{i:02d}.mp4'
    fade = f'fade=t=in:st=0:d=0.3:color={PAPER},fade=t=out:st={secs - 0.3}:d=0.3:color={PAPER}'
    cap = tmp / f'cap{i:02d}.png'
    caption(label, text, opts.get('right', False)).save(cap)
    if kind in ('card', 'still'):
        plate = card(src) if kind == 'card' else frame_plate(Image.open(SHOTS / src).convert('RGB'))
        big = tmp / f'plate{i:02d}.png'
        plate.resize((W * 2, H * 2), Image.LANCZOS).save(big)
        frames = round(secs * FPS)
        # A slow push towards the centre: 1.00 to 1.04 over the shot.
        zoom = f"zoompan=z='1+0.04*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}"
        run('-loop', '1', '-i', str(big), '-i', str(cap), '-filter_complex',
            f'[0:v]{zoom}[v];[v][1:v]overlay=0:0,{fade},format=yuv420p', '-t', f'{secs}',
            '-c:v', 'libx264', '-crf', '14', '-preset', 'medium', '-r', str(FPS), str(out))
    else:
        plate = tmp / f'plate{i:02d}.png'
        frame_plate().save(plate)
        x0, y0, x1, y1 = BOX
        iw, ih = x1 - x0 - 24, y1 - y0 - 24
        run('-loop', '1', '-i', str(plate), '-ss', str(opts.get('ss', 0)), '-i', str(FOOTAGE / src),
            '-i', str(cap), '-filter_complex',
            f'[1:v]fps={FPS},scale={iw}:{ih}:force_original_aspect_ratio=decrease[f];'
            f'[0:v][f]overlay={(x0 + x1) // 2}-w/2:{(y0 + y1) // 2}-h/2:shortest=1[b];[b][2:v]overlay=0:0,{fade},format=yuv420p',
            '-t', f'{secs}', '-an', '-c:v', 'libx264', '-crf', '14', '-preset', 'medium', '-r', str(FPS), str(out))
    return out


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix='corkbored-trailer-'))
    try:
        parts = [segment(i, *row, tmp) for i, row in enumerate(EDIT)]
        listing = tmp / 'list.txt'
        listing.write_text(''.join(f"file '{p}'\n" for p in parts))
        master = tmp / 'master.mp4'
        run('-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', str(master))
        digest = hashlib.sha256(master.read_bytes()).hexdigest()[:8]
        OUT.mkdir(parents=True, exist_ok=True)
        for old in OUT.glob('trailer-*'):
            old.unlink()
        files = {}
        for name, scale, crf in (('', None, 34), ('-720', '1280:720', 33)):
            dest = OUT / f'trailer-{digest}{name}.webm'
            vf = ['-vf', f'scale={scale}'] if scale else []
            common = ['-i', str(master), *vf, '-c:v', 'libvpx-vp9', '-crf', str(crf), '-b:v', '0',
                      '-row-mt', '1', '-tile-columns', '2', '-g', '240', '-an']
            log = str(tmp / f'pass{name}')
            run(*common, '-pass', '1', '-passlogfile', log, '-f', 'webm', '/dev/null')
            run(*common, '-pass', '2', '-passlogfile', log, str(dest))
            files['src' if not name else 'mobile'] = dest.name
        poster = OUT / f'trailer-{digest}-poster.webp'
        still = tmp / 'poster.png'
        run('-ss', '9', '-i', str(master), '-frames:v', '1', '-vf', 'scale=1280:-2', str(still))
        Image.open(still).save(poster, 'WEBP', quality=72, method=6)
        files['poster'] = poster.name
        manifest = json.loads(MANIFEST.read_text())
        seconds = sum(row[2] for row in EDIT)
        manifest['_trailer'] = {**files, 'hash': digest, 'seconds': seconds}
        MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
        for f in files.values():
            print(f, f'{(OUT / f).stat().st_size / 1024:.0f} KB')
        print(f'{seconds:.1f} s')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()

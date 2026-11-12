"""Pre-build every site image at fixed widths, so nothing uses an image optimizer.

Run from the repo root with the app's virtual environment (Pillow only):
    .venv/bin/python site/tools/build_images.py

Reads site/media-src/*.png and writes, for each image and each width that
doesn't upscale it, site/public/media/<name>-<hash>-<width>.avif and .webp.
The short content hash makes every file safe to cache as immutable.
site/lib/media-manifest.json records the widths, the intrinsic size and a
tiny blurred placeholder for each image.
"""
import base64
import hashlib
import io
import json
from pathlib import Path

from PIL import Image

SITE = Path(__file__).resolve().parents[1]
SRC = SITE / 'media-src'
OUT = SITE / 'public' / 'media'
MANIFEST = SITE / 'lib' / 'media-manifest.json'
WIDTHS = (480, 768, 1080, 1440, 1920)
AVIF_QUALITY = 44
WEBP_QUALITY = 78


def placeholder(im: Image.Image) -> str:
    small = im.copy()
    small.thumbnail((24, 24))
    buf = io.BytesIO()
    small.save(buf, 'WEBP', quality=40)
    return 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()


def build(path: Path) -> dict:
    im = Image.open(path).convert('RGB')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    widths = [w for w in WIDTHS if w <= im.width] or [im.width]
    if im.width not in widths and im.width < WIDTHS[-1]:
        widths.append(im.width)  # The largest file is the original size, never upscaled.
    widths = sorted(set(widths))
    for w in widths:
        h = round(im.height * w / im.width)
        frame = im if w == im.width else im.resize((w, h), Image.LANCZOS)
        stem = OUT / f'{path.stem}-{digest}-{w}'
        frame.save(stem.with_suffix('.avif'), 'AVIF', quality=AVIF_QUALITY, speed=4)
        frame.save(stem.with_suffix('.webp'), 'WEBP', quality=WEBP_QUALITY, method=6)
    return {'hash': digest, 'width': im.width, 'height': im.height,
            'widths': widths, 'blur': placeholder(im)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {p.stem: build(p) for p in sorted(SRC.glob('*.png'))}
    live = {f'{name}-{entry["hash"]}-{w}{ext}' for name, entry in manifest.items()
            for w in entry['widths'] for ext in ('.avif', '.webp')}
    for stale in OUT.glob('*'):
        if stale.suffix in ('.avif', '.webp') and stale.name not in live:
            stale.unlink()  # Only generated site images live here.
    MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    total = sum((OUT / name).stat().st_size for name in live)
    print(f'{len(manifest)} images, {len(live)} files, {total / 1024:.0f} KB')


if __name__ == '__main__':
    main()

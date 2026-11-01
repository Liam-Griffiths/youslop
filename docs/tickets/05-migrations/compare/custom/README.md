# T5.2c still comparisons (reviewer)

Chromium is unavailable in the implementer's sandbox. Visual acceptance is
pending. `styles.json` contains three saved-style fixtures; no owner styles
were available at the legacy or Corkbored data locations. The local image
below is synthetic, so this kit needs no archives or model calls.

On a machine with system Chromium, capture only the three settled scenes:

```sh
CORKBORED_DATA=$(mktemp -d) .venv/bin/python - <<'PY'
import json
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from app import custom_slide
kit = Path('docs/tickets/05-migrations/compare/custom')
with tempfile.TemporaryDirectory(prefix='custom-compare-') as tmp:
    root = Path(tmp)
    photo = Image.new('RGB', (600, 400), '#486b80')
    ImageDraw.Draw(photo).ellipse((100, 20, 500, 380), fill='#e8c36a')
    photo.save(root / 'photo.png')
    for style in json.loads((kit / 'styles.json').read_text()):
        opts = dict(media_root=root, grain=0)
        pillow = custom_slide.render_still(style['spec'], engine='pillow', **opts)
        scene = custom_slide.render_still(style['spec'], engine='scene', **opts)
        name = style['name']
        pillow.save(kit / f'{name}-pillow.png')
        scene.save(kit / f'{name}-scene.png')
        Image.blend(pillow, scene, .5).save(kit / f'{name}-overlay.png')
PY
```

Review text baselines/wrapping, positions, opacity, image cover/contain and
shape outlines. The scene reuses Pillow's fitted font size and line breaks,
with per-line SVG baselines computed from Pillow's glyph bounds (review
round 2 removes CSS half-leading). Browser font rasterization and CSS
outlines may differ slightly. In a paused
scene, check grouped and sparse reveal orders, `reveal=all`, static images,
and the six entrances. Video capture uses one transparent plate per element;
ffmpeg applies the same quadratic reveal and pixel travel as Pillow. The
HTML presets also allow seeking entrances directly. Set the project's
`style.custom_engine` to `pillow` to compare the original rendering path.
Standalone `candidate` and `render_still` keep their Pillow default and accept
`engine='scene'`; existing editor previews and style thumbnails keep Pillow.

# T5.2b still comparisons (reviewer)

Chromium is unavailable in the implementer's sandbox. No scene screenshots
or visual approval are claimed. Fixtures cover boxes, branching arrows and
circular nodes; the flow also covers dashed edges and arrow labels.

On a machine with system Chromium, capture only these three finished stills:

```sh
CORKBORED_DATA=$(mktemp -d) .venv/bin/python - <<'PY'
import json
from pathlib import Path
from PIL import Image
from app import diagram
root = Path('docs/tickets/05-migrations/compare/diagram')
for spec in json.loads((root / 'specs.json').read_text()):
    kind = spec['kind']
    pillow = diagram.render_still(spec, grain=0, engine='pillow')
    scene = diagram.render_still(spec, grain=0, engine='scene')
    pillow.save(root / f'{kind}-pillow.png')
    scene.save(root / f'{kind}-scene.png')
    Image.blend(pillow, scene, .5).save(root / f'{kind}-overlay.png')
PY
```

Check matching node positions and wrapped text baselines in each overlay.
SVG boxes use native rectangles with a fixed low-scale displacement filter;
Pillow retains four independently bowed, overshooting corner strokes.
Circular outlines, arrows, dashes and underlines retain Pillow's point lists.
Check reveal order and path draw-on by seeking the paused scene timeline in
the reviewer environment. Motion captures contain only each beat's arrival
and settled endpoint; ffmpeg clones that endpoint for every remaining hold.

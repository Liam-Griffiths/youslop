"""Local sample paragraphs, in scratch caches; never use an owner's project."""
import hashlib
import json
import os
import threading

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image

from . import board, cuts, custom_slide, ffutil, paths, render, slide_styles, stage, style_kits
from .block_overlays import run_graph
from .config import STATIC_DIR
from .schema import Project, Slide, Style

_LOCK = threading.Lock()
SAMPLE = STATIC_DIR / 'blocks/split_comparison/sample.png'


def preview(ident, mode):
    kit = style_kits.get(ident)
    if mode not in ('poster', 'motion'):
        raise HTTPException(404, 'Unknown style preview')
    # UI snapshots explicitly disable all captures/movies.
    if os.environ.get('CORKBORED_BLOCK_POSTERS') == 'off':
        return FileResponse(SAMPLE) if mode == 'poster' else Response(status_code=204)
    saved = slide_styles.get(kit['default_kind'][7:]) if kit['default_kind'].startswith('custom:') else None
    key = hashlib.sha256(json.dumps([3, kit, saved.to_dict() if saved else None], sort_keys=True).encode()).hexdigest()
    root = paths.data_root() / '.cache/style-previews' / key
    root.mkdir(parents=True, exist_ok=True)
    out = root / ('poster.jpg' if mode == 'poster' else 'motion.webm')
    with _LOCK:
        if not out.exists():
            # Absolute internal id keeps renderer helpers entirely inside the scratch root.
            p = Project(id=str(root.resolve()), idea='How a city moves', title='How a city moves', style=Style())
            style_kits.apply_kit(p, kit)
            s = Slide(id='sample', title='How a city moves', narration='Every morning, 42,000 people cross the city. One small change can save them time.',
                      board_lead='How a city moves', board_points=['42,000 journeys', 'One small change'],
                      chosen_id='sample', candidates=[dict(id='sample', local_path=str(SAMPLE), kind='image')])
            p.slides = [s]
            temp = root / ('pending.jpg' if mode == 'poster' else 'pending.webm')
            if p.style.format == 'stage':
                html = root / 'sample.html'
                html.write_text('''<html><body style="margin:0;background:#111820"><p style="position:absolute;top:12px;left:20px;color:white;font:18px sans-serif">How a city moves</p><script type="module">
import * as T from '/static/vendor/three/three.module.js';
const r=new T.WebGLRenderer({antialias:true});r.setSize(480,270);document.body.append(r.domElement);
const scene=new T.Scene(), camera=new T.PerspectiveCamera(40,480/270,.1,100);camera.position.set(4,3,5);camera.lookAt(0,0,0);
scene.add(new T.HemisphereLight(0xffffff,0x223344,3));const light=new T.DirectionalLight(0xffffff,4);light.position.set(3,5,2);scene.add(light);
const model=new T.Mesh(new T.TorusKnotGeometry(1,.3,96,12),new T.MeshStandardMaterial({color:ACCENT,roughness:.35}));scene.add(model);
window.__seek=()=>r.render(scene,camera);window.__seek();window.__ready=true;
</script></body></html>'''.replace('ACCENT', json.dumps(p.style.accent)))
                if not (root / 'stage.png').exists():
                    (root / 'stage.png').write_bytes(stage.capture_one(html,480,270,0,(480,270),assets_root=root))
                inputs, graph, last = ['-loop','1','-i',str(root / 'stage.png')], "[0:v]zoompan=z='1+on*.001':d=1:s=480x270:fps=15[out]", '[out]'
            elif mode == 'poster' and (cuts.is_cut(p.style.format) or p.style.format == 'board' or saved):
                png = root / 'still.png'
                if saved:
                    custom_slide.render_still(saved.spec).save(png)
                elif p.style.format == 'board':
                    board.still(p,s,png,image=SAMPLE)
                else:
                    cuts.still(p,s,png,image_for=lambda _: SAMPLE,cache_dir=root)
                with Image.open(png) as image:
                    image.convert('RGB').resize((480,270)).save(temp)
                os.replace(temp,out)
                return FileResponse(out)
            elif mode == 'motion':
                render._render_segment(p,[(s,4)],4,0,temp,size=(480,270),fps=15,threads=1)
                os.replace(temp,out)
                return FileResponse(out)
            else:
                inputs, graph, last = render._segment_graph(p,[(s,4)],4,'creep_in',size=(480,270),fps=15)
            script = root / 'preview.ffgraph'
            script.write_text(graph)
            run_graph([*inputs,'-filter_complex_script',str(script),'-map',last,
                        *(['-ss','2','-frames:v','1'] if mode == 'poster' else ['-t','4','-r','15',*ffutil.video_args(temp)]),
                        '-an',str(temp)],threads=1)
            os.replace(temp,out)
    return FileResponse(out)

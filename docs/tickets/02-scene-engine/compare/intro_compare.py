"""Quarter-size stills only; run at repo root. No video, audio or LLM calls."""
import io
from itertools import islice
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='corkbored-intro-review-') as data:
        os.environ['CORKBORED_DATA'] = os.environ['YOUSLOP_DATA'] = data
        from PIL import Image, ImageDraw
        from app import channels, intro, scenes
        from app.schema import Channel

        directory = Path(__file__).parent
        channel = Channel(id='intro-review', name='The Evidence Room',
                          tagline='Stories behind the record')
        title = 'How an archive becomes a story'
        channel.intro.template = 'dossier'

        def still(out, frames, what='the intro'):
            # FPS=1 preserves t=2 while generating only three Pillow frames.
            next(islice(frames, 2, None)).resize((480, 270)).save(out)

        with patch.object(intro, 'FPS', 1), patch.object(intro, '_encode', still):
            intro.render_intro(channel, title, directory / 'intro_pillow.png')
        print('Pillow dossier: intro_pillow.png (480x270, t=2)')
        if '--pillow-only' in sys.argv:
            return

        portrait = Image.new('RGB', (500, 720), '#6fb7ff')
        draw = ImageDraw.Draw(portrait)
        draw.ellipse((140, 90, 360, 310), fill='#f3ede3')
        draw.ellipse((50, 330, 450, 900), fill='#1b1a17')
        portrait.save(channels.channel_dir(channel.id) / 'intro/portrait.png')
        channel.intro.images = ['intro/portrait.png']
        for name in ('solo', 'dossier', 'folio', 'portrait'):
            ctx = scenes.context_base(channel=channel)
            ctx.update(scenes.intro_context(channel), card=channel.intro.to_dict())
            ctx['vars']['title'] = title
            template = f'cards/intro_{name}.html'
            png = scenes.capture(Path(data), template, ctx, t=2, size=(480, 270))
            assert Image.open(io.BytesIO(png)).size == (480, 270)
            held = scenes.capture(Path(data), template, ctx,
                                  t=channel.frame.arrive_s + .1, size=(480, 270))
            assert png == held, f'{name}: slate moved during the hold'
            out = directory / ('intro_scene.png' if name == 'dossier' else f'intro_{name}.png')
            out.write_bytes(png)
            print(f'{out.name}: 480x270; stationary after arrival')


if __name__ == '__main__':
    main()

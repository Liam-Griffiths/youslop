"""Two quarter-size stills only. Run from the repo root; never renders a video."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='corkbored-outro-review-') as data:
        os.environ['CORKBORED_DATA'] = os.environ['YOUSLOP_DATA'] = data
        from app import outro, scenes
        from app.schema import Channel, OutroSpec

        ctx = json.loads((ROOT / 'tests/fixtures/ctx_channel.json').read_text())
        channel = Channel(id='cpreview', name=ctx['vars']['channel_name'],
                          tagline=ctx['vars']['tagline'])
        channel.outro = OutroSpec(**ctx['card'])
        directory = Path(__file__).parent

        def still(path, ground, pieces, duration, live=None):
            frame = ground.copy()
            for piece in pieces:
                frame.paste(piece.layer, piece.pos, piece.layer)
            if live:
                for pos, patch in live(2.0):
                    frame.paste(patch, pos, patch)
            frame.convert('RGB').resize((480, 270)).save(path)
            return duration

        # All Pillow pieces are settled at t=2 for this fixture.
        outro._play = still
        channel.outro.template = 'twoup'
        outro.render_outro(channel, ctx['vars']['title'], directory / 'outro_pillow.png')
        print(directory / 'outro_pillow.png')
        if '--pillow-only' not in sys.argv:
            png = scenes.capture(Path(data), 'cards/outro_twoup.html', ctx,
                                 t=2.0, size=(480, 270))
            (directory / 'outro_scene.png').write_bytes(png)
            print(directory / 'outro_scene.png')


if __name__ == '__main__':
    main()

"""HEAVY, opt-in: encode 90 scene frames at full and quarter size. No LLMs."""
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="corkbored-scene-bench-") as tmp:
        os.environ["CORKBORED_DATA"] = tmp
        from app import stage

        for size in ((1920, 1080), (480, 270)):
            start = time.monotonic()
            stage.render_scene([dict(clip="static", url_path="/static/scene/_test/static.html",
                                    W=1920, H=1080, size=size, fps=30, frames=90)], Path(tmp))
            elapsed = time.monotonic() - start
            print(f"{size[0]}x{size[1]}: 90 frames in {elapsed:.2f} s = {90 / elapsed:.1f} fps")


if __name__ == "__main__":
    main()

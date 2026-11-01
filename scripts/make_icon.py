"""Generate platform icons from the approved SVGs using system Chromium.

Run: .venv/bin/python scripts/make_icon.py
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("brand_build", ROOT / "docs/brand/src/build.py")
_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-png", action="store_true",
                        help="use checked-in approved PNGs when Chromium cannot run")
    args = parser.parse_args()
    out_dir = ROOT / "resources"
    iconset = out_dir / "icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        images = {}
        for name in ("icon", "mark"):
            svg = work / f"{name}.svg"
            svg.write_bytes((ROOT / f"docs/brand/src/corkbored-{name}.svg" if name == "icon"
                             else ROOT / "docs/brand/corkbored-mark.svg").read_bytes())
            png = work / f"{name}.png"
            if args.from_png:
                png = ROOT / "docs/brand" / ("corkbored-icon-1024.png" if name == "icon"
                                            else "corkbored-mark-64.png")
            else:
                _build.render(svg, png, 1024, 1024)
            with Image.open(png) as image:
                images[name] = image.convert("RGBA")

        def sized(size: int) -> Image.Image:
            return images["mark" if size <= 32 else "icon"].resize(
                (size, size), Image.Resampling.LANCZOS)

        images["icon"].save(out_dir / "icon_1024.png")
        for size in (16, 32, 64, 128, 256, 512, 1024):
            sized(size).save(iconset / f"icon_{size}x{size}.png")
            if size <= 512:
                sized(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
        images["icon"].save(out_dir / "icon.icns")
        sizes = (16, 32, 48, 256)
        sized(256).save(out_dir / "icon.ico", sizes=[(s, s) for s in sizes],
                        append_images=[sized(s) for s in sizes[:-1]])
    print("wrote resources/icon_1024.png, resources/icon.iconset/*.png, resources/icon.icns, resources/icon.ico")


if __name__ == "__main__":
    main()

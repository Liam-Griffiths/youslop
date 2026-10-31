"""Generate the temporary C app icon using the bundled Inter font.

T6.2 replaces this placeholder with the final mark. Keep the current dark
tile and accent colour from static/styles.css.

Run: .venv/bin/python scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BG = "#0d0e12"
ACCENT = "#e8c36a"


def draw_master(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = int(size * 0.06)
    radius = int(size * 0.225)
    draw.rounded_rectangle([pad, pad, size - pad, size - pad],
                           radius=radius, fill=BG)
    font = ImageFont.truetype(str(ROOT / "resources/fonts/Inter-Bold.ttf"),
                              int(size * 0.72))
    left, top, right, bottom = draw.textbbox((0, 0), "C", font=font)
    draw.text(((size - (right - left)) / 2 - left,
               (size - (bottom - top)) / 2 - top),
              "C", font=font, fill=ACCENT)
    return img


def main() -> None:
    out_dir = ROOT / "resources"
    out_dir.mkdir(exist_ok=True)
    master = draw_master()
    master.save(out_dir / "icon_1024.png")
    iconset = out_dir / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512, 1024):
        master.resize((size, size), Image.Resampling.LANCZOS).save(
            iconset / f"icon_{size}x{size}.png")
        if size <= 512:
            master.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(
                iconset / f"icon_{size}x{size}@2x.png")
    master.save(out_dir / "icon.icns")
    print("wrote resources/icon_1024.png, resources/icon.iconset/*.png, resources/icon.icns")


if __name__ == "__main__":
    main()

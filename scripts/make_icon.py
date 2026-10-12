"""Generates resources/icon.icns (macOS) from the app's own header mark — the
🪣 bucket emoji in static/index.html's `.brand` ("Fresh AI slop, daily") — so
the packaged app's icon is the same mark as the web header instead of
PyInstaller's default.

Matches the in-app palette (static/styles.css): dark tile (#0d0e12).

Run: .venv/bin/python scripts/make_icon.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BG = "#0d0e12"
EMOJI = "\U0001FAA3"  # 🪣

EMOJI_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
]


# Apple Color Emoji ships only a handful of fixed strike sizes; any other
# size PIL/FreeType is asked for raises "invalid pixel size". 160 is its
# largest strike, so render there and upscale the bitmap to the target size.
EMOJI_STRIKE = 160


def _emoji_font() -> ImageFont.FreeTypeFont:
    for p in EMOJI_FONT_CANDIDATES:
        if p.exists():
            return ImageFont.truetype(str(p), EMOJI_STRIKE)
    raise SystemExit("no colour emoji font found (expected on macOS)")


def draw_master(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = int(size * 0.06)
    radius = int(size * 0.225)
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius, fill=BG)

    font = _emoji_font()
    emoji_img = Image.new("RGBA", (EMOJI_STRIKE * 2, EMOJI_STRIKE * 2), (0, 0, 0, 0))
    ed = ImageDraw.Draw(emoji_img)
    bbox = ed.textbbox((0, 0), EMOJI, font=font, embedded_color=True)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    ed.text((-bbox[0], -bbox[1]), EMOJI, font=font, embedded_color=True)
    emoji_img = emoji_img.crop((0, 0, tw, th))

    target_w = int(size * 0.62)
    scale = target_w / tw
    emoji_img = emoji_img.resize((target_w, int(th * scale)), Image.LANCZOS)

    ex = (size - emoji_img.width) // 2
    ey = (size - emoji_img.height) // 2
    img.alpha_composite(emoji_img, (ex, ey))

    return img


def main() -> None:
    out_dir = ROOT / "resources"
    out_dir.mkdir(exist_ok=True)
    master = draw_master(1024)
    master.save(out_dir / "icon_1024.png")

    if sys.platform == "darwin":
        iconset = out_dir / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        sizes = [16, 32, 64, 128, 256, 512, 1024]
        for s in sizes:
            master.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            if s <= 512:
                master.resize((s * 2, s * 2), Image.LANCZOS).save(
                    iconset / f"icon_{s}x{s}@2x.png"
                )
        icns_path = out_dir / "icon.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
            check=True,
        )
        print(f"wrote {icns_path}")
    else:
        print(f"wrote {out_dir / 'icon_1024.png'} (run iconutil on macOS for .icns)")


if __name__ == "__main__":
    main()

"""Build the Corkbored logo set from one drawing.

    python3 docs/brand/src/build.py

Writes SVGs and PNGs into docs/brand/. The icon (corkbored-icon.svg) is
hand-edited; everything else is generated here so the note, play mark and pin
are the same shapes at every size. PNGs are rendered with the system Chromium
(no Node). The wordmark font (Archivo Black, OFL, resources/fonts) is embedded
as base64 so the SVGs render the same on GitHub and in the app.
"""
from __future__ import annotations

import base64
import pathlib
import shutil
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
BRAND = HERE.parent
ROOT = BRAND.parent.parent
FONT = base64.b64encode((ROOT / "resources/fonts/ArchivoBlack-Regular.ttf").read_bytes()).decode()
MARKER = base64.b64encode((ROOT / "resources/fonts/PermanentMarker-Regular.ttf").read_bytes()).decode()

INK = "#1B1B1F"
PAPER = "#F4EFE6"
ACCENT = "#FF5A1F"
CORK = "#C58C52"

FONTS = f"""<style>
@font-face {{ font-family: 'CB Wordmark'; src: url(data:font/ttf;base64,{FONT}) format('truetype'); }}
@font-face {{ font-family: 'CB Marker'; src: url(data:font/ttf;base64,{MARKER}) format('truetype'); }}
</style>"""

# Shared defs. Granule filter as in the icon; the flat mark never uses it.
DEFS = f"""
<filter id="grain" x="0" y="0" width="100%" height="100%">
  <feTurbulence type="fractalNoise" baseFrequency="0.16" numOctaves="3" seed="7" result="n"/>
  <feColorMatrix in="n" type="matrix" values="0 0 0 0 0.40  0 0 0 0 0.23  0 0 0 0 0.10  0 0 0 -6 3.2" result="dark"/>
  <feTurbulence type="fractalNoise" baseFrequency="0.22" numOctaves="2" seed="21" result="m"/>
  <feColorMatrix in="m" type="matrix" values="0 0 0 0 0.86  0 0 0 0 0.64  0 0 0 0 0.40  0 0 0 7 -4.55" result="light"/>
  <feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="1" seed="5" result="f"/>
  <feColorMatrix in="f" type="matrix" values="0 0 0 0 0.30  0 0 0 0 0.16  0 0 0 0 0.06  0 0 0 -3 1.75" result="fine"/>
  <feTurbulence type="fractalNoise" baseFrequency="0.025" numOctaves="2" seed="3" result="b"/>
  <feColorMatrix in="b" type="matrix" values="0 0 0 0 0.52  0 0 0 0 0.31  0 0 0 0 0.14  0 0 0 2 -0.85" result="blot"/>
  <feMerge><feMergeNode in="SourceGraphic"/><feMergeNode in="blot"/><feMergeNode in="fine"/><feMergeNode in="dark"/><feMergeNode in="light"/></feMerge>
</filter>
<linearGradient id="note" x1="0" y1="0" x2="0.35" y2="1">
  <stop offset="0" stop-color="#FFE987"/><stop offset="1" stop-color="#FFD43B"/>
</linearGradient>
<linearGradient id="curl" x1="1" y1="1" x2="0.6" y2="0.6">
  <stop offset="0" stop-color="#C79A12"/><stop offset="1" stop-color="#FFE071"/>
</linearGradient>
<radialGradient id="pinhead" cx="38%" cy="32%" r="70%">
  <stop offset="0" stop-color="#FFB08A"/><stop offset="0.35" stop-color="{ACCENT}"/><stop offset="1" stop-color="#B8320A"/>
</radialGradient>
<filter id="lift" x="-20%" y="-20%" width="140%" height="150%">
  <feDropShadow dx="0.6" dy="1.4" stdDeviation="1" flood-color="#2a1404" flood-opacity="0.5"/>
</filter>
"""


def note(x: float, y: float, s: float, angle: float = -5, *, shadow: bool = True) -> str:
    """The pinned note with its play mark, on a 64-unit design scaled by s/64."""
    k = s / 64
    lift = ' filter="url(#lift)"' if shadow else ""
    return f"""
<g transform="translate({x} {y}) scale({k})">
  <g transform="rotate({angle} 32 34)"{lift}>
    <path d="M14.5 16.4 H49.5 V44.25 L44.75 50.1 H14.5 Z" fill="url(#note)"/>
    <path d="M49.5 44.25 L44.75 50.1 L45.5 45 Z" fill="url(#curl)"/>
    <path d="M26.9 24.9 L26.9 41.6 L40 33.25 Z" fill="{INK}" stroke="{INK}" stroke-width="2.1" stroke-linejoin="round"/>
  </g>
  <ellipse cx="33.1" cy="18.75" rx="2.75" ry="1.1" fill="#2a1404" opacity="0.35" transform="translate(1 1.1)"/>
  <circle cx="32" cy="16.75" r="3.6" fill="url(#pinhead)"/>
  <ellipse cx="30.9" cy="15.5" rx="1.1" ry="0.7" fill="#fff" opacity="0.55" transform="rotate(-30 30.9 15.5)"/>
</g>"""


def flat_mark(size: int = 64) -> str:
    """Favicon / header mark: a cork chip with the note, no texture."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}">
<title>Corkbored</title><defs>{DEFS}</defs>
<rect width="64" height="64" rx="14" fill="{CORK}"/>
<g fill="#8F5A2B" opacity="0.55">
  <circle cx="9" cy="12" r="1.1"/><circle cx="54" cy="9" r="0.9"/><circle cx="57" cy="52" r="1.2"/>
  <circle cx="7" cy="49" r="0.9"/><circle cx="20" cy="58" r="0.8"/><circle cx="45" cy="58.5" r="1"/>
</g>
{note(-3.2, -3.4, 70.4, shadow=True)}
</svg>"""


def lockup(text_fill: str, *, title: str = "Corkbored") -> str:
    """Mark + wordmark, transparent background. 560 x 128.

    The chip is flat cork (a few granules, no noise filter): the textured cork
    of the icon turns to static below about 200 px.
    """
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 128" width="560" height="128">
<title>{title}</title>{FONTS}<defs>{DEFS}</defs>
<rect x="4" y="4" width="120" height="120" rx="27" fill="{CORK}"/>
<g fill="#8F5A2B" opacity="0.55">
  <circle cx="20" cy="26" r="2"/><circle cx="105" cy="20" r="1.7"/><circle cx="110" cy="102" r="2.2"/>
  <circle cx="16" cy="96" r="1.7"/><circle cx="40" cy="113" r="1.5"/><circle cx="88" cy="114" r="1.9"/>
</g>
{note(-2, -3, 132)}
<text x="146" y="88" font-family="'CB Wordmark'" font-size="70" letter-spacing="-1.5" fill="{text_fill}">Corkbored</text>
</svg>"""


def header() -> str:
    """App header: 28 px mark + wordmark for the dark UI bar. 200 x 40."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 40" width="200" height="40">
<title>Corkbored</title>{FONTS}<defs>{DEFS}</defs>
<rect x="4" y="4" width="32" height="32" rx="7.5" fill="{CORK}"/>
{note(2.4, 2.2, 36)}
<text x="46" y="28.5" font-family="'CB Wordmark'" font-size="21" letter-spacing="-0.4" fill="{PAPER}">Corkbored</text>
</svg>"""


def banner() -> str:
    """README / social hero, 1280 x 640: a cork board, the note, an index card."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" width="1280" height="640">
<title>Corkbored: idea in, episode out</title>{FONTS}<defs>{DEFS}
<radialGradient id="vig" cx="50%" cy="45%" r="75%">
  <stop offset="55%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#2a1404" stop-opacity="0.5"/>
</radialGradient>
<filter id="cardlift" x="-10%" y="-10%" width="125%" height="135%">
  <feDropShadow dx="6" dy="14" stdDeviation="10" flood-color="#2a1404" flood-opacity="0.5"/>
</filter>
</defs>
<rect width="1280" height="640" fill="{CORK}" filter="url(#grain)"/>
<rect width="1280" height="640" fill="url(#vig)"/>
<!-- Index card with the wordmark, pinned. -->
<g transform="rotate(2 820 320)" filter="url(#cardlift)">
  <rect x="470" y="170" width="700" height="300" fill="#FBF8F1"/>
  <g stroke="#9FC3E6" stroke-width="2"><line x1="470" y1="262" x2="1170" y2="262" stroke="#E7A2A2"/>
  <line x1="470" y1="314" x2="1170" y2="314"/><line x1="470" y1="366" x2="1170" y2="366"/><line x1="470" y1="418" x2="1170" y2="418"/></g>
  <text x="510" y="246" font-family="'CB Wordmark'" font-size="78" letter-spacing="-2" fill="{INK}">Corkbored</text>
  <text x="514" y="352" font-family="'CB Marker'" font-size="44" fill="{INK}">Idea in.</text>
  <text x="514" y="404" font-family="'CB Marker'" font-size="44" fill="{ACCENT}">Episode out.</text>
</g>
<g transform="translate(822 152)">
  <ellipse cx="18" cy="22" rx="30" ry="12" fill="#2a1404" opacity="0.35"/>
  <circle cx="0" cy="0" r="30" fill="url(#pinhead)"/>
  <ellipse cx="-9" cy="-10" rx="9" ry="6" fill="#fff" opacity="0.55" transform="rotate(-30 -9 -10)"/>
</g>
{note(90, 120, 400, angle=-6)}
</svg>"""


def cork_board(w: int, h: int) -> str:
    """Plain cork, for scene backgrounds (rendered once to JPEG)."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
<defs>{DEFS}
<radialGradient id="vig" cx="50%" cy="45%" r="75%">
  <stop offset="55%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#2a1404" stop-opacity="0.5"/>
</radialGradient></defs>
<rect width="{w}" height="{h}" fill="{CORK}" filter="url(#grain)"/>
<rect width="{w}" height="{h}" fill="url(#vig)"/>
</svg>"""


def render(svg: pathlib.Path, png: pathlib.Path, w: int, h: int) -> None:
    exe = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not exe:
        raise RuntimeError("Chromium is required to rasterise brand assets")
    page = svg.with_suffix(".render.html")
    page.write_text(f'<!doctype html><style>html,body{{margin:0;background:transparent}}'
                    f'img{{display:block;width:{w}px;height:{h}px}}</style><img src="{svg.name}">')
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as prof:
            subprocess.run([exe, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}",
                            f"--window-size={w},{h}", "--hide-scrollbars", "--default-background-color=00000000",
                            "--virtual-time-budget=2000", f"--screenshot={png}", page.as_uri()],
                           capture_output=True, timeout=60, check=True)
    finally:
        page.unlink(missing_ok=True)
    print("wrote", png.relative_to(ROOT) if png.is_relative_to(ROOT) else png.name)


def main() -> None:
    out = {
        "corkbored-mark.svg": flat_mark(),
        "corkbored-header.svg": header(),
        "corkbored-light.svg": lockup(INK),
        "corkbored-dark.svg": lockup(PAPER),
        "corkbored-banner.svg": banner(),
    }
    for name, svg in out.items():
        (BRAND / name).write_text(svg)
        print("wrote", (BRAND / name).relative_to(ROOT))
    shutil.copyfile(HERE / "corkbored-icon.svg", BRAND / "corkbored-icon.svg")
    for size in (1024, 256):
        render(BRAND / "corkbored-icon.svg", BRAND / f"corkbored-icon-{size}.png", size, size)
    render(BRAND / "corkbored-mark.svg", BRAND / "corkbored-mark-64.png", 64, 64)
    render(BRAND / "corkbored-banner.svg", BRAND / "corkbored-banner.png", 1280, 640)
    render(BRAND / "corkbored-light.svg", BRAND / "corkbored-light.png", 560, 128)
    render(BRAND / "corkbored-dark.svg", BRAND / "corkbored-dark.png", 560, 128)
    render(BRAND / "corkbored-header.svg", BRAND / "corkbored-header.png", 400, 80)
    static = ROOT / "static/brand"
    static.mkdir(exist_ok=True)
    from PIL import Image
    with Image.open(BRAND / "corkbored-icon-1024.png") as icon:
        icon.resize((128, 128), Image.Resampling.LANCZOS).save(static / "corkbored-icon-128.png")
    # Scene assets: the flat mark, and a cork board baked to JPEG (noise filters
    # are too slow to run per frame).
    for name in ("corkbored-mark.svg", "corkbored-icon.svg", "corkbored-header.svg"):
        shutil.copyfile(BRAND / name, static / name)
    board = static / "cork-1920.svg"
    board.write_text(cork_board(2112, 1188))     # 10% larger, room for a slow push-in
    render(board, static / "cork-1920.png", 2112, 1188)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(static / "cork-1920.png"),
                    "-q:v", "3", str(static / "cork-1920.jpg")], check=True)
    board.unlink()
    (static / "cork-1920.png").unlink()
    print("wrote static/brand/cork-1920.jpg")


if __name__ == "__main__":
    main()

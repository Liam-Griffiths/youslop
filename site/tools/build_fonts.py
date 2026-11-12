"""Subset the bundled OFL faces into small Latin WOFF2 files for the site.

Run from the repo root (fontTools stays out of the app's .venv):
    uv run --with fonttools --with brotli python site/tools/build_fonts.py

Archivo is pinned to the wordmark instance (width 62, weight 800), so the page
loads one static face instead of the 650 KB variable font.
"""
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'resources' / 'fonts'
OUT = ROOT / 'site' / 'public' / 'fonts'
# Basic Latin, Latin-1, general punctuation, arrows used in copy, the × sign.
UNICODES = [*range(0x20, 0x7F), *range(0xA0, 0x100), *range(0x2010, 0x2028),
            0x2030, 0x2039, 0x203A, 0x2190, 0x2192, 0x2193, 0x00D7, 0x2026, 0x20AC]


def save_subset(font: TTFont, name: str, unicodes=None) -> None:
    options = subset.Options()
    options.flavor = 'woff2'
    options.layout_features = ['kern', 'liga', 'calt', 'tnum', 'case']
    options.name_IDs = ['*']
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=unicodes or UNICODES)
    sub.subset(font)
    path = OUT / name
    font.flavor = 'woff2'
    font.save(path)
    print(f'{name}: {path.stat().st_size / 1024:.1f} KB')


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    archivo = instancer.instantiateVariableFont(
        TTFont(SRC / 'Archivo-Variable.ttf'), {'wdth': 62, 'wght': 800})
    save_subset(archivo, 'archivo-condensed-800.woff2')
    for src, name in (('Inter-Medium.ttf', 'inter-500.woff2'),
                      ('Inter-Bold.ttf', 'inter-700.woff2')):
        save_subset(TTFont(SRC / src), name)
    # Mono only sets small uppercase labels and figures.
    mono = TTFont(SRC / 'JetBrainsMono-Regular.ttf')
    save_subset(mono, 'jetbrains-mono-400.woff2', [*range(0x20, 0x60), 0xB7, 0x2013, 0x2014, 0x2192])


if __name__ == '__main__':
    main()

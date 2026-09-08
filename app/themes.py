"""Themes: what kind of channel this is, expressed as colour, icons and picks.

The house look started as one accent colour on black, which suits a history
channel and nothing else. A gaming channel is two loud colours on a third; a
beauty channel is printed on cream; a sports channel is a flag. So a theme
carries four colours rather than one, a set of icons the patterns are built
from, and the slate, thumbnail and end screen that were designed together.

A theme is a starting point, not a cage. Applying one writes its two colours
into the channel's style — after that they are the channel's colours and can be
edited freely — and offers its three template picks, which can be taken or
ignored. Everything a template needs is resolved through `palette()`, so a
channel that has drifted from its theme still gets a coherent set of colours.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------- themes
# `ground` and `ink` are what the colourful templates paint on and in; `accent`
# and `accent2` are copied into the channel's style when the theme is applied.
# `pattern` is what a template reaches for when it wants to fill a flat area.
THEMES = [
    {
        "key": "archive", "label": "Archive", "for": "History, biography, essays",
        "blurb": "Warm gold on black, and the restraint the rest of these do not "
                 "have. The default, and what every channel made before themes "
                 "existed already looks like.",
        "accent": "#E8C36A", "accent2": "#7FA6B8",
        "ground": "#0A0B0E", "ink": "#FFFFFF", "grade": "warm",
        "icons": ["column", "laurel", "hourglass", "quill", "key"],
        "pattern": "icons", "light": False,
        "intro": "columns", "thumb": "banner", "outro": "twoup",
    },
    {
        "key": "arcade", "label": "Arcade", "for": "Gaming, streaming, tech culture",
        "blurb": "Hot pink and cyan over deep violet, with a field of controllers "
                 "and pixel hearts behind everything. The loudest theme here.",
        "accent": "#FF3D81", "accent2": "#3DFFDC",
        "ground": "#140A2E", "ink": "#FFFFFF", "grade": "cool",
        "icons": ["controller", "dpad", "pixel_heart", "star4", "bolt"],
        "pattern": "icons", "light": False,
        "intro": "arcade", "thumb": "sticker", "outro": "arcade",
    },
    {
        "key": "gloss", "label": "Gloss", "for": "Beauty, makeup, skincare, fashion",
        "blurb": "Blush and rose printed on a soft gradient, scattered with "
                 "sparkles and droplets. The only theme that runs light.",
        "accent": "#D9698C", "accent2": "#F6C6A8",
        "ground": "#FBE9EF", "ink": "#3A2A31", "grade": "warm",
        "icons": ["sparkle", "droplet", "bow", "lipstick", "compact", "brush"],
        "pattern": "icons", "light": True,
        "intro": "gloss", "thumb": "gloss", "outro": "gloss",
    },
    {
        "key": "kickoff", "label": "Kickoff", "for": "Sports, fitness, competition",
        "blurb": "Electric green cut across navy on the diagonal, condensed "
                 "italics, and a number big enough to read across a stadium.",
        "accent": "#00E07A", "accent2": "#FFFFFF",
        "ground": "#0B2545", "ink": "#FFFFFF", "grade": "cool",
        "icons": ["ball", "whistle", "trophy", "flag", "stopwatch"],
        "pattern": "stripes", "light": False,
        "intro": "kickoff", "thumb": "scoreline", "outro": "sideline",
    },
    {
        "key": "amp", "label": "Amp", "for": "Music, podcasts, interviews",
        "blurb": "Orange into magenta, and the channel name repeated across the "
                 "frame as its own wallpaper. Built around type, not pictures.",
        "accent": "#FF8A3D", "accent2": "#FF2E63",
        "ground": "#12070E", "ink": "#FFFFFF", "grade": "warm",
        "icons": ["note", "beam", "wave", "disc", "mic", "speaker"],
        "pattern": "words", "light": False,
        "intro": "stack", "thumb": "duotone", "outro": "wordmark",
    },
    {
        "key": "terminal", "label": "Terminal", "for": "Technology, science, explainers",
        "blurb": "Signal green on near-black, mono type and a circuit field. "
                 "The technical one, and the quietest of the loud ones.",
        "accent": "#4FD1C5", "accent2": "#A3F7BF",
        "ground": "#080A0C", "ink": "#FFFFFF", "grade": "cool",
        "icons": ["chip", "cursor", "bolt", "plus", "ring", "globe"],
        "pattern": "icons", "light": False,
        "intro": "signal", "thumb": "split", "outro": "console",
    },
    {
        "key": "kitchen", "label": "Kitchen", "for": "Food, craft, making things",
        "blurb": "Tomato and olive on warm paper, with pots and leaves tiled "
                 "behind. Reads as a recipe card before a word of it is legible.",
        "accent": "#D9482B", "accent2": "#6E8C3A",
        "ground": "#F4EAD8", "ink": "#2E241C", "grade": "warm",
        "icons": ["pot", "leaf", "droplet", "plus", "camera"],
        "pattern": "icons", "light": True,
        "intro": "tiles", "thumb": "tiles", "outro": "ledger",
    },
    {
        "key": "broadcast", "label": "Broadcast", "for": "News, analysis, current affairs",
        "blurb": "Alert red on graphite with a halftone screen and a hard "
                 "horizontal. Urgent without being a tabloid about it.",
        "accent": "#E5334C", "accent2": "#F2F4F8",
        "ground": "#15181E", "ink": "#FFFFFF", "grade": "neutral",
        "icons": ["globe", "chevron", "triangle", "ring", "bolt"],
        "pattern": "halftone", "light": False,
        "intro": "kickoff", "thumb": "duotone", "outro": "marquee",
    },
]
THEME_KEYS = [t["key"] for t in THEMES]
DEFAULT = "archive"


def theme(key: str) -> dict:
    for t in THEMES:
        if t["key"] == key:
            return t
    return THEMES[0]


@dataclass
class Palette:
    """Everything a colourful template needs, resolved for one channel.

    The two accents come from the channel's own style, because applying a theme
    copies them there and the creator may have moved them since. The ground, the
    ink and the icons come from the theme, which is the part there is no
    interface for and no reason to diverge from.
    """
    key: str
    accent: tuple[int, int, int, int]
    accent2: tuple[int, int, int, int]
    ground: tuple[int, int, int, int]
    ink: tuple[int, int, int, int]
    icons: list[str]
    pattern: str
    light: bool

    @property
    def duo(self) -> list:
        return [self.accent, self.accent2]


def palette(style) -> Palette:
    """Resolve a Style into the colours and icons the templates draw with."""
    from . import titles

    t = theme(getattr(style, "theme", DEFAULT) or DEFAULT)
    accent = titles._hex(getattr(style, "accent", "") or t["accent"])
    second = getattr(style, "accent2", "") or t["accent2"]
    return Palette(
        key=t["key"],
        accent=accent,
        accent2=titles._hex(second),
        ground=titles._hex(t["ground"]),
        ink=titles._hex(t["ink"]),
        icons=list(t["icons"]),
        pattern=t["pattern"],
        light=bool(t["light"]),
    )


def apply_to_style(style, key: str, take_templates: bool = True) -> dict:
    """Write a theme onto a Style. Returns the template picks it suggests."""
    t = theme(key)
    style.theme = t["key"]
    style.accent = t["accent"]
    style.accent2 = t["accent2"]
    style.grade = t["grade"]
    if not take_templates:
        return {}
    return {"intro": t["intro"], "thumb": t["thumb"], "outro": t["outro"]}
